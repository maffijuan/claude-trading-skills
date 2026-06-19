#!/usr/bin/env python3
"""Tests for the After-Hours Market Screener (offline; no API key required)."""

import json
import tempfile
from pathlib import Path

import classifier
import report_generator
import scan_after_hours as scan

# ---------------------------------------------------------------------------
# normalize_records
# ---------------------------------------------------------------------------


def test_normalize_computes_change_from_prices():
    recs = scan.normalize_records([{"symbol": "abc", "regular_close": 100, "ah_price": 110}])
    assert len(recs) == 1
    assert recs[0]["symbol"] == "ABC"
    assert recs[0]["ah_change_pct"] == 10.0


def test_normalize_keeps_explicit_change_and_drops_unusable():
    recs = scan.normalize_records(
        [
            {"symbol": "X", "ah_change_pct": -7.5},
            {"symbol": "", "ah_change_pct": 5},  # no symbol -> dropped
            {"symbol": "Y"},  # no price/move -> dropped
        ]
    )
    assert [r["symbol"] for r in recs] == ["X"]
    assert recs[0]["ah_change_pct"] == -7.5


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


def test_earnings_gap_up_routes_to_earnings_skills():
    rec = {
        "symbol": "NVDA",
        "ah_change_pct": 10.5,
        "has_earnings": True,
        "earnings_time": "amc",
        "eps": 0.78,
        "eps_estimate": 0.64,
        "market_cap": 3e12,
    }
    out = classifier.classify_record(rec)
    assert out["category"] == "EARNINGS_GAP_UP"
    assert out["direction"] == "up"
    assert "earnings-trade-analyzer" in out["routes"]
    assert out["earnings_surprise_pct"] is not None and out["earnings_surprise_pct"] > 0


def test_earnings_gap_down_routes_to_scenario_and_short():
    rec = {
        "symbol": "SNAP",
        "ah_change_pct": -17.0,
        "has_earnings": True,
        "eps": -0.02,
        "eps_estimate": 0.05,
        "market_cap": 1.8e10,
    }
    out = classifier.classify_record(rec)
    assert out["category"] == "EARNINGS_GAP_DOWN"
    assert "scenario-analyzer" in out["routes"]
    assert out["earnings_surprise_pct"] < 0


def test_news_gap_without_earnings():
    rec = {"symbol": "ACME", "ah_change_pct": 60.0, "has_earnings": False, "market_cap": 5e8}
    out = classifier.classify_record(rec)
    assert out["category"] == "NEWS_GAP_UP"
    assert "market-news-analyst" in out["routes"]


def test_parabolic_overlay_adds_short_route():
    rec = {"symbol": "ACME", "ah_change_pct": 60.0, "has_earnings": False, "market_cap": 5e8}
    out = classifier.classify_record(rec)
    assert "parabolic-short-trade-planner" in out["routes"]
    assert out["urgency"] == "HIGH"


def test_inline_earnings_below_threshold():
    rec = {
        "symbol": "KO",
        "ah_change_pct": 0.6,
        "has_earnings": True,
        "eps": 0.72,
        "eps_estimate": 0.71,
    }
    out = classifier.classify_record(rec)
    assert out["category"] == "EARNINGS_INLINE"
    assert out["direction"] == "flat"


def test_quiet_filtered_by_default():
    recs = [{"symbol": "ZZ", "ah_change_pct": 0.2, "has_earnings": False}]
    norm = scan.normalize_records(recs)
    classified = classifier.classify_all(norm)
    assert classified == []
    classified_incl = classifier.classify_all(norm, include_quiet=True)
    assert classified_incl[0]["category"] == "QUIET"


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def test_score_bounds_and_ordering():
    big = {
        "symbol": "A",
        "ah_change_pct": 25.0,
        "ah_volume": 2_000_000,
        "market_cap": 5e10,
        "has_earnings": True,
        "eps": 1,
        "eps_estimate": 0.5,
    }
    small = {"symbol": "B", "ah_change_pct": 5.1, "ah_volume": 0, "market_cap": 1e8}
    sbig = classifier.score_record(big)
    ssmall = classifier.score_record(small)
    assert 0 <= ssmall <= sbig <= 100
    assert sbig > ssmall


def test_surprise_none_when_estimate_zero_or_missing():
    assert classifier.earnings_surprise_pct({"eps": 1.0, "eps_estimate": 0}) is None
    assert classifier.earnings_surprise_pct({"eps": 1.0}) is None


# ---------------------------------------------------------------------------
# summary + end-to-end
# ---------------------------------------------------------------------------


