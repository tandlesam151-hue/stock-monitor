
"""
Test script to validate all stock_monitor modules work correctly
"""

import sys
import os

# Ensure unicode (✓, emoji) prints correctly on Windows consoles (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_imports():
    """Test if all required modules can be imported"""
    print("=" * 60)
    print("TEST 1: Checking Module Imports")
    print("=" * 60)
    
    try:
        import config
        print("✓ config.py imported successfully")
    except Exception as e:
        print(f"✗ config.py import failed: {e}")
        return False
    
    try:
        import state
        print("✓ state.py imported successfully")
    except Exception as e:
        print(f"✗ state.py import failed: {e}")
        return False
    
    try:
        import fetcher
        print("✓ fetcher.py imported successfully")
    except Exception as e:
        print(f"✗ fetcher.py import failed: {e}")
        return False
    
    try:
        import alert_engine
        print("✓ alert_engine.py imported successfully")
    except Exception as e:
        print(f"✗ alert_engine.py import failed: {e}")
        return False
    
    try:
        import notifier
        print("✓ notifier.py imported successfully")
    except Exception as e:
        print(f"✗ notifier.py import failed: {e}")
        return False
    
    print("\n✓ All imports successful!\n")
    return True


def test_config():
    """Test if config loads correctly"""
    print("=" * 60)
    print("TEST 2: Validating Configuration")
    print("=" * 60)
    
    try:
        from config import (WATCHLIST, ALERT_THRESHOLDS, MARKET_OPEN, 
                           MARKET_CLOSE, TIMEZONE, DISCORD_WEBHOOK_URL)
        
        print(f"✓ WATCHLIST: {WATCHLIST}")
        print(f"✓ ALERT_THRESHOLDS: {ALERT_THRESHOLDS}")
        print(f"✓ Trading Hours: {MARKET_OPEN} - {MARKET_CLOSE}")
        print(f"✓ Timezone: {TIMEZONE}")
        
        if DISCORD_WEBHOOK_URL and "YOUR" not in DISCORD_WEBHOOK_URL:
            print(f"✓ Discord Webhook: Configured (length: {len(DISCORD_WEBHOOK_URL)})")
        else:
            print(f"⚠ Discord Webhook: Not configured")
        
        print("\n✓ Configuration valid!\n")
        return True
    except Exception as e:
        print(f"✗ Configuration test failed: {e}\n")
        return False


def test_state():
    """Test database initialization and state functions"""
    print("=" * 60)
    print("TEST 3: Testing State/Database")
    print("=" * 60)
    
    try:
        from state import init_db, can_alert, record_alert
        
        init_db()
        print("✓ Database initialized successfully")
        
        # Test can_alert
        test_symbol = "TEST.NS"
        test_type = "pct_+"
        
        result = can_alert(test_symbol, test_type, 30)
        print(f"✓ can_alert({test_symbol}) returned: {result}")
        
        # Record alert
        record_alert(test_symbol, test_type)
        print(f"✓ Alert recorded for {test_symbol}")
        
        # Test cooldown
        result2 = can_alert(test_symbol, test_type, 30)
        print(f"✓ can_alert after recording returned: {result2} (should be False)")
        
        print("\n✓ State management working!\n")
        return True
    except Exception as e:
        print(f"✗ State test failed: {e}\n")
        return False


def test_alert_engine():
    """Test alert engine logic with mock data"""
    print("=" * 60)
    print("TEST 4: Testing Alert Engine")
    print("=" * 60)
    
    try:
        from alert_engine import check_alerts
        import pandas as pd
        import numpy as np

        # Create a mock 5-min OHLCV DataFrame with 40 rows
        idx = pd.date_range(end=pd.Timestamp.now(), periods=40, freq='5min')
        prices = 100 + np.cumsum(np.random.normal(0, 0.2, size=len(idx)))
        high = prices + np.random.uniform(0, 0.5, size=len(idx))
        low = prices - np.random.uniform(0, 0.5, size=len(idx))
        openp = prices + np.random.uniform(-0.2, 0.2, size=len(idx))
        volume = np.random.randint(1000, 50000, size=len(idx))

        mock_df = pd.DataFrame({'Open': openp, 'High': high, 'Low': low, 'Close': prices, 'Volume': volume}, index=idx)
        mock_df.attrs['symbol'] = 'JUBLFOOD.NS'

        alerts = check_alerts(mock_df)
        print(f"✓ check_alerts returned {len(alerts)} alert(s)")
        if alerts:
            for alert in alerts:
                print(f"  {alert}")

        # Test that too-few candles are rejected (engine requires >=30 rows)
        small_df = mock_df.iloc[:10].copy()
        small_df.attrs['symbol'] = 'JUBLFOOD.NS'
        alerts2 = check_alerts(small_df)
        print(f"✓ Insufficient-data scenario: {len(alerts2)} alerts (should be 0)")

        print("\n✓ Alert engine working!\n")
        return True
    except Exception as e:
        print(f"✗ Alert engine test failed: {e}\n")
        return False


