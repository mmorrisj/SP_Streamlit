import { useState, useEffect, useRef, useCallback } from 'react'
import { X, FileBarChart, Download, Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell
} from 'recharts'
import { generateReportStream, exportReportToDocx } from '../api/client'
import type { ReportData, ReportRequest } from '../api/client'
import './ChatReportModal.css'

interface ChatReportModalProps {
  isOpen: boolean
  onClose: () => void
  inferredFilters: {
    influencer?: string
    recipient?: string
    category?: string
    start_date?: string
    end_date?: string
  }
  query: string
}

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

function ShimmerBlock({ lines = 2 }: { lines?: number }) {
  return (
    <div className="shimmer-placeholder">
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

function getDefaultDates() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 30)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  return { start: fmt(start), end: fmt(end) }
}

export default function ChatReportModal({ isOpen, onClose, inferredFilters, query }: ChatReportModalProps) {
  const defaults = getDefaultDates()

  // Use inferred filters or defaults
  const [country, setCountry] = useState<string>(inferredFilters.influencer || 'China')
  const [startDate, setStartDate] = useState<string>(inferredFilters.start_date || defaults.start)
  const [endDate, setEndDate] = useState<string>(inferredFilters.end_date || defaults.end)
  const [recipient, setRecipient] = useState<string>(inferredFilters.recipient || 'All')

  const [report, setReport] = useState<ReportData | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [streamPhase, setStreamPhase] = useState('')
  const [narrativesDone, setNarrativesDone] = useState(0)
  const [narrativesTotal, setNarrativesTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [isExporting, setIsExporting] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())
  const abortRef = useRef<AbortController | null>(null)

  // Update filters when modal opens with new inferred values
  useEffect(() => {
    if (isOpen) {
      setCountry(inferredFilters.influencer || 'China')
      setStartDate(inferredFilters.start_date || defaults.start)
      setEndDate(inferredFilters.end_date || defaults.end)
      setRecipient(inferredFilters.recipient || 'All')
      setReport(null)
      setError(null)
    }
  }, [isOpen, inferredFilters])

  const handleGenerate = useCallback(async () => {
    setError(null)
    setIsGenerating(true)
    setStreamPhase('Loading data...')
    setNarrativesDone(0)
    setNarrativesTotal(0)
    setReport(null)
    setExpandedCategories(new Set())

    const controller = new AbortController()
    abortRef.current = controller

    const request: ReportRequest = {
      country,
      start_date: startDate,
      end_date: endDate,
      recipient: recipient === 'All' ? 'All' : recipient,
      top_events: 10,
      model: 'gpt-4o-mini',
    }

    try {
      await generateReportStream(request, {
        onSkeleton: (skeleton) => {
          setReport(skeleton)
          const totalEvents = skeleton.categories.reduce((s, c) => s + c.events.length, 0)
          const totalCats = skeleton.categories.length
          setNarrativesTotal(totalEvents + totalCats + 2)
          setStreamPhase('Generating narratives...')
        },

        onEventNarrative: ({ category, event_index, overview, outcomes }) => {
          setReport(prev => {
            if (!prev) return prev
            return {
              ...prev,
              categories: prev.categories.map(cat => {
                if (cat.category !== category) return cat
                return {
                  ...cat,
                  events: cat.events.map((evt, idx) =>
                    idx === event_index ? { ...evt, overview, outcomes } : evt
                  )
                }
              })
            }
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
        },

        onEntitySummary: ({ entity_type_index, entity_index, summary }) => {
          setReport(prev => {
            if (!prev || !prev.entities) return prev
            const newEntities = [...prev.entities]
            if (newEntities[entity_type_index]?.entities?.[entity_index]) {
              newEntities[entity_type_index] = {
                ...newEntities[entity_type_index],
                entities: newEntities[entity_type_index].entities.map((e, i) =>
                  i === entity_index ? { ...e, summary } : e
                )
              }
            }
            return { ...prev, entities: newEntities }
          })
        },

        onTitle: ({ title }) => {
          setReport(prev => prev ? { ...prev, title } : prev)
          setNarrativesDone(n => n + 1)
        },

        onComplete: () => {
          setIsGenerating(false)
          setStreamPhase('Complete')
        },

        onError: (errorMessage) => {
          setError(errorMessage)
          setIsGenerating(false)
        },
      }, controller.signal)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError((err as Error).message)
      }
      setIsGenerating(false)
    }
  }, [country, startDate, endDate, recipient])

  const handleExport = async () => {
    if (!report) return
    setIsExporting(true)
    try {
      await exportReportToDocx(report)
    } catch (err) {
      console.error('Export failed:', err)
    }
    setIsExporting(false)
  }

  const handleCancel = () => {
    if (abortRef.current) {
      abortRef.current.abort()
    }
    setIsGenerating(false)
  }

  const toggleCategory = (category: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev)
      if (next.has(category)) {
        next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }

  if (!isOpen) return null

  const progressPercent = narrativesTotal > 0 ? Math.round((narrativesDone / narrativesTotal) * 100) : 0

  return (
    <div className="chat-report-modal-overlay" onClick={onClose}>
      <div className="chat-report-modal" onClick={e => e.stopPropagation()}>
        <div className="chat-report-header">
          <div className="chat-report-title">
            <FileBarChart size={20} />
            <h2>Generate Full Report</h2>
          </div>
          <button className="chat-report-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        {/* Configuration Panel */}
        {!report && !isGenerating && (
          <div className="chat-report-config">
            <p className="chat-report-intro">
              Generate a comprehensive report based on your query. The report will include key events,
              metrics, entity analysis, and LLM-generated narratives.
            </p>

            <div className="chat-report-query">
              <strong>Based on:</strong> "{query.length > 100 ? query.slice(0, 100) + '...' : query}"
            </div>

            <div className="chat-report-filters">
              <div className="filter-item">
                <label>Influencer Country</label>
                <select value={country} onChange={e => setCountry(e.target.value)}>
                  <option value="China">China</option>
                  <option value="Russia">Russia</option>
                  <option value="Iran">Iran</option>
                  <option value="Turkey">Turkey</option>
                  <option value="United States">United States</option>
                </select>
              </div>

              <div className="filter-item">
                <label>Recipient (optional)</label>
                <select value={recipient} onChange={e => setRecipient(e.target.value)}>
                  <option value="All">All Recipients</option>
                  <option value="Egypt">Egypt</option>
                  <option value="Saudi Arabia">Saudi Arabia</option>
                  <option value="United Arab Emirates">UAE</option>
                  <option value="Qatar">Qatar</option>
                  <option value="Israel">Israel</option>
                  <option value="Syria">Syria</option>
                  <option value="Iraq">Iraq</option>
                  <option value="Iran">Iran</option>
                  <option value="Turkey">Turkey</option>
                </select>
              </div>

              <div className="filter-item">
                <label>Start Date</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={e => setStartDate(e.target.value)}
                />
              </div>

              <div className="filter-item">
                <label>End Date</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={e => setEndDate(e.target.value)}
                />
              </div>
            </div>

            <button className="generate-report-btn" onClick={handleGenerate}>
              <FileBarChart size={18} />
              Generate Report
            </button>
          </div>
        )}

        {/* Generation Progress */}
        {isGenerating && (
          <div className="chat-report-progress">
            <div className="progress-header">
              <Loader2 className="spin" size={20} />
              <span>{streamPhase}</span>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
            </div>
            <div className="progress-stats">
              {narrativesDone} / {narrativesTotal} narratives generated ({progressPercent}%)
            </div>
            <button className="cancel-btn" onClick={handleCancel}>Cancel</button>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="chat-report-error">
            <p>Error: {error}</p>
            <button onClick={handleGenerate}>Try Again</button>
          </div>
        )}

        {/* Report Content */}
        {report && !isGenerating && (
          <div className="chat-report-content">
            <div className="report-header-section">
              <h3>{report.title || 'Report'}</h3>
              <div className="report-meta">
                <span>{report.period_start} to {report.period_end}</span>
                {report.recipient_filter !== 'All' && (
                  <span className="recipient-badge">{report.recipient_filter}</span>
                )}
              </div>
              <button
                className="export-btn"
                onClick={handleExport}
                disabled={isExporting}
              >
                {isExporting ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
                Export to Word
              </button>
            </div>

            {/* Overall Summary */}
            {report.overall_summary && (
              <div className="report-section">
                <h4>Executive Summary</h4>
                <p className="summary-text">{report.overall_summary}</p>
              </div>
            )}

            {/* Metrics Overview */}
            {report.metrics && (
              <div className="report-section metrics-section">
                <h4>Key Metrics</h4>
                <div className="metrics-grid">
                  <div className="metric-card">
                    <span className="metric-value">{report.metrics.total_documents}</span>
                    <span className="metric-label">Documents</span>
                  </div>
                  <div className="metric-card">
                    <span className="metric-value">{report.metrics.total_events}</span>
                    <span className="metric-label">Events</span>
                  </div>
                </div>

                {/* Category Distribution Chart */}
                {report.metrics.category_distribution.length > 0 && (
                  <div className="chart-container">
                    <h5>Category Distribution</h5>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={report.metrics.category_distribution} layout="vertical">
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis type="number" />
                        <YAxis dataKey="category" type="category" width={80} tick={{ fontSize: 12 }} />
                        <Tooltip />
                        <Bar dataKey="count" name="Documents">
                          {report.metrics.category_distribution.map((entry, index) => (
                            <Cell
                              key={`cell-${index}`}
                              fill={CATEGORY_COLORS[entry.category] || '#6b7280'}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            )}

            {/* Categories with Events */}
            <div className="report-section">
              <h4>Events by Category</h4>
              {report.categories.map(cat => (
                <div key={cat.category} className="category-section">
                  <button
                    className="category-header"
                    onClick={() => toggleCategory(cat.category)}
                  >
                    <span
                      className="category-color-dot"
                      style={{ background: CATEGORY_COLORS[cat.category] || '#6b7280' }}
                    />
                    <span className="category-name">{cat.category}</span>
                    <span className="event-count">{cat.events.length} events</span>
                    {expandedCategories.has(cat.category) ?
                      <ChevronUp size={18} /> : <ChevronDown size={18} />}
                  </button>

                  {expandedCategories.has(cat.category) && (
                    <div className="category-content">
                      {cat.narrative && (
                        <p className="category-narrative">{cat.narrative}</p>
                      )}
                      <div className="events-list">
                        {cat.events.map((evt, idx) => (
                          <div key={idx} className="event-card">
                            <div className="event-header">
                              <span
                                className="materiality-badge"
                                style={{ background: getMaterialityColor(evt.materiality_score) }}
                              >
                                {evt.materiality_score.toFixed(1)}
                              </span>
                              <span className="event-name">{evt.event_name}</span>
                            </div>
                            <div className="event-meta">
                              <span>{evt.first_mention_date} - {evt.last_mention_date}</span>
                              <span>{evt.article_count} articles</span>
                            </div>
                            {evt.overview ? (
                              <p className="event-overview">{evt.overview}</p>
                            ) : (
                              <ShimmerBlock lines={2} />
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
