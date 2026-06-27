> **Historical document.** This captures the one-time analysis of the original
> SQLite-based, hardcoded-credentials version of the app and the cross-environment
> migration that followed. The app has since moved to PostgreSQL + TimescaleDB
> with environment-driven configuration. For current setup and behaviour see
> `SETUP.md` and `QUICK_START.md`; this file is retained only for context.

# Environment Compatibility Analysis - stock_monitor

## Issues Found

### 🔴 Critical Issues

#### 1. **Hardcoded Database Path (state.py)**
- **Issue**: `DB = "monitor.db"` creates database in current working directory
- **Problem**: Running from different directories will create multiple database instances
- **Impact**: High - Can cause data inconsistency across environments
- **Solution**: Use absolute or configurable path with `os.path.dirname(__file__)`

#### 2. **Hardcoded Credentials in config.py**
- **Issue**: Discord webhook URL is publicly exposed in source code
- **Problem**: Security risk and not portable across environments
- **Impact**: Critical - Credentials compromised and not environment-specific
- **Solution**: Read from environment variables with fallback

#### 3. **Relative Path Dependencies in validate_syntax.py**
- **Issue**: Opens files using relative paths (e.g., `"config.py"`)
- **Problem**: Script must be run from stock_monitor directory
- **Impact**: High - Script fails if run from parent directory
- **Solution**: Use `os.path.dirname(__file__)` to resolve paths

### 🟡 Moderate Issues

#### 4. **No Environment Variable Support for Configuration**
- **Issue**: All credentials (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL) are hardcoded
- **Problem**: Not suitable for production deployment across different environments
- **Impact**: Medium - Requires code changes for different environments
- **Solution**: Support reading from environment variables (.env or system vars)

#### 5. **Conditional Import Issues (notifier.py)**
- **Issue**: `from telegram import Bot` is inside function, asyncio.run() called inside
- **Problem**: Creates Bot instance on every call; asyncio.run() has issues on Windows with existing event loops
- **Impact**: Medium - May fail on certain platforms or when called from async context
- **Solution**: Initialize bot at module level, use proper async handling

#### 6. **Missing Error Handling for Missing Packages**
- **Issue**: Requirements.txt doesn't specify python version, and some packages may not install on all systems
- **Problem**: No graceful fallback if optional packages missing
- **Impact**: Low - Script crashes if dependencies not installed
- **Solution**: Add optional dependency handling with warnings

### 🟢 Minor Issues

#### 7. **Timezone Hardcoded to Asia/Kolkata**
- **Issue**: `TIMEZONE = "Asia/Kolkata"` is hardcoded in config
- **Problem**: Not suitable for other regions
- **Impact**: Low - Works as designed for this specific use case
- **Solution**: Make timezone configurable via environment variable

#### 8. **test_all.py Incomplete**
- **Issue**: Test file is truncated/incomplete
- **Impact**: Low - Test script doesn't fully work
- **Solution**: Complete the test script

## Recommendations

### Priority 1 (Fix immediately for cross-environment use):
1. ✅ Add environment variable support for credentials
2. ✅ Fix database path to use absolute path
3. ✅ Fix validate_syntax.py path handling
4. ✅ Add .env support

### Priority 2 (Improve robustness):
1. Fix async/await handling in notifier.py
2. Add graceful fallback for missing packages
3. Complete test_all.py

### Priority 3 (Nice to have):
1. Make timezone configurable
2. Add logging configuration to environment variables
