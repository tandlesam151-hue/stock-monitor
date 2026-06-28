"""Salvage test: can a calibrated, regime-gated logistic model built from the
few signal components that showed any edge (breakout / VWAP / volume) produce a
POSITIVE and STABLE Information Coefficient out-of-sample?

Method (honest, no lookahead):
  * Features (all directional / signed): breakout (Chart Pattern), VWAP, Volume,
    plus daily-regime dummies and a breakout x trend interaction (the gating).
  * Target: P(forward raw return > 0) at a horizon.
  * Time split: train on the EARLIEST 60% of sessions, test on the LATEST 40%.
    The scaler and weights are fit on TRAIN only; all IC numbers are TEST (OOS).
  * Logistic regression fit in numpy (GD + L2); probabilities are naturally
    calibrated and we print a reliability table to confirm.
  * Compare the model's OOS IC to the raw engine's conviction IC on the SAME
    test rows — apples to apples.

Dependency-free (numpy only). Reads signal_labels.csv from ic_analysis.py.

Run:  python ic_model.py            (uses signal_labels.csv, target=reod)
"""
import argparse
import numpy as np
import pandas as pd

FEATURES = ["breakout", "vwap", "volume", "regime_up", "regime_down", "breakout_x_trend"]


def spearman(a, b):
    """Spearman rho via Pearson-on-ranks (no scipy)."""
    s = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(s) < 5 or s["a"].nunique() < 2 or s["b"].nunique() < 2:
        return float("nan")
    return s["a"].rank().corr(s["b"].rank(), method="pearson")


def cross_sectional_ic(df, factor_col, ret_col):
    """Mean per-timestamp IC and its information ratio (stability)."""
    ics = []
    for _, g in df.groupby("ts"):
        if g["symbol"].nunique() >= 5:
            ic = spearman(g[factor_col], g[ret_col])
            if pd.notna(ic):
                ics.append(ic)
    if not ics:
        return float("nan"), float("nan"), 0
    s = pd.Series(ics)
    ir = s.mean() / s.std() if s.std() > 0 else float("nan")
    return s.mean(), ir, len(ics)


def build_features(df):
    X = pd.DataFrame(index=df.index)
    X["breakout"] = df["Chart Pattern"].astype(float)
    X["vwap"] = df["VWAP"].astype(float)
    X["volume"] = df["Volume"].astype(float)
    is_up = (df["regime"] == "UP").astype(float)
    is_down = (df["regime"] == "DOWN").astype(float)
    X["regime_up"] = is_up
    X["regime_down"] = is_down
    # Gating: breakout only "counts" in a trending regime (UP or DOWN).
    X["breakout_x_trend"] = X["breakout"] * ((is_up + is_down) > 0).astype(float)
    return X[FEATURES]


def sigmoid(z):
    return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)),
                    np.exp(z) / (1.0 + np.exp(z)))


def fit_logistic(X, y, lr=0.5, iters=4000, l2=1e-3):
    """Logistic regression via gradient descent with L2 (bias unregularized)."""
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])          # bias column
    w = np.zeros(k + 1)
    for _ in range(iters):
        p = sigmoid(Xb @ w)
        grad = Xb.T @ (p - y) / n
        grad[1:] += l2 * w[1:]
        w -= lr * grad
    return w


def predict(w, X):
    Xb = np.hstack([np.ones((X.shape[0], 1)), X])
    return sigmoid(Xb @ w)


def calibration_table(p, y, bins=5):
    df = pd.DataFrame({"p": p, "y": y})
    df["bin"] = pd.qcut(df["p"], min(bins, df["p"].nunique()), duplicates="drop")
    g = df.groupby("bin", observed=True).agg(n=("y", "size"),
                                             pred=("p", "mean"),
                                             actual=("y", "mean"))
    return g


