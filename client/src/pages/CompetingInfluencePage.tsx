import { useMemo, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { Globe, TrendingUp, Zap, FileText, Loader2, ChevronDown, ChevronUp, ExternalLink, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { fetchCompetingInfluence } from '../api/client'
import type { CompetingInfluenceSummary, CompetingInfluenceEvent } from '../api/client'
import './CompetingInfluencePage.css'

interface AssessmentSource {
  citation_number: number
  doc_id: string | null
  content: string
  title: string | null
  source_name: string | null
  date: string | null
  initiating_country: string | null
  recipient_country: string | null
  category: string | null
  relevance_score: number
}

const RECIPIENTS = [
  'Bahrain', 'Cyprus', 'Egypt', 'Iran', 'Iraq', 'Israel', 'Jordan', 'Kuwait',
  'Lebanon', 'Libya', 'Oman', 'Palestine', 'Qatar', 'Saudi Arabia', 'Syria',
  'Turkey', 'UAE', 'Yemen',
]

const INFLUENCERS = ['China', 'Iran', 'Russia', 'Turkey', 'United States']

const INFLUENCER_COLORS: Record<string, string> = {
  'China': '#dc2626',
  'Iran': '#059669',
  'Russia': '#2563eb',
  'Turkey': '#d97706',
  'United States': '#7c3aed',
}

const CATEGORY_COLORS: Record<string, string> = {
  'Economic': '#2563eb',
  'Social': '#059669',
  'Military': '#dc2626',
  'Diplomacy': '#7c3aed',
}

const CATEGORIES = ['Economic', 'Social', 'Military', 'Diplomacy']

function getHeatColor(value: number, max: number): string {
  if (!value || !max) return '#f9fafb'
  const intensity = Math.min(value / max, 1)
  const r = Math.round(255 - intensity * (255 - 26))
  const g = Math.round(255 - intensity * (255 - 54))
  const b = Math.round(255 - intensity * (255 - 93))
  return `rgb(${r}, ${g}, ${b})`
}

export default function CompetingInfluencePage() {
  const { recipient: routeRecipient } = useParams<{ recipient: string }>()
  const navigate = useNavigate()
  const recipient = routeRecipient || 'Egypt'

  // Assessment state
  const [assessmentContent, setAssessmentContent] = useState('')
  const [assessmentSources, setAssessmentSources] = useState<AssessmentSource[]>([])
  const [assessmentLoading, setAssessmentLoading] = useState(false)
  const [assessmentGenerated, setAssessmentGenerated] = useState(false)
  const [sourcesExpanded, setSourcesExpanded] = useState(false)
  const assessmentRef = useRef<HTMLDivElement>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['competing-influence', recipient],
    queryFn: () => fetchCompetingInfluence(recipient),
    enabled: !!recipient,
    staleTime: 5 * 60 * 1000,
  })

  // Build metrics context string for the LLM prompt
  const buildMetricsContext = useCallback(() => {
    if (!data) return ''

    let ctx = 'Influencer Activity Summary:\n'
    for (const inf of data.influencer_summary) {
      ctx += `- ${inf.influencer}: ${inf.doc_count.toLocaleString()} documents, ${inf.event_count} events`
      if (inf.avg_materiality != null) ctx += `, avg materiality ${inf.avg_materiality.toFixed(1)}`
      if (inf.top_category) ctx += `, top category: ${inf.top_category}`
      ctx += '\n'
    }

    ctx += '\nCategory Breakdown (documents per influencer):\n'
    ctx += '| Category | ' + INFLUENCERS.join(' | ') + ' |\n'
    for (const cat of CATEGORIES) {
      const row = INFLUENCERS.map(inf => {
        const m = data.category_matrix.find((r: Record<string, unknown>) => r.influencer === inf)
        return String((m?.[cat] as number) || 0)
      })
      ctx += `| ${cat} | ${row.join(' | ')} |\n`
    }

    return ctx
  }, [data])

  const generateAssessment = useCallback(async () => {
    if (!data || assessmentLoading) return

    setAssessmentLoading(true)
    setAssessmentContent('')
    setAssessmentSources([])
    setAssessmentGenerated(true)

    const token = localStorage.getItem('token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

    try {
      const response = await fetch(`/api/competing-influence/${encodeURIComponent(recipient)}/assessment`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ metrics_context: buildMetricsContext() }),
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'sources') {
              setAssessmentSources(event.sources || [])
            } else if (event.type === 'content') {
              setAssessmentContent(prev => prev + event.content)
            }
          } catch { /* skip malformed lines */ }
        }
      }
    } catch (err) {
      setAssessmentContent(prev => prev + `\n\n[Error: ${err}]`)
    } finally {
      setAssessmentLoading(false)
    }
  }, [data, recipient, assessmentLoading, buildMetricsContext])

  // Reset assessment when recipient changes
  const prevRecipient = useRef(recipient)
  if (prevRecipient.current !== recipient) {
    prevRecipient.current = recipient
    setAssessmentContent('')
    setAssessmentSources([])
    setAssessmentGenerated(false)
  }

  // Find max value in category matrix for heatmap scaling
  const maxCatValue = useMemo(() => {
    if (!data?.category_matrix) return 1
    let max = 0
    for (const row of data.category_matrix) {
      for (const cat of CATEGORIES) {
        const v = (row[cat] as number) || 0
        if (v > max) max = v
      }
    }
    return max || 1
  }, [data])

  const handleRecipientChange = (newRecipient: string) => {
    navigate(`/competing/${encodeURIComponent(newRecipient)}`)
  }

  if (isLoading) {
    return (
      <div className="competing-page">
        <div className="loading-state">Loading competing influence data...</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="competing-page">
        <div className="empty-state">No data available for {recipient}</div>
      </div>
    )
  }

  return (
    <div className="competing-page">
      {/* Header */}
      <div className="competing-header">
        <div>
          <h1><Globe size={24} /> Competing Influence</h1>
          <p>All influencer activity targeting a single recipient</p>
        </div>
        <select
          className="recipient-select"
          value={recipient}
          onChange={e => handleRecipientChange(e.target.value)}
        >
          {RECIPIENTS.map(r => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </div>

      {/* KPI Cards */}
      <div className="influencer-kpi-row">
        {data.influencer_summary.map((inf: CompetingInfluenceSummary) => (
          <div
            key={inf.influencer}
            className="influencer-kpi-card"
            style={{ borderTopColor: INFLUENCER_COLORS[inf.influencer] || '#999' }}
            onClick={() => navigate(`/bilateral/${encodeURIComponent(inf.influencer)}/${encodeURIComponent(recipient)}`)}
          >
            <div className="kpi-card-country">{inf.influencer}</div>
            <div className="kpi-card-stats">
              <div className="kpi-stat">
                <FileText size={14} />
                <span>{inf.doc_count.toLocaleString()}</span>
                <span className="kpi-label">docs</span>
              </div>
              <div className="kpi-stat">
                <Zap size={14} />
                <span>{inf.event_count}</span>
                <span className="kpi-label">events</span>
              </div>
            </div>
            {inf.top_category && (
              <span
                className="kpi-category-badge"
                style={{ background: CATEGORY_COLORS[inf.top_category] || '#999' }}
              >
                {inf.top_category}
              </span>
            )}
            {inf.avg_materiality != null && (
              <div className="kpi-materiality">
                <TrendingUp size={12} />
                <span>{inf.avg_materiality.toFixed(1)}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Corroborated Share of Attention — provenance-normalized dominance */}
      <div className="competing-section">
        <h2>Corroborated Share of Attention</h2>
        <p style={{ fontSize: '0.8rem', color: '#64748b', margin: '0 0 0.75rem' }}>
          Share of third-party-corroborated coverage (excluding each actor&rsquo;s own state media) toward {data.recipient}.
          Corrects for state-media volume &mdash; an actor&rsquo;s raw lead can collapse once its own outlets are stripped.
        </p>
        {(() => {
          const rows = data.influencer_summary.filter(i => (i.corroborated ?? 0) > 0)
          const total = rows.reduce((s, i) => s + i.corroborated, 0) || 1
          const sorted = [...rows].sort((a, b) => b.corroborated - a.corroborated)
          return (
            <>
              <div style={{ display: 'flex', width: '100%', height: 34, borderRadius: 6, overflow: 'hidden', border: '1px solid #e2e8f0' }}>
                {sorted.map(i => {
                  const pct = 100 * i.corroborated / total
                  return (
                    <div key={i.influencer} title={`${i.influencer}: ${i.corroborated.toLocaleString()} (${pct.toFixed(0)}%)`}
                      style={{ width: `${pct}%`, background: INFLUENCER_COLORS[i.influencer] || '#999',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: '0.72rem', fontWeight: 600 }}>
                      {pct >= 8 ? `${pct.toFixed(0)}%` : ''}
                    </div>
                  )
                })}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.85rem', marginTop: '0.6rem' }}>
                {sorted.map(i => (
                  <span key={i.influencer} style={{ fontSize: '0.75rem', color: '#475569', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: INFLUENCER_COLORS[i.influencer] || '#999' }} />
                    {i.influencer}: {i.corroborated.toLocaleString()}
                    {i.self_report_share >= 0.3 && (
                      <em style={{ color: '#b91c1c' }}> ({Math.round(i.self_report_share * 100)}% self-rep., raw {i.doc_count.toLocaleString()})</em>
                    )}
                  </span>
                ))}
              </div>
            </>
          )
        })()}
      </div>

      {/* Timeline Section */}
      <div className="competing-section">
        <h2>Monthly Activity by Influencer</h2>
        <div className="chart-container">
          <ResponsiveContainer width="100%" height={360}>
            <AreaChart data={data.monthly_by_influencer}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="month"
                tickFormatter={(v: string) => {
                  if (!v) return ''
                  const d = new Date(v)
                  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
                }}
                tick={{ fontSize: 12 }}
              />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                labelFormatter={(v: string) => {
                  if (!v) return ''
                  return new Date(v).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
                }}
              />
              <Legend />
              {INFLUENCERS.map(inf => (
                <Area
                  key={inf}
                  type="monotone"
                  dataKey={inf}
                  stackId="1"
                  stroke={INFLUENCER_COLORS[inf]}
                  fill={INFLUENCER_COLORS[inf]}
                  fillOpacity={0.6}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Category Heatmap */}
      <div className="competing-section">
        <h2>Category Breakdown by Influencer</h2>
        <div className="heatmap-container">
          <table className="heatmap-table">
            <thead>
              <tr>
                <th></th>
                {INFLUENCERS.map(inf => (
                  <th key={inf} style={{ color: INFLUENCER_COLORS[inf] }}>{inf}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CATEGORIES.map(cat => (
                <tr key={cat}>
                  <td className="heatmap-row-label">
                    <span
                      className="cat-dot"
                      style={{ background: CATEGORY_COLORS[cat] }}
                    />
                    {cat}
                  </td>
                  {INFLUENCERS.map(inf => {
                    const row = data.category_matrix.find(
                      (r: Record<string, unknown>) => r.influencer === inf
                    )
                    const val = (row?.[cat] as number) || 0
                    return (
                      <td
                        key={inf}
                        className="heatmap-cell"
                        style={{
                          background: getHeatColor(val, maxCatValue),
                          color: val > maxCatValue * 0.5 ? 'white' : '#333',
                        }}
                        onClick={() => navigate(
                          `/bilateral/${encodeURIComponent(inf)}/${encodeURIComponent(recipient)}`
                        )}
                        title={`${inf} → ${recipient}: ${val} ${cat} documents`}
                      >
                        {val > 0 ? val.toLocaleString() : '-'}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Events */}
      <div className="competing-section">
        <h2>Recent Events by Influencer</h2>
        <div className="events-grid">
          {INFLUENCERS.map(inf => (
            <div key={inf} className="events-column">
              <div
                className="events-column-header"
                style={{ borderBottomColor: INFLUENCER_COLORS[inf] }}
              >
                {inf}
              </div>
              {(data.recent_events[inf] || []).length === 0 ? (
                <div className="no-events">No recent events</div>
              ) : (
                data.recent_events[inf].map((event: CompetingInfluenceEvent) => (
                  <div
                    key={event.id}
                    className="event-card-mini"
                    onClick={() => navigate(`/events/${event.id}`)}
                  >
                    <div className="event-card-mini-name">{event.event_name}</div>
                    <div className="event-card-mini-meta">
                      {event.date && (
                        <span>{new Date(event.date).toLocaleDateString()}</span>
                      )}
                      {event.material_score != null && (
                        <span className="mat-score">
                          {event.material_score.toFixed(1)}
                        </span>
                      )}
                      {event.story_phase && (
                        <span className={`phase-badge phase-${event.story_phase}`}>
                          {event.story_phase}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Comparative Assessment */}
      <div className="competing-section assessment-section" ref={assessmentRef}>
        <div className="assessment-header">
          <h2><Sparkles size={18} /> Comparative Assessment</h2>
          {!assessmentGenerated && (
            <button
              className="generate-assessment-btn"
              onClick={generateAssessment}
              disabled={assessmentLoading}
            >
              {assessmentLoading ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
              Generate Assessment
            </button>
          )}
          {assessmentGenerated && !assessmentLoading && (
            <button
              className="regenerate-btn"
              onClick={generateAssessment}
            >
              Regenerate
            </button>
          )}
        </div>

        {!assessmentGenerated && !assessmentLoading && (
          <p className="assessment-placeholder">
            Click "Generate Assessment" to produce a RAG-powered comparative analysis
            interpreting the data above, with source citations.
          </p>
        )}

        {(assessmentContent || assessmentLoading) && (
          <div className="assessment-content">
            {assessmentContent ? (
              <ReactMarkdown>{assessmentContent}</ReactMarkdown>
            ) : (
              <div className="assessment-loading">
                <Loader2 size={20} className="spin" />
                <span>Analyzing sources and generating comparative assessment...</span>
              </div>
            )}
            {assessmentLoading && assessmentContent && (
              <Loader2 size={16} className="spin streaming-indicator" />
            )}
          </div>
        )}

        {/* Assessment Sources */}
        {assessmentSources.length > 0 && !assessmentLoading && (
          <div className="assessment-sources">
            <button
              className="sources-toggle-btn"
              onClick={() => setSourcesExpanded(!sourcesExpanded)}
            >
              {sourcesExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              {assessmentSources.length} Sources
            </button>

            {sourcesExpanded && (
              <div className="assessment-sources-list">
                {assessmentSources.map((src, idx) => (
                  <div key={idx} className="assessment-source-card">
                    <div className="assessment-source-header">
                      <span className="source-num">[{src.citation_number}]</span>
                      <span className="source-ttl">{src.title || 'Untitled'}</span>
                      <span className="source-scr">
                        {(src.relevance_score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="assessment-source-meta">
                      {src.source_name && <span>{src.source_name}</span>}
                      {src.date && <span>{src.date}</span>}
                      {src.initiating_country && src.recipient_country && (
                        <span>{src.initiating_country} → {src.recipient_country}</span>
                      )}
                      {src.category && <span className="src-cat">{src.category}</span>}
                    </div>
                    {src.content && (
                      <p className="assessment-source-excerpt">
                        {src.content.length > 250 ? src.content.slice(0, 250) + '...' : src.content}
                      </p>
                    )}
                    {src.doc_id && (
                      <a href={`/documents?doc_id=${src.doc_id}`} className="source-view-link">
                        <ExternalLink size={12} /> View Document
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
