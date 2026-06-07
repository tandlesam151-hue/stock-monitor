import logging
from config import ALERT_THRESHOLDS
from state import can_alert, record_alert

logger = logging.getLogger(__name__)

def check_alerts(data: dict) -> list[str]:
    """Check if price movement triggers alerts based on thresholds."""
    messages = []
    
    if not data:
        return messages
    
    sym   = data.get("symbol", "UNKNOWN")
    pct   = data.get("pct_chg", 0)
    cool  = ALERT_THRESHOLDS.get("cooldown_mins", 30)
    thr   = ALERT_THRESHOLDS.get("pct_move", 1.5)

    if abs(pct) >= thr:
        direction = "🚀 SURGE" if pct > 0 else "🔴 DROP"
        atype = f"pct_{'+' if pct > 0 else '-'}"
        
        if can_alert(sym, atype, cool):
            msg = (f"{direction} | {sym.replace('.NS', '')}"
                   f"\nChange: {pct:+.2f}%  |  ₹{data.get('current', 'N/A')}"
                   f"\nOpen: ₹{data.get('open', 'N/A')}  High: ₹{data.get('high', 'N/A')}  Low: ₹{data.get('low', 'N/A')}")
            messages.append(msg)
            record_alert(sym, atype)
            logger.info(f"Alert triggered for {sym}: {pct:+.2f}%")
    
    return messages