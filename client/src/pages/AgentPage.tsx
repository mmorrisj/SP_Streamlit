import { useEffect, useState } from 'react'
import axios from 'axios'
import './AgentPage.css'

// TODO: wire to /api/agent/analyze with streaming workflow trace updates.
// This is a scaffolding-only page; tool execution and briefing rendering
// are intentionally stubbed until the orchestrator and providers land.

type WorkflowStep = {
  step: number
  tool: string
  reason: string
  status: string
}

type ToolDescriptor = {
  name: string
  description: string
  foundation_dependency?: string
}

type AnalyzeResponse = {
  run_id: string
  briefing: unknown | null
  workflow: WorkflowStep[]
  evidence: unknown[]
  entities: unknown[]
  timeline: unknown[]
}

const api = axios.create({ baseURL: '/api' })

export default function AgentPage() {
  const [query, setQuery] = useState('')
  const [tools, setTools] = useState<ToolDescriptor[]>([])
  const [response, setResponse] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    api.get('/agent/health').then((r) => setHealth(r.data)).catch(() => setHealth(null))
    api.get('/agent/tools').then((r) => setTools(r.data.tools || [])).catch(() => setTools([]))
  }, [])

  const onAnalyze = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      const r = await api.post<AnalyzeResponse>('/agent/analyze', { query })
      setResponse(r.data)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="agent-page">
      <header className="agent-header">
        <h1>Agent</h1>
        <span className="agent-subtitle">
          Orchestrated MCP-style tool calling over Soft Power holdings
        </span>
        {health && (
          <div className="agent-health">
            provider: <code>{String(health.provider)}</code> · mode:{' '}
            <code>{String(health.tool_mode)}</code>
          </div>
        )}
      </header>

      <section className="agent-query">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask an analyst question (e.g. 'Generate a 72-hour briefing on China–Egypt activity')"
          rows={3}
        />
        <button onClick={onAnalyze} disabled={loading || !query.trim()}>
          {loading ? 'Running…' : 'Analyze'}
        </button>
      </section>

      <div className="agent-grid">
        <section className="agent-panel">
          <h2>Plan</h2>
          {response?.workflow?.length ? (
            <ol className="agent-plan">
              {response.workflow.map((s) => (
                <li key={s.step}>
                  <strong>{s.tool}</strong>
                  <div className="agent-plan-reason">{s.reason}</div>
                  <div className="agent-plan-status">{s.status}</div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="agent-empty">No plan yet. Submit a query to see the workflow.</div>
          )}
        </section>

        <section className="agent-panel">
          <h2>Workflow trace</h2>
          <div className="agent-empty">
            Trace rendering pending — orchestrator persists steps to
            <code> agent_tool_calls</code>.
          </div>
        </section>

        <section className="agent-panel agent-panel-wide">
          <h2>Briefing</h2>
          {response?.briefing ? (
            <pre>{JSON.stringify(response.briefing, null, 2)}</pre>
          ) : (
            <div className="agent-empty">Briefing generator is not yet wired.</div>
          )}
        </section>

        <section className="agent-panel agent-panel-wide">
          <h2>Available tools</h2>
          <ul className="agent-tools">
            {tools.map((t) => (
              <li key={t.name}>
                <strong>{t.name}</strong> — {t.description}
                {t.foundation_dependency && (
                  <div className="agent-tool-dep">
                    wraps <code>{t.foundation_dependency}</code>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
