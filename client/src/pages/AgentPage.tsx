import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Loader2,
  MinusCircle,
  Play,
  StopCircle,
  XCircle,
} from 'lucide-react'
import {
  streamAgentReport,
  type AgentReportRequest,
  type StageCompletePayload,
  type StageSkippedPayload,
  type StageStartedPayload,
  type WorkflowCompletePayload,
  type WorkflowStartedPayload,
} from '../api/client'
import './AgentPage.css'

type StageStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'

type StageState = {
  name: string
  index: number
  status: StageStatus
  summary?: string | null
  confidence?: number | null
  notes?: string[] | null
  output?: any
  error?: string | null
  latency_ms?: number
  skip_reason?: string
}

type RunStatus = 'idle' | 'running' | 'succeeded' | 'failed' | 'error'

type RunState = {
  run_id: string | null
  status: RunStatus
  error: string | null
  started_at: number | null
  finished_at: number | null
  stage_order: string[]
  stages: Record<string, StageState>
}

const initialRunState: RunState = {
  run_id: null,
  status: 'idle',
  error: null,
  started_at: null,
  finished_at: null,
  stage_order: [],
  stages: {},
}

const defaultForm: AgentReportRequest = {
  influencer: 'China',
  recipient: 'Egypt',
  start_date: '2026-01-01',
  end_date: '2026-03-31',
}

export default function AgentPage() {
  const [form, setForm] = useState<AgentReportRequest>(defaultForm)
  const [run, setRun] = useState<RunState>(initialRunState)
  const abortRef = useRef<AbortController | null>(null)

  // tick every second while running so the elapsed timer updates
  const [, forceTick] = useState(0)
  useEffect(() => {
    if (run.status !== 'running') return
    const t = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [run.status])

  const start = useCallback(async () => {
    if (run.status === 'running') return

    // reset
    setRun({ ...initialRunState, status: 'running', started_at: Date.now() })

    const ac = new AbortController()
    abortRef.current = ac

    try {
      await streamAgentReport(
        form,
        {
          onWorkflowStarted: (p: WorkflowStartedPayload) => {
            const stage_order = p.stage_names
            const stages: Record<string, StageState> = {}
            stage_order.forEach((name, index) => {
              stages[name] = { name, index, status: 'pending' }
            })
            setRun((r) => ({
              ...r,
              run_id: p.run_id,
              stage_order,
              stages,
            }))
          },
          onStageStarted: (p: StageStartedPayload) => {
            setRun((r) => ({
              ...r,
              stages: {
                ...r.stages,
                [p.stage_name]: { ...(r.stages[p.stage_name] || { name: p.stage_name, index: p.index }), status: 'running' },
              },
            }))
          },
          onStageSkipped: (p: StageSkippedPayload) => {
            setRun((r) => ({
              ...r,
              stages: {
                ...r.stages,
                [p.stage_name]: {
                  ...(r.stages[p.stage_name] || { name: p.stage_name, index: p.index }),
                  status: 'skipped',
                  skip_reason: p.reason,
                },
              },
            }))
          },
          onStageComplete: (p: StageCompletePayload) => {
            setRun((r) => ({
              ...r,
              stages: {
                ...r.stages,
                [p.stage_name]: {
                  ...(r.stages[p.stage_name] || { name: p.stage_name, index: p.index }),
                  status: p.status === 'succeeded' ? 'succeeded' : 'failed',
                  summary: p.summary,
                  confidence: p.confidence,
                  notes: p.notes,
                  output: p.output,
                  error: p.error,
                  latency_ms: p.latency_ms,
                },
              },
            }))
          },
          onWorkflowComplete: (p: WorkflowCompletePayload) => {
            setRun((r) => ({
              ...r,
              status: p.status === 'succeeded' ? 'succeeded' : 'failed',
              error: p.error,
              finished_at: Date.now(),
            }))
          },
          onWorkflowError: (msg: string) => {
            setRun((r) => ({
              ...r,
              status: 'error',
              error: msg,
              finished_at: Date.now(),
            }))
          },
        },
        ac.signal,
      )
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setRun((r) => ({ ...r, status: 'error', error: 'Aborted by user', finished_at: Date.now() }))
      } else {
        setRun((r) => ({ ...r, status: 'error', error: String(e?.message || e), finished_at: Date.now() }))
      }
    } finally {
      abortRef.current = null
    }
  }, [form, run.status])

  const abort = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const ordered = useMemo(
    () => run.stage_order.map((n) => run.stages[n]).filter(Boolean),
    [run.stage_order, run.stages],
  )

  const validator = run.stages['validator']?.output as any | undefined
  const narratives = (run.stages['event_narrator']?.output as any)?.narratives as any[] | undefined
  const sourcedClaims = (run.stages['sourcing_claims']?.output as any)?.sourced_claims as any[] | undefined
  const entities = (run.stages['sourcing_entities']?.output as any)?.sourced_entities as any[] | undefined
    || (run.stages['entity_curator']?.output as any)?.entities as any[] | undefined

  return (
    <div className="agent-page">
      <header className="agent-header">
        <h1>Agent</h1>
        <div className="agent-subtitle">
          Twelve-stage report workflow. Streams stage results live; full run ~5 min.
        </div>
      </header>

      <RunForm
        form={form}
        setForm={setForm}
        onStart={start}
        onAbort={abort}
        running={run.status === 'running'}
      />

      {run.run_id && (
        <>
          <RunStatusBar run={run} />
          <StageTimeline stages={ordered} />
          {validator && <ValidatorCard data={validator} />}
          {narratives && narratives.length > 0 && (
            <NarrativesPanel narratives={narratives} sourced={sourcedClaims} />
          )}
          {entities && entities.length > 0 && <EntitiesPanel entities={entities} />}
        </>
      )}
    </div>
  )
}

