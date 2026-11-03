// 银行股 5分钟量化买卖点分析前端核心逻辑

let chart = null;
let currentSymbol = 'sh600036';
let currentAnalysisData = null;
let currentSubIndicator = 'macd'; // 'macd' | 'rsi' | 'index'
let currentFilter = 'ALL';

// 初始化
document.addEventListener('DOMContentLoaded', () => {
  // 解析 URL 参数以支持直达 (例如 ?symbol=sz000001&strategy=boll_reversion)
  const urlParams = new URLSearchParams(window.location.search);
  const paramSymbol = urlParams.get('symbol');
  const paramStrategy = urlParams.get('strategy');
  const paramLimit = urlParams.get('limit');

  if (paramSymbol) {
    currentSymbol = paramSymbol;
    const selSymbol = document.getElementById('select-symbol');
    if (selSymbol) {
      selSymbol.value = paramSymbol;
      const symName = currentSymbol === 'sz000001' ? '平安银行' : '招商银行';
      const chartTitle = document.querySelector('.panel-title');
      if (chartTitle) chartTitle.innerText = `${symName} 5分钟K线与量化决策分析`;
    }
  }
  if (paramStrategy) {
    const selStrat = document.getElementById('select-strategy');
    if (selStrat) selStrat.value = paramStrategy;
  }
  if (paramLimit) {
    const selLimit = document.getElementById('select-limit');
    if (selLimit) selLimit.value = paramLimit;
  }

  initChart();
  bindEvents();
  bindSimEvents();
  loadData();
  loadStats();
  loadQuotes();
  loadSimAccount();
  loadSyncStatus();

  // 定时刷新行情快照与模拟账户盈亏 (每 5 秒)
  setInterval(() => {
    loadQuotes();
    loadSimAccount();
  }, 5000);

  // 定时刷新后台调度同步状态 (每 10 秒)
  setInterval(() => {
    loadSyncStatus();
  }, 10000);
});


// 初始化 ECharts
function initChart() {
  const dom = document.getElementById('main-kline-chart');
  chart = echarts.init(dom, 'dark');
  window.addEventListener('resize', () => chart && chart.resize());
}

// 绑定交互事件
function bindEvents() {
  // 标的切换
  const selSymbol = document.getElementById('select-symbol');
  if (selSymbol) {
    selSymbol.addEventListener('change', (e) => {
      currentSymbol = e.target.value;
      const symName = currentSymbol === 'sz000001' ? '平安银行' : '招商银行';
      const chartTitle = document.querySelector('.panel-title');
      if (chartTitle) {
        chartTitle.innerText = `${symName} 5分钟K线与量化决策分析`;
      }
      loadData();
      loadStats();
      loadSimAccount();
    });
  }

  // 策略切换
  document.getElementById('select-strategy').addEventListener('change', () => loadData());
  // 范围切换
  document.getElementById('select-limit').addEventListener('change', () => loadData());

  // 指标勾选切换
  document.getElementById('chk-boll').addEventListener('change', () => renderChart());
  document.getElementById('chk-ma').addEventListener('change', () => renderChart());
  document.getElementById('chk-signals').addEventListener('change', () => renderChart());

  // 副图指标切换
  document.querySelectorAll('.sub-chart-switch .pill-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.sub-chart-switch .pill-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      currentSubIndicator = e.target.getAttribute('data-sub');
      renderChart();
    });
  });

  // 信号表格筛选
  document.querySelectorAll('.signals-filter .filter-chip').forEach(chip => {
    chip.addEventListener('click', (e) => {
      document.querySelectorAll('.signals-filter .filter-chip').forEach(c => c.classList.remove('active'));
      e.target.classList.add('active');
      currentFilter = e.target.getAttribute('data-filter');
      renderSignalsTable();
    });
  });

  // 手动同步 API
  document.getElementById('btn-manual-sync').addEventListener('click', async () => {
    const btn = document.getElementById('btn-manual-sync');
    const statusText = document.getElementById('sync-status');
    const dot = document.getElementById('live-dot');
    
    btn.disabled = true;
    btn.innerText = "同步中...";
    statusText.innerText = "增量拉取最新数据...";

    try {
      const resp = await fetch('/api/sync', { method: 'POST' });
      const json = await resp.json();
      statusText.innerText = "同步成功!";
      setTimeout(() => { statusText.innerText = "就绪"; }, 3000);
      loadStats();
      loadQuotes();
      loadData();
    } catch (err) {
      console.error(err);
      statusText.innerText = "同步失败，请检查网络";
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none">
          <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
        </svg> 增量同步API
      `;
    }
  });

  // 飞书推送设置弹窗
  document.getElementById('btn-notify-settings')?.addEventListener('click', openNotifySettingsModal);
  document.getElementById('btn-close-notify-modal')?.addEventListener('click', closeNotifySettingsModal);
  document.getElementById('btn-cancel-notify-settings')?.addEventListener('click', closeNotifySettingsModal);
  document.getElementById('modal-notify-settings')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-notify-settings') closeNotifySettingsModal();
  });
  document.getElementById('btn-save-notify-settings')?.addEventListener('click', saveNotifySettings);

  // 测试飞书推送
  document.getElementById('btn-test-feishu')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-test-feishu');
    btn.disabled = true;
    btn.innerText = "发送中...";
    try {
      const resp = await fetch('/api/notify/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: currentSymbol })
      });
      const json = await resp.json();
      if (json.status === 'success' && json.sent) {
        showToast('飞书测试卡片已成功发送！请查看手机飞书', 'success');
      } else {
        showToast('发送失败，请检查 Webhook 配置', 'error');
      }
    } catch (e) {
      console.error(e);
      showToast('发送失败，请检查网络', 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
        </svg> 飞书推送测试
      `;
    }
  });
}

// 加载后台数据同步调度器状态
async function loadSyncStatus() {
  try {
    const resp = await fetch('/api/sync/status');
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      const data = json.data;
      const statusText = document.getElementById('sync-status');
      const dot = document.getElementById('live-dot');
      if (data.is_trading_time) {
        if (dot) dot.className = 'pulse-indicator live';
        if (statusText) {
          statusText.innerText = `盘中自动刷新 (${data.interval_seconds}s)`;
          statusText.title = `A股交易时段中，每 ${data.interval_seconds} 秒自动拉取增量K线入库；上次同步: ${data.last_sync_time || '刚刚'}`;
        }
      } else {
        if (dot) dot.className = 'pulse-indicator';
        if (statusText) {
          statusText.innerText = `休市待机 (${data.interval_seconds}s)`;
          statusText.title = `当前非交易时段，每 ${data.interval_seconds} 秒心跳待机；上次同步: ${data.last_sync_time || '刚刚'}`;
        }
      }
    }
  } catch (err) {
    console.error("Failed to load sync status:", err);
  }
}

