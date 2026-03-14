import { useEffect, useMemo, useState } from 'react'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8101'

function App() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const healthUrl = useMemo(() => `${apiBaseUrl}/health`, [])

  useEffect(() => {
    let cancelled = false

    async function loadHealth() {
      try {
        setLoading(true)
        setError('')

        const response = await fetch(healthUrl)
        if (!response.ok) {
          throw new Error(`Backend health check failed with status ${response.status}`)
        }

        const payload = await response.json()
        if (!cancelled) {
          setHealth(payload)
        }
      } catch (caughtError) {
        if (!cancelled) {
          setError(caughtError instanceof Error ? caughtError.message : 'Unknown error')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadHealth()

    return () => {
      cancelled = true
    }
  }, [healthUrl])

  return (
    <main className="app-shell">
      <section className="hero-card">
        <p className="eyebrow">Phase 1 bootstrap</p>
        <h1>Small Account Multi-Asset Trading Bot</h1>
        <p className="summary">
          Backend, frontend, environment loading, Docker Compose, PostgreSQL wiring,
          and a live health handshake are now scaffolded.
        </p>

        <div className="status-grid">
          <article className="status-card">
            <h2>Frontend</h2>
            <p>React + Vite shell running on port 4174.</p>
          </article>

          <article className="status-card">
            <h2>Backend</h2>
            <p>FastAPI health endpoint exposed on port 8101.</p>
          </article>

          <article className="status-card">
            <h2>Database</h2>
            <p>PostgreSQL container mapped to host port 55432.</p>
          </article>
        </div>

        <div className="health-panel">
          <h2>Backend health</h2>

          {loading && <p className="muted">Checking backend pulse…</p>}

          {!loading && error && <p className="error">{error}</p>}

          {!loading && health && (
            <dl className="health-grid">
              <div>
                <dt>Status</dt>
                <dd>{health.status}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{health.environment}</dd>
              </div>
              <div>
                <dt>API Prefix</dt>
                <dd>{health.api_prefix}</dd>
              </div>
              <div>
                <dt>Backend Port</dt>
                <dd>{health.backend_port}</dd>
              </div>
            </dl>
          )}
        </div>
      </section>
    </main>
  )
}

export default App
