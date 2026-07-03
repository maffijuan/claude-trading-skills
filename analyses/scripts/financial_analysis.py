"""Systematized fundamental analysis workbook builder.

Reproduces the MSFT / GOOGL / PEP analysis (Income Statement, Balance Sheet,
Cash Flow, Market data and 11 valuation / quality ratios) for any ticker.

Two entry points share one Excel *writer* so both outputs look identical:

  * ``fetch_yfinance(ticker)``  -> pulls the raw line items from Yahoo Finance
    (free, no API key) and returns a normalized ``inputs``/``periods`` payload.
  * ``write_ticker_sheet(...)`` -> lays out one worksheet: data grouped by
    statement, with every derived line and every ratio written as a *live*
    Excel formula so the workbook stays a working model.

CLI:
    python financial_analysis.py MSFT
    python financial_analysis.py AAPL --output analyses/Analisis_AAPL.xlsx
    python financial_analysis.py NVDA GOOGL --years 3

The latest fiscal year may be incomplete. In that case the quarters reported
since the last annual filing are annualized to a *run-rate* (flows are scaled
by 4 / number_of_reported_quarters; balance-sheet stocks and the share count
are taken as-is from the most recent quarter). This mirrors the original
spreadsheet's ``=12/9 * <9-month figure>`` column.
"""

from __future__ import annotations

import argparse
import hashlib
import json as _json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# --------------------------------------------------------------------------- #
# Layout definition
# --------------------------------------------------------------------------- #
# Each line item is either an INPUT (a raw figure) or a FORMULA (a template
# that references other rows by their line-item key, resolved at write time).
# ``fmt`` is an Excel number format string.

CUR = "#,##0"          # currency (thousands/millions as-is)
CUR2 = "#,##0.00"      # price
PCT = "0.0%"           # percentage
PCT2 = "0.00%"         # fine percentage (dividend yield)
MULT = '0.0"x"'        # valuation multiple

INPUT = "input"
FORMULA = "formula"
HEADER = "header"      # section banner row

# --- recommendation templates (return "BUY"/"HOLD"/"SELL"/"") ---------------
# {last} = latest-period cell of the ratio, {peer} = its peer-median cell,
# {price}/{trefis} = latest-period market price / Trefis estimate.
# Valuation multiples are judged RELATIVE to the peer median (cheaper = BUY);
# quality / leverage / growth use absolute thresholds.
REC_MULT = ('=IF(OR({peer}="",NOT(ISNUMBER({last})),{last}<=0),"",'
            'IF({last}<{peer}*0.9,"BUY",IF({last}>{peer}*1.1,"SELL","HOLD")))')
REC_GROWTH = ('=IF(NOT(ISNUMBER({last})),"",'
              'IF({last}>=0.1,"BUY",IF({last}<0,"SELL","HOLD")))')
REC_ROCE = ('=IF(NOT(ISNUMBER({last})),"",'
            'IF({last}>=0.15,"BUY",IF({last}<0.08,"SELL","HOLD")))')
REC_TSR = ('=IF(NOT(ISNUMBER({last})),"",'
           'IF({last}>=0.05,"BUY",IF({last}<0.02,"SELL","HOLD")))')
REC_DY = ('=IF(NOT(ISNUMBER({last})),"",'
          'IF({last}>=0.03,"BUY",IF({last}<0.01,"SELL","HOLD")))')
REC_LEV_ASSETS = ('=IF(NOT(ISNUMBER({last})),"",'
                  'IF({last}<=0.3,"BUY",IF({last}>0.6,"SELL","HOLD")))')
REC_LEV_BOOK = ('=IF(NOT(ISNUMBER({last})),"",'
                'IF({last}<=0.2,"BUY",IF({last}>0.4,"SELL","HOLD")))')
REC_LEV_MKT = ('=IF(NOT(ISNUMBER({last})),"",'
               'IF({last}<=0.15,"BUY",IF({last}>0.4,"SELL","HOLD")))')
REC_UPSIDE = ('=IF(OR({trefis}="",{price}=""),"",'
              'IF({trefis}>{price}*1.1,"BUY",IF({trefis}<{price}*0.9,"SELL","HOLD")))')
REC_ACID = ('=IF(NOT(ISNUMBER({last})),"",'
            'IF({last}>=0.05,"BUY",IF({last}<0.04,"SELL","HOLD")))')


@dataclass
class Row:
    key: str
    label: str
    kind: str = INPUT
    fmt: str = CUR
    # For FORMULA rows: a template using {item} placeholders and {c} for the
    # current column letter, e.g. "={Market price:c}*{Total shares:c}".
    formula: str | None = None
    note: str = ""
    skip_first: bool = False   # leave blank in the first period (needs YoY prior)
    rec: str | None = None     # BUY/HOLD/SELL formula template ({last}/{peer}/{price}/{trefis})
    peer: bool = False         # show a peer-median cell for this ratio


