"""
Quant Performance Metrics Calculator
Net Return, Sharpe, Sortino, MDD, Calmar, Profit Factor, Win Rate, Expectancy
"""
from typing import List, Dict, Any
import numpy as np


def calculate_metrics(
    initial_equity: float,
    equity_curve: List[float],
    trade_history: List[dict]
) -> Dict[str, Any]:
    if not equity_curve:
        return {}

    eq_arr = np.array(equity_curve)
    final_equity = float(eq_arr[-1])
    total_net_return_pct = ((final_equity - initial_equity) / initial_equity) * 100.0

    # Drawdown series
    running_max = np.maximum.accumulate(eq_arr)
    drawdowns = (running_max - eq_arr) / running_max
    max_drawdown_pct = float(np.max(drawdowns)) * 100.0

    # Periodic returns
    returns = np.diff(eq_arr) / eq_arr[:-1]
    if len(returns) > 1 and np.std(returns) > 0:
        # Annualized Sharpe (assuming 20-min bars = 72 bars/day * 365 = 26,280 periods/yr)
        annual_factor = np.sqrt(26280)
        sharpe_ratio = float((np.mean(returns) / np.std(returns)) * annual_factor)

        # Sortino (downside deviation)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and np.std(downside_returns) > 0:
            sortino_ratio = float((np.mean(returns) / np.std(downside_returns)) * annual_factor)
        else:
            sortino_ratio = sharpe_ratio
    else:
        sharpe_ratio = 0.0
        sortino_ratio = 0.0

    calmar_ratio = total_net_return_pct / max_drawdown_pct if max_drawdown_pct > 0 else 0.0

    # Trade-level statistics
    total_trades = len(trade_history)
    if total_trades > 0:
        pnls = [t["net_pnl"] for t in trade_history]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = (len(wins) / total_trades) * 100.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        expectancy = float(np.mean(pnls))
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
    else:
        win_rate = 0.0
        profit_factor = 0.0
        expectancy = 0.0
        avg_win = 0.0
        avg_loss = 0.0

    return {
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "net_return_pct": round(total_net_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "sortino_ratio": round(sortino_ratio, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "expectancy_usd": round(expectancy, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2)
    }