// 加载数据库状态
async function loadStats() {
  try {
    const resp = await fetch('/api/stats');
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      const target = json.data[currentSymbol] || json.data['sh600036'];
      if (target) {
        document.getElementById('db-records-count').innerText = `${target.name || currentSymbol}: ${target.bar_count.toLocaleString()} 根 (5M)`;
        if (target.first_time && target.latest_time) {
          document.getElementById('db-time-range').innerText = `${target.first_time.slice(0, 10)} ~ ${target.latest_time.slice(0, 16)}`;
        }
      }
    }
  } catch (err) {
    console.error("Failed to load stats:", err);
  }
}

// 加载实时行情快照
async function loadQuotes() {
  try {
    const resp = await fetch('/api/quotes');
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      const quotes = json.data;
      updateTicker('cmb', quotes['sh600036']);
      updateTicker('pab', quotes['sz000001']);
      updateTicker('idx', quotes['sh000001']);

      const now = new Date();
      document.getElementById('last-refresh-time').innerText = `更新时间: ${now.toTimeString().slice(0, 8)}`;
    }
  } catch (err) {
    console.error("Failed to load quotes:", err);
  }
}

function updateTicker(prefix, data) {
  if (!data) return;
  const pElem = document.getElementById(`${prefix}-price`);
  const pctElem = document.getElementById(`${prefix}-pct`);
  const highElem = document.getElementById(`${prefix}-high`);
  const lowElem = document.getElementById(`${prefix}-low`);

  const isUp = data.change >= 0;
  pElem.innerText = data.price.toFixed(prefix === 'idx' ? 2 : 2);
  pctElem.innerText = `${isUp ? '+' : ''}${data.change_pct.toFixed(2)}%`;
  highElem.innerText = data.high.toFixed(2);
  lowElem.innerText = data.low.toFixed(2);

  pElem.className = `ticker-price ${isUp ? 'is-up' : 'is-down'}`;
  pctElem.className = `ticker-badge ${isUp ? 'is-up-badge' : 'is-down-badge'}`;
}

// 加载量化分析数据
async function loadData() {
  const strategy = document.getElementById('select-strategy').value;
  const limit = document.getElementById('select-limit').value;
  const symbol = document.getElementById('select-symbol') ? document.getElementById('select-symbol').value : currentSymbol;

  chart.showLoading({
    text: '正在计算量化指标与买卖信号...',
    color: '#38bdf8',
    textColor: '#94a3b8',
    maskColor: 'rgba(8, 12, 20, 0.7)'
  });

  try {
    const resp = await fetch(`/api/analysis?symbol=${symbol}&strategy=${strategy}&limit=${limit}`);
    const json = await resp.json();
    if (json.status === 'success') {
      currentAnalysisData = json;
      updateMetrics(json.metrics);
      updateDecisionBanner(json.latest_decision, json.strategy_meta);
      updateStrategyBanner(json.strategy_meta);
      renderChart();
      renderSignalsTable();
    }
  } catch (err) {
    console.error("Analysis load error:", err);
  } finally {
    chart.hideLoading();
  }
}

// 更新顶部实时买卖点决策指引看板
function updateDecisionBanner(decision, meta) {
  if (!decision) return;
  const banner = document.getElementById('action-banner');
  const pill = document.getElementById('decision-status-pill');
  const statusText = document.getElementById('decision-status-text');
  const headline = document.getElementById('decision-headline');
  const subtext = document.getElementById('decision-subtext');
  const planDesc = document.getElementById('decision-plan-desc');
  const timingBadge = document.getElementById('timing-badge');

  banner.className = `action-decision-banner status-${decision.action.includes('BUY') ? 'BUY' : (decision.action.includes('SELL') ? 'SELL' : 'WAIT')}`;

  if (decision.action === 'BUY_TRIGGERED') {
    pill.className = 'decision-status-pill is-buy';
    statusText.innerText = '买点信号触发';
  } else if (decision.action === 'BUY_ACTIVE') {
    pill.className = 'decision-status-pill is-buy';
    statusText.innerText = '买点跟踪中';
  } else if (decision.action === 'SELL_TRIGGERED') {
    pill.className = 'decision-status-pill is-sell';
    statusText.innerText = '卖点/高抛预警';
  } else if (decision.action === 'SELL_ACTIVE') {
    pill.className = 'decision-status-pill is-sell';
    statusText.innerText = '卖点防守中';
  } else {
    pill.className = 'decision-status-pill is-wait';
    statusText.innerText = '建议观望等待';
  }

  headline.innerText = decision.title || '正在监控高胜率窗口...';
  subtext.innerText = `${decision.advice || ''} · ${decision.period_eval || ''}`;
  planDesc.innerText = decision.plan_desc || '暂无特定计划';

  if (timingBadge) {
    timingBadge.className = `timing-badge ${decision.period_grade || 'normal'}`;
    timingBadge.innerText = decision.period_grade === 'golden' ? '🌟 午后优质窗口 (回测胜率>65%)' : (decision.period_grade === 'caution' ? '⚠️ 早盘高噪期 (少动)' : '常态观察期');
  }
}

// 更新选中策略的机制说明条
function updateStrategyBanner(meta) {
  if (!meta) return;
  const tagElem = document.getElementById('strat-banner-tag');
  const textElem = document.getElementById('strat-banner-text');
  const paramsElem = document.getElementById('strat-banner-params');

  if (tagElem) {
    tagElem.innerText = meta.tag || meta.name;
    tagElem.className = `strat-banner-tag ${meta.category === 'benchmark' ? 'benchmark' : ''}`;
  }
  if (textElem) {
    textElem.innerText = meta.description || '';
  }
  if (paramsElem) {
    paramsElem.innerHTML = `
      <span>推荐止盈: <b style="color:var(--up-color)">+${meta.default_take_profit_pct}%</b></span>
      <span>严格止损: <b style="color:var(--down-color)">-${meta.default_stop_loss_pct}%</b></span>
      <span>建议持有时长: <b>${meta.recommended_hold_min} 分钟</b></span>
      <span>风险评级: <b>${meta.risk_level}</b></span>
    `;
  }
}

