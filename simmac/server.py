"""Local web server: the static page plus a JSON snapshot of this Mac.

Binds to 127.0.0.1 only. The page polls /api/snapshot. In record mode the page
posts its finished clip to /api/clip, and every page posts a short render
report to /api/rendered so the smoke test can check what was drawn.
"""
import argparse
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from .city import Sampler
from .sources import Raw, read_raw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
MAX_CLIP_BYTES = 200 * 2 ** 20


class State:
    def __init__(self, reader: Callable[[], Raw], out_dir: str, min_interval: float = 1.0):
        self.reader = reader
        self.out_dir = out_dir
        self.min_interval = min_interval
        self.sampler = Sampler()
        self.lock = threading.Lock()
        self.cached: Optional[dict] = None
        self.cached_at = 0.0
        self.rendered: list = []

    def snapshot(self) -> dict:
        with self.lock:
            now = time.time()
            if self.cached is None or now - self.cached_at >= self.min_interval:
                self.cached = self.sampler.snapshot(self.reader(), now)
                self.cached_at = now
            return self.cached


def make_handler(state: State):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=STATIC, **kw)

        def log_message(self, *a):
            pass

        def _json(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.split("?")[0] == "/api/snapshot":
                return self._json(200, state.snapshot())
            return super().do_GET()

        def do_POST(self):
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_CLIP_BYTES:
                return self._json(413, {"error": "body must be 1 byte to 200 MB"})
            body = self.rfile.read(length)
            if path == "/api/clip":
                os.makedirs(state.out_dir, exist_ok=True)
                dest = os.path.join(state.out_dir, "clip.webm")
                with open(dest + ".part", "wb") as f:
                    f.write(body)
                os.replace(dest + ".part", dest)
                return self._json(200, {"saved": dest, "bytes": len(body)})
            if path == "/api/rendered":
                try:
                    state.rendered.append(json.loads(body))
                except ValueError:
                    return self._json(400, {"error": "render report must be JSON"})
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "unknown endpoint"})

    return Handler


def serve(port: int = 8817, out_dir: Optional[str] = None,
          reader: Callable[[], Raw] = read_raw) -> ThreadingHTTPServer:
    state = State(reader, out_dir or os.path.join(ROOT, "out"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    httpd.state = state  # type: ignore[attr-defined]
    return httpd


def main():
    ap = argparse.ArgumentParser(description="Serve SimMac on this machine only.")
    ap.add_argument("--port", type=int, default=8817)
    args = ap.parse_args()
    httpd = serve(args.port)
    print("SimMac running at http://127.0.0.1:%d/" % httpd.server_address[1], flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
