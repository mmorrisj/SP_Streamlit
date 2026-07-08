import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, LineChart, Line, Legend,
  ScatterChart, Scatter, ZAxis, ReferenceLine, LabelList,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis
} from 'recharts'
import { FileBarChart, ExternalLink, Users, Building2, MapPin, Briefcase, X, Download } from 'lucide-react'
import {
  fetchReportConfig,
  exportReportToDocx,
  validateReportStream,
} from '../api/client'
import type {
  ReportRequest,
  ValidationStatus,
  SectionValidation,
  ReportMetrics,
} from '../api/client'
import { useReportGeneration } from '../contexts/ReportGenerationContext'
import { ValidationIndicator } from '../components/ValidationIndicator'
import './Pages.css'

const CATEGORY_COLORS: Record<string, string> = {
  'Economic': '#2563eb',
  'Diplomacy': '#7c3aed',
  'Social': '#059669',
  'Military': '#dc2626',
}

const PILLARS = ['Economic', 'Social', 'Military', 'Diplomacy']

/** Influence Signature — category mix as a radar; overlays raw vs. corroborated share so
 *  the gap reveals where reporting is self-generated (state-media projection). */
function SignatureRadar({ metrics }: { metrics: ReportMetrics }) {
  const cats = metrics.category_distribution
  const totalRaw = cats.reduce((s, c) => s + c.count, 0)
  const hasCorr = cats.some(c => c.corroborated != null)
  const totalCorr = cats.reduce((s, c) => s + (c.corroborated ?? c.count), 0)
  const data = PILLARS.map(p => {
    const row = cats.find(c => c.category === p)
    const raw = row?.count ?? 0
    const corr = row?.corroborated ?? raw
    return {
      category: p,
      raw: totalRaw ? +(100 * raw / totalRaw).toFixed(1) : 0,
      corroborated: totalCorr ? +(100 * corr / totalCorr).toFixed(1) : 0,
    }
  })
  return (
    <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
      <h3>Influence Signature</h3>
      <p style={{ fontSize: '0.78rem', color: '#64748b', margin: '0.25rem 0 0.5rem' }}>
        Share of effort across the four instruments.{hasCorr ? ' The corroborated profile strips the initiator’s own state-media coverage — the gap shows where reporting is self-generated.' : ''}
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <RadarChart data={data} outerRadius="72%">
          <PolarGrid />
          <PolarAngleAxis dataKey="category" tick={{ fontSize: 12 }} />
          <PolarRadiusAxis angle={90} tick={{ fontSize: 9 }} />
          {hasCorr && <Radar name="Raw %" dataKey="raw" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.15} />}
          <Radar name={hasCorr ? 'Corroborated %' : 'Share %'} dataKey="corroborated" stroke="#1a365d" fill="#1a365d" fillOpacity={0.35} />
          <Legend />
          <Tooltip formatter={(v) => `${v}%`} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
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

function getDefaultDates() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 30)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  return { start: fmt(start), end: fmt(end) }
}