// 更新回测统计卡片
function updateMetrics(metrics) {
  if (!metrics) return;
  document.getElementById('stat-win30').innerText = `${metrics.win_rate_30m || 0}%`;
  document.getElementById('stat-ret30').innerText = `均值: ${(metrics.avg_return_30m > 0 ? '+' : '')}${metrics.avg_return_30m || 0}%`;

  document.getElementById('stat-win60').innerText = `${metrics.win_rate_60m || 0}%`;
  document.getElementById('stat-ret60').innerText = `均值: ${(metrics.avg_return_60m > 0 ? '+' : '')}${metrics.avg_return_60m || 0}%`;

  document.getElementById('stat-plr').innerText = metrics.profit_loss_ratio || '--';
  const plrSub = document.querySelector('#stat-plr + .metric-sub');
  if (plrSub && metrics.tp_sl_win_rate !== undefined) {
    plrSub.innerHTML = `实测止盈胜率: <b style="color:var(--up-color)">${metrics.tp_sl_win_rate}%</b> (止盈:${metrics.tp_hit_count} 止损:${metrics.sl_hit_count})`;
  } else if (plrSub) {
    plrSub.innerText = '盈利均值 / 亏损均值';
  }

  document.getElementById('stat-signals-count').innerText = `${metrics.total_signals || 0} 次`;
  document.getElementById('stat-buy-cnt').innerText = metrics.buy_count || 0;
  document.getElementById('stat-sell-cnt').innerText = metrics.sell_count || 0;
}


