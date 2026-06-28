"""Signal labeling + Information Coefficient (IC) analysis.

Answers the only question that matters before trusting a signal engine:
*does it actually predict forward returns?*

What it does
------------
1. Replays the LIVE signal engine (``alert_engine.analyze``) bar-by-bar over the
   last ~month of 5-min data for the watchlist, with no lookahead (each bar sees
   only data up to itself; daily context uses only prior days).
2. Labels every evaluation with forward returns at +30m / +60m / end-of-day.
3. Quantifies edge:
     * Information Coefficient (IC): rank-correlation of the engine's directional
       conviction with realized forward return — pooled and proper
       cross-sectional (per-timestamp, averaged) with an IC information ratio.
     * Directional hit-rate on the signals that would actually fire an alert.
     * Per-component edge: forward return conditional on each individual
       indicator firing BULL vs BEAR (which inputs carry signal, which are noise).
     * Confidence calibration: realized hit-rate per confidence band.
4. Writes the full labeled dataset to ``signal_labels.csv`` for further research.

Run:  python ic_analysis.py            (replays from yfinance)
      python ic_analysis.py --period 2mo

This is research tooling; it does not write to the production DB.
"""
import argparse
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

import config
from fetcher import _normalize
from context import compute_context
from alert_engine import analyze, MIN_SCORE, SIGNAL_WEIGHTS

# Forward-return horizons in number of 5-min bars (6 = 30 min, 12 = 60 min).
HORIZON_BARS = {"r30m": 6, "r60m": 12}
COMPONENTS = list(SIGNAL_WEIGHTS.keys())


def _signed_points(signals):
    """Per-component signed points: +points if BULL, -points if BEAR, 0 absent."""
    out = {c: 0 for c in COMPONENTS}
    for s in signals:
        sign = 1 if s["direction"] == "BULL" else (-1 if s["direction"] == "BEAR" else 0)
        out[s["name"]] = sign * s["points"]
    return out


def _sessions(df):
    by_day = {}
    for ts in df.index:
        by_day.setdefault(ts.date(), []).append(ts)
    for d in sorted(by_day):
        idx = by_day[d]
        yield d, df.loc[idx[0]:idx[-1]]


def build_labeled_dataset(symbols, period_5m="1mo", period_daily="3mo", start_date=None,
                          max_5m_days=59):
    """Replay the engine and return a DataFrame of labeled evaluations."""
    rows = []
    for sym in symbols:
        try:
            # 5-min data is hard-capped by Yahoo to the last 60 days, and a
            # period that resolves just past it is rejected outright. Request an
            # explicit window capped at 59 days to get the maximum available.
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=min(59, max_5m_days))
            h5 = yf.Ticker(sym).history(start=start_dt, end=end_dt, interval="5m")
            hd = yf.Ticker(sym).history(period=period_daily, interval="1d")
        except Exception as e:
            print(f"  ! {sym}: fetch error {e!r}", file=sys.stderr)
            continue
        if h5 is None or h5.empty or hd is None or hd.empty:
            print(f"  ! {sym}: no data", file=sys.stderr)
            continue
        f5, fd = _normalize(h5), _normalize(hd)

        for sdate, sdf in _sessions(f5):
            if start_date and sdate < start_date:
                continue
            if len(sdf) < 30:
                continue
            ctx = compute_context(fd, session_date=sdate)
            closes = sdf["Close"].astype(float).values
            n = len(sdf)
            session_last_close = float(closes[-1])

            for i in range(30, n + 1):
                slice_df = sdf.iloc[:i].copy()
                slice_df.attrs["symbol"] = sym
                res = analyze(slice_df, context=ctx)
                if res is None or res["direction"] == "NEUTRAL":
                    continue

                cur_close = float(closes[i - 1])
                if cur_close <= 0:
                    continue
                # Forward RAW (long-side) returns, no lookahead beyond i-1.
                fwd = {}
                for name, hb in HORIZON_BARS.items():
                    j = min(i - 1 + hb, n - 1)
                    fwd[name] = closes[j] / cur_close - 1.0
                fwd["reod"] = session_last_close / cur_close - 1.0

                dirn = 1 if res["direction"] == "BULL" else -1
                fired = (res["score"] >= MIN_SCORE and res.get("aligned") is not False)

                row = {
                    "ts": sdf.index[i - 1], "symbol": sym, "session": sdate,
                    "direction": res["direction"], "dirn": dirn,
                    "bull_score": res["bull_score"], "bear_score": res["bear_score"],
                    "signed_conviction": res["bull_score"] - res["bear_score"],
                    "score": res["score"], "confidence": res["confidence"],
                    "conf_signed": res["confidence"] * dirn,
                    "regime": res.get("regime"), "aligned": res.get("aligned"),
                    "level": res["level"], "fired": fired,
                    "price": cur_close,
                }
                row.update(fwd)
                # Direction-adjusted forward returns (the trade's P&L sign).
                for h in list(HORIZON_BARS) + ["reod"]:
                    row[f"{h}_dir"] = fwd[h] * dirn
                row.update(_signed_points(res["signals"]))
                rows.append(row)
    return pd.DataFrame(rows)