// =================================================================
// Form
// =================================================================

function RunForm({
  form,
  setForm,
  onStart,
  onAbort,
  running,
}: {
  form: AgentReportRequest
  setForm: (f: AgentReportRequest) => void
  onStart: () => void
  onAbort: () => void
  running: boolean
}) {
  const update = (k: keyof AgentReportRequest, v: string) => setForm({ ...form, [k]: v })

  return (
    <section className="agent-form">
      <div className="agent-form-grid">
        <label>
          <span>Influencer</span>
          <input
            value={form.influencer || ''}
            onChange={(e) => update('influencer', e.target.value)}
            placeholder="China"
            disabled={running}
          />
        </label>
        <label>
          <span>Recipient</span>
          <input
            value={form.recipient || ''}
            onChange={(e) => update('recipient', e.target.value)}
            placeholder="Egypt"
            disabled={running}
          />
        </label>
        <label>
          <span>Start date</span>
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => update('start_date', e.target.value)}
            disabled={running}
          />
        </label>
        <label>
          <span>End date</span>
          <input
            type="date"
            value={form.end_date}
            onChange={(e) => update('end_date', e.target.value)}
            disabled={running}
          />
        </label>
      </div>

      <div className="agent-form-actions">
        {running ? (
          <button className="agent-btn agent-btn-danger" onClick={onAbort}>
            <StopCircle size={16} /> Abort
          </button>
        ) : (
          <button className="agent-btn agent-btn-primary" onClick={onStart}>
            <Play size={16} /> Run workflow
          </button>
        )}
      </div>
    </section>
  )
}

// =================================================================
// Run status bar
// =================================================================

function RunStatusBar({ run }: { run: RunState }) {
  const elapsed_ms = run.started_at
    ? (run.finished_at ?? Date.now()) - run.started_at
    : 0
  const elapsed = formatElapsed(elapsed_ms)

  const completed = run.stage_order.filter((n) => {
    const s = run.stages[n]?.status
    return s === 'succeeded' || s === 'failed' || s === 'skipped'
  }).length

  return (
    <section className="agent-status-bar">
      <div>
        <span className="agent-label">Run</span>
        <code className="agent-runid">{run.run_id?.slice(0, 8)}…</code>
      </div>
      <div>
        <span className="agent-label">Status</span>
        <RunStatusPill status={run.status} />
      </div>
      <div>
        <span className="agent-label">Progress</span>
        <span>
          {completed}/{run.stage_order.length} stages
        </span>
      </div>
      <div>
        <span className="agent-label">Elapsed</span>
        <span>{elapsed}</span>
      </div>
      {run.error && (
        <div className="agent-status-error">
          <AlertCircle size={14} /> {run.error}
        </div>
      )}
    </section>
  )
}

