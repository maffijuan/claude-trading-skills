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
import statistics
import sys
from dataclasses import dataclass, field

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
        rec=REC_GROWTH, peer=True),
    Row("dNI", "2. Δ Net income (YoY)", FORMULA, fmt=PCT,
        formula='=IF({Net income:prev}<=0,"n.m.",{Net income}/{Net income:prev}-1)',
        note="YoY earnings growth (n.m. when prior year <= 0)",
        rec=REC_GROWTH, peer=True),
    Row("pe_ttm", "3. P/E (trailing)", FORMULA, fmt=MULT,
        formula="={Market cap.}/{Net income}", note="Market cap / net income; vs peer median",
        rec=REC_MULT, peer=True),
    Row("fwd_pe", "   Forward P/E", FORMULA, fmt=MULT,
        formula="=IF(ISNUMBER({dNI}),{Market cap.}/({Net income}*(1+{dNI})),{Market cap.}/{Net income})",
        note="Market cap / (net income * (1 + earnings growth)); vs peer median",
        skip_first=True, rec=REC_MULT, peer=True),
    Row("roce", "4. ROCE", FORMULA, fmt=PCT,
        formula="={EBIT}/{Capital employed}", note="EBIT / capital employed (>=15% BUY, <8% SELL)",
        rec=REC_ROCE, peer=True),
    Row("mod_roce", "   Modified ROCE", FORMULA, fmt=PCT,
        formula="={EBIT}/({Market cap.}-{Stockholders' equity})",
        note="EBIT / (market cap - equity)", peer=True),
    Row("ev_ebitda", "5. EV / EBITDA", FORMULA, fmt=MULT,
        formula="=({Market cap.}+{Total liabilities}-{Cash & mktb sec.})/{EBITDA}",
        note="Enterprise value / EBITDA; vs peer median", rec=REC_MULT, peer=True),
    Row("pb", "6. P / B", FORMULA, fmt=MULT,
        formula="={Market cap.}/{Stockholders' equity}", note="vs peer median",
        rec=REC_MULT, peer=True),
    Row("ps", "7. P / S", FORMULA, fmt=MULT,
        formula="={Market cap.}/{Revenue}", note="vs peer median", rec=REC_MULT, peer=True),
    Row("ev_fcf", "8. EV / FCF", FORMULA, fmt=MULT,
        formula="=({Market cap.}+{Total liabilities}-{Cash & mktb sec.})/{FCF}",
        note="vs peer median", rec=REC_MULT, peer=True),
    Row("DY", "9. Dividend yield", INPUT, fmt=PCT2,
        note=">=3% BUY, <1% SELL", rec=REC_DY),
    Row("tsr", "10. Total shareholder return", FORMULA, fmt=PCT,
        formula="=({Cash dividend paid}+{Repurchase of capital stock})/{Market cap.}",
        note="(dividends + buybacks) / market cap (>=5% BUY, <2% SELL)",
        rec=REC_TSR, peer=True),
    Row("capex_ebitda", "11. CapEx / EBITDA", FORMULA, fmt=PCT,
        formula="={CapEx}/{EBITDA}", note="informational; vs peer median", peer=True),
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
                   partial_method: str = "runrate") -> SheetData:
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

    # annual period-end dates, newest first -> take ``years`` most recent, oldest->newest
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

    # dividend yield (trailing) & current price from info
    try:
        info = tk.info
    except Exception:
        info = {}
    div_yield = info.get("dividendYield")
    if div_yield is not None and div_yield > 1:  # some feeds return percent
        div_yield = div_yield / 100.0
    cur_price = info.get("currentPrice") or info.get("regularMarketPrice")

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
        inputs["DY"][-1] = None
        period_meta.append({"label": label, "partial": True})

    # attach trailing dividend yield to the most recent *full* year column
    if div_yield is not None and period_meta:
        # place on last full-year column (index of last non-partial)
        for i in range(len(period_meta) - 1, -1, -1):
            if not period_meta[i]["partial"]:
                inputs["DY"][i] = div_yield
                break

    unit_label = "US$ millions" if unit_millions else "US$"
    src = (f"Source: Yahoo Finance via yfinance. Non-marketable securities and "
           f"dividend yield are best-effort. Generated for {ticker}.")
    notes = [warning] if warning else []
    return SheetData(ticker=ticker.upper(), inputs=inputs, periods=period_meta,
                     unit_label=unit_label, notes=notes, source_note=src)


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

    def bs_latest(series):
        return s(_get(series, latest)) if series is not None else None

    cash_latest = _get(qcash, latest) if qcash is not None else None
    if cash_latest is not None and qcash is not None and qshinv is not None and \
            qcash.name not in ("Cash Cash Equivalents And Short Term Investments",):
        si = _get(qshinv, latest)
        if si is not None:
            cash_latest = cash_latest + si

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

    def safe(num, den, pos_den=False):
        if num is None or den is None or den == 0:
            return None
        if pos_den and den < 0:
            return None
        return num / den

    dRev = safe(rev, rev_prev, pos_den=True) - 1 if rev and rev_prev and rev_prev > 0 else None
    dNI = ni / ni_prev - 1 if ni is not None and ni_prev is not None and ni_prev > 0 else None
    fwd_pe = None
    if mktcap is not None and ni is not None and ni > 0:
        fwd_pe = mktcap / (ni * (1 + dNI)) if dNI is not None else mktcap / ni

    return {
        "dRev": dRev,
        "dNI": dNI,
        "pe_ttm": safe(mktcap, ni, pos_den=True) if ni and ni > 0 else None,
        "fwd_pe": fwd_pe,
        "roce": safe(ebit, capemp),
        "mod_roce": safe(ebit, (mktcap - equity)) if mktcap is not None and equity is not None else None,
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
    }


