import { useEffect, useMemo, useState } from 'react'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8101'
const apiPrefix = '/api/v1'
const sidebarPages = [
  { key: 'dashboard', label: 'Dashboard', icon: '◫' },
  { key: 'performance', label: 'Performance', icon: '◧' },
  { key: 'universe', label: 'Universe', icon: '◎' },
  { key: 'strategies', label: 'Strategies', icon: '⌁' },
  { key: 'positions', label: 'Position', icon: '▣' },
  { key: 'activity', label: 'Activity', icon: '◌' },
  { key: 'settings', label: 'Settings', icon: '⚙' },
]
const topUtilityPages = [{ key: 'data', label: 'Data' }]
const refreshOptions = [0, 10, 20, 30, 60]
const settingsCatalog = [
  {
    category: 'App / Broker Modes',
    fields: [
      field('execution.default_mode', 'Default execution mode', 'string', 'mixed', { options: ['mixed', 'paper', 'live'] }),
      field('execution.stock.mode', 'Stock route mode', 'string', 'paper', { options: ['paper', 'live'] }),
      field('execution.crypto.mode', 'Crypto route mode', 'string', 'paper', { options: ['paper', 'live'] }),
      field('controls.stock.trading_enabled', 'Stocks trading enabled', 'bool', 'true', { dangerous: true }),
      field('controls.crypto.trading_enabled', 'Crypto trading enabled', 'bool', 'true', { dangerous: true }),
    ],
  },
  {
    category: 'Universe Settings',
    fields: [
      field('stock_universe_source', 'Stock universe source', 'string', 'ai', { options: ['ai', 'fallback'] }),
      field('stock_universe_max_size', 'Stock universe max size', 'int', '50'),
      field('ai_enabled', 'AI ranking enabled', 'bool', 'true'),
      field('ai_run_once_daily', 'AI run once daily', 'bool', 'true'),
    ],
  },
  {
    category: 'Risk Settings',
    fields: [
      field('risk.default_profile', 'Risk profile', 'string', 'moderate', { options: ['moderate'] }),
      field('risk.max_account_deployment_pct', 'Max account deployment pct', 'float', '0.90'),
      field('risk.max_per_trade_pct', 'Max risk per trade pct', 'float', '0.02'),
      field('risk.default_per_trade_pct', 'Default risk per trade pct', 'float', '0.0125'),
      field('risk.long_only_until_equity', 'Long-only until equity', 'float', '2500'),
      field('risk.stock.fee_pct', 'Stock fee pct', 'float', '0.0005'),
      field('risk.crypto.fee_pct', 'Crypto fee pct', 'float', '0.0013'),
      field('risk.stock.slippage_pct', 'Stock slippage pct', 'float', '0.0005'),
      field('risk.crypto.slippage_pct', 'Crypto slippage pct', 'float', '0.0015'),
    ],
  },
  {
    category: 'Circuit Breakers',
    fields: [
      field('risk.stock.soft_stop_pct', 'Stock soft stop pct', 'float', '-0.035', { dangerous: true }),
      field('risk.stock.hard_stop_pct', 'Stock hard stop pct', 'float', '-0.055', { dangerous: true }),
      field('risk.crypto.soft_stop_pct', 'Crypto soft stop pct', 'float', '-0.040', { dangerous: true }),
      field('risk.crypto.hard_stop_pct', 'Crypto hard stop pct', 'float', '-0.065', { dangerous: true }),
      field('risk.total_account.hard_stop_pct', 'Total account hard stop pct', 'float', '-0.075', { dangerous: true }),
    ],
  },
  {
    category: 'Stop Settings',
    fields: [
      field('stops.stock.style', 'Stock stop style', 'string', 'fixed', { options: ['fixed', 'trailing', 'step'] }),
      field('stops.crypto.style', 'Crypto stop style', 'string', 'trailing', { options: ['fixed', 'trailing', 'step'] }),
      field('stops.stock.fallback_stop_pct', 'Stock fallback stop pct', 'float', '0.01'),
      field('stops.crypto.fallback_stop_pct', 'Crypto fallback stop pct', 'float', '0.015'),
      field('stops.stock.trailing_activation_pct', 'Stock trailing activation pct', 'float', '0.01'),
      field('stops.stock.trailing_offset_pct', 'Stock trailing offset pct', 'float', '0.0075'),
      field('stops.crypto.trailing_activation_pct', 'Crypto trailing activation pct', 'float', '0.015'),
      field('stops.crypto.trailing_offset_pct', 'Crypto trailing offset pct', 'float', '0.01'),
      field('stops.stock.step_trigger_pct', 'Stock step trigger pct', 'float', '0.02'),
      field('stops.stock.step_increment_pct', 'Stock step increment pct', 'float', '0.01'),
      field('stops.crypto.step_trigger_pct', 'Crypto step trigger pct', 'float', '0.025'),
      field('stops.crypto.step_increment_pct', 'Crypto step increment pct', 'float', '0.0125'),
    ],
  },
  {
    category: 'Strategy Toggles',
    fields: [
      field('strategy_enabled.stock.trend_pullback_long', 'Stock · Trend Pullback Long', 'bool', 'true'),
      field('strategy_enabled.stock.vwap_reclaim_long', 'Stock · VWAP Reclaim Long', 'bool', 'true'),
      field('strategy_enabled.stock.opening_range_breakout_long', 'Stock · Opening Range Breakout Long', 'bool', 'true'),
      field('strategy_enabled.crypto.trend_continuation_long', 'Crypto · Trend Continuation Long', 'bool', 'true'),
      field('strategy_enabled.crypto.vwap_reclaim_long', 'Crypto · VWAP Reclaim Long', 'bool', 'true'),
      field('strategy_enabled.crypto.breakout_long', 'Crypto · Breakout Long', 'bool', 'true'),
      field('strategy_enabled.crypto.bbrsi_mean_reversion_long', 'Crypto · BBRSI Mean Reversion Long', 'bool', 'true'),
    ],
  },
]

function field(key, label, valueType, defaultValue, options = {}) {
  return {
    key,
    label,
    valueType,
    defaultValue,
    dangerous: Boolean(options.dangerous),
    options: options.options ?? null,
  }
}