# The order below IS the report order.
LAYOUT: list[Row] = [
    Row("hdr_is", "INCOME STATEMENT", HEADER),
    Row("Revenue", "Revenue"),
    Row("EBITDA", "EBITDA"),
    Row("EBIT", "EBIT (operating income)"),
    Row("Net income", "Net income"),
    Row("D&A", "D&A"),

    Row("hdr_bs", "BALANCE SHEET", HEADER),
    Row("Total assets", "Total assets"),
    Row("Cash & mktb sec.", "Cash & marketable securities"),
    Row("Non-mktb sec.", "Non-marketable securities"),
    Row("Current liabilities", "Current liabilities"),
    Row("Capital employed", "Capital employed", FORMULA,
        formula="={Total assets}-{Cash & mktb sec.}-{Non-mktb sec.}-{Current liabilities}",
        note="Total assets - cash - non-mktb sec. - current liabilities"),
    Row("Stockholders' equity", "Stockholders' equity"),
    Row("Total liabilities", "Total liabilities"),
    Row("Total debt", "Total debt", note="Short-term + long-term interest-bearing debt"),
    Row("Net debt", "Net debt", note="Total debt - cash & equivalents"),
    Row("GW & intangibles", "Goodwill & intangibles", note="For tangible book value (P/TBV)"),

    Row("hdr_cf", "CASH FLOW", HEADER),
    Row("Operating CF", "Operating cash flow"),
    Row("Cash dividend paid", "Cash dividend paid", note="Common dividends paid (outflow, shown positive)"),
    Row("Repurchase of capital stock", "Repurchase of capital stock", note="Buybacks (outflow, shown positive)"),
    Row("CapEx", "CapEx"),
    Row("FCF", "Free cash flow"),

    Row("hdr_mkt", "MARKET DATA", HEADER),
    Row("Total shares", "Total shares (diluted)"),
    Row("Market price", "Market price", INPUT, fmt=CUR2),
    Row("Market cap.", "Market cap.", FORMULA, fmt=CUR,
        formula="={Market price}*{Total shares}"),

    Row("hdr_rt", "VALUATION & QUALITY RATIOS", HEADER),
    Row("dRev", "1. Δ Revenue (YoY)", FORMULA, fmt=PCT,
        formula="={Revenue}/{Revenue:prev}-1", note="YoY revenue growth",
        rec=REC_GROWTH),
    Row("dNI", "2. Δ Net income (YoY)", FORMULA, fmt=PCT,
        formula="=IF({Net income:prev}<=0,1,{Net income}/{Net income:prev}-1)",
        note="YoY earnings growth (capped at +100% when prior year <= 0)",
        rec=REC_GROWTH),
    Row("pe_ttm", "3. P/E (trailing)", FORMULA, fmt=MULT,
        formula='=IF({Net income}>0,{Market cap.}/{Net income},"n/m")',
        note="Market cap / net income; vs peer median (blank if losses)",
        rec=REC_MULT, peer=True),
    Row("fwd_pe", "   Forward P/E", FORMULA, fmt=MULT,
        formula='=IF({Net income}<=0,"n/m",IF(ISNUMBER({dNI}),{Market cap.}/({Net income}*(1+{dNI})),{Market cap.}/{Net income}))',
        note="Market cap / (net income * (1 + earnings growth)); vs peer median",
        skip_first=True, rec=REC_MULT, peer=True),
    Row("roce", "4. ROCE", FORMULA, fmt=PCT,
        formula='=IF({Capital employed}>0,{EBIT}/{Capital employed},"n/m")',
        note="EBIT / capital employed (>=15% BUY, <8% SELL)",
        rec=REC_ROCE, peer=True),
    Row("roe", "   ROE", FORMULA, fmt=PCT,
        formula='=IF({Stockholders\' equity}>0,{Net income}/{Stockholders\' equity},"n/m")',
        note="Net income / equity — blank if equity < 0 (e.g. MCD buybacks). >=15% BUY, <8% SELL",
        rec=REC_ROCE, peer=True),
    Row("mod_roce", "   Acid ROCE", FORMULA, fmt=PCT,
        formula='=IF(({Market cap.}-{Stockholders\' equity})>0,{EBIT}/({Market cap.}-{Stockholders\' equity}),"n/m")',
        note="EBIT / (market cap - equity) (>=5% BUY, 4-5% HOLD, <4% SELL)",
        rec=REC_ACID, peer=True),
    Row("ev_ebitda", "5. EV / EBITDA", FORMULA, fmt=MULT,
        formula='=IF({EBITDA}>0,({Market cap.}+{Total liabilities}-{Cash & mktb sec.})/{EBITDA},"n/m")',
        note="Enterprise value / EBITDA; vs peer median (blank if EBITDA < 0)", rec=REC_MULT, peer=True),
    Row("pb", "6. P / B", FORMULA, fmt=MULT,
        formula='=IF({Stockholders\' equity}>0,{Market cap.}/{Stockholders\' equity},"n/m")',
        note="vs peer median (blank if equity < 0)", rec=REC_MULT, peer=True),
    Row("ptbv", "   P / TBV", FORMULA, fmt=MULT,
        formula='=IF(({Stockholders\' equity}-{GW & intangibles})>0,{Market cap.}/({Stockholders\' equity}-{GW & intangibles}),"n/m")',
        note="Price / tangible book — key for banks; blank if tangible book < 0",
        rec=REC_MULT, peer=True),
    Row("ps", "7. P / S", FORMULA, fmt=MULT,
        formula="={Market cap.}/{Revenue}", note="vs peer median", rec=REC_MULT, peer=True),
    Row("ev_fcf", "8. EV / FCF", FORMULA, fmt=MULT,
        formula='=IF({FCF}>0,({Market cap.}+{Total liabilities}-{Cash & mktb sec.})/{FCF},"n/m")',
        note="vs peer median (blank if FCF < 0)", rec=REC_MULT, peer=True),
    Row("DY", "9. Dividend yield", FORMULA, fmt=PCT2,
        formula="={Cash dividend paid}/{Market cap.}",
        note="Dividends paid / market cap (>=3% BUY, <1% SELL)", rec=REC_DY),
    Row("tsr", "10. Total shareholder return", FORMULA, fmt=PCT,
        formula="=({Cash dividend paid}+{Repurchase of capital stock})/{Market cap.}",
        note="(dividends + buybacks) / market cap (>=5% BUY, <2% SELL)",
        rec=REC_TSR, peer=True),
    Row("capex_ebitda", "11. CapEx / EBITDA", FORMULA, fmt=PCT,
        formula='=IF({EBITDA}>0,{CapEx}/{EBITDA},"n/m")', note="informational; vs peer median", peer=True),
    Row("capex_da", "12. CapEx / D&A", FORMULA, fmt=MULT,
        formula="={CapEx}/{D&A}", note="informational; vs peer median", peer=True),
    Row("debt_assets", "13. Ratio de endeudamiento", FORMULA, fmt=PCT,
        formula="={Total debt}/{Total assets}",
        note="Total debt / total assets (<=30% BUY, >60% SELL)",
        rec=REC_LEV_ASSETS, peer=True),
    Row("debt_book", "14. Deuda financiera neta / activos (libros)", FORMULA, fmt=PCT,
        formula="={Net debt}/({Net debt}+{Total assets})",
        note="Net debt / (net debt + total assets) (<=20% BUY, >40% SELL)",
        rec=REC_LEV_BOOK, peer=True),
    Row("debt_mkt", "15. Deuda financiera neta / market cap", FORMULA, fmt=PCT,
        formula="={Net debt}/{Market cap.}",
        note="Net debt / market cap (<=15% BUY, >40% SELL)", rec=REC_LEV_MKT, peer=True),
    Row("trefis", "16. Price estimate (Trefis)", INPUT, fmt=CUR2,
        note="External target vs price (>+10% BUY, <-10% SELL)", rec=REC_UPSIDE),
]

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
NAVY = "1F3864"
LT_BLUE = "D9E1F2"
GREY = "F2F2F2"
_thin = Side(style="thin", color="BFBFBF")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


@dataclass
class SheetData:
    ticker: str
    inputs: dict[str, list]          # item key -> value per period (None allowed)
    periods: list[dict]              # [{'label': str, 'partial': bool}]
    unit_label: str = "US$ millions"
    notes: list[str] = field(default_factory=list)
    source_note: str = ""
    peer_median: dict[str, float] = field(default_factory=dict)  # ratio key -> sector peer median
    peer_note: str = ""                                          # e.g. "Peers: KO, PG, CL"
    sector: str = ""
    industry: str = ""
    is_financial: bool = False


