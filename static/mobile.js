// 移动端专用轻量量化交易前端逻辑

let mChart = null;
let currentSymbol = 'sh600036';
let currentLimit = 300;
let currentStrategy = 'boll_reversion';
let currentPrice = 0.0;
let currentPosShares = 0;
let tradeActionType = 'BUY'; // 'BUY' | 'SELL'

document.addEventListener('DOMContentLoaded', () => {
  // 解析移动端 URL 直达参数
  const urlParams = new URLSearchParams(window.location.search);
  const paramSymbol = urlParams.get('symbol');
  const paramStrategy = urlParams.get('strategy');
  const paramLimit = urlParams.get('limit');

  if (paramSymbol) {
    currentSymbol = paramSymbol;
    const isCMB = currentSymbol === 'sh600036';
    const symName = isCMB ? '招商银行' : '平安银行';
    const symNameElem = document.getElementById('m-chart-symbol-name');
    if (symNameElem) symNameElem.innerText = symName;
    const footerSym = document.getElementById('m-footer-sym');
    if (footerSym) footerSym.innerText = symName;
    const sheetStock = document.getElementById('m-sheet-stock');
    if (sheetStock) sheetStock.innerText = `${symName} (${currentSymbol})`;

    // 更新 Tab 选中状态
    document.querySelectorAll('.m-sym-tab').forEach(tab => {
      if (tab.getAttribute('data-symbol') === paramSymbol) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });
  }

  if (paramStrategy) {
    currentStrategy = paramStrategy;
  }
  if (paramLimit) {
    currentLimit = parseInt(paramLimit, 10) || 300;
  }

  initMobileChart();
  bindMobileEvents();
  loadMobileData();
  loadQuotes();
  loadSimAccount();
  loadSyncStatus();

  // 轮询行情与账户 (每 5 秒)
  setInterval(() => {
    loadQuotes();
    loadSimAccount();
  }, 5000);

  // 轮询开盘同步状态 (每 10 秒)
  setInterval(() => {
    loadSyncStatus();
  }, 10000);
});

// 初始化 ECharts 触控优化图表
function initMobileChart() {
  const dom = document.getElementById('mobile-kline-chart');
  if (!dom) return;
  mChart = echarts.init(dom, 'dark');
  window.addEventListener('resize', () => mChart && mChart.resize());
}