// 渲染 ECharts 5分钟多图联动
function renderChart() {
  if (!currentAnalysisData || !currentAnalysisData.data) return;

  const rawData = currentAnalysisData.data;
  const signals = currentAnalysisData.signals || [];

  const dates = [];
  const klineValues = [];
  const volumes = [];
  const ma5 = [];
  const ma20 = [];
  const ma60 = [];
  const bollUp = [];
  const bollMid = [];
  const bollLow = [];
  const macdDif = [];
  const macdDea = [];
  const macdHist = [];
  const rsi = [];
  const indexClose = [];

  const showBoll = document.getElementById('chk-boll').checked;
  const showMa = document.getElementById('chk-ma').checked;
  const showSignals = document.getElementById('chk-signals').checked;

  // 映射时间戳到信号信息
  const signalMap = new Map();
  signals.forEach(s => signalMap.set(s.datetime, s));

  rawData.forEach(row => {
    dates.push(row.datetime);
    // [open, close, lowest, highest]
    klineValues.push([row.open, row.close, row.low, row.high]);
    volumes.push([row.datetime, row.volume, row.close >= row.open ? 1 : -1]);

    ma5.push(row.ma5 !== null ? row.ma5 : '-');
    ma20.push(row.ma20 !== null ? row.ma20 : '-');
    ma60.push(row.ma60 !== null ? row.ma60 : '-');

    bollUp.push(row.boll_up !== null ? row.boll_up : '-');
    bollMid.push(row.boll_mid !== null ? row.boll_mid : '-');
    bollLow.push(row.boll_low !== null ? row.boll_low : '-');

    macdDif.push(row.macd_dif !== null ? row.macd_dif : 0);
    macdDea.push(row.macd_dea !== null ? row.macd_dea : 0);
    macdHist.push(row.macd_hist !== null ? row.macd_hist : 0);

    rsi.push(row.rsi14 !== null ? row.rsi14 : '-');
    indexClose.push(row.index_close !== null ? row.index_close : '-');
  });

  // 构造 Buy / Sell markPoints
  const markPointsData = [];
  if (showSignals) {
    signals.forEach(s => {
      const isBuy = s.type === 'BUY';
      markPointsData.push({
        name: isBuy ? '买入信号' : '卖出信号',
        coord: [s.datetime, s.price],
        value: isBuy ? 'B' : 'S',
        itemStyle: {
          color: isBuy ? '#ef4444' : '#10b981', // A股：红买绿卖
          borderColor: '#ffffff',
          borderWidth: 1.5,
          shadowBlur: 8,
          shadowColor: isBuy ? 'rgba(239, 68, 68, 0.6)' : 'rgba(16, 185, 129, 0.6)'
        },
        symbol: isBuy ? 'pin' : 'pin',
        symbolSize: 28,
        symbolOffset: [0, isBuy ? 12 : -12],
        symbolRotate: isBuy ? 180 : 0,
        label: {
          show: true,
          formatter: isBuy ? 'B' : 'S',
          color: '#ffffff',
          fontWeight: 'bold',
          fontSize: 11
        },
        rawSignal: s
      });
    });
  }

  // 组装系列
  const series = [
    {
      name: '招商银行K线',
      type: 'candlestick',
      data: klineValues,
      itemStyle: {
        color: '#ef4444',         // 阳线 红
        color0: '#10b981',        // 阴线 绿
        borderColor: '#ef4444',
        borderColor0: '#10b981'
      },
      markPoint: {
        data: markPointsData,
        tooltip: {
          formatter: function (param) {
            const sig = param.data.rawSignal;
            if (!sig) return '';
            const plan = sig.trade_plan || {};
            return `
              <div style="font-size:12px; line-height: 1.6; padding: 2px;">
                <b style="color:${sig.type==='BUY'?'#ef4444':'#10b981'}; font-size:13px;">${sig.type==='BUY'?'🟢 买入信号 (BUY)':'🔴 卖出信号 (SELL)'}</b><br/>
                <b>时间:</b> ${sig.datetime} (${plan.timing_tip || '常规时段'})<br/>
                <b>触发价:</b> ¥${sig.price}<br/>
                <div style="margin: 4px 0; padding: 4px 6px; background: rgba(15,23,42,0.8); border-radius: 4px; border: 1px dashed rgba(56,189,248,0.4);">
                  <b>🎯 目标止盈:</b> <span style="color:#ef4444; font-weight:bold;">¥${plan.take_profit_price || '--'} (${plan.take_profit_pct || '--'})</span><br/>
                  <b>🛡️ 严格止损:</b> <span style="color:#10b981; font-weight:bold;">¥${plan.stop_loss_price || '--'} (${plan.stop_loss_pct || '--'})</span><br/>
                  <b>⏱️ 建议持有:</b> <span style="color:#38bdf8;">${plan.recommended_hold_min || 60} 分钟</span>
                </div>
                <b>依据:</b> <span style="color:#cbd5e1;">${sig.reason}</span><br/>
                ${sig.ret_30m !== null ? `<b>后续30M实测:</b> <span style="color:${sig.ret_30m>=0?'#ef4444':'#10b981'}; font-weight:bold;">${sig.ret_30m>0?'+':''}${sig.ret_30m}%</span><br/>`:''}
                ${sig.ret_60m !== null ? `<b>后续60M实测:</b> <span style="color:${sig.ret_60m>=0?'#ef4444':'#10b981'}; font-weight:bold;">${sig.ret_60m>0?'+':''}${sig.ret_60m}%</span>`:''}
              </div>
            `;
          }
        }
      }

    },
    // 成交量
    {
      name: '成交量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: volumes.map(v => ({
        value: v[1],
        itemStyle: {
          color: v[2] === 1 ? 'rgba(239, 68, 68, 0.7)' : 'rgba(16, 185, 129, 0.7)'
        }
      }))
    }
  ];

  // 均线
  if (showMa) {
    series.push(
      { name: 'MA5', type: 'line', data: ma5, smooth: true, lineStyle: { width: 1.2, color: '#facc15' }, showSymbol: false },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { width: 1.2, color: '#38bdf8' }, showSymbol: false },
      { name: 'MA60', type: 'line', data: ma60, smooth: true, lineStyle: { width: 1.5, color: '#c084fc' }, showSymbol: false }
    );
  }

  // 布林带
  if (showBoll) {
    series.push(
      { name: 'BOLL上轨', type: 'line', data: bollUp, lineStyle: { width: 1, type: 'dashed', color: 'rgba(244, 63, 94, 0.7)' }, showSymbol: false },
      { name: 'BOLL中轨', type: 'line', data: bollMid, lineStyle: { width: 1, color: 'rgba(148, 163, 184, 0.5)' }, showSymbol: false },
      { name: 'BOLL下轨', type: 'line', data: bollLow, lineStyle: { width: 1, type: 'dashed', color: 'rgba(52, 211, 153, 0.7)' }, showSymbol: false }
    );
  }

  // 副图系列根据切换展示
  if (currentSubIndicator === 'macd') {
    series.push(
      { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macdDif, lineStyle: { width: 1.2, color: '#38bdf8' }, showSymbol: false },
      { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macdDea, lineStyle: { width: 1.2, color: '#f59e0b' }, showSymbol: false },
      {
        name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
        data: macdHist.map(h => ({
          value: h,
          itemStyle: { color: h >= 0 ? '#ef4444' : '#10b981' }
        }))
      }
    );
  } else if (currentSubIndicator === 'rsi') {
    series.push(
      { name: 'RSI(14)', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: rsi, lineStyle: { width: 1.5, color: '#a855f7' }, showSymbol: false }
    );
  } else if (currentSubIndicator === 'index') {
    series.push(
      { name: '上证指数', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: indexClose, lineStyle: { width: 1.5, color: '#38bdf8' }, showSymbol: false }
    );
  }

  const option = {
    animation: false,
    backgroundColor: 'transparent',
    legend: {
      data: ['招商银行K线', 'MA5', 'MA20', 'MA60', 'BOLL上轨', 'BOLL下轨', '成交量', 'DIF', 'DEA', 'MACD柱', 'RSI(14)', '上证指数'],
      selected: {
        'BOLL上轨': showBoll,
        'BOLL中轨': showBoll,
        'BOLL下轨': showBoll,
        'MA5': showMa,
        'MA20': showMa,
        'MA60': showMa
      },
      top: 0,
      left: 10,
      textStyle: { color: '#94a3b8', fontSize: 11 }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: '#475569', type: 'dashed' } },
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      borderColor: '#334155',
      borderWidth: 1,
      textStyle: { color: '#f8fafc', fontSize: 12 },
      formatter: function (params) {
        if (!params || !params.length) return '';
        const date = params[0].axisValue;
        const klineParam = params.find(p => p.seriesName === '招商银行K线');
        const volParam = params.find(p => p.seriesName === '成交量');
        const sig = signalMap.get(date);

        let html = `<div style="padding:2px 4px; min-width:180px;">`;
        html += `<div style="font-weight:600; color:#38bdf8; margin-bottom:4px;">${date}</div>`;

        if (sig) {
          html += `
            <div style="background:${sig.type==='BUY'?'rgba(239,68,68,0.2)':'rgba(16,185,129,0.2)'}; 
                        border-left:3px solid ${sig.type==='BUY'?'#ef4444':'#10b981'};
                        padding:3px 6px; margin:4px 0; border-radius:2px; font-size:11px;">
              <b style="color:${sig.type==='BUY'?'#ef4444':'#10b981'}">${sig.type==='BUY'?'🟢 买入触发':'🔴 卖出触发'}</b>: ${sig.reason}
            </div>
          `;
        }

        if (klineParam && klineParam.data) {
          const [o, c, l, h] = klineParam.data;
          const isUp = c >= o;
          html += `
            <div style="display:flex; justify-content:space-between; margin-top:2px;">
              <span style="color:#94a3b8">开盘 / 收盘:</span>
              <span>${o.toFixed(2)} / <b style="color:${isUp?'#ef4444':'#10b981'}">${c.toFixed(2)}</b></span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-top:2px;">
              <span style="color:#94a3b8">最高 / 最低:</span>
              <span>${h.toFixed(2)} / ${l.toFixed(2)}</span>
            </div>
          `;
        }

        if (volParam) {
          html += `
            <div style="display:flex; justify-content:space-between; margin-top:2px;">
              <span style="color:#94a3b8">成交量:</span>
              <span>${(volParam.value / 10000).toFixed(1)} 万股</span>
            </div>
          `;
        }

        html += `</div>`;
        return html;
      }
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: '4%', right: '3%', top: '7%', height: '52%' },    // 主K线
      { left: '4%', right: '3%', top: '63%', height: '14%' },   // 成交量
      { left: '4%', right: '3%', top: '80%', height: '14%' }    // 副图指标
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        scale: true,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { show: false },
        splitLine: { show: true, lineStyle: { color: 'rgba(51, 65, 85, 0.25)' } }
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        scale: true,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { show: false },
        splitLine: { show: true, lineStyle: { color: 'rgba(51, 65, 85, 0.25)' } }
      },
      {
        type: 'category',
        gridIndex: 2,
        data: dates,
        scale: true,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: {
          color: '#94a3b8',
          fontSize: 10,
          formatter: v => v.slice(5, 16)
        },
        splitLine: { show: true, lineStyle: { color: 'rgba(51, 65, 85, 0.25)' } }
      }
    ],
    yAxis: [
      {
        scale: true,
        axisLine: { lineStyle: { color: '#334155' } },
        splitLine: { lineStyle: { color: 'rgba(51, 65, 85, 0.25)' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 }
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLine: { lineStyle: { color: '#334155' } },
        splitLine: { show: false },
        axisLabel: {
          color: '#64748b',
          fontSize: 9,
          formatter: v => (v / 10000).toFixed(0) + 'w'
        }
      },
      {
        scale: true,
        gridIndex: 2,
        splitNumber: 2,
        axisLine: { lineStyle: { color: '#334155' } },
        splitLine: { lineStyle: { color: 'rgba(51, 65, 85, 0.25)' } },
        axisLabel: { color: '#64748b', fontSize: 9 }
      }
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1, 2],
        start: 70,
        end: 100
      },
      {
        show: true,
        xAxisIndex: [0, 1, 2],
        type: 'slider',
        top: '96%',
        height: 16,
        borderColor: '#334155',
        backgroundColor: '#0f172a',
        dataBackground: {
          lineStyle: { color: '#38bdf8' },
          areaStyle: { color: 'rgba(56, 189, 248, 0.1)' }
        },
        selectedDataBackground: {
          lineStyle: { color: '#ef4444' },
          areaStyle: { color: 'rgba(239, 68, 68, 0.2)' }
        },
        fillerColor: 'rgba(56, 189, 248, 0.25)',
        textStyle: { color: '#94a3b8' }
      }
    ],
    series: series
  };

  chart.setOption(option, true);
}