def write_ticker_sheet(ws, data: SheetData) -> None:
    """Render one ticker's analysis onto worksheet ``ws``."""
    n = len(data.periods)
    first_data_col = 3          # column C (col B = labels)
    label_col = 2

    # ---- title block -----------------------------------------------------
    ws.cell(row=1, column=label_col, value=f"{data.ticker}  —  Fundamental Analysis")
    ws.cell(row=1, column=label_col).font = Font(bold=True, size=14, color=NAVY)
    ws.cell(row=2, column=label_col, value=f"Units: {data.unit_label} (except per-share & ratios)")
    ws.cell(row=2, column=label_col).font = Font(italic=True, size=9, color="808080")

    # ---- period header row ----------------------------------------------
    hrow = 4
    ws.cell(row=hrow, column=label_col, value="")
    for j, per in enumerate(data.periods):
        c = ws.cell(row=hrow, column=first_data_col + j, value=per["label"])
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER

    # ---- resolve each line item to an absolute row ----------------------
    row_of: dict[str, int] = {}
    r = hrow + 1
    for item in LAYOUT:
        row_of[item.key] = r
        r += 1

    def col_letter(j: int) -> str:
        return get_column_letter(first_data_col + j)

    def render_formula(tmpl: str, j: int) -> str | None:
        """Expand {key}, {key:prev}, {key:c} into A1 references for column j."""
        out = tmpl
        # find placeholders
        import re
        def repl(m):
            body = m.group(1)
            if ":prev" in body:
                key = body.replace(":prev", "")
                if j == 0:
                    return "__NOPREV__"
                return f"{col_letter(j-1)}{row_of[key]}"
            if ":c" in body:
                key = body.replace(":c", "")
                return f"{col_letter(j)}{row_of[key]}"
            key = body
            return f"{col_letter(j)}{row_of[key]}"
        out = re.sub(r"\{([^{}]+)\}", repl, out)
        if "__NOPREV__" in out:
            return None
        return out

    # ---- write rows ------------------------------------------------------
    for item in LAYOUT:
        rr = row_of[item.key]
        lc = ws.cell(row=rr, column=label_col, value=item.label)

        if item.kind == HEADER:
            lc.font = Font(bold=True, color="FFFFFF")
            lc.fill = PatternFill("solid", fgColor=NAVY)
            for j in range(n):
                cc = ws.cell(row=rr, column=first_data_col + j)
                cc.fill = PatternFill("solid", fgColor=NAVY)
            continue

        # shade sub-total / ratio label
        indent = item.label.startswith("   ")
        lc.font = Font(italic=indent, color="404040" if indent else "000000")
        lc.border = BORDER
        if item.note:
            lc.comment = None  # keep clean; note goes to a side column below

        for j in range(n):
            cc = ws.cell(row=rr, column=first_data_col + j)
            cc.border = BORDER
            cc.number_format = item.fmt
            cc.alignment = Alignment(horizontal="right")
            if item.kind == INPUT:
                vals = data.inputs.get(item.key) or []
                v = vals[j] if j < len(vals) else None
                if v is not None:
                    cc.value = v
            else:  # FORMULA
                if item.skip_first and j == 0:
                    continue
                f = render_formula(item.formula, j)
                cc.value = f if f is not None else None

        # zebra shading for readability
        if not indent and item.key not in ("Market cap.", "Capital employed"):
            pass

    # ---- peer-median + recommendation columns (right of data) -----------
    peer_col = first_data_col + n
    rec_col = first_data_col + n + 1
    last_col_letter = col_letter(n - 1)      # latest period column

    def render_rec(tmpl: str, rr: int) -> str:
        return (tmpl
                .replace("{last}", f"{last_col_letter}{rr}")
                .replace("{peer}", f"{get_column_letter(peer_col)}{rr}")
                .replace("{price}", f"{last_col_letter}{row_of['Market price']}")
                .replace("{trefis}", f"{last_col_letter}{row_of['trefis']}"))

    pc = ws.cell(row=hrow, column=peer_col, value="Peer median")
    pc.font = Font(bold=True, color="FFFFFF")
    pc.fill = PatternFill("solid", fgColor="7030A0")
    pc.alignment = Alignment(horizontal="center")
    pc.border = BORDER
    rc = ws.cell(row=hrow, column=rec_col, value="Rec.")
    rc.font = Font(bold=True, color="FFFFFF")
    rc.fill = PatternFill("solid", fgColor="7030A0")
    rc.alignment = Alignment(horizontal="center")
    rc.border = BORDER

    for item in LAYOUT:
        if item.kind == HEADER:
            continue
        rr = row_of[item.key]
        if item.peer:
            pcell = ws.cell(row=rr, column=peer_col)
            pcell.number_format = item.fmt
            pcell.alignment = Alignment(horizontal="right")
            pcell.border = BORDER
            pv = data.peer_median.get(item.key)
            if pv is not None:
                pcell.value = pv
        if item.rec:
            rcell = ws.cell(row=rr, column=rec_col, value=render_rec(item.rec, rr))
            rcell.alignment = Alignment(horizontal="center")
            rcell.font = Font(bold=True)
            rcell.border = BORDER

    # colour BUY green / HOLD amber / SELL red
    from openpyxl.formatting.rule import CellIsRule
    rng = f"{get_column_letter(rec_col)}{hrow + 1}:{get_column_letter(rec_col)}{r}"
    ws.conditional_formatting.add(rng, CellIsRule(
        operator="equal", formula=['"BUY"'],
        fill=PatternFill("solid", fgColor="C6EFCE"), font=Font(color="006100", bold=True)))
    ws.conditional_formatting.add(rng, CellIsRule(
        operator="equal", formula=['"HOLD"'],
        fill=PatternFill("solid", fgColor="FFEB9C"), font=Font(color="9C6500", bold=True)))
    ws.conditional_formatting.add(rng, CellIsRule(
        operator="equal", formula=['"SELL"'],
        fill=PatternFill("solid", fgColor="FFC7CE"), font=Font(color="9C0006", bold=True)))

    # ---- explanatory note column (right of rec) -------------------------
    note_col = first_data_col + n + 2
    nc = ws.cell(row=hrow, column=note_col, value="Definition / source")
    nc.font = Font(bold=True, italic=True, size=9, color="808080")
    for item in LAYOUT:
        if item.kind == HEADER or not item.note:
            continue
        c = ws.cell(row=row_of[item.key], column=note_col, value=item.note)
        c.font = Font(italic=True, size=9, color="808080")

    # ---- run-rate footnote ----------------------------------------------
    partial_labels = [p["label"] for p in data.periods if p.get("partial")]
    foot = r + 1
    if partial_labels:
        msg = ("Run-rate: " + ", ".join(partial_labels) +
               " annualizes reported year-to-date flows; balance-sheet items "
               "are the latest reported quarter (point-in-time).")
        c = ws.cell(row=foot, column=label_col, value=msg)
        c.font = Font(italic=True, size=9, color="C00000")
        foot += 1

    if data.peer_note:
        c = ws.cell(row=foot, column=label_col,
                    value=data.peer_note + " (Peer median column). Rec. compares the "
                    "latest period; valuation multiples vs peer median, the rest vs "
                    "absolute thresholds shown in Definition.")
        c.font = Font(italic=True, size=9, color="7030A0")
        foot += 1

    if data.source_note:
        c = ws.cell(row=foot, column=label_col, value=data.source_note)
        c.font = Font(italic=True, size=8, color="A0A0A0")
        foot += 1

    # ---- observations ----------------------------------------------------
    if data.notes:
        foot += 1
        c = ws.cell(row=foot, column=label_col, value="Observaciones")
        c.font = Font(bold=True, color=NAVY)
        for i, note in enumerate(data.notes, start=1):
            ws.cell(row=foot + i, column=label_col, value=f"• {note}").font = Font(size=10)

    # ---- column widths ---------------------------------------------------
    ws.column_dimensions[get_column_letter(label_col)].width = 34
    for j in range(n):
        ws.column_dimensions[col_letter(j)].width = 16
    ws.column_dimensions[get_column_letter(peer_col)].width = 13
    ws.column_dimensions[get_column_letter(rec_col)].width = 8
    ws.column_dimensions[get_column_letter(note_col)].width = 44
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = ws.cell(row=hrow + 1, column=first_data_col)


# --------------------------------------------------------------------------- #
# On-disk cache for fetched fundamentals (survives throttles / re-runs)
# --------------------------------------------------------------------------- #
# Yahoo rate-limits large sweeps. Caching each ticker's fetched SheetData means a
# re-run serves already-fetched names instantly and only re-hits Yahoo for the
# ones that failed — turning a throttled S&P-500 sweep into a converging retry.
_CACHE_DIR = Path(__file__).resolve().parents[1] / "dashboard" / ".cache"
_CACHE_ENABLED = True
_CACHE_TTL = 6 * 3600      # seconds; fundamentals barely move intraday


def configure_cache(enabled: bool = True, ttl: int | None = None, cache_dir=None):
    """Toggle / tune the on-disk fundamentals cache."""
    global _CACHE_ENABLED, _CACHE_TTL, _CACHE_DIR
    _CACHE_ENABLED = enabled
    if ttl is not None:
        _CACHE_TTL = ttl
    if cache_dir is not None:
        _CACHE_DIR = Path(cache_dir)


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / (hashlib.md5(key.encode()).hexdigest()[:16] + ".json")


def _cache_load(key: str):
    if not _CACHE_ENABLED:
        return None
    p = _cache_path(key)
    try:
        if p.exists() and (time.time() - p.stat().st_mtime) < _CACHE_TTL:
            return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _cache_store(key: str, obj: dict):
    if not _CACHE_ENABLED:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(key).with_suffix(".tmp")
        tmp.write_text(_json.dumps(obj), encoding="utf-8")
        tmp.replace(_cache_path(key))
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Trefis price-estimate fetcher (public feed, best-effort)
# --------------------------------------------------------------------------- #
_TREFIS_CACHE: dict | None = None
_TREFIS_URL = "https://www.trefis.com/api/price-estimates"


def _load_trefis_feed() -> dict:
    """Return {ticker: price_estimate} from the Trefis public feed (cached).

    The public endpoint only exposes ~200 tickers, so many names are absent;
    callers must handle a missing ticker (returns None from the lookup).
    """
    global _TREFIS_CACHE
    if _TREFIS_CACHE is not None:
        return _TREFIS_CACHE
    out: dict[str, float] = {}
    try:
        import time

        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.trefis.com/data/price-estimates",
        }
        # the AWS-fronted endpoint returns intermittent 504s -> retry a few times
        data = None
        for attempt in range(4):
            r = requests.get(_TREFIS_URL, headers=headers, timeout=25)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data = r.json()
                break
            time.sleep(1.5)
        if data is None:
            print("  [warn] Trefis feed unavailable after retries "
                  "(flaky endpoint); leaving estimate blank.", file=sys.stderr)
        for row in (data or {}).get("contents", []):
            tk = (row.get("ticker") or "").upper()
            est = row.get("trefisPriceGF")
            if est is None:  # fall back to marketPrice * (1 + upside)
                mp, up = row.get("marketPrice"), row.get("trefisPriceUpsideGF")
                est = mp * (1 + up) if mp is not None and up is not None else None
            if tk and est is not None:
                out[tk] = round(float(est), 2)
    except Exception as exc:
        print(f"  [warn] Trefis feed unavailable: {exc}", file=sys.stderr)
    _TREFIS_CACHE = out
    return out


def fetch_trefis_estimate(ticker: str) -> float | None:
    """Trefis price estimate for ``ticker`` if the public feed exposes it."""
    return _load_trefis_feed().get(ticker.upper())


# --------------------------------------------------------------------------- #
# yfinance fetcher
# --------------------------------------------------------------------------- #
# Yahoo Finance row labels can vary; we try a list of candidates per concept.