function App() {
  const [page, setPage] = useHashPage('dashboard')
  const [refreshSeconds, setRefreshSeconds] = useState(20)
  const [drawer, setDrawer] = useState(null)
  const [actionState, setActionState] = useState({ status: 'idle', message: '' })
  const [settingsFilter, setSettingsFilter] = useState('')
  const [settingsCategory, setSettingsCategory] = useState('All categories')
  const [draftSettings, setDraftSettings] = useState({})
  const [settingsSaveBusy, setSettingsSaveBusy] = useState(false)
  const { data, loading, refreshing, error, refresh } = useControlCenterData(refreshSeconds)

  useEffect(() => {
    setDraftSettings({})
  }, [data.settingsList])

  const derived = useMemo(() => deriveState(data), [data])
  const settingsGroups = useMemo(
    () => buildSettingsGroups(data, draftSettings, settingsFilter, settingsCategory),
    [data, draftSettings, settingsFilter, settingsCategory],
  )

  async function runAction(label, path, body = {}) {
    setActionState({ status: 'busy', message: `${label} in flight…` })
    try {
      const payload = await requestJson(`${apiBaseUrl}${apiPrefix}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      setActionState({ status: 'success', message: payload.message ?? `${label} completed.` })
      await refresh({ silent: false })
    } catch (caughtError) {
      setActionState({ status: 'error', message: caughtError.message })
    }
  }

  async function saveSettings() {
    const changedEntries = Object.entries(draftSettings).filter(([, item]) => item.changed)
    if (changedEntries.length === 0) {
      setActionState({ status: 'idle', message: 'No staged settings changes.' })
      return
    }

    setSettingsSaveBusy(true)
    setActionState({ status: 'busy', message: 'Saving staged settings…' })
    try {
      await requestJson(`${apiBaseUrl}${apiPrefix}/settings/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: changedEntries.map(([key, item]) => ({
            key,
            value: item.value,
            value_type: item.valueType,
            description: item.description,
            is_secret: false,
          })),
        }),
      })
      setDraftSettings({})
      setActionState({ status: 'success', message: `Saved ${changedEntries.length} setting changes.` })
      await refresh({ silent: false })
    } catch (caughtError) {
      setActionState({ status: 'error', message: caughtError.message })
    } finally {
      setSettingsSaveBusy(false)
    }
  }

  function updateDraft(fieldConfig, nextValue) {
    const current = settingValueForKey(data, fieldConfig.key, fieldConfig.defaultValue)
    setDraftSettings((previous) => ({
      ...previous,
      [fieldConfig.key]: {
        value: nextValue,
        valueType: fieldConfig.valueType,
        description: fieldConfig.label,
        changed: String(nextValue) !== String(current),
      },
    }))
  }

  function restoreDefault(fieldConfig) {
    updateDraft(fieldConfig, fieldConfig.defaultValue)
  }

  const pageProps = {
    data,
    derived,
    loading,
    refreshing,
    openDrawer: setDrawer,
    runAction,
    goToPage: setPage,
    refreshNow: refresh,
  }

  return (
    <div className="shell">
      <Sidebar
        currentPage={page}
        derived={derived}
        onSelectPage={setPage}
      />

      <main className="main-column">
        <TopBar
          currentPage={page}
          onSelectPage={setPage}
          refreshSeconds={refreshSeconds}
          onRefreshSeconds={setRefreshSeconds}
          onRefresh={refresh}
          refreshing={refreshing}
          actionState={actionState}
          lastUpdatedAt={derived.lastUpdatedAt}
        />

        {derived.banner && (
          <section className={`alert-strip ${derived.banner.tone}`}>
            <div>
              <strong>{derived.banner.title}</strong>
              <span>{derived.banner.message}</span>
            </div>
            <button className="ghost-button" onClick={() => setPage(derived.banner.page ?? 'activity')}>
              Inspect
            </button>
          </section>
        )}

        {error && (
          <section className="alert-strip error">
            <div>
              <strong>Data stream hiccup</strong>
              <span>{error}</span>
            </div>
          </section>
        )}

        <div className="page-stage">
          {page === 'dashboard' && <DashboardPage {...pageProps} />}
          {page === 'performance' && <PerformancePage {...pageProps} />}
          {page === 'universe' && <UniversePage {...pageProps} />}
          {page === 'strategies' && <StrategiesPage {...pageProps} />}
          {page === 'positions' && <PositionsPage {...pageProps} />}
          {page === 'activity' && <ActivityPage {...pageProps} />}
          {page === 'settings' && (
            <SettingsPage
              {...pageProps}
              settingsGroups={settingsGroups}
              settingsFilter={settingsFilter}
              onSettingsFilter={setSettingsFilter}
              settingsCategory={settingsCategory}
              onSettingsCategory={setSettingsCategory}
              updateDraft={updateDraft}
              restoreDefault={restoreDefault}
              onSaveSettings={saveSettings}
              settingsSaveBusy={settingsSaveBusy}
            />
          )}
          {page === 'data' && <DataPage {...pageProps} />}
        </div>
      </main>

      <Drawer drawer={drawer} onClose={() => setDrawer(null)} />
    </div>
  )
}

function useHashPage(defaultPage) {
  const [page, setPage] = useState(() => readPageHash(defaultPage))

  useEffect(() => {
    function handleHashChange() {
      setPage(readPageHash(defaultPage))
    }
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [defaultPage])

  function updatePage(nextPage) {
    window.location.hash = nextPage
    setPage(nextPage)
  }

  return [page, updatePage]
}

function readPageHash(defaultPage) {
  const raw = window.location.hash.replace('#', '').trim()
  const validPages = new Set([...sidebarPages, ...topUtilityPages].map((item) => item.key))
  return validPages.has(raw) ? raw : defaultPage
}

function useControlCenterData(refreshSeconds) {
  const [data, setData] = useState(createEmptyData())
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)

  async function refresh(options = { silent: false }) {
    if (options.silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
      setRefreshing(true)
    }
    try {
      const nextData = await fetchDashboardState()
      setData(nextData)
      setError('')
    } catch (caughtError) {
      setError(caughtError.message)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    refresh({ silent: false })
  }, [nonce])

  useEffect(() => {
    if (!refreshSeconds) {
      return undefined
    }
    const timer = window.setInterval(() => {
      refresh({ silent: true })
    }, refreshSeconds * 1000)
    return () => window.clearInterval(timer)
  }, [refreshSeconds])

  return {
    data,
    loading,
    refreshing,
    error,
    refresh: async ({ silent = false } = {}) => {
      await refresh({ silent })
      setNonce((value) => value)
    },
  }
}