function RunStatusPill({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, { label: string; cls: string }> = {
    idle: { label: 'idle', cls: 'pill-muted' },
    running: { label: 'running', cls: 'pill-running' },
    succeeded: { label: 'succeeded', cls: 'pill-ok' },
    failed: { label: 'failed', cls: 'pill-bad' },
    error: { label: 'error', cls: 'pill-bad' },
  }
  const v = map[status]
  return <span className={`agent-pill ${v.cls}`}>{v.label}</span>
}

// =================================================================
// Stage timeline
// =================================================================

function StageTimeline({ stages }: { stages: StageState[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (name: string) =>
    setExpanded((s) => {
      const n = new Set(s)
      if (n.has(name)) n.delete(name)
      else n.add(name)
      return n
    })

  return (
    <section className="agent-timeline">
      <h2>Stages</h2>
      <ul>
        {stages.map((s) => {
          const isOpen = expanded.has(s.name)
          const canExpand = !!(s.output || s.error || s.notes?.length)
          return (
            <li key={s.name} className={`agent-stage stage-${s.status}`}>
              <div className="agent-stage-head" onClick={() => canExpand && toggle(s.name)}>
                <StageIcon status={s.status} />
                <div className="agent-stage-main">
                  <div className="agent-stage-name">{prettyStageName(s.name)}</div>
                  <div className="agent-stage-summary">
                    {s.summary || s.skip_reason || (s.status === 'running' ? 'running…' : '—')}
                  </div>
                </div>
                <div className="agent-stage-meta">
                  {s.confidence != null && (
                    <span className="agent-meta-item">conf {(s.confidence * 100).toFixed(0)}%</span>
                  )}
                  {s.latency_ms != null && (
                    <span className="agent-meta-item">{formatLatency(s.latency_ms)}</span>
                  )}
                  {canExpand && (
                    <span className="agent-chev">
                      {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </span>
                  )}
                </div>
              </div>
              {isOpen && (
                <div className="agent-stage-body">
                  {s.error && (
                    <div className="agent-error">
                      <strong>Error:</strong> {s.error}
                    </div>
                  )}
                  {s.notes && s.notes.length > 0 && (
                    <div className="agent-notes">
                      {s.notes.map((n, i) => (
                        <div key={i} className="agent-note">• {n}</div>
                      ))}
                    </div>
                  )}
                  {s.output && (
                    <details className="agent-raw">
                      <summary>raw output</summary>
                      <pre>{JSON.stringify(s.output, null, 2)}</pre>
                    </details>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function StageIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case 'running':
      return <Loader2 size={16} className="agent-spin" />
    case 'succeeded':
      return <CheckCircle2 size={16} className="agent-icon-ok" />
    case 'failed':
      return <XCircle size={16} className="agent-icon-bad" />
    case 'skipped':
      return <MinusCircle size={16} className="agent-icon-muted" />
    default:
      return <Circle size={16} className="agent-icon-muted" />
  }
}

// =================================================================
// Validator verdict card
// =================================================================

function ValidatorCard({ data }: { data: any }) {
  const passed: boolean = !!data.passed
  const findings: any[] = data.findings || []
  const metrics: Record<string, any> = data.metrics || {}

  return (
    <section className={`agent-validator ${passed ? 'validator-pass' : 'validator-fail'}`}>
      <div className="validator-head">
        {passed ? <CheckCircle2 size={20} /> : <XCircle size={20} />}
        <h2>Validator: {passed ? 'PASS' : 'FAIL'}</h2>
        <span className="validator-counts">
          {data.error_count ?? 0} error · {data.warning_count ?? 0} warning · {data.info_count ?? 0} info
        </span>
      </div>

      <div className="validator-metrics">
        {Object.entries(metrics).map(([k, v]) => (
          <div key={k} className="validator-metric">
            <div className="validator-metric-k">{prettyMetricName(k)}</div>
            <div className="validator-metric-v">{formatMetricValue(k, v)}</div>
          </div>
        ))}
      </div>

      {findings.length > 0 && (
        <div className="validator-findings">
          <h3>Findings</h3>
          <ul>
            {findings.map((f: any, i: number) => (
              <li key={i} className={`finding-${f.severity}`}>
                <span className="finding-sev">{f.severity}</span>
                <span className="finding-where">{f.where}</span>
                <span className="finding-detail">{f.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

// =================================================================
// Narrated events panel
// =================================================================

function NarrativesPanel({ narratives, sourced }: { narratives: any[]; sourced?: any[] }) {
  // group sourced claims by event for quick lookup
  const claimsByEvent = useMemo(() => {
    const map: Record<string, any[]> = {}
    for (const c of sourced || []) {
      const k = c.referent_id
      if (!k) continue
      ;(map[k] ||= []).push(c)
    }
    return map
  }, [sourced])

  return (
    <section className="agent-narratives">
      <h2>Narrated events</h2>
      <div className="narrative-cards">
        {narratives.map((n) => {
          const eventClaims = claimsByEvent[n.event_id] || []
          const hallucinated = (n.hallucinated_doc_ids || []).length
          const salvaged = Object.keys(n.salvaged_doc_ids || {}).length
          return (
            <article key={n.event_id} className="narrative-card">
              <header>
                <h3>{n.event_name}</h3>
                <div className="narrative-meta">
                  {n.context_doc_count != null && (
                    <span>{n.context_doc_count} docs in context</span>
                  )}
                  {hallucinated > 0 && (
                    <span className="meta-warn">{hallucinated} hallucinated</span>
                  )}
                  {salvaged > 0 && (
                    <span className="meta-info">{salvaged} salvaged</span>
                  )}
                </div>
              </header>
              {n.overview && (
                <div className="narrative-section">
                  <h4>Overview</h4>
                  <p>{stripCitations(n.overview)}</p>
                </div>
              )}
              {n.outcomes && (
                <div className="narrative-section">
                  <h4>Outcomes</h4>
                  <p>{stripCitations(n.outcomes)}</p>
                </div>
              )}
              {n.cited_doc_ids && n.cited_doc_ids.length > 0 && (
                <div className="narrative-citations">
                  <span className="cites-label">Cited:</span>
                  {n.cited_doc_ids.slice(0, 8).map((d: string) => (
                    <CiteChip key={d} docId={d} />
                  ))}
                  {n.cited_doc_ids.length > 8 && (
                    <span className="cites-more">+{n.cited_doc_ids.length - 8}</span>
                  )}
                </div>
              )}
              {eventClaims.length > 0 && (
                <details className="narrative-claims">
                  <summary>{eventClaims.length} sourced claims</summary>
                  <ul>
                    {eventClaims.map((c) => (
                      <li key={c.claim_id}>
                        <span className={`claim-conf conf-${(c.confidence || 'LOW').toLowerCase()}`}>
                          {c.confidence}
                        </span>
                        <span className="claim-text">{c.claim_text}</span>
                        {c.cited_doc_ids?.length > 0 && (
                          <span className="claim-cites">
                            {c.cited_doc_ids.map((d: string) => (
                              <CiteChip key={d} docId={d} compact />
                            ))}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}

// =================================================================
// Entities panel
// =================================================================

function EntitiesPanel({ entities }: { entities: any[] }) {
  return (
    <section className="agent-entities">
      <h2>Curated entities</h2>
      <div className="entity-cards">
        {entities.map((e) => (
          <article key={e.canonical_id} className="entity-card">
            <header>
              <h3>{e.name}</h3>
              <span className="entity-type">{e.entity_type}</span>
            </header>
            {e.country_affiliations?.length > 0 && (
              <div className="entity-countries">
                {e.country_affiliations.join(' · ')}
              </div>
            )}
            <p className="entity-synopsis">{e.role_synopsis}</p>
            {e.cited_doc_ids?.length > 0 && (
              <div className="entity-citations">
                <span className="cites-label">Cited:</span>
                {e.cited_doc_ids.slice(0, 6).map((d: string) => (
                  <CiteChip key={d} docId={d} />
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}

// =================================================================
// Cite chip — links to the Documents page filtered to that one doc.
// `compact` shrinks padding for inline use inside claim rows.
// =================================================================

function CiteChip({ docId, compact = false }: { docId: string; compact?: boolean }) {
  return (
    <Link
      to={`/documents?doc_ids=${encodeURIComponent(docId)}`}
      className={`cite-chip cite-chip-link${compact ? ' cite-chip-compact' : ''}`}
      title={docId}
    >
      {docId.slice(0, 8)}
    </Link>
  )
}

// =================================================================
// Helpers
// =================================================================

function prettyStageName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function prettyMetricName(name: string): string {
  return name
    .replace(/_/g, ' ')
    .replace(/\bpct\b/, '%')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatMetricValue(key: string, v: any): string {
  if (v == null) return '—'
  if (typeof v === 'number') {
    if (key.endsWith('_pct')) return `${(v * 100).toFixed(1)}%`
    return v.toLocaleString()
  }
  return String(v)
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}m ${r}s` : `${s}s`
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// Strip inline [doc_id: ...] / [uuid] tokens so prose reads cleanly in the
// card. Full citation list is shown below the prose as chips.
function stripCitations(text: string): string {
  return text.replace(/\s*\[(?:doc_id:\s*)?[A-Za-z0-9_\-:.]+\]/g, '').trim()
}
