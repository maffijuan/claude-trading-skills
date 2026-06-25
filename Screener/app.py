"""Flask server for the dashboard + live screening.

Run:
    python app.py            # -> http://127.0.0.1:5000

Endpoints:
    GET  /                    self-contained dashboard (with live buttons wired)
    GET  /api/results         current results.json
    GET  /api/status          live run status {running, processed, total, current}
    POST /api/screen          start a run: {"mode":"all"} or
                              {"mode":"tickers","tickers":["AAPL","MSFT"]}

Screening runs in a background thread so the page stays responsive and can poll
progress. Only one run at a time. No LLM calls; only yfinance for data (via screener).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, request

import config as C
import dashboard
import screener
from universe import build_universe

ROOT = Path(__file__).resolve().parent
RESULTS_JSON = ROOT / "output" / "results.json"

app = Flask(__name__)

# ---- shared run state (single background run at a time) -------------------- #
_lock = threading.Lock()
STATE = {
    "running": False,
    "processed": 0,
    "total": 0,
    "current": "",
    "last_label": "",
    "mode": "",
    "error": "",
}


def _progress(done, total, symbol, result):
    STATE["processed"] = done
    STATE["total"] = total
    STATE["current"] = symbol
    if result:
        STATE["last_label"] = result.get("label", "")


def _run_job(symbols, mode):
    try:
        STATE.update(running=True, processed=0, total=len(symbols),
                     current="", mode=mode, error="")
        screener.run(symbols, resume=False, flush_every=10,
                     regen_dashboard=True, progress_cb=_progress)
    except Exception as exc:  # noqa: BLE001
        STATE["error"] = str(exc)
    finally:
        STATE["running"] = False
        STATE["current"] = ""


@app.route("/")
def index() -> Response:
    payload = (json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
               if RESULTS_JSON.exists() else {"meta": {}, "results": []})
    return Response(dashboard._render(payload), mimetype="text/html")


@app.route("/api/results")
def api_results():
    if not RESULTS_JSON.exists():
        return jsonify({"meta": {}, "results": []})
    return jsonify(json.loads(RESULTS_JSON.read_text(encoding="utf-8")))


@app.route("/api/status")
def api_status():
    return jsonify(STATE)


@app.route("/api/screen", methods=["POST"])
def api_screen():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "tickers")

    with _lock:
        if STATE["running"]:
            return jsonify({"started": False, "reason": "a run is already in progress"}), 409

        if mode == "all":
            limit = int(body.get("limit", 2000))
            symbols = build_universe(limit=limit)
        else:
            tickers = body.get("tickers") or []
            symbols = [str(t).upper().strip() for t in tickers if str(t).strip()]
            if not symbols:
                return jsonify({"started": False, "reason": "no tickers provided"}), 400

        t = threading.Thread(target=_run_job, args=(symbols, mode), daemon=True)
        t.start()

    return jsonify({"started": True, "mode": mode, "count": len(symbols)})


if __name__ == "__main__":
    print("Market Screener UI -> http://127.0.0.1:5000")
    # threaded=True so /api/status polling works while a run thread is active.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