def _pick(df, candidates):
    """Return the row (a pandas Series indexed by period) for the first label
    in ``candidates`` that exists in ``df`` (df indexed by row label)."""
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def _get(series, col, default=None):
    if series is None:
        return default
    try:
        v = series.get(col)
    except Exception:
        return default
    if v is None:
        return default
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return default
    except Exception:
        pass
    return v


def fetch_yfinance(ticker: str, years: int = 3, unit_millions: bool = True,
                   partial_method: str = "runrate", with_trefis: bool = True) -> SheetData:
    """Build a :class:`SheetData` for ``ticker`` from Yahoo Finance.

    ``partial_method`` controls the trailing column:
        "runrate" -> annualize the fiscal-year-to-date flows (default; matches
                     the original spreadsheet, but distorts seasonal businesses
                     when only 1-2 quarters have been reported).
        "ttm"     -> sum the last 4 reported quarters (seasonally complete,
                     robust for consumer/retail names with a Dec fiscal year).
        "none"    -> omit the trailing column; full fiscal years only.
    """
    import yfinance as yf

    cache_key = f"sd:{ticker.upper()}:{years}:{unit_millions}:{partial_method}:{with_trefis}"
    cached = _cache_load(cache_key)
    if cached is not None:
        try:
            return SheetData(**cached)
        except Exception:  # noqa: BLE001 - stale/incompatible cache, refetch
            pass

    tk = yf.Ticker(ticker)
    inc = tk.income_stmt           # annual, columns = period-end Timestamps
    bal = tk.balance_sheet
    cf = tk.cashflow
    qinc = tk.quarterly_income_stmt
    qbal = tk.quarterly_balance_sheet
    qcf = tk.quarterly_cashflow

    if inc is None or inc.empty:
        raise RuntimeError(f"No income statement returned for {ticker} "
                           "(delisted, invalid ticker, or Yahoo throttling).")

    scale = 1e6 if unit_millions else 1.0

    def s(x):
        return None if x is None else x / scale

    # annual period-end dates, newest first -> take ``years`` most recent, oldest->newest.
    # Drop columns Yahoo lists but hasn't populated yet (all-NaN) — e.g. a just-ended
    # fiscal year with no annual figures loaded (NKE's May year-end). Otherwise that
    # empty column becomes the "latest year" and every ratio reads blank/zero. The
    # trailing run-rate/TTM column then reconstructs it from the quarterlies instead.
    _rev_row = _pick(inc, ["Total Revenue", "Operating Revenue"])
    ann_cols = [c for c in inc.columns if _get(_rev_row, c) is not None][:years][::-1]
    if not ann_cols:
        ann_cols = list(inc.columns)[:years][::-1]

    # concept -> candidate Yahoo labels
    C = {
        "Revenue": ["Total Revenue", "Operating Revenue"],
        "EBIT": ["EBIT", "Operating Income", "Total Operating Income As Reported"],
        "Net income": ["Net Income", "Net Income Common Stockholders",
                       "Net Income From Continuing Operation Net Minority Interest"],
        "EBITDA_direct": ["EBITDA", "Normalized EBITDA"],
        "D&A_inc": ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement"],
    }
    CB = {
        "Total assets": ["Total Assets"],
        "Current liabilities": ["Current Liabilities", "Total Current Liabilities"],
        "Stockholders' equity": ["Stockholders Equity", "Total Equity Gross Minority Interest",
                                 "Common Stock Equity"],
        "Total liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
        "Cash": ["Cash Cash Equivalents And Short Term Investments",
                 "Cash And Cash Equivalents"],
        "ShortInv": ["Other Short Term Investments", "Short Term Investments"],
        "LongInv": ["Long Term Equity Investment", "Investmentin Financial Assets",
                    "Other Investments", "Long Term Investments"],
        "Shares": ["Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding"],
        "Total debt": ["Total Debt"],
        "Net debt": ["Net Debt"],
        "LT debt": ["Long Term Debt And Capital Lease Obligation", "Long Term Debt"],
        "Current debt": ["Current Debt And Capital Lease Obligation", "Current Debt"],
        "CashOnly": ["Cash And Cash Equivalents"],
        "GW combined": ["Goodwill And Other Intangible Assets"],
        "Goodwill": ["Goodwill"],
        "Intangibles": ["Other Intangible Assets"],
    }
    CC = {
        "Operating CF": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
                         "Total Cash From Operating Activities"],
        "CapEx": ["Capital Expenditure", "Purchase Of PPE"],
        "FCF": ["Free Cash Flow"],
        "D&A_cf": ["Depreciation And Amortization", "Depreciation Amortization Depletion"],
        "Dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid",
                      "Common Stock Dividends Paid"],
        "Buyback": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    }

    rev = _pick(inc, C["Revenue"])
    ebit = _pick(inc, C["EBIT"])
    ni = _pick(inc, C["Net income"])
    ebitda_direct = _pick(inc, C["EBITDA_direct"])
    da_inc = _pick(inc, C["D&A_inc"])
    da_cf = _pick(cf, CC["D&A_cf"])

    ta = _pick(bal, CB["Total assets"])
    cl = _pick(bal, CB["Current liabilities"])
    eq = _pick(bal, CB["Stockholders' equity"])
    tl = _pick(bal, CB["Total liabilities"])
    cash = _pick(bal, CB["Cash"])
    shinv = _pick(bal, CB["ShortInv"])
    lginv = _pick(bal, CB["LongInv"])
    shares = _pick(bal, CB["Shares"])

    ocf = _pick(cf, CC["Operating CF"])
    capex = _pick(cf, CC["CapEx"])
    fcf = _pick(cf, CC["FCF"])
    tdebt = _pick(bal, CB["Total debt"])
    ndebt = _pick(bal, CB["Net debt"])
    ltdebt = _pick(bal, CB["LT debt"])
    curdebt = _pick(bal, CB["Current debt"])
    cash_only = _pick(bal, CB["CashOnly"])
    dividends = _pick(cf, CC["Dividends"])
    buyback = _pick(cf, CC["Buyback"])

    def total_debt_at(col):
        v = _get(tdebt, col)
        if v is not None:
            return v
        lt, cd = _get(ltdebt, col), _get(curdebt, col)
        if lt is not None or cd is not None:
            return (lt or 0) + (cd or 0)
        return None

    def net_debt_at(col):
        v = _get(ndebt, col)
        if v is not None:
            return v
        td = total_debt_at(col)
        c0 = _get(cash_only, col)
        if td is not None and c0 is not None:
            return td - c0
        return None

    gw_combined = _pick(bal, CB["GW combined"])
    goodwill = _pick(bal, CB["Goodwill"])
    intangibles = _pick(bal, CB["Intangibles"])

    def gw_at(col):
        v = _get(gw_combined, col)
        if v is not None:
            return v
        g, i = _get(goodwill, col), _get(intangibles, col)
        if g is not None or i is not None:
            return (g or 0) + (i or 0)
        return None

    def da_at(col):
        v = _get(da_inc, col)
        if v is None:
            v = _get(da_cf, col)
        return abs(v) if v is not None else None

    def ebitda_at(col):
        v = _get(ebitda_direct, col)
        if v is not None:
            return v
        e = _get(ebit, col)
        d = da_at(col)
        if e is not None and d is not None:
            return e + d
        return None

    def cash_mktb_at(col):
        base = _get(cash, col)
        if base is None:
            return None
        # if the "cash" line does not already include short-term investments, add them
        if cash is not None and shinv is not None and \
                cash.name not in ("Cash Cash Equivalents And Short Term Investments",):
            si = _get(shinv, col)
            if si is not None:
                base = base + si
        return base

    inputs: dict[str, list] = {k: [] for k in [
        "Revenue", "EBITDA", "EBIT", "Net income", "D&A",
        "Total assets", "Cash & mktb sec.", "Non-mktb sec.", "Current liabilities",
        "Stockholders' equity", "Total liabilities", "Total debt", "Net debt",
        "GW & intangibles",
        "Operating CF", "Cash dividend paid", "Repurchase of capital stock", "CapEx", "FCF",
        "Total shares", "Market price", "DY", "trefis",
    ]}

    # ---- historical annual prices (close near each fiscal year end) ------
    try:
        hist = tk.history(period="6y", interval="1mo")["Close"]
    except Exception:
        hist = None

    def price_near(ts):
        if hist is None or len(hist) == 0:
            return None
        try:
            sub = hist[hist.index.tz_localize(None) <= ts.tz_localize(None) if hist.index.tz is not None else hist.index <= ts]
        except Exception:
            try:
                sub = hist[hist.index <= ts]
            except Exception:
                return None
        if len(sub) == 0:
            return None
        return float(sub.iloc[-1])

    # current price + sector from info (dividend yield is now a formula)
    try:
        info = tk.info
    except Exception:
        info = {}
    cur_price = info.get("currentPrice") or info.get("regularMarketPrice")
    currency = info.get("financialCurrency") or info.get("currency") or "USD"
    sector = info.get("sector") or ""
    industry = info.get("industry") or ""
    fin_sector = (sector == "Financial Services") or any(
        k in industry for k in ("Bank", "Capital Markets", "Insurance", "Credit"))

    period_meta = []

    for col in ann_cols:
        inputs["Revenue"].append(s(_get(rev, col)))
        inputs["EBITDA"].append(s(ebitda_at(col)))
        inputs["EBIT"].append(s(_get(ebit, col)))
        inputs["Net income"].append(s(_get(ni, col)))
        inputs["D&A"].append(s(da_at(col)))
        inputs["Total assets"].append(s(_get(ta, col)))
        inputs["Cash & mktb sec."].append(s(cash_mktb_at(col)))
        li = _get(lginv, col)
        inputs["Non-mktb sec."].append(s(li) if li is not None else None)
        inputs["Current liabilities"].append(s(_get(cl, col)))
        inputs["Stockholders' equity"].append(s(_get(eq, col)))
        inputs["Total liabilities"].append(s(_get(tl, col)))
        inputs["Total debt"].append(s(total_debt_at(col)))
        inputs["Net debt"].append(s(net_debt_at(col)))
        inputs["GW & intangibles"].append(s(gw_at(col)))
        inputs["Operating CF"].append(s(_get(ocf, col)))
        dv = _get(dividends, col)
        inputs["Cash dividend paid"].append(s(abs(dv)) if dv is not None else None)
        bb = _get(buyback, col)
        inputs["Repurchase of capital stock"].append(s(abs(bb)) if bb is not None else None)
        cx = _get(capex, col)
        inputs["CapEx"].append(s(abs(cx)) if cx is not None else None)
        fv = _get(fcf, col)
        if fv is None and cx is not None and _get(ocf, col) is not None:
            fv = _get(ocf, col) - abs(cx)
        inputs["FCF"].append(s(fv))
        sh = _get(shares, col)
        inputs["Total shares"].append(s(sh) if sh is not None else None)
        inputs["Market price"].append(price_near(col))
        inputs["DY"].append(None)
        inputs["trefis"].append(None)
        period_meta.append({"label": f"FY{col.year}", "partial": False})

    # ---- trailing partial column (run-rate / TTM / none) ----------------
    warning = ""
    partial = None
    if partial_method != "none":
        partial = _build_runrate(
            qinc, qbal, qcf, ann_cols[-1] if ann_cols else None,
            rev, ebit, ni, ebitda_direct, da_inc, da_cf,
            ta, cl, eq, tl, cash, shinv, lginv, shares, ocf, capex, fcf,
            C, CB, CC, scale, method=partial_method)
    if partial is not None:
        label, vals, asof, warning = partial
        for k in inputs:
            inputs[k].append(vals.get(k))
        # latest price for the trailing column
        inputs["Market price"][-1] = cur_price if cur_price is not None else inputs["Market price"][-1]
        period_meta.append({"label": label, "partial": True})

    # ---- Trefis price estimate on the current-year (last) column --------
    notes = [warning] if warning else []
    if with_trefis and period_meta:
        est = fetch_trefis_estimate(ticker)
        if est is not None:
            inputs["trefis"][-1] = est
        else:
            notes.append(f"Trefis price estimate for {ticker.upper()} is not in the "
                         "public feed (only ~200 tickers exposed); enter it by hand.")

    cur_sym = {"USD": "US$", "EUR": "€", "GBP": "£", "GBp": "£", "CHF": "CHF",
               "JPY": "¥", "SEK": "SEK", "DKK": "DKK"}.get(currency, currency)
    unit_label = f"{cur_sym} millions" if unit_millions else cur_sym
    src = (f"Source: Yahoo Finance via yfinance; Trefis price estimate via "
           f"trefis.com public feed. Non-marketable securities are best-effort. "
           f"Generated for {ticker}.")
    # bank-like = a financial-sector name that structurally lacks EBITDA
    # (true banks/insurers) — excludes Visa/Mastercard which do report EBITDA.
    is_financial = fin_sector and all(v is None for v in inputs["EBITDA"])
    result = SheetData(ticker=ticker.upper(), inputs=inputs, periods=period_meta,
                       unit_label=unit_label, notes=notes, source_note=src,
                       sector=sector, industry=industry, is_financial=is_financial)
    _cache_store(cache_key, to_jsonable(asdict(result)))
    return result


