import os
import signal
import subprocess

# Keep timers and animation frames running in a headless window nobody looks at.
NO_THROTTLE = ["--disable-renderer-backgrounding", "--disable-background-timer-throttling",
               "--disable-backgrounding-occluded-windows", "--no-first-run", "--no-default-browser-check"]


def stop_chrome(proc):
    """Stop a Chrome we started in its own session, with all its helper processes."""
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue
