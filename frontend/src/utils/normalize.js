const MODE_OPTIONS = [
  { value: 'paper', label: 'Paper' },
  { value: 'live', label: 'Live' },
  { value: 'mixed', label: 'Mixed' },
];

const YES_VALUES = new Set(['1', 'true', 'yes', 'on', 'enabled']);


const KRAKEN_PAIR_DISPLAY_MAP = {
  XBTUSD: { displaySymbol: 'BTC/USD', displayName: 'Bitcoin' },
  ETHUSD: { displaySymbol: 'ETH/USD', displayName: 'Ethereum' },
  SOLUSD: { displaySymbol: 'SOL/USD', displayName: 'Solana' },
  XRPUSD: { displaySymbol: 'XRP/USD', displayName: 'XRP' },
  ADAUSD: { displaySymbol: 'ADA/USD', displayName: 'Cardano' },
  XDGUSD: { displaySymbol: 'DOGE/USD', displayName: 'Dogecoin' },
  AVAXUSD: { displaySymbol: 'AVAX/USD', displayName: 'Avalanche' },
  LINKUSD: { displaySymbol: 'LINK/USD', displayName: 'Chainlink' },
  LTCUSD: { displaySymbol: 'LTC/USD', displayName: 'Litecoin' },
  DOTUSD: { displaySymbol: 'DOT/USD', displayName: 'Polkadot' },
  BCHUSD: { displaySymbol: 'BCH/USD', displayName: 'Bitcoin Cash' },
  TRXUSD: { displaySymbol: 'TRX/USD', displayName: 'TRON' },
  XLMUSD: { displaySymbol: 'XLM/USD', displayName: 'Stellar' },
  ATOMUSD: { displaySymbol: 'ATOM/USD', displayName: 'Cosmos' },
  NEARUSD: { displaySymbol: 'NEAR/USD', displayName: 'NEAR Protocol' },
};

