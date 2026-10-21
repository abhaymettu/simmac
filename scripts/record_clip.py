"""Record a clip of this Mac's live city.

Starts SimMac on a free local port with real system data, opens the page in
headless Chrome in record mode, waits for the page to upload its WebM, then
converts it to MP4 with ffmpeg and saves a poster frame.

    python3 scripts/record_clip.py --seconds 20 --out media
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simmac.chrome import NO_THROTTLE, stop_chrome  # noqa: E402
from simmac.server import serve  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--out", default="media")
    ap.add_argument("--query", default="", help="extra page options, for example hour=13")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        httpd = serve(port=0, out_dir=tmp)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/?record=%d" % (httpd.server_address[1], args.seconds)
        if args.query:
            url += "&" + args.query
        chrome = subprocess.Popen([CHROME, "--headless=new", "--window-size=1280,720"] + NO_THROTTLE + [ "--hide-scrollbars",
                                   "--user-data-dir=" + os.path.join(tmp, "profile"), url],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
        webm = os.path.join(tmp, "clip.webm")
        deadline = time.time() + args.seconds + 60
        try:
            while time.time() < deadline and not os.path.exists(webm):
                time.sleep(0.5)
        finally:
            stop_chrome(chrome)
            httpd.shutdown()
        if not os.path.exists(webm):
            sys.exit("The page never uploaded a clip.")
        name = "simmac-%ds" % args.seconds + ("-" + args.query.replace("=", "") if args.query else "")
        keep_webm = os.path.join(args.out, name + ".webm")
        shutil.copy(webm, keep_webm)
        mp4 = os.path.join(args.out, name + ".mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", "-crf", "20", "-r", "30", "-movflags", "+faststart", mp4], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(args.seconds / 2), "-i", mp4,
                        "-frames:v", "1", os.path.join(args.out, name + "-poster.png")], check=True)
        print(mp4)


if __name__ == "__main__":
    main()