def _build_runrate(qinc, qbal, qcf, last_annual_end,
                   rev, ebit, ni, ebitda_direct, da_inc, da_cf,
                   ta, cl, eq, tl, cash, shinv, lginv, shares, ocf, capex, fcf,
                   C, CB, CC, scale, method="runrate"):
    """Build the trailing partial column.

    method="runrate": annualize the fiscal-year-to-date flows reported after
        the last annual filing (flows x 4/nq; stocks = latest quarter).
    method="ttm": sum the last 4 reported quarters (seasonally complete).

    Returns (label, {item: value}, as_of_timestamp, warning) or None.
    """
    if qinc is None or qinc.empty:
        return None

    warning = ""
    if method == "ttm":
        qcols = sorted(qinc.columns)[-4:]
        nq = len(qcols)
        if nq == 0:
            return None
        factor = 1.0                       # already ~12 months of flows
        if nq < 4:
            warning = (f"TTM built from only {nq} reported quarter(s); "
                       "trailing flows are incomplete.")
    else:  # runrate
        if last_annual_end is None:
            return None
        qcols = sorted([c for c in qinc.columns if c > last_annual_end])
        nq = len(qcols)
        if nq == 0:
            return None
        factor = 4.0 / nq
        if nq < 3:
            warning = (f"Run-rate annualizes only {nq} reported quarter(s) of the "
                       "current fiscal year. For seasonal businesses (e.g. Dec "
                       "fiscal year-end) this distorts cash-flow lines; re-run "
                       "with --partial-method ttm for a seasonally complete view.")

    def s(x):
        return None if x is None else x / scale

    qrev = _pick(qinc, C["Revenue"])
    qebit = _pick(qinc, C["EBIT"])
    qni = _pick(qinc, C["Net income"])
    qebitda = _pick(qinc, C["EBITDA_direct"])
    qda_i = _pick(qinc, C["D&A_inc"])
    qda_c = _pick(qcf, CC["D&A_cf"]) if qcf is not None else None
    qta = _pick(qbal, CB["Total assets"]) if qbal is not None else None
    qcl = _pick(qbal, CB["Current liabilities"]) if qbal is not None else None
    qeq = _pick(qbal, CB["Stockholders' equity"]) if qbal is not None else None
    qtl = _pick(qbal, CB["Total liabilities"]) if qbal is not None else None
    qcash = _pick(qbal, CB["Cash"]) if qbal is not None else None
    qshinv = _pick(qbal, CB["ShortInv"]) if qbal is not None else None
    qlginv = _pick(qbal, CB["LongInv"]) if qbal is not None else None
    qshares = _pick(qbal, CB["Shares"]) if qbal is not None else None
    qocf = _pick(qcf, CC["Operating CF"]) if qcf is not None else None
    qcapex = _pick(qcf, CC["CapEx"]) if qcf is not None else None
    qfcf = _pick(qcf, CC["FCF"]) if qcf is not None else None
    qtdebt = _pick(qbal, CB["Total debt"]) if qbal is not None else None
    qndebt = _pick(qbal, CB["Net debt"]) if qbal is not None else None
    qgwc = _pick(qbal, CB["GW combined"]) if qbal is not None else None
    qgood = _pick(qbal, CB["Goodwill"]) if qbal is not None else None
    qintang = _pick(qbal, CB["Intangibles"]) if qbal is not None else None
    qdiv = _pick(qcf, CC["Dividends"]) if qcf is not None else None
    qbuy = _pick(qcf, CC["Buyback"]) if qcf is not None else None

    def flow_sum(series):
        if series is None:
            return None
        tot, seen = 0.0, False
        for c in qcols:
            v = _get(series, c)
            if v is not None:
                tot += v
                seen = True
        return tot if seen else None

    def da_flow():
        v = flow_sum(qda_i)
        if v is None:
            v = flow_sum(qda_c)
        return abs(v) if v is not None else None

    def ann(series):
        v = flow_sum(series)
        return None if v is None else v * factor

    ebitda_rr = ann(qebitda)
    if ebitda_rr is None:
        e = flow_sum(qebit)
        d = da_flow()
        if e is not None and d is not None:
            ebitda_rr = (e + d) * factor

    capex_sum = flow_sum(qcapex)
    capex_rr = abs(capex_sum) * factor if capex_sum is not None else None
    fcf_sum = flow_sum(qfcf)
    if fcf_sum is None:
        oc = flow_sum(qocf)
        if oc is not None and capex_sum is not None:
            fcf_sum = oc - abs(capex_sum)
    fcf_rr = fcf_sum * factor if fcf_sum is not None else None

    latest = qcols[-1]

    # Balance-sheet stocks use the latest QUARTERLY BALANCE column that actually
    # has data, which can lag the income statement (Yahoo loads them separately —
    # e.g. NKE's income has a May quarter the balance sheet doesn't yet). Using the
    # income quarter's date to look up the balance sheet would return None for every
    # stock (blank shares -> blank market cap -> all multiples blank).
    bs_ref = None
    if qbal is not None:
        for c in sorted(qbal.columns, reverse=True):
            if _get(qeq, c) is not None or _get(qta, c) is not None:
                bs_ref = c
                break

    def bs_latest(series):
        return s(_get(series, bs_ref)) if series is not None and bs_ref is not None else None

    cash_latest = _get(qcash, bs_ref) if (qcash is not None and bs_ref is not None) else None
    if cash_latest is not None and qcash is not None and qshinv is not None and \
            qcash.name not in ("Cash Cash Equivalents And Short Term Investments",):
        si = _get(qshinv, bs_ref)
        if si is not None:
            cash_latest = cash_latest + si

    def gw_latest():
        if bs_ref is None:
            return None
        v = _get(qgwc, bs_ref)
        if v is not None:
            return v
        g, i = _get(qgood, bs_ref), _get(qintang, bs_ref)
        if g is not None or i is not None:
            return (g or 0) + (i or 0)
        return None

    div_sum = flow_sum(qdiv)
    div_rr = abs(div_sum) * factor if div_sum is not None else None
    buy_sum = flow_sum(qbuy)
    buy_rr = abs(buy_sum) * factor if buy_sum is not None else None

    da_rr = da_flow()
    vals = {
        "Revenue": s(ann(qrev)) if ann(qrev) is not None else None,
        "EBITDA": s(ebitda_rr),
        "EBIT": s(ann(qebit)),
        "Net income": s(ann(qni)),
        "D&A": s(da_rr * factor) if da_rr is not None else None,
        "Total assets": bs_latest(qta),
        "Cash & mktb sec.": s(cash_latest),
        "Non-mktb sec.": bs_latest(qlginv),
        "Current liabilities": bs_latest(qcl),
        "Stockholders' equity": bs_latest(qeq),
        "Total liabilities": bs_latest(qtl),
        "Total debt": bs_latest(qtdebt),
        "Net debt": bs_latest(qndebt),
        "GW & intangibles": s(gw_latest()),
        "Operating CF": s(ann(qocf)),
        "Cash dividend paid": s(div_rr),
        "Repurchase of capital stock": s(buy_rr),
        "CapEx": s(capex_rr),
        "FCF": s(fcf_rr),
        "Total shares": bs_latest(qshares),
        "Market price": None,
        "DY": None,
        "trefis": None,
    }
    tag = "TTM" if method == "ttm" else "run-rate"
    label = f"{latest.year}-{latest.month:02d} ({tag})"
    return label, vals, latest, warning