def evaluate(df, target):
    df = df.dropna(subset=[target]).copy()
    df["y"] = (df[target] > 0).astype(int)

    sessions = sorted(df["session"].unique())
    cut = sessions[int(len(sessions) * 0.6)]
    train = df[df["session"] < cut].copy()
    test = df[df["session"] >= cut].copy()

    Xtr_raw, Xte_raw = build_features(train), build_features(test)
    mu, sd = Xtr_raw.mean(), Xtr_raw.std().replace(0, 1.0)
    Xtr = ((Xtr_raw - mu) / sd).values
    Xte = ((Xte_raw - mu) / sd).values
    ytr = train["y"].values.astype(float)

    w = fit_logistic(Xtr, ytr)
    train["model_p"] = predict(w, Xtr)
    test["model_p"] = predict(w, Xte)
    # Directional model factor (centered prob; ranking == ranking of linear score)
    train["model_factor"] = train["model_p"] - 0.5
    test["model_factor"] = test["model_p"] - 0.5

    print("\n" + "=" * 66)
    print(f"CALIBRATED LOGISTIC MODEL  — target: forward return > 0  [{target}]")
    print("=" * 66)
    print(f"Train: {len(train):,} rows / {train['session'].nunique()} sessions  "
          f"(< {cut})")
    print(f"Test : {len(test):,} rows / {test['session'].nunique()} sessions  "
          f"(>= {cut})   [all metrics below are OUT-OF-SAMPLE]")

    print("\nLearned weights (standardized; sign = directional pull on P(up)):")
    print(f"  {'bias':18s} {w[0]:+.4f}")
    for name, wi in zip(FEATURES, w[1:]):
        print(f"  {name:18s} {wi:+.4f}")

    # --- OOS IC: model vs raw engine conviction, same test rows -------------
    print("\n[A] POOLED IC (out-of-sample)  Spearman(factor, raw fwd return)")
    ic_model = spearman(test["model_factor"], test[target])
    ic_engine = spearman(test["signed_conviction"], test[target])
    print(f"    model factor    : IC = {ic_model:+.4f}")
    print(f"    engine conviction: IC = {ic_engine:+.4f}   (baseline)")

    print("\n[B] CROSS-SECTIONAL IC (out-of-sample, per-timestamp, averaged)")
    m_ic, m_ir, nb = cross_sectional_ic(test, "model_factor", target)
    e_ic, e_ir, _ = cross_sectional_ic(test, "signed_conviction", target)
    print(f"    model : mean IC = {m_ic:+.4f} | IC IR = {m_ir:+.3f} | buckets = {nb}")
    print(f"    engine: mean IC = {e_ic:+.4f} | IC IR = {e_ir:+.3f}   (baseline)")

    # --- Directional hit-rate using the model's chosen side -----------------
    print("\n[C] DIRECTIONAL HIT-RATE (out-of-sample)")
    side = np.sign(test["model_factor"].values)
    trade_ret = side * test[target].values
    valid = side != 0
    hit = (trade_ret[valid] > 0).mean() * 100 if valid.any() else float("nan")
    print(f"    model picks side: hit = {hit:5.1f}% | mean trade-return = "
          f"{trade_ret[valid].mean()*100:+.3f}% | n = {valid.sum()}")
    eng_side = np.sign(test["signed_conviction"].values)
    eng_ret = eng_side * test[target].values
    ev = eng_side != 0
    print(f"    engine side     : hit = {(eng_ret[ev]>0).mean()*100:5.1f}% | mean "
          f"trade-return = {eng_ret[ev].mean()*100:+.3f}%   (baseline)")

    # --- Calibration (reliability) on test ----------------------------------
    print("\n[D] CALIBRATION (out-of-sample reliability; predicted vs actual P(up))")
    ct = calibration_table(test["model_p"].values, test["y"].values)
    for b, row in ct.iterrows():
        print(f"    {str(b):28s} n={int(row['n']):4d}  pred={row['pred']*100:5.1f}%  "
              f"actual={row['actual']*100:5.1f}%")

    return ic_model, m_ir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="signal_labels.csv")
    ap.add_argument("--targets", nargs="+", default=["reod", "r30m"])
    args = ap.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["ts"])
    df["session"] = df["ts"].dt.date
    print(f"Loaded {len(df):,} labeled evaluations from {args.csv}")

    summary = {}
    for t in args.targets:
        ic, ir = evaluate(df, t)
        summary[t] = (ic, ir)

    print("\n" + "=" * 66)
    print("VERDICT")
    print("=" * 66)
    for t, (ic, ir) in summary.items():
        ok = (not np.isnan(ic)) and ic > 0.03 and (not np.isnan(ir)) and ir > 0.3
        tag = "SALVAGEABLE EDGE" if ok else "no usable/stable edge"
        print(f"  [{t}] OOS pooled IC={ic:+.4f}, cross-sec IC IR={ir:+.3f}  -> {tag}")
    print("  (bar: pooled IC>+0.03 AND IC IR>+0.3 to call it real and stable)")


if __name__ == "__main__":
    main()
