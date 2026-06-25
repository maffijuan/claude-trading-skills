"""Desktop launcher: start the Flask UI and open the browser when it's ready.

Double-clicking the desktop shortcut (or "Start Market Screener.bat") runs this.
It boots the same server as ``app.py`` and opens http://127.0.0.1:5000 in the
default browser once the port is actually responding (so the first page load never
fails with "connection refused"). Close the console window to stop the server.
"""

from __future__ import annotations

import threading
import time
import urllib.request
import webbrowser

import app as flaskapp

URL = "http://127.0.0.1:5000/"


def _open_when_up():
    for _ in range(60):  # up to ~15s for the server to come up
        try:
            urllib.request.urlopen(URL, timeout=1)
            break
        except Exception:  # noqa: BLE001 - not up yet, keep polling
            time.sleep(0.25)
    webbrowser.open(URL)


if __name__ == "__main__":
    print("=" * 56)
    print(" US Market Screener")
    print(" Opening", URL, "in your browser...")
    print(" Keep this window open while you use it.")
    print(" Close this window to stop the screener.")
    print("=" * 56)
    threading.Thread(target=_open_when_up, daemon=True).start()
    # Reloader off so there's a single process tied to this console window.
    flaskapp.app.run(host="127.0.0.1", port=5000, debug=False,
                     threaded=True, use_reloader=False)
