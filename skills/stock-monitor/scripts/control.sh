#!/bin/bash
# Stock Monitor 一键启动脚本 V2

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/.stock_monitor"
PID_FILE="$LOG_DIR/monitor.pid"
ALERT_FILE="$LOG_DIR/latest_alerts.txt"

case "$1" in
    start)
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "⚠️  监控进程已在运行 (PID: $(cat $PID_FILE))"
            exit 1
        fi
        
        echo "🚀 启动 Stock Monitor 后台进程..."
        mkdir -p "$LOG_DIR"
        nohup python3 "$SCRIPT_DIR/monitor_daemon.py" > "$LOG_DIR/daemon_stdout.log" 2>&1 &
        echo $! > "$PID_FILE"
        echo "✅ 已启动 (PID: $!)"
        echo "📋 日志: $LOG_DIR/monitor.log"
        echo "📋 预警: $ALERT_FILE"
        ;;
        
    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "🛑 停止监控进程 (PID: $PID)..."
                kill "$PID"
                rm "$PID_FILE"
                echo "✅ 已停止"
            else
                echo "⚠️  进程不存在"
                rm "$PID_FILE"
            fi
        else
            echo "⚠️  没有运行中的进程"
        fi
        ;;
        
    status)
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "✅ 监控运行中 (PID: $(cat $PID_FILE))"
            echo "📋 最近预警:"
            if [ -f "$ALERT_FILE" ]; then
                cat "$ALERT_FILE" | tail -30
            else
                echo "  暂无预警"
            fi
            echo ""
            echo "📋 最近日志 (最后10行):"
            tail -10 "$LOG_DIR/monitor.log" 2>/dev/null || echo "  暂无日志"
        else
            echo "⏹️  监控未运行"
        fi
        ;;
        
    alerts)
        echo "📋 最近预警 (24小时内):"
        if [ -f "$ALERT_FILE" ]; then
            # 只显示近24小时的预警
            awk -v cutoff="$(date -d '24 hours ago' '+%Y-%m-%d %H:%M')" '
                /^[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
                    if ($1 " " substr($2,1,5) >= cutoff) print
                }' "$ALERT_FILE" | tail -50
        else
            echo "  暂无预警"
        fi
        ;;
        
    log)
        tail -f "$LOG_DIR/monitor.log"
        ;;
        
    *)
        echo "Stock Monitor 控制脚本 V2"
        echo ""
        echo "用法: ./control.sh [start|stop|status|alerts|log]"
        echo ""
        echo "  start   - 启动后台监控"
        echo "  stop    - 停止监控"
        echo "  status  - 查看状态 + 最近预警"
        echo "  alerts  - 查看最近预警"
        echo "  log     - 查看实时日志"
        ;;
esac