// 绑定交互事件
function bindMobileEvents() {
  // 标的切换 Tab
  document.querySelectorAll('.m-sym-tab').forEach(tab => {
    tab.addEventListener('click', (e) => {
      const btn = e.currentTarget;
      document.querySelectorAll('.m-sym-tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      currentSymbol = btn.getAttribute('data-symbol');
      
      const isCMB = currentSymbol === 'sh600036';
      document.getElementById('m-chart-symbol-name').innerText = isCMB ? '招商银行' : '平安银行';
      document.getElementById('m-footer-sym').innerText = isCMB ? '招商银行' : '平安银行';
      document.getElementById('m-sheet-stock').innerText = `${isCMB ? '招商银行' : '平安银行'} (${currentSymbol})`;

      loadMobileData();
      loadSimAccount();
    });
  });

  // 周期切换按钮
  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      currentLimit = parseInt(e.target.getAttribute('data-limit'), 10);
      loadMobileData();
    });
  });

  // 手动点击顶部同步图标触发同步
  document.getElementById('m-sync-badge')?.addEventListener('click', async () => {
    const textElem = document.getElementById('m-sync-text');
    textElem.innerText = "同步中";
    try {
      const resp = await fetch('/api/sync', { method: 'POST' });
      await resp.json();
      showToast("数据同步成功！");
      loadQuotes();
      loadMobileData();
      loadSyncStatus();
    } catch (e) {
      showToast("同步出错");
    }
  });

  // 底部快速买入/卖出唤起抽屉
  document.getElementById('m-btn-quick-buy')?.addEventListener('click', () => {
    openTradeSheet('BUY');
  });

  document.getElementById('m-btn-quick-sell')?.addEventListener('click', () => {
    openTradeSheet('SELL');
  });

  // 移动端飞书推送设置抽屉交互
  document.getElementById('m-btn-notify-settings')?.addEventListener('click', openMobileNotifySheet);
  document.getElementById('m-notify-mask')?.addEventListener('click', closeMobileNotifySheet);
  document.getElementById('m-notify-close')?.addEventListener('click', closeMobileNotifySheet);
  document.getElementById('m-btn-save-notify')?.addEventListener('click', saveMobileNotifySettings);

  // 抽屉遮罩与关闭
  document.getElementById('m-trade-mask')?.addEventListener('click', closeTradeSheet);
  document.getElementById('m-sheet-close')?.addEventListener('click', closeTradeSheet);

  // 价格微调步进按钮
  document.getElementById('m-step-minus')?.addEventListener('click', () => {
    const input = document.getElementById('m-sheet-price');
    let p = parseFloat(input.value) || currentPrice;
    p = Math.max(0.01, p - 0.05);
    input.value = p.toFixed(2);
    updateEstimate();
  });

  document.getElementById('m-step-plus')?.addEventListener('click', () => {
    const input = document.getElementById('m-sheet-price');
    let p = parseFloat(input.value) || currentPrice;
    p = p + 0.05;
    input.value = p.toFixed(2);
    updateEstimate();
  });

  // 股数预设药丸
  document.querySelectorAll('.pill-share').forEach(pill => {
    pill.addEventListener('click', (e) => {
      document.querySelectorAll('.pill-share').forEach(p => p.classList.remove('active'));
      e.target.classList.add('active');
      const shares = e.target.getAttribute('data-shares');
      document.getElementById('m-sheet-shares').value = shares;
      updateEstimate();
    });
  });

  document.getElementById('m-sheet-shares')?.addEventListener('input', updateEstimate);
  document.getElementById('m-sheet-price')?.addEventListener('input', updateEstimate);

  // 提交交易委托
  document.getElementById('m-sheet-submit')?.addEventListener('click', submitTradeOrder);

  // 模拟账户重置
  document.getElementById('m-btn-reset-acc')?.addEventListener('click', async () => {
    if (confirm("确认重置模拟操盘账户至初始 ¥100,000 资金吗？")) {
      try {
        const resp = await fetch('/api/sim/reset', { method: 'POST' });
        const json = await resp.json();
        showToast(json.message || "账户已重置");
        loadSimAccount();
      } catch (e) {
        showToast("重置失败");
      }
    }
  });
}

// 加载量化分析数据与绘制图表
async function loadMobileData() {
  if (mChart) {
    mChart.showLoading({
      text: '计算中...',
      color: '#38bdf8',
      textColor: '#94a3b8',
      maskColor: 'rgba(7, 10, 17, 0.6)'
    });
  }

  try {
    const resp = await fetch(`/api/analysis?symbol=${currentSymbol}&strategy=${currentStrategy}&limit=${currentLimit}`);
    const json = await resp.json();
    if (json.status === 'success') {
      renderDecisionCard(json.latest_decision, json.strategy_meta);
      renderMetrics(json.metrics);
      renderMobileChart(json.data, json.signals);
    }
  } catch (err) {
    console.error("Mobile load error:", err);
  } finally {
    if (mChart) mChart.hideLoading();
  }
}

