import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  FileBarChart,
  Loader2,
  MinusCircle,
  Play,
  Send,
  StopCircle,
  Wrench,
  XCircle,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  streamAgentConverse,
  streamAgentReport,
  type AgentReportRequest,
  type ChatScope,
  type ChatTurn,
  type ConverseReportOfferScope,
  type ConverseSourceDoc,
  type StageCompletePayload,
  type StageSkippedPayload,
  type StageStartedPayload,
  type WorkflowCompletePayload,
  type WorkflowStartedPayload,
} from '../api/client'
import DataCoverageBadge from '../components/DataCoverageBadge'
import './AgentPage.css'

// =================================================================
// Types
// =================================================================

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

type ToolActivity = {
  step: number
  tool: string
  args: Record<string, unknown>
  status: 'running' | 'ok' | 'failed'
  summary?: string | null
}

type ChatMessage =
  | { id: string; role: 'user'; type: 'text'; content: string }
  | {
      id: string
      role: 'assistant'
      type: 'agent'
      content: string
      status: 'working' | 'done' | 'error'
      tools: ToolActivity[]
      sources?: ConverseSourceDoc[]
      seed?: boolean
    }
  | { id: string; role: 'assistant'; type: 'offer'; scope: ConverseReportOfferScope; launched: boolean }
  | { id: string; role: 'assistant'; type: 'workflow'; run: RunState; scope_at_run: ChatScope }

const EXAMPLES = [
  'Which influencer has gained the most ground across the Middle East in 2026, on corroborated evidence?',
  "Compare China's and Turkey's economic initiatives across the region in 2026",
  "Is Iran's 2026 outreach to the Gulf states real traction or its own media narrative?",
  "How has Russia's activity across the Middle East trended through 2026, and where is it concentrated?",
  'Where are the influencers competing hardest for the same recipients in 2026?',
  'Give me a full report on Turkey across the Middle East for 2026',
]

