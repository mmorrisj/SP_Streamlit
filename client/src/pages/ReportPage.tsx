import { useState, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell
} from 'recharts'
import { FileBarChart, Calendar, FileText, Hash, ExternalLink, Users, Building2, MapPin, Briefcase, X } from 'lucide-react'
import {
  fetchReportConfig,
  generateReportStream,
} from '../api/client'
import type {
  ReportData,
  ReportRequest,
} from '../api/client'
import './Pages.css'

const CATEGORY_COLORS: Record<string, string> = {
  'Economic': '#2563eb',
  'Diplomacy': '#7c3aed',
  'Social': '#059669',
  'Military': '#dc2626',
}

const getMaterialityColor = (score: number): string => {
  if (score >= 8) return '#dc2626'
  if (score >= 6) return '#ea580c'
  if (score >= 4) return '#ca8a04'
  if (score >= 2) return '#16a34a'
  return '#6b7280'
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return ''
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

/** Shimmer placeholder block for pending LLM text */
function ShimmerBlock({ lines = 2 }: { lines?: number }) {
  return (
    <div className="shimmer-placeholder" style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.5rem' }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="shimmer-line"
          style={{ width: i === lines - 1 ? '60%' : '100%' }}
        />
      ))}
    </div>
  )
}

export default function ReportPage() {
  const [country, setCountry] = useState<string>('China')
  const [startDate, setStartDate] = useState<string>('2025-07-01')
  const [endDate, setEndDate] = useState<string>('2025-07-30')
  const [recipient, setRecipient] = useState<string>('All')
  const [topEvents, setTopEvents] = useState<number>(10)
  const [report, setReport] = useState<ReportData | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [streamPhase, setStreamPhase] = useState('')
  const [narrativesDone, setNarrativesDone] = useState(0)
  const [narrativesTotal, setNarrativesTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const { data: config } = useQuery({
    queryKey: ['reportConfig'],
    queryFn: fetchReportConfig,
  })

  const handleGenerate = useCallback(async () => {
    setError(null)
    setIsGenerating(true)
    setStreamPhase('Loading data...')
    setNarrativesDone(0)
    setNarrativesTotal(0)
    setReport(null)

    const controller = new AbortController()
    abortRef.current = controller

    const request: ReportRequest = {
      country,
      start_date: startDate,
      end_date: endDate,
      recipient: recipient === 'All' ? 'All' : recipient,
      top_events: topEvents,
    }

    try {
      await generateReportStream(request, {
        onSkeleton: (skeleton) => {
          setReport(skeleton)
          // Count total narratives expected
          const totalEvents = skeleton.categories.reduce((s, c) => s + c.events.length, 0)
          const totalCats = skeleton.categories.length
          // events + categories + synthesis + title = totalEvents + totalCats + 1 + 1
          setNarrativesTotal(totalEvents + totalCats + 2)
          setStreamPhase('Generating narratives...')
        },

        onEventNarrative: ({ category, event_index, overview, outcomes }) => {
          setReport(prev => {
            if (!prev) return prev
            const updated = { ...prev, categories: prev.categories.map(cat => {
              if (cat.category !== category) return cat
              return {
                ...cat,
                events: cat.events.map((evt, idx) =>
                  idx === event_index ? { ...evt, overview, outcomes } : evt
                )
              }
            })}
            return updated
          })
          setNarrativesDone(n => n + 1)
        },

        onCategoryNarrative: ({ category, narrative }) => {
          setReport(prev => {
            if (!prev) return prev
            return {
              ...prev,
              categories: prev.categories.map(cat =>
                cat.category === category ? { ...cat, narrative } : cat
              )
            }
          })
          setNarrativesDone(n => n + 1)
        },

        onOverallSynthesis: ({ overall_summary }) => {
          setReport(prev => prev ? { ...prev, overall_summary } : prev)
          setNarrativesDone(n => n + 1)
          setStreamPhase('Finishing up...')
        },

        onEntitySummary: ({ entity_type_index, entity_index, summary }) => {
          setReport(prev => {
            if (!prev) return prev
            return {
              ...prev,
              entities: prev.entities.map((group, gi) => {
                if (gi !== entity_type_index) return group
                return {
                  ...group,
                  entities: group.entities.map((ent, ei) =>
                    ei === entity_index ? { ...ent, summary } : ent
                  )
                }
              })
            }
          })
        },

        onTitle: ({ title }) => {
          setReport(prev => prev ? { ...prev, title } : prev)
          setNarrativesDone(n => n + 1)
        },

        onComplete: () => {
          setIsGenerating(false)
          setStreamPhase('')
        },

        onError: (errMsg) => {
          setError(errMsg)
          setIsGenerating(false)
        },
      }, controller.signal)
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setStreamPhase('Cancelled')
        setIsGenerating(false)
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to generate report')
      setIsGenerating(false)
    }
  }, [country, startDate, endDate, recipient, topEvents])

  const handleCancel = () => {
    abortRef.current?.abort()
    abortRef.current = null
  }

  // Count total citations
  const totalCitations = report?.citations_by_event?.reduce(
    (sum, group) => sum + group.events.reduce(
      (eSum, evt) => eSum + evt.citations.length, 0
    ), 0
  ) || 0

  // Progress percentage
  const progressPct = narrativesTotal > 0 ? Math.round((narrativesDone / narrativesTotal) * 100) : 0

  return (
    <div className="page">
      <div className="page-header">
        <h1><FileBarChart size={28} style={{ marginRight: '0.5rem', verticalAlign: 'middle' }} />Publication Generator</h1>
        <p style={{ color: '#666', marginTop: '0.25rem' }}>
          Generate structured summary reports with AI narratives, metrics, and source citations
        </p>
      </div>

      {/* Configuration Panel */}
      <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
        <h3>Report Configuration</h3>
        <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', alignItems: 'end', marginTop: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#666', marginBottom: '0.4rem', fontWeight: 500 }}>
              Initiating Country
            </label>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #d1d5db', fontSize: '0.9rem', minWidth: '160px' }}
            >
              {config?.influencers.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#666', marginBottom: '0.4rem', fontWeight: 500 }}>
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              min={config?.date_range.min}
              max={config?.date_range.max}
              style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #d1d5db', fontSize: '0.9rem' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#666', marginBottom: '0.4rem', fontWeight: 500 }}>
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              min={config?.date_range.min}
              max={config?.date_range.max}
              style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #d1d5db', fontSize: '0.9rem' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#666', marginBottom: '0.4rem', fontWeight: 500 }}>
              Recipient Country
            </label>
            <select
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #d1d5db', fontSize: '0.9rem', minWidth: '180px' }}
            >
              {config?.recipients.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#666', marginBottom: '0.4rem', fontWeight: 500 }}>
              Top Events/Category
            </label>
            <input
              type="number"
              value={topEvents}
              onChange={(e) => setTopEvents(Math.max(1, Math.min(25, parseInt(e.target.value) || 10)))}
              min={1}
              max={25}
              style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #d1d5db', fontSize: '0.9rem', width: '80px' }}
            />
          </div>

          <button
            onClick={isGenerating ? handleCancel : handleGenerate}
            style={{
              padding: '0.5rem 1.5rem',
              borderRadius: '6px',
              border: 'none',
              background: isGenerating ? '#dc2626' : '#1a365d',
              color: 'white',
              fontSize: '0.9rem',
              fontWeight: 600,
              cursor: 'pointer',
              height: '38px',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
            }}
          >
            {isGenerating ? (
              <><X size={16} /> Cancel</>
            ) : (
              'Generate Report'
            )}
          </button>
        </div>
      </div>

      {/* Streaming Progress Bar */}
      {isGenerating && (
        <div className="chart-card" style={{ marginBottom: '1.5rem', padding: '1rem 1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.9rem', color: '#333', fontWeight: 500 }}>{streamPhase}</span>
            {narrativesTotal > 0 && (
              <span style={{ fontSize: '0.8rem', color: '#666' }}>
                {narrativesDone}/{narrativesTotal} ({progressPct}%)
              </span>
            )}
          </div>
          <div style={{
            width: '100%', height: '6px', background: '#e2e8f0',
            borderRadius: '3px', overflow: 'hidden'
          }}>
            {narrativesTotal > 0 ? (
              <div style={{
                width: `${progressPct}%`,
                height: '100%',
                background: '#1a365d',
                borderRadius: '3px',
                transition: 'width 0.3s ease',
              }} />
            ) : (
              <div className="report-progress-bar" />
            )}
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="chart-card" style={{ borderLeft: '4px solid #dc2626', padding: '1.5rem', marginBottom: '1.5rem' }}>
          <p style={{ color: '#dc2626', fontWeight: 600 }}>Failed to generate report</p>
          <p style={{ color: '#666', marginTop: '0.5rem' }}>{error}</p>
        </div>
      )}

      {/* Report Display — shows as soon as skeleton arrives */}
      {report && (
        <>
          {/* Report Header */}
          <div className="chart-card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid #1a365d' }}>
            <h2 style={{ color: '#1a365d', marginBottom: '0.5rem' }}>{report.title}</h2>
            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', fontSize: '0.9rem', color: '#666' }}>
              <span><strong>Country:</strong> {report.country}</span>
              <span><strong>Period:</strong> {formatDate(report.period_start)} to {formatDate(report.period_end)}</span>
              <span><strong>Recipient:</strong> {report.recipient_filter}</span>
              <span><strong>Generated:</strong> {new Date(report.generated_at).toLocaleString()}</span>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="stats-grid" style={{ marginBottom: '1.5rem' }}>
            <div className="stat-card">
              <FileText size={24} style={{ color: '#1a365d' }} />
              <div className="stat-value">{report.metrics.total_documents.toLocaleString()}</div>
              <div className="stat-label">Documents</div>
            </div>
            <div className="stat-card">
              <Calendar size={24} style={{ color: '#7c3aed' }} />
              <div className="stat-value">{report.metrics.total_events}</div>
              <div className="stat-label">Key Events</div>
            </div>
            <div className="stat-card">
              <Hash size={24} style={{ color: '#059669' }} />
              <div className="stat-value">{totalCitations}</div>
              <div className="stat-label">Citations</div>
            </div>
          </div>

          {/* Strategic Overview */}
          <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
            <h3>Strategic Overview</h3>
            {report.overall_summary ? (
              <div style={{ lineHeight: 1.8, color: '#333', marginTop: '0.75rem' }}>
                {report.overall_summary.split('\n\n').filter(p => p.trim()).map((paragraph, i) => (
                  <p key={i} style={{ marginBottom: '1rem' }}>{paragraph.trim()}</p>
                ))}
              </div>
            ) : (
              <ShimmerBlock lines={4} />
            )}
          </div>

          {/* Key Events by Category */}
          {report.categories.map((cat) => (
            <div key={cat.category} className="chart-card" style={{ marginBottom: '1.5rem' }}>
              <h3 style={{ color: CATEGORY_COLORS[cat.category] || '#1a365d', borderBottom: `2px solid ${CATEGORY_COLORS[cat.category] || '#1a365d'}`, paddingBottom: '0.5rem' }}>
                {cat.category}
              </h3>

              {/* Category narrative */}
              {cat.narrative ? (
                <p style={{ lineHeight: 1.7, marginTop: '1rem', marginBottom: '1.5rem', color: '#444' }}>
                  {cat.narrative}
                </p>
              ) : (
                <ShimmerBlock lines={2} />
              )}

              {/* Event cards */}
              <div style={{ display: 'grid', gap: '1rem' }}>
                {cat.events.map((event, i) => (
                  <div key={i} className="report-event-card" style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '8px',
                    padding: '1.25rem',
                    borderLeft: `4px solid ${CATEGORY_COLORS[cat.category] || '#1a365d'}`
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                      <div>
                        <h4 style={{ margin: 0, fontSize: '1rem' }}>{event.event_name}</h4>
                        <p style={{ fontSize: '0.8rem', color: '#666', marginTop: '0.25rem' }}>
                          {formatDate(event.first_mention_date)} to {formatDate(event.last_mention_date)} | {event.article_count} articles
                        </p>
                      </div>
                      <span className="materiality-badge" style={{
                        background: getMaterialityColor(event.materiality_score),
                        padding: '0.2rem 0.7rem',
                        borderRadius: '12px',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        color: 'white',
                        whiteSpace: 'nowrap'
                      }}>
                        {event.materiality_score.toFixed(1)}/10
                      </span>
                    </div>

                    {event.overview ? (
                      <div style={{ marginTop: '0.75rem' }}>
                        <strong style={{ fontSize: '0.85rem' }}>Overview:</strong>
                        <span style={{ fontSize: '0.9rem', marginLeft: '0.4rem' }}>{event.overview}</span>
                      </div>
                    ) : isGenerating ? (
                      <div style={{ marginTop: '0.75rem' }}>
                        <strong style={{ fontSize: '0.85rem' }}>Overview:</strong>
                        <ShimmerBlock lines={1} />
                      </div>
                    ) : null}

                    {event.outcomes ? (
                      <div style={{ marginTop: '0.5rem' }}>
                        <strong style={{ fontSize: '0.85rem' }}>Outcomes:</strong>
                        <span style={{ fontSize: '0.9rem', marginLeft: '0.4rem' }}>{event.outcomes}</span>
                      </div>
                    ) : isGenerating ? (
                      <div style={{ marginTop: '0.5rem' }}>
                        <strong style={{ fontSize: '0.85rem' }}>Outcomes:</strong>
                        <ShimmerBlock lines={1} />
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Key Entities */}
          {report.entities && report.entities.length > 0 && (
            <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
              <h3>Key Entities</h3>

              {report.entities.map((group) => {
                const EntityIcon = group.entity_type === 'person' ? Users
                  : group.entity_type === 'organization' ? Building2
                  : group.entity_type === 'company' ? Briefcase
                  : group.entity_type === 'location' ? MapPin
                  : Users

                const typeColor = group.entity_type === 'person' ? '#7c3aed'
                  : group.entity_type === 'organization' ? '#2563eb'
                  : group.entity_type === 'company' ? '#059669'
                  : group.entity_type === 'location' ? '#ea580c'
                  : '#6b7280'

                return (
                  <div key={group.entity_type} style={{ marginTop: '1.5rem' }}>
                    <h4 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: typeColor, marginBottom: '0.75rem' }}>
                      <EntityIcon size={18} />
                      {group.type_label}
                    </h4>

                    <div style={{ display: 'grid', gap: '0.75rem' }}>
                      {group.entities.map((entity, idx) => (
                        <div key={idx} style={{
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          padding: '1rem 1.25rem',
                          borderLeft: `3px solid ${typeColor}`
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                            <div>
                              <h5 style={{ margin: 0, fontSize: '0.95rem' }}>{entity.name}</h5>
                              <p style={{ fontSize: '0.75rem', color: '#888', margin: '0.2rem 0 0' }}>
                                {entity.role} | {entity.document_count} documents | {formatDate(entity.first_seen)} to {formatDate(entity.last_seen)}
                              </p>
                            </div>
                            {entity.citation_numbers.length > 0 && (
                              <span style={{ fontSize: '0.7rem', color: '#666', whiteSpace: 'nowrap' }}>
                                Sources: [{entity.citation_numbers.join(', ')}]
                              </span>
                            )}
                          </div>
                          {entity.summary ? (
                            <p style={{ marginTop: '0.6rem', fontSize: '0.85rem', lineHeight: 1.6, color: '#444' }}>
                              {entity.summary}
                            </p>
                          ) : isGenerating ? (
                            <ShimmerBlock lines={2} />
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* Metrics Dashboard — 2x2 Quadrant */}
          <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
            <h3>Metrics Dashboard</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem', marginTop: '1rem' }}>
              {/* Q1: Category Distribution */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0.75rem' }}>
                <h4 style={{ fontSize: '0.85rem', margin: '0 0 0.5rem' }}>Category Distribution</h4>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={report.metrics.category_distribution} layout="vertical" margin={{ left: 0, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis dataKey="category" type="category" width={70} tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#1a365d">
                      {report.metrics.category_distribution.map((entry) => (
                        <Cell key={entry.category} fill={CATEGORY_COLORS[entry.category] || '#1a365d'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Q2: Materiality Histogram */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0.75rem' }}>
                <h4 style={{ fontSize: '0.85rem', margin: '0 0 0.5rem' }}>Materiality Score Distribution</h4>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={report.metrics.materiality_histogram.filter(d => d.count > 0)} margin={{ right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="bin" tick={{ fontSize: 10 }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#4a6fa5" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Q3: Top Recipient Countries */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0.75rem' }}>
                <h4 style={{ fontSize: '0.85rem', margin: '0 0 0.5rem' }}>Top Recipient Countries</h4>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={report.metrics.recipient_distribution.slice(0, 8)} layout="vertical" margin={{ left: 0, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis dataKey="recipient" type="category" width={90} tick={{ fontSize: 9 }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#059669" radius={[0, 3, 3, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Q4: Top Subcategories */}
              {report.metrics.subcategory_distribution.length > 0 && (
                <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0.75rem' }}>
                  <h4 style={{ fontSize: '0.85rem', margin: '0 0 0.5rem' }}>Top Subcategories</h4>
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={report.metrics.subcategory_distribution.slice(0, 8)} layout="vertical" margin={{ left: 0, right: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" tick={{ fontSize: 10 }} />
                      <YAxis dataKey="subcategory" type="category" width={120} tick={{ fontSize: 9 }} />
                      <Tooltip />
                      <Bar dataKey="count" fill="#6366f1" radius={[0, 3, 3, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          {/* Citations (End Notes) - Grouped by Category and Event */}
          <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
            <h3>End Notes ({totalCitations} citations)</h3>

            {report.citations_by_event.map((group) => (
              <div key={group.category} style={{ marginTop: '1.5rem' }}>
                <h4 style={{
                  color: CATEGORY_COLORS[group.category] || '#1a365d',
                  borderBottom: `1px solid ${CATEGORY_COLORS[group.category] || '#e2e8f0'}`,
                  paddingBottom: '0.4rem',
                  marginBottom: '1rem'
                }}>
                  {group.category}
                </h4>

                {group.events.map((evt, evtIdx) => (
                  <div key={evtIdx} style={{ marginBottom: '1.25rem', marginLeft: '1rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                      <h5 style={{ margin: 0, fontSize: '0.9rem' }}>{evt.event_name}</h5>
                      <span style={{
                        background: getMaterialityColor(evt.materiality_score),
                        padding: '0.1rem 0.5rem',
                        borderRadius: '10px',
                        fontSize: '0.7rem',
                        fontWeight: 600,
                        color: 'white'
                      }}>
                        {evt.materiality_score.toFixed(1)}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: '#888' }}>{evt.date_range}</span>
                    </div>

                    <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                      {evt.citations.map((citation) => (
                        <div key={citation.citation_number} style={{
                          padding: '0.5rem 0',
                          borderBottom: '1px solid #f5f5f5',
                          display: 'flex',
                          gap: '0.5rem',
                          fontSize: '0.8rem',
                          marginLeft: '0.5rem'
                        }}>
                          <span style={{ fontWeight: 700, color: '#1a365d', minWidth: '2.5rem' }}>
                            [{citation.citation_number}]
                          </span>
                          <div style={{ flex: 1 }}>
                            <span style={{ fontWeight: 500 }}>{citation.headline}</span>
                            <span style={{ color: '#888', marginLeft: '0.5rem' }}>
                              {citation.source_name}{citation.published_date ? ` | ${formatDate(citation.published_date)}` : ''}
                            </span>
                            {citation.repo_hyperlink && (
                              <a
                                href={citation.repo_hyperlink}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ marginLeft: '0.5rem', color: '#2563eb', fontSize: '0.75rem' }}
                              >
                                <ExternalLink size={12} style={{ verticalAlign: 'middle' }} /> ATOM
                              </a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
