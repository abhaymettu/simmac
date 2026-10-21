import threading

from simmac.server import serve
from simmac.sources import Proc, Raw

APP_COUNT = 12


def fake_raw():
    procs = []
    for i in range(APP_COUNT):
        cmd = "/Applications/App%02d.app/Contents/MacOS/App%02d" % (i, i) if i < 6 else "tool%02d" % i
        procs.append(Proc(100 + i, 1, float(5 * i), 0.5, 1024 * (50 + 120 * i), cmd))
    return Raw(procs=procs, vm={"active": 2 ** 32, "wired": 2 ** 31, "compressed": 0},
               net_rx=10 ** 9, net_tx=10 ** 8, load=[2.0, 1.5, 1.0], ncpu=8, mem_total=16 * 2 ** 30)


class Running:
    """Serve on a free port in a background thread for the length of a test."""

    def __init__(self, out_dir, reader=fake_raw):
        self.httpd = serve(port=0, out_dir=out_dir, reader=reader)
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