// 渲染买卖点信号表格
function renderSignalsTable() {
  const tbody = document.getElementById('signals-tbody');
  if (!currentAnalysisData || !currentAnalysisData.signals) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-td">无信号数据</td></tr>`;
    return;
  }

  let signals = currentAnalysisData.signals;
  if (currentFilter !== 'ALL') {
    signals = signals.filter(s => s.type === currentFilter);
  }

  if (signals.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-td">当前筛选条件下无信号记录</td></tr>`;
    return;
  }

  // 按时间倒序展示（最近的在前）
  const reversed = [...signals].reverse();

  let html = '';
  reversed.forEach(s => {
    const isBuy = s.type === 'BUY';
    const ret30 = s.ret_30m !== null ? s.ret_30m : null;
    const ret60 = s.ret_60m !== null ? s.ret_60m : null;
    const plan = s.trade_plan || {};

    html += `
      <tr>
        <td style="font-family:var(--font-mono); font-size:11px; white-space:nowrap;">${s.datetime}</td>
        <td>
          <span class="badge-signal ${s.type}">
            ${isBuy ? '🟢 买点 (B)' : '🔴 卖点 (S)'}
          </span>
        </td>
        <td style="font-family:var(--font-mono); font-weight:700;">¥${s.price.toFixed(2)}</td>
        <td class="sl-tag">
          ${plan.stop_loss_price ? `¥${plan.stop_loss_price} <span style="font-size:10px; color:#10b981;">(${plan.stop_loss_pct})</span>` : '--'}
        </td>
        <td class="tp-tag">
          ${plan.take_profit_price ? `¥${plan.take_profit_price} <span style="font-size:10px; color:#ef4444;">(${plan.take_profit_pct})</span>` : '--'}
        </td>
        <td class="hold-tag">
          ${plan.recommended_hold_min ? `${plan.recommended_hold_min}m` : '--'}
        </td>
        <td style="color:#cbd5e1; max-width: 300px; font-size:12px;">${s.reason}</td>
        <td>
          ${ret30 !== null ? `<span style="font-family:var(--font-mono); font-weight:600; color:${ret30 >= 0 ? '#ef4444' : '#10b981'}">${ret30 > 0 ? '+' : ''}${ret30}%</span>` : '<span style="color:#64748b">样本外</span>'}
        </td>
        <td>
          ${ret60 !== null ? `<span style="font-family:var(--font-mono); font-weight:600; color:${ret60 >= 0 ? '#ef4444' : '#10b981'}">${ret60 > 0 ? '+' : ''}${ret60}%</span>` : '<span style="color:#64748b">样本外</span>'}
        </td>
        <td>
          <button class="locate-btn" onclick="locateSignal('${s.datetime}')">定位</button>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}


// 在图表上快速缩放并定位到指定时间
window.locateSignal = function (datetime) {
  if (!chart || !currentAnalysisData || !currentAnalysisData.data) return;
  const dates = currentAnalysisData.data.map(d => d.datetime);
  const targetIndex = dates.indexOf(datetime);
  if (targetIndex === -1) return;

  const total = dates.length;
  // 聚焦前后 30 根 K 线
  const startIdx = Math.max(0, targetIndex - 30);
  const endIdx = Math.min(total - 1, targetIndex + 30);

  const startPercent = (startIdx / total) * 100;
  const endPercent = (endIdx / total) * 100;

  chart.dispatchAction({
    type: 'dataZoom',
    start: startPercent,
    end: endPercent
  });

  chart.dispatchAction({
    type: 'showTip',
    seriesIndex: 0,
    dataIndex: targetIndex
  });

  // 平滑滚动回顶部图表
  document.querySelector('.chart-layout').scrollIntoView({ behavior: 'smooth' });
};

// ============================================================
// 模拟实操交易面板 (Paper Trading Console) 核心交互逻辑
// ============================================================
let currentSimData = null;
let currentStockPrice = 42.98;

function bindSimEvents() {
  // 点击“现价”填充
  const btnLatest = document.getElementById('btn-use-latest-price');
  if (btnLatest) {
    btnLatest.addEventListener('click', () => fillLatestPrice());
  }

  // 设定初始底仓按钮
  const btnCustomHolding = document.getElementById('btn-custom-holding');
  if (btnCustomHolding) {
    btnCustomHolding.addEventListener('click', async () => {
      const curShares = (currentSimData && currentSimData.position) ? currentSimData.position.shares : 1000;
      const curCost = (currentSimData && currentSimData.position && currentSimData.position.avg_cost) ? currentSimData.position.avg_cost : 42.0;
      
      const priceStr = prompt(`请输入昨日买入底仓成本价 (元):`, curCost || "42.00");
      if (!priceStr) return;
      const sharesStr = prompt(`请输入底仓股数 (须为100的整数倍):`, curShares || "1000");
      if (!sharesStr) return;

      const p = parseFloat(priceStr);
      const s = parseInt(sharesStr, 10);
      if (isNaN(p) || p <= 0 || isNaN(s) || s <= 0 || s % 100 !== 0) {
        showToast('输入的价格或股数不合法', 'error');
        return;
      }

      try {
        const resp = await fetch('/api/sim/set_holding', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbol: currentSymbol,
            shares: s,
            price: p,
            buy_date: '2026-10-28 14:30:00',
            initial_cash: 100000.0
          })
        });
        const json = await resp.json();
        if (json.status === 'success') {
          showToast(json.message, 'success');
          if (json.account) {
            currentSimData = json.account;
            renderSimAccount(currentSimData);
          }
        }
      } catch (err) {
        console.error(err);
        showToast('设置底仓失败', 'error');
      }
    });
  }

  // 同步市价
  const btnSync = document.getElementById('btn-sync-sim-price');
  if (btnSync) {
    btnSync.addEventListener('click', () => {
      fillLatestPrice();
      loadSimAccount();
      showToast('已同步最新盘口实时价', 'info');
    });
  }


  // 快捷数量按钮
  document.querySelectorAll('.sim-quick-chips .chip-qty').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const qty = e.target.getAttribute('data-qty');
      const ratio = e.target.getAttribute('data-ratio');
      const sharesInput = document.getElementById('sim-input-shares');
      const price = parseFloat(document.getElementById('sim-input-price').value) || currentStockPrice;

      if (qty) {
        sharesInput.value = qty;
      } else if (ratio && currentSimData) {
        const cash = currentSimData.cash || 0;
        const maxShares = Math.floor(cash / (price * 1.0003 * 100)) * 100;
        const targetShares = Math.max(100, Math.floor((maxShares * parseFloat(ratio)) / 100) * 100);
        sharesInput.value = targetShares;
      }
      updateOrderEstimate();
    });
  });

  // 价格或数量变动动态计算预计耗资
  const priceInput = document.getElementById('sim-input-price');
  const sharesInput = document.getElementById('sim-input-shares');
  if (priceInput) priceInput.addEventListener('input', updateOrderEstimate);
  if (sharesInput) sharesInput.addEventListener('input', updateOrderEstimate);

  // 载入策略推荐挂单
  const btnQuickfill = document.getElementById('btn-fill-strategy-order');
  if (btnQuickfill) {
    btnQuickfill.addEventListener('click', () => {
      if (!currentAnalysisData || !currentAnalysisData.latest_decision) {
        showToast('暂无策略推荐计划', 'warn');
        return;
      }
      const dec = currentAnalysisData.latest_decision;
      const meta = currentAnalysisData.strategy_meta || {};
      priceInput.value = dec.current_price || currentStockPrice;
      const noteInput = document.getElementById('sim-input-note');
      if (noteInput) {
        noteInput.value = `策略【${meta.name || '量化'}】推荐：${dec.title || ''}`;
      }
      updateOrderEstimate();
      showToast(`已载入策略【${meta.name}】参考计划`, 'info');
    });
  }

  // 模拟买入
  const btnBuy = document.getElementById('btn-sim-buy');
  if (btnBuy) {
    btnBuy.addEventListener('click', () => submitSimTrade('BUY'));
  }

  // 模拟卖出
  const btnSell = document.getElementById('btn-sim-sell');
  if (btnSell) {
    btnSell.addEventListener('click', () => submitSimTrade('SELL'));
  }

  // 一键清仓
  const btnCloseAll = document.getElementById('btn-sim-close-all');
  if (btnCloseAll) {
    btnCloseAll.addEventListener('click', () => {
      if (!currentSimData || !currentSimData.position || currentSimData.position.shares <= 0) {
        showToast('当前持仓为空，无需清仓', 'warn');
        return;
      }
      if (confirm(`确定要以市价平仓全部 ${currentSimData.position.shares} 股招商银行持仓吗？`)) {
        submitSimTrade('SELL', currentSimData.position.shares, 0, '一键市价清仓平仓');
      }
    });
  }

  // 重置模拟账户
  const btnReset = document.getElementById('btn-reset-sim');
  if (btnReset) {
    btnReset.addEventListener('click', async () => {
      if (confirm('确定要重置模拟交易账户吗？所有历史交易和持仓将被清空，初始资金恢复为 ¥100,000.00。')) {
        await submitSimReset();
      }
    });
  }
}

// 填入最新市价
function fillLatestPrice() {
  const priceInput = document.getElementById('sim-input-price');
  if (priceInput) {
    priceInput.value = currentStockPrice.toFixed(2);
    updateOrderEstimate();
  }
}

// 动态预估订单耗资
function updateOrderEstimate() {
  const p = parseFloat(document.getElementById('sim-input-price')?.value) || currentStockPrice;
  const s = parseInt(document.getElementById('sim-input-shares')?.value, 10) || 0;
  const buySub = document.getElementById('buy-estimate-sub');
  const sellSub = document.getElementById('sell-estimate-sub');

  if (buySub) {
    const cost = (p * s * 1.00025);
    buySub.innerText = `预计耗资: ¥${cost.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (sellSub && currentSimData && currentSimData.position) {
    sellSub.innerText = `可卖股数: ${currentSimData.position.shares} 股`;
  }
}

// 请求后端加载模拟账户
async function loadSimAccount() {
  try {
    const resp = await fetch(`/api/sim/account?symbol=${currentSymbol}`);
    const json = await resp.json();
    if (json.status === 'success' && json.data) {
      currentSimData = json.data;
      if (json.data.position && json.data.position.current_price > 0) {
        currentStockPrice = json.data.position.current_price;
      }
      renderSimAccount(currentSimData);
    }
  } catch (err) {
    console.error('Failed to load sim account:', err);
  }
}

// 渲染模拟账户数据与交易流水
function renderSimAccount(data) {
  if (!data) return;

  // 资产概览
  document.getElementById('sim-total-assets').innerText = `¥${data.total_assets.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
  document.getElementById('sim-cash').innerText = `¥${data.cash.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;

  const pnlElem = document.getElementById('sim-total-pnl');
  const isUp = data.total_pnl >= 0;
  pnlElem.innerText = `${isUp ? '+' : ''}¥${data.total_pnl.toFixed(2)} (${isUp ? '+' : ''}${data.total_pnl_pct.toFixed(2)}%)`;
  pnlElem.style.color = isUp ? 'var(--up-color)' : 'var(--down-color)';

  // 持仓状态
  const pos = data.position || {};
  const shares = pos.shares || 0;
  const posTag = document.getElementById('sim-pos-tag');
  if (posTag) {
    posTag.className = `pos-status-tag ${shares > 0 ? 'holding' : 'empty'}`;
    posTag.innerText = shares > 0 ? `持仓中 (${shares}股)` : '空仓';
  }

  document.getElementById('sim-shares').innerText = `${shares.toLocaleString()} 股`;
  document.getElementById('sim-avg-cost').innerText = `¥${pos.avg_cost ? pos.avg_cost.toFixed(2) : '0.00'}`;
  document.getElementById('sim-market-val').innerText = `¥${pos.market_value ? pos.market_value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) : '0.00'}`;

  const unPnlElem = document.getElementById('sim-unrealized-pnl');
  if (unPnlElem) {
    const isPosUp = pos.unrealized_pnl >= 0;
    unPnlElem.innerText = `${isPosUp ? '+' : ''}¥${(pos.unrealized_pnl || 0).toFixed(2)} (${isPosUp ? '+' : ''}${(pos.unrealized_pnl_pct || 0).toFixed(2)}%)`;
    unPnlElem.style.color = isPosUp ? 'var(--up-color)' : 'var(--down-color)';
  }

  // 价格输入框如果为空，默认填充当前最新价
  const priceInput = document.getElementById('sim-input-price');
  if (priceInput && (!priceInput.value || parseFloat(priceInput.value) <= 0)) {
    priceInput.value = currentStockPrice.toFixed(2);
  }

  // 策略快捷建议文字
  const adviceElem = document.getElementById('quickfill-advice');
  if (adviceElem && currentAnalysisData && currentAnalysisData.latest_decision) {
    adviceElem.innerText = currentAnalysisData.latest_decision.title || '监控中';
  }

  updateOrderEstimate();
  renderSimTradesTable(data.trades || []);
}

// 渲染模拟订单流水
function renderSimTradesTable(trades) {
  const tbody = document.getElementById('sim-trades-tbody');
  const countElem = document.getElementById('sim-trades-count');
  if (countElem) countElem.innerText = trades.length;

  if (!tbody) return;
  if (!trades || trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="loading-td">暂无模拟交易记录，可以在上方尝试买入建仓！</td></tr>`;
    return;
  }

  let html = '';
  trades.forEach(t => {
    const isBuy = t.type === 'BUY';
    const isProfit = t.pnl >= 0;
    html += `
      <tr>
        <td style="font-family:var(--font-mono); font-size:11px;">${t.created_at}</td>
        <td>
          <span class="badge-signal ${t.type}">
            ${isBuy ? '🟢 买入' : '🔴 卖出'}
          </span>
        </td>
        <td>招商银行</td>
        <td style="font-family:var(--font-mono); font-weight:700;">¥${t.price.toFixed(2)}</td>
        <td style="font-family:var(--font-mono); font-weight:600;">${t.shares} 股</td>
        <td style="font-family:var(--font-mono);">¥${t.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
        <td style="font-family:var(--font-mono); font-size:11px; color:#94a3b8;">¥${t.fee.toFixed(2)}</td>
        <td style="font-family:var(--font-mono); font-weight:700; color:${t.type==='SELL' ? (isProfit?'var(--up-color)':'var(--down-color)') : '#64748b'}">
          ${t.type === 'SELL' ? `${isProfit?'+':''}¥${t.pnl.toFixed(2)}` : '--'}
        </td>
        <td style="color:#cbd5e1; font-size:12px;">${t.note || '手动交易'}</td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

// 提交模拟交易
async function submitSimTrade(type, explicitShares = null, explicitPrice = null, explicitNote = null) {
  const price = explicitPrice !== null ? explicitPrice : (parseFloat(document.getElementById('sim-input-price')?.value) || currentStockPrice);
  const shares = explicitShares !== null ? explicitShares : (parseInt(document.getElementById('sim-input-shares')?.value, 10) || 100);
  const note = explicitNote !== null ? explicitNote : (document.getElementById('sim-input-note')?.value || `手动模拟${type==='BUY'?'买入':'卖出'}`);

  if (shares <= 0) {
    showToast('股数必须大于 0', 'error');
    return;
  }
  if (type === 'BUY' && shares % 100 !== 0) {
    showToast('A股买入必须是整手 (100股的整数倍)', 'error');
    return;
  }

  try {
    const resp = await fetch('/api/sim/trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: currentSymbol,
        type: type,
        shares: shares,
        price: price,
        note: note
      })
    });

    const json = await resp.json();
    if (json.status === 'success') {
      showToast(json.message, 'success');
      if (json.account) {
        currentSimData = json.account;
        renderSimAccount(currentSimData);
      } else {
        loadSimAccount();
      }
    } else {
      showToast(json.message || '委托失败', 'error');
    }
  } catch (err) {
    console.error('Trade submit error:', err);
    showToast('提交委托失败，请检查网络', 'error');
  }
}

// 提交重置模拟账户
async function submitSimReset() {
  try {
    const resp = await fetch('/api/sim/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initial_cash: 100000.0 })
    });
    const json = await resp.json();
    if (json.status === 'success') {
      showToast(json.message, 'success');
      if (json.account) {
        currentSimData = json.account;
        renderSimAccount(currentSimData);
      } else {
        loadSimAccount();
      }
    }
  } catch (err) {
    console.error('Reset account error:', err);
    showToast('重置账户失败', 'error');
  }
}

// 轻量 Toast 提示系统
function showToast(message, type = 'info') {
  let toastContainer = document.getElementById('app-toast-container');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'app-toast-container';
    toastContainer.style.cssText = `
      position: fixed;
      top: 24px;
      right: 24px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 10px;
      pointer-events: none;
    `;
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement('div');
  const bgColors = {
    success: 'linear-gradient(135deg, #059669, #10b981)',
    error: 'linear-gradient(135deg, #dc2626, #ef4444)',
    warn: 'linear-gradient(135deg, #d97706, #f59e0b)',
    info: 'linear-gradient(135deg, #2563eb, #38bdf8)'
  };

  toast.style.cssText = `
    background: ${bgColors[type] || bgColors.info};
    color: white;
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    opacity: 0;
    transform: translateY(-10px);
    transition: all 0.25s ease-out;
  `;
  toast.innerText = message;
  toastContainer.appendChild(toast);

  // 动画进入
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
  });

  // 3秒后淡出
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-10px)';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ================= 飞书推送设置模态框管理 =================
let cachedNotifySettings = null;