const DEFAULT_SETTINGS_CATALOG = [
  { key: 'execution.default_mode', valueType: 'string', defaultValue: 'mixed', description: 'Default execution route for the full bot.' },
  { key: 'execution.stock.mode', valueType: 'string', defaultValue: 'paper', description: 'Stock venue route override.' },
  { key: 'execution.crypto.mode', valueType: 'string', defaultValue: 'paper', description: 'Crypto venue route override.' },
  { key: 'controls.kill_switch_enabled', valueType: 'bool', defaultValue: false, description: 'Blocks new entries immediately.' },
  { key: 'controls.stock.trading_enabled', valueType: 'bool', defaultValue: true, description: 'Enable or disable new stock trades.' },
  { key: 'controls.crypto.trading_enabled', valueType: 'bool', defaultValue: true, description: 'Enable or disable new crypto trades.' },
  { key: 'stock_universe_source', valueType: 'string', defaultValue: 'ai', description: 'Choose AI or fallback stock universe generation.' },
  { key: 'stock_universe_max_size', valueType: 'int', defaultValue: 50, description: 'Maximum stock universe size.' },
  { key: 'ai_enabled', valueType: 'bool', defaultValue: true, description: 'Allow AI ranking for stock universe selection.' },
  { key: 'ai_run_once_daily', valueType: 'bool', defaultValue: true, description: 'Only run the AI stock universe once per day.' },
  { key: 'ai_premarket_time_et', valueType: 'string', defaultValue: '08:40', description: 'Premarket AI universe build time in New York.' },
  { key: 'risk.default_profile', valueType: 'string', defaultValue: 'moderate', description: 'Risk profile label used by the risk gate.' },
  { key: 'risk.max_account_deployment_pct', valueType: 'float', defaultValue: 0.9, description: 'Maximum deployed capital across all open trades.' },
  { key: 'risk.max_per_trade_pct', valueType: 'float', defaultValue: 0.02, description: 'Hard max risk allowed per trade.' },
  { key: 'risk.default_per_trade_pct', valueType: 'float', defaultValue: 0.0125, description: 'Default target risk per trade.' },
  { key: 'risk.long_only_until_equity', valueType: 'float', defaultValue: 2500, description: 'Remain long-only until equity exceeds this amount.' },
  { key: 'risk.stock.soft_stop_pct', valueType: 'float', defaultValue: -0.035, description: 'Stock soft circuit-breaker threshold.' },
  { key: 'risk.stock.hard_stop_pct', valueType: 'float', defaultValue: -0.055, description: 'Stock hard circuit-breaker threshold.' },
  { key: 'risk.crypto.soft_stop_pct', valueType: 'float', defaultValue: -0.04, description: 'Crypto soft circuit-breaker threshold.' },
  { key: 'risk.crypto.hard_stop_pct', valueType: 'float', defaultValue: -0.065, description: 'Crypto hard circuit-breaker threshold.' },
  { key: 'risk.total_account.hard_stop_pct', valueType: 'float', defaultValue: -0.075, description: 'Whole-account hard stop threshold.' },
  { key: 'strategy_enabled.stock.trend_pullback_long', valueType: 'bool', defaultValue: true, description: 'Enable the stock Trend Pullback Long strategy.' },
  { key: 'strategy_enabled.stock.vwap_reclaim_long', valueType: 'bool', defaultValue: true, description: 'Enable the stock VWAP Reclaim Long strategy.' },
  { key: 'strategy_enabled.stock.opening_range_breakout_long', valueType: 'bool', defaultValue: true, description: 'Enable the stock Opening Range Breakout Long strategy.' },
  { key: 'strategy_enabled.crypto.trend_continuation_long', valueType: 'bool', defaultValue: true, description: 'Enable the crypto 4H/1H Trend Continuation Long strategy.' },
  { key: 'strategy_enabled.crypto.vwap_reclaim_long', valueType: 'bool', defaultValue: true, description: 'Enable the crypto VWAP Reclaim Long strategy.' },
  { key: 'strategy_enabled.crypto.breakout_long', valueType: 'bool', defaultValue: true, description: 'Enable the crypto Breakout Long strategy.' },
  { key: 'strategy_enabled.crypto.bbrsi_mean_reversion_long', valueType: 'bool', defaultValue: true, description: 'Enable the crypto BBRSI Mean Reversion Long strategy.' },
  { key: 'stops.stock.fallback_stop_pct', valueType: 'float', defaultValue: 0.01, description: 'Stock fallback stop percentage.' },
  { key: 'stops.stock.trailing_activation_pct', valueType: 'float', defaultValue: 0.01, description: 'Stock trailing-stop activation threshold.' },
  { key: 'stops.stock.trailing_offset_pct', valueType: 'float', defaultValue: 0.0075, description: 'Stock trailing-stop offset percentage.' },
  { key: 'stops.stock.step_trigger_pct', valueType: 'float', defaultValue: 0.02, description: 'Stock step-stop trigger percentage.' },
  { key: 'stops.stock.step_increment_pct', valueType: 'float', defaultValue: 0.01, description: 'Stock step-stop increment percentage.' },
  { key: 'stops.crypto.fallback_stop_pct', valueType: 'float', defaultValue: 0.015, description: 'Crypto fallback stop percentage.' },
  { key: 'stops.crypto.trailing_activation_pct', valueType: 'float', defaultValue: 0.015, description: 'Crypto trailing-stop activation threshold.' },
  { key: 'stops.crypto.trailing_offset_pct', valueType: 'float', defaultValue: 0.01, description: 'Crypto trailing-stop offset percentage.' },
  { key: 'stops.crypto.step_trigger_pct', valueType: 'float', defaultValue: 0.025, description: 'Crypto step-stop trigger percentage.' },
  { key: 'stops.crypto.step_increment_pct', valueType: 'float', defaultValue: 0.0125, description: 'Crypto step-stop increment percentage.' },
];

const SETTINGS_CATALOG_BY_KEY = new Map(DEFAULT_SETTINGS_CATALOG.map((item, index) => [item.key, { ...item, order: index }]));

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
    'ai_premarket_time_et': 'AI Premarket Time ET',
    'risk.default_profile': 'Risk Profile',
    'risk.max_account_deployment_pct': 'Max Account Deployment %',
    'risk.max_per_trade_pct': 'Max Risk Per Trade %',
    'risk.default_per_trade_pct': 'Default Risk Per Trade %',
    'risk.long_only_until_equity': 'Long Only Until Equity',
    'risk.stock.soft_stop_pct': 'Stock Soft Stop %',
    'risk.stock.hard_stop_pct': 'Stock Hard Stop %',
    'risk.crypto.soft_stop_pct': 'Crypto Soft Stop %',
    'risk.crypto.hard_stop_pct': 'Crypto Hard Stop %',
    'risk.total_account.hard_stop_pct': 'Total Account Hard Stop %',
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
  if (raw.startsWith('strategy_enabled.') || raw.startsWith('strategy_') || raw.startsWith('strategy.')) return 'Strategy Controls';
  if (raw.includes('universe') || raw.startsWith('ai_')) return 'Universe Controls';
  if (raw.startsWith('stops.') || raw.startsWith('stop_') || raw.includes('.stop')) return 'Stop Management';
  if (raw.startsWith('risk.') && (raw.includes('deployment') || raw.includes('per_trade') || raw.includes('long_only'))) return 'Position Sizing';
  if (raw.startsWith('risk.') || raw.includes('breaker') || raw.includes('hard_stop') || raw.includes('soft_stop')) return 'Risk Controls';
  if (raw.includes('order') || raw.includes('time_in_force')) return 'Execution Controls';
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

function runtimeDefaultsFromSnapshot(runtimeSnapshot) {
  if (!runtimeSnapshot || typeof runtimeSnapshot !== 'object') return {};
  return Object.fromEntries(
    Object.entries(runtimeSnapshot).filter(([key, value]) => key !== 'setting_sources' && ['string', 'number', 'boolean'].includes(typeof value))
  );
}

function resolveSyntheticSettingValue(key, runtimeDefaults, controlSnapshot, fallbackValue) {
  const controls = controlSnapshot && typeof controlSnapshot === 'object' ? controlSnapshot : {};
  if (key === 'execution.default_mode') return controls.default_mode || runtimeDefaults[key] || fallbackValue;
  if (key === 'execution.stock.mode') return controls.stock_mode || runtimeDefaults[key] || fallbackValue;
  if (key === 'execution.crypto.mode') return controls.crypto_mode || runtimeDefaults[key] || fallbackValue;
  if (key === 'controls.kill_switch_enabled') return controls.kill_switch_enabled ?? fallbackValue;
  if (key === 'controls.stock.trading_enabled') return controls.stock_trading_enabled ?? fallbackValue;
  if (key === 'controls.crypto.trading_enabled') return controls.crypto_trading_enabled ?? fallbackValue;
  if (Object.prototype.hasOwnProperty.call(runtimeDefaults, key)) return runtimeDefaults[key];
  return fallbackValue;
}

export function normalizeSettings(settings = [], runtimeSnapshot = null, controlSnapshot = null) {
  const runtimeDefaults = runtimeDefaultsFromSnapshot(runtimeSnapshot);
  const rowsByKey = new Map((Array.isArray(settings) ? settings : []).map((row) => [row.key, row]));

  for (const descriptor of DEFAULT_SETTINGS_CATALOG) {
    if (!rowsByKey.has(descriptor.key)) {
      const currentValue = resolveSyntheticSettingValue(descriptor.key, runtimeDefaults, controlSnapshot, descriptor.defaultValue);
      rowsByKey.set(descriptor.key, {
        key: descriptor.key,
        value: serializeSettingValue(currentValue, descriptor.valueType),
        value_type: descriptor.valueType,
        description: descriptor.description,
        is_secret: false,
        updated_at: null,
        synthetic: true,
      });
    }
  }

  return Array.from(rowsByKey.values())
    .map((row) => {
      const key = row.key;
      const descriptor = SETTINGS_CATALOG_BY_KEY.get(key) || {};
      const valueType = row.value_type || descriptor.valueType || 'string';
      const type = inferSettingInputType(key, valueType);
      const parsedValue = parseSettingValue(row.value, valueType);
      const defaultValue = Object.prototype.hasOwnProperty.call(descriptor, 'defaultValue')
        ? descriptor.defaultValue
        : (Object.prototype.hasOwnProperty.call(runtimeDefaults, key) ? runtimeDefaults[key] : null);

      return {
        key,
        label: formatSettingLabel(key),
        category: descriptor.category || inferCategory(key),
        valueType,
        type,
        value: parsedValue,
        defaultValue,
        description: row.description || descriptor.description || '',
        lastChanged: row.updated_at || null,
        dangerous: /kill_switch|\.mode$|default_mode|flatten|breaker|hard_stop|live/i.test(key),
        options: type === 'mode' ? MODE_OPTIONS : [],
        raw: row,
        order: descriptor.order ?? Number.MAX_SAFE_INTEGER,
      };
    })
    .sort((left, right) => (left.order - right.order) || left.label.localeCompare(right.label));
}

export function normalizeUniverse(stockRows = [], cryptoRows = []) {
  return {
    stocks: normalizeUniverseRows(stockRows, 'Stock'),
    crypto: normalizeUniverseRows(cryptoRows, 'Crypto'),
  };
}