def _spearman(a, b):
    """Spearman rho without scipy: Pearson correlation of the ranks."""
    s = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(s) < 5 or s["a"].nunique() < 2 or s["b"].nunique() < 2:
        return float("nan")
    ra = s["a"].rank()
    rb = s["b"].rank()
    return ra.corr(rb, method="pearson")


def report(df):
    horizons = list(HORIZON_BARS) + ["reod"]
    hlabel = {"r30m": "+30 min", "r60m": "+60 min", "reod": "to EOD"}

    print("\n" + "=" * 64)
    print("SIGNAL LABELING + INFORMATION COEFFICIENT ANALYSIS")
    print("=" * 64)
    print(f"Evaluations (non-neutral): {len(df):,}  | symbols: {df['symbol'].nunique()}  "
          f"| sessions: {df['session'].nunique()}")
    fired = df[df["fired"]]
    print(f"Would-fire alerts (score>={MIN_SCORE}, not against trend): {len(fired):,}")

    # ---- 1. Pooled IC: conviction factor vs RAW forward return --------------
    print("\n[1] POOLED IC  — Spearman( signed_conviction , raw forward return )")
    print("    (>0 means the engine's bullish/bearish lean predicts direction)")
    for h in horizons:
        ic = _spearman(df["signed_conviction"], df[h])
        print(f"    {hlabel[h]:8s}: IC = {ic:+.4f}")

    # ---- 2. Cross-sectional IC (proper): per-timestamp, averaged ------------
    print("\n[2] CROSS-SECTIONAL IC  — per 5-min timestamp across symbols, averaged")
    print("    (institutional IC: rank names each bar, correlate with fwd return)")
    for h in horizons:
        ics = []
        for _, g in df.groupby("ts"):
            if g["symbol"].nunique() >= 5:
                ic = _spearman(g["signed_conviction"], g[h])
                if pd.notna(ic):
                    ics.append(ic)
        if ics:
            s = pd.Series(ics)
            ir = s.mean() / s.std() if s.std() > 0 else float("nan")
            print(f"    {hlabel[h]:8s}: mean IC = {s.mean():+.4f}  | IC IR = {ir:+.3f}  "
                  f"| n_buckets = {len(ics)}")
        else:
            print(f"    {hlabel[h]:8s}: insufficient cross-section")

    # ---- 3. Directional hit-rate on fired signals ---------------------------
    print("\n[3] DIRECTIONAL HIT-RATE  — on would-fire alerts")
    print("    (fraction where the trade direction matched realized move; 50% = coin flip)")
    if len(fired):
        for h in horizons:
            dr = fired[f"{h}_dir"].dropna()
            hit = (dr > 0).mean() * 100 if len(dr) else float("nan")
            print(f"    {hlabel[h]:8s}: hit = {hit:5.1f}%  | mean dir-return = "
                  f"{dr.mean()*100:+.3f}%  | n = {len(dr)}")
    else:
        print("    (no fired signals)")

    # ---- 4. Per-component edge ----------------------------------------------
    print("\n[4] PER-COMPONENT EDGE  — mean EOD raw return when component fires")
    print(f"    {'component':16s} {'BULL n':>7s} {'BULL ret':>9s} {'BEAR n':>7s} {'BEAR ret':>9s} {'spread':>8s}")
    base = df["reod"].mean()
    print(f"    {'(baseline all)':16s} {'':>7s} {base*100:+8.3f}%")
    comp_stats = []
    for c in COMPONENTS:
        bull = df[df[c] > 0]["reod"]
        bear = df[df[c] < 0]["reod"]
        bull_r = bull.mean() * 100 if len(bull) else float("nan")
        bear_r = bear.mean() * 100 if len(bear) else float("nan")
        spread = (bull_r - bear_r) if pd.notna(bull_r) and pd.notna(bear_r) else float("nan")
        comp_stats.append((c, len(bull), bull_r, len(bear), bear_r, spread))
    # sort by absolute spread (bull-minus-bear edge) descending
    for c, nb, br, nr, sr, sp in sorted(comp_stats, key=lambda x: -(abs(x[5]) if pd.notna(x[5]) else -1)):
        sp_txt = f"{sp:+7.3f}%" if pd.notna(sp) else "    n/a "
        print(f"    {c:16s} {nb:7d} {br:+8.3f}% {nr:7d} {sr:+8.3f}% {sp_txt}")
    print("    (spread = BULL minus BEAR mean return; a real signal => clearly positive)")

    # ---- 5. Confidence calibration ------------------------------------------
    print("\n[5] CONFIDENCE CALIBRATION  — EOD directional hit-rate by confidence band")
    print("    (a calibrated score => hit-rate rises monotonically with confidence)")
    if len(fired):
        bands = [(0, 45, "WEAK <45"), (45, 70, "NORMAL 45-69"), (70, 101, "STRONG >=70")]
        for lo, hi, name in bands:
            sub = fired[(fired["confidence"] >= lo) & (fired["confidence"] < hi)]
            dr = sub["reod_dir"].dropna()
            if len(dr):
                print(f"    {name:14s}: n = {len(dr):4d}  hit = {(dr>0).mean()*100:5.1f}%  "
                      f"mean dir-return = {dr.mean()*100:+.3f}%")
            else:
                print(f"    {name:14s}: n = 0")
    else:
        print("    (no fired signals)")

    print("\n" + "=" * 64)
    print("READING IT: |IC| < ~0.03 => no usable linear predictive power.")
    print("IC IR < ~0.3 => the (weak) signal is not stable across time.")
    print("Hit-rate ~50% and component spreads near 0 => no directional edge.")
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description="Signal labeling + IC analysis")
    ap.add_argument("--period", default="1mo", help="5-min history window (e.g. 1mo, 2mo)")
    ap.add_argument("--daily-period", default="3mo", help="daily history for context")
    ap.add_argument("--days", type=int, default=31, help="only label sessions within last N days")
    ap.add_argument("--csv", default="signal_labels.csv", help="output labeled dataset path")
    args = ap.parse_args()

    start_date = datetime.now().date() - timedelta(days=args.days)
    print(f"Replaying engine over {len(config.WATCHLIST)} symbols, "
          f"5m period={args.period}, sessions since {start_date} ...")
    df = build_labeled_dataset(config.WATCHLIST, period_5m=args.period,
                               period_daily=args.daily_period, start_date=start_date,
                               max_5m_days=args.days)
    if df.empty:
        print("No evaluations produced (no data / window too short).")
        return
    df.to_csv(args.csv, index=False)
    print(f"Labeled dataset written: {args.csv}  ({len(df):,} rows)")
    report(df)


if __name__ == "__main__":
    main()
