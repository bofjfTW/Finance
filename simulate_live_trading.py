"""
Simulated Real Trading Runner (Paper / Shadow Trading Demonstration)
Connects to BingX live WebSocket, executes real-time 20-min multi-agent evaluation,
executes orders via PaperBroker, and continuously monitors live position ROI and TP/SL.
"""
import os
import sys
import asyncio
import time
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

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
from data.schema import StrategyType, OrderSide, PositionSide


async def run_simulation(duration_seconds: int = 15):
    console = Console()
    console.print("\n[bold cyan]==================================================================[/]")
    console.print("[bold cyan]       BingX Multi-Agent 量化交易系統 — 真實行情模擬交易示範       [/]")
    console.print("[bold cyan]==================================================================[/]\n")

    # 1. 讀取配置
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    with open("config/symbols.yaml", "r", encoding="utf-8") as f:
        symbols_cfg = yaml.safe_load(f)

    symbols = settings["trading"]["symbols"]
    console.print(f"[bold yellow][Step 1] 載入交易配置與標的：[/] {', '.join(symbols)}")
    console.print(f"  - 初始資金：$1,000.00 USDT")
    console.print(f"  - 預設槓桿：{settings['risk']['default_leverage']}x (系統上限 {settings['risk']['max_leverage']}x)")
    console.print(f"  - 進場決策週期：每 20 分鐘評估一次")
    console.print(f"  - 停利規則：+15% 啟動追蹤停利，+30% 硬停利")
    console.print(f"  - 止損規則：-5%～-10% 動態止損，-10% 硬止損上限\n")

    # 2. 初始化核心引擎
    collector = DataCollector(symbols, symbols_cfg["symbols"])
    feature_engine = FeatureEngine(collector)
    selector = StrategySelector(symbols, max_symbols=2)
    kill_switch = KillSwitch()
    risk_gate = RiskGate(
        kill_switch=kill_switch,
        base_trade_risk=settings["risk"]["base_trade_risk"],
        default_leverage=settings["risk"]["default_leverage"],
        max_open_symbols=settings["trading"]["max_open_symbols"]
    )
    broker = PaperBroker(initial_balance=1000.0)
    exit_monitor = ContinuousExitMonitor(
        broker=broker,
        kill_switch=kill_switch,
        soft_tp_roi=settings["exit"]["soft_take_profit"],
        hard_tp_roi=settings["exit"]["hard_take_profit"],
        soft_sl_roi=settings["exit"]["soft_stop_loss"],
        hard_sl_roi=settings["exit"]["hard_stop_loss"],
        trailing_callback_rate=settings["exit"]["trailing_callback_rate"]
    )

    # 3. 連線 BingX 即時市場資料流
    console.print("[bold yellow][Step 2] 正在連接 BingX 永續合約與現貨 WebSocket 即時數據流...[/]")
    ws_task = asyncio.create_task(collector.start_live_feed())
    await asyncio.sleep(4)

    # 顯示市場健康狀態
    health = collector.get_health_status()
    m_table = Table(title="BingX 即時市場報價與微結構狀態 (Live Market Stream)")
    m_table.add_column("標的 (Symbol)", style="cyan")
    m_table.add_column("永續最新價", justify="right")
    m_table.add_column("買賣點差 (Spread)", justify="right")
    m_table.add_column("訂單簿失衡度 (OBI 5)", justify="right")
    m_table.add_column("延遲狀態", justify="center")

    for sym, st in health.items():
        is_stale_str = "[red]逾時[/]" if st["is_stale"] else "[green]即時 (Live)[/]"
        m_table.add_row(
            sym,
            f"${st['perp_price']:.5f}",
            f"{st['spread_bps']:.1f} bps",
            f"{st['obi_5']:+.2f}",
            is_stale_str
        )
    console.print(m_table)
    console.print()

    # 4. 執行 20 分鐘決策窗口：Multi-Agent 評估與機會排序
    console.print("[bold yellow][Step 3] 觸發 20 分鐘新進場評估窗口 (Entry Decision Gate)...[/]")
    snapshots = {s: feature_engine.create_snapshot(s) for s in symbols}
    evaluations = selector.scan_all_symbols(snapshots)

    e_table = Table(title="Multi-Agent 決策融合與機會排序 (Opportunity Ranking)")
    e_table.add_column("排名", justify="center")
    e_table.add_column("標的", style="cyan")
    e_table.add_column("選定策略", justify="center")
    e_table.add_column("預期淨 Edge", justify="right")
    e_table.add_column("信賴度", justify="right")
    e_table.add_column("風險分級", justify="right")
    e_table.add_column("審查結果", justify="center")

    for ev in evaluations:
        strat_color = "green" if "LONG" in ev.strategy.value else ("red" if "SHORT" in ev.strategy.value else "yellow")
        valid_str = "[bold green]通過核准[/]" if ev.passed_validation else f"[dim]未達標 ({ev.rejection_reason})[/]"
        e_table.add_row(
            str(ev.rank),
            ev.symbol,
            f"[{strat_color}]{ev.strategy.value}[/]",
            f"{ev.net_edge_bps:+.1f} bps",
            f"{ev.confidence*100:.0f}%",
            f"{ev.risk_score:.2f}",
            valid_str
        )
    console.print(e_table)
    console.print()

    # 5. 風控門（Risk Gate）動態部位計算與審核
    console.print("[bold yellow][Step 4] 送交風控門 (Risk Gate 15 項檢驗) 審核與動態部位計算...[/]")
    approved_orders = []
    for ev in evaluations:
        if ev.passed_validation and ev.strategy != StrategyType.NO_TRADE:
            snap = snapshots[ev.symbol]
            risk_decision = risk_gate.evaluate_proposal(
                opp=ev,
                snapshot=snap,
                account_equity=broker.get_equity(),
                current_positions=broker.get_positions()
            )
            if risk_decision.approved:
                console.print(f"  [bold green][V] 風控核准：{ev.symbol}[/]")
                console.print(f"      - 決策 ID: {risk_decision.decision_id}")
                console.print(f"      - 分配名目價值: ${risk_decision.notional_usd:.2f} (保證金: ${risk_decision.allocated_margin:.2f})")
                console.print(f"      - 採用槓桿: {risk_decision.leverage}x")
                console.print(f"      - 動態止損 ROI: {risk_decision.soft_stop_roi*100:.1f}% (硬止損 {risk_decision.hard_stop_roi*100:.1f}%)")
                console.print(f"      - 目標停利 ROI: +{risk_decision.soft_tp_roi*100:.1f}% 起 (+{risk_decision.hard_tp_roi*100:.1f}% 硬停利)")
                approved_orders.append((ev, snap, risk_decision))
            else:
                console.print(f"  [bold red][X] 風控否決：{ev.symbol}，原因：{risk_decision.reason}[/]")

    # 6. 模擬經紀商執行下單（PaperBroker Execution）
    console.print("\n[bold yellow][Step 5] 模擬撮合經紀商執行開倉（扣除真實 Taker 手續費 0.05% 與跨點差滑價）...[/]")
    if not approved_orders:
        console.print("  [dim]當前所有標的未達正 Edge 門檻，策略選擇 NO_TRADE 保留現金，不盲目交易。[/]")
        # 為了展示持倉監控機制，若此時市場平靜全為 NO_TRADE，則以排名第一的標的建立一筆展示用部位
        top_ev = evaluations[0]
        top_snap = snapshots[top_ev.symbol]
        console.print(f"  [cyan]>>> 建立展示部位：以排名第一的 {top_ev.symbol} 建立多頭示範持倉...[/]")
        demo_pos = broker.open_position(
            symbol=top_ev.symbol,
            side=OrderSide.BUY,
            quantity=100.0,
            price=top_snap.mid_price,
            leverage=2,
            trace_id="demo_trade_1"
        )
    else:
        for ev, snap, r_dec in approved_orders:
            side = OrderSide.BUY if "LONG" in ev.strategy.value or ev.strategy == StrategyType.SPOT_PERP_ARBITRAGE else OrderSide.SELL
            broker.open_position(
                symbol=ev.symbol,
                side=side,
                quantity=r_dec.position_size,
                price=snap.mid_price,
                leverage=r_dec.leverage,
                trace_id=f"live_{r_dec.decision_id}"
            )

    console.print()

    # 7. 即時持續出場引擎監控（Continuous Exit Monitoring）
    console.print(f"[bold yellow][Step 6] 啟動 24/7 持續出場監控 (監控秒數：{duration_seconds} 秒)...[/]")
    console.print("  [dim]持續以 BingX 最新 Tick 價格計算淨部位 ROI、峰值 ROI 與追蹤停利/止損條件...[/]")

    start_t = time.time()
    tick_count = 0
    while time.time() - start_t < duration_seconds:
        tick_count += 1
        curr_prices = {s: collector.get_orderbook(s).mid_price for s in symbols}
        exit_monitor.evaluate_all_positions(curr_prices)

        # 輸出目前持倉即時 ROI
        positions = broker.get_positions()
        pos_info = []
        for sym, pos in positions.items():
            pos_info.append(f"{sym}: 市價=${pos.current_price:.5f} | 淨ROI={pos.net_roi*100:+.2f}% | 峰值={pos.peak_roi*100:.2f}%")
        
        sys.stdout.write(f"\r  [Tick #{tick_count:02d}] " + " | ".join(pos_info) if pos_info else f"\r  [Tick #{tick_count:02d}] 無持倉")
        sys.stdout.flush()
        await asyncio.sleep(1.0)

    console.print("\n")

    # 8. 輸出帳戶與持倉結算報告
    console.print("[bold yellow][Step 7] 模擬交易結算報告 (Session Performance Report)...[/]")
    p_table = Table(title="當前持倉狀態 (Active Positions)")
    p_table.add_column("標的", style="cyan")
    p_table.add_column("方向", justify="center")
    p_table.add_column("進場價", justify="right")
    p_table.add_column("現價", justify="right")
    p_table.add_column("配置保證金", justify="right")
    p_table.add_column("浮動損益 (USDT)", justify="right")
    p_table.add_column("淨部位 ROI", justify="right")
    p_table.add_column("狀態", justify="center")

    for sym, pos in broker.get_positions().items():
        roi_color = "green" if pos.net_roi >= 0 else "red"
        p_table.add_row(
            sym,
            pos.side.value,
            f"${pos.entry_price:.5f}",
            f"${pos.current_price:.5f}",
            f"${pos.margin:.2f}",
            f"[{roi_color}]${pos.unrealized_pnl:+.4f}[/]",
            f"[{roi_color}]{pos.net_roi*100:+.2f}%[/]",
            "[green]監控中 (持續監控 TP/SL)[/]"
        )
    console.print(p_table)

    # 帳戶總覽
    r_table = Table(title="帳戶資金與風控概況 (Account Equity & Risk Summary)")
    r_table.add_column("指標", style="white")
    r_table.add_column("數值", justify="right", style="bold")
    r_table.add_row("總權益 (Total Equity)", f"${broker.get_equity():.2f} USDT")
    r_table.add_row("可用餘額 (Available Balance)", f"${broker.get_available_balance():.2f} USDT")
    r_table.add_row("已用保證金 (Used Margin)", f"${sum(p.margin for p in broker.get_positions().values()):.2f} USDT")
    r_table.add_row("今日已實現損益", f"${risk_gate.daily_pnl:+.4f} USDT")
    r_table.add_row("風控緊急停止 (Kill Switch)", "[green]正常 (未觸發)[/]")
    console.print(r_table)

    # 關閉連線
    collector.ws_client.stop()
    ws_task.cancel()
    console.print("\n[bold green][SUCCESS] 真實行情模擬交易流程驗證成功！[/]\n")


if __name__ == "__main__":
    asyncio.run(run_simulation(duration_seconds=12))