// 渲染决策大卡片
function renderDecisionCard(decision, meta) {
  if (!decision) return;
  const card = document.getElementById('m-decision-card');
  const pill = document.getElementById('m-decision-pill');
  const icon = document.getElementById('m-decision-icon');
  const statusTxt = document.getElementById('m-decision-status');
  const title = document.getElementById('m-decision-title');
  const desc = document.getElementById('m-decision-desc');
  const timeTag = document.getElementById('m-decision-time');

  card.className = `m-decision-card status-${decision.action.includes('BUY') ? 'BUY' : (decision.action.includes('SELL') ? 'SELL' : 'WAIT')}`;

  if (decision.action === 'BUY_TRIGGERED') {
    pill.className = 'decision-pill is-buy';
    icon.innerText = '🟢';
    statusTxt.innerText = '买点触发';
  } else if (decision.action === 'BUY_ACTIVE') {
    pill.className = 'decision-pill is-buy';
    icon.innerText = '🟢';
    statusTxt.innerText = '买点跟踪';
  } else if (decision.action === 'SELL_TRIGGERED') {
    pill.className = 'decision-pill is-sell';
    icon.innerText = '🔴';
    statusTxt.innerText = '高抛预警';
  } else if (decision.action === 'SELL_ACTIVE') {
    pill.className = 'decision-pill is-sell';
    icon.innerText = '🔴';
    statusTxt.innerText = '卖点防守';
  } else {
    pill.className = 'decision-pill is-wait';
    icon.innerText = '⚪';
    statusTxt.innerText = '观望等待';
  }

  title.innerText = decision.title || '正在监控高胜率窗口...';
  desc.innerText = `${decision.advice || ''} · ${decision.period_eval || ''}`;
  timeTag.innerText = decision.latest_time ? decision.latest_time.slice(11, 16) : '--:--';

  const plan = decision.plan || {};
  const price = decision.latest_price || currentPrice;
  document.getElementById('m-stat-price').innerText = `¥${price.toFixed(2)}`;
  document.getElementById('m-stat-tp').innerText = plan.take_profit_price ? `¥${plan.take_profit_price.toFixed(2)}` : '--';
  document.getElementById('m-stat-sl').innerText = plan.stop_loss_price ? `¥${plan.stop_loss_price.toFixed(2)}` : '--';
}

// 渲染回测指标
function renderMetrics(metrics) {
  if (!metrics) return;
  document.getElementById('m-metric-winrate').innerText = `${metrics.win_rate_60m || '--'}%`;
  document.getElementById('m-metric-plr').innerText = metrics.profit_loss_ratio ? `${metrics.profit_loss_ratio.toFixed(2)}` : '--';
  document.getElementById('m-metric-buys').innerText = `${metrics.buy_count || 0}次`;
  document.getElementById('m-metric-sells').innerText = `${metrics.sell_count || 0}次`;
}

// 渲染手机专属 ECharts K线图
function renderMobileChart(data, signals) {
  if (!mChart || !data || data.length === 0) return;

  const dates = data.map(d => d.datetime.slice(5, 16));
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high]);
  const bollMid = data.map(d => d.boll_mid);
  const bollUp = data.map(d => d.boll_up);
  const bollLow = data.map(d => d.boll_low);

  // 标出买卖点 MarkPoint
  const markPoints = [];
  if (signals && signals.length > 0) {
    signals.forEach(sig => {
      const idx = data.findIndex(d => d.datetime === sig.datetime);
      if (idx !== -1) {
        const isBuy = sig.type === 'BUY';
        markPoints.push({
          name: isBuy ? '买入' : '卖出',
          coord: [dates[idx], isBuy ? data[idx].low * 0.998 : data[idx].high * 1.002],
          value: isBuy ? 'B' : 'S',
          itemStyle: {
            color: isBuy ? '#10b981' : '#ef4444'
          },
          symbolSize: 22
        });
      }
    });
  }

  const option = {
    backgroundColor: 'transparent',
    animation: false,
    grid: {
      left: '2%',
      right: '2%',
      top: '8%',
      bottom: '12%',
      containLabel: true
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      textStyle: { color: '#f8fafc', fontSize: 11 },
      formatter: function(params) {
        if (!params || params.length === 0) return '';
        const item = params[0];
        const d = data[item.dataIndex];
        if (!d) return '';
        const isUp = d.close >= d.open;
        const color = isUp ? '#ef4444' : '#10b981';
        return `
          <div style="font-weight:700; margin-bottom:2px;">${d.datetime.slice(5, 16)}</div>
          <div>现价: <b style="color:${color}">${d.close.toFixed(2)}</b></div>
          <div>开: ${d.open.toFixed(2)} 高: ${d.high.toFixed(2)} 低: ${d.low.toFixed(2)}</div>
        `;
      }
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { show: false }
    },
    yAxis: {
      scale: true,
      position: 'right',
      axisLine: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } }
    },
    dataZoom: [
      {
        type: 'inside',
        start: 70,
        end: 100,
        zoomOnTouch: true,
        moveOnTouch: true
      }
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ef4444',
          color0: '#10b981',
          borderColor: '#ef4444',
          borderColor0: '#10b981'
        },
        markPoint: {
          data: markPoints,
          label: {
            fontSize: 10,
            fontWeight: 'bold',
            color: '#fff'
          }
        }
      },
      {
        name: 'BOLL上轨',
        type: 'line',
        data: bollUp,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1, color: 'rgba(244, 63, 94, 0.5)', type: 'dashed' }
      },
      {
        name: 'BOLL中轨',
        type: 'line',
        data: bollMid,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1, color: 'rgba(56, 189, 248, 0.6)' }
      },
      {
        name: 'BOLL下轨',
        type: 'line',
        data: bollLow,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1, color: 'rgba(16, 185, 129, 0.5)', type: 'dashed' }
      }
    ]
  };

  mChart.setOption(option, true);
}

