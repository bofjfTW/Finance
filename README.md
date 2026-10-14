# 加密貨幣 Multi-Agent 量化交易系統 (Crypto Multi-Agent Quant Trading Bot)

根據《計畫書 v1.1》(1.docx) 與《P1–P15 詳細工程計畫書 v2.0》(2.docx) 完整實作之量化交易與 AI 研究系統。

---

## 📌 系統核心規格與交易規則

| 規則項目 | 系統實作規格 | 設計說明 |
| :--- | :--- | :--- |
| **交易標的** | **DOGE / PEPE / WIF / BONK** | 針對 BingX 永續合約 (`DOGE-USDT`, `1000PEPE-USDT`, `WIF-USDT`, `1000BONK-USDT`) 與現貨市場 |
| **進場評估節奏** | **每 20 分鐘一次 (每小時 00 / 20 / 40 分)** | 20 分鐘為新進場決策窗口；若無足夠 Edge 允許選擇 `NO_TRADE` |
| **選幣機制** | **Best Opportunity 1～2 標的** | 四幣同時掃描排序，最多同時持有 1～2 個最高期望值機會 |
| **停利機制 (TP)** | **+15% 起啟動追蹤停利；+30% 硬停利** | 持續監控（Continuous Exit），達到 +15% 啟動 Trailing Stop，達 +30% 強制出場 |
| **止損機制 (SL)** | **-5%～-10% 動態止損；-10% 硬止損上限** | 低波動/訊號逆轉 -5% 先退，-10% 嚴格硬上限 |
| **槓桿與單筆風控** | **最高 5×（預設 2×），帳戶單筆風險上限 1%** | 採 Stop-Distance 倉位公式動態計算保證金與部位大小 |
| **風控機制** | **15 項風控 + Kill Switch 最高否決權** | 包含點差爆炸過濾、滑價扣除、日損上限、MDD 20% 限制與緊急停止 |

---

## 🏗️ 系統架構圖 (Event-Driven & Multi-Agent)

```
BingX Perpetual WS & Spot WS (GZIP Stream)
                 │
                 ▼
      [Real-Time Data Engine]
   (OrderBook Depth / Trades / Multi-TF Candles)
                 │
                 ▼
       [Feature Engine]
   (Technical / OrderFlow OBI / Spread bps / Basis)
                 │
                 ▼
       [Multi-Agent Layer]
   ┌───────────────────────┬───────────────────────┐
   │ Market Regime Agent   │ Technical Agent       │
   │ Order Book Agent      │ Arbitrage Agent       │
   └───────────────────────┴───────────────────────┘
                 │
                 ▼
  [20-Min Strategy Selector & Opportunity Ranker]
         (Top 1~2 Best Coins or NO_TRADE)
                 │
                 ▼
       [Risk Gate (15 Controls)]  ───────> [REJECT / NO_TRADE]
  (Dynamic Sizing, Leverage Cap, Kill Switch)
                 │
                 ▼
       [Execution Engine]
   (PaperBroker / BingX Connector)
                 │
                 ▼
   [Continuous Exit Monitor (24/7)]
  (Real-Time +15% Trailing / +30% TP / -5%~-10% SL)
```

---

## 🚀 快速啟動指南

### 1. 執行單元與整合測試
驗證訂單簿深度計算、特徵工程、Multi-Agent 決策、風控停損停利以及經紀商撮合：
```bash
python main.py --mode test
```

### 2. 執行歷史回測與 Walk-Forward 模擬
模擬四幣 20 分鐘進場與即時 TP/SL，扣除手續費與滑價後計算 Sharpe、Sortino、MDD、Profit Factor：
```bash
python main.py --mode backtest
```

### 3. 啟動即時模擬盤 (Paper Trading + Rich 即時儀表板)
直接連接 BingX 即時行情 WebSocket（免 API Key、零成本），啟用 20 分鐘排程與即時 TP/SL 監控終端介面：
```bash
python main.py --mode paper
```

---

## 📁 專案目錄結構

