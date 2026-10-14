"""
Rich Live Terminal Dashboard
Renders real-time market data, multi-agent decisions, 20-min countdown, positions, and risk metrics.
"""
from typing import Dict, List, Optional
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.align import Align

from data.schema import PositionState, OpportunityEvaluation, MarketRegime


class TradingDashboard:
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def generate_layout(
        self,
        market_data: Dict[str, dict],
        evaluations: List[OpportunityEvaluation],
        positions: Dict[str, PositionState],
        equity: float,
        balance: float,
        daily_pnl: float,
        kill_switch_active: bool,
        next_window_seconds: int,
        last_trade_history: List[dict]
    ) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=7)
        )
        layout["main"].split_row(
            Layout(name="left", ratio=3),
            Layout(name="right", ratio=2)
        )
        layout["left"].split_column(
            Layout(name="market_table", ratio=3),
            Layout(name="position_table", ratio=2)
        )
        layout["right"].split_column(
            Layout(name="opportunity_table", ratio=3),
            Layout(name="risk_summary", ratio=2)
        )

        # Header
        ks_text = "[bold red]KILL SWITCH ACTIVE[/]" if kill_switch_active else "[bold green]SYSTEM HEALTHY[/]"
        mins = next_window_seconds // 60
        secs = next_window_seconds % 60
        header_text = Text.from_markup(
            f"[*] [bold cyan]BingX Multi-Agent Quant Bot v2.0[/] | "
            f"Mode: [yellow]Paper Trading[/] | "
            f"Status: {ks_text} | "
            f"20-min Window: [bold magenta]{mins:02d}:{secs:02d}[/]"
        )
        layout["header"].update(Panel(Align.center(header_text), style="blue"))

        # Market Table
        m_table = Table(title="Live Market & Order Book Microstructure", expand=True)
        m_table.add_column("Symbol", style="cyan", no_wrap=True)
        m_table.add_column("Price (USD)", justify="right")
        m_table.add_column("Spread (bps)", justify="right")
        m_table.add_column("OBI (5)", justify="right")
        m_table.add_column("Regime", justify="center")
        m_table.add_column("Data Health", justify="center")

        for sym, d in market_data.items():
            price = f"${d.get('price', 0):.5f}"
            spread = f"{d.get('spread_bps', 0):.1f}"
            obi = f"{d.get('obi_5', 0):+.2f}"
            regime = d.get("regime", "RANGE")
            regime_color = "green" if "BULL" in regime else ("red" if "BEAR" in regime else "yellow")

            is_stale = d.get("is_stale", False)
            health = "[red]STALE[/]" if is_stale else "[green]LIVE[/]"

            m_table.add_row(sym, price, spread, obi, f"[{regime_color}]{regime}[/]", health)

        layout["left"]["market_table"].update(Panel(m_table, border_style="cyan"))

        # Position Table
        p_table = Table(title="Active Positions (+15%~30% TP | -5%~-10% SL)", expand=True)
        p_table.add_column("Symbol", style="cyan")
        p_table.add_column("Side", justify="center")
        p_table.add_column("Entry / Mark", justify="right")
        p_table.add_column("Margin (Lev)", justify="right")
        p_table.add_column("Net ROI (%)", justify="right")
        p_table.add_column("Status / Trailing", justify="center")

        if not positions:
            p_table.add_row("-", "-", "-", "-", "-", "[dim]No Open Positions[/]")
        else:
            for sym, pos in positions.items():
                side_str = f"[bold green]LONG[/]" if pos.side.value == "LONG" else f"[bold red]SHORT[/]"
                prices = f"{pos.entry_price:.5f} / {pos.current_price:.5f}"
                margin_str = f"${pos.margin:.1f} ({pos.leverage}x)"
                roi_pct = pos.net_roi * 100.0
                roi_color = "green" if roi_pct >= 0 else "red"
                roi_str = f"[{roi_color}]{roi_pct:+.1f}%[/]"

                if pos.trailing_stop_active:
                    status = f"[bold magenta]TRAILING (Pk:{pos.peak_roi*100:.1f}%)[/]"
                elif roi_pct >= 15.0:
                    status = "[bold green]IN TP ZONE[/]"
                elif roi_pct <= -5.0:
                    status = "[bold yellow]IN SL ZONE[/]"
                else:
                    status = "[dim]HOLDING[/]"

                p_table.add_row(sym, side_str, prices, margin_str, roi_str, status)

        layout["left"]["position_table"].update(Panel(p_table, border_style="green"))

        # Opportunity Table
        o_table = Table(title="20-Min Opportunity Scan (Top 1-2 Coins)", expand=True)
        o_table.add_column("Rank", justify="center", width=5)
        o_table.add_column("Symbol", style="cyan")
        o_table.add_column("Strategy", justify="center")
        o_table.add_column("Net Edge", justify="right")
        o_table.add_column("Confidence", justify="right")

        if not evaluations:
            o_table.add_row("-", "-", "[dim]Evaluating...[/]", "-", "-")
        else:
            for ev in evaluations:
                rank_str = str(ev.rank)
                strat_color = "green" if "LONG" in ev.strategy.value else ("red" if "SHORT" in ev.strategy.value else "dim")
                strat_str = f"[{strat_color}]{ev.strategy.value}[/]"
                edge_str = f"{ev.net_edge_bps:+.1f} bps"
                conf_str = f"{ev.confidence*100:.0f}%"
                o_table.add_row(rank_str, ev.symbol, strat_str, edge_str, conf_str)

        layout["right"]["opportunity_table"].update(Panel(o_table, border_style="magenta"))

        # Risk Summary
        unrealized = sum(p.unrealized_pnl for p in positions.values())
        r_table = Table(title="Portfolio & Risk Gate", expand=True)
        r_table.add_column("Metric", style="white")
        r_table.add_column("Value", justify="right", style="bold")

        r_table.add_row("Total Equity", f"${equity:.2f}")
        r_table.add_row("Available Balance", f"${balance:.2f}")
        r_table.add_row("Unrealized PnL", f"${unrealized:+.2f}")
        r_table.add_row("Daily Realized PnL", f"${daily_pnl:+.2f}")
        r_table.add_row("Max Open Symbols Cap", "2 Coins Max")
        r_table.add_row("Research MDD Limit", "20.0%")

        layout["right"]["risk_summary"].update(Panel(r_table, border_style="yellow"))

        # Footer: Recent Trades
        f_table = Table(title="Recent Closed Trades Audit", expand=True)
        f_table.add_column("Time", width=10)
        f_table.add_column("Symbol", style="cyan")
        f_table.add_column("Side")
        f_table.add_column("Net PnL ($)", justify="right")
        f_table.add_column("ROI (%)", justify="right")
        f_table.add_column("Exit Reason")

        recent = last_trade_history[-4:] if last_trade_history else []
        if not recent:
            f_table.add_row("-", "-", "-", "$0.00", "0.0%", "[dim]No closed trades yet[/]")
        else:
            for t in reversed(recent):
                pnl_color = "green" if t["net_pnl"] >= 0 else "red"
                f_table.add_row(
                    time.strftime("%H:%M:%S", time.localtime(t["timestamp"]/1000)),
                    t["symbol"],
                    t["side"],
                    f"[{pnl_color}]${t['net_pnl']:+.2f}[/]",
                    f"[{pnl_color}]{t['roi']*100:+.1f}%[/]",
                    t["reason"][:35]
                )

        layout["footer"].update(Panel(f_table, border_style="dim"))
        return layout
