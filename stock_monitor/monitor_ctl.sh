#!/usr/bin/env bash
# Control script for the stock-monitor app, invoked by cron.
#   monitor_ctl.sh start   -> launch main.py (scans every 5 min) if not running
#   monitor_ctl.sh stop    -> stop the running monitor
#
# Cron runs in the server timezone (UTC). IST market window 09:00-15:30 IST
# maps to 03:30-10:00 UTC. See /etc/cron.d/stock-monitor.
set -euo pipefail

APP_DIR="/data/github/stock-monitor/stock_monitor"
PYTHON="/usr/bin/python3"
PIDFILE="$APP_DIR/monitor.pid"
LOGFILE="$APP_DIR/monitor.log"

cd "$APP_DIR"

is_running() {
    [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "${1:-}" in
    start)
        if is_running; then
            echo "$(date -u +%FT%TZ) start: already running (pid $(cat "$PIDFILE"))" >> "$LOGFILE"
            exit 0
        fi
        nohup "$PYTHON" main.py >> "$LOGFILE" 2>&1 &
        echo $! > "$PIDFILE"
        echo "$(date -u +%FT%TZ) start: launched pid $(cat "$PIDFILE")" >> "$LOGFILE"
        ;;
    stop)
        if is_running; then
            kill "$(cat "$PIDFILE")" 2>/dev/null || true
            echo "$(date -u +%FT%TZ) stop: killed pid $(cat "$PIDFILE")" >> "$LOGFILE"
        else
            echo "$(date -u +%FT%TZ) stop: not running" >> "$LOGFILE"
        fi
        rm -f "$PIDFILE"
        ;;
    *)
        echo "usage: $0 {start|stop}" >&2
        exit 2
        ;;
esac