def compute_peer_medians(peer_tickers: list[str], years: int,
                         partial_method: str) -> dict[str, float]:
    """Fetch each peer, compute its latest-period ratios, return per-ratio median."""
    buckets: dict[str, list] = {}
    for pt in peer_tickers:
        try:
            print(f"  peer {pt} ...", file=sys.stderr)
            pdata = fetch_yfinance(pt, years=years, partial_method=partial_method)
            last = len(pdata.periods) - 1
            for k, v in compute_ratios_for_period(pdata.inputs, last).items():
                if v is not None:
                    buckets.setdefault(k, []).append(v)
        except Exception as exc:
            print(f"  [warn] peer {pt} skipped: {exc}", file=sys.stderr)
    return {k: statistics.median(vs) for k, vs in buckets.items() if vs}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_workbook(tickers: list[str], years: int, output: str,
                   partial_method: str = "runrate",
                   peers: list[str] | None = None) -> str:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    peer_median: dict[str, float] = {}
    peer_note = ""
    if peers:
        subjects = {t.upper() for t in tickers}
        peer_list = [p for p in peers if p.upper() not in subjects]
        print(f"Computing sector peer medians from {len(peer_list)} peers ...", file=sys.stderr)
        peer_median = compute_peer_medians(peer_list, years, partial_method)
        peer_note = "Peers: " + ", ".join(p.upper() for p in peer_list)

    for t in tickers:
        print(f"Fetching {t} ...", file=sys.stderr)
        data = fetch_yfinance(t, years=years, partial_method=partial_method)
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
    p.add_argument("--output", "-o", default=None, help="Output .xlsx path")
    args = p.parse_args(argv)

    out = args.output
    if out is None:
        tag = "_".join(t.upper() for t in args.tickers)
        out = f"analyses/Analisis_{tag}.xlsx"

    peers = [x.strip() for x in args.peers.split(",") if x.strip()] if args.peers else None
    path = build_workbook(args.tickers, args.years, out,
                          partial_method=args.partial_method, peers=peers)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