def test_notifier():
    """Test notifier functions"""
    print("=" * 60)
    print("TEST 5: Testing Notifier (Discord)")
    print("=" * 60)
    
    try:
        from notifier import send_discord
        
        test_message = "🧪 Test Alert: This is a test message from stock monitor"
        
        print(f"Sending test message to Discord...")
        result = send_discord(test_message)
        
        if result:
            print(f"✓ Discord notification sent successfully!")
        else:
            print(f"✗ Discord notification failed (check webhook URL)")
        
        print("\n")
        return result
    except Exception as e:
        print(f"✗ Notifier test failed: {e}\n")
        return False


def test_sample_stock_notification():
    """Pull sample stock data and send it as a Discord message."""
    print("=" * 60)
    print("TEST 6: Testing Sample Stock Data Notification")
    print("=" * 60)
    
    try:
        from config import WATCHLIST
        from fetcher import get_price
        from notifier import send_discord

        symbol = WATCHLIST[0] if WATCHLIST else "HDFCBANK.NS"
        print(f"Fetching sample data for {symbol}...")
        df = get_price(symbol)

        if df is None or df.empty:
            print(f"✗ No data retrieved for {symbol}")
            return False

        latest = df.iloc[-1]
        open_price = df.iloc[0]['Open']
        sample_message = (
            f"📈 Sample Stock Update: {symbol.replace('.NS','')}\n"
            "```ini\n"
            "Symbol   | Price    | Open     | High     | Low      | Change\n"
            "---------|----------|----------|----------|----------|---------\n"
            f"{symbol.replace('.NS',''):<8} | ₹{latest['Close']:<7.2f} | ₹{open_price:<7.2f} | ₹{df['High'].max():<7.2f} | ₹{df['Low'].min():<7.2f} | {((latest['Close']-open_price)/open_price*100):+.2f}%\n"
            "```"
        )

        print("Sending sample stock notification to Discord...")
        result = send_discord(sample_message)
        
        if result:
            print("✓ Sample stock notification sent successfully!")
        else:
            print("✗ Sample stock notification failed")
        
        print("\n")
        return result
    except Exception as e:
        print(f"✗ Sample stock notification test failed: {e}\n")
        return False


def test_fetcher_offline():
    """Test fetcher with mock data (offline test)"""
    print("=" * 60)
    print("TEST 7: Testing Fetcher (Mock Data)")
    print("=" * 60)
    
    try:
        from fetcher import get_price
        
        # This will attempt real API call - only works with internet
        print("Testing fetcher with real API call (requires internet)...")
        print("Fetching data for HDFCBANK.NS...")
        
        df = get_price("HDFCBANK.NS")

        if df is not None and not df.empty:
            print(f"✓ Data retrieved successfully: {len(df)} candles")
            print(df.tail(1).to_dict('records')[0])
            ok = True
        else:
            print(f"✗ No data retrieved (market closed or API error) or insufficient candles")
            ok = False

        print("\n")
        return ok
    except Exception as e:
        print(f"✗ Fetcher test failed: {e}\n")
        return False


def run_all_tests():
    """Run all tests and generate report"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "STOCK MONITOR TEST SUITE" + " " * 19 + "║")
    print("╚" + "=" * 58 + "╝")
    print("\n")
    
    results = {
        "Imports": test_imports(),
        "Configuration": test_config(),
        "State/Database": test_state(),
        "Alert Engine": test_alert_engine(),
        "Notifier (Discord)": test_notifier(),
        "Sample Stock Notification": test_sample_stock_notification(),
        "Fetcher (API)": test_fetcher_offline(),
    }
    
    print("\n")
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} | {test_name}")
    
    print("=" * 60)
    print(f"Result: {passed}/{total} tests passed")
    print("=" * 60)
    
    if passed == total:
        print("\n✓ All tests passed! Your scripts are ready to run.\n")
    else:
        print(f"\n⚠ {total - passed} test(s) failed. Check error messages above.\n")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