def test_session_summary_breadth():
    recs = scan.normalize_records(
        [
            {"symbol": "A", "ah_change_pct": 10, "has_earnings": True},
            {"symbol": "B", "ah_change_pct": 12, "has_earnings": True},
            {"symbol": "C", "ah_change_pct": 9, "has_earnings": False},
            {"symbol": "D", "ah_change_pct": 8, "has_earnings": False},
            {"symbol": "E", "ah_change_pct": -11, "has_earnings": True},
        ]
    )
    summary = classifier.session_summary(classifier.classify_all(recs))
    assert summary["total_movers"] == 5
    assert summary["gainers"] == 4
    assert summary["losers"] == 1
    assert summary["net_breadth"] == 3
    assert "risk-on" in summary["tone"]


def _args(**kw):
    parser = scan.build_parser()
    defaults = parser.parse_args(["--dry-run"])
    for k, v in kw.items():
        setattr(defaults, k, v)
    return defaults


def test_dry_run_end_to_end_and_report_writes():
    report = scan.run(_args())
    assert report["schema_version"] == "1.0"
    assert report["summary"]["total_movers"] >= 4
    # The three genuine big movers (SNAP -17%, ACME +60%, NVDA +10.5%) should
    # top the ranking ahead of the muted/in-line names (KO, MSFT).
    top3 = [m["symbol"] for m in report["movers"][:3]]
    assert report["movers"][0]["symbol"] == "SNAP"
    assert set(top3) == {"SNAP", "ACME", "NVDA"}

    md = report_generator.generate_markdown(report)
    assert "After-Hours Market Screener" in md
    assert "NVDA" in md

    with tempfile.TemporaryDirectory() as d:
        jpath, mpath = report_generator.write_reports(report, d, report["as_of_date"])
        assert Path(jpath).exists() and Path(mpath).exists()
        loaded = json.loads(Path(jpath).read_text())
        assert loaded["skill"] == "after-hours-market-screener"


def test_earnings_only_filter():
    report = scan.run(_args(earnings_only=True))
    assert all(m["has_earnings"] for m in report["movers"])


def test_min_cap_filter_drops_microcaps():
    report = scan.run(_args(min_cap=1e9))
    assert all((m.get("market_cap") or 0) >= 1e9 for m in report["movers"])
    assert "ACME" not in [m["symbol"] for m in report["movers"]]


# ---------------------------------------------------------------------------
# yfinance free source (mocked — no network)
# ---------------------------------------------------------------------------

import ah_yf_source  # noqa: E402


class _FakeTicker:
    def __init__(self, info):
        self._info = info

    def get_info(self):
        return self._info


def test_yf_source_computes_postmarket_move():
    fake = {
        "AAPL": {
            "shortName": "Apple Inc",
            "regularMarketPrice": 200.0,
            "postMarketPrice": 210.0,
            "marketCap": 3e12,
            "sector": "Technology",
        },
        "NOPM": {"regularMarketPrice": 50.0},  # no post-market -> skipped
    }
    recs = ah_yf_source.fetch_yf_records(
        ["AAPL", "NOPM"], as_of="2026-06-19", ticker_factory=lambda s: _FakeTicker(fake[s])
    )
    assert len(recs) == 1
    assert recs[0]["symbol"] == "AAPL"
    assert recs[0]["ah_change_pct"] == 5.0
    assert recs[0]["market_cap"] == 3e12


def test_yf_source_skips_failing_symbol():
    def boom(_sym):
        raise RuntimeError("Yahoo blocked")

    recs = ah_yf_source.fetch_yf_records(["X"], as_of="2026-06-19", ticker_factory=boom)
    assert recs == []


def test_yf_source_infers_earnings_today_from_timestamp():
    import datetime as _dt
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    ts = int(_dt.datetime(2026, 6, 19, 16, 30, tzinfo=et).timestamp())
    fake = {
        "regularMarketPrice": 100.0,
        "postMarketPrice": 92.0,
        "earningsTimestamp": ts,
    }
    recs = ah_yf_source.fetch_yf_records(
        ["ZZ"], as_of="2026-06-19", ticker_factory=lambda s: _FakeTicker(fake)
    )
    assert recs[0]["has_earnings"] is True
    assert recs[0]["earnings_time"] == "amc"


def test_load_watchlist_strips_comments(tmp_path):
    f = tmp_path / "wl.txt"
    f.write_text("# header\nAAPL\n  msft  # inline\n\nNVDA\n", encoding="utf-8")
    assert ah_yf_source.load_watchlist(str(f)) == ["AAPL", "MSFT", "NVDA"]


def test_default_watchlist_file_exists_and_parses():
    symbols = ah_yf_source.load_watchlist(str(scan.DEFAULT_WATCHLIST))
    assert "NVDA" in symbols and "SPY" in symbols
    assert len(symbols) >= 30
