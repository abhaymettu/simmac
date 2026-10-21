"""Render smoke test: load the page in headless Chrome against a fake Mac and
check what the page reports it drew, including the pixels on its canvas."""
import base64
import os
import shutil
import struct
import sys
import subprocess
import tempfile
import time
import unittest
import zlib

from simmac.chrome import NO_THROTTLE, stop_chrome
from tests.helpers import APP_COUNT, Running

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]
CHROME = next((p for p in CHROME_PATHS if p and os.path.exists(p)), None)


def png_colors(path):
    """Count distinct colors in an 8-bit RGB or RGBA PNG using only the stdlib."""
    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h, ctype = 8, b"", 0, 0, 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8 and ctype in (2, 6)
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    bpp = 4 if ctype == 6 else 3
    raw, stride = zlib.decompress(idat), w * bpp
    prev, colors, i = bytearray(stride), set(), 0
    for _ in range(h):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], prev[x - bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        for x in range(0, stride, bpp * 7):
            colors.add(bytes(line[x:x + 3]))
        prev = line
    return w, h, len(colors)


@unittest.skipIf(CHROME is None, "Chrome is not installed")
class RenderSmokeTest(unittest.TestCase):
    def render(self, query):
        """Open the page in real-time headless Chrome and return its render reports."""
        with tempfile.TemporaryDirectory() as tmp, Running(tmp) as s:
            chrome = subprocess.Popen([CHROME, "--headless=new", "--window-size=1280,720"] + NO_THROTTLE + [
                                       "--user-data-dir=" + os.path.join(tmp, "live"), s.url + "/?" + query],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
            try:
                started = time.time()
                deadline = started + 90
                while time.time() < deadline and not s.httpd.state.rendered:
                    time.sleep(0.2)
            finally:
                stop_chrome(chrome)
            print("render report after %.1fs" % (time.time() - started), file=sys.stderr)
            return list(s.httpd.state.rendered)

    def test_keeps_drawing_without_animation_frames(self):
        # Chrome on macOS can fail to start its display link in a headless
        # window, so animation frames never come. The page must still draw.
        reports = self.render("hour=13&noraf")
        self.assertGreaterEqual(len(reports), 1, "the page stopped drawing without animation frames")
        self.assertEqual(reports[0]["buildings"], APP_COUNT)

    def test_city_renders_every_app_as_a_building(self):
        reports = self.render("hour=13&reportpng")
        self.assertGreaterEqual(len(reports), 1, "the page never reported a render")
        png = reports[0].pop("png", "")
        self.assertTrue(png.startswith("data:image/png;base64,"))
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "shot.png")
            with open(shot, "wb") as f:
                f.write(base64.b64decode(png.split(",", 1)[1]))
            w, h, colors = png_colors(shot)
        r = reports[0]
        self.assertEqual(r["frame"], 60)
        self.assertEqual(r["apps"], APP_COUNT)
        self.assertEqual(r["buildings"], APP_COUNT)
        self.assertGreaterEqual(r["cars"], 6)
        self.assertGreater(r["colors"], 20)
        # The view scales the 640x360 city to fit the window, keeping 16:9.
        self.assertGreaterEqual(w, 640)
        self.assertAlmostEqual(w / h, 16 / 9, places=2)
        self.assertGreater(colors, 30)


if __name__ == "__main__":
    unittest.main()