# --------------------------------------------------------------------------- #
# Peer-median computation (numeric mirror of the Excel ratio formulas)
# --------------------------------------------------------------------------- #
# Keys here must match the ``rec``/``peer`` ratio Rows in LAYOUT.
def compute_ratios_for_period(inputs: dict, p: int) -> dict:
    """Compute the numeric value of each peer-comparable ratio for period ``p``."""
    def g(k):
        arr = inputs.get(k) or []
        return arr[p] if 0 <= p < len(arr) and arr[p] is not None else None

    def gp(k):
        arr = inputs.get(k) or []
        j = p - 1
        return arr[j] if 0 <= j < len(arr) and arr[j] is not None else None

    price, shares = g("Market price"), g("Total shares")
    mktcap = price * shares if price is not None and shares is not None else None
    tl, cash = g("Total liabilities"), g("Cash & mktb sec.")
    ev = mktcap + (tl or 0) - (cash or 0) if mktcap is not None else None
    ni, ni_prev = g("Net income"), gp("Net income")
    rev, rev_prev = g("Revenue"), gp("Revenue")
    ebitda, ebit = g("EBITDA"), g("EBIT")
    equity, fcf = g("Stockholders' equity"), g("FCF")
    ta, cl, nonmktb = g("Total assets"), g("Current liabilities"), g("Non-mktb sec.")
    capemp = ta - (cash or 0) - (nonmktb or 0) - (cl or 0) if ta is not None else None
    td, nd = g("Total debt"), g("Net debt")
    div, buy = g("Cash dividend paid"), g("Repurchase of capital stock")
    da, capex = g("D&A"), g("CapEx")
    gw = g("GW & intangibles")
    tbv = equity - (gw or 0) if equity is not None else None

    def safe(num, den, pos_den=False):
        if num is None or den is None or den == 0:
            return None
        if pos_den and den < 0:
            return None
        return num / den

    dRev = safe(rev, rev_prev, pos_den=True) - 1 if rev and rev_prev and rev_prev > 0 else None
    if ni is None or ni_prev is None:
        dNI = None
    elif ni_prev <= 0:
        dNI = 1.0                      # cap at +100% off a non-positive base (mirrors Excel)
    else:
        dNI = ni / ni_prev - 1
    fwd_pe = None
    if mktcap is not None and ni is not None and ni > 0:
        fwd_pe = mktcap / (ni * (1 + dNI)) if dNI is not None else mktcap / ni

    return {
        "dRev": dRev,
        "dNI": dNI,
        "pe_ttm": safe(mktcap, ni, pos_den=True) if ni and ni > 0 else None,
        "fwd_pe": fwd_pe,
        "roce": safe(ebit, capemp, pos_den=True) if capemp and capemp > 0 else None,
        "roe": safe(ni, equity, pos_den=True) if equity and equity > 0 else None,
        "mod_roce": (safe(ebit, (mktcap - equity)) if mktcap is not None and equity is not None
                     and (mktcap - equity) > 0 else None),
        "ptbv": safe(mktcap, tbv, pos_den=True) if tbv and tbv > 0 else None,
        "ev_ebitda": safe(ev, ebitda, pos_den=True) if ebitda and ebitda > 0 else None,
        "pb": safe(mktcap, equity, pos_den=True) if equity and equity > 0 else None,
        "ps": safe(mktcap, rev),
        "ev_fcf": safe(ev, fcf, pos_den=True) if fcf and fcf > 0 else None,
        "tsr": safe((div or 0) + (buy or 0), mktcap) if mktcap else None,
        "capex_ebitda": safe(capex, ebitda, pos_den=True) if ebitda and ebitda > 0 else None,
        "capex_da": safe(capex, da),
        "debt_assets": safe(td, ta),
        "debt_book": safe(nd, (nd + ta)) if nd is not None and ta is not None else None,
        "debt_mkt": safe(nd, mktcap),
        "DY": safe(div, mktcap),
    }


# ratio display metadata shared by the Excel writer intent and the web dashboard:
# (key, label, format, has_peer_median)
RATIO_DISPLAY = [
    ("dRev", "Δ Revenue (YoY)", "pct", False),
    ("dNI", "Δ Net income (YoY)", "pct", False),
    ("pe_ttm", "P/E (trailing)", "mult", True),
    ("fwd_pe", "Forward P/E", "mult", True),
    ("roce", "ROCE", "pct", True),
    ("roe", "ROE", "pct", True),
    ("mod_roce", "Acid ROCE", "pct", True),
    ("ev_ebitda", "EV / EBITDA", "mult", True),
    ("pb", "P / B", "mult", True),
    ("ptbv", "P / TBV", "mult", True),
    ("ps", "P / S", "mult", True),
    ("ev_fcf", "EV / FCF", "mult", True),
    ("DY", "Dividend yield", "pct2", False),
    ("tsr", "Total shareholder return", "pct", True),
    ("capex_ebitda", "CapEx / EBITDA", "pct", True),
    ("capex_da", "CapEx / D&A", "mult", True),
    ("debt_assets", "Ratio de endeudamiento", "pct", True),
    ("debt_book", "Deuda neta / activos (libros)", "pct", True),
    ("debt_mkt", "Deuda neta / market cap", "pct", True),
]
_MULT_KEYS = {"pe_ttm", "fwd_pe", "ev_ebitda", "pb", "ptbv", "ps", "ev_fcf"}
# ratios that are structurally N/A for banks / financials (no EBIT/EBITDA/CapEx/
# current-liabilities) — the UI marks these "n/a" instead of a blank dash.
BANK_NA_KEYS = ["roce", "mod_roce", "ev_ebitda", "ev_fcf", "capex_ebitda", "capex_da"]