async function fetchDashboardState() {
  const [
    health,
    runtimeSettings,
    controlSnapshot,
    settingsList,
    totalAccount,
    stockAccount,
    cryptoAccount,
    stockUniverse,
    cryptoUniverse,
    stockUniverseRun,
    cryptoUniverseRun,
    stockStrategies,
    cryptoStrategies,
    stockStrategySync,
    cryptoStrategySync,
    stockRegime,
    cryptoRegime,
    stockRegimeSync,
    cryptoRegimeSync,
    stockRisk,
    cryptoRisk,
    stockRiskSync,
    cryptoRiskSync,
    stockPositions,
    cryptoPositions,
    stockOpenOrders,
    cryptoOpenOrders,
    stockMismatches,
    cryptoMismatches,
    stockPositionSync,
    cryptoPositionSync,
    stockStops,
    cryptoStops,
    stockStopSync,
    cryptoStopSync,
    events,
    stockCandleSync,
    cryptoCandleSync,
    stockFreshness,
    cryptoFreshness,
    stockFeatureSync,
    cryptoFeatureSync,
  ] = await Promise.all([
    requestJson(`${apiBaseUrl}/health`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/settings/runtime/snapshot`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/controls/snapshot`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/settings`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/account-snapshots/latest/total`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/account-snapshots/latest/stock`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/account-snapshots/latest/crypto`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/universe/stock/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/universe/crypto/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/universe/stock/run`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/universe/crypto/run`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/strategy/stock/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/strategy/crypto/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/strategy/stock/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/strategy/crypto/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/regime/stock/current`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/regime/crypto/current`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/regime/stock/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/regime/crypto/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/risk/stock/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/risk/crypto/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/risk/stock/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/risk/crypto/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/stock/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/crypto/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/stock/open-orders`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/crypto/open-orders`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/stock/mismatches`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/crypto/mismatches`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/stock/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/positions/crypto/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/stops/stock/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/stops/crypto/current`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/stops/stock/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/stops/crypto/sync-state`, { fallback: null }),
    requestJson(`${apiBaseUrl}${apiPrefix}/system-events?limit=120`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/data/candles/stock/sync-state`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/data/candles/crypto/sync-state`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/data/candles/stock/freshness`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/data/candles/crypto/freshness`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/data/features/stock/sync-state`, { fallback: [] }),
    requestJson(`${apiBaseUrl}${apiPrefix}/data/features/crypto/sync-state`, { fallback: [] }),
  ])

  return {
    health,
    runtimeSettings,
    controlSnapshot,
    settingsList,
    accounts: { total: totalAccount, stock: stockAccount, crypto: cryptoAccount },
    universe: {
      stockRows: stockUniverse,
      cryptoRows: cryptoUniverse,
      stockRun: stockUniverseRun,
      cryptoRun: cryptoUniverseRun,
    },
    strategies: {
      stockRows: stockStrategies,
      cryptoRows: cryptoStrategies,
      stockSync: stockStrategySync,
      cryptoSync: cryptoStrategySync,
    },
    regime: {
      stock: stockRegime,
      crypto: cryptoRegime,
      stockSync: stockRegimeSync,
      cryptoSync: cryptoRegimeSync,
    },
    risk: {
      stockRows: stockRisk,
      cryptoRows: cryptoRisk,
      stockSync: stockRiskSync,
      cryptoSync: cryptoRiskSync,
    },
    positions: {
      stockRows: stockPositions,
      cryptoRows: cryptoPositions,
      stockOpenOrders,
      cryptoOpenOrders,
      stockMismatches,
      cryptoMismatches,
      stockSync: stockPositionSync,
      cryptoSync: cryptoPositionSync,
    },
    stops: {
      stockRows: stockStops,
      cryptoRows: cryptoStops,
      stockSync: stockStopSync,
      cryptoSync: cryptoStopSync,
    },
    activity: { events },
    data: {
      stockCandleSync,
      cryptoCandleSync,
      stockFreshness,
      cryptoFreshness,
      stockFeatureSync,
      cryptoFeatureSync,
    },
  }
}

function createEmptyData() {
  return {
    health: null,
    runtimeSettings: null,
    controlSnapshot: null,
    settingsList: [],
    accounts: { total: null, stock: null, crypto: null },
    universe: { stockRows: [], cryptoRows: [], stockRun: null, cryptoRun: null },
    strategies: { stockRows: [], cryptoRows: [], stockSync: null, cryptoSync: null },
    regime: { stock: null, crypto: null, stockSync: null, cryptoSync: null },
    risk: { stockRows: [], cryptoRows: [], stockSync: null, cryptoSync: null },
    positions: {
      stockRows: [],
      cryptoRows: [],
      stockOpenOrders: [],
      cryptoOpenOrders: [],
      stockMismatches: [],
      cryptoMismatches: [],
      stockSync: null,
      cryptoSync: null,
    },
    stops: { stockRows: [], cryptoRows: [], stockSync: null, cryptoSync: null },
    activity: { events: [] },
    data: {
      stockCandleSync: [],
      cryptoCandleSync: [],
      stockFreshness: [],
      cryptoFreshness: [],
      stockFeatureSync: [],
      cryptoFeatureSync: [],
    },
  }
}

async function requestJson(url, options = {}) {
  const { fallback, ...fetchOptions } = options
  const response = await fetch(url, fetchOptions)
  if (response.status === 404 && fallback !== undefined) {
    return fallback
  }
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed with status ${response.status}`)
  }
  return response.json()
}

function Sidebar({ currentPage, derived, onSelectPage }) {
  const modeLabel = derived.modeLabel
  return (
    <aside className="sidebar">
      <div className="brand-panel">
        <div className="brand-mark">A</div>
        <div>
          <p className="kicker">Trade Bot</p>
          <h1>Aetherium</h1>
        </div>
      </div>

      <div className="status-panel">
        <div className={`status-dot ${derived.systemTone}`} />
        <div>
          <p className="status-caption">Bot Status</p>
          <strong>{derived.systemLabel}</strong>
          <p className="status-meta">{modeLabel}</p>
          <p className="status-meta">Last sync {formatRelativeTime(derived.lastUpdatedAt)}</p>
        </div>
      </div>

      <nav className="nav-list">
        {sidebarPages.map((item) => (
          <button
            key={item.key}
            className={`nav-button ${currentPage === item.key ? 'active' : ''}`}
            onClick={() => onSelectPage(item.key)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  )
}

function TopBar({
  currentPage,
  onSelectPage,
  refreshSeconds,
  onRefreshSeconds,
  onRefresh,
  refreshing,
  actionState,
  lastUpdatedAt,
}) {
  return (
    <header className="topbar">
      <div>
        <p className="kicker">Phase 14 settings deck</p>
        <h2>{humanizePage(currentPage)}</h2>
      </div>

      <div className="topbar-controls">
        {topUtilityPages.map((item) => (
          <button
            key={item.key}
            className={`ghost-button ${currentPage === item.key ? 'active' : ''}`}
            onClick={() => onSelectPage(item.key)}
          >
            {item.label}
          </button>
        ))}

        <label className="refresh-picker">
          <span>Auto</span>
          <select value={refreshSeconds} onChange={(event) => onRefreshSeconds(Number(event.target.value))}>
            {refreshOptions.map((item) => (
              <option key={item} value={item}>
                {item === 0 ? 'Off' : `${item}s`}
              </option>
            ))}
          </select>
        </label>

        <button className="primary-button" onClick={() => onRefresh({ silent: false })}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className="topbar-footnote">
        <StatusPill tone={toneFromAction(actionState.status)}>{actionState.message || `Updated ${formatRelativeTime(lastUpdatedAt)}`}</StatusPill>
      </div>
    </header>
  )
}

function DashboardPage({ derived, data, openDrawer, runAction, goToPage }) {
  const total = data.accounts.total
  const stock = data.accounts.stock
  const crypto = data.accounts.crypto
  const criticalEvents = data.activity.events.filter((event) => ['critical', 'error', 'warning'].includes((event.severity ?? '').toLowerCase()))

  return (
    <div className="page-grid dashboard-grid">
      <Panel title="Mission control" subtitle="What is happening right now?" className="hero-panel wide clickable" onClick={() => goToPage('performance')}>
        <div className="hero-metrics">
          <MetricCard label="Total net equity" value={formatCurrency(total?.equity)} tone="neutral" />
          <MetricCard label="Total P/L" value={formatSignedCurrency(derived.totalPnl)} tone={toneFromValue(derived.totalPnl)} />
          <MetricCard label="Return" value={formatPercent(derived.totalReturnPct)} tone={toneFromValue(derived.totalReturnPct)} />
          <MetricCard label="Mode" value={derived.modeLabel} tone={derived.modeTone} />
        </div>
        <div className="progress-cluster">
          <ProgressStat label="Stocks share" value={derived.stockWeightPct} />
          <ProgressStat label="Crypto share" value={derived.cryptoWeightPct} tone="secondary" />
          <ProgressStat label="Capital deployed" value={derived.deploymentPct} tone="warning" />
        </div>
        <ActionRow
          actions={[
            { label: 'Refresh', onClick: () => window.location.reload() },
            { label: 'Sync candles', onClick: () => goToPage('data'), variant: 'ghost' },
            { label: 'View positions', onClick: () => goToPage('positions'), variant: 'ghost' },
          ]}
        />
      </Panel>

      <Panel title="Equities division" subtitle="Cash, exposure, and stock state" tone="stock">
        <MetricCard label="Stock equity" value={formatCurrency(stock?.equity)} tone="stock" />
        <MetricCard label="Cash available" value={formatCurrency(stock?.cash)} tone="neutral" />
        <MetricCard label="Stock P/L" value={formatSignedCurrency(derived.stockPnl)} tone={toneFromValue(derived.stockPnl)} />
        <MetricCard label="Open stock positions" value={String(data.positions.stockRows.length)} tone="neutral" />
        <ActionRow
          actions={[
            { label: 'Stock positions', onClick: () => goToPage('positions'), variant: 'ghost' },
            { label: 'Flatten stocks', onClick: () => runAction('Flatten stocks', '/controls/flatten/stocks', { engage_kill_switch: true }), variant: 'danger' },
          ]}
        />
      </Panel>

      <Panel title="Digital assets division" subtitle="Crypto equity and venue readiness" tone="crypto">
        <MetricCard label="Crypto equity" value={formatCurrency(crypto?.equity)} tone="crypto" />
        <MetricCard label="Buying power" value={formatCurrency(crypto?.buying_power ?? crypto?.cash)} tone="neutral" />
        <MetricCard label="Crypto P/L" value={formatSignedCurrency(derived.cryptoPnl)} tone={toneFromValue(derived.cryptoPnl)} />
        <MetricCard label="Open crypto positions" value={String(data.positions.cryptoRows.length)} tone="neutral" />
        <ActionRow
          actions={[
            { label: 'Crypto positions', onClick: () => goToPage('positions'), variant: 'ghost' },
            { label: 'Flatten crypto', onClick: () => runAction('Flatten crypto', '/controls/flatten/crypto', { engage_kill_switch: true }), variant: 'danger' },
          ]}
        />
      </Panel>

      <Panel title="Stock leaderboard" subtitle="Best current stock candidates" tone="stock">
        <DataTable
          columns={[
            { key: 'rank', label: '#' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'metric', label: 'Metric' },
          ]}
          rows={derived.stockLeaderboard.map((item, index) => ({
            rank: index + 1,
            symbol: item.symbol,
            metric: item.metricLabel,
            raw: item,
          }))}
          emptyLabel="No stock leaderboard data yet."
          onRowClick={(row) => openDrawer({ title: row.symbol, data: row.raw })}
        />
      </Panel>

      <Panel title="Active positions" subtitle="Live position strip" className="wide">
        <DataTable
          columns={[
            { key: 'symbol', label: 'Symbol' },
            { key: 'side', label: 'Side' },
            { key: 'quantity', label: 'Size' },
            { key: 'entry', label: 'Entry' },
            { key: 'current', label: 'Current' },
            { key: 'upl', label: 'Unrealized P/L' },
          ]}
          rows={derived.activePositions.map((row) => ({
            symbol: row.symbol,
            side: row.side,
            quantity: formatNumber(row.quantity),
            entry: formatCurrency(row.average_entry_price),
            current: formatCurrency(row.current_price),
            upl: formatSignedCurrency(row.unrealized_pnl),
            raw: row,
          }))}
          emptyLabel="No active positions in broker truth right now."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} position`, data: row.raw })}
        />
      </Panel>

      <Panel title="Crypto leaderboard" subtitle="Best current crypto candidates" tone="crypto">
        <DataTable
          columns={[
            { key: 'rank', label: '#' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'metric', label: 'Metric' },
          ]}
          rows={derived.cryptoLeaderboard.map((item, index) => ({
            rank: index + 1,
            symbol: item.symbol,
            metric: item.metricLabel,
            raw: item,
          }))}
          emptyLabel="No crypto leaderboard data yet."
          onRowClick={(row) => openDrawer({ title: row.symbol, data: row.raw })}
        />
      </Panel>

      <Panel title="Operator alerts" subtitle="Recent warnings, mismatches, and system noise" className="wide">
        <AlertList items={criticalEvents.slice(0, 6)} onClickItem={(item) => openDrawer({ title: item.event_type, data: item })} />
      </Panel>
    </div>
  )
}

function PerformancePage({ derived, data, openDrawer }) {
  const stockContribution = buildContributionRows(data.positions.stockRows)
  const cryptoContribution = buildContributionRows(data.positions.cryptoRows)

  return (
    <div className="page-grid performance-grid">
      <Panel title="Portfolio scoreboard" subtitle="Quality of returns, without inventing fairy dust" className="hero-panel wide">
        <div className="hero-metrics four-up">
          <MetricCard label="Net P/L" value={formatSignedCurrency(derived.totalPnl)} tone={toneFromValue(derived.totalPnl)} />
          <MetricCard label="Return" value={formatPercent(derived.totalReturnPct)} tone={toneFromValue(derived.totalReturnPct)} />
          <MetricCard label="Realized P/L" value={formatSignedCurrency(derived.realizedPnl)} tone={toneFromValue(derived.realizedPnl)} />
          <MetricCard label="Unrealized P/L" value={formatSignedCurrency(derived.unrealizedPnl)} tone={toneFromValue(derived.unrealizedPnl)} />
        </div>
        <div className="hero-metrics five-up">
          <MetricCard label="Sharpe" value={fallbackMetric('n/a')} caption="Needs historical snapshot depth." />
          <MetricCard label="Sortino" value={fallbackMetric('n/a')} caption="Needs downside series." />
          <MetricCard label="Max drawdown" value={fallbackMetric('n/a')} caption="Needs running equity history." />
          <MetricCard label="Win rate" value={fallbackMetric('n/a')} caption="Awaiting closed-trade archive." />
          <MetricCard label="Exposure-adjusted return" value={formatPercent(derived.exposureAdjustedReturnPct)} tone={toneFromValue(derived.exposureAdjustedReturnPct)} />
        </div>
      </Panel>

      <Panel title="Equities attribution" subtitle="What stock positions are doing right now" tone="stock">
        <MetricCard label="Stock P/L" value={formatSignedCurrency(derived.stockPnl)} tone={toneFromValue(derived.stockPnl)} />
        <MetricCard label="Stock exposure" value={formatCurrency(derived.stockExposure)} />
        <MetricCard label="Stock mismatches" value={String(data.positions.stockMismatches.length)} tone={data.positions.stockMismatches.length ? 'warning' : 'positive'} />
        <ContributionList items={stockContribution} onClickItem={(item) => openDrawer({ title: item.symbol, data: item.raw })} />
      </Panel>

      <Panel title="Digital assets attribution" subtitle="What crypto positions are doing right now" tone="crypto">
        <MetricCard label="Crypto P/L" value={formatSignedCurrency(derived.cryptoPnl)} tone={toneFromValue(derived.cryptoPnl)} />
        <MetricCard label="Crypto exposure" value={formatCurrency(derived.cryptoExposure)} />
        <MetricCard label="Crypto mismatches" value={String(data.positions.cryptoMismatches.length)} tone={data.positions.cryptoMismatches.length ? 'warning' : 'positive'} />
        <ContributionList items={cryptoContribution} onClickItem={(item) => openDrawer({ title: item.symbol, data: item.raw })} />
      </Panel>

      <Panel title="Stock performance board" subtitle="Open positions driving stock P/L" tone="stock">
        <DataTable
          columns={[
            { key: 'rank', label: '#' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'pnl', label: 'P/L' },
          ]}
          rows={stockContribution.map((item, index) => ({ rank: index + 1, symbol: item.symbol, pnl: formatSignedCurrency(item.value), raw: item.raw }))}
          emptyLabel="No open stock positions yet."
          onRowClick={(row) => openDrawer({ title: row.symbol, data: row.raw })}
        />
      </Panel>

      <Panel title="Active positions strip" subtitle="These are still moving the board" className="wide">
        <DataTable
          columns={[
            { key: 'symbol', label: 'Symbol' },
            { key: 'status', label: 'Status' },
            { key: 'marketValue', label: 'Market value' },
            { key: 'unrealized', label: 'Unrealized P/L' },
          ]}
          rows={derived.activePositions.map((row) => ({
            symbol: row.symbol,
            status: row.status,
            marketValue: formatCurrency(row.market_value),
            unrealized: formatSignedCurrency(row.unrealized_pnl),
            raw: row,
          }))}
          emptyLabel="No active positions right now."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} performance detail`, data: row.raw })}
        />
      </Panel>

      <Panel title="Crypto performance board" subtitle="Open positions driving crypto P/L" tone="crypto">
        <DataTable
          columns={[
            { key: 'rank', label: '#' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'pnl', label: 'P/L' },
          ]}
          rows={cryptoContribution.map((item, index) => ({ rank: index + 1, symbol: item.symbol, pnl: formatSignedCurrency(item.value), raw: item.raw }))}
          emptyLabel="No open crypto positions yet."
          onRowClick={(row) => openDrawer({ title: row.symbol, data: row.raw })}
        />
      </Panel>
    </div>
  )
}

function UniversePage({ data, derived, openDrawer, runAction }) {
  return (
    <div className="page-grid universe-grid">
      <Panel title="Stock universe" subtitle="What can trade on the stock side" tone="stock" className="wide">
        <ActionRow
          actions={[
            { label: 'Refresh universe', onClick: () => runAction('Refresh universe', '/controls/universe/run-once', { asset_class: 'stock' }) },
            { label: 'Run AI universe', onClick: () => runAction('Run AI universe', '/controls/universe/run-once', { asset_class: 'stock', force: true }), variant: 'ghost' },
          ]}
        />
        <DataTable
          columns={[
            { key: 'rank', label: 'Rank' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'source', label: 'Source' },
            { key: 'status', label: 'Eligibility' },
            { key: 'reason', label: 'Reason' },
          ]}
          rows={data.universe.stockRows.map((row) => ({
            rank: row.rank,
            symbol: row.symbol,
            source: row.source,
            status: 'Eligible',
            reason: row.selection_reason || summarizePayload(row.payload),
            raw: row,
          }))}
          emptyLabel="Stock universe not resolved yet."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} universe detail`, data: row.raw })}
        />
      </Panel>

      <Panel title="Summary core" subtitle="Continuity card kept intentionally boring" className="hero-panel">
        <MetricCard label="Total net equity" value={formatCurrency(data.accounts.total?.equity)} tone="neutral" />
        <MetricCard label="Total P/L" value={formatSignedCurrency(derived.totalPnl)} tone={toneFromValue(derived.totalPnl)} />
        <MetricCard label="Stock rows" value={String(data.universe.stockRows.length)} tone="stock" />
        <MetricCard label="Crypto rows" value={String(data.universe.cryptoRows.length)} tone="crypto" />
        <MetricCard label="Stock source" value={data.universe.stockRun?.source ?? 'n/a'} tone="stock" />
        <MetricCard label="Crypto source" value={data.universe.cryptoRun?.source ?? 'n/a'} tone="crypto" />
      </Panel>

      <Panel title="Crypto universe" subtitle="What can trade on the crypto side" tone="crypto" className="wide">
        <ActionRow
          actions={[
            { label: 'Refresh universe', onClick: () => runAction('Refresh crypto universe', '/controls/universe/run-once', { asset_class: 'crypto' }) },
            { label: 'Static refresh', onClick: () => runAction('Refresh all universe', '/controls/universe/run-once', { asset_class: 'all', force: true }), variant: 'ghost' },
          ]}
        />
        <DataTable
          columns={[
            { key: 'rank', label: 'Rank' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'source', label: 'Source' },
            { key: 'status', label: 'Eligibility' },
            { key: 'reason', label: 'Reason' },
          ]}
          rows={data.universe.cryptoRows.map((row) => ({
            rank: row.rank,
            symbol: row.symbol,
            source: row.source,
            status: 'Eligible',
            reason: row.selection_reason || summarizePayload(row.payload),
            raw: row,
          }))}
          emptyLabel="Crypto universe not resolved yet."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} universe detail`, data: row.raw })}
        />
      </Panel>

      <Panel title="Stock leaderboard" subtitle="Top stock ranks from current universe" tone="stock">
        <Leaderboard items={derived.stockLeaderboard} onClickItem={(item) => openDrawer({ title: item.symbol, data: item.raw })} />
      </Panel>

      <Panel title="Active positions strip" subtitle="Symbols already in the air" className="wide">
        <CompactPositionList items={derived.activePositions} onClickItem={(item) => openDrawer({ title: `${item.symbol} position`, data: item })} />
      </Panel>

      <Panel title="Crypto leaderboard" subtitle="Top crypto ranks from current universe" tone="crypto">
        <Leaderboard items={derived.cryptoLeaderboard} onClickItem={(item) => openDrawer({ title: item.symbol, data: item.raw })} />
      </Panel>
    </div>
  )
}

