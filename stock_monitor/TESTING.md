# Testing Guide for Stock Monitor

## Test entry points

### 1. Syntax validation (fastest)
```bash
python validate_syntax.py
```
Parses each core module and reports syntax errors. No imports executed, no
network or DB needed.

### 2. Deterministic fetch + scoring tests
```bash
python test_fetch_and_scoring.py
```
The most useful suite for verifying behaviour. It pins down concrete answers
(no random data) and needs no database — DB persistence is toggled off inside
the relevant tests. Coverage:

- fetcher session-slicing (`_latest_session`) and column normalization
- breakout detector → BULL above range / BEAR below range
- candlestick detector → bullish marubozu
- `compute_all` populates every indicator column with finite values
- `analyze()` returns None below 30 candles
- `analyze()` direction is consistent with the bull/bear score split
- a forced-BULL scenario scores BULL
- daily context: regime detection, no-lookahead cutoff, and confidence
  alignment boost / contradiction penalty (with the trend filter suppressing
  signals that fight the daily trend)
- floor pivots: correct math + ordering, no-lookahead, structure-based
  stop/target levels, and the support/resistance confidence nudge (including
  ATR-scaled tolerance and breakout de-duplication)
- `check_alerts()` emits nothing on neutral data
- a live fetch smoke test (skipped gracefully if offline)

Expected: `30 passed, 0 failed` online (the two live smoke tests self-skip when
offline, e.g. `28 passed, 0 failed, 2 skipped`).

### 3. Broader integration checks
```bash
python test_all.py
```
Exercises imports, config, the DB-backed cooldown state, the alert engine, and
**sends real Discord test messages** plus a live yfinance call. Requires a
configured `.env`, a reachable Postgres, and network access.

### 4. Send a single Discord test message
```bash
python send_discord_test.py
```

## Targeted one-liners

Imports:
```bash
python -c "import config, fetcher, indicators, patterns, alert_engine, notifier, state, db; print('imports OK')"
```

Config:
```bash
python -c "from config import WATCHLIST, DISCORD_WEBHOOK_URL; print('Watchlist:', WATCHLIST); print('Discord configured:', 'YOUR' not in DISCORD_WEBHOOK_URL)"
```

Database connectivity + schema:
```bash
python -c "import db; db.init_schema(); print('DB OK')"
```

End-to-end on one symbol (note: `check_alerts` takes a **DataFrame**, which
`get_price` returns — not a plain dict):
```bash
python -c "
from config import WATCHLIST
from fetcher import get_price
from alert_engine import check_alerts, analyze

symbol = WATCHLIST[0]
df = get_price(symbol)
if df is None or df.empty:
    print('No price data (no recent session / offline)')
else:
    df.attrs['symbol'] = symbol
    res = analyze(df)
    print(f'{symbol}: dir={res[\"direction\"]} score={res[\"score\"]} conf={res[\"confidence\"]}')
    print('alerts:', len(check_alerts(df)))
"
```

## Notes

- `test_fetch_and_scoring.py` is the source of truth for fetch/scoring logic and
  needs no DB or network (the one live test self-skips).
- `test_all.py` and `send_discord_test.py` produce real side effects (Discord
  messages, DB writes) and need a configured environment.
- The market does not need to be open to run the tests; the live fetch falls
  back to the most recent available session.