async function openNotifySettingsModal() {
  const modal = document.getElementById('modal-notify-settings');
  if (!modal) return;
  modal.style.display = 'flex';
  requestAnimationFrame(() => {
    modal.classList.add('show');
  });
  await loadNotifySettings();
}

function closeNotifySettingsModal() {
  const modal = document.getElementById('modal-notify-settings');
  if (!modal) return;
  modal.classList.remove('show');
  setTimeout(() => {
    modal.style.display = 'none';
  }, 250);
}

async function loadNotifySettings() {
  const listEl = document.getElementById('notify-stocks-list');
  const globalChk = document.getElementById('chk-global-push');
  const statusText = document.getElementById('modal-status-text');
  
  if (listEl) {
    listEl.innerHTML = `<div style="text-align:center; padding: 20px; color: #94a3b8;">正在加载推送配置...</div>`;
  }

  try {
    const resp = await fetch('/api/notify/settings');
    const res = await resp.json();
    if (res.status === 'success' && res.data) {
      cachedNotifySettings = res.data;
      if (globalChk) {
        globalChk.checked = Boolean(res.data.global_enabled);
      }
      renderNotifyStockCards(res.data.stocks || []);
      if (statusText) statusText.innerText = "配置读取成功，修改后点击保存即可实时生效";
    }
  } catch (err) {
    console.error("加载推送配置失败:", err);
    if (listEl) {
      listEl.innerHTML = `<div style="text-align:center; padding: 20px; color: #ef4444;">加载失败，请检查网络或后端服务</div>`;
    }
  }
}

