"""Interactive fundamental-analysis dashboard.

A thin Flask server on top of ``financial_analysis.py``:

  * single ticker  -> full analysis (statements grouped by source + ratios with
    BUY / HOLD / SELL recommendations + Excel download);
  * batch / universe -> one compact row per ticker (last-period ratios coloured
    by recommendation), no raw annual data.

Run:
    python analyses/dashboard/app.py           # then open http://127.0.0.1:5000
    python analyses/dashboard/app.py --port 8000 --open
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

# make financial_analysis.py importable
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import financial_analysis as fa  # noqa: E402
from indices import INDEX_LABELS, INDICES  # noqa: E402
from peers import sector_peers, sector_of  # noqa: E402

app = Flask(__name__)
app.json.sort_keys = False   # preserve statement / field order in JSON responses

# Optional password gate for a deployed URL: set DASH_PASSWORD in the host's env
# to require HTTP Basic auth (any username, that password). Unset -> open access.
_DASH_PASSWORD = os.environ.get("DASH_PASSWORD")


@app.before_request
def _require_auth():
    if not _DASH_PASSWORD:
        return None
    auth = request.authorization
    if not auth or auth.password != _DASH_PASSWORD:
        return Response("Acceso restringido.", 401,
                        {"WWW-Authenticate": 'Basic realm="Fundamental Analyzer"'})
    return None


def _parse_list(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = str(raw).replace("\n", ",").split(",")
    return [str(t).strip().upper() for t in items if str(t).strip()]


def _peer_medians(peers: list[str], years: int, method: str) -> dict:
    return fa.compute_peer_medians(peers, years, method) if peers else {}


@app.route("/")
def index():
    counts = {k: len(v) for k, v in INDICES.items()}
    return render_template("index.html", indices=INDEX_LABELS, counts=counts)


@app.route("/api/analyze")
def api_analyze():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "no ticker"}), 400
    years = int(request.args.get("years", 3))
    method = request.args.get("method", "runrate")
    trefis = request.args.get("trefis", "false").lower() == "true"
    auto_peers = request.args.get("auto_peers", "true").lower() == "true"
    peers = _parse_list(request.args.get("peers"))
    peer_source = "manual" if peers else ""
    try:
        if not peers and auto_peers:
            peers = sector_peers(ticker, n=8)
            peer_source = f"sector S&P: {sector_of(ticker)}" if peers else "sin peers"
        pm = _peer_medians([p for p in peers if p != ticker], years, method)
        data = fa.analyze_to_dict(ticker, years=years, partial_method=method,
                                  peer_median=pm, with_trefis=trefis)
        data["peers"] = peers
        data["peer_source"] = peer_source
        return jsonify(data)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/batch", methods=["POST"])
def api_batch():
    body = request.get_json(force=True) or {}
    tickers = _parse_list(body.get("tickers"))[:520]     # safety cap (fits S&P 500)
    if not tickers:
        return jsonify({"error": "no tickers"}), 400
    try:
        data = fa.build_batch(
            tickers, years=int(body.get("years", 3)),
            partial_method=body.get("method", "runrate"),
            peers=_parse_list(body.get("peers")),
            self_peer=bool(body.get("self_peer", True)))
        return jsonify(data)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/excel")
def api_excel():
    tickers = _parse_list(request.args.get("ticker"))
    if not tickers:
        return jsonify({"error": "no ticker"}), 400
    years = int(request.args.get("years", 3))
    method = request.args.get("method", "runrate")
    peers = _parse_list(request.args.get("peers"))
    trefis = request.args.get("trefis", "false").lower() == "true"
    tmp = Path(tempfile.gettempdir()) / f"Analisis_{'_'.join(tickers)}.xlsx"
    fa.build_workbook(tickers, years, str(tmp), partial_method=method,
                      peers=peers or None, with_trefis=trefis)
    return send_file(tmp, as_attachment=True, download_name=tmp.name)


@app.route("/api/universe/<name>")
def api_universe(name):
    return jsonify({"tickers": INDICES.get(name, [])})


def main():
    p = argparse.ArgumentParser(description="Fundamental-analysis dashboard server.")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--open", action="store_true", help="open the browser on start")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard on {url}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(url)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