```
量化/
├── config/
│   ├── settings.yaml          # 系統交易參數、停利停損比例、風控門檻
│   └── symbols.yaml           # DOGE, PEPE, WIF, BONK 交易對與合約規格
├── exchange/
│   ├── __init__.py
│   ├── base.py                # 交易所介面抽象層
│   └── bingx/
│       ├── __init__.py
│       └── ws.py              # BingX GZIP WebSocket 客戶端 (Perp & Spot)
├── data/
│   ├── __init__.py
│   ├── schema.py              # Pydantic 統一資料模型與 UTC 毫秒事件
│   ├── orderbook.py           # 訂單簿、OBI (5/10/20)、點差與微價格計算
│   ├── candle.py              # 1m, 5m, 15m, 20m 多時間尺度 K 線聚合
│   └── collector.py           # 即時資料收集器與資料健康監控 (Stale 檢查)
├── features/
│   ├── __init__.py
│   ├── technical.py           # 動能、EMA 斜率、ATR、已實現波動度、成交量 Z-Score
│   ├── orderbook_features.py  # 訂單簿深度失衡度、Spread bps 特徵提取
│   ├── basis.py               # 現貨-永續基差 (Basis bps) 與資金成本
│   └── engine.py              # Point-in-time 特徵快照 (FeatureSnapshot) 生成器
├── agents/
│   ├── __init__.py
│   ├── base.py                # BaseAgent 標準輸出契約 (score, confidence, risk)
│   ├── regime_agent.py        # 市場狀態 Agent (趨勢、震盪、高波動、異常)
│   ├── technical_agent.py     # 技術動能 Agent (多時間尺度動能融合)
│   ├── orderbook_agent.py     # 微結構 Agent (OBI、流動性防滑價)
│   ├── arbitrage_agent.py     # 現貨-永續套利 Agent (Net Edge 計算)
│   └── selector.py            # 策略選擇器與四幣 Opportunity 排程器
├── risk/
│   ├── __init__.py
│   ├── kill_switch.py         # 緊急停止開關 (人工與程式雙重觸發)
│   └── risk_gate.py           # 15 項風控過濾門與動態倉位計算器
├── execution/
│   ├── __init__.py
│   ├── base.py                # 經紀商介面
│   ├── paper_broker.py        # 模擬撮合經紀商 (手續費、滑價、保證金與損益帳本)
│   └── exit_monitor.py        # 持續出場引擎 (即時監控 +15%~+30% TP, -5%~-10% SL)
├── backtest/
│   ├── __init__.py
│   ├── engine.py              # 多資產事件回測引擎
│   └── metrics.py             # 量化指標計算 (Sharpe, Sortino, MDD, Expectancy)
├── monitoring/
│   ├── __init__.py
│   └── dashboard.py           # Rich 終端即時儀表板
├── tests/
│   ├── __init__.py
│   └── test_core.py           # 系統核心單元測試
├── requirements.txt           # Python 相依套件列表
├── .env.example               # 環境變數與 API Key 範本
└── main.py                    # 系統主執行入口
```

---

## 📊 模組驗收標準與通過證明

1. **資料引擎 (P1)**：支援 BingX Perpetual & Spot WebSocket GZIP 解壓，自動 Ping/Pong 心跳保活與斷線重連，延遲小於 100ms。
2. **微結構與特徵 (P2)**：精確計算 Top-5/10 OBI 與 Spread bps，並對異常高點差自動觸發風控。
3. **回測引擎 (P3)**：支援 Walk-Forward 測試，手續費與滑價扣除，計算 Sharpe、Sortino、MDD、Profit Factor。
4. **Multi-Agent (P4 & P5)**：四個 Agent 分工協作，Strategy Selector 正確在無顯著 Edge 時發出 `NO_TRADE`。
5. **風控與持續出場 (P6 & P8)**：
   - 部位 ROI >= +15% 時啟動 Trailing Stop。
   - 部位 ROI >= +30% 時觸發 Hard Take-Profit。
   - 部位 ROI <= -5% 時依波動動態預警退出。
   - 部位 ROI <= -10% 時觸發 Hard Stop-Loss 上限強制平倉。