const newMessageId = () =>
  `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

const seedMessage = (): ChatMessage => ({
  id: newMessageId(),
  role: 'assistant',
  type: 'agent',
  status: 'done',
  tools: [],
  seed: true,
  content:
    'Ask me anything about soft-power activity in the corpus — I pull the data ' +
    'I need (provenance-corrected volumes, corroborated initiatives, activity ' +
    'trends, entities, verified report findings) and answer in whatever form ' +
    'your question calls for. If a question is really a full report, I\'ll ' +
    'offer to run the validated report pipeline.',
})

// =================================================================
// Page
// =================================================================

export default function AgentPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([seedMessage()])
  const [isWorking, setIsWorking] = useState(false)      // converse turn in flight
  const [isRunningReport, setIsRunningReport] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // tick every second while a report runs so elapsed timers update
  const [, forceTick] = useState(0)
  useEffect(() => {
    if (!isRunningReport) return
    const t = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [isRunningReport])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const updateMessage = useCallback((id: string, mut: (m: ChatMessage) => ChatMessage) => {
    setMessages((all) => all.map((m) => (m.id === id ? mut(m) : m)))
  }, [])

  // ----- conversational turn ------------------------------------------------

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || isWorking) return

      // History = prior user + assistant answer text (skip seed / offers / workflows)
      const history: ChatTurn[] = messages
        .filter((m): m is Extract<ChatMessage, { type: 'text' } | { type: 'agent' }> =>
          (m.type === 'text' || m.type === 'agent') && !(m as any).seed)
        .map((m) => ({ role: m.role, content: m.content }))

      const userMsg: ChatMessage = { id: newMessageId(), role: 'user', type: 'text', content: trimmed }
      const agentId = newMessageId()
      const agentMsg: ChatMessage = {
        id: agentId, role: 'assistant', type: 'agent',
        content: '', status: 'working', tools: [],
      }
      setMessages((m) => [...m, userMsg, agentMsg])
      setIsWorking(true)

      const ac = new AbortController()
      abortRef.current = ac

      try {
        await streamAgentConverse(
          { message: trimmed, history },
          {
            onToolCall: (p) => {
              updateMessage(agentId, (m) => m.type === 'agent'
                ? { ...m, tools: [...m.tools, { step: p.step, tool: p.tool, args: p.arguments, status: 'running' }] }
                : m)
            },
            onToolResult: (p) => {
              updateMessage(agentId, (m) => m.type === 'agent'
                ? {
                    ...m,
                    tools: m.tools.map((t) =>
                      t.step === p.step
                        ? { ...t, status: p.ok ? 'ok' : 'failed', summary: p.summary }
                        : t),
                  }
                : m)
            },
            onReportOffer: (scope) => {
              setMessages((all) => [
                ...all,
                { id: newMessageId(), role: 'assistant', type: 'offer', scope, launched: false },
              ])
            },
            onAnswer: (answer) => {
              updateMessage(agentId, (m) => m.type === 'agent'
                ? { ...m, content: answer, status: 'done' }
                : m)
            },
            onSources: (docs) => {
              updateMessage(agentId, (m) => m.type === 'agent' ? { ...m, sources: docs } : m)
            },
            onError: (msg) => {
              updateMessage(agentId, (m) => m.type === 'agent'
                ? { ...m, content: `Something went wrong: ${msg}`, status: 'error' }
                : m)
            },
          },
          ac.signal,
        )
      } catch (e: any) {
        const reason = e?.name === 'AbortError' ? 'Stopped.' : `Request failed: ${String(e?.message || e)}`
        updateMessage(agentId, (m) => m.type === 'agent'
          ? { ...m, content: m.content || reason, status: e?.name === 'AbortError' ? 'done' : 'error' }
          : m)
      } finally {
        abortRef.current = null
        setIsWorking(false)
      }
    },
    [isWorking, messages, updateMessage],
  )

  // ----- full report pipeline (explicit, from an offer card) -----------------

  const runReport = useCallback(async (offerId: string, scope: ConverseReportOfferScope) => {
    if (isRunningReport) return
    updateMessage(offerId, (m) => (m.type === 'offer' ? { ...m, launched: true } : m))

    const scopeAtRun: ChatScope = {
      influencer: scope.influencer,
      recipient: scope.recipient,
      region: scope.region,
      start_date: scope.start_date,
      end_date: scope.end_date,
      category: scope.category,
      subcategory: null,
      category_mode: scope.category_mode || 'flat',
    }
    const initialRun: RunState = {
      run_id: null, status: 'running', error: null,
      started_at: Date.now(), finished_at: null,
      stage_order: [], stages: {},
    }
    const wfId = newMessageId()
    setMessages((m) => [
      ...m,
      { id: wfId, role: 'assistant', type: 'workflow', run: initialRun, scope_at_run: scopeAtRun },
    ])
    setIsRunningReport(true)

    const ac = new AbortController()
    abortRef.current = ac
    const updateRun = (mut: (r: RunState) => RunState) => {
      setMessages((all) =>
        all.map((m) => (m.id === wfId && m.type === 'workflow' ? { ...m, run: mut(m.run) } : m)),
      )
    }

    const req: AgentReportRequest = {
      influencer: scope.influencer || undefined,
      recipient: scope.recipient || undefined,
      region: scope.region || undefined,
      start_date: scope.start_date,
      end_date: scope.end_date,
      ...(scope.category ? { category: scope.category } : {}),
      ...(scope.category_mode ? { category_mode: scope.category_mode } : {}),
    } as AgentReportRequest & { category?: string; category_mode?: string }

    try {
      await streamAgentReport(
        req,
        {
          onWorkflowStarted: (p: WorkflowStartedPayload) => {
            const stages: Record<string, StageState> = {}
            p.stage_names.forEach((name, index) => {
              stages[name] = { name, index, status: 'pending' }
            })
            updateRun((r) => ({ ...r, run_id: p.run_id, stage_order: p.stage_names, stages }))
          },
          onStageStarted: (p: StageStartedPayload) => {
            updateRun((r) => ({
              ...r,
              stages: {
                ...r.stages,
                [p.stage_name]: {
                  ...(r.stages[p.stage_name] || { name: p.stage_name, index: p.index }),
                  status: 'running',
                },
              },
            }))
          },
          onStageSkipped: (p: StageSkippedPayload) => {
            updateRun((r) => ({
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
            updateRun((r) => ({
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
            updateRun((r) => ({
              ...r,
              status: p.status === 'succeeded' ? 'succeeded' : 'failed',
              error: p.error,
              finished_at: Date.now(),
            }))
          },
          onWorkflowError: (msg: string) => {
            updateRun((r) => ({ ...r, status: 'error', error: msg, finished_at: Date.now() }))
          },
        },
        ac.signal,
      )
    } catch (e: any) {
      const reason = e?.name === 'AbortError' ? 'Aborted by user' : String(e?.message || e)
      updateRun((r) => ({ ...r, status: 'error', error: reason, finished_at: Date.now() }))
    } finally {
      abortRef.current = null
      setIsRunningReport(false)
    }
  }, [isRunningReport, updateMessage])

  const abort = useCallback(() => abortRef.current?.abort(), [])

  const busy = isWorking || isRunningReport
  const showExamples = messages.length === 1

  return (
    <div className="agent-shell agent-shell-conversational">
      <div className="agent-chat-col">
        <header className="agent-header">
          <h1>Agent <DataCoverageBadge /></h1>
          <div className="agent-subtitle">
            Conversational analyst assistant — pulls provenance-corrected data with tools and
            answers in the form your question calls for. Full validated reports run only when
            you click.
          </div>
        </header>

        <div className="agent-thread" ref={scrollRef}>
          {messages.map((m) => {
            switch (m.type) {
              case 'text':
                return (
                  <div key={m.id} className="chat-message chat-user">
                    <div className="chat-bubble">{m.content}</div>
                  </div>
                )
              case 'agent':
                return <AgentMessageView key={m.id} msg={m} />
              case 'offer':
                return (
                  <OfferCard
                    key={m.id}
                    msg={m}
                    disabled={isRunningReport}
                    onRun={() => runReport(m.id, m.scope)}
                  />
                )
              case 'workflow':
                return <WorkflowMessageView key={m.id} msg={m} />
            }
          })}
          {showExamples && (
            <div className="agent-examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="agent-example" onClick={() => send(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="agent-input-row">
          <ChatInput onSend={send} disabled={busy} />
          {busy && (
            <button className="agent-btn agent-btn-danger agent-stop" onClick={abort} title="Stop">
              <StopCircle size={16} /> Stop
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// =================================================================
// Conversational agent message (tool activity + markdown answer + sources)
// =================================================================

function AgentMessageView({ msg }: { msg: Extract<ChatMessage, { type: 'agent' }> }) {
  return (
    <div className="chat-message chat-assistant">
      <div className={`chat-bubble agent-answer ${msg.status === 'error' ? 'agent-answer-error' : ''}`}>
        {msg.tools.length > 0 && (
          <div className="agent-tools">
            {msg.tools.map((t) => (
              <div
                key={t.step}
                className={`agent-tool agent-tool-${t.status}`}
                title={JSON.stringify(t.args, null, 2)}
              >
                {t.status === 'running' ? (
                  <Loader2 size={13} className="agent-spin" />
                ) : t.status === 'ok' ? (
                  <CheckCircle2 size={13} />
                ) : (
                  <XCircle size={13} />
                )}
                <span className="agent-tool-name">
                  <Wrench size={11} /> {t.tool}
                </span>
                {t.summary && <span className="agent-tool-summary">{t.summary}</span>}
              </div>
            ))}
          </div>
        )}

        {msg.status === 'working' && !msg.content ? (
          <div className="agent-thinking">
            <Loader2 size={14} className="agent-spin" /> working…
          </div>
        ) : (
          <div className="agent-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          </div>
        )}

        {msg.sources && msg.sources.length > 0 && (
          <div className="agent-sources">
            <span className="agent-sources-label">Sources</span>
            {msg.sources.map((s) =>
              s.kind === 'event' && s.app_link ? (
                <Link key={s.id} to={s.app_link} className="agent-source-chip agent-source-link"
                  title={`${s.title ?? s.id} · ${s.date ?? ''}`}>
                  {truncateLabel(s.title || s.id)}
                </Link>
              ) : (
                <span key={s.id} className="agent-source-chip"
                  title={`${s.title ?? s.id}${s.source_name ? ` — ${s.source_name}` : ''}${s.date ? ` · ${s.date}` : ''}`}>
                  {truncateLabel(s.source_name || s.title || s.id)}
                </span>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function truncateLabel(s: string): string {
  return s.length > 40 ? s.slice(0, 39) + '…' : s
}

// =================================================================
// Full-report offer card (the pipeline never auto-runs)
// =================================================================

function OfferCard({
  msg,
  disabled,
  onRun,
}: {
  msg: Extract<ChatMessage, { type: 'offer' }>
  disabled: boolean
  onRun: () => void
}) {
  const s = msg.scope
  const target = s.recipient || s.region
  return (
    <div className="chat-message chat-assistant">
      <div className="agent-offer">
        <div className="agent-offer-head">
          <FileBarChart size={16} />
          <span>Full validated report available</span>
        </div>
        <div className="agent-offer-scope">
          {s.influencer} → {target} · {s.start_date} → {s.end_date}
          {s.category && s.category_mode === 'filter' && <> · {s.category} only</>}
        </div>
        {s.reason && <div className="agent-offer-reason">{s.reason}</div>}
        <div className="agent-offer-actions">
          <button
            className="agent-btn agent-btn-primary agent-btn-small"
            onClick={onRun}
            disabled={disabled || msg.launched}
          >
            <Play size={14} /> {msg.launched ? 'Started' : 'Run full report (~minutes)'}
          </button>
          <span className="agent-offer-note">
            12 stages: retrieval, narration, sourcing, QA, hallucination validation
          </span>
        </div>
      </div>
    </div>
  )
}

function WorkflowMessageView({
  msg,
}: {
  msg: Extract<ChatMessage, { type: 'workflow' }>
}) {
  const run = msg.run
  const ordered = useMemo(
    () => run.stage_order.map((n) => run.stages[n]).filter(Boolean),
    [run.stage_order, run.stages],
  )

  const validator = run.stages['validator']?.output as any | undefined
  const narratives = (run.stages['event_narrator']?.output as any)?.narratives as any[] | undefined
  const sourcedClaims = (run.stages['sourcing_claims']?.output as any)?.sourced_claims as any[] | undefined
  const entities =
    ((run.stages['sourcing_entities']?.output as any)?.sourced_entities as any[] | undefined) ||
    ((run.stages['entity_curator']?.output as any)?.entities as any[] | undefined)

  const elapsed_ms = run.started_at ? (run.finished_at ?? Date.now()) - run.started_at : 0
  const completed = run.stage_order.filter((n) => {
    const s = run.stages[n]?.status
    return s === 'succeeded' || s === 'failed' || s === 'skipped'
  }).length

  return (
    <div className="chat-message chat-assistant chat-workflow">
      <div className="workflow-bubble">
        <div className="workflow-header">
          <span className="workflow-title">Workflow run</span>
          <RunStatusPill status={run.status} />
          <span className="workflow-meta">
            {completed}/{run.stage_order.length} stages · {formatElapsed(elapsed_ms)}
            {run.run_id && <> · <code>{run.run_id.slice(0, 8)}</code></>}
          </span>
        </div>
        <div className="workflow-scope">
          {[msg.scope_at_run.influencer, '→', msg.scope_at_run.recipient || msg.scope_at_run.region]
            .filter(Boolean)
            .join(' ')}
          {' · '}
          {msg.scope_at_run.start_date} → {msg.scope_at_run.end_date}
          {msg.scope_at_run.category &&
            msg.scope_at_run.category_mode === 'filter' && (
              <> · {msg.scope_at_run.category} only</>
            )}
        </div>

        {run.error && (
          <div className="agent-error workflow-error">
            <AlertCircle size={14} /> {run.error}
          </div>
        )}

        <StageTimeline stages={ordered} />
        {validator && <ValidatorCard data={validator} />}
        {narratives && narratives.length > 0 && (
          <NarrativesPanel narratives={narratives} sourced={sourcedClaims} />
        )}
        {entities && entities.length > 0 && <EntitiesPanel entities={entities} />}
      </div>
    </div>
  )
}

// =================================================================
// Chat input
// =================================================================

function ChatInput({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void
  disabled: boolean
}) {
  const [draft, setDraft] = useState('')
  const submit = () => {
    if (!draft.trim() || disabled) return
    onSend(draft)
    setDraft('')
  }
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }
  return (
    <div className="chat-input">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Describe what you want a brief on… (Shift+Enter for newline)"
        rows={2}
        disabled={disabled}
      />
      <button
        className="agent-btn agent-btn-primary"
        onClick={submit}
        disabled={disabled || !draft.trim()}
      >
        <Send size={16} />
      </button>
    </div>
  )
}

// =================================================================
// Run-status pill
// =================================================================

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
// Validator card
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
                  {salvaged > 0 && <span className="meta-info">{salvaged} salvaged</span>}
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
// Entities
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
              <div className="entity-countries">{e.country_affiliations.join(' · ')}</div>
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
// Cite chip -> /documents?doc_ids=<uuid>
// Opens in a new tab so clicking a citation never disrupts an
// in-flight workflow run on the agent page (state is held in this
// component; navigating away unmounts it and aborts the SSE stream).
// =================================================================

function CiteChip({ docId, compact = false }: { docId: string; compact?: boolean }) {
  return (
    <Link
      to={`/documents?doc_ids=${encodeURIComponent(docId)}`}
      target="_blank"
      rel="noopener noreferrer"
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
  return name.replace(/_/g, ' ').replace(/\bpct\b/, '%').replace(/\b\w/g, (c) => c.toUpperCase())
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

function stripCitations(text: string): string {
  return text.replace(/\s*\[(?:doc_id:\s*)?[A-Za-z0-9_\-:.]+\]/g, '').trim()
}