function StrategiesPage({ data, derived, openDrawer, runAction }) {
  return (
    <div className="page-grid strategies-grid">
      <Panel title="Stock strategies" subtitle="What stock setups are close to firing" tone="stock" className="wide">
        <ActionRow
          actions={[
            { label: 'Refresh strategies', onClick: () => runAction('Refresh strategies', '/controls/strategy/run-once', { asset_class: 'stock' }) },
            { label: 'Recompute regime', onClick: () => runAction('Recompute regime', '/controls/regime/run-once', { asset_class: 'stock' }), variant: 'ghost' },
          ]}
        />
        <StrategyTable rows={data.strategies.stockRows} onRowClick={(row) => openDrawer({ title: `${row.symbol} strategy detail`, data: row })} />
      </Panel>

      <Panel title="Summary core" subtitle="Regime and readiness overview" className="hero-panel">
        <MetricCard label="Stock regime" value={data.regime.stock?.regime ?? 'n/a'} tone="stock" />
        <MetricCard label="Crypto regime" value={data.regime.crypto?.regime ?? 'n/a'} tone="crypto" />
        <MetricCard label="Ready rows" value={String(derived.readyStrategyCount)} tone="positive" />
        <MetricCard label="Blocked rows" value={String(derived.blockedStrategyCount)} tone="warning" />
      </Panel>

      <Panel title="Crypto strategies" subtitle="What crypto setups are close to firing" tone="crypto" className="wide">
        <ActionRow
          actions={[
            { label: 'Refresh strategies', onClick: () => runAction('Refresh strategies', '/controls/strategy/run-once', { asset_class: 'crypto' }) },
            { label: 'Recompute regime', onClick: () => runAction('Recompute regime', '/controls/regime/run-once', { asset_class: 'crypto' }), variant: 'ghost' },
          ]}
        />
        <StrategyTable rows={data.strategies.cryptoRows} onRowClick={(row) => openDrawer({ title: `${row.symbol} strategy detail`, data: row })} />
      </Panel>

      <Panel title="Stock rank board" subtitle="Best current stock setups" tone="stock">
        <Leaderboard items={derived.stockLeaderboard} onClickItem={(item) => openDrawer({ title: item.symbol, data: item.raw })} />
      </Panel>

      <Panel title="Active positions strip" subtitle="Useful context when a symbol is already occupied" className="wide">
        <CompactPositionList items={derived.activePositions} onClickItem={(item) => openDrawer({ title: `${item.symbol} position`, data: item })} />
      </Panel>

      <Panel title="Crypto rank board" subtitle="Best current crypto setups" tone="crypto">
        <Leaderboard items={derived.cryptoLeaderboard} onClickItem={(item) => openDrawer({ title: item.symbol, data: item.raw })} />
      </Panel>
    </div>
  )
}

