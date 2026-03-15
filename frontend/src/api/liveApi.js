import {
  mergeAccountSnapshots,
  normalizeLogs,
  normalizePerformance,
  normalizePositions,
  normalizeSettings,
  normalizeStrategies,
  normalizeSummary,
  normalizeUniverse,
  serializeSettingValue,
} from '../utils/normalize';

const DEFAULT_API_ORIGIN = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8101').replace(/\/$/, '');
export const API_BASE = `${DEFAULT_API_ORIGIN}/api/v1`;

const STOCK_TIMEFRAMES = ['1h', '15m', '5m', '1d'];
const CRYPTO_TIMEFRAMES = ['4h', '1h', '15m', '1d'];

const CONTROL_MAP = {
  refresh_universe: { path: '/controls/universe/run-once', buildPayload: () => ({ asset_class: 'all', force: true }) },
  backfill_candles: { path: '/controls/candles/backfill', buildPayload: () => ({ asset_class: 'all', force: true }) },
  sync_incremental_candles: { path: '/controls/candles/incremental', buildPayload: () => ({ asset_class: 'all' }) },
  recompute_regime: { path: '/controls/regime/run-once', buildPayload: () => ({ asset_class: 'all', force: true }) },
  refresh_strategies: { path: '/controls/strategy/run-once', buildPayload: () => ({ asset_class: 'all', force: true }) },
  flatten_stocks: { path: '/controls/flatten/stock', buildPayload: () => ({ engage_kill_switch: true }) },
  flatten_crypto: { path: '/controls/flatten/crypto', buildPayload: () => ({ engage_kill_switch: true }) },
  flatten_all: { path: '/controls/flatten/all', buildPayload: () => ({ engage_kill_switch: true }) },
  toggle_kill_switch: { path: '/controls/kill-switch/toggle', buildPayload: (payload) => ({ enabled: payload.enabled }) },
};

function makeUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

async function readJson(response) {
  const text = await response.text();
  if (!text) return {};
  return JSON.parse(text);
}

