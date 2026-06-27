# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Pivot-based support/resistance.** `context.compute_context` now derives
  classic floor-trader pivots (`pivot`, `r1`, `r2`, `s1`, `s2`) from the prior
  daily bar. These are pure arithmetic on already-fetched data (no extra fetch)
  and inherit the existing no-lookahead session cutoff.
- **Structure-based stop/target levels.** Alerts now carry pivot-derived levels
  alongside the existing ATR-based ones: for a BULL the target is the nearest
  resistance above price and the stop sits just beyond the nearest support
  (mirrored for a BEAR). Surfaced in both the text alert and the Discord embed.
- **Support/resistance confidence nudge.** A signal with room to run (BULL at
  support / BEAR at resistance) is boosted by a small amount; one fighting an
  adjacent level (BULL under resistance / BEAR propped on support) is dampened.
  The "at a level" tolerance scales per stock as `0.25 × daily_atr`, and the
  nudge is suppressed when the breakout detector is already firing near the same
  level to avoid double-counting.
- Tests in `test_fetch_and_scoring.py` covering pivot math/ordering, the
  no-lookahead guarantee, the boost/dampen logic for both directions, mid-range
  no-ops, breakout de-duplication, structure-level construction, ATR-scaled
  tolerance, the no-pivots no-op, and end-to-end wiring through `analyze()`.

### Changed
- `SETUP.md` and `TESTING.md` updated to document the daily-context overlay,
  pivot/structure levels, and the expanded test coverage. `context.py` was also
  added to the `SETUP.md` file index.

### Notes
- The signal scoring weights are unchanged: `TOTAL_MAX` stays at 110 and the
  STRONG/NORMAL/WEAK confidence bands (70/45) are untouched. The S/R logic is a
  purely additive modifier layered on top of the existing trend adjustment, so
  no recalibration of the alert thresholds was required.
- A full, separately-scored "Support/Resistance" signal category was
  intentionally deferred until pivots have been observed on live alerts.

### Baseline (previously uncommitted working tree)
The following changes were already present in the working tree and are recorded
here for completeness; they predate the pivot work above:
- Migrated persistence from SQLite to **PostgreSQL + TimescaleDB**
  (`ohlcv`/`signals` hypertables, `alerts` table) with a one-off SQLite→Postgres
  migration path.
- Configuration moved to environment variables / `.env` support.
- Daily multi-timeframe context: trend regime, prior-day and 20-day swing
  levels, daily ATR and average volume, with confidence alignment/contradiction
  adjustments and a trend filter that suppresses counter-trend signals.
- DB resilience knobs (connect/pool timeouts, circuit-breaker cooldown).
- Market-hours gating (`ALLOW_ANYTIME` / `ALLOW_WEEKEND_RUN`).
