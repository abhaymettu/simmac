import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

from tests.helpers import APP_COUNT, Running


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def post(url, body):
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_json(self):
        with Running(self.tmp.name) as s:
            status, ctype, body = get(s.url + "/api/snapshot")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        snap = json.loads(body)
        self.assertEqual(set(snap), {"t", "hour", "ncpu", "load", "cpu", "mem", "net", "procs", "apps"})
        self.assertEqual(len(snap["apps"]), APP_COUNT)
        self.assertEqual(snap["procs"], APP_COUNT)
        self.assertEqual(snap["apps"][0]["name"], "tool11")

    def test_serves_the_page(self):
        with Running(self.tmp.name) as s:
            status, ctype, body = get(s.url + "/")
            js_status, _, js = get(s.url + "/city.js")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b'<script src="city.js">', body)
        self.assertEqual(js_status, 200)
        self.assertIn(b"api/snapshot", js)

    def test_clip_upload_is_saved(self):
        with Running(self.tmp.name) as s:
            status, body = post(s.url + "/api/clip", b"\x1aE\xdf\xa3fake-webm")
        self.assertEqual(status, 200)
        with open(os.path.join(self.tmp.name, "clip.webm"), "rb") as f:
            self.assertEqual(f.read(), b"\x1aE\xdf\xa3fake-webm")
        self.assertEqual(body["bytes"], 13)

    def test_render_report_and_errors(self):
        with Running(self.tmp.name) as s:
            ok = post(s.url + "/api/rendered", b'{"buildings": 3}')
            bad = post(s.url + "/api/rendered", b"not json")
            missing = post(s.url + "/api/nope", b"x")
            reports = s.httpd.state.rendered
        self.assertEqual(ok[0], 200)
        self.assertEqual(bad[0], 400)
        self.assertEqual(missing[0], 404)
        self.assertEqual(reports, [{"buildings": 3}])

    def test_binds_to_localhost_only(self):
        with Running(self.tmp.name) as s:
            self.assertEqual(s.httpd.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