export default function ReportPage() {
  const defaults = getDefaultDates()
  const [country, setCountry] = useState<string>('China')
  const [startDate, setStartDate] = useState<string>(defaults.start)
  const [endDate, setEndDate] = useState<string>(defaults.end)
  const [recipient, setRecipient] = useState<string>('All')
  const [topEvents, setTopEvents] = useState<number>(10)
  const [selectedModel, setSelectedModel] = useState<string>('gpt-4o-mini')
  const [includeEvents, setIncludeEvents] = useState(true)
  const [includeEntities, setIncludeEntities] = useState(true)
  const [includeMetrics, setIncludeMetrics] = useState(true)
  const [includePersons, setIncludePersons] = useState(true)
  const [isExporting, setIsExporting] = useState(false)
  // Provenance view: 'corroborated' strips the initiator's own state-media coverage
  const [provMode, setProvMode] = useState<'raw' | 'corroborated'>('corroborated')

  // Report generation from context (persists across navigation)
  const {
    status,
    report,
    request: activeRequest,
    error,
    streamPhase,
    narrativesDone,
    narrativesTotal,
    progressPct,
    startGeneration,
    cancelGeneration,
    dismissError,
  } = useReportGeneration()

  const isGenerating = status === 'generating'

  // Sync config inputs from active/completed request when returning to this page
  useEffect(() => {
    if (activeRequest && status !== 'idle') {
      setCountry(activeRequest.country)
      setStartDate(activeRequest.start_date)
      setEndDate(activeRequest.end_date)
      setRecipient(activeRequest.recipient || 'All')
      setTopEvents(activeRequest.top_events || 10)
      setSelectedModel(activeRequest.model || 'gpt-4o-mini')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Only on mount

  // Local error for export/validation failures (separate from context's generation error)
  const [localError, setLocalError] = useState<string | null>(null)

  // Validation state (local — only relevant on this page)
  const [isValidating, setIsValidating] = useState(false)
  const [validationStatus, setValidationStatus] = useState<Record<string, SectionValidation>>({})
  const [validationProgress, setValidationProgress] = useState({ done: 0, total: 0 })
  const [overallValidationStatus, setOverallValidationStatus] = useState<ValidationStatus | null>(null)
  const validationAbortRef = useRef<AbortController | null>(null)

  const { data: config } = useQuery({
    queryKey: ['reportConfig'],
    queryFn: fetchReportConfig,
  })

  const handleGenerate = useCallback(() => {
    const request: ReportRequest = {
      country,
      start_date: startDate,
      end_date: endDate,
      recipient: recipient === 'All' ? 'All' : recipient,
      top_events: topEvents,
      model: selectedModel,
      include_events: includeEvents,
      include_entities: includeEntities,
      include_metrics: includeMetrics,
      include_persons: includePersons,
    }
    startGeneration(request)
  }, [country, startDate, endDate, recipient, topEvents, selectedModel, includeEvents, includeEntities, includeMetrics, includePersons, startGeneration])

  const handleQuarterlyGenerate = useCallback(() => {
    // Auto-calculate 3-month range ending at endDate
    const end = new Date(endDate + 'T00:00:00')
    const start = new Date(end)
    start.setMonth(start.getMonth() - 3)
    const fmt = (d: Date) => d.toISOString().slice(0, 10)
    const qStart = fmt(start)
    const qEnd = fmt(end)
    setStartDate(qStart)
    const request: ReportRequest = {
      country,
      start_date: qStart,
      end_date: qEnd,
      recipient: recipient === 'All' ? 'All' : recipient,
      top_events: topEvents,
      model: selectedModel,
      quarterly: true,
      include_events: includeEvents,
      include_entities: includeEntities,
      include_metrics: includeMetrics,
      include_persons: includePersons,
    }
    startGeneration(request)
  }, [country, endDate, recipient, topEvents, selectedModel, includeEvents, includeEntities, includeMetrics, includePersons, startGeneration])

  const handleCancel = () => {
    cancelGeneration()
  }

  const handleExport = async () => {
    if (!report) return
    setIsExporting(true)
    try {
      await exportReportToDocx(report)
    } catch (e: any) {
      setLocalError(`Export failed: ${e.message}`)
    } finally {
      setIsExporting(false)
    }
  }

  const handleValidation = useCallback(async () => {
    if (!report) return
    setIsValidating(true)
    setValidationStatus({})
    setValidationProgress({ done: 0, total: 0 })
    setOverallValidationStatus(null)

    const controller = new AbortController()
    validationAbortRef.current = controller

    try {
      await validateReportStream(report, {
        onStart: ({ total_sections }) => {
          setValidationProgress({ done: 0, total: total_sections })
        },
        onSectionValidated: (section) => {
          setValidationStatus(prev => ({
            ...prev,
            [section.section_id]: section
          }))
          setValidationProgress(prev => ({ ...prev, done: prev.done + 1 }))
        },
        onComplete: ({ overall_status }) => {
          setOverallValidationStatus(overall_status)
          setIsValidating(false)
        },
        onError: (errMsg) => {
          setLocalError(`Validation failed: ${errMsg}`)
          setIsValidating(false)
        },
      }, selectedModel, controller.signal)
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setIsValidating(false)
        return
      }
      setLocalError(err instanceof Error ? err.message : 'Validation failed')
      setIsValidating(false)
    }
  }, [report, selectedModel])

  const handleCancelValidation = () => {
    validationAbortRef.current?.abort()
    validationAbortRef.current = null
  }

  const getValidationForSection = (sectionId: string): SectionValidation | undefined => {
    return validationStatus[sectionId]
  }

  // Count total citations
  const totalCitations = report?.citations_by_event?.reduce(
    (sum, group) => sum + group.events.reduce(
      (eSum, evt) => eSum + evt.citations.length, 0
    ), 0
  ) || 0

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

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#666', marginBottom: '0.4rem', fontWeight: 500 }}>
              LLM Model
            </label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #d1d5db', fontSize: '0.9rem', minWidth: '140px' }}
            >
              <option value="gpt-4o-mini">GPT-4o Mini</option>
              <option value="gpt-4.1-mini">GPT-4.1 Mini</option>
              <option value="gpt-4.1">GPT-4.1</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.8rem', color: '#666', fontWeight: 500 }}>Sections:</span>
            {([
              ['Key Events', includeEvents, setIncludeEvents],
              ['Entities', includeEntities, setIncludeEntities],
              ['Persons', includePersons, setIncludePersons],
              ['Metrics', includeMetrics, setIncludeMetrics],
            ] as [string, boolean, (v: boolean) => void][]).map(([label, checked, setter]) => (
              <label key={label} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', color: '#374151', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => setter(e.target.checked)}
                  style={{ accentColor: '#1a365d' }}
                />
                {label}
              </label>
            ))}
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

          {!isGenerating && (
            <button
              onClick={handleQuarterlyGenerate}
              title="Generates a 3-month report ending at the selected End Date, with historical context from the prior 3 months"
              style={{
                padding: '0.5rem 1.5rem',
                borderRadius: '6px',
                border: '1px solid #7c3aed',
                background: '#f5f3ff',
                color: '#7c3aed',
                fontSize: '0.9rem',
                fontWeight: 600,
                cursor: 'pointer',
                height: '38px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
              }}
            >
              Quarterly Report
            </button>
          )}

          {report && !isGenerating && (
            <>
              <button
                onClick={isValidating ? handleCancelValidation : handleValidation}
                disabled={isExporting}
                style={{
                  padding: '0.5rem 1.5rem',
                  borderRadius: '6px',
                  border: '1px solid #d1d5db',
                  background: isValidating ? '#fef3c7' : overallValidationStatus === 'green' ? '#dcfce7' : overallValidationStatus === 'yellow' ? '#fef9c3' : overallValidationStatus === 'red' ? '#fee2e2' : 'white',
                  color: isValidating ? '#d97706' : overallValidationStatus === 'green' ? '#166534' : overallValidationStatus === 'yellow' ? '#854d0e' : overallValidationStatus === 'red' ? '#991b1b' : '#1a365d',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  cursor: isExporting ? 'not-allowed' : 'pointer',
                  height: '38px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                {isValidating ? (
                  <><X size={16} /> Cancel</>
                ) : overallValidationStatus ? (
                  `Re-validate Sources`
                ) : (
                  'Validate Sources'
                )}
              </button>
              <button
                onClick={handleExport}
                disabled={isExporting}
                style={{
                  padding: '0.5rem 1.5rem',
                  borderRadius: '6px',
                  border: '1px solid #d1d5db',
                  background: isExporting ? '#e5e7eb' : 'white',
                  color: isExporting ? '#9ca3af' : '#1a365d',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  cursor: isExporting ? 'not-allowed' : 'pointer',
                  height: '38px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <Download size={16} />
                {isExporting ? 'Exporting...' : 'Export to Word'}
              </button>
            </>
          )}
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

      {/* Validation Progress Bar */}
      {isValidating && (
        <div className="chart-card" style={{ marginBottom: '1.5rem', padding: '1rem 1.5rem', borderLeft: '4px solid #eab308' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.9rem', color: '#333', fontWeight: 500 }}>Validating sources...</span>
            {validationProgress.total > 0 && (
              <span style={{ fontSize: '0.8rem', color: '#666' }}>
                {validationProgress.done}/{validationProgress.total} ({Math.round((validationProgress.done / validationProgress.total) * 100)}%)
              </span>
            )}
          </div>
          <div style={{
            width: '100%', height: '6px', background: '#e2e8f0',
            borderRadius: '3px', overflow: 'hidden'
          }}>
            <div style={{
              width: `${validationProgress.total > 0 ? (validationProgress.done / validationProgress.total) * 100 : 0}%`,
              height: '100%',
              background: '#eab308',
              borderRadius: '3px',
              transition: 'width 0.3s ease',
            }} />
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="chart-card" style={{ borderLeft: '4px solid #dc2626', padding: '1.5rem', marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <p style={{ color: '#dc2626', fontWeight: 600 }}>Failed to generate report</p>
            <p style={{ color: '#666', marginTop: '0.5rem' }}>{error}</p>
          </div>
          <button
            onClick={dismissError}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: '0.25rem' }}
            title="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {localError && (
        <div className="chart-card" style={{ borderLeft: '4px solid #dc2626', padding: '1.5rem', marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <p style={{ color: '#dc2626', fontWeight: 600 }}>Error</p>
            <p style={{ color: '#666', marginTop: '0.5rem' }}>{localError}</p>
          </div>
          <button
            onClick={() => setLocalError(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: '0.25rem' }}
            title="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Report Display — shows as soon as skeleton arrives */}
      {report && (
        <>
          {/* Report Header — compact */}
          <div className="chart-card" style={{ marginBottom: '1rem', borderLeft: '4px solid #1a365d', padding: '0.75rem 1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h2 style={{ color: '#1a365d', margin: 0, fontSize: '1.15rem' }}>{report.title}</h2>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                Generated {new Date(report.generated_at).toLocaleDateString()}
              </span>
            </div>
            <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap', fontSize: '0.8rem', color: '#666', marginTop: '0.35rem' }}>
              <span>{report.country}</span>
              <span>{formatDate(report.period_start)} – {formatDate(report.period_end)}</span>
              {report.recipient_filter !== 'All' && <span>Recipient: {report.recipient_filter}</span>}
              <span style={{ marginLeft: 'auto', display: 'flex', gap: '1rem' }}>
                <span><strong>{report.metrics.total_documents.toLocaleString()}</strong> docs</span>
                <span><strong>{report.metrics.total_events}</strong> events</span>
                <span><strong>{totalCitations}</strong> citations</span>
              </span>
            </div>
          </div>

          {/* Strategic Overview */}
          <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              Strategic Overview
              {getValidationForSection('overall_summary') && (
                <ValidationIndicator
                  status={getValidationForSection('overall_summary')!.status as ValidationStatus}
                  issues={getValidationForSection('overall_summary')!.issues}
                  summary={getValidationForSection('overall_summary')!.summary}
                  claimsValidated={getValidationForSection('overall_summary')!.claims_validated}
                  uncitedClaims={getValidationForSection('overall_summary')!.uncited_claims}
                />
              )}
              {isValidating && !getValidationForSection('overall_summary') && (
                <ValidationIndicator status="pending" />
              )}
            </h3>
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

          {/* Historical Context (Quarterly Reports) */}
          {report.historical_context && report.historical_context.groups.length > 0 && (
            <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#7c3aed', borderBottom: '2px solid #7c3aed', paddingBottom: '0.5rem' }}>
                Historical Context
                <span style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 400 }}>
                  ({formatDate(report.historical_context.lookback_start)} to {formatDate(report.historical_context.lookback_end)})
                </span>
              </h3>
              {report.historical_context.narrative ? (
                <div style={{ lineHeight: 1.8, color: '#333', marginTop: '0.75rem' }}>
                  {report.historical_context.narrative.split('\n\n').filter(p => p.trim()).map((paragraph, i) => (
                    <p key={i} style={{ marginBottom: '1rem' }}>{paragraph.trim()}</p>
                  ))}
                </div>
              ) : (
                <ShimmerBlock lines={4} />
              )}

              {/* Grouped lookback events */}
              <div style={{ marginTop: '1rem' }}>
                {report.historical_context.groups.map((group, gi) => (
                  <div key={gi} style={{ marginBottom: '1rem' }}>
                    <h4 style={{ fontSize: '0.85rem', color: '#475569', marginBottom: '0.5rem' }}>
                      Prior events related to: <span style={{ fontWeight: 600 }}>{group.report_event_name}</span>
                    </h4>
                    {group.lookback_events.map((lb, li) => (
                      <div key={li} style={{
                        padding: '0.6rem 0.75rem', border: '1px solid #e2e8f0',
                        borderRadius: '6px', marginBottom: '0.4rem', background: '#f8fafc',
                        borderLeft: `3px solid ${
                          lb.match_type === 'master_chain' ? '#7c3aed' :
                          lb.match_type === 'shared_entities' ? '#2563eb' : '#64748b'
                        }`
                      }}>
                        <div style={{ fontWeight: 600, fontSize: '0.85rem', color: '#1e293b' }}>{lb.event_name}</div>
                        <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.2rem' }}>
                          {formatDate(lb.first_mention_date)} to {formatDate(lb.last_mention_date)}
                          {' | '}{lb.article_count} articles
                          {' | '}Materiality: {lb.materiality_score}/10
                          {' | '}Match: {lb.match_type.replace(/_/g, ' ')}
                          {lb.shared_entities.length > 0 && ` | Shared: ${lb.shared_entities.join(', ')}`}
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Key Events by Category */}
          {report.categories.map((cat) => {
            const catSectionId = `category:${cat.category}`
            const catValidation = getValidationForSection(catSectionId)
            return (
            <div key={cat.category} className="chart-card" style={{ marginBottom: '1.5rem' }}>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: CATEGORY_COLORS[cat.category] || '#1a365d', borderBottom: `2px solid ${CATEGORY_COLORS[cat.category] || '#1a365d'}`, paddingBottom: '0.5rem' }}>
                {cat.category}
                {catValidation && (
                  <ValidationIndicator
                    status={catValidation.status as ValidationStatus}
                    issues={catValidation.issues}
                    summary={catValidation.summary}
                    claimsValidated={catValidation.claims_validated}
                    uncitedClaims={catValidation.uncited_claims}
                  />
                )}
                {isValidating && !catValidation && (
                  <ValidationIndicator status="pending" />
                )}
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
                {cat.events.map((event, i) => {
                  const eventSectionId = `event:${cat.category}:${i}`
                  const eventValidation = getValidationForSection(eventSectionId)
                  return (
                  <div key={i} className="report-event-card" style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '8px',
                    padding: '1.25rem',
                    borderLeft: `4px solid ${CATEGORY_COLORS[cat.category] || '#1a365d'}`
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <div>
                          <h4 style={{ margin: 0, fontSize: '1rem' }}>{event.event_name}</h4>
                          <p style={{ fontSize: '0.8rem', color: '#666', marginTop: '0.25rem' }}>
                            {formatDate(event.first_mention_date)} to {formatDate(event.last_mention_date)} | {event.article_count} articles
                          </p>
                        </div>
                        {eventValidation && (
                          <ValidationIndicator
                            status={eventValidation.status as ValidationStatus}
                            issues={eventValidation.issues}
                            summary={eventValidation.summary}
                            claimsValidated={eventValidation.claims_validated}
                            uncitedClaims={eventValidation.uncited_claims}
                          />
                        )}
                        {isValidating && !eventValidation && (
                          <ValidationIndicator status="pending" />
                        )}
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

                    {event.material_justification && (
                      <div style={{ marginTop: '0.5rem' }}>
                        <strong style={{ fontSize: '0.85rem', color: '#666' }}>Materiality Assessment:</strong>
                        <span style={{ fontSize: '0.85rem', marginLeft: '0.4rem', fontStyle: 'italic', color: '#555' }}>
                          {event.material_justification}
                        </span>
                      </div>
                    )}

                    {event.key_entities && event.key_entities.length > 0 && (
                      <div style={{ marginTop: '0.6rem', display: 'flex', flexWrap: 'wrap', gap: '0.35rem', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.75rem', color: '#888', marginRight: '0.25rem' }}>Entities:</span>
                        {event.key_entities.map((ent, eidx) => {
                          const typeColors: Record<string, string> = {
                            'PERSON': '#7c3aed',
                            'ORGANIZATION': '#2563eb',
                            'COMPANY': '#059669',
                            'LOCATION': '#ea580c'
                          }
                          const c = typeColors[ent.entity_type] || '#666'
                          return (
                            <span key={eidx} style={{
                              display: 'inline-block',
                              padding: '0.15rem 0.5rem',
                              borderRadius: '10px',
                              fontSize: '0.7rem',
                              fontWeight: 500,
                              color: c,
                              background: `${c}15`,
                              border: `1px solid ${c}40`
                            }}>
                              {ent.name}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </div>
                  )
                })}
              </div>
            </div>
            )
          })}

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
                      {group.entities.map((entity, idx) => {
                        const entitySectionId = `entity:${group.entity_type}:${entity.name}`
                        const entityValidation = getValidationForSection(entitySectionId)
                        return (
                        <div key={idx} style={{
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          padding: '1rem 1.25rem',
                          borderLeft: `3px solid ${typeColor}`
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                            <div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <h5 style={{ margin: 0, fontSize: '0.95rem' }}>{entity.name}</h5>
                                {entityValidation && (
                                  <ValidationIndicator
                                    status={entityValidation.status as ValidationStatus}
                                    issues={entityValidation.issues}
                                    summary={entityValidation.summary}
                                    claimsValidated={entityValidation.claims_validated}
                                    uncitedClaims={entityValidation.uncited_claims}
                                  />
                                )}
                                {isValidating && !entityValidation && (
                                  <ValidationIndicator status="pending" />
                                )}
                              </div>
                              <p style={{ fontSize: '0.75rem', color: '#888', margin: '0.2rem 0 0' }}>
                                {entity.role && entity.role !== 'OTHER' && entity.role !== 'Unknown'
                                  ? `${entity.role.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())} | `
                                  : ''}{entity.total_documents} documents | {entity.total_mention_days} mention days
                              </p>
                            </div>
                            {entity.citation_numbers.length > 0 && (
                              <span style={{ fontSize: '0.7rem', color: '#666', whiteSpace: 'nowrap' }}>
                                Sources: [{entity.citation_numbers.join(', ')}]
                              </span>
                            )}
                          </div>
                          {/* Category and recipient tags */}
                          {(entity.primary_categories && Object.keys(entity.primary_categories).length > 0) && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.5rem' }}>
                              {Object.entries(entity.primary_categories)
                                .sort(([,a], [,b]) => b - a)
                                .slice(0, 4)
                                .map(([cat, count]) => (
                                  <span key={cat} style={{
                                    fontSize: '0.65rem', padding: '0.15rem 0.5rem',
                                    borderRadius: '9999px', background: '#f0f4ff', color: '#3b5998',
                                    border: '1px solid #d0d8ee'
                                  }}>
                                    {cat} ({count})
                                  </span>
                                ))}
                              {entity.primary_recipients && Object.entries(entity.primary_recipients)
                                .sort(([,a], [,b]) => b - a)
                                .slice(0, 3)
                                .map(([recip, count]) => (
                                  <span key={recip} style={{
                                    fontSize: '0.65rem', padding: '0.15rem 0.5rem',
                                    borderRadius: '9999px', background: '#fef9ec', color: '#92400e',
                                    border: '1px solid #e8d5a3'
                                  }}>
                                    {recip} ({count})
                                  </span>
                                ))}
                            </div>
                          )}
                          {entity.summary ? (
                            <p style={{ marginTop: '0.6rem', fontSize: '0.85rem', lineHeight: 1.6, color: '#444' }}>
                              {entity.summary}
                            </p>
                          ) : isGenerating ? (
                            <ShimmerBlock lines={2} />
                          ) : null}
                        </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* Influence Signature radar (category mix; raw vs. corroborated) */}
          {report.metrics.category_distribution.length > 0 && <SignatureRadar metrics={report.metrics} />}

          {/* Metrics Dashboard — 2x2 Quadrant */}
          <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h3 style={{ margin: 0 }}>Metrics Dashboard</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                {report.metrics.provenance && (
                  <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    {report.metrics.provenance.corroborated_documents.toLocaleString()} corroborated of {report.metrics.provenance.total_documents.toLocaleString()} ·{' '}
                    <strong style={{ color: report.metrics.provenance.self_report_share >= 0.5 ? '#b91c1c' : '#047857' }}>
                      {Math.round(report.metrics.provenance.self_report_share * 100)}% self-reported
                    </strong>
                  </span>
                )}
                <div style={{ display: 'inline-flex', border: '1px solid #cbd5e1', borderRadius: '6px', overflow: 'hidden' }} title="Corroborated strips the initiator's own state-media coverage">
                  {(['raw', 'corroborated'] as const).map(m => (
                    <button key={m} onClick={() => setProvMode(m)} style={{
                      padding: '0.25rem 0.6rem', fontSize: '0.72rem', border: 'none', cursor: 'pointer',
                      background: provMode === m ? '#1a365d' : '#fff', color: provMode === m ? '#fff' : '#475569',
                    }}>{m === 'raw' ? 'Raw' : 'Corroborated'}</button>
                  ))}
                </div>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem', marginTop: '1rem' }}>
              {/* Q1: Category Distribution */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0.75rem' }}>
                <h4 style={{ fontSize: '0.85rem', margin: '0 0 0.5rem' }}>Category Distribution</h4>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={report.metrics.category_distribution.map(d => ({ ...d, value: (provMode === 'corroborated' && d.corroborated != null) ? d.corroborated : d.count }))} layout="vertical" margin={{ left: 0, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis dataKey="category" type="category" width={70} tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#1a365d">
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
                  <BarChart data={report.metrics.recipient_distribution.slice(0, 8).map(d => ({ ...d, value: (provMode === 'corroborated' && d.corroborated != null) ? d.corroborated : d.count }))} layout="vertical" margin={{ left: 0, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis dataKey="recipient" type="category" width={90} tick={{ fontSize: 9 }} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#059669" radius={[0, 3, 3, 0]} />
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

          {/* Provenance Quadrant — narrative projection vs. genuine traction */}
          {report.metrics.provenance_quadrant && report.metrics.provenance_quadrant.length > 0 && (
            <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
              <h3>Narrative Projection vs. Genuine Traction</h3>
              <p style={{ fontSize: '0.78rem', color: '#64748b', margin: '0.25rem 0 0.75rem' }}>
                Each recipient by raw coverage (x) vs. third-party-corroborated share (y). Lower band = high volume but low corroboration (state-media projection); upper band = genuine traction. Bubble size = corroborated documents.
              </p>
              <ResponsiveContainer width="100%" height={300}>
                <ScatterChart margin={{ top: 10, right: 30, bottom: 24, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="raw" name="raw docs" scale="log" domain={['auto', 'auto']} tick={{ fontSize: 10 }}
                    label={{ value: 'raw documents (log)', position: 'insideBottom', offset: -12, fontSize: 11 }} />
                  <YAxis type="number" dataKey="corroborated_share" name="corroborated share" domain={[0, 1]} tick={{ fontSize: 10 }}
                    label={{ value: 'corroborated share', angle: -90, position: 'insideLeft', fontSize: 11 }} />
                  <ZAxis type="number" dataKey="corroborated" range={[50, 400]} name="corroborated docs" />
                  <ReferenceLine y={0.5} stroke="#cbd5e1" strokeDasharray="4 4" />
                  <Tooltip cursor={{ strokeDasharray: '3 3' }}
                    formatter={(v, n) => [typeof v === 'number' ? v.toLocaleString() : v, n]} />
                  <Scatter data={report.metrics.provenance_quadrant} fill="#1a365d" fillOpacity={0.8}>
                    <LabelList dataKey="recipient" position="top" style={{ fontSize: 9, fill: '#475569' }} />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Materiality Trends + Top Entities — side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
            {/* Materiality Trends Chart */}
            {report.materiality_trends && report.materiality_trends.overall_series.length > 1 ? (() => {
              const trends = report.materiality_trends
              const allMonths = new Set<string>()
              trends.overall_series.forEach(p => allMonths.add(p.month))
              Object.values(trends.recipient_series).forEach(series =>
                series.forEach(p => allMonths.add(p.month))
              )
              const sortedMonths = Array.from(allMonths).sort()
              const recipients = Object.keys(trends.recipient_series)

              const chartData = sortedMonths.map(month => {
                const row: Record<string, string | number> = {
                  month: new Date(month + 'T00:00:00').toLocaleDateString('en-US', { year: '2-digit', month: 'short' })
                }
                const overall = trends.overall_series.find(p => p.month === month)
                if (overall) row['Overall'] = overall.avg_score
                for (const r of recipients) {
                  const pt = trends.recipient_series[r].find(p => p.month === month)
                  if (pt) row[r] = pt.avg_score
                }
                return row
              })

              const TREND_COLORS = ['#2563eb', '#7c3aed', '#059669', '#ea580c', '#dc2626']

              return (
                <div className="chart-card" style={{ margin: 0 }}>
                  <h3 style={{ fontSize: '1rem', marginBottom: '0.25rem' }}>Materiality Trends</h3>
                  <p style={{ fontSize: '0.75rem', color: '#666', margin: '0 0 0.5rem' }}>
                    Avg materiality by month (3-month lookback)
                  </p>

                  {trends.significant_changes.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginBottom: '0.5rem' }}>
                      {trends.significant_changes.map((sc, idx) => (
                        <span key={idx} style={{
                          display: 'inline-block',
                          padding: '0.15rem 0.5rem',
                          borderRadius: '12px',
                          fontSize: '0.65rem',
                          fontWeight: 600,
                          color: sc.direction === 'increase' ? '#dc2626' : '#059669',
                          background: sc.direction === 'increase' ? '#fef2f2' : '#f0fdf4',
                          border: `1px solid ${sc.direction === 'increase' ? '#fca5a5' : '#86efac'}`,
                        }}>
                          {sc.recipient}: {sc.direction === 'increase' ? '▲' : '▼'} {Math.abs(sc.delta).toFixed(1)} ({new Date(sc.month + 'T00:00:00').toLocaleDateString('en-US', { month: 'short' })})
                        </span>
                      ))}
                    </div>
                  )}

                  <ResponsiveContainer width="100%" height={260}>
                    <LineChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="month" tick={{ fontSize: 9 }} />
                      <YAxis domain={[0, 10]} tick={{ fontSize: 9 }} label={{ value: 'Avg Score', angle: -90, position: 'insideLeft', style: { fontSize: 9 } }} />
                      <Tooltip />
                      <Legend wrapperStyle={{ fontSize: '0.7rem' }} />
                      <Line
                        type="monotone"
                        dataKey="Overall"
                        stroke="#1a365d"
                        strokeWidth={2.5}
                        dot={{ r: 3 }}
                        activeDot={{ r: 5 }}
                      />
                      {recipients.map((r, i) => (
                        <Line
                          key={r}
                          type="monotone"
                          dataKey={r}
                          stroke={TREND_COLORS[i % TREND_COLORS.length]}
                          strokeWidth={1.5}
                          strokeDasharray="5 3"
                          dot={{ r: 2 }}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )
            })() : <div />}

            {/* Top Entities by References Chart */}
            {(() => {
              const ENTITY_COLORS: Record<string, string> = {
                person: '#7c3aed',
                organization: '#2563eb',
                company: '#059669',
                location: '#ea580c',
              }
              const ENTITY_COLORS_UPPER: Record<string, string> = {
                PERSON: '#7c3aed',
                ORGANIZATION: '#2563eb',
                COMPANY: '#059669',
                LOCATION: '#ea580c',
              }

              let allEntities: { name: string; fullName: string; count: number; type: string; color: string }[] = []
              let subtitle = 'Entities ranked by document mentions'

              // Primary source: canonical entities from report.entities
              if (report.entities && report.entities.length > 0) {
                allEntities = report.entities.flatMap(group =>
                  group.entities.map(e => ({
                    name: e.name.length > 22 ? e.name.slice(0, 20) + '...' : e.name,
                    fullName: e.name,
                    count: e.total_documents,
                    type: group.entity_type,
                    color: ENTITY_COLORS[group.entity_type] || '#6b7280',
                  }))
                ).sort((a, b) => b.count - a.count).slice(0, 15)
              }

              // Fallback: aggregate key_entities from events
              if (allEntities.length === 0 && report.categories) {
                const entityCounts = new Map<string, { count: number; type: string }>()
                for (const cat of report.categories) {
                  for (const evt of cat.events) {
                    if (evt.key_entities) {
                      for (const ent of evt.key_entities) {
                        const key = ent.name
                        const existing = entityCounts.get(key)
                        if (existing) {
                          existing.count += 1
                        } else {
                          entityCounts.set(key, { count: 1, type: ent.entity_type })
                        }
                      }
                    }
                  }
                }
                allEntities = Array.from(entityCounts.entries()).map(([name, { count, type }]) => ({
                  name: name.length > 22 ? name.slice(0, 20) + '...' : name,
                  fullName: name,
                  count,
                  type: type.toLowerCase(),
                  color: ENTITY_COLORS_UPPER[type] || ENTITY_COLORS[type.toLowerCase()] || '#6b7280',
                })).sort((a, b) => b.count - a.count).slice(0, 15)
                subtitle = 'Entities ranked by event appearances'
              }

              if (allEntities.length === 0) return <div />

              return (
                <div className="chart-card" style={{ margin: 0 }}>
                  <h3 style={{ fontSize: '1rem', marginBottom: '0.25rem' }}>Top Entities by References</h3>
                  <p style={{ fontSize: '0.75rem', color: '#666', margin: '0 0 0.5rem' }}>
                    {subtitle}
                  </p>
                  <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                    {Object.entries(ENTITY_COLORS).map(([type, color]) => (
                      <span key={type} style={{ fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: 'inline-block' }} />
                        {type.charAt(0).toUpperCase() + type.slice(1)}
                      </span>
                    ))}
                  </div>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={allEntities} layout="vertical" margin={{ left: 0, right: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" tick={{ fontSize: 9 }} allowDecimals={false} />
                      <YAxis dataKey="name" type="category" width={110} tick={{ fontSize: 8 }} />
                      <Tooltip
                        formatter={(value, _name, props) => [
                          `${value} ${subtitle.includes('event') ? 'events' : 'documents'}`,
                          (props.payload as Record<string, string>)?.fullName || ''
                        ]}
                      />
                      <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                        {allEntities.map((entry, idx) => (
                          <Cell key={idx} fill={entry.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )
            })()}
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