// 加载实时行情
async function loadQuotes() {
  try {
    const resp = await fetch('/api/quotes');
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      const quotes = json.data;
      const cmb = quotes['sh600036'];
      const pab = quotes['sz000001'];

      if (cmb) {
        document.getElementById('cmb-live-price').innerText = cmb.price.toFixed(2);
        const isUp = cmb.change >= 0;
        document.getElementById('cmb-live-pct').innerText = `${isUp ? '+' : ''}${cmb.change_pct.toFixed(2)}%`;
        document.getElementById('cmb-live-pct').className = `sym-pct ${isUp ? 'is-up' : 'is-down'}`;
      }

      if (pab) {
        document.getElementById('pab-live-price').innerText = pab.price.toFixed(2);
        const isUp = pab.change >= 0;
        document.getElementById('pab-live-pct').innerText = `${isUp ? '+' : ''}${pab.change_pct.toFixed(2)}%`;
        document.getElementById('pab-live-pct').className = `sym-pct ${isUp ? 'is-up' : 'is-down'}`;
      }

      const activeQuote = quotes[currentSymbol];
      if (activeQuote) {
        currentPrice = activeQuote.price;
        document.getElementById('m-footer-price').innerText = `¥${currentPrice.toFixed(2)}`;
      }
    }
  } catch (e) {
    console.error("Quotes load error:", e);
  }
}

// 加载模拟操盘账户
async function loadSimAccount() {
  try {
    const resp = await fetch(`/api/sim/account?symbol=${currentSymbol}`);
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      const d = json.data;
      document.getElementById('m-acc-total').innerText = `¥${d.total_assets.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
      document.getElementById('m-acc-cash').innerText = `¥${d.cash.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
      
      const pos = d.position || {};
      currentPosShares = pos.shares || 0;
      document.getElementById('m-acc-shares').innerText = `${currentPosShares.toLocaleString()} 股`;
      document.getElementById('m-footer-pos').innerText = `持仓: ${currentPosShares}股`;

      const pnlElem = document.getElementById('m-acc-pnl');
      const isUp = d.total_pnl >= 0;
      pnlElem.innerText = `${isUp ? '+' : ''}¥${d.total_pnl.toFixed(2)} (${isUp ? '+' : ''}${d.total_pnl_pct.toFixed(2)}%)`;
      pnlElem.className = `acc-val ${isUp ? 'up' : 'down'}`;

      document.getElementById('m-sell-sub').innerText = currentPosShares > 0 ? `可卖${currentPosShares}股` : '暂无持仓';
    }
  } catch (e) {
    console.error("Sim account error:", e);
  }
}

