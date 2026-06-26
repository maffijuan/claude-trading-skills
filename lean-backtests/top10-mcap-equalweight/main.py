# region imports
from AlgorithmImports import *
# endregion


class Top10MarketCapEqualWeight(QCAlgorithm):
    """
    Strategy: Hold the 10 largest US-listed companies by market capitalization,
    equal-weighted, rebalanced on a configurable cadence (quarterly by default,
    semi-annual with rebalance_months=6).

    Hypothesis (one sentence): The mega-cap leaders of the US market, refreshed
    each quarter and equal-weighted, capture the long-run equity risk premium with
    fewer single-name concentration risks than a cap-weighted index.

    Design notes (see backtest-expert methodology):
      - Survivorship bias: avoided. QuantConnect's Fundamental universe is
        point-in-time and INCLUDES securities that were later delisted, merged or
        bankrupted. At each quarterly selection we rank the companies that were
        actually the largest *on that date*, not the largest as of today.
      - Look-ahead bias: avoided. market_cap comes from data already reported as
        of self.time; rebalancing happens the morning AFTER selection.
      - Zero discretion: ranking, weighting and cadence are fully rule-based.
      - Friction: realistic IB-style fees + slippage via the default brokerage
        model (mega caps have negligible slippage, but it is still modeled).

    Periods (switch with the "mode" parameter, default = in-sample):
      - in-sample (is):  2010-01-01 .. 2020-12-31
      - out-of-sample (oos): 2021-01-01 .. 2025-12-31
      - full:            2010-01-01 .. 2025-12-31

    Rebalance cadence (switch with the "rebalance_months" parameter):
      - 3  -> quarterly (default)
      - 6  -> semi-annual
      - 12 -> annual
    """

    # ----- strategy constants (kept round, no curve-fitting) -----
    NUM_HOLDINGS = 10          # size of the basket
    MIN_PRICE = 5.0            # ignore sub-$5 names (data-quality / penny filter)
    DEFAULT_REBALANCE_MONTHS = 3   # quarterly unless overridden by parameter

    def initialize(self):
        mode = (self.get_parameter("mode") or "is").lower()
        start, end = self._period_for(mode)
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(100_000)

        # Rebalance cadence in months (must divide 12: 1,2,3,4,6,12).
        self.rebalance_months = int(
            self.get_parameter("rebalance_months") or self.DEFAULT_REBALANCE_MONTHS
        )

        # Survivorship-bias-free, point-in-time fundamentals at daily resolution.
        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self._select_fundamental)

        # Benchmark the broad market for context (cap-weighted S&P 500 proxy).
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

        # State.
        self._last_period = None      # (year, period) index of the last selection
        self._rebalance_pending = False
        self._targets: list[Symbol] = []

        # Rebalance the morning AFTER a new selection (no look-ahead).
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(9, 31),
            self._rebalance,
        )

        self.log(
            f"Initialized mode={mode} {start:%Y-%m-%d}..{end:%Y-%m-%d} "
            f"rebalance_months={self.rebalance_months}"
        )

    # ------------------------------------------------------------------
    # Universe selection: top N by market cap, refreshed once per period.
    # ------------------------------------------------------------------
    def _select_fundamental(self, fundamental: list[Fundamental]) -> list[Symbol]:
        period = (self.time.year, (self.time.month - 1) // self.rebalance_months)
        if period == self._last_period:
            return Universe.UNCHANGED
        self._last_period = period

        candidates = [
            f for f in fundamental
            if f.has_fundamental_data
            and f.market_cap and f.market_cap > 0
            and f.price > self.MIN_PRICE
        ]
        ranked = sorted(candidates, key=lambda f: f.market_cap, reverse=True)
        self._targets = [f.symbol for f in ranked[: self.NUM_HOLDINGS]]
        self._rebalance_pending = True

        names = ", ".join(s.value for s in self._targets)
        self.log(f"{self.time:%Y-%m-%d} new basket: {names}")
        return self._targets

    # ------------------------------------------------------------------
    # Rebalance: equal weight the current basket, liquidate everything else.
    # ------------------------------------------------------------------
    def _rebalance(self):
        if not self._rebalance_pending or not self._targets:
            return

        # Wait until every selected name has tradable price data loaded.
        if not all(self.securities[s].price > 0 for s in self._targets):
            return

        weight = 1.0 / len(self._targets)
        targets = [PortfolioTarget(s, weight) for s in self._targets]
        # liquidate_existing_holdings=True sells anything not in the new basket.
        self.set_holdings(targets, liquidate_existing_holdings=True)
        self._rebalance_pending = False
        self.log(f"{self.time:%Y-%m-%d} rebalanced to {len(targets)} names @ {weight:.1%} each")

    # ------------------------------------------------------------------
    # Keep SPY (benchmark only) from being traded if it leaves the universe.
    # ------------------------------------------------------------------
    def on_securities_changed(self, changes: SecurityChanges):
        for security in changes.removed_securities:
            if security.symbol == self.spy:
                continue
            if security.invested and security.symbol not in self._targets:
                self.liquidate(security.symbol, tag="left universe")

    @staticmethod
    def _period_for(mode: str):
        from datetime import date
        periods = {
            "is":   (date(2010, 1, 1), date(2020, 12, 31)),
            "oos":  (date(2021, 1, 1), date(2025, 12, 31)),
            "full": (date(2010, 1, 1), date(2025, 12, 31)),
        }
        return periods.get(mode, periods["is"])