function renderNotifyStockCards(stocks) {
  const listEl = document.getElementById('notify-stocks-list');
  if (!listEl) return;
  listEl.innerHTML = '';

  stocks.forEach(st => {
    const card = document.createElement('div');
    card.className = `notify-stock-card ${st.enabled ? '' : 'is-disabled'}`;
    card.setAttribute('data-symbol', st.symbol);

    card.innerHTML = `
      <div class="stock-card-top">
        <div class="stock-meta-info">
          <span class="stock-icon">${st.icon || '📌'}</span>
          <span class="stock-name-title">${st.name}</span>
          <span class="stock-code-badge">${st.symbol.toUpperCase()}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="stock-state-label" style="font-size: 0.78rem; font-weight: 500; color: ${st.enabled ? '#10b981' : '#64748b'};">
            ${st.enabled ? '已开启推送' : '已静音'}
          </span>
          <label class="toggle-switch">
            <input type="checkbox" class="stock-chk-toggle" ${st.enabled ? 'checked' : ''} data-symbol="${st.symbol}">
            <span class="slider"></span>
          </label>
        </div>
      </div>
      <div class="stock-card-filter-row">
        <div class="filter-left-group">
          <span class="filter-label">推送过滤:</span>
          <div class="filter-pills" data-symbol="${st.symbol}">
            <button type="button" class="pill-btn ${st.signal_filter === 'ALL' ? 'active' : ''}" data-filter="ALL" title="接收所有买入与卖出信号">
              全部买卖点
            </button>
            <button type="button" class="pill-btn ${st.signal_filter === 'BUY_ONLY' ? 'active' : ''}" data-filter="BUY_ONLY" title="仅推送买入进场信号">
              仅买入点 (B)
            </button>
            <button type="button" class="pill-btn ${st.signal_filter === 'SELL_ONLY' ? 'active' : ''}" data-filter="SELL_ONLY" title="仅推送止盈/止损卖点">
              仅卖出点 (S)
            </button>
          </div>
        </div>
        <button type="button" class="stock-test-btn" data-symbol="${st.symbol}" data-name="${st.name}">
          ⚡ 测试推送
        </button>
      </div>
    `;

    // 绑定该卡片的交互事件
    const chk = card.querySelector('.stock-chk-toggle');
    const stateLabel = card.querySelector('.stock-state-label');
    chk.addEventListener('change', (e) => {
      const isChecked = e.target.checked;
      card.classList.toggle('is-disabled', !isChecked);
      stateLabel.innerText = isChecked ? '已开启推送' : '已静音';
      stateLabel.style.color = isChecked ? '#10b981' : '#64748b';
    });

    const pills = card.querySelectorAll('.pill-btn');
    pills.forEach(p => {
      p.addEventListener('click', (e) => {
        pills.forEach(other => other.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    const testBtn = card.querySelector('.stock-test-btn');
    testBtn.addEventListener('click', async () => {
      const activePill = card.querySelector('.pill-btn.active');
      const filter = activePill ? activePill.getAttribute('data-filter') : 'ALL';
      const sigType = filter === 'SELL_ONLY' ? 'SELL' : 'BUY';
      
      testBtn.disabled = true;
      const originalText = testBtn.innerHTML;
      testBtn.innerHTML = `<span>⏳ 发送中...</span>`;
      try {
        const resp = await fetch('/api/notify/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: st.symbol, signal_type: sigType })
        });
        const res = await resp.json();
        if (res.status === 'success' && res.sent) {
          showToast(`已向飞书推送【${st.name}】${sigType === 'BUY' ? '买入' : '卖出'}暗号卡片！`, 'success');
        } else {
          showToast(`发送失败，请检查 Webhook 配置`, 'error');
        }
      } catch (err) {
        showToast(`网络异常: ${err}`, 'error');
      } finally {
        testBtn.disabled = false;
        testBtn.innerHTML = originalText;
      }
    });

    listEl.appendChild(card);
  });
}

async function saveNotifySettings() {
  const saveBtn = document.getElementById('btn-save-notify-settings');
  const globalChk = document.getElementById('chk-global-push');
  const statusText = document.getElementById('modal-status-text');
  
  const global_enabled = globalChk ? globalChk.checked : true;
  const cards = document.querySelectorAll('#notify-stocks-list .notify-stock-card');
  const stockConfigs = [];

  cards.forEach(card => {
    const symbol = card.getAttribute('data-symbol');
    const chk = card.querySelector('.stock-chk-toggle');
    const enabled = chk ? chk.checked : true;
    const activePill = card.querySelector('.pill-btn.active');
    const signal_filter = activePill ? activePill.getAttribute('data-filter') : 'ALL';
    
    if (symbol) {
      stockConfigs.push({ symbol, enabled, signal_filter });
    }
  });

  saveBtn.disabled = true;
  saveBtn.innerText = "正在保存...";
  if (statusText) statusText.innerText = "正在持久化到数据库...";

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
      showToast('✓ 飞书推送配置已成功保存并实时生效！', 'success');
      if (statusText) statusText.innerText = "✓ 配置已成功更新并实时生效";
      setTimeout(() => {
        closeNotifySettingsModal();
      }, 500);
    } else {
      showToast('保存失败: ' + (res.message || '未知错误'), 'error');
    }
  } catch (err) {
    console.error("保存推送配置失败:", err);
    showToast('保存异常，请检查网络', 'error');
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerHTML = `💾 保存并实时生效`;
  }
}