def recommend_ratio(key: str, value, peer=None, price=None, trefis_val=None) -> str:
    """Return 'BUY' / 'HOLD' / 'SELL' / '' for a ratio, mirroring the Excel rules."""
    def band(v, buy, sell, low_good=False):
        if v is None:
            return ""
        if low_good:
            return "BUY" if v <= buy else ("SELL" if v > sell else "HOLD")
        return "BUY" if v >= buy else ("SELL" if v < sell else "HOLD")

    if key in _MULT_KEYS:                       # valuation multiples: vs peer median
        if peer is None or value is None or value <= 0:
            return ""
        return "BUY" if value < peer * 0.9 else ("SELL" if value > peer * 1.1 else "HOLD")
    if key in ("dRev", "dNI"):
        return band(value, 0.10, 0.0)
    if key in ("roce", "roe"):
        return band(value, 0.15, 0.08)
    if key == "mod_roce":                        # Acid ROCE: >=5% BUY, 4-5% HOLD, <4% SELL
        return band(value, 0.05, 0.04)
    if key == "tsr":
        return band(value, 0.05, 0.02)
    if key == "DY":
        return band(value, 0.03, 0.01)
    if key == "debt_assets":
        return band(value, 0.30, 0.60, low_good=True)
    if key == "debt_book":
        return band(value, 0.20, 0.40, low_good=True)
    if key == "debt_mkt":
        return band(value, 0.15, 0.40, low_good=True)
    if key == "trefis":
        if trefis_val is None or price is None:
            return ""
        return "BUY" if trefis_val > price * 1.1 else ("SELL" if trefis_val < price * 0.9 else "HOLD")
    return ""                                    # capex_* -> informational


# statement groupings for the dashboard (label, computed?) --------------------
_STATEMENTS = {
    "Income Statement": [
        ("Revenue", "Revenue"), ("EBITDA", "EBITDA"),
        ("EBIT", "EBIT (operating income)"), ("Net income", "Net income"), ("D&A", "D&A")],
    "Balance Sheet": [
        ("Total assets", "Total assets"), ("Cash & mktb sec.", "Cash & marketable securities"),
        ("Non-mktb sec.", "Non-marketable securities"), ("Current liabilities", "Current liabilities"),
        ("__capemp__", "Capital employed"), ("Stockholders' equity", "Stockholders' equity"),
        ("Total liabilities", "Total liabilities"), ("Total debt", "Total debt"),
        ("Net debt", "Net debt")],
    "Cash Flow": [
        ("Operating CF", "Operating cash flow"), ("Cash dividend paid", "Cash dividend paid"),
        ("Repurchase of capital stock", "Repurchase of capital stock"),
        ("CapEx", "CapEx"), ("FCF", "Free cash flow")],
    "Market Data": [
        ("Total shares", "Total shares (diluted)"), ("Market price", "Market price"),
        ("__mktcap__", "Market cap.")],
}


def _series(inputs, key, n):
    arr = inputs.get(key) or []
    return [arr[i] if i < len(arr) else None for i in range(n)]


def to_jsonable(obj):
    """Recursively convert numpy scalars / NaN / inf into plain JSON-safe values."""
    import math
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    # numpy scalar with .item()
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:
            return None
    return obj


def analyze_to_dict(ticker: str, years: int = 3, partial_method: str = "runrate",
                    peer_median: dict | None = None, with_trefis: bool = False) -> dict:
    """Full single-ticker analysis as a JSON-serializable dict for the dashboard."""
    data = fetch_yfinance(ticker, years=years, partial_method=partial_method,
                          with_trefis=with_trefis)
    inputs = data.inputs
    n = len(data.periods)
    peer_median = peer_median or {}

    def capemp(p):
        ta = _series(inputs, "Total assets", n)[p]
        cash = _series(inputs, "Cash & mktb sec.", n)[p]
        nm = _series(inputs, "Non-mktb sec.", n)[p]
        cl = _series(inputs, "Current liabilities", n)[p]
        return ta - (cash or 0) - (nm or 0) - (cl or 0) if ta is not None else None

    def mktcap(p):
        pr = _series(inputs, "Market price", n)[p]
        sh = _series(inputs, "Total shares", n)[p]
        return pr * sh if pr is not None and sh is not None else None

    statements = {}
    for grp, rows in _STATEMENTS.items():
        out_rows = []
        for key, label in rows:
            if key == "__capemp__":
                vals = [capemp(p) for p in range(n)]
                fmt = "num"
            elif key == "__mktcap__":
                vals = [mktcap(p) for p in range(n)]
                fmt = "num"
            else:
                vals = _series(inputs, key, n)
                fmt = "price" if key == "Market price" else "num"
            out_rows.append({"label": label, "fmt": fmt, "values": vals})
        statements[grp] = out_rows

    per_period = [compute_ratios_for_period(inputs, p) for p in range(n)]
    last = n - 1
    price_last = _series(inputs, "Market price", n)[last]
    trefis_series = _series(inputs, "trefis", n)

    ratios = []
    for key, label, fmt, has_peer in RATIO_DISPLAY:
        vals = [per_period[p].get(key) for p in range(n)]
        rec = recommend_ratio(key, vals[last], peer=peer_median.get(key), price=price_last)
        ratios.append({
            "key": key, "label": label, "fmt": fmt, "values": vals,
            "peer": peer_median.get(key) if has_peer else None, "rec": rec,
        })
    # Trefis price-estimate row (manual by default; blank -> no rec)
    ratios.append({
        "key": "trefis", "label": "Price estimate (Trefis)", "fmt": "price",
        "values": trefis_series, "peer": None,
        "rec": recommend_ratio("trefis", None, price=price_last, trefis_val=trefis_series[last]),
    })

    tally = {"BUY": 0, "HOLD": 0, "SELL": 0}
    for r in ratios:
        if r["rec"] in tally:
            tally[r["rec"]] += 1

    return to_jsonable({
        "ticker": data.ticker,
        "price": price_last,
        "periods": [pm["label"] for pm in data.periods],
        "unit_label": data.unit_label,
        "sector": data.sector,
        "industry": data.industry,
        "is_financial": data.is_financial,
        "bank_na_keys": BANK_NA_KEYS,
        "statements": statements,
        "ratios": ratios,
        "tally": tally,
        "notes": data.notes,
        "source_note": data.source_note,
    })


def summarize_ticker(ticker: str, years: int, partial_method: str,
                     peer_median: dict | None = None, with_trefis: bool = False) -> dict:
    """Compact last-period summary for batch view: per-ratio value + rec, no raw data."""
    data = fetch_yfinance(ticker, years=years, partial_method=partial_method,
                          with_trefis=with_trefis)
    inputs = data.inputs
    n = len(data.periods)
    last = n - 1
    peer_median = peer_median or {}
    vals = compute_ratios_for_period(inputs, last)
    price_last = (inputs.get("Market price") or [None])[last] if n else None
    cells = {}
    tally = {"BUY": 0, "HOLD": 0, "SELL": 0}
    for key, label, fmt, has_peer in RATIO_DISPLAY:
        v = vals.get(key)
        rec = recommend_ratio(key, v, peer=peer_median.get(key), price=price_last)
        cells[key] = {"value": v, "rec": rec, "fmt": fmt}
        if rec in tally:
            tally[rec] += 1
    return to_jsonable({
        "ticker": data.ticker,
        "price": price_last,
        "period": data.periods[last]["label"] if n else None,
        "is_financial": data.is_financial,
        "sector": data.sector,
        "cells": cells,
        "tally": tally,
        "score": tally["BUY"] - tally["SELL"],
    })