// 加载同步调度器状态
async function loadSyncStatus() {
  try {
    const resp = await fetch('/api/sync/status');
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      const data = json.data;
      const dot = document.getElementById('m-sync-dot');
      const txt = document.getElementById('m-sync-text');
      if (data.is_trading_time) {
        dot.className = 'm-dot live';
        txt.innerText = '盘中60s';
      } else {
        dot.className = 'm-dot';
        txt.innerText = '休市待机';
      }
    }
  } catch (e) {
    console.error("Sync status error:", e);
  }
}

// 打开交易抽屉
function openTradeSheet(type) {
  tradeActionType = type;
  const isBuy = type === 'BUY';
  document.getElementById('m-sheet-title').innerText = isBuy ? '🟢 快速买入委托' : '🔴 快速卖出委托';
  document.getElementById('m-sheet-submit').innerText = isBuy ? '确认买入' : '确认卖出';
  document.getElementById('m-sheet-submit').style.background = isBuy ? 
    'linear-gradient(135deg, #10b981 0%, #059669 100%)' : 
    'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)';

  document.getElementById('m-sheet-price').value = currentPrice.toFixed(2);
  
  if (!isBuy && currentPosShares > 0) {
    document.getElementById('m-sheet-shares').value = Math.min(500, currentPosShares);
  } else {
    document.getElementById('m-sheet-shares').value = 500;
  }
  updateEstimate();

  document.getElementById('m-trade-mask').classList.add('show');
  document.getElementById('m-trade-sheet').classList.add('show');
}

function closeTradeSheet() {
  document.getElementById('m-trade-mask').classList.remove('show');
  document.getElementById('m-trade-sheet').classList.remove('show');
}

