// BingX Multi-Agent Quant Dashboard Client

const symbolMeta = {
  "DOGE-USDT": { name: "Dogecoin", icon: "🐕", decimals: 5 },
  "PEPE-USDT": { name: "Pepe (1000PEPE)", icon: "🐸", decimals: 6 },
  "WIF-USDT": { name: "dogwifhat", icon: "🧢", decimals: 4 },
  "BONK-USDT": { name: "Bonk (1000BONK)", icon: "🦴", decimals: 6 }
};

let previousPrices = {};
let logRecords = [];

async function fetchDashboardData() {
  try {
    const res = await fetch("/api/data");
    if (!res.ok) return;
    const data = await res.json();
    renderDashboard(data);
  } catch (err) {
    console.error("Dashboard fetch error:", err);
  }
}

function renderDashboard(data) {
  // 1. Header Countdown & Status
  const mins = Math.floor(data.next_window_seconds / 60);
  const secs = data.next_window_seconds % 60;
  document.getElementById("countdownTimer").textContent = 
    `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

  const statusPill = document.getElementById("systemStatusPill");
  const statusText = document.getElementById("systemStatusText");
  const btnKill = document.getElementById("btnKillSwitch");

  if (data.kill_switch_active) {
    statusPill.className = "status-pill status-alert";
    statusText.textContent = "已觸發緊急停止 (Kill Switch Active)";
    btnKill.textContent = "✓ 重置 Kill Switch";
    btnKill.className = "btn btn-outline";
  } else {
    statusPill.className = "status-pill status-healthy";
    statusText.textContent = "系統正常運行 (Healthy)";
    btnKill.innerHTML = '<span class="btn-icon">⚠</span> Kill Switch';
    btnKill.className = "btn btn-danger";
  }

  // 2. Metrics Row
  document.getElementById("metricTotalEquity").textContent = `$${data.equity.toFixed(2)}`;
  document.getElementById("metricAvailBalance").textContent = `$${data.available_balance.toFixed(2)}`;
  
  const realizedPnlEl = document.getElementById("metricRealizedPnl");
  const pnlSign = data.daily_pnl >= 0 ? "+" : "";
  realizedPnlEl.textContent = `${pnlSign}$${data.daily_pnl.toFixed(2)}`;
  realizedPnlEl.className = data.daily_pnl >= 0 ? "metric-value font-mono text-success" : "metric-value font-mono text-danger";
  
  const pnlRateEl = document.getElementById("badgePnlRate");
  const pnlRate = (data.daily_pnl / 1000.0) * 100.0;
  pnlRateEl.textContent = `${pnlSign}${pnlRate.toFixed(2)}%`;
  pnlRateEl.className = data.daily_pnl >= 0 ? "metric-badge text-success" : "metric-badge text-danger";

  document.getElementById("metricWinRate").textContent = `${data.win_rate_pct.toFixed(1)}% (${data.total_trades} 筆)`;
  
  const unrealizedEl = document.getElementById("metricUnrealizedPnl");
  const unSign = data.unrealized_pnl >= 0 ? "+" : "";
  unrealizedEl.textContent = `${unSign}$${data.unrealized_pnl.toFixed(2)}`;
  unrealizedEl.className = data.unrealized_pnl >= 0 ? "metric-value font-mono text-success" : "metric-value font-mono text-danger";
  
  document.getElementById("metricUsedMargin").textContent = `$${data.used_margin.toFixed(2)}`;
  document.getElementById("metricMaxDrawdown").textContent = `${data.current_drawdown_pct.toFixed(2)}%`;

  // 3. Render Market Cards
  renderMarketCards(data.market);

  // 4. Render Opportunities Table
  renderOpportunities(data.evaluations);

  // 5. Render Active Positions
  renderPositions(data.positions);

  // 6. Render Audit Logs
  renderAuditLogs(data.audit_logs);
}

function renderMarketCards(market) {
  const container = document.getElementById("marketCardsContainer");
  container.innerHTML = "";

  Object.entries(market).forEach(([sym, m]) => {
    const meta = symbolMeta[sym] || { name: sym, icon: "🪙", decimals: 4 };
    const prevPrice = previousPrices[sym] || m.price;
    const priceChange = m.price >= prevPrice ? "text-success" : "text-danger";
    previousPrices[sym] = m.price;

    const obiPercent = Math.round(((m.obi_5 + 1.0) / 2.0) * 100);
    const obiColorClass = m.obi_5 >= 0 ? "obi-bar-bid" : "obi-bar-ask";

    const regime = m.regime || "RANGE";
    let regimeClass = "regime-range";
    if (regime.includes("BULL")) regimeClass = "regime-bull";
    else if (regime.includes("BEAR")) regimeClass = "regime-bear";

    const card = document.createElement("div");
    card.className = "market-card";
    card.innerHTML = `
      <div class="card-top">
        <div>
          <div class="symbol-name">${meta.icon} ${sym}</div>
          <div class="symbol-desc">${meta.name}</div>
        </div>
        <div class="spread-badge">${m.spread_bps.toFixed(1)} bps</div>
      </div>

      <div class="price-box">
        <div class="price-main font-mono ${priceChange}">$${m.price.toFixed(meta.decimals)}</div>
      </div>

      <div class="obi-container">
        <div class="obi-header">
          <span>買盤失衡 (OBI)</span>
          <span class="font-mono">${m.obi_5 >= 0 ? '+' : ''}${m.obi_5.toFixed(2)}</span>
        </div>
        <div class="obi-track">
          <div class="obi-bar ${obiColorClass}" style="width: ${obiPercent}%"></div>
        </div>
      </div>

      <div class="regime-pill ${regimeClass}">
        ${regime}
      </div>
    `;
    container.appendChild(card);
  });
}

function renderOpportunities(evaluations) {
  const tbody = document.getElementById("oppTableBody");
  tbody.innerHTML = "";

  if (!evaluations || evaluations.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted" style="padding:20px;">正在進行 20 分鐘行情掃描...</td></tr>`;
    return;
  }

  evaluations.forEach((ev) => {
    const isTop = ev.rank <= 2 && ev.passed_validation;
    const rankClass = ev.rank === 1 ? "rank-1" : (ev.rank === 2 ? "rank-2" : "");
    
    let stratBadge = `<span class="badge badge-subtle">${ev.strategy}</span>`;
    if (ev.strategy.includes("LONG")) stratBadge = `<span class="badge" style="background:rgba(16,185,129,0.2);color:#34d399;">LONG 多頭</span>`;
    else if (ev.strategy.includes("SHORT")) stratBadge = `<span class="badge" style="background:rgba(239,68,68,0.2);color:#f87171;">SHORT 空頭</span>`;
    else if (ev.strategy.includes("ARB")) stratBadge = `<span class="badge badge-accent">⚡ 現貨-永續套利</span>`;

    const edgeSign = ev.net_edge_bps >= 0 ? "+" : "";
    const edgeColor = ev.net_edge_bps >= 0 ? "text-success" : "text-muted";

    const statusBadge = ev.passed_validation 
      ? `<span class="badge badge-primary">核准開倉 (Top ${ev.rank})</span>`
      : `<span class="badge badge-subtle">過濾 (未達 Edge)</span>`;

    const tr = document.createElement("tr");
    if (isTop) tr.style.background = "rgba(0, 240, 255, 0.03)";
    tr.innerHTML = `
      <td class="text-center"><span class="rank-badge ${rankClass}">${ev.rank}</span></td>
      <td><strong>${ev.symbol}</strong></td>
      <td>${stratBadge}</td>
      <td class="text-right font-mono ${edgeColor}">${edgeSign}${ev.net_edge_bps.toFixed(1)} bps</td>
      <td class="text-right font-mono">${(ev.confidence * 100).toFixed(0)}%</td>
      <td class="text-center">${statusBadge}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderPositions(positions) {
  const container = document.getElementById("positionsContainer");
  container.innerHTML = "";

  const posList = Object.values(positions);
  if (posList.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding: 40px 20px; color: var(--text-dim);">
        <p style="font-size: 14px; margin-bottom: 6px;">目前無持倉部位 (No Active Positions)</p>
        <p style="font-size: 12px;">系統於每小時 00 / 20 / 40 分執行進場審查，若無高勝率 Edge 則嚴格空手</p>
      </div>
    `;
    return;
  }

  posList.forEach(pos => {
    const roi = pos.net_roi * 100.0;
    const roiSign = roi >= 0 ? "+" : "";
    const roiClass = roi >= 0 ? "text-success" : "text-danger";

    let statusPill = `<span class="badge badge-subtle">持倉中 (Holding)</span>`;
    if (pos.trailing_stop_active) {
      statusPill = `<span class="badge badge-accent">🎯 追蹤停利中 (峰值 ${((pos.peak_roi || 0)*100).toFixed(1)}%)</span>`;
    } else if (roi >= 15.0) {
      statusPill = `<span class="badge" style="background:rgba(16,185,129,0.2);color:#34d399;">到達可出場區 (+15%)</span>`;
    } else if (roi <= -5.0) {
      statusPill = `<span class="badge" style="background:rgba(239,68,68,0.2);color:#fca5a5;">進入動態止損警戒區</span>`;
    }

    const card = document.createElement("div");
    card.className = "position-card";
    card.innerHTML = `
      <div class="position-top">
        <div class="pos-tag">
          <span class="side-pill ${pos.side === 'LONG' ? 'side-long' : 'side-short'}">${pos.side}</span>
          <span style="font-size: 16px; font-weight: 700;">${pos.symbol}</span>
          <span style="font-size: 12px; color: var(--text-dim);">${pos.leverage}x 槓桿</span>
        </div>
        <div class="pos-roi ${roiClass}">${roiSign}${roi.toFixed(2)}%</div>
      </div>

      <div class="pos-details">
        <span>開倉均價：<strong class="font-mono text-muted">$${pos.entry_price.toFixed(5)}</strong></span>
        <span>當前標記價：<strong class="font-mono text-muted">$${pos.current_price.toFixed(5)}</strong></span>
        <span>保證金：<strong class="font-mono text-muted">$${pos.margin.toFixed(2)}</strong></span>
      </div>

      <div class="tpsl-gauge">
        <div class="gauge-track">
          <div class="gauge-marker gauge-marker-sl10" title="硬止損 -10%"></div>
          <div class="gauge-marker gauge-marker-sl5" title="動態止損 -5%"></div>
          <div class="gauge-marker gauge-marker-tp15" title="可停利 +15%"></div>
          <div class="gauge-marker gauge-marker-tp30" title="硬停利 +30%"></div>
          <div class="gauge-fill" style="width: ${Math.min(100, Math.max(5, (roi + 15) * 2.2))}% ; background: ${roi >= 0 ? 'linear-gradient(90deg, #10b981, #00f0ff)' : '#ef4444'}"></div>
        </div>
      </div>

      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>${statusPill}</div>
        <div style="font-size:11px; color:var(--text-dim);">Trace: ${pos.trace_id || 'live'}</div>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderAuditLogs(logs) {
  const container = document.getElementById("auditLogContainer");
  if (!logs || logs.length === 0) {
    container.innerHTML = `<div class="text-dim">尚無交易事件記錄...</div>`;
    return;
  }

  document.getElementById("logCountText").textContent = `${logs.length} 筆記錄`;
  container.innerHTML = "";

  logs.slice(-12).reverse().forEach(log => {
    const div = document.createElement("div");
    div.className = "log-entry";
    div.innerHTML = `
      <span class="log-time">[${log.time}]</span>
      <span class="${log.tag.includes('OPEN') ? 'log-tag-open' : (log.tag.includes('CLOSE') ? 'log-tag-close' : 'log-tag-risk')}">${log.tag}</span>
      <span>${log.message}</span>
    `;
    container.appendChild(div);
  });
}

// Button Events
document.getElementById("btnManualScan").addEventListener("click", async () => {
  try {
    await fetch("/api/trigger_scan", { method: "POST" });
    fetchDashboardData();
  } catch (err) {
    console.error("Scan trigger error:", err);
  }
});

document.getElementById("btnKillSwitch").addEventListener("click", async () => {
  try {
    await fetch("/api/kill_switch", { method: "POST" });
    fetchDashboardData();
  } catch (err) {
    console.error("Kill switch error:", err);
  }
});

// Periodic fetch
fetchDashboardData();
setInterval(fetchDashboardData, 1000);
