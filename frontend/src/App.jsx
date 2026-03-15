import { useEffect, useMemo, useRef, useState } from 'react';
import './styles.css';
import { executeControlAction, fetchLiveRolloutChecklist, loadLiveSnapshot, runConnectionDiagnostics, saveSettingItems, saveSettings } from './api/liveApi';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: '◫' },
  { id: 'performance', label: 'Performance', icon: '◭' },
  { id: 'universe', label: 'Universe', icon: '◎' },
  { id: 'strategies', label: 'Strategies', icon: '✦' },
  { id: 'positions', label: 'Position', icon: '▣' },
  { id: 'activity', label: 'Activity', icon: '◌' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
];

const PAGE_ACTIONS = {
  dashboard: [
    { key: 'refresh', label: 'Refresh', dangerous: false },
    { key: 'sync_incremental_candles', label: 'Sync Candles', dangerous: false },
    { key: 'toggle_kill_switch', label: 'Kill Switch', dangerous: true },
  ],
  performance: [{ key: 'refresh', label: 'Refresh', dangerous: false }],
  universe: [
    { key: 'refresh', label: 'Refresh', dangerous: false },
    { key: 'refresh_universe', label: 'Refresh Universe', dangerous: false },
    { key: 'backfill_candles', label: 'Backfill Candles', dangerous: false },
  ],
  strategies: [
    { key: 'refresh', label: 'Refresh', dangerous: false },
    { key: 'refresh_strategies', label: 'Refresh Evaluations', dangerous: false },
    { key: 'recompute_regime', label: 'Recompute Regime', dangerous: false },
  ],
  positions: [
    { key: 'refresh', label: 'Refresh', dangerous: false },
    { key: 'flatten_stocks', label: 'Flatten Stocks', dangerous: true },
    { key: 'flatten_crypto', label: 'Flatten Crypto', dangerous: true },
    { key: 'flatten_all', label: 'Flatten All', dangerous: true },
  ],
  activity: [{ key: 'refresh', label: 'Refresh', dangerous: false }],
  settings: [
    { key: 'refresh', label: 'Refresh', dangerous: false },
    { key: 'toggle_kill_switch', label: 'Kill Switch', dangerous: true },
  ],
};

const DEFAULT_SCOPE_OPTIONS = [
  { value: 'all', label: 'All scopes' },
  { value: 'stock', label: 'Stocks' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'paper', label: 'Paper' },
  { value: 'live', label: 'Live' },
  { value: 'eligible', label: 'Eligible' },
  { value: 'blocked', label: 'Blocked' },
];

const STRATEGY_SCOPE_OPTIONS = [
  { value: 'all', label: 'All strategies' },
  { value: 'eligible', label: 'Eligible' },
  { value: 'blocked', label: 'Blocked' },
];

const SCOPE_OPTIONS_BY_PAGE = {
  strategies: STRATEGY_SCOPE_OPTIONS,
};

const SETTINGS_GROUPS = [
  'Broker / Account',
  'Risk Controls',
  'Position Sizing',
  'Strategy Controls',
  'Universe Controls',
  'Execution Controls',
  'Stop Management',
  'Notifications',
  'UI / Admin',
];

const DEFAULT_MODE_KEY = 'execution.default_mode';
const STOCK_MODE_KEY = 'execution.stock.mode';
const CRYPTO_MODE_KEY = 'execution.crypto.mode';
const STOCK_LIVE_KEYS = new Set(['public_live_enabled', 'stock_live_enabled', 'live_stock_enabled']);
const STOCK_PAPER_KEYS = new Set(['alpaca_paper_stock_enabled', 'paper_stock_enabled', 'stock_paper_enabled']);
const CRYPTO_LIVE_KEYS = new Set(['kraken_live_enabled', 'crypto_live_enabled', 'live_crypto_enabled']);
const CRYPTO_PAPER_KEYS = new Set(['alpaca_paper_crypto_enabled', 'paper_crypto_enabled', 'crypto_paper_enabled']);

const QUICK_SETTING_METADATA = {
  'execution.default_mode': { valueType: 'string', description: 'Global execution mode' },
  'execution.stock.mode': { valueType: 'string', description: 'Stock broker route mode' },
  'execution.crypto.mode': { valueType: 'string', description: 'Crypto broker route mode' },
  'controls.stock.trading_enabled': { valueType: 'bool', description: 'Stock trading enabled' },
  'controls.crypto.trading_enabled': { valueType: 'bool', description: 'Crypto trading enabled' },
};

const QUICK_SETTING_LABELS = {
  'execution.default_mode': 'Global execution mode',
  'execution.stock.mode': 'Stock route',
  'execution.crypto.mode': 'Crypto route',
  'controls.stock.trading_enabled': 'Stock trading',
  'controls.crypto.trading_enabled': 'Crypto trading',
};

function formatMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const numeric = Number(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(2)}%`;
}

function formatNumber(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(Number(value));
}

function formatTime(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

function formatCompactTime(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString([], {
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return String(value);
  }
}

function toneFromNumber(value) {
  if (value == null || Number.isNaN(Number(value))) return 'neutral';
  const numeric = Number(value);
  if (numeric > 0) return 'positive';
  if (numeric < 0) return 'danger';
  return 'neutral';
}

function sortStrategiesByReadiness(rows, direction = 'desc') {
  const multiplier = direction === 'asc' ? 1 : -1;
  return [...rows].sort((left, right) => {
    const leftValue = Number(left.readinessScore);
    const rightValue = Number(right.readinessScore);
    const leftMissing = Number.isNaN(leftValue);
    const rightMissing = Number.isNaN(rightValue);
    if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
    if (!leftMissing && leftValue !== rightValue) return (leftValue - rightValue) * multiplier;
    return left.symbol.localeCompare(right.symbol) || left.primaryStrategy.localeCompare(right.primaryStrategy);
  });
}

function titleCase(value) {
  return String(value || 'unknown')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function buildSettingMap(settings) {
  return settings.reduce((acc, setting) => {
    acc[setting.key] = setting.value;
    return acc;
  }, {});
}

function normalizeBoolean(value) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  return ['true', '1', 'yes', 'on', 'enabled'].includes(String(value).toLowerCase());
}

function normalizeMode(value) {
  const mode = String(value ?? '').toLowerCase();
  if (mode === 'live' || mode === 'paper' || mode === 'mixed') return mode;
  return '';
}

function applyRoutingExclusivity(nextMap, changedKey, changedValue) {
  const enabled = normalizeBoolean(changedValue);
  const mode = normalizeMode(changedValue);

  if (changedKey === DEFAULT_MODE_KEY && mode) {
    nextMap[DEFAULT_MODE_KEY] = mode;
    if (mode === 'live' || mode === 'paper') {
      if (STOCK_MODE_KEY in nextMap) nextMap[STOCK_MODE_KEY] = mode;
      if (CRYPTO_MODE_KEY in nextMap) nextMap[CRYPTO_MODE_KEY] = mode;
    }
  }

  if (changedKey === STOCK_MODE_KEY && (mode === 'live' || mode === 'paper')) {
    nextMap[STOCK_MODE_KEY] = mode;
  }

  if (changedKey === CRYPTO_MODE_KEY && (mode === 'live' || mode === 'paper')) {
    nextMap[CRYPTO_MODE_KEY] = mode;
  }

  if (STOCK_LIVE_KEYS.has(changedKey) && enabled) {
    for (const key of STOCK_PAPER_KEYS) if (key in nextMap) nextMap[key] = false;
  }
  if (STOCK_PAPER_KEYS.has(changedKey) && enabled) {
    for (const key of STOCK_LIVE_KEYS) if (key in nextMap) nextMap[key] = false;
  }
  if (CRYPTO_LIVE_KEYS.has(changedKey) && enabled) {
    for (const key of CRYPTO_PAPER_KEYS) if (key in nextMap) nextMap[key] = false;
  }
  if (CRYPTO_PAPER_KEYS.has(changedKey) && enabled) {
    for (const key of CRYPTO_LIVE_KEYS) if (key in nextMap) nextMap[key] = false;
  }
  return nextMap;
}

function App() {
  const [page, setPage] = useState('dashboard');
  const [scope, setScope] = useState('all');
  const [query, setQuery] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [snapshot, setSnapshot] = useState({
    health: { status: 'loading', mode: 'loading', killSwitchEnabled: false, systemHalted: false },
    summary: {},
    performance: {},
    universe: { stocks: [], crypto: [] },
    strategies: [],
    positions: [],
    logs: [],
    settings: [],
    controlState: {},
    diagnostics: {},
    fetchedAt: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyAction, setBusyAction] = useState('');
  const [drawer, setDrawer] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null);
  const [draftSettings, setDraftSettings] = useState({});
  const [settingsFilter, setSettingsFilter] = useState('all');
  const [settingsQuery, setSettingsQuery] = useState('');
  const [reviewOpen, setReviewOpen] = useState(false);
  const importInputRef = useRef(null);

  const refresh = async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true);
    setError('');
    try {
      const live = await loadLiveSnapshot();
      setSnapshot(live);
      setDraftSettings(buildSettingMap(live.settings));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load live data.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const interval = window.setInterval(() => {
      refresh({ quiet: true });
    }, 12000);
    return () => window.clearInterval(interval);
  }, [autoRefresh]);

  useEffect(() => {
    if (!drawer) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setDrawer(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [drawer]);

  const scopeOptions = SCOPE_OPTIONS_BY_PAGE[page] || DEFAULT_SCOPE_OPTIONS;

  useEffect(() => {
    if (!scopeOptions.some((option) => option.value === scope)) {
      setScope(scopeOptions[0]?.value || 'all');
    }
  }, [page, scope, scopeOptions]);

  const changedSettings = useMemo(() => {
    const original = buildSettingMap(snapshot.settings);
    const changed = {};
    for (const [key, value] of Object.entries(draftSettings)) {
      const originalValue = original[key];
      if (JSON.stringify(value) !== JSON.stringify(originalValue)) {
        changed[key] = value;
      }
    }
    return changed;
  }, [draftSettings, snapshot.settings]);

  const pageActions = PAGE_ACTIONS[page] || PAGE_ACTIONS.dashboard;

  const settingsMap = useMemo(() => buildSettingMap(snapshot.settings), [snapshot.settings]);

  const filteredUniverse = useMemo(() => {
    const search = query.trim().toLowerCase();
    const filterRows = (rows) => rows.filter((row) => {
      const matchesScope = scope === 'all' || row.eligibility?.toLowerCase() === scope || String(row.symbol).toLowerCase().includes(scope);
      const matchesQuery = !search || String(row.symbol).toLowerCase().includes(search);
      return matchesScope && matchesQuery;
    });
    return {
      stocks: filterRows(snapshot.universe.stocks || []),
      crypto: filterRows(snapshot.universe.crypto || []),
    };
  }, [query, scope, snapshot.universe]);

  const filteredStrategies = useMemo(() => {
    const search = query.trim().toLowerCase();
    return (snapshot.strategies || []).filter((row) => {
      const normalizedStatus = String(row.status || '').toLowerCase();
      const isEligible = normalizedStatus !== 'blocked';
      const scopeMatch = scope === 'all'
        || (scope === 'eligible' && isEligible)
        || (scope === 'blocked' && normalizedStatus === 'blocked');
      const queryMatch = !search || String(row.symbol).toLowerCase().includes(search) || String(row.primaryStrategy).toLowerCase().includes(search);
      return scopeMatch && queryMatch;
    });
  }, [query, scope, snapshot.strategies]);

  const filteredPositions = useMemo(() => {
    const search = query.trim().toLowerCase();
    return (snapshot.positions || []).filter((row) => {
      const scopeMatch = scope === 'all' || row.assetClass.toLowerCase() === scope || String(row.account).toLowerCase() === scope;
      const queryMatch = !search || String(row.symbol).toLowerCase().includes(search) || String(row.strategy).toLowerCase().includes(search);
      return scopeMatch && queryMatch;
    });
  }, [query, scope, snapshot.positions]);

  const filteredLogs = useMemo(() => {
    const search = query.trim().toLowerCase();
    return (snapshot.logs || []).filter((row) => {
      const queryMatch = !search || String(row.message).toLowerCase().includes(search) || String(row.action).toLowerCase().includes(search) || String(row.symbol).toLowerCase().includes(search);
      return queryMatch;
    });
  }, [query, snapshot.logs]);

  const filteredSettings = useMemo(() => {
    return snapshot.settings.filter((setting) => {
      const categoryMatch = settingsFilter === 'all' || setting.category === settingsFilter;
      const search = settingsQuery.trim().toLowerCase();
      const queryMatch = !search || setting.label.toLowerCase().includes(search) || setting.key.toLowerCase().includes(search);
      return categoryMatch && queryMatch;
    });
  }, [settingsFilter, settingsQuery, snapshot.settings]);

  const defaultSettingValues = useMemo(() => ({
    'execution.default_mode': snapshot.controlState.defaultMode || 'paper',
    'execution.stock.mode': snapshot.controlState.stockMode || 'paper',
    'execution.crypto.mode': snapshot.controlState.cryptoMode || 'paper',
    'controls.stock.trading_enabled': Boolean(snapshot.controlState.stockTradingEnabled ?? true),
    'controls.crypto.trading_enabled': Boolean(snapshot.controlState.cryptoTradingEnabled ?? true),
  }), [snapshot.controlState]);

  const summarizeCandleSync = (details = []) => {
    if (!Array.isArray(details) || !details.length) return '';
    return details.map((detail) => {
      const asset = titleCase(detail.asset_class || 'asset');
      if (detail.skipped_reason) return `${asset} ${String(detail.skipped_reason).replace(/_/g, ' ')}`;
      if (detail.upserted_bars != null) return `${asset} ${detail.upserted_bars} bars`;
      return asset;
    }).join(' · ');
  };

  const handleAction = async (action) => {
    if (action.key === 'refresh') {
      refresh();
      return;
    }
    if (action.dangerous) {
      setConfirmAction(action);
      return;
    }
    try {
      setBusyAction(action.key);

      if (action.key === 'refresh_universe') {
        await executeControlAction('refresh_universe', { source: 'frontend' });
        const backfill = await executeControlAction('backfill_candles', { source: 'frontend' });
        await executeControlAction('recompute_regime', { source: 'frontend' });
        await executeControlAction('refresh_strategies', { source: 'frontend' });
        const summary = summarizeCandleSync(backfill.details);
        setNotice(summary ? `Universe pipeline refreshed. ${summary}.` : 'Universe pipeline refreshed.');
        await refresh({ quiet: true });
        return;
      }

      if (action.key === 'sync_incremental_candles') {
        const incremental = await executeControlAction('sync_incremental_candles', { source: 'frontend' });
        await executeControlAction('recompute_regime', { source: 'frontend' });
        await executeControlAction('refresh_strategies', { source: 'frontend' });
        const summary = summarizeCandleSync(incremental.details);
        setNotice(summary ? `Incremental sync completed. ${summary}.` : 'Incremental sync completed.');
        await refresh({ quiet: true });
        return;
      }

      if (action.key === 'recompute_regime') {
        const regime = await executeControlAction('recompute_regime', { source: 'frontend' });
        await executeControlAction('refresh_strategies', { source: 'frontend' });
        const summary = Array.isArray(regime.details)
          ? regime.details.map((detail) => {
            const asset = titleCase(detail.asset_class || 'asset');
            return `${asset} ${titleCase(detail.regime || 'unavailable')}`;
          }).join(' · ')
          : '';
        setNotice(summary ? `Regime recompute completed. ${summary}.` : 'Regime recompute completed.');
        await refresh({ quiet: true });
        return;
      }

      const response = await executeControlAction(action.key, { source: 'frontend' });
      setNotice(response?.message || `${action.label} submitted.`);
      await refresh({ quiet: true });
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : `Failed to run ${action.label}.`);
    } finally {
      setBusyAction('');
    }
  };

  const runConfirmedAction = async () => {
    if (!confirmAction) return;
    try {
      setBusyAction(confirmAction.key);
      const payload = confirmAction.key === 'toggle_kill_switch'
        ? { enabled: !snapshot.controlState.killSwitchEnabled, source: 'frontend' }
        : { source: 'frontend' };
      await executeControlAction(confirmAction.key, payload);
      setNotice(`${confirmAction.label} submitted.`);
      setConfirmAction(null);
      await refresh({ quiet: true });
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : `Failed to run ${confirmAction.label}.`);
    } finally {
      setBusyAction('');
    }
  };

  const updateDraftSetting = (key, value) => {
    setDraftSettings((current) => {
      const next = { ...current, [key]: value };
      return { ...applyRoutingExclusivity(next, key, value) };
    });
  };

  const saveDraftSettings = async () => {
    try {
      setBusyAction('save_settings');
      await saveSettings(changedSettings, snapshot.settings);
      setNotice(`Saved ${Object.keys(changedSettings).length} setting${Object.keys(changedSettings).length === 1 ? '' : 's'}.`);
      setReviewOpen(false);
      await refresh({ quiet: true });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Settings save failed.');
    } finally {
      setBusyAction('');
    }
  };

  const applyQuickSettingChange = async (changedKey, changedValue) => {
    const label = QUICK_SETTING_LABELS[changedKey] || titleCase(changedKey);
    const isDangerous = /mode|trading_enabled/i.test(changedKey);
    if (isDangerous) {
      const confirmed = window.confirm(`Apply ${label} now? This writes directly to the backend settings.`);
      if (!confirmed) return;
    }

    const base = {
      ...settingsMap,
      ...defaultSettingValues,
    };
    const next = { ...base, [changedKey]: changedValue };
    applyRoutingExclusivity(next, changedKey, changedValue);

    const diffEntries = Object.entries(next).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(base[key]));
    if (!diffEntries.length) return;

    const items = diffEntries.map(([key, value]) => {
      const detail = snapshot.settings.find((item) => item.key === key) || QUICK_SETTING_METADATA[key] || {};
      return {
        key,
        value,
        valueType: detail.valueType || detail.value_type || 'string',
        description: detail.description || null,
        isSecret: Boolean(detail.raw?.is_secret),
      };
    });

    try {
      setBusyAction(`quick:${changedKey}`);
      await saveSettingItems(items);
      setNotice(`${label} updated.`);
      await refresh({ quiet: true });
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : `Failed to update ${label}.`);
    } finally {
      setBusyAction('');
    }
  };

  const restoreFieldDefault = (setting) => {
    if (setting.defaultValue == null) return;
    updateDraftSetting(setting.key, setting.defaultValue);
  };

  const restoreCategoryDefaults = (settingsInCategory) => {
    setDraftSettings((current) => {
      const next = { ...current };
      for (const setting of settingsInCategory) {
        if (setting.defaultValue != null) {
          next[setting.key] = setting.defaultValue;
        }
      }
      return next;
    });
  };

  const exportCurrentSettings = () => {
    const payload = (snapshot.settings || []).map((setting) => ({
      key: setting.key,
      value: setting.value,
      value_type: setting.valueType || setting.value_type || 'string',
      description: setting.description || null,
      is_secret: Boolean(setting.raw?.is_secret),
    }));
    const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), items: payload }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'trade_bot_settings_export.json';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setNotice('Settings export downloaded.');
  };

  const importSettingsFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    try {
      const raw = await file.text();
      const parsed = JSON.parse(raw);
      const itemsSource = Array.isArray(parsed) ? parsed : Array.isArray(parsed.items) ? parsed.items : [];
      const items = itemsSource
        .filter((item) => item && item.key != null)
        .map((item) => ({
          key: item.key,
          value: item.value,
          valueType: item.valueType || item.value_type || snapshot.settings.find((row) => row.key === item.key)?.valueType || QUICK_SETTING_METADATA[item.key]?.valueType || 'string',
          description: item.description || snapshot.settings.find((row) => row.key === item.key)?.description || QUICK_SETTING_METADATA[item.key]?.description || null,
          isSecret: Boolean(item.isSecret ?? item.is_secret ?? snapshot.settings.find((row) => row.key === item.key)?.raw?.is_secret),
        }));

      if (!items.length) throw new Error('Import file did not contain any settings items.');
      const confirmed = window.confirm(`Import ${items.length} settings and save them to the backend now?`);
      if (!confirmed) return;

      setBusyAction('settings_import');
      await saveSettingItems(items);
      setNotice(`Imported ${items.length} setting${items.length === 1 ? '' : 's'}.`);
      await refresh({ quiet: true });
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : 'Settings import failed.');
    } finally {
      setBusyAction('');
    }
  };

  const runSettingsValidation = async () => {
    try {
      setBusyAction('validate_config');
      const checklist = await fetchLiveRolloutChecklist();
      setNotice(`Validation status: ${titleCase(checklist.overall_status)}. Live assets configured: ${checklist.live_asset_count}.`);
    } catch (validationError) {
      setError(validationError instanceof Error ? validationError.message : 'Config validation failed.');
    } finally {
      setBusyAction('');
    }
  };

  const testConnections = async () => {
    try {
      setBusyAction('test_connections');
      const diagnostics = await runConnectionDiagnostics();
      const healthy = diagnostics.filter((item) => item.ok).length;
      setNotice(`Connection diagnostics: ${healthy}/${diagnostics.length} checks answered.`);
    } catch (diagnosticError) {
      setError(diagnosticError instanceof Error ? diagnosticError.message : 'Connection diagnostics failed.');
    } finally {
      setBusyAction('');
    }
  };

  const resetDraftSettings = () => {
    setDraftSettings(buildSettingMap(snapshot.settings));
    setReviewOpen(false);
  };

  return (
    <div className="app-shell">
      <BackgroundGlow />
      <Sidebar page={page} setPage={setPage} snapshot={snapshot} />
      <main className="main-stage">
        <TopBar
          page={page}
          scope={scope}
          setScope={setScope}
          scopeOptions={scopeOptions}
          query={query}
          setQuery={setQuery}
          autoRefresh={autoRefresh}
          setAutoRefresh={setAutoRefresh}
          actions={pageActions}
          onAction={handleAction}
          busyAction={busyAction}
          fetchedAt={snapshot.fetchedAt}
        />

        {error ? <Banner tone="danger" text={error} /> : null}
        {notice ? <Banner tone="success" text={notice} onClose={() => setNotice('')} /> : null}

        {page === 'dashboard' && (
          <DashboardPage snapshot={snapshot} positions={filteredPositions.slice(0, 6)} onOpen={setDrawer} />
        )}
        {page === 'performance' && <PerformancePage snapshot={snapshot} positions={filteredPositions} />}
        {page === 'universe' && (
          <UniversePage universe={filteredUniverse} onOpen={setDrawer} loading={loading} />
        )}
        {page === 'strategies' && (
          <StrategiesPage strategies={filteredStrategies} onOpen={setDrawer} loading={loading} />
        )}
        {page === 'positions' && (
          <PositionsPage positions={filteredPositions} onOpen={setDrawer} loading={loading} />
        )}
        {page === 'activity' && (
          <ActivityPage logs={filteredLogs} onOpen={setDrawer} loading={loading} />
        )}
        {page === 'settings' && (
          <SettingsPage
            settings={filteredSettings}
            allSettings={snapshot.settings}
            snapshot={snapshot}
            draftSettings={draftSettings}
            changedSettings={changedSettings}
            settingsFilter={settingsFilter}
            setSettingsFilter={setSettingsFilter}
            settingsQuery={settingsQuery}
            setSettingsQuery={setSettingsQuery}
            onChange={updateDraftSetting}
            onReset={resetDraftSettings}
            onReview={() => setReviewOpen(true)}
            onRestoreFieldDefault={restoreFieldDefault}
            onRestoreCategoryDefaults={restoreCategoryDefaults}
            onQuickSettingChange={applyQuickSettingChange}
            onRunControlAction={handleAction}
            onExportSettings={exportCurrentSettings}
            onImportSettings={() => importInputRef.current?.click()}
            onValidateConfig={runSettingsValidation}
            onTestConnections={testConnections}
            busyAction={busyAction}
          />
        )}
      </main>

      <input ref={importInputRef} type="file" accept="application/json" className="hidden-input" onChange={importSettingsFile} />

      <Drawer drawer={drawer} onClose={() => setDrawer(null)} />

      {confirmAction ? (
        <ConfirmModal
          title={confirmAction.label}
          body={confirmAction.key === 'toggle_kill_switch'
            ? `This will ${snapshot.controlState.killSwitchEnabled ? 'disable' : 'enable'} the kill switch.`
            : 'This action affects live operator controls and should not be fired casually.'}
          busy={busyAction === confirmAction.key}
          onCancel={() => setConfirmAction(null)}
          onConfirm={runConfirmedAction}
        />
      ) : null}

      {reviewOpen ? (
        <ReviewModal
          changes={changedSettings}
          busy={busyAction === 'save_settings'}
          onCancel={() => setReviewOpen(false)}
          onConfirm={saveDraftSettings}
        />
      ) : null}
    </div>
  );
}

function BackgroundGlow() {
  return (
    <div className="background-wrap" aria-hidden="true">
      <div className="grid-noise" />
      <div className="light-beam beam-a" />
      <div className="light-beam beam-b" />
      <div className="light-beam beam-c" />
      <div className="orb orb-a" />
      <div className="orb orb-b" />
      <div className="orb orb-c" />
    </div>
  );
}

function Sidebar({ page, setPage, snapshot }) {
  return (
    <aside className="sidebar">
      <section className="panel-glass brand-lockup">
        <div className="brand-mark">TB</div>
        <div>
          <div className="eyebrow">Operator Console</div>
          <h1>Trade_Bot</h1>
        </div>
      </section>

      <section className="panel-soft status-card">
        <div className="eyebrow">System state</div>
        <div className="sidebar-state-grid">
          <StatusPill label={snapshot.health.status} tone={snapshot.health.status === 'ok' || snapshot.health.status === 'healthy' ? 'positive' : 'warning'} />
          <StatusPill label={snapshot.health.mode} tone="neutral" />
          <StatusPill label={snapshot.controlState.killSwitchEnabled ? 'Kill switch on' : 'Kill switch off'} tone={snapshot.controlState.killSwitchEnabled ? 'danger' : 'positive'} />
        </div>
      </section>

      <nav className="panel-soft nav-panel">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`nav-button ${page === item.id ? 'active' : ''}`}
            onClick={() => setPage(item.id)}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}

function TopBar({ page, scope, setScope, scopeOptions = DEFAULT_SCOPE_OPTIONS, query, setQuery, autoRefresh, setAutoRefresh, actions, onAction, busyAction, fetchedAt }) {
  return (
    <section className="panel-glass topbar">
      <div>
        <div className="eyebrow">{titleCase(page)}</div>
        <h2>{titleCase(page)} panel</h2>
        <div className="subtle">Last live refresh: {formatTime(fetchedAt)}</div>
      </div>

      <div className="topbar-controls">
        <input
          className="search-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search symbol, strategy, or event"
        />
        <select value={scope} onChange={(event) => setScope(event.target.value)}>
          {scopeOptions.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <label className="toggle-inline">
          <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
          <span>Auto refresh</span>
        </label>
      </div>

      <div className="action-rail">
        {actions.map((action) => (
          <button
            key={action.key}
            type="button"
            className={`action-button ${action.dangerous ? 'danger' : ''}`}
            disabled={busyAction === action.key}
            onClick={() => onAction(action)}
          >
            {busyAction === action.key ? 'Working…' : action.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function DashboardPage({ snapshot, positions, onOpen }) {
  const summary = snapshot.summary || {};
  const healthTone = snapshot.health.status === 'healthy' || snapshot.health.status === 'ok' ? 'positive' : 'warning';
  return (
    <section className="page-grid dashboard-grid">
      <div className="metric-strip">
        <MetricCard label="Total equity" value={formatMoney(summary.totalEquity)} tone="positive" />
        <MetricCard label="Day PnL" value={formatMoney(summary.totalDayPnl)} tone={Number(summary.totalDayPnl) >= 0 ? 'positive' : 'danger'} />
        <MetricCard label="Deployment" value={formatPct(summary.deploymentPct)} tone="violet" />
        <MetricCard label="Open positions" value={formatNumber(summary.openPositions)} tone="neutral" />
      </div>

      <article className="panel-glass hero-tile">
        <div className="eyebrow">Live snapshot</div>
        <h3>System now</h3>
        <div className="hero-grid">
          <MiniStat label="Mode" value={titleCase(summary.livePaperLabel)} />
          <MiniStat label="Kill switch" value={summary.killSwitchEnabled ? 'Enabled' : 'Disabled'} tone={summary.killSwitchEnabled ? 'danger' : 'positive'} />
          <MiniStat label="System health" value={titleCase(snapshot.health.status)} tone={healthTone} />
          <MiniStat label="Stocks equity" value={formatMoney(summary.stockEquity)} />
          <MiniStat label="Crypto equity" value={formatMoney(summary.cryptoEquity)} />
          <MiniStat label="Strategy rows" value={formatNumber(snapshot.strategies.length)} />
        </div>
      </article>

      <article className="panel-soft table-panel">
        <PanelHeader title="Open positions" subtitle="Live rows only, no mock smoke and mirrors" />
        <SimpleTable
          columns={['Symbol', 'Asset', 'Strategy', 'UPnL', 'Status']}
          rows={positions.map((row) => [
            row.symbol,
            row.assetClass,
            row.strategy,
            formatMoney(row.unrealizedPnl),
            <StatusPill label={row.status} tone={toneFromText(row.status)} />,
          ])}
          onRowClick={(index) => onOpen({ type: 'position', item: positions[index] })}
          emptyText="No live positions returned yet."
        />
      </article>

      <article className="panel-soft table-panel">
        <PanelHeader title="Recent activity" subtitle="Latest backend events" />
        <SimpleTable
          columns={['When', 'Event', 'Message']}
          rows={snapshot.logs.slice(0, 8).map((row) => [formatCompactTime(row.timestamp), `${titleCase(row.level)} · ${titleCase(row.action)}`, row.message])}
          onRowClick={(index) => onOpen({ type: 'log', item: snapshot.logs[index] })}
          emptyText="No events returned yet."
        />
      </article>
    </section>
  );
}

function PerformancePage({ snapshot, positions }) {
  const performance = snapshot.performance || {};
  return (
    <section className="page-grid performance-grid">
      <div className="metric-strip performance-metric-strip">
        <MetricCard label="Sharpe" value={performance.sharpe ?? '—'} tone="positive" />
        <MetricCard label="Sortino" value={performance.sortino ?? '—'} tone="violet" />
        <MetricCard label="Realized today" value={formatMoney(performance.realizedToday)} tone="neutral" />
        <MetricCard label="Unrealized" value={formatMoney(performance.unrealized)} tone={Number(performance.unrealized) >= 0 ? 'positive' : 'danger'} />
      </div>

      <article className="panel-glass hero-tile">
        <div className="eyebrow">Performance composition</div>
        <h3>Return quality</h3>
        <div className="hero-grid">
          <MiniStat label="Total PnL" value={formatMoney(performance.totalPnl)} tone={Number(performance.totalPnl) >= 0 ? 'positive' : 'danger'} />
          <MiniStat label="Max drawdown" value={formatPct(performance.maxDrawdown)} tone="warning" />
          <MiniStat label="Stock alpha" value={formatNumber(performance.stockAlpha)} />
          <MiniStat label="Crypto alpha" value={formatNumber(performance.cryptoAlpha)} />
        </div>
      </article>

      <article className="panel-soft table-panel full-span">
        <PanelHeader title="PnL by position" subtitle="Derived from live position rows when available" />
        <SimpleTable
          columns={['Symbol', 'Asset', 'UPnL', 'Realized', 'Market value']}
          rows={positions.map((row) => [
            row.symbol,
            row.assetClass,
            formatMoney(row.unrealizedPnl),
            formatMoney(row.realizedPnl),
            formatMoney(row.marketValue),
          ])}
          emptyText="No position rows available for attribution yet."
        />
      </article>
    </section>
  );
}

function UniversePage({ universe, onOpen, loading }) {
  return (
    <section className="page-grid two-column-grid">
      <article className="panel-glass table-panel">
        <PanelHeader title="Stock universe" subtitle={loading ? 'Refreshing live rows…' : 'Updates on stock 5m candle refresh'} />
        <SimpleTable
          className="centered-table universe-table"
          columns={['Rank', 'Symbol', 'Price', 'Change', 'Eligibility']}
          rows={universe.stocks.map((row) => [
            row.rank,
            row.symbol,
            formatMoney(row.lastPrice),
            <PercentValue value={row.changePct} />,
            <StatusPill label={row.eligibility} tone={toneFromText(row.eligibility)} />,
          ])}
          onRowClick={(index) => onOpen({ type: 'universe', item: universe.stocks[index] })}
          emptyText="No stock universe data returned from the backend."
        />
      </article>

      <article className="panel-glass table-panel">
        <PanelHeader title="Crypto universe" subtitle={loading ? 'Refreshing live rows…' : 'Updates on crypto 15m candle refresh'} />
        <SimpleTable
          className="centered-table universe-table"
          columns={['Rank', 'Pair', 'Price', 'Change', 'Eligibility']}
          rows={universe.crypto.map((row) => [
            row.rank,
            row.symbol,
            formatMoney(row.lastPrice),
            <PercentValue value={row.changePct} />,
            <StatusPill label={row.eligibility} tone={toneFromText(row.eligibility)} />,
          ])}
          onRowClick={(index) => onOpen({ type: 'universe', item: universe.crypto[index] })}
          emptyText="No crypto universe data returned from the backend."
        />
      </article>
    </section>
  );
}

function StrategiesPage({ strategies, onOpen, loading }) {
  const [stockReadinessOrder, setStockReadinessOrder] = useState('desc');
  const [cryptoReadinessOrder, setCryptoReadinessOrder] = useState('desc');
  const stocks = sortStrategiesByReadiness(
    strategies.filter((row) => row.assetClass === 'Stock'),
    stockReadinessOrder,
  );
  const crypto = sortStrategiesByReadiness(
    strategies.filter((row) => row.assetClass === 'Crypto'),
    cryptoReadinessOrder,
  );
  return (
    <section className="page-grid two-column-grid">
      <article className="panel-glass table-panel">
        <PanelHeader
          title="Stock strategies"
          subtitle={loading ? 'Polling live signals…' : 'Live evaluation rows'}
          action={(
            <button
              type="button"
              className="action-button compact"
              onClick={() => setStockReadinessOrder((current) => (current === 'desc' ? 'asc' : 'desc'))}
            >
              Readiness {stockReadinessOrder === 'desc' ? '↓' : '↑'}
            </button>
          )}
        />
        <SimpleTable
          className="centered-table strategy-table"
          columns={['Symbol', 'Primary', 'Readiness', 'Status', 'Regime']}
          rows={stocks.map((row) => [
            row.symbol,
            row.primaryStrategy,
            formatNumber(row.readinessScore),
            <StatusPill label={row.status} tone={toneFromText(row.status)} />,
            row.regime,
          ])}
          onRowClick={(index) => onOpen({ type: 'strategy', item: stocks[index] })}
          emptyText="No stock strategy rows returned yet."
        />
      </article>

      <article className="panel-glass table-panel">
        <PanelHeader
          title="Crypto strategies"
          subtitle={loading ? 'Polling live signals…' : 'Live evaluation rows'}
          action={(
            <button
              type="button"
              className="action-button compact"
              onClick={() => setCryptoReadinessOrder((current) => (current === 'desc' ? 'asc' : 'desc'))}
            >
              Readiness {cryptoReadinessOrder === 'desc' ? '↓' : '↑'}
            </button>
          )}
        />
        <SimpleTable
          className="centered-table strategy-table"
          columns={['Symbol', 'Primary', 'Readiness', 'Status', 'Regime']}
          rows={crypto.map((row) => [
            row.symbol,
            row.primaryStrategy,
            formatNumber(row.readinessScore),
            <StatusPill label={row.status} tone={toneFromText(row.status)} />,
            row.regime,
          ])}
          onRowClick={(index) => onOpen({ type: 'strategy', item: crypto[index] })}
          emptyText="No crypto strategy rows returned yet."
        />
      </article>
    </section>
  );
}

function PositionsPage({ positions, onOpen, loading }) {
  return (
    <section className="page-grid single-column-grid">
      <article className="panel-glass table-panel full-span">
        <PanelHeader title="Positions" subtitle={loading ? 'Refreshing broker state…' : 'Live positions and reconciliation state'} />
        <SimpleTable
          columns={['Symbol', 'Asset', 'Venue', 'Account', 'Qty', 'UPnL', 'Stop', 'Status']}
          rows={positions.map((row) => [
            row.symbol,
            row.assetClass,
            row.venue,
            row.account,
            formatNumber(row.qty),
            formatMoney(row.unrealizedPnl),
            formatMoney(row.stop),
            <StatusPill label={row.status} tone={toneFromText(row.status)} />,
          ])}
          onRowClick={(index) => onOpen({ type: 'position', item: positions[index] })}
          emptyText="No live positions returned yet."
        />
      </article>
    </section>
  );
}

function ActivityPage({ logs, onOpen, loading }) {
  return (
    <section className="page-grid single-column-grid">
      <article className="panel-glass table-panel full-span">
        <PanelHeader title="Activity log" subtitle={loading ? 'Polling system events…' : 'Frontend reflects backend event truth'} />
        <SimpleTable
          columns={['Time', 'Level', 'Component', 'Action', 'Message']}
          rows={logs.map((row) => [
            formatTime(row.timestamp),
            <StatusPill label={row.level} tone={toneFromText(row.level)} />,
            row.component,
            row.action,
            row.message,
          ])}
          onRowClick={(index) => onOpen({ type: 'log', item: logs[index] })}
          emptyText="No events returned yet."
        />
      </article>
    </section>
  );
}

function SettingsPage({
  settings,
  allSettings,
  snapshot,
  draftSettings,
  changedSettings,
  settingsFilter,
  setSettingsFilter,
  settingsQuery,
  setSettingsQuery,
  onChange,
  onReset,
  onReview,
  onRestoreFieldDefault,
  onRestoreCategoryDefaults,
  onQuickSettingChange,
  onRunControlAction,
  onExportSettings,
  onImportSettings,
  onValidateConfig,
  onTestConnections,
  busyAction,
}) {
  const grouped = SETTINGS_GROUPS.map((group) => ({
    group,
    rows: settings.filter((item) => item.category === group),
  })).filter((entry) => entry.rows.length > 0);

  return (
    <section className="page-grid single-column-grid settings-page-grid">
      <article className="panel-glass settings-toolbar">
        <div>
          <div className="eyebrow">Settings search</div>
          <h3>Backend-wired settings command deck</h3>
          <div className="subtle">Dangerous runtime actions route through backend endpoints. Settings edits stay staged until you save.</div>
        </div>
        <div className="topbar-controls">
          <input
            className="search-input"
            value={settingsQuery}
            onChange={(event) => setSettingsQuery(event.target.value)}
            placeholder="Search setting name"
          />
          <select value={settingsFilter} onChange={(event) => setSettingsFilter(event.target.value)}>
            <option value="all">All categories</option>
            {SETTINGS_GROUPS.map((group) => (
              <option key={group} value={group}>{group}</option>
            ))}
          </select>
          <button type="button" className="action-button" onClick={onExportSettings}>Export Settings</button>
          <button type="button" className="action-button" onClick={onImportSettings} disabled={busyAction === 'settings_import'}>
            {busyAction === 'settings_import' ? 'Importing…' : 'Import Settings'}
          </button>
          <button type="button" className="action-button" onClick={onTestConnections} disabled={busyAction === 'test_connections'}>
            {busyAction === 'test_connections' ? 'Testing…' : 'Test Connection'}
          </button>
          <button type="button" className="action-button" onClick={onValidateConfig} disabled={busyAction === 'validate_config'}>
            {busyAction === 'validate_config' ? 'Validating…' : 'Validate Config'}
          </button>
          <button type="button" className="action-button" onClick={onReset}>Cancel changes</button>
          <button type="button" className="action-button" disabled={!Object.keys(changedSettings).length || busyAction === 'save_settings'} onClick={onReview}>
            Review and Save
          </button>
        </div>
      </article>

      <SettingsCommandDeck
        snapshot={snapshot}
        allSettings={allSettings}
        busyAction={busyAction}
        onQuickSettingChange={onQuickSettingChange}
        onRunControlAction={onRunControlAction}
      />

      {renderRoutingBanner(allSettings, draftSettings)}

      {grouped.length ? grouped.map(({ group, rows }) => (
        <article key={group} className="panel-soft settings-group">
          <PanelHeader
            title={group}
            subtitle={`${rows.length} live setting${rows.length === 1 ? '' : 's'}`}
            action={(
              <button type="button" className="action-button compact" onClick={() => onRestoreCategoryDefaults(rows)}>
                Restore category defaults
              </button>
            )}
          />
          <div className="settings-list">
            {rows.map((setting) => (
              <SettingRow
                key={setting.key}
                setting={setting}
                value={draftSettings[setting.key]}
                dirty={Object.prototype.hasOwnProperty.call(changedSettings, setting.key)}
                onChange={onChange}
                onRestoreDefault={onRestoreFieldDefault}
              />
            ))}
          </div>
        </article>
      )) : (
        <article className="panel-soft settings-group">
          <PanelHeader title="No matching settings" subtitle="This category is still running on defaults or your search filtered everything out." />
          <div className="subtle">Pick another category or clear the search box to reveal the full settings vault.</div>
        </article>
      )}
    </section>
  );
}

function SettingsCommandDeck({ snapshot, allSettings, busyAction, onQuickSettingChange, onRunControlAction }) {
  const controls = snapshot.controlState || {};
  const hasSetting = (key) => allSettings.some((item) => item.key === key);
  const canToggleStocks = hasSetting('controls.stock.trading_enabled') || controls.stockTradingEnabled != null;
  const canToggleCrypto = hasSetting('controls.crypto.trading_enabled') || controls.cryptoTradingEnabled != null;

  return (
    <section className="settings-command-grid">
      <article className="panel-soft command-card">
        <PanelHeader title="Execution routes" subtitle="Immediate backend write for route mode controls" />
        <div className="command-stack">
          <ModeButtonRow
            label="Global"
            value={controls.defaultMode || 'paper'}
            busy={busyAction.startsWith('quick:execution.default_mode')}
            onSelect={(value) => onQuickSettingChange('execution.default_mode', value)}
            options={[
              { value: 'paper', label: 'Paper' },
              { value: 'mixed', label: 'Mixed' },
              { value: 'live', label: 'Live' },
            ]}
          />
          <ModeButtonRow
            label="Stocks"
            value={controls.stockMode || 'paper'}
            busy={busyAction.startsWith('quick:execution.stock.mode')}
            onSelect={(value) => onQuickSettingChange('execution.stock.mode', value)}
          />
          <ModeButtonRow
            label="Crypto"
            value={controls.cryptoMode || 'paper'}
            busy={busyAction.startsWith('quick:execution.crypto.mode')}
            onSelect={(value) => onQuickSettingChange('execution.crypto.mode', value)}
          />
        </div>
      </article>

      <article className="panel-soft command-card">
        <PanelHeader title="Trading enablement" subtitle="Per-asset trading gates saved through backend settings" />
        <div className="command-stack">
          {canToggleStocks ? (
            <QuickToggleRow
              label="Stock trading"
              enabled={Boolean(controls.stockTradingEnabled ?? true)}
              busy={busyAction.startsWith('quick:controls.stock.trading_enabled')}
              onToggle={() => onQuickSettingChange('controls.stock.trading_enabled', !Boolean(controls.stockTradingEnabled ?? true))}
            />
          ) : null}
          {canToggleCrypto ? (
            <QuickToggleRow
              label="Crypto trading"
              enabled={Boolean(controls.cryptoTradingEnabled ?? true)}
              busy={busyAction.startsWith('quick:controls.crypto.trading_enabled')}
              onToggle={() => onQuickSettingChange('controls.crypto.trading_enabled', !Boolean(controls.cryptoTradingEnabled ?? true))}
            />
          ) : null}
          <div className="subtle">Kraken live vs Alpaca crypto paper and Public live vs Alpaca stock paper remain mutually exclusive when route modes change.</div>
        </div>
      </article>

      <article className="panel-soft command-card">
        <PanelHeader title="Safety controls" subtitle="Direct backend control routes, confirmations included" />
        <div className="command-stack">
          <QuickActionButton
            label={controls.killSwitchEnabled ? 'Disable Kill Switch' : 'Enable Kill Switch'}
            busy={busyAction === 'toggle_kill_switch'}
            dangerous
            onClick={() => onRunControlAction({ key: 'toggle_kill_switch', label: controls.killSwitchEnabled ? 'Disable Kill Switch' : 'Enable Kill Switch', dangerous: true })}
          />
          <div className="button-cluster">
            <QuickActionButton label="Flatten Stocks" busy={busyAction === 'flatten_stocks'} dangerous onClick={() => onRunControlAction({ key: 'flatten_stocks', label: 'Flatten Stocks', dangerous: true })} />
            <QuickActionButton label="Flatten Crypto" busy={busyAction === 'flatten_crypto'} dangerous onClick={() => onRunControlAction({ key: 'flatten_crypto', label: 'Flatten Crypto', dangerous: true })} />
            <QuickActionButton label="Flatten All" busy={busyAction === 'flatten_all'} dangerous onClick={() => onRunControlAction({ key: 'flatten_all', label: 'Flatten All', dangerous: true })} />
          </div>
        </div>
      </article>
    </section>
  );
}

function ModeButtonRow({ label, value, onSelect, busy = false, options = [{ value: 'paper', label: 'Paper' }, { value: 'live', label: 'Live' }] }) {
  return (
    <div className="quick-row">
      <div>
        <div className="setting-label">{label}</div>
        <div className="subtle">Current route: {titleCase(value)}</div>
      </div>
      <div className="button-cluster">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`action-button compact ${value === option.value ? 'selected' : ''}`}
            disabled={busy}
            onClick={() => onSelect(option.value)}
          >
            {busy && value !== option.value ? 'Working…' : option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function QuickToggleRow({ label, enabled, onToggle, busy = false }) {
  return (
    <div className="quick-row">
      <div>
        <div className="setting-label">{label}</div>
        <div className="subtle">{enabled ? 'Enabled in backend state' : 'Disabled in backend state'}</div>
      </div>
      <button type="button" className={`action-button compact ${enabled ? 'selected' : ''}`} disabled={busy} onClick={onToggle}>
        {busy ? 'Working…' : enabled ? 'Disable' : 'Enable'}
      </button>
    </div>
  );
}

function QuickActionButton({ label, onClick, busy = false, dangerous = false }) {
  return (
    <button type="button" className={`action-button compact ${dangerous ? 'danger' : ''}`} disabled={busy} onClick={onClick}>
      {busy ? 'Working…' : label}
    </button>
  );
}

function SettingRow({ setting, value, dirty, onChange, onRestoreDefault }) {
  const inputId = `setting-${setting.key}`;
  const hasDefault = setting.defaultValue != null;
  return (
    <div className={`setting-row ${dirty ? 'dirty' : ''}`}>
      <div>
        <label className="setting-label" htmlFor={inputId}>{setting.label}</label>
        <div className="subtle mono">{setting.key}</div>
        {setting.description ? <div className="subtle">{setting.description}</div> : null}
        <div className="setting-meta">
          <span>Default: {String(setting.defaultValue ?? '—')}</span>
          <span>Updated: {formatTime(setting.lastChanged)}</span>
          {setting.dangerous ? <span className="warning-text">Dangerous</span> : null}
        </div>
      </div>

      <div className="setting-input-wrap">
        <div className="setting-input-stack">
          {setting.type === 'boolean' ? (
            <label className="toggle-switch" htmlFor={inputId}>
              <input id={inputId} type="checkbox" checked={normalizeBoolean(value)} onChange={(event) => onChange(setting.key, event.target.checked)} />
              <span>{normalizeBoolean(value) ? 'Enabled' : 'Disabled'}</span>
            </label>
          ) : setting.type === 'mode' ? (
            <select id={inputId} value={value ?? ''} onChange={(event) => onChange(setting.key, event.target.value)}>
              {setting.options.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          ) : setting.type === 'number' ? (
            <input id={inputId} type="number" value={value ?? ''} onChange={(event) => onChange(setting.key, event.target.value === '' ? '' : Number(event.target.value))} />
          ) : (
            <input id={inputId} type="text" value={value ?? ''} onChange={(event) => onChange(setting.key, event.target.value)} />
          )}
          <button type="button" className="action-button compact" disabled={!hasDefault} onClick={() => onRestoreDefault(setting)}>
            Restore Default
          </button>
        </div>
      </div>
    </div>
  );
}

function renderRoutingBanner(settings, draftSettings) {
  const keys = new Set(settings.map((item) => item.key));
  const rows = [];

  const stockMode = keys.has(STOCK_MODE_KEY)
    ? normalizeMode(draftSettings[STOCK_MODE_KEY])
    : ([...STOCK_LIVE_KEYS].some((key) => normalizeBoolean(draftSettings[key])) ? 'live' : 'paper');
  const cryptoMode = keys.has(CRYPTO_MODE_KEY)
    ? normalizeMode(draftSettings[CRYPTO_MODE_KEY])
    : ([...CRYPTO_LIVE_KEYS].some((key) => normalizeBoolean(draftSettings[key])) ? 'live' : 'paper');

  if (keys.has(STOCK_MODE_KEY) || [...STOCK_LIVE_KEYS, ...STOCK_PAPER_KEYS].some((key) => keys.has(key))) {
    rows.push({
      label: 'Stocks',
      mode: stockMode || 'paper',
      primaryRoute: (stockMode || 'paper') === 'live' ? 'Public live' : 'Alpaca stock paper',
      secondaryRoute: (stockMode || 'paper') === 'live' ? 'Alpaca stock paper off' : 'Public live off',
    });
  }

  if (keys.has(CRYPTO_MODE_KEY) || [...CRYPTO_LIVE_KEYS, ...CRYPTO_PAPER_KEYS].some((key) => keys.has(key))) {
    rows.push({
      label: 'Crypto',
      mode: cryptoMode || 'paper',
      primaryRoute: (cryptoMode || 'paper') === 'live' ? 'Kraken live' : 'Alpaca crypto paper',
      secondaryRoute: (cryptoMode || 'paper') === 'live' ? 'Alpaca crypto paper off' : 'Kraken live off',
    });
  }

  if (!rows.length) return null;

  return (
    <article className="panel-soft routing-banner">
      <PanelHeader title="Broker mode exclusivity" subtitle="Live routes and paper routes stay mutually exclusive for each asset class." />
      <div className="routing-grid">
        {rows.map((row) => (
          <div key={row.label} className="routing-card">
            <div className="routing-name">{row.label}</div>
            <StatusPill label={row.mode === 'live' ? 'Live route active' : 'Paper route active'} tone={row.mode === 'live' ? 'danger' : 'positive'} />
            <StatusPill label={row.primaryRoute} tone={row.mode === 'live' ? 'danger' : 'positive'} />
            <StatusPill label={row.secondaryRoute} tone="neutral" />
          </div>
        ))}
      </div>
    </article>
  );
}

function Drawer({ drawer, onClose }) {
  if (!drawer) return null;

  const title = drawer.type === 'strategy'
    ? 'Strategy explanation drawer'
    : drawer.type === 'position'
      ? 'Position detail drawer'
      : drawer.type === 'log'
        ? 'Event detail drawer'
        : 'Universe detail drawer';

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer panel-glass" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <div className="drawer-header">
          <div>
            <div className="eyebrow">{title}</div>
            <h3>{drawer.item.symbol || drawer.item.action || 'Detail'}</h3>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close detail panel">
            ✕
          </button>
        </div>

        {drawer.type === 'strategy' ? <StrategyDetail item={drawer.item} /> : null}
        {drawer.type === 'position' ? <PositionDetail item={drawer.item} /> : null}
        {drawer.type === 'log' ? <LogDetail item={drawer.item} /> : null}
        {drawer.type === 'universe' ? <UniverseDetail item={drawer.item} /> : null}
      </aside>
    </div>
  );
}

function StrategyDetail({ item }) {
  return (
    <div className="detail-stack">
      <div className="pill-row">
        <StatusPill label={item.status} tone={toneFromText(item.status)} />
        <StatusPill label={item.regime} tone="neutral" />
      </div>
      <DetailRow label="Display symbol" value={item.symbol} />
      <DetailRow label="Venue symbol" value={item.marketSymbol || item.rawSymbol || '—'} />
      <DetailRow label="Primary strategy" value={item.primaryStrategy} />
      <DetailRow label="Secondary strategy" value={item.secondaryStrategies || '—'} />
      <DetailRow label="Readiness score" value={formatNumber(item.readinessScore)} />
      <DetailRow label="Thresholds passed" value={item.thresholdsPassed || 'None'} />
      <DetailRow label="Thresholds failed" value={item.thresholdsFailed || 'None'} />
      <DetailRow label="Regime requirement" value={item.regimeRequirement} />
      <DetailRow label="Next reevaluation" value={formatTime(item.nextReevaluation)} />
      <DetailRow label="Previous signal attempts" value={item.previousSignalAttempts || 'None'} />
      <DetailRow label="Why it did or did not qualify" value={item.explanation} />
    </div>
  );
}

function PositionDetail({ item }) {
  return (
    <div className="detail-stack">
      <div className="pill-row">
        <StatusPill label={item.status} tone={toneFromText(item.status)} />
        <StatusPill label={item.account} tone="neutral" />
      </div>
      <DetailRow label="Display symbol" value={item.symbol} />
      <DetailRow label="Venue symbol" value={item.marketSymbol || item.rawSymbol || '—'} />
      <DetailRow label="Venue" value={item.venue} />
      <DetailRow label="Strategy" value={item.strategy} />
      <DetailRow label="Qty" value={formatNumber(item.qty)} />
      <DetailRow label="Average entry" value={formatMoney(item.avgEntry)} />
      <DetailRow label="Last price" value={formatMoney(item.lastPrice)} />
      <DetailRow label="Market value" value={formatMoney(item.marketValue)} />
      <DetailRow label="Unrealized PnL" value={formatMoney(item.unrealizedPnl)} />
      <DetailRow label="Realized PnL" value={formatMoney(item.realizedPnl)} />
      <DetailRow label="Stop" value={formatMoney(item.stop)} />
      <DetailRow label="Target" value={item.target} />
      <DetailRow label="Time in trade" value={item.timeInTrade} />
      <DetailRow label="Updated" value={formatTime(item.updatedAt)} />
    </div>
  );
}

function LogDetail({ item }) {
  return (
    <div className="detail-stack">
      <div className="pill-row">
        <StatusPill label={item.level} tone={toneFromText(item.level)} />
        <StatusPill label={item.component} tone="neutral" />
      </div>
      <DetailRow label="Timestamp" value={formatTime(item.timestamp)} />
      <DetailRow label="Action" value={item.action} />
      <DetailRow label="Symbol" value={item.symbol || '—'} />
      <DetailRow label="Status" value={item.status || '—'} />
      <DetailRow label="Message" value={item.message} />
      <DetailRow label="Payload" value={typeof item.payload === 'string' ? item.payload : JSON.stringify(item.payload ?? {}, null, 2)} mono />
    </div>
  );
}

function UniverseDetail({ item }) {
  return (
    <div className="detail-stack">
      <div className="pill-row">
        <StatusPill label={item.eligibility} tone={toneFromText(item.eligibility)} />
      </div>
      <DetailRow label="Display symbol" value={item.symbol} />
      <DetailRow label="Asset name" value={item.displayName || '—'} />
      <DetailRow label="Venue symbol" value={item.marketSymbol || item.rawSymbol || '—'} />
      <DetailRow label="Rank" value={String(item.rank)} />
      <DetailRow label="Source rank" value={String(item.sourceRank ?? item.rank)} />
      <DetailRow label="Last price" value={formatMoney(item.lastPrice)} />
      <DetailRow label="Change" value={<PercentValue value={item.changePct} />} />
      <DetailRow label="Liquidity score" value={formatNumber(item.liquidityScore)} />
      <DetailRow label="Participation score" value={formatNumber(item.participationScore)} />
      <DetailRow label="Trend score" value={formatNumber(item.trendScore)} />
      <DetailRow label="Composite score" value={formatNumber(item.compositeScore)} />
      <DetailRow label="Why symbol is in universe" value={item.selectionReason || 'None'} />
      <DetailRow label="Last candle" value={formatTime(item.lastCandleAt)} />
      <DetailRow label="Block reason" value={item.blockReason || 'None'} />
      <DetailRow label="Raw factors" value={JSON.stringify(item.raw ?? {}, null, 2)} mono />
    </div>
  );
}

function SimpleTable({ columns, rows, onRowClick, emptyText, className = '' }) {
  return (
    <div className={`table-wrap ${className}`.trim()}>
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {!rows.length ? (
            <tr>
              <td colSpan={columns.length} className="empty-cell">{emptyText}</td>
            </tr>
          ) : rows.map((row, index) => (
            <tr key={`row-${index}`} onClick={onRowClick ? () => onRowClick(index) : undefined} className={onRowClick ? 'clickable-row' : ''}>
              {row.map((cell, cellIndex) => <td key={`cell-${index}-${cellIndex}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PanelHeader({ title, subtitle, action = null }) {
  return (
    <div className="panel-header">
      <div>
        <div className="eyebrow">{subtitle}</div>
        <h3>{title}</h3>
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

function MetricCard({ label, value, tone = 'neutral' }) {
  return (
    <article className={`panel-soft mini-stat tone-${tone}`}>
      <div className="eyebrow">{label}</div>
      <div className="metric-value">{value}</div>
    </article>
  );
}

function MiniStat({ label, value, tone = 'neutral' }) {
  return (
    <div className={`mini-stat-tile tone-${tone}`}>
      <div className="eyebrow">{label}</div>
      <div className="metric-value compact">{value}</div>
    </div>
  );
}

function StatusPill({ label, tone = 'neutral' }) {
  return <span className={`status-pill tone-${tone}`}>{titleCase(label)}</span>;
}

function PercentValue({ value }) {
  return <span className={`numeric-tone tone-${toneFromNumber(value)}`}>{formatPct(value)}</span>;
}

function DetailRow({ label, value, mono = false }) {
  return (
    <div className="detail-row">
      <div className="detail-label">{label}</div>
      <div className={`detail-value ${mono ? 'mono' : ''}`}>{value}</div>
    </div>
  );
}

function Banner({ tone, text, onClose }) {
  return (
    <div className={`banner tone-${tone}`}>
      <span>{text}</span>
      {onClose ? <button type="button" onClick={onClose}>Dismiss</button> : null}
    </div>
  );
}

function ConfirmModal({ title, body, busy, onCancel, onConfirm }) {
  return (
    <div className="modal-backdrop">
      <div className="panel-glass modal-card">
        <div className="eyebrow">Dangerous action</div>
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="modal-actions">
          <button type="button" className="action-button" onClick={onCancel}>Cancel</button>
          <button type="button" className="action-button danger" onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : 'Confirm'}</button>
        </div>
      </div>
    </div>
  );
}

function ReviewModal({ changes, busy, onCancel, onConfirm }) {
  const entries = Object.entries(changes);
  return (
    <div className="modal-backdrop">
      <div className="panel-glass modal-card wide">
        <div className="eyebrow">Review settings</div>
        <h3>{entries.length} staged change{entries.length === 1 ? '' : 's'}</h3>
        <div className="review-list">
          {entries.map(([key, value]) => (
            <div key={key} className="review-row">
              <span className="mono">{key}</span>
              <span>{String(value)}</span>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="action-button" onClick={onCancel}>Keep editing</button>
          <button type="button" className="action-button" onClick={onConfirm} disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button>
        </div>
      </div>
    </div>
  );
}

function toneFromText(text) {
  const value = String(text || '').toLowerCase();
  if (value.includes('ready') || value.includes('eligible') || value.includes('healthy') || value.includes('managed') || value.includes('enabled') || value.includes('info') || value.includes('ok')) return 'positive';
  if (value.includes('warn') || value.includes('cooldown') || value.includes('near') || value.includes('neutral')) return 'warning';
  if (value.includes('block') || value.includes('stale') || value.includes('error') || value.includes('danger') || value.includes('kill') || value.includes('halt') || value.includes('mismatch')) return 'danger';
  if (value.includes('bull') || value.includes('active')) return 'violet';
  return 'neutral';
}

export default App;