function updateEstimate() {
  const p = parseFloat(document.getElementById('m-sheet-price').value) || 0;
  const s = parseInt(document.getElementById('m-sheet-shares').value, 10) || 0;
  const est = (p * s * 1.00025);
  document.getElementById('m-sheet-estimate').innerText = `预计成交额: ¥${est.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// 提交委托
async function submitTradeOrder() {
  const p = parseFloat(document.getElementById('m-sheet-price').value);
  const s = parseInt(document.getElementById('m-sheet-shares').value, 10);

  if (!p || p <= 0 || !s || s <= 0 || s % 100 !== 0) {
    showToast("请输入合法的委托价及100的整倍数股数");
    return;
  }

  const btn = document.getElementById('m-sheet-submit');
  btn.disabled = true;
  btn.innerText = "提交中...";

  try {
    const resp = await fetch('/api/sim/trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: currentSymbol,
        type: tradeActionType,
        shares: s,
        price: p,
        note: "移动端快捷下单"
      })
    });
    const json = await resp.json();
    if (json.status === 'success') {
      showToast(json.message);
      closeTradeSheet();
      loadSimAccount();
    } else {
      showToast(json.message || "委托失败");
    }
  } catch (e) {
    showToast("网络请求失败");
  } finally {
    btn.disabled = false;
    btn.innerText = tradeActionType === 'BUY' ? '确认买入' : '确认卖出';
  }
}

function showToast(msg) {
  const toast = document.getElementById('m-toast');
  if (!toast) return;
  toast.innerText = msg;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2200);
}

// ================= 移动端飞书推送设置抽屉管理 =================
async function openMobileNotifySheet() {
  document.getElementById('m-notify-mask')?.classList.add('show');
  document.getElementById('m-notify-sheet')?.classList.add('show');
  await loadMobileNotifySettings();
}

function closeMobileNotifySheet() {
  document.getElementById('m-notify-mask')?.classList.remove('show');
  document.getElementById('m-notify-sheet')?.classList.remove('show');
}

async function loadMobileNotifySettings() {
  const listEl = document.getElementById('m-notify-stocks-list');
  const globalChk = document.getElementById('m-chk-global-push');
  if (listEl) {
    listEl.innerHTML = `<div style="text-align: center; color: #94a3b8; font-size: 12px; padding: 12px;">加载中...</div>`;
  }
  try {
    const resp = await fetch('/api/notify/settings');
    const res = await resp.json();
    if (res.status === 'success' && res.data) {
      if (globalChk) globalChk.checked = Boolean(res.data.global_enabled);
      renderMobileNotifyCards(res.data.stocks || []);
    }
  } catch (e) {
    if (listEl) listEl.innerHTML = `<div style="text-align: center; color: #ef4444; font-size: 12px;">读取失败</div>`;
  }
}

function renderMobileNotifyCards(stocks) {
  const listEl = document.getElementById('m-notify-stocks-list');
  if (!listEl) return;
  listEl.innerHTML = '';

  stocks.forEach(st => {
    const card = document.createElement('div');
    card.className = `m-notify-card ${st.enabled ? '' : 'is-disabled'}`;
    card.setAttribute('data-symbol', st.symbol);

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.15rem;">${st.icon || '📌'}</span>
          <div>
            <span style="font-size: 0.95rem; font-weight: 600; color: #f8fafc;">${st.name}</span>
            <span style="font-size: 0.7rem; font-family: var(--font-mono); color: #94a3b8; margin-left: 4px;">${st.symbol.toUpperCase()}</span>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
          <span class="m-stock-state" style="font-size: 0.72rem; color: ${st.enabled ? '#10b981' : '#64748b'};">
            ${st.enabled ? '已开启' : '已静音'}
          </span>
          <label class="toggle-switch">
            <input type="checkbox" class="m-stock-chk" ${st.enabled ? 'checked' : ''} data-symbol="${st.symbol}">
            <span class="slider"></span>
          </label>
        </div>
      </div>
      <div class="m-pill-row" data-symbol="${st.symbol}">
        <button type="button" class="m-pill-btn ${st.signal_filter === 'ALL' ? 'active' : ''}" data-filter="ALL">全量信号</button>
        <button type="button" class="m-pill-btn ${st.signal_filter === 'BUY_ONLY' ? 'active' : ''}" data-filter="BUY_ONLY">仅买入 (B)</button>
        <button type="button" class="m-pill-btn ${st.signal_filter === 'SELL_ONLY' ? 'active' : ''}" data-filter="SELL_ONLY">仅卖出 (S)</button>
      </div>
    `;

    const chk = card.querySelector('.m-stock-chk');
    const stateLabel = card.querySelector('.m-stock-state');
    chk.addEventListener('change', (e) => {
      const isChecked = e.target.checked;
      card.classList.toggle('is-disabled', !isChecked);
      stateLabel.innerText = isChecked ? '已开启' : '已静音';
      stateLabel.style.color = isChecked ? '#10b981' : '#64748b';
    });

    const pills = card.querySelectorAll('.m-pill-btn');
    pills.forEach(p => {
      p.addEventListener('click', (e) => {
        pills.forEach(other => other.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    listEl.appendChild(card);
  });
}

async function saveMobileNotifySettings() {
  const btn = document.getElementById('m-btn-save-notify');
  const globalChk = document.getElementById('m-chk-global-push');
  const global_enabled = globalChk ? globalChk.checked : true;
  
  const cards = document.querySelectorAll('#m-notify-stocks-list .m-notify-card');
  const stockConfigs = [];

  cards.forEach(card => {
    const symbol = card.getAttribute('data-symbol');
    const chk = card.querySelector('.m-stock-chk');
    const enabled = chk ? chk.checked : true;
    const activePill = card.querySelector('.m-pill-btn.active');
    const signal_filter = activePill ? activePill.getAttribute('data-filter') : 'ALL';
    if (symbol) {
      stockConfigs.push({ symbol, enabled, signal_filter });
    }
  });

  btn.disabled = true;
  btn.innerText = "保存中...";
  try {
    const resp = await fetch('/api/notify/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        global_enabled,
        stocks: stockConfigs
      })
    });
    const res = await resp.json();
    if (res.status === 'success') {
      showToast("✓ 推送设置已生效！");
      closeMobileNotifySheet();
    } else {
      showToast("保存失败: " + (res.message || ""));
    }
  } catch (err) {
    showToast("网络异常");
  } finally {
    btn.disabled = false;
    btn.innerText = "💾 保存推送设置并生效";
  }
}