function PositionsPage({ data, derived, openDrawer, runAction }) {
  const allRows = [...data.positions.stockRows, ...data.positions.cryptoRows]
  return (
    <div className="page-grid positions-grid">
      <Panel title="Position summary" subtitle="Broker truth, internal truth, and where they argue" className="hero-panel wide">
        <div className="hero-metrics four-up">
          <MetricCard label="Open positions" value={String(allRows.length)} />
          <MetricCard label="Realized P/L" value={formatSignedCurrency(derived.realizedPnl)} tone={toneFromValue(derived.realizedPnl)} />
          <MetricCard label="Unrealized P/L" value={formatSignedCurrency(derived.unrealizedPnl)} tone={toneFromValue(derived.unrealizedPnl)} />
          <MetricCard label="Reconciliation mismatches" value={String(derived.totalMismatchCount)} tone={derived.totalMismatchCount ? 'warning' : 'positive'} />
        </div>
        <ActionRow
          actions={[
            { label: 'Flatten stocks', onClick: () => runAction('Flatten stocks', '/controls/flatten/stocks', { engage_kill_switch: true }), variant: 'danger' },
            { label: 'Flatten crypto', onClick: () => runAction('Flatten crypto', '/controls/flatten/crypto', { engage_kill_switch: true }), variant: 'danger' },
            { label: 'Flatten all', onClick: () => runAction('Flatten all', '/controls/flatten/all', { engage_kill_switch: true }), variant: 'danger' },
          ]}
        />
      </Panel>

      <Panel title="Positions table" subtitle="The hangar bay" className="wide tall">
        <DataTable
          columns={[
            { key: 'symbol', label: 'Symbol' },
            { key: 'asset', label: 'Asset' },
            { key: 'mode', label: 'Mode' },
            { key: 'qty', label: 'Qty' },
            { key: 'entry', label: 'Avg entry' },
            { key: 'last', label: 'Last' },
            { key: 'market', label: 'Market value' },
            { key: 'upl', label: 'UPL' },
            { key: 'status', label: 'Status' },
            { key: 'sync', label: 'Sync' },
          ]}
          rows={allRows.map((row) => ({
            symbol: row.symbol,
            asset: row.asset_class,
            mode: row.mode,
            qty: formatNumber(row.quantity),
            entry: formatCurrency(row.average_entry_price),
            last: formatCurrency(row.current_price),
            market: formatCurrency(row.market_value),
            upl: formatSignedCurrency(row.unrealized_pnl),
            status: row.status,
            sync: row.reconciliation_status,
            raw: row,
          }))}
          emptyLabel="No reconciled positions yet."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} position detail`, data: row.raw })}
        />
      </Panel>

      <Panel title="Open orders" subtitle="Still waiting in the queue" className="wide">
        <DataTable
          columns={[
            { key: 'symbol', label: 'Symbol' },
            { key: 'side', label: 'Side' },
            { key: 'type', label: 'Type' },
            { key: 'qty', label: 'Qty' },
            { key: 'status', label: 'Status' },
            { key: 'sync', label: 'Sync' },
          ]}
          rows={[...data.positions.stockOpenOrders, ...data.positions.cryptoOpenOrders].map((row) => ({
            symbol: row.symbol,
            side: row.side,
            type: row.order_type,
            qty: formatNumber(row.quantity ?? row.notional_value),
            status: row.status,
            sync: row.reconciliation_status,
            raw: row,
          }))}
          emptyLabel="No open orders waiting around."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} order detail`, data: row.raw })}
        />
      </Panel>

      <Panel title="Mismatch queue" subtitle="Where internal and broker state disagree" className="wide">
        <DataTable
          columns={[
            { key: 'asset', label: 'Asset' },
            { key: 'symbol', label: 'Symbol' },
            { key: 'type', label: 'Type' },
            { key: 'severity', label: 'Severity' },
            { key: 'message', label: 'Message' },
          ]}
          rows={[...data.positions.stockMismatches, ...data.positions.cryptoMismatches].map((row) => ({
            asset: row.asset_class,
            symbol: row.symbol ?? 'n/a',
            type: row.mismatch_type,
            severity: row.severity,
            message: row.message,
            raw: row,
          }))}
          emptyLabel="No active mismatches. The ledgers are behaving."
          onRowClick={(row) => openDrawer({ title: `${row.symbol} mismatch`, data: row.raw })}
        />
      </Panel>
    </div>
  )
}