async function fetchJson(path, options = {}) {
  const { timeoutMs = /^\/controls\//.test(path) ? 60000 : 15000, ...requestOptions } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(makeUrl(path), {
      headers: { Accept: 'application/json', ...(requestOptions.headers || {}) },
      signal: controller.signal,
      ...requestOptions,
    });

    if (!response.ok) {
      const error = new Error(`${response.status} ${path}`);
      error.status = response.status;
      throw error;
    }

    return readJson(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      const timeoutError = new Error(`Request timed out for ${path}`);
      timeoutError.status = 408;
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function tryFetch(path, options = {}) {
  try {
    const data = await fetchJson(path, options);
    return { ok: true, data, path };
  } catch (error) {
    return { ok: false, data: null, path, error: error instanceof Error ? error.message : String(error) };
  }
}

async function firstHealthy(paths) {
  for (const path of paths) {
    const result = await tryFetch(path);
    if (result.ok) return result;
  }
  return { ok: false, data: null, path: paths[0], error: `Unable to reach ${paths.join(' or ')}` };
}

function timeframePaths(prefix, timeframes) {
  return timeframes.map((timeframe) => `${prefix}?timeframe=${encodeURIComponent(timeframe)}`);
}

function mergeOkData(results) {
  return results.flatMap((result) => (result.ok && Array.isArray(result.data) ? result.data : []));
}

export async function loadLiveSnapshot() {
  const [
    healthRes,
    settingsRes,
    runtimeRes,
    controlsRes,
    eventsRes,
    stockUniverseRes,
    cryptoUniverseRes,
    stockStrategyResults,
    cryptoStrategyResults,
    stockPositionResults,
    cryptoPositionResults,
    stockRiskResults,
    cryptoRiskResults,
    totalAccountRes,
    stockAccountRes,
    cryptoAccountRes,
  ] = await Promise.all([
    firstHealthy(['/health', '/api/v1/health']),
    tryFetch('/settings'),
    tryFetch('/settings/runtime/snapshot'),
    tryFetch('/controls/snapshot'),
    tryFetch('/system-events?limit=40'),
    tryFetch('/universe/stock/current'),
    tryFetch('/universe/crypto/current'),
    Promise.all(timeframePaths('/strategy/stock/current', STOCK_TIMEFRAMES).map((path) => tryFetch(path))),
    Promise.all(timeframePaths('/strategy/crypto/current', CRYPTO_TIMEFRAMES).map((path) => tryFetch(path))),
    Promise.all(timeframePaths('/positions/stock/current', STOCK_TIMEFRAMES).map((path) => tryFetch(path))),
    Promise.all(timeframePaths('/positions/crypto/current', CRYPTO_TIMEFRAMES).map((path) => tryFetch(path))),
    Promise.all(timeframePaths('/risk/stock/current', STOCK_TIMEFRAMES).map((path) => tryFetch(path))),
    Promise.all(timeframePaths('/risk/crypto/current', CRYPTO_TIMEFRAMES).map((path) => tryFetch(path))),
    tryFetch('/account-snapshots/latest/total'),
    tryFetch('/account-snapshots/latest/stock'),
    tryFetch('/account-snapshots/latest/crypto'),
  ]);

  const mustHave = [healthRes, settingsRes, controlsRes, eventsRes];
  const successfulEssential = mustHave.filter((item) => item.ok).length;
  if (successfulEssential === 0) {
    throw new Error('Backend live endpoints are unavailable. I could not verify live UI data because the API did not answer from the uploaded project.');
  }

  const degraded = successfulEssential < mustHave.length;
  const settings = normalizeSettings(settingsRes.data || [], runtimeRes.data || null, controlsRes.data || null);
  const strategies = normalizeStrategies(mergeOkData(stockStrategyResults), mergeOkData(cryptoStrategyResults));
  const universe = normalizeUniverse(stockUniverseRes.data || [], cryptoUniverseRes.data || [], strategies);
  const positions = normalizePositions(mergeOkData(stockPositionResults), mergeOkData(cryptoPositionResults));
  const logs = normalizeLogs(eventsRes.data || []);
  const riskRows = {
    stock: mergeOkData(stockRiskResults),
    crypto: mergeOkData(cryptoRiskResults),
  };
  const accountSnapshots = mergeAccountSnapshots(totalAccountRes.data, stockAccountRes.data, cryptoAccountRes.data);

  const summary = normalizeSummary({
    accountSnapshots,
    positions,
    controlSnapshot: controlsRes.data || {},
    health: healthRes.data || {},
    riskRows,
  });

  const performance = normalizePerformance({
    accountSnapshots,
    positions,
    riskRows,
  });

  return {
    health: {
      status: healthRes.data?.status || 'unknown',
      mode: controlsRes.data?.default_mode || 'unknown',
      killSwitchEnabled: Boolean(controlsRes.data?.kill_switch_enabled),
      systemHalted: Boolean(controlsRes.data?.kill_switch_enabled),
      degraded,
      raw: healthRes.data || {},
    },
    summary,
    performance,
    universe,
    strategies,
    positions,
    logs,
    settings,
    controlState: {
      killSwitchEnabled: Boolean(controlsRes.data?.kill_switch_enabled),
      stockTradingEnabled: Boolean(controlsRes.data?.stock_trading_enabled ?? true),
      cryptoTradingEnabled: Boolean(controlsRes.data?.crypto_trading_enabled ?? true),
      defaultMode: controlsRes.data?.default_mode || 'unknown',
      stockMode: controlsRes.data?.stock_mode || 'unknown',
      cryptoMode: controlsRes.data?.crypto_mode || 'unknown',
      raw: controlsRes.data || {},
    },
    fetchedAt: new Date().toISOString(),
    diagnostics: {
      health: healthRes,
      settings: settingsRes,
      runtime: runtimeRes,
      controls: controlsRes,
      events: eventsRes,
      stockUniverse: stockUniverseRes,
      cryptoUniverse: cryptoUniverseRes,
      stockStrategies: stockStrategyResults,
      cryptoStrategies: cryptoStrategyResults,
      stockPositions: stockPositionResults,
      cryptoPositions: cryptoPositionResults,
      stockRisk: stockRiskResults,
      cryptoRisk: cryptoRiskResults,
      totalAccount: totalAccountRes,
      stockAccount: stockAccountRes,
      cryptoAccount: cryptoAccountRes,
    },
  };
}

export async function executeControlAction(actionKey, payload = {}) {
  const config = CONTROL_MAP[actionKey];
  if (!config) throw new Error(`Unsupported control action: ${actionKey}`);

  const response = await fetchJson(config.path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config.buildPayload(payload)),
  });

  return response;
}

export async function saveSettings(changes, currentSettings = []) {
  const metadata = Object.fromEntries((currentSettings || []).map((item) => [item.key, item]));
  const items = Object.entries(changes).map(([key, value]) => {
    const detail = metadata[key] || {};
    return {
      key,
      value: serializeSettingValue(value, detail.valueType || detail.value_type || 'string'),
      value_type: detail.valueType || detail.value_type || 'string',
      description: detail.description || null,
      is_secret: Boolean(detail.raw?.is_secret),
    };
  });

  return fetchJson('/settings/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  });
}

export async function saveSettingItems(items) {
  const payloadItems = (Array.isArray(items) ? items : []).map((item) => ({
    key: item.key,
    value: serializeSettingValue(item.value, item.valueType || item.value_type || 'string'),
    value_type: item.valueType || item.value_type || 'string',
    description: item.description || null,
    is_secret: Boolean(item.isSecret ?? item.is_secret),
  }));

  return fetchJson('/settings/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: payloadItems }),
  });
}

export async function fetchLiveRolloutChecklist() {
  return fetchJson('/operations/live-rollout/checklist');
}

export async function runConnectionDiagnostics() {
  const checks = [
    { label: 'health', path: '/health' },
    { label: 'controls', path: '/controls/snapshot' },
    { label: 'runtime', path: '/settings/runtime/snapshot' },
  ];

  return Promise.all(checks.map(async (check) => {
    try {
      const data = await fetchJson(check.path);
      return { ...check, ok: true, data };
    } catch (error) {
      return { ...check, ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  }));
}
