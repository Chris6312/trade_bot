const MODE_OPTIONS = [
  { value: 'paper', label: 'Paper' },
  { value: 'live', label: 'Live' },
  { value: 'mixed', label: 'Mixed' },
];

const YES_VALUES = new Set(['1', 'true', 'yes', 'on', 'enabled']);

export function toNumber(value) {
  if (value == null || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function toPercent(value) {
  const numeric = toNumber(value);
  if (numeric == null) return null;
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
}

export function normalizeBoolean(value) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  return YES_VALUES.has(String(value).trim().toLowerCase());
}

export function parseSettingValue(value, valueType = 'string') {
  const type = String(valueType || 'string').toLowerCase();
  if (type === 'bool' || type === 'boolean') return normalizeBoolean(value);
  if (['int', 'integer', 'float', 'number', 'decimal'].includes(type)) {
    const numeric = toNumber(value);
    return numeric == null ? '' : numeric;
  }
  return value ?? '';
}

export function serializeSettingValue(value, valueType = 'string') {
  const type = String(valueType || 'string').toLowerCase();
  if (type === 'bool' || type === 'boolean') return value ? 'true' : 'false';
  if (['int', 'integer', 'float', 'number', 'decimal'].includes(type)) return value === '' || value == null ? '' : String(value);
  return String(value ?? '');
}

export function formatSettingLabel(key) {
  const map = {
    'controls.kill_switch_enabled': 'Master Kill Switch',
    'controls.stock.trading_enabled': 'Stock Trading Enabled',
    'controls.crypto.trading_enabled': 'Crypto Trading Enabled',
    'execution.default_mode': 'Global Execution Mode',
    'execution.stock.mode': 'Stock Broker Route',
    'execution.crypto.mode': 'Crypto Broker Route',
    'stock_universe_source': 'Stock Universe Source',
    'stock_universe_max_size': 'Stock Universe Max Size',
    'ai_enabled': 'AI Universe Enabled',
    'ai_run_once_daily': 'AI Universe Once Daily',
  };

  if (map[key]) return map[key];

  return String(key)
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function inferCategory(key) {
  const raw = String(key || '').toLowerCase();
  if (raw.startsWith('controls.') || raw.startsWith('execution.') || raw.includes('kraken') || raw.includes('public') || raw.includes('alpaca')) {
    return 'Broker / Account';
  }
  if (raw.startsWith('risk.') || raw.includes('breaker')) return 'Risk Controls';
  if (raw.includes('size') || raw.includes('deployment')) return 'Position Sizing';
  if (raw.startsWith('strategy_') || raw.startsWith('strategy.')) return 'Strategy Controls';
  if (raw.includes('universe') || raw.startsWith('ai_')) return 'Universe Controls';
  if (raw.includes('order') || raw.includes('time_in_force')) return 'Execution Controls';
  if (raw.startsWith('stop_') || raw.includes('.stop')) return 'Stop Management';
  if (raw.includes('notify') || raw.includes('alert')) return 'Notifications';
  return 'UI / Admin';
}

function inferSettingInputType(key, valueType) {
  const rawKey = String(key || '').toLowerCase();
  const rawType = String(valueType || 'string').toLowerCase();

  if (rawKey === 'execution.default_mode' || rawKey === 'execution.stock.mode' || rawKey === 'execution.crypto.mode') {
    return 'mode';
  }
  if (rawType === 'bool' || rawType === 'boolean') return 'boolean';
  if (['int', 'integer', 'float', 'number', 'decimal'].includes(rawType)) return 'number';
  return 'text';
}

export function normalizeSettings(settings = [], runtimeSnapshot = null) {
  const runtimeDefaults = runtimeSnapshot && typeof runtimeSnapshot === 'object'
    ? Object.fromEntries(Object.entries(runtimeSnapshot).filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value)))
    : {};

  return (Array.isArray(settings) ? settings : []).map((row) => {
    const key = row.key;
    const type = inferSettingInputType(key, row.value_type);
    const parsedValue = parseSettingValue(row.value, row.value_type);
    return {
      key,
      label: formatSettingLabel(key),
      category: inferCategory(key),
      valueType: row.value_type || 'string',
      type,
      value: parsedValue,
      defaultValue: Object.prototype.hasOwnProperty.call(runtimeDefaults, key) ? runtimeDefaults[key] : null,
      description: row.description || '',
      lastChanged: row.updated_at || null,
      dangerous: /kill_switch|\.mode$|default_mode|flatten|breaker|hard_stop|live/i.test(key),
      options: type === 'mode' ? MODE_OPTIONS : [],
      raw: row,
    };
  });
}

