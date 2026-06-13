# Testing Guide for Stock Monitor

## Quick Test Methods

### 1️⃣ **Syntax Validation (Fastest)**
Check if Python files have valid syntax without running them.

```bash
python validate_syntax.py
```

**Expected Output:**
```
✓ config.py            - OK
✓ fetcher.py           - OK
✓ alert_engine.py      - OK
✓ notifier.py          - OK
✓ state.py             - OK
✓ main.py              - OK

✓ All files have valid Python syntax!
```

---

### 2️⃣ **Full Integration Test**
Runs comprehensive tests for all modules, including Discord notifications.

```bash
python test_all.py
```

**What it tests:**
- ✓ Module imports
- ✓ Configuration loading
- ✓ Database initialization
- ✓ State management (cooldown logic)
- ✓ Alert engine with mock data
- ✓ Discord webhook connection
- ✓ Live API call to fetch stock price (takes ~5-10 seconds)

**Expected Result:** 6/6 tests passed ✓

---

### 3️⃣ **Individual Module Testing**

#### Test Imports Only
```bash
python -c "from config import *; from fetcher import *; from alert_engine import *; from notifier import *; from state import *; print('✓ All imports OK')"
```

#### Test Config
```bash
python -c "from config import WATCHLIST, DISCORD_WEBHOOK_URL; print('Watchlist:', WATCHLIST); print('Discord configured:', bool(DISCORD_WEBHOOK_URL))"
```

#### Test Database
```bash
python -c "from state import init_db; init_db(); print('✓ Database initialized')"
```

#### Test Alert Engine Logic
```bash
python -c "
from alert_engine import check_alerts

data = {
    'symbol': 'TEST.NS',
    'open': 100.0,
    'current': 102.5,
    'high': 103.0,
    'low': 99.5,
    'volume': 50000,
    'pct_chg': 2.5  # 2.5% change (exceeds 1.5% threshold)
}

alerts = check_alerts(data)
print(f'Alerts generated: {len(alerts)}')
for alert in alerts:
    print(alert)
"
```

#### Test Discord Notification
```bash
python -c "
from notifier import send_discord

message = '🧪 Test Alert: Stock Monitor is working!'
result = send_discord(message)
print('Discord test:', '✓ Success' if result else '✗ Failed')
"
```

---

### 4️⃣ **Dry-Run Without Scheduling**
Test the main scanner logic without the scheduler:

```bash
python -c "
from config import WATCHLIST
from fetcher import get_price
from alert_engine import check_alerts
from notifier import send_discord
from state import init_db

init_db()

# Test with first symbol
symbol = WATCHLIST[0]
print(f'Testing with {symbol}...')

data = get_price(symbol)
if data:
    print(f'✓ Got price data: {data}')
    alerts = check_alerts(data)
    print(f'✓ Alerts: {len(alerts)}')
    if alerts:
        send_discord(alerts[0])
else:
    print('✗ No price data (market closed?)')
"
```

---

### 5️⃣ **Check Dependencies**
Verify all required packages are installed:

```bash
pip show yfinance requests pytz apscheduler
```

If any package is missing, install them:
```bash
pip install -r requirements.txt
```

---

## Troubleshooting Tests

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'yfinance'` | Run `pip install -r requirements.txt` |
| `Discord test returns False` | Check Discord webhook URL in config.py |
| `API test takes too long` | Normal - yfinance takes 5-10 seconds. Market data only available during trading hours |
| `Database locked error` | Delete `monitor.db` and try again: `rm monitor.db` |
| `Tests show "DeprecationWarning"` | Warnings are OK, not errors |

---

## How to Know Everything is Working ✓

✅ `validate_syntax.py` - All files pass syntax check  
✅ `test_all.py` - All 6 tests pass  
✅ Discord notification test sends a message to your Discord  
✅ No import errors when running Python scripts  
✅ Database initializes without errors  

## Recommended Testing Flow

1. **First time setup:**
   ```bash
   pip install -r requirements.txt
   python validate_syntax.py
   ```

2. **Before running main.py:**
   ```bash
   python test_all.py
   ```

3. **If tests pass, run the monitor:**
   ```bash
   python main.py
   ```

---

## Notes

- Tests don't require market to be open (except API test)
- Discord test sends an actual test message
- Database tests use real SQLite operations
- Alert engine uses mock data (doesn't affect real alerts)
- No credentials exposed in test output

---

**Last Updated:** June 7, 2026