function ActivityPage({ data, openDrawer }) {
  return (
    <div className="page-grid activity-grid">
      <Panel title="Logs / activity" subtitle="The flight recorder" className="wide tall">
        <DataTable
          columns={[
            { key: 'time', label: 'Timestamp' },
            { key: 'severity', label: 'Level' },
            { key: 'source', label: 'Component' },
            { key: 'type', label: 'Action' },
            { key: 'message', label: 'Message' },
          ]}
          rows={data.activity.events.map((row) => ({
            time: formatTimestamp(row.created_at),
            severity: row.severity,
            source: row.event_source ?? 'system',
            type: row.event_type,
            message: row.message,
            raw: row,
          }))}
          emptyLabel="No system events yet."
          onRowClick={(row) => openDrawer({ title: row.type, data: row.raw })}
        />
      </Panel>

      <Panel title="Active positions strip" subtitle="Useful context when a log row mentions a symbol" className="wide">
        <CompactPositionList items={[...data.positions.stockRows, ...data.positions.cryptoRows]} onClickItem={(item) => openDrawer({ title: `${item.symbol} position`, data: item })} />
      </Panel>
    </div>
  )
}

function SettingsPage({
  data,
  derived,
  settingsGroups,
  settingsFilter,
  onSettingsFilter,
  settingsCategory,
  onSettingsCategory,
  updateDraft,
  restoreDefault,
  onSaveSettings,
  settingsSaveBusy,
  runAction,
}) {
  return (
    <div className="page-grid settings-grid">
      <Panel title="Platform settings" subtitle="Powerful, searchable, and padded with guard rails" className="wide tall">
        <div className="settings-toolbar">
          <select value={settingsCategory} onChange={(event) => onSettingsCategory(event.target.value)}>
            <option>All categories</option>
            {settingsCatalog.map((group) => (
              <option key={group.category}>{group.category}</option>
            ))}
          </select>
          <input
            value={settingsFilter}
            onChange={(event) => onSettingsFilter(event.target.value)}
            placeholder="Search settings…"
          />
          <button className="primary-button" onClick={onSaveSettings} disabled={settingsSaveBusy}>
            {settingsSaveBusy ? 'Saving…' : 'Save changes'}
          </button>
        </div>

        <div className="settings-group-list">
          {settingsGroups.map((group) => (
            <section key={group.category} className="settings-group">
              <header>
                <h3>{group.category}</h3>
                <p>{group.fields.length} visible settings</p>
              </header>
              <div className="settings-field-list">
                {group.fields.map((item) => (
                  <div key={item.key} className={`settings-field ${item.dangerous ? 'dangerous' : ''}`}>
                    <div>
                      <strong>{item.label}</strong>
                      <p>{item.key}</p>
                    </div>
                    <div className="settings-editors">
                      {item.options ? (
                        <select value={item.currentValue} onChange={(event) => updateDraft(item, event.target.value)}>
                          {item.options.map((option) => (
                            <option key={option} value={option}>{option}</option>
                          ))}
                        </select>
                      ) : item.valueType === 'bool' ? (
                        <select value={item.currentValue} onChange={(event) => updateDraft(item, event.target.value)}>
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      ) : (
                        <input value={item.currentValue} onChange={(event) => updateDraft(item, event.target.value)} />
                      )}
                      <button className="ghost-button" onClick={() => restoreDefault(item)}>
                        Restore default
                      </button>
                    </div>
                    <div className="settings-footnote">
                      <span>Default: {String(item.defaultValue)}</span>
                      {item.changed && <StatusPill tone="warning">Staged</StatusPill>}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </Panel>

      <Panel title="Danger zone" subtitle="These need extra caution" className="wide">
        <ActionRow
          actions={[
            {
              label: derived.killSwitchEnabled ? 'Disable kill switch' : 'Enable kill switch',
              onClick: () => runAction('Toggle kill switch', '/controls/kill-switch/toggle', { enabled: !derived.killSwitchEnabled }),
              variant: 'danger',
            },
            { label: 'Flatten all', onClick: () => runAction('Flatten all', '/controls/flatten/all', { engage_kill_switch: true }), variant: 'danger' },
            { label: 'Export settings', onClick: () => window.alert('Use the browser save or copy current settings JSON from the drawer in a later pass.'), variant: 'ghost' },
          ]}
        />
      </Panel>

      <Panel title="Runtime snapshot" subtitle="Environment versus database truth" className="wide">
        <DataTable
          columns={[
            { key: 'name', label: 'Field' },
            { key: 'value', label: 'Value' },
            { key: 'source', label: 'Source' },
          ]}
          rows={Object.entries(data.runtimeSettings?.setting_sources ?? {}).map(([key, source]) => ({
            name: key,
            value: stringifySettingValue(runtimeValue(data.runtimeSettings, key)),
            source,
          }))}
          emptyLabel="Runtime snapshot not available yet."
        />
      </Panel>
    </div>
  )
}

function DataPage({ data, openDrawer, runAction }) {
  return (
    <div className="page-grid data-grid">
      <Panel title="Data operations" subtitle="Candle freshness and compute surfaces" className="hero-panel wide">
        <ActionRow
          actions={[
            { label: 'Backfill candles', onClick: () => runAction('Backfill candles', '/controls/candles/backfill', { asset_class: 'all' }) },
            { label: 'Sync incremental candles', onClick: () => runAction('Sync incremental candles', '/controls/candles/incremental', { asset_class: 'all' }) },
            { label: 'Recompute regime', onClick: () => runAction('Recompute regime', '/controls/regime/run-once', { asset_class: 'all' }), variant: 'ghost' },
          ]}
        />
        <div className="hero-metrics four-up">
          <MetricCard label="Stock candle sync rows" value={String(data.data.stockCandleSync.length)} tone="stock" />
          <MetricCard label="Crypto candle sync rows" value={String(data.data.cryptoCandleSync.length)} tone="crypto" />
          <MetricCard label="Stock feature sync rows" value={String(data.data.stockFeatureSync.length)} tone="stock" />
          <MetricCard label="Crypto feature sync rows" value={String(data.data.cryptoFeatureSync.length)} tone="crypto" />
        </div>
      </Panel>

      <Panel title="Stock candle sync" subtitle="How fresh the stock bars are" tone="stock" className="wide">
        <SyncTable rows={data.data.stockCandleSync} onRowClick={(row) => openDrawer({ title: `${row.symbol} stock candle sync`, data: row })} />
      </Panel>

      <Panel title="Crypto candle sync" subtitle="How fresh the crypto bars are" tone="crypto" className="wide">
        <SyncTable rows={data.data.cryptoCandleSync} onRowClick={(row) => openDrawer({ title: `${row.symbol} crypto candle sync`, data: row })} />
      </Panel>

      <Panel title="Stock feature sync" subtitle="Feature engine heartbeat" tone="stock" className="wide">
        <FeatureTable rows={data.data.stockFeatureSync} onRowClick={(row) => openDrawer({ title: `${row.symbol} stock features`, data: row })} />
      </Panel>

      <Panel title="Crypto feature sync" subtitle="Feature engine heartbeat" tone="crypto" className="wide">
        <FeatureTable rows={data.data.cryptoFeatureSync} onRowClick={(row) => openDrawer({ title: `${row.symbol} crypto features`, data: row })} />
      </Panel>
    </div>
  )
}

function Panel({ title, subtitle, children, className = '', tone = 'neutral', onClick }) {
  return (
    <section className={`panel ${className} ${tone}`} onClick={onClick}>
      <header className="panel-header">
        <div>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
      </header>
      <div className="panel-body">{children}</div>
    </section>
  )
}

function MetricCard({ label, value, caption, tone = 'neutral' }) {
  return (
    <article className={`metric-card ${tone}`}>
      <p>{label}</p>
      <strong>{value ?? 'n/a'}</strong>
      {caption && <span>{caption}</span>}
    </article>
  )
}

function StatusPill({ tone = 'neutral', children }) {
  return <span className={`status-pill ${tone}`}>{children}</span>
}

function ActionRow({ actions }) {
  return (
    <div className="action-row">
      {actions.map((action) => (
        <button
          key={action.label}
          className={`${action.variant === 'danger' ? 'danger-button' : action.variant === 'ghost' ? 'ghost-button' : 'primary-button'}`}
          onClick={(event) => {
            event.stopPropagation()
            action.onClick()
          }}
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}

function DataTable({ columns, rows, emptyLabel, onRowClick }) {
  if (!rows.length) {
    return <EmptyState label={emptyLabel} />
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row[columns[0].key]}-${index}`} onClick={() => onRowClick?.(row)}>
              {columns.map((column) => (
                <td key={column.key}>{row[column.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StrategyTable({ rows, onRowClick }) {
  return (
    <DataTable
      columns={[
        { key: 'symbol', label: 'Symbol' },
        { key: 'strategy', label: 'Primary strategy' },
        { key: 'readiness', label: 'Readiness' },
        { key: 'status', label: 'Status' },
        { key: 'reason', label: 'Reason / blocker' },
        { key: 'regime', label: 'Regime' },
      ]}
      rows={rows.map((row) => ({
        symbol: row.symbol,
        strategy: row.strategy_name,
        readiness: formatPercent(row.readiness_score),
        status: row.status,
        reason: row.decision_reason || (row.blocked_reasons?.join(', ') || 'ready'),
        regime: row.regime || 'n/a',
        raw: row,
      }))}
      emptyLabel="No strategy rows yet."
      onRowClick={(row) => onRowClick(row.raw)}
    />
  )
}

function SyncTable({ rows, onRowClick }) {
  return (
    <DataTable
      columns={[
        { key: 'symbol', label: 'Symbol' },
        { key: 'timeframe', label: 'Timeframe' },
        { key: 'status', label: 'Status' },
        { key: 'syncedAt', label: 'Last synced' },
        { key: 'candleAt', label: 'Last candle' },
      ]}
      rows={rows.map((row) => ({
        symbol: row.symbol,
        timeframe: row.timeframe,
        status: row.last_status,
        syncedAt: formatTimestamp(row.last_synced_at),
        candleAt: formatTimestamp(row.last_candle_at),
        raw: row,
      }))}
      emptyLabel="No candle sync data yet."
      onRowClick={(row) => onRowClick(row.raw)}
    />
  )
}

function FeatureTable({ rows, onRowClick }) {
  return (
    <DataTable
      columns={[
        { key: 'symbol', label: 'Symbol' },
        { key: 'timeframe', label: 'Timeframe' },
        { key: 'status', label: 'Status' },
        { key: 'features', label: 'Features' },
        { key: 'computedAt', label: 'Last computed' },
      ]}
      rows={rows.map((row) => ({
        symbol: row.symbol,
        timeframe: row.timeframe,
        status: row.last_status,
        features: row.feature_count,
        computedAt: formatTimestamp(row.last_computed_at),
        raw: row,
      }))}
      emptyLabel="No feature sync rows yet."
      onRowClick={(row) => onRowClick(row.raw)}
    />
  )
}

function Leaderboard({ items, onClickItem }) {
  if (!items.length) {
    return <EmptyState label="Nothing ranked yet." />
  }
  return (
    <ol className="leaderboard">
      {items.slice(0, 10).map((item) => (
        <li key={`${item.symbol}-${item.metricLabel}`} onClick={() => onClickItem(item)}>
          <span>{item.symbol}</span>
          <strong>{item.metricLabel}</strong>
        </li>
      ))}
    </ol>
  )
}

function CompactPositionList({ items, onClickItem }) {
  if (!items.length) {
    return <EmptyState label="No active positions yet." />
  }
  return (
    <div className="compact-list">
      {items.map((item) => (
        <button key={`${item.asset_class}-${item.symbol}-${item.id}`} className="compact-row" onClick={() => onClickItem(item)}>
          <div>
            <strong>{item.symbol}</strong>
            <p>{item.asset_class} • {item.mode}</p>
          </div>
          <div className={toneFromValue(item.unrealized_pnl)}>{formatSignedCurrency(item.unrealized_pnl)}</div>
        </button>
      ))}
    </div>
  )
}

function ContributionList({ items, onClickItem }) {
  if (!items.length) {
    return <EmptyState label="No contribution rows yet." />
  }
  return (
    <div className="contribution-list">
      {items.slice(0, 6).map((item) => (
        <button key={item.symbol} className="contribution-row" onClick={() => onClickItem(item)}>
          <span>{item.symbol}</span>
          <div className="contribution-bar-wrap">
            <div className="contribution-bar" style={{ width: `${Math.min(100, Math.max(8, item.percentOfBook))}%` }} />
          </div>
          <strong>{formatSignedCurrency(item.value)}</strong>
        </button>
      ))}
    </div>
  )
}

function AlertList({ items, onClickItem }) {
  if (!items.length) {
    return <EmptyState label="No recent alerts. Quiet skies." />
  }
  return (
    <div className="alert-list">
      {items.map((item) => (
        <button key={`${item.id}-${item.event_type}`} className="alert-row" onClick={() => onClickItem(item)}>
          <StatusPill tone={toneFromSeverity(item.severity)}>{item.severity}</StatusPill>
          <div>
            <strong>{item.event_type}</strong>
            <p>{item.message}</p>
          </div>
          <span>{formatRelativeTime(item.created_at)}</span>
        </button>
      ))}
    </div>
  )
}

function EmptyState({ label }) {
  return <div className="empty-state">{label}</div>
}

function Drawer({ drawer, onClose }) {
  if (!drawer) {
    return null
  }
  return (
    <aside className="drawer-backdrop" onClick={onClose}>
      <section className="drawer" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-header">
          <div>
            <p className="kicker">Detail drawer</p>
            <h3>{drawer.title}</h3>
          </div>
          <button className="ghost-button" onClick={onClose}>Close</button>
        </header>
        <pre>{JSON.stringify(drawer.data, null, 2)}</pre>
      </section>
    </aside>
  )
}

function ProgressStat({ label, value, tone = 'primary' }) {
  return (
    <div className="progress-stat">
      <div>
        <span>{label}</span>
        <strong>{formatPercent(value)}</strong>
      </div>
      <div className="progress-track">
        <div className={`progress-fill ${tone}`} style={{ width: `${Math.min(100, Math.max(0, (Number(value) || 0) * 100))}%` }} />
      </div>
    </div>
  )
}

function deriveState(data) {
  const stockRows = data.positions.stockRows ?? []
  const cryptoRows = data.positions.cryptoRows ?? []
  const allPositions = [...stockRows, ...cryptoRows]
  const totalPnl = numberValue(data.accounts.total?.realized_pnl) + numberValue(data.accounts.total?.unrealized_pnl)
  const stockPnl = numberValue(data.accounts.stock?.realized_pnl) + numberValue(data.accounts.stock?.unrealized_pnl)
  const cryptoPnl = numberValue(data.accounts.crypto?.realized_pnl) + numberValue(data.accounts.crypto?.unrealized_pnl)
  const totalEquity = numberValue(data.accounts.total?.equity)
  const stockEquity = numberValue(data.accounts.stock?.equity)
  const cryptoEquity = numberValue(data.accounts.crypto?.equity)
  const stockExposure = sumBy(stockRows, 'market_value')
  const cryptoExposure = sumBy(cryptoRows, 'market_value')
  const totalExposure = stockExposure + cryptoExposure
  const totalReturnPct = totalEquity ? totalPnl / Math.max(1, totalEquity - totalPnl) : 0
  const deploymentPct = totalEquity ? totalExposure / totalEquity : 0
  const stockWeightPct = totalEquity ? stockEquity / totalEquity : 0
  const cryptoWeightPct = totalEquity ? cryptoEquity / totalEquity : 0
  const realizedPnl = numberValue(data.accounts.total?.realized_pnl)
  const unrealizedPnl = numberValue(data.accounts.total?.unrealized_pnl)
  const totalMismatchCount = (data.positions.stockMismatches?.length ?? 0) + (data.positions.cryptoMismatches?.length ?? 0)
  const readyStrategyCount = countWhere([...data.strategies.stockRows, ...data.strategies.cryptoRows], (row) => row.status?.toLowerCase() === 'ready')
  const blockedStrategyCount = countWhere([...data.strategies.stockRows, ...data.strategies.cryptoRows], (row) => row.status?.toLowerCase() !== 'ready')
  const criticalEvent = (data.activity.events ?? []).find((item) => ['critical', 'error'].includes((item.severity ?? '').toLowerCase()))
  const warningEvent = (data.activity.events ?? []).find((item) => (item.severity ?? '').toLowerCase() === 'warning')
  const killSwitchEnabled = Boolean(data.controlSnapshot?.kill_switch_enabled)
  const modeLabel = buildModeLabel(data.controlSnapshot)
  const modeTone = modeLabel.toLowerCase().includes('live') ? 'warning' : 'neutral'
  const systemTone = killSwitchEnabled ? 'warning' : criticalEvent ? 'error' : warningEvent ? 'warning' : 'positive'
  const systemLabel = killSwitchEnabled ? 'Kill switch engaged' : criticalEvent ? 'Attention required' : 'Live & observant'
  const stockLeaderboard = buildLeaderboard(data.strategies.stockRows, data.universe.stockRows)
  const cryptoLeaderboard = buildLeaderboard(data.strategies.cryptoRows, data.universe.cryptoRows)
  const activePositions = allPositions
    .slice()
    .sort((left, right) => Math.abs(numberValue(right.unrealized_pnl)) - Math.abs(numberValue(left.unrealized_pnl)))
    .slice(0, 8)
  const lastUpdatedAt = latestTimestamp([
    data.accounts.total?.as_of,
    data.accounts.stock?.as_of,
    data.accounts.crypto?.as_of,
    data.positions.stockSync?.last_synced_at,
    data.positions.cryptoSync?.last_synced_at,
    data.activity.events?.[0]?.created_at,
  ])
  const banner = buildBanner({ killSwitchEnabled, criticalEvent, warningEvent, totalMismatchCount })

  return {
    totalPnl,
    stockPnl,
    cryptoPnl,
    totalReturnPct,
    deploymentPct,
    stockWeightPct,
    cryptoWeightPct,
    stockExposure,
    cryptoExposure,
    exposureAdjustedReturnPct: totalExposure ? totalPnl / totalExposure : 0,
    realizedPnl,
    unrealizedPnl,
    totalMismatchCount,
    readyStrategyCount,
    blockedStrategyCount,
    killSwitchEnabled,
    modeLabel,
    modeTone,
    systemTone,
    systemLabel,
    stockLeaderboard,
    cryptoLeaderboard,
    activePositions,
    lastUpdatedAt,
    banner,
  }
}

function buildSettingsGroups(data, draftSettings, search, category) {
  const query = search.trim().toLowerCase()
  return settingsCatalog
    .filter((group) => category === 'All categories' || group.category === category)
    .map((group) => ({
      ...group,
      fields: group.fields
        .map((item) => ({
          ...item,
          currentValue: draftSettings[item.key]?.value ?? settingValueForKey(data, item.key, item.defaultValue),
          changed: Boolean(draftSettings[item.key]?.changed),
        }))
        .filter((item) => {
          if (!query) {
            return true
          }
          return item.label.toLowerCase().includes(query) || item.key.toLowerCase().includes(query)
        }),
    }))
    .filter((group) => group.fields.length)
}

function settingValueForKey(data, key, fallback) {
  const stored = data.settingsList.find((item) => item.key === key)
  if (stored) {
    return stored.value
  }
  if (key === 'execution.default_mode') {
    return data.controlSnapshot?.default_mode ?? fallback
  }
  if (key === 'execution.stock.mode') {
    return data.controlSnapshot?.stock_mode ?? fallback
  }
  if (key === 'execution.crypto.mode') {
    return data.controlSnapshot?.crypto_mode ?? fallback
  }
  if (key === 'controls.kill_switch_enabled') {
    return String(Boolean(data.controlSnapshot?.kill_switch_enabled))
  }
  if (key === 'controls.stock.trading_enabled') {
    return String(Boolean(data.controlSnapshot?.stock_trading_enabled ?? true))
  }
  if (key === 'controls.crypto.trading_enabled') {
    return String(Boolean(data.controlSnapshot?.crypto_trading_enabled ?? true))
  }
  return fallback
}

function runtimeValue(snapshot, key) {
  if (!snapshot) {
    return 'n/a'
  }
  return snapshot[key] ?? snapshot.setting_sources?.[key] ?? 'n/a'
}

function buildModeLabel(controlSnapshot) {
  if (!controlSnapshot) {
    return 'Paper / awaiting control snapshot'
  }
  return `Default ${controlSnapshot.default_mode} · Stock ${controlSnapshot.stock_mode} · Crypto ${controlSnapshot.crypto_mode}`
}

function buildBanner({ killSwitchEnabled, criticalEvent, warningEvent, totalMismatchCount }) {
  if (killSwitchEnabled) {
    return {
      tone: 'warning',
      title: 'Kill switch engaged',
      message: 'New entries are blocked until the control is released.',
      page: 'settings',
    }
  }
  if (criticalEvent) {
    return {
      tone: 'error',
      title: 'Critical event detected',
      message: criticalEvent.message,
      page: 'activity',
    }
  }
  if (totalMismatchCount > 0) {
    return {
      tone: 'warning',
      title: 'Reconciliation mismatch in queue',
      message: `${totalMismatchCount} mismatch record${totalMismatchCount === 1 ? '' : 's'} need attention.`,
      page: 'positions',
    }
  }
  if (warningEvent) {
    return {
      tone: 'warning',
      title: 'Warning event detected',
      message: warningEvent.message,
      page: 'activity',
    }
  }
  return null
}

function buildLeaderboard(strategyRows, universeRows) {
  if (strategyRows?.length) {
    return strategyRows
      .slice()
      .sort((left, right) => numberValue(right.readiness_score) - numberValue(left.readiness_score))
      .slice(0, 10)
      .map((row) => ({
        symbol: row.symbol,
        metricLabel: `${formatPercent(row.readiness_score)} readiness`,
        raw: row,
      }))
  }

  return (universeRows ?? []).slice(0, 10).map((row) => ({
    symbol: row.symbol,
    metricLabel: `${row.source} rank ${row.rank}`,
    raw: row,
  }))
}

function buildContributionRows(rows) {
  const totalBook = Math.max(1, sumBy(rows, 'market_value'))
  return rows
    .map((row) => ({
      symbol: row.symbol,
      value: numberValue(row.unrealized_pnl),
      percentOfBook: (numberValue(row.market_value) / totalBook) * 100,
      raw: row,
    }))
    .sort((left, right) => Math.abs(right.value) - Math.abs(left.value))
}

function sumBy(rows, key) {
  return (rows ?? []).reduce((total, row) => total + numberValue(row[key]), 0)
}

function countWhere(rows, predicate) {
  return (rows ?? []).reduce((total, row) => total + (predicate(row) ? 1 : 0), 0)
}

function latestTimestamp(values) {
  const stamps = values.filter(Boolean).map((value) => new Date(value).getTime())
  if (!stamps.length) {
    return null
  }
  return new Date(Math.max(...stamps)).toISOString()
}

function toneFromAction(status) {
  if (status === 'success') {
    return 'positive'
  }
  if (status === 'error') {
    return 'error'
  }
  if (status === 'busy') {
    return 'warning'
  }
  return 'neutral'
}

function toneFromSeverity(severity) {
  const value = String(severity ?? '').toLowerCase()
  if (value === 'critical' || value === 'error') {
    return 'error'
  }
  if (value === 'warning') {
    return 'warning'
  }
  return 'neutral'
}

function toneFromValue(value) {
  const numeric = numberValue(value)
  if (numeric > 0) {
    return 'positive'
  }
  if (numeric < 0) {
    return 'error'
  }
  return 'neutral'
}

function humanizePage(page) {
  return [...sidebarPages, ...topUtilityPages].find((item) => item.key === page)?.label ?? page
}

function numberValue(value) {
  if (value === null || value === undefined || value === '') {
    return 0
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function formatCurrency(value) {
  if (value === null || value === undefined || value === '') {
    return 'n/a'
  }
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(numberValue(value))
}

function formatSignedCurrency(value) {
  if (value === null || value === undefined || value === '') {
    return 'n/a'
  }
  const numeric = numberValue(value)
  return `${numeric >= 0 ? '+' : '-'}${formatCurrency(Math.abs(numeric)).replace('$', '$')}`
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') {
    return 'n/a'
  }
  return `${(numberValue(value) * 100).toFixed(1)}%`
}

function formatNumber(value) {
  if (value === null || value === undefined || value === '') {
    return 'n/a'
  }
  return Number(value).toLocaleString('en-US', { maximumFractionDigits: 4 })
}

function formatTimestamp(value) {
  if (!value) {
    return 'n/a'
  }
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatRelativeTime(value) {
  if (!value) {
    return 'just now-ish'
  }
  const deltaSeconds = Math.round((Date.now() - new Date(value).getTime()) / 1000)
  if (Math.abs(deltaSeconds) < 60) {
    return `${Math.max(deltaSeconds, 0)}s ago`
  }
  const deltaMinutes = Math.round(deltaSeconds / 60)
  if (Math.abs(deltaMinutes) < 60) {
    return `${Math.max(deltaMinutes, 0)}m ago`
  }
  const deltaHours = Math.round(deltaMinutes / 60)
  return `${Math.max(deltaHours, 0)}h ago`
}

function summarizePayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return 'No payload detail'
  }
  const keys = Object.keys(payload)
  return keys.slice(0, 3).map((key) => `${key}: ${stringifySettingValue(payload[key])}`).join(' · ')
}

function stringifySettingValue(value) {
  if (Array.isArray(value)) {
    return value.join(', ')
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

function fallbackMetric(value) {
  return value
}

export default App