export function normalizeUniverse(stockRows = [], cryptoRows = []) {
  return {
    stocks: normalizeUniverseRows(stockRows, 'Stock'),
    crypto: normalizeUniverseRows(cryptoRows, 'Crypto'),
  };
}

function normalizeUniverseRows(rows, assetClass) {
  return rows.map((row, index) => {
    const payload = row.payload && typeof row.payload === 'object' ? row.payload : {};
    return {
      id: row.id || `${assetClass}-${row.symbol || index}`,
      symbol: row.symbol || '—',
      assetClass,
      rank: row.rank ?? index + 1,
      lastPrice: toNumber(payload.last_price ?? payload.price ?? payload.last),
      changePct: toPercent(payload.change_pct ?? payload.daily_change_pct ?? payload.changePercent),
      liquidityScore: toNumber(payload.liquidity_score ?? payload.liquidity),
      participationScore: toNumber(payload.participation_score ?? payload.participation),
      trendScore: toNumber(payload.trend_score ?? payload.trend),
      stabilityScore: toNumber(payload.stability_score ?? payload.stability),
      compositeScore: toNumber(payload.composite_score ?? payload.score),
      eligibility: payload.eligibility || row.selection_reason || 'Selected',
      blockReason: payload.block_reason || '',
      raw: row,
    };
  });
}

export function normalizeStrategies(stockRows = [], cryptoRows = []) {
  return [...normalizeStrategyRows(stockRows, 'Stock'), ...normalizeStrategyRows(cryptoRows, 'Crypto')];
}

function normalizeStrategyRows(rows, assetClass) {
  return rows.map((row) => ({
    id: row.id || `${assetClass}-${row.symbol}-${row.strategy_name}`,
    symbol: row.symbol || '—',
    assetClass,
    primaryStrategy: formatSettingLabel(row.strategy_name || '—').replace(/\./g, ' '),
    secondaryStrategies: stringifyList(row.payload?.secondary_strategies),
    strategyRankScore: toNumber(row.composite_score),
    readinessScore: toNumber(row.readiness_score),
    status: row.status || 'unknown',
    blocker: stringifyList(row.blocked_reasons),
    timeframe: row.timeframe || '—',
    regime: row.regime || '—',
    evaluatedAt: row.computed_at || row.candidate_timestamp || null,
    thresholdsPassed: stringifyList(row.payload?.thresholds_passed),
    thresholdsFailed: stringifyList(row.blocked_reasons || row.payload?.thresholds_failed),
    regimeRequirement: row.entry_policy || '—',
    nextReevaluation: row.payload?.next_reevaluation || '—',
    previousSignalAttempts: stringifyList(row.payload?.previous_signal_attempts),
    explanation: row.decision_reason || stringifyList(row.blocked_reasons) || 'No explanation returned yet.',
    raw: row,
  }));
}

export function normalizePositions(stockRows = [], cryptoRows = []) {
  return [...normalizePositionRows(stockRows, 'Stock'), ...normalizePositionRows(cryptoRows, 'Crypto')];
}