function resolveDisplayMeta(row, assetClass) {
  const payload = row?.payload && typeof row.payload === 'object' ? row.payload : {};
  const rawSymbol = String(row?.symbol || '—');
  if (assetClass !== 'Crypto') {
    return {
      displaySymbol: rawSymbol,
      displayName: payload.display_name || rawSymbol,
      marketSymbol: rawSymbol,
    };
  }

  const mapped = KRAKEN_PAIR_DISPLAY_MAP[rawSymbol] || {};
  return {
    displaySymbol: payload.display_symbol || mapped.displaySymbol || rawSymbol,
    displayName: payload.display_name || mapped.displayName || rawSymbol,
    marketSymbol: payload.kraken_pair || rawSymbol,
  };
}

function normalizeUniverseRows(rows, assetClass) {
  return rows.map((row, index) => {
    const payload = row.payload && typeof row.payload === 'object' ? row.payload : {};
    const display = resolveDisplayMeta(row, assetClass);
    const blockedReasons = stringifyList(payload.blocked_reasons);
    const selectionReason = row.selection_reason || payload.selection_reason || '';
    const blockReason = payload.block_reason || blockedReasons || '';
    const eligibility = payload.eligibility
      || (blockReason ? 'Blocked' : (payload.last_price != null || selectionReason ? 'Eligible' : 'Selected'));

    return {
      id: row.id || `${assetClass}-${row.symbol || index}`,
      symbol: display.displaySymbol,
      displayName: display.displayName,
      marketSymbol: display.marketSymbol,
      rawSymbol: row.symbol || '—',
      assetClass,
      rank: row.rank ?? index + 1,
      lastPrice: toNumber(payload.last_price ?? payload.price ?? payload.last),
      changePct: toPercent(payload.change_pct ?? payload.daily_change_pct ?? payload.changePercent),
      lastCandleAt: payload.last_candle_at || null,
      liquidityScore: toNumber(payload.liquidity_score ?? payload.liquidity),
      participationScore: toNumber(payload.participation_score ?? payload.participation),
      trendScore: toNumber(payload.trend_score ?? payload.trend),
      stabilityScore: toNumber(payload.stability_score ?? payload.stability),
      compositeScore: toNumber(payload.composite_score ?? payload.score),
      eligibility,
      selectionReason,
      blockReason,
      raw: row,
    };
  });
}

export function normalizeStrategies(stockRows = [], cryptoRows = []) {
  return [...normalizeStrategyRows(stockRows, 'Stock'), ...normalizeStrategyRows(cryptoRows, 'Crypto')];
}

function normalizeStrategyRows(rows, assetClass) {
  return rows.map((row) => {
    const display = resolveDisplayMeta(row, assetClass);
    return {
      id: row.id || `${assetClass}-${row.symbol}-${row.strategy_name}`,
      symbol: display.displaySymbol,
      displayName: display.displayName,
      marketSymbol: display.marketSymbol,
      rawSymbol: row.symbol || '—',
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
    };
  });
}

export function normalizePositions(stockRows = [], cryptoRows = []) {
  return [...normalizePositionRows(stockRows, 'Stock'), ...normalizePositionRows(cryptoRows, 'Crypto')];
}

function normalizePositionRows(rows, assetClass) {
  return rows.map((row) => {
    const display = resolveDisplayMeta(row, assetClass);
    return {
      id: row.id || `${assetClass}-${row.symbol}-${row.timeframe}`,
      symbol: display.displaySymbol,
      displayName: display.displayName,
      marketSymbol: display.marketSymbol,
      rawSymbol: row.symbol || '—',
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
    };
  });
}

export function normalizeLogs(events = []) {
  return (Array.isArray(events) ? events : []).map((row) => {
    const rawSymbol = row.payload?.symbol || '';
    const symbolDetail = rawSymbol ? resolveDisplayMeta({ symbol: rawSymbol, payload: row.payload }, 'Crypto') : null;
    return {
      id: row.id,
      timestamp: row.created_at || null,
      level: String(row.severity || 'info').toUpperCase(),
      component: row.event_source || 'system',
      source: row.event_source || 'backend',
      action: row.event_type || 'event',
      symbol: symbolDetail?.displaySymbol || rawSymbol,
      marketSymbol: symbolDetail?.marketSymbol || rawSymbol,
      status: row.payload?.status || '',
      message: row.message || '(no message)',
      payload: row.payload || null,
      raw: row,
    };
  });
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
