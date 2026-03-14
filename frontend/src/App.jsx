import { useEffect, useMemo, useState } from 'react';
import './styles.css';
import { API_BASE, executeControlAction, loadLiveSnapshot, saveSettings } from './api/liveApi';

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
      const scopeMatch = scope === 'all' || row.assetClass.toLowerCase() === scope;
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
      await executeControlAction(action.key, { source: 'frontend' });
      setNotice(`${action.label} submitted.`);
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
        <Banner tone="info" text={`Live API base: ${API_BASE}`} />

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
            draftSettings={draftSettings}
            changedSettings={changedSettings}
            settingsFilter={settingsFilter}
            setSettingsFilter={setSettingsFilter}
            settingsQuery={settingsQuery}
            setSettingsQuery={setSettingsQuery}
            onChange={updateDraftSetting}
            onReset={resetDraftSettings}
            onReview={() => setReviewOpen(true)}
            busyAction={busyAction}
          />
        )}
      </main>

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

function TopBar({ page, scope, setScope, query, setQuery, autoRefresh, setAutoRefresh, actions, onAction, busyAction, fetchedAt }) {
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
          <option value="all">All scopes</option>
          <option value="stock">Stocks</option>
          <option value="crypto">Crypto</option>
          <option value="paper">Paper</option>
          <option value="live">Live</option>
          <option value="eligible">Eligible</option>
          <option value="blocked">Blocked</option>
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
          <MiniStat label="API rows" value={formatNumber(snapshot.logs.length + snapshot.positions.length + snapshot.strategies.length)} />
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
          columns={['Time', 'Level', 'Action', 'Message']}
          rows={snapshot.logs.slice(0, 8).map((row) => [formatTime(row.timestamp), row.level, row.action, row.message])}
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
      <div className="metric-strip">
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
        <PanelHeader title="Stock universe" subtitle={loading ? 'Refreshing live rows…' : 'Live universe rows'} />
        <SimpleTable
          columns={['Rank', 'Symbol', 'Price', 'Change', 'Eligibility']}
          rows={universe.stocks.map((row) => [
            row.rank,
            row.symbol,
            formatMoney(row.lastPrice),
            formatPct(row.changePct),
            <StatusPill label={row.eligibility} tone={toneFromText(row.eligibility)} />,
          ])}
          onRowClick={(index) => onOpen({ type: 'universe', item: universe.stocks[index] })}
          emptyText="No stock universe data returned from the backend."
        />
      </article>

      <article className="panel-glass table-panel">
        <PanelHeader title="Crypto universe" subtitle={loading ? 'Refreshing live rows…' : 'Live universe rows'} />
        <SimpleTable
          columns={['Rank', 'Pair', 'Price', 'Change', 'Eligibility']}
          rows={universe.crypto.map((row) => [
            row.rank,
            row.symbol,
            formatMoney(row.lastPrice),
            formatPct(row.changePct),
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
  const stocks = strategies.filter((row) => row.assetClass === 'Stock');
  const crypto = strategies.filter((row) => row.assetClass === 'Crypto');
  return (
    <section className="page-grid two-column-grid">
      <article className="panel-glass table-panel">
        <PanelHeader title="Stock strategies" subtitle={loading ? 'Polling live signals…' : 'Live evaluation rows'} />
        <SimpleTable
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
        <PanelHeader title="Crypto strategies" subtitle={loading ? 'Polling live signals…' : 'Live evaluation rows'} />
        <SimpleTable
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

function SettingsPage({ settings, draftSettings, changedSettings, settingsFilter, setSettingsFilter, settingsQuery, setSettingsQuery, onChange, onReset, onReview, busyAction }) {
  const grouped = SETTINGS_GROUPS.map((group) => ({
    group,
    rows: settings.filter((item) => item.category === group),
  })).filter((entry) => entry.rows.length > 0);

  return (
    <section className="page-grid single-column-grid">
      <article className="panel-glass settings-toolbar">
        <div>
          <div className="eyebrow">Settings search</div>
          <h3>Staged settings editor</h3>
          <div className="subtle">Changes stay local until you review and save.</div>
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
          <button type="button" className="action-button" onClick={onReset}>Cancel changes</button>
          <button type="button" className="action-button" disabled={!Object.keys(changedSettings).length || busyAction === 'save_settings'} onClick={onReview}>
            Review and Save
          </button>
        </div>
      </article>

      {renderRoutingBanner(settings, draftSettings)}

      {grouped.map(({ group, rows }) => (
        <article key={group} className="panel-soft settings-group">
          <PanelHeader title={group} subtitle={`${rows.length} live setting${rows.length === 1 ? '' : 's'}`} />
          <div className="settings-list">
            {rows.map((setting) => (
              <SettingRow
                key={setting.key}
                setting={setting}
                value={draftSettings[setting.key]}
                dirty={Object.prototype.hasOwnProperty.call(changedSettings, setting.key)}
                onChange={onChange}
              />
            ))}
          </div>
        </article>
      ))}
    </section>
  );
}

function SettingRow({ setting, value, dirty, onChange }) {
  const inputId = `setting-${setting.key}`;
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
      <DetailRow label="Primary strategy" value={item.primaryStrategy} />
      <DetailRow label="Secondary strategy" value={item.secondaryStrategies || '—'} />
      <DetailRow label="Readiness score" value={formatNumber(item.readinessScore)} />
      <DetailRow label="Thresholds passed" value={item.thresholdsPassed || 'None'} />
      <DetailRow label="Thresholds failed" value={item.thresholdsFailed || 'None'} />
      <DetailRow label="Regime requirement" value={item.regimeRequirement} />
      <DetailRow label="Next reevaluation" value={item.nextReevaluation} />
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
      <DetailRow label="Rank" value={String(item.rank)} />
      <DetailRow label="Last price" value={formatMoney(item.lastPrice)} />
      <DetailRow label="Change" value={formatPct(item.changePct)} />
      <DetailRow label="Liquidity score" value={formatNumber(item.liquidityScore)} />
      <DetailRow label="Participation score" value={formatNumber(item.participationScore)} />
      <DetailRow label="Trend score" value={formatNumber(item.trendScore)} />
      <DetailRow label="Composite score" value={formatNumber(item.compositeScore)} />
      <DetailRow label="Block reason" value={item.blockReason || 'None'} />
      <DetailRow label="Raw factors" value={JSON.stringify(item.raw ?? {}, null, 2)} mono />
    </div>
  );
}

function SimpleTable({ columns, rows, onRowClick, emptyText }) {
  return (
    <div className="table-wrap">
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

function PanelHeader({ title, subtitle }) {
  return (
    <div className="panel-header">
      <div>
        <div className="eyebrow">{subtitle}</div>
        <h3>{title}</h3>
      </div>
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