function normalizePositionRows(rows, assetClass) {
  return rows.map((row) => ({
    id: row.id || `${assetClass}-${row.symbol}-${row.timeframe}`,
    symbol: row.symbol || '—',
    assetClass,
    venue: row.venue || '—',
    account: row.mode || '—',
    strategy: row.payload?.strategy_name || row.source || '—',
    side: row.side || '—',
    qty: toNumber(row.quantity),
    avgEntry: toNumber(row.average_entry_price),
    lastPrice: toNumber(row.current_price),
    marketValue: toNumber(row.market_value),
    unrealizedPnl: toNumber(row.unrealized_pnl),
    realizedPnl: toNumber(row.realized_pnl),
    stop: toNumber(row.payload?.current_stop_price ?? row.payload?.stop_price),
    target: row.payload?.target_price || '—',
    timeInTrade: row.payload?.time_in_trade || '—',
    status: row.reconciliation_status || row.status || '—',
    updatedAt: row.synced_at || null,
    details: row,
  }));
}

export function normalizeLogs(events = []) {
  return (Array.isArray(events) ? events : []).map((row) => ({
    id: row.id,
    timestamp: row.created_at || null,
    level: String(row.severity || 'info').toUpperCase(),
    component: row.event_source || 'system',
    source: row.event_source || 'backend',
    action: row.event_type || 'event',
    symbol: row.payload?.symbol || '',
    status: row.payload?.status || '',
    message: row.message || '(no message)',
    payload: row.payload || null,
    raw: row,
  }));
}

export function normalizeSummary({ accountSnapshots = {}, positions = [], controlSnapshot = {}, health = {}, riskRows = [] }) {
  const total = accountSnapshots.total || null;
  const stock = accountSnapshots.stock || null;
  const crypto = accountSnapshots.crypto || null;
  const deploymentRow = [...riskRows.stock, ...riskRows.crypto].find((row) => row && row.deployment_pct != null);
  const totalDayPnl = toNumber(total?.realized_pnl) != null || toNumber(total?.unrealized_pnl) != null
    ? (toNumber(total?.realized_pnl) || 0) + (toNumber(total?.unrealized_pnl) || 0)
    : positions.reduce((sum, row) => sum + (Number(row.unrealizedPnl) || 0) + (Number(row.realizedPnl) || 0), 0);

  return {
    totalEquity: toNumber(total?.equity),
    stockEquity: toNumber(stock?.equity),
    cryptoEquity: toNumber(crypto?.equity),
    totalDayPnl,
    deploymentPct: toPercent(deploymentRow?.deployment_pct),
    openPositions: positions.length,
    livePaperLabel: controlSnapshot.default_mode || health.environment || 'unknown',
    killSwitchEnabled: Boolean(controlSnapshot.kill_switch_enabled),
    updatedAt: total?.as_of || stock?.as_of || crypto?.as_of || null,
  };
}

export function normalizePerformance({ accountSnapshots = {}, positions = [], riskRows = {} }) {
  const total = accountSnapshots.total || null;
  const combinedRiskRows = [...(riskRows.stock || []), ...(riskRows.crypto || [])];
  const drawdown = combinedRiskRows.reduce((worst, row) => {
    const value = toPercent(row.projected_loss_pct);
    return value == null ? worst : Math.min(worst, value);
  }, 0);

  return {
    sharpe: '—',
    sortino: '—',
    maxDrawdown: drawdown === 0 ? null : drawdown,
    realizedToday: toNumber(total?.realized_pnl) ?? positions.reduce((sum, row) => sum + (Number(row.realizedPnl) || 0), 0),
    unrealized: toNumber(total?.unrealized_pnl) ?? positions.reduce((sum, row) => sum + (Number(row.unrealizedPnl) || 0), 0),
    totalPnl: (toNumber(total?.realized_pnl) || 0) + (toNumber(total?.unrealized_pnl) || 0),
    stockAlpha: (riskRows.stock || []).filter((row) => row.status === 'ready').length,
    cryptoAlpha: (riskRows.crypto || []).filter((row) => row.status === 'ready').length,
  };
}

export function mergeAccountSnapshots(total = null, stock = null, crypto = null) {
  return { total, stock, crypto };
}

export function stringifyList(value) {
  if (Array.isArray(value)) return value.join(', ');
  if (value == null || value === '') return '';
  return String(value);
}
