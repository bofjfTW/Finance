"""
Web Server for BingX Multi-Agent Quant Trading Dashboard
Hosts web interface on http://localhost:8080 with live REST API.
"""
import os
import sys
import asyncio
import time
import yaml
from aiohttp import web

# Reconfigure stdout/stderr for Windows UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from data.collector import DataCollector
from features.engine import FeatureEngine
from agents.selector import StrategySelector
from risk.risk_gate import RiskGate
from risk.kill_switch import KillSwitch
from execution.paper_broker import PaperBroker
from execution.exit_monitor import ContinuousExitMonitor
from data.schema import StrategyType, OrderSide, MarketType


class QuantWebServer:
    def __init__(self, port: int = 8080):
        self.port = port
        with open("config/settings.yaml", "r", encoding="utf-8") as f:
            self.settings = yaml.safe_load(f)
        with open("config/symbols.yaml", "r", encoding="utf-8") as f:
            self.symbols_cfg = yaml.safe_load(f)

        self.symbols = self.settings["trading"]["symbols"]
        self.collector = DataCollector(self.symbols, self.symbols_cfg["symbols"])
        self.feature_engine = FeatureEngine(self.collector)
        self.selector = StrategySelector(self.symbols, max_symbols=2)
        self.kill_switch = KillSwitch()
        self.risk_gate = RiskGate(
            kill_switch=self.kill_switch,
            base_trade_risk=self.settings["risk"]["base_trade_risk"],
            default_leverage=self.settings["risk"]["default_leverage"],
            max_open_symbols=self.settings["trading"]["max_open_symbols"]
        )
        self.broker = PaperBroker(initial_balance=1000.0)
        self.exit_monitor = ContinuousExitMonitor(
            broker=self.broker,
            kill_switch=self.kill_switch,
            soft_tp_roi=self.settings["exit"]["soft_take_profit"],
            hard_tp_roi=self.settings["exit"]["hard_take_profit"],
            soft_sl_roi=self.settings["exit"]["soft_stop_loss"],
            hard_sl_roi=self.settings["exit"]["hard_stop_loss"],
            trailing_callback_rate=self.settings["exit"]["trailing_callback_rate"],
            on_exit_callback=self._on_exit
        )

        self.cached_evaluations = []
        self.audit_logs = [
            {"time": time.strftime("%H:%M:%S"), "tag": "[SYSTEM]", "message": "Multi-Agent Trading Bot v2.0 已啟動"}
        ]
        self.schedule_minutes = self.settings["trading"].get("entry_schedule_minutes", [0, 20, 40])
        self.last_eval_time = 0

    def _on_exit(self, symbol: str, pnl: float, reason: str):
        self.risk_gate.record_trade_result(pnl or 0.0)
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        self.audit_logs.append({
            "time": time.strftime("%H:%M:%S"),
            "tag": "[CLOSE]",
            "message": f"平倉 {symbol}: 損益 {pnl_str} ({reason})"
        })

    async def start_background_tasks(self, app):
        # Start BingX WebSocket feed
        app["ws_task"] = asyncio.create_task(self.collector.start_live_feed())
        app["loop_task"] = asyncio.create_task(self._main_loop())

    async def cleanup_background_tasks(self, app):
        self.collector.ws_client.stop()
        app["ws_task"].cancel()
        app["loop_task"].cancel()

    async def _main_loop(self):
        """1-second main loop: exit monitoring and 20-min scheduler"""
        while True:
            try:
                now = time.time()
                now_dt = time.localtime(now)
                current_min = now_dt.tm_min
                current_sec = now_dt.tm_sec

                # 1. Continuous Exit Monitoring
                curr_prices = {s: self.collector.get_orderbook(s).mid_price for s in self.symbols}
                self.exit_monitor.evaluate_all_positions(curr_prices)

                # 2. 20-Minute Entry Window
                is_window_time = (current_min in self.schedule_minutes and current_sec < 2)
                has_live_data = self.collector.ws_client is not None and self.collector.ws_client.last_msg_ts > 0
                is_warmup_eval = (self.last_eval_time == 0 and has_live_data and (now * 1000 - self.collector.ws_client.last_msg_ts < 5000))

                if (is_window_time or is_warmup_eval) and (now - self.last_eval_time > 15):
                    self.last_eval_time = now
                    await self._execute_evaluation()

            except Exception as e:
                print("Error in main loop:", e)

            await asyncio.sleep(1.0)

    async def _execute_evaluation(self):
        self.risk_gate.on_window_tick()
        snapshots = {s: self.feature_engine.create_snapshot(s) for s in self.symbols}
        self.cached_evaluations = self.selector.scan_all_symbols(snapshots)

        for opp in self.cached_evaluations:
            if opp.passed_validation and opp.strategy in [StrategyType.MOMENTUM_LONG, StrategyType.MOMENTUM_SHORT, StrategyType.SPOT_PERP_ARBITRAGE]:
                snap = snapshots[opp.symbol]
                risk_dec = self.risk_gate.evaluate_proposal(
                    opp=opp,
                    snapshot=snap,
                    account_equity=self.broker.get_equity(),
                    current_positions=self.broker.get_positions()
                )

                if risk_dec.approved and risk_dec.position_size > 0:
                    side = OrderSide.BUY if "LONG" in opp.strategy.value or opp.strategy == StrategyType.SPOT_PERP_ARBITRAGE else OrderSide.SELL
                    pos = self.broker.open_position(
                        symbol=opp.symbol,
                        side=side,
                        quantity=risk_dec.position_size,
                        price=snap.mid_price,
                        leverage=risk_dec.leverage,
                        trace_id=f"gate_{int(time.time())}"
                    )
                    if pos:
                        self.audit_logs.append({
                            "time": time.strftime("%H:%M:%S"),
                            "tag": "[OPEN]",
                            "message": f"開倉 {pos.side.value} {pos.symbol}: ${pos.entry_price:.5f} x {pos.quantity:.2f} (槓桿 {pos.leverage}x)"
                        })

    async def handle_get_data(self, request):
        now = time.time()
        now_dt = time.localtime(now)
        current_min = now_dt.tm_min
        current_sec = now_dt.tm_sec

        next_targets = [(m - current_min) * 60 - current_sec for m in self.schedule_minutes if (m - current_min) * 60 - current_sec > 0]
        next_sec = min(next_targets) if next_targets else (60 - current_min + self.schedule_minutes[0]) * 60 - current_sec

        # Market dict
        market_dict = {}
        for s in self.symbols:
            book = self.collector.get_orderbook(s)
            market_dict[s] = {
                "price": book.mid_price,
                "spread_bps": round(book.spread_bps, 1),
                "obi_5": round(book.calculate_obi(5), 2),
                "is_stale": book.is_stale(),
                "regime": "RANGE"
            }

        for ev in self.cached_evaluations:
            if ev.symbol in market_dict:
                market_dict[ev.symbol]["regime"] = ev.strategy.value

        # Positions dict
        positions_dict = {}
        for s, p in self.broker.get_positions().items():
            positions_dict[s] = {
                "symbol": p.symbol,
                "side": p.side.value,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "margin": p.margin,
                "leverage": p.leverage,
                "unrealized_pnl": p.unrealized_pnl,
                "net_roi": p.net_roi,
                "peak_roi": p.peak_roi,
                "trailing_stop_active": p.trailing_stop_active,
                "trace_id": p.trace_id
            }

        # Calculations
        equity = self.broker.get_equity()
        avail = self.broker.get_available_balance()
        used_margin = sum(p.margin for p in self.broker.get_positions().values())
        unrealized = sum(p.unrealized_pnl for p in self.broker.get_positions().values())

        eval_list = [ev.model_dump() for ev in self.cached_evaluations]

        total_trades = len(self.broker.trade_history)
        wins = [t for t in self.broker.trade_history if t.get("net_pnl", 0) > 0]
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

        dd_pct = (self.risk_gate.peak_equity - equity) / self.risk_gate.peak_equity * 100.0 if self.risk_gate.peak_equity > 0 else 0.0

        payload = {
            "equity": equity,
            "available_balance": avail,
            "used_margin": used_margin,
            "unrealized_pnl": unrealized,
            "daily_pnl": self.risk_gate.daily_pnl,
            "current_drawdown_pct": max(0.0, dd_pct),
            "win_rate_pct": win_rate,
            "total_trades": total_trades,
            "kill_switch_active": self.kill_switch.is_active,
            "next_window_seconds": max(0, next_sec),
            "market": market_dict,
            "evaluations": eval_list,
            "positions": positions_dict,
            "audit_logs": self.audit_logs
        }
        return web.json_response(payload)

    async def handle_trigger_scan(self, request):
        await self._execute_evaluation()
        self.audit_logs.append({
            "time": time.strftime("%H:%M:%S"),
            "tag": "[TRIGGER]",
            "message": "手動觸發 20 分鐘新進場審核窗口"
        })
        return web.json_response({"status": "ok"})

    async def handle_kill_switch(self, request):
        if self.kill_switch.is_active:
            self.kill_switch.reset("USER_WEB")
            self.audit_logs.append({
                "time": time.strftime("%H:%M:%S"),
                "tag": "[RESET]",
                "message": "手動解除 Kill Switch 緊急停止"
            })
        else:
            self.kill_switch.trigger("USER_WEB_TRIGGERED")
            self.audit_logs.append({
                "time": time.strftime("%H:%M:%S"),
                "tag": "[ALERT]",
                "message": "手動啟用 Kill Switch 緊急停止！禁止所有新開倉"
            })
        return web.json_response({"status": "ok", "is_active": self.kill_switch.is_active})

    def run(self):
        app = web.Application()
        app.router.add_get("/api/data", self.handle_get_data)
        app.router.add_post("/api/trigger_scan", self.handle_trigger_scan)
        app.router.add_post("/api/kill_switch", self.handle_kill_switch)
        # Serve static web directory
        app.router.add_static("/", path="web", show_index=True)

        app.on_startup.append(self.start_background_tasks)
        app.on_cleanup.append(self.cleanup_background_tasks)

        print(f"\n=======================================================")
        print(f"🚀 Quant Dashboard Web Server running at:")
        print(f"👉 http://localhost:{self.port}")
        print(f"=======================================================\n")
        web.run_app(app, host="127.0.0.1", port=self.port, print=None)


if __name__ == "__main__":
    server = QuantWebServer(port=8080)
    server.run()
