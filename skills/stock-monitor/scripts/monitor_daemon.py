#!/usr/bin/env python3
"""
Stock Monitor Daemon V2.1 — 联邦投顾持仓监控
按守东需求改造：
- A股盘中(09:30-15:00): 跳过（守东自己盯盘）
- 美股盘中(21:30-04:00): 5分钟（腾讯API实时）
- 盘后(15:00-21:30 + 04:00-09:30): 30分钟（全标的+技术指标）
"""

import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from pathlib import Path

# 设置日志
log_dir = Path.home() / ".stock_monitor"
log_dir.mkdir(exist_ok=True)
ALERT_FILE = log_dir / "latest_alerts.txt"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "monitor.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 导入监控类
sys.path.insert(0, str(Path(__file__).parent))

# 加载联邦配置
try:
    from federal_loader import load_and_monkeypatch
    FEDERAL_LOADED = load_and_monkeypatch()
except Exception as e:
    print(f"⚠️ 联邦配置加载失败: {e}")
    FEDERAL_LOADED = False

from monitor import StockAlert, WATCHLIST


def get_cst_now():
    """获取北京时间"""
    return datetime.now() + timedelta(hours=13)


class MonitorDaemon:
    def __init__(self):
        self.monitor = StockAlert()
        self.running = True
        self.last_run_time = 0
        self.last_tech_scan = None  # 上次技术指标扫描时间
        
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)
    
    def handle_shutdown(self, signum, frame):
        logger.info(f"收到信号 {signum}，正在关闭...")
        self.running = False
    
    def get_schedule(self):
        """
        基于北京时间的智能频率控制 V2.1：
        ┌──────────────────────────────────────────────────────────┐
        │ 时段                    │ 频率  │ A股       │ 美股      │
        ├──────────────────────────────────────────────────────────┤
        │ 09:30-15:00 A股盘中     │ 5min  │ ⛔跳过    │ 5min实时  │
        │ 15:00-21:30 盘后        │ 30min │ ✅全扫描  │ ✅全扫描  │
        │ 21:30-04:00 美股盘中    │ 5min  │ 实时现价  │ 5min实时  │
        │ 04:00-09:30 凌晨        │ 30min │ ✅全扫描  │ ✅全扫描  │
        └──────────────────────────────────────────────────────────┘
        """
        cst = get_cst_now()
        hour, minute = cst.hour, cst.minute
        time_val = hour * 100 + minute
        weekday = cst.weekday()
        
        # 周末：30分钟全扫描（不监控盘中）
        if weekday >= 5:
            return {
                "run": True, "mode": "weekend",
                "a_stocks": True, "us_stocks": True,
                "tech_scan": True, "interval": 1800
            }
        
        # A股盘中 (09:30-11:30, 13:00-15:00): A股跳过，美股5分钟
        morning = 930 <= time_val <= 1130
        afternoon = 1300 <= time_val <= 1500
        
        if morning or afternoon:
            return {
                "run": True, "mode": "a_share_market",
                "a_stocks": False,      # ⛔ A股盘中跳过
                "us_stocks": True,       # 美股实时
                "tech_scan": False,      # 盘中不扫技术指标
                "interval": 300          # 5分钟
            }
        
        # 美股盘中 (21:30-04:00): 全部5分钟
        if time_val >= 2130 or time_val < 400:
            # 美股盘中A股是盘后→A股现价也能拿（收盘价）
            return {
                "run": True, "mode": "us_market",
                "a_stocks": True,        # A股收盘价
                "us_stocks": True,       # 美股实时
                "tech_scan": False,      # 盘中不扫技术指标
                "interval": 300          # 5分钟
            }
        
        # 盘后 (15:00-21:30 + 04:00-09:30): 30分钟全扫描+技术指标
        return {
            "run": True, "mode": "after_hours",
            "a_stocks": True,
            "us_stocks": True,
            "tech_scan": True,           # ✅ 盘后扫技术指标
            "interval": 1800             # 30分钟
        }
    
    def run(self):
        logger.info("=" * 60)
        logger.info("🚀 Stock Monitor Daemon V2.1 启动（联邦投顾持仓监控）")
        logger.info(f"📋 监控标的: {len(WATCHLIST)} 只")
        logger.info("🕐 频率: A股盘后30min | 美股盘中5min | A股盘中跳过")
        logger.info("=" * 60)
        
        while self.running:
            try:
                sched = self.get_schedule()
                
                if sched["run"]:
                    mode = sched["mode"]
                    interval = sched["interval"]
                    
                    # 构建监控列表
                    stocks_to_check = []
                    for s in WATCHLIST:
                        is_us = s.get('market') == 'us'
                        if is_us and sched["us_stocks"]:
                            stocks_to_check.append(s)
                        elif not is_us and sched["a_stocks"]:
                            stocks_to_check.append(s)
                    
                    if stocks_to_check:
                        logger.info(f"[{mode}] 扫描 {len(stocks_to_check)} 标 | "
                                   f"A股={'✅' if sched['a_stocks'] else '⛔'} "
                                   f"美股={'✅' if sched['us_stocks'] else '⛔'} "
                                   f"技术={'✅' if sched['tech_scan'] else '⛔'}")
                        
                        alerts = self.monitor.run_once(
                            stocks_to_check=stocks_to_check,
                            tech_scan=sched["tech_scan"]
                        )
                        
                        if alerts:
                            logger.info(f"⚠️ 触发 {len(alerts)} 条预警")
                            # 写入预警文件（control.sh status/alerts 读取）
                            with open(ALERT_FILE, 'a') as f:
                                f.write(f"\n{'='*60}\n")
                                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{mode}]\n")
                                f.write(f"{'='*60}\n")
                                for a in alerts:
                                    f.write(a + "\n")
                            # 同时输出到日志
                            for a in alerts:
                                logger.info(f"\n{a}")
                        else:
                            logger.debug("✅ 无预警")
                    else:
                        logger.debug(f"[{mode}] 无标的需监控（A股盘中跳过）")
                    
                    self.last_run_time = time.time()
                
                # 分段睡眠
                sleep_interval = sched.get("interval", 300)
                slept = 0
                while slept < sleep_interval and self.running:
                    time.sleep(1)
                    slept += 1
                    
            except Exception as e:
                logger.error(f"运行出错: {e}", exc_info=True)
                time.sleep(60)
        
        logger.info("👋 Daemon 已停止")


if __name__ == '__main__':
    daemon = MonitorDaemon()
    daemon.run()