def build_batch(tickers, years: int = 3, partial_method: str = "runrate",
                peers=None, self_peer: bool = True, max_workers: int = 8,
                with_trefis: bool = False) -> dict:
    """Batch summary: one compact last-period row per ticker + universe medians.

    When no explicit ``peers`` are given and ``self_peer`` is on, valuation
    multiples are judged against the batch's OWN median (relative value within
    the group). Returns the same shape the dashboard and static report consume.
    """
    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    explicit_peers = [p.upper() for p in (peers or []) if p]
    self_peer = self_peer and not explicit_peers
    peer_median = compute_peer_medians(explicit_peers, years, partial_method) if explicit_peers else {}

    def work(t):
        return summarize_ticker(t, years, partial_method,
                                peer_median=peer_median, with_trefis=with_trefis)

    results, errors = map_tickers_chunked(tickers, work, max_workers=max_workers,
                                          label="batch")
    rows = list(results.values())

    used_median = dict(peer_median)
    if self_peer and rows:
        for key in _MULT_KEYS:
            xs = [r["cells"][key]["value"] for r in rows
                  if r["cells"][key]["value"] is not None and r["cells"][key]["value"] > 0]
            if xs:
                used_median[key] = median(xs)
        for r in rows:
            tally = {"BUY": 0, "HOLD": 0, "SELL": 0}
            for key, *_ in RATIO_DISPLAY:
                c = r["cells"][key]
                if key in _MULT_KEYS:
                    c["rec"] = recommend_ratio(key, c["value"], peer=used_median.get(key))
                if c["rec"] in tally:
                    tally[c["rec"]] += 1
            r["tally"] = tally
            r["score"] = tally["BUY"] - tally["SELL"]

    rows.sort(key=lambda r: r["score"], reverse=True)
    return to_jsonable({
        "rows": rows,
        "errors": errors,
        "ratio_order": [k for k, *_ in RATIO_DISPLAY],
        "ratio_labels": {k: lbl for k, lbl, *_ in RATIO_DISPLAY},
        "ratio_fmts": {k: fmt for k, _, fmt, _ in RATIO_DISPLAY},
        "bank_na_keys": BANK_NA_KEYS,
        "peer_median": used_median,
        "peer_basis": ("explicit: " + ", ".join(explicit_peers)) if explicit_peers
        else ("universe self-median" if self_peer else "none"),
    })


def map_tickers_chunked(tickers, work_fn, max_workers: int = 6, chunk_size: int = 25,
                        pause: float = 1.0, retries: int = 3, label: str = ""):
    """Run ``work_fn(ticker)`` over many tickers in throttled batches.

    Processes ``chunk_size`` tickers at a time with ``max_workers`` threads, pauses
    between chunks, and retries the failures over several passes with EXPONENTIAL
    backoff (Yahoo rate-limits large sweeps and returns empty frames). Combined with
    the on-disk cache, a throttled S&P-500 sweep converges: each pass serves the
    already-fetched names from cache and only re-hits Yahoo for the stragglers.
    Returns ``(results_dict, errors_list)``.
    """
    results: dict = {}
    remaining = list(dict.fromkeys(tickers))
    failed: list = []
    for attempt in range(retries + 1):
        failed = []
        total = len(remaining)
        for i in range(0, total, chunk_size):
            chunk = remaining[i:i + chunk_size]
            if label:
                done = len(results)
                print(f"  {label}: pass {attempt + 1}, {min(i + chunk_size, total)}/{total} "
                      f"(ok {done})", file=sys.stderr)
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {ex.submit(work_fn, t): t for t in chunk}
                for fut in as_completed(futs):
                    t = futs[fut]
                    try:
                        results[t] = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        failed.append((t, exc))
            if i + chunk_size < total:
                time.sleep(pause)
        remaining = [t for t, _ in failed]
        if not remaining or attempt == retries:
            break
        # exponential backoff (with jitter) before retrying the stragglers
        backoff = min(60.0, pause * (2 ** (attempt + 1))) + random.uniform(0, 1.5)
        if label:
            print(f"  {label}: {len(remaining)} failed, backing off {backoff:.0f}s "
                  f"before retry", file=sys.stderr)
        time.sleep(backoff)
    errors = [{"ticker": t, "error": f"{type(e).__name__}: {e}"} for t, e in failed]
    return results, errors


def compute_peer_medians(peer_tickers: list[str], years: int,
                         partial_method: str, max_workers: int = 8) -> dict[str, float]:
    """Fetch each peer (throttled batches), compute its latest-period ratios,
    return the per-ratio median across peers."""
    def work(pt):
        pdata = fetch_yfinance(pt, years=years, partial_method=partial_method,
                               with_trefis=False)
        last = len(pdata.periods) - 1
        return compute_ratios_for_period(pdata.inputs, last)

    results, _ = map_tickers_chunked(peer_tickers, work, max_workers=max_workers)
    buckets: dict[str, list] = {}
    for ratios in results.values():
        for k, v in ratios.items():
            if v is not None:
                buckets.setdefault(k, []).append(v)
    return {k: statistics.median(vs) for k, vs in buckets.items() if vs}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _sector_peers(ticker: str, n: int = 8):
    """Resolve S&P-500 sector peers via the dashboard's bundled list (best-effort)."""
    try:
        dash = Path(__file__).resolve().parents[1] / "dashboard"
        if str(dash) not in sys.path:
            sys.path.insert(0, str(dash))
        from peers import sector_of, sector_peers
        return sector_peers(ticker, n=n), sector_of(ticker)
    except Exception:  # noqa: BLE001
        return [], ""


def build_workbook(tickers: list[str], years: int, output: str,
                   partial_method: str = "runrate",
                   peers: list[str] | None = None,
                   with_trefis: bool = True,
                   auto_peers: bool = False) -> str:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    explicit = None
    if peers:
        subjects = {t.upper() for t in tickers}
        peer_list = [p for p in peers if p.upper() not in subjects]
        print(f"Computing peer medians from {len(peer_list)} peers ...", file=sys.stderr)
        explicit = (compute_peer_medians(peer_list, years, partial_method),
                    "Peers: " + ", ".join(p.upper() for p in peer_list))

    for t in tickers:
        if explicit:
            peer_median, peer_note = explicit
        elif auto_peers:
            sp, sector = _sector_peers(t)
            sp = [x for x in sp if x.upper() != t.upper()]
            print(f"Auto peers for {t} (S&P {sector or 'n/a'}): {len(sp)} peers ...", file=sys.stderr)
            peer_median = compute_peer_medians(sp, years, partial_method) if sp else {}
            peer_note = (f"Auto peers (S&P {sector}): " + ", ".join(sp)) if sp \
                else "No S&P-500 sector peers found (ticker outside the index)"
        else:
            peer_median, peer_note = {}, ""

        print(f"Fetching {t} ...", file=sys.stderr)
        data = fetch_yfinance(t, years=years, partial_method=partial_method,
                              with_trefis=with_trefis)
        data.peer_median = dict(peer_median)
        data.peer_note = peer_note
        ws = wb.create_sheet(title=t.upper()[:31])
        write_ticker_sheet(ws, data)
    wb.save(output)
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description="Build a fundamental-analysis Excel from a ticker.")
    p.add_argument("tickers", nargs="+", help="One or more tickers, e.g. MSFT AAPL")
    p.add_argument("--years", type=int, default=3, help="Number of full fiscal years (default 3)")
    p.add_argument("--partial-method", choices=["runrate", "ttm", "none"],
                   default="runrate",
                   help="Trailing column: runrate (annualize fiscal-YTD, default), "
                        "ttm (last 4 quarters, seasonally complete), or none.")
    p.add_argument("--peers", default=None,
                   help="Comma-separated peer tickers for sector-median comparison, "
                        "e.g. --peers KO,PG,CL. Drives the BUY/HOLD/SELL of valuation multiples.")
    p.add_argument("--auto-peers", action="store_true",
                   help="Auto-pick S&P-500 sector peers per ticker (ignored if --peers given).")
    p.add_argument("--no-trefis", action="store_true",
                   help="Skip the Trefis price-estimate lookup (avoids the external call).")
    p.add_argument("--output", "-o", default=None, help="Output .xlsx path")
    args = p.parse_args(argv)

    out = args.output
    if out is None:
        tag = "_".join(t.upper() for t in args.tickers)
        out = f"analyses/Analisis_{tag}.xlsx"

    peers = [x.strip() for x in args.peers.split(",") if x.strip()] if args.peers else None
    path = build_workbook(args.tickers, args.years, out,
                          partial_method=args.partial_method, peers=peers,
                          with_trefis=not args.no_trefis, auto_peers=args.auto_peers)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
