import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { ArrowLeft, FileText, Calendar, Globe, TrendingUp, Layers, Newspaper } from 'lucide-react'
import { fetchDrilldown } from '../api/client'
import type {
  DrilldownRequest,
  DrilldownResponse,
  DrilldownQueryContext,
  DrilldownChartSelection,
} from '../api/client'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a8c5e8', '#c3daf7']
const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Military: '#8b1a1a',
  Social: '#1a5f1a',
  Diplomacy: '#5f1a5f',
}

function formatDimension(dim: string): string {
  return dim.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export default function DrilldownPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [data, setData] = useState<DrilldownResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const queryContext: DrilldownQueryContext = {}
    const chartSelection: DrilldownChartSelection = {
      dimension: searchParams.get('dimension') as DrilldownChartSelection['dimension'] || 'category',
      value: searchParams.get('value') || '',
      chart_type: searchParams.get('chart_type') || undefined,
    }

    // Restore original query context from URL params
    if (searchParams.get('init_country')) queryContext.initiating_country = searchParams.get('init_country')!
    if (searchParams.get('recip_country')) queryContext.recipient_country = searchParams.get('recip_country')!
    if (searchParams.get('category')) queryContext.category = searchParams.get('category')!
    if (searchParams.get('subcategory')) queryContext.subcategory = searchParams.get('subcategory')!
    if (searchParams.get('start_date')) queryContext.start_date = searchParams.get('start_date')!
    if (searchParams.get('end_date')) queryContext.end_date = searchParams.get('end_date')!
    if (searchParams.get('page_source')) queryContext.page_source = searchParams.get('page_source')!

    if (!chartSelection.value) {
      setError('No chart selection provided')
      setLoading(false)
      return
    }

    const request: DrilldownRequest = {
      query_context: queryContext,
      chart_selection: chartSelection,
      include_narrative: true,
    }

    fetchDrilldown(request)
      .then(setData)
      .catch(err => setError(err.message || 'Failed to load drilldown'))
      .finally(() => setLoading(false))
  }, [searchParams])

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div style={{ fontSize: '1.25rem', marginBottom: '0.5rem' }}>Analyzing data...</div>
          <div style={{ fontSize: '0.875rem', color: '#94a3b8' }}>
            Computing metrics and generating narrative
          </div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load drilldown</h3>
          <p>{error || 'Unknown error'}</p>
          <button onClick={() => navigate(-1)} style={{ marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer' }}>
            Go Back
          </button>
        </div>
      </div>
    )
  }

  const { metrics, query_context: ctx, chart_selection: sel } = data

  // Build a human-readable description of the original query
  const queryParts: string[] = []
  if (ctx.initiating_country && ctx.initiating_country !== 'ALL') queryParts.push(ctx.initiating_country)
  if (ctx.recipient_country && ctx.recipient_country !== 'ALL') queryParts.push(`→ ${ctx.recipient_country}`)
  if (ctx.start_date) queryParts.push(`from ${ctx.start_date}`)
  if (ctx.end_date) queryParts.push(`to ${ctx.end_date}`)
  const queryDesc = queryParts.length > 0 ? queryParts.join(' ') : 'All data'

  return (
    <div className="page">
      <header className="page-header">
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'none',
            border: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            cursor: 'pointer',
            color: '#1a365d',
            fontSize: '0.875rem',
            marginBottom: '1rem',
            padding: '0.5rem',
          }}
        >
          <ArrowLeft size={16} />
          Back to {ctx.page_source || 'Charts'}
        </button>
        <h1>
          {formatDimension(sel.dimension)}: {sel.value}
        </h1>
        <p style={{ color: '#64748b', fontSize: '0.95rem' }}>
          Drilldown from query: <strong>{queryDesc}</strong>
        </p>
      </header>

      {/* Key Stats */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="#1a365d" />
            <h3>Documents</h3>
          </div>
          <p className="stat-value">{metrics.total_documents.toLocaleString()}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Calendar size={20} color="#2d4a7c" />
            <h3>Date Range</h3>
          </div>
          <p className="stat-value" style={{ fontSize: '1.25rem' }}>
            {metrics.date_range.min || '—'} to {metrics.date_range.max || '—'}
          </p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Globe size={20} color="#4a6fa5" />
            <h3>Recipients</h3>
          </div>
          <p className="stat-value">{metrics.recipient_distribution.length}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Layers size={20} color="#6b8cbe" />
            <h3>Categories</h3>
          </div>
          <p className="stat-value">{metrics.category_distribution.length}</p>
        </div>
      </div>

      {/* LLM Narrative */}
      {data.narrative && (
        <div className="chart-card" style={{ marginBottom: '2rem', background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)' }}>
          <h3 style={{ color: '#1e293b', marginBottom: '1rem' }}>
            Analytical Summary
          </h3>
          <div style={{ color: '#334155', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
            {data.narrative}
          </div>
          {data.narrative_model && (
            <div style={{ marginTop: '1rem', fontSize: '0.75rem', color: '#94a3b8' }}>
              Generated by {data.narrative_model} from {Math.min(data.sample_documents.length, 15)} of {data.total_documents} documents
            </div>
          )}
        </div>
      )}

      {/* Monthly Trend */}
      {metrics.monthly_trend.length > 1 && (
        <div className="chart-card" style={{ marginBottom: '2rem' }}>
          <h3><TrendingUp size={18} style={{ marginRight: '0.5rem', verticalAlign: 'text-bottom' }} />Monthly Trend</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={metrics.monthly_trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 12 }}
                tickFormatter={(v) => {
                  const [y, m] = v.split('-')
                  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
                  return `${months[parseInt(m)-1]} '${y.slice(2)}`
                }}
              />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#1a365d" strokeWidth={3} name="Documents" dot={{ fill: '#1a365d', r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="charts-grid">
        {/* Category Distribution */}
        {metrics.category_distribution.length > 0 && sel.dimension !== 'category' && (
          <div className="chart-card">
            <h3>Category Distribution</h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={metrics.category_distribution}
                  dataKey="count"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={(e: any) => e.category}
                >
                  {metrics.category_distribution.map((entry) => (
                    <Cell key={entry.category} fill={CATEGORY_COLORS[entry.category] || COLORS[0]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number | undefined) => v?.toLocaleString() || '0'} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Recipient Distribution */}
        {metrics.recipient_distribution.length > 0 && sel.dimension !== 'recipient_country' && (
          <div className="chart-card">
            <h3>Top Recipients</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={metrics.recipient_distribution.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="recipient" type="category" width={100} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v: number | undefined) => v?.toLocaleString() || '0'} />
                <Bar dataKey="count" fill="#1a365d" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Subcategory Distribution */}
      {metrics.subcategory_distribution.length > 0 && sel.dimension !== 'subcategory' && (
        <div className="chart-card" style={{ marginBottom: '2rem' }}>
          <h3>Top Subcategories</h3>
          <ResponsiveContainer width="100%" height={Math.max(300, metrics.subcategory_distribution.slice(0, 12).length * 35)}>
            <BarChart data={metrics.subcategory_distribution.slice(0, 12)} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="subcategory" type="category" width={140} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number | undefined) => v?.toLocaleString() || '0'} />
              <Bar dataKey="count" fill="#4a6fa5" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Top Sources */}
      {metrics.top_sources.length > 0 && (
        <div className="chart-card" style={{ marginBottom: '2rem' }}>
          <h3><Newspaper size={18} style={{ marginRight: '0.5rem', verticalAlign: 'text-bottom' }} />Top Sources</h3>
          <ResponsiveContainer width="100%" height={Math.max(250, metrics.top_sources.slice(0, 10).length * 35)}>
            <BarChart data={metrics.top_sources.slice(0, 10)} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="source" type="category" width={150} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number | undefined) => v?.toLocaleString() || '0'} />
              <Bar dataKey="count" fill="#2d4a7c" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Sample Documents */}
      {data.sample_documents.length > 0 && (
        <div className="chart-card">
          <h3 style={{ marginBottom: '1rem' }}>
            <FileText size={18} style={{ marginRight: '0.5rem', verticalAlign: 'text-bottom' }} />
            Recent Documents ({data.sample_documents.length} of {data.total_documents.toLocaleString()})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {data.sample_documents.map((doc) => (
              <div
                key={doc.doc_id}
                style={{
                  padding: '1rem',
                  borderRadius: '8px',
                  border: '1px solid #e2e8f0',
                  background: '#fafbfc',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: '#1e293b', marginBottom: '0.25rem' }}>
                      {doc.title || 'Untitled'}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: '#64748b', display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                      {doc.date && <span>{doc.date}</span>}
                      {doc.source_name && <span>{doc.source_name}</span>}
                      {doc.initiating_country && <span>{doc.initiating_country}</span>}
                      {doc.recipient_country && <span>→ {doc.recipient_country}</span>}
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                      {doc.category && (
                        <span style={{
                          padding: '0.15rem 0.5rem',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          background: CATEGORY_COLORS[doc.category] ? `${CATEGORY_COLORS[doc.category]}20` : '#e2e8f0',
                          color: CATEGORY_COLORS[doc.category] || '#475569',
                          fontWeight: 500,
                        }}>
                          {doc.category}
                        </span>
                      )}
                      {doc.subcategory && (
                        <span style={{
                          padding: '0.15rem 0.5rem',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          background: '#f1f5f9',
                          color: '#475569',
                        }}>
                          {doc.subcategory}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                {doc.distilled_text && (
                  <div style={{ fontSize: '0.85rem', color: '#475569', lineHeight: 1.6, marginTop: '0.25rem' }}>
                    {doc.distilled_text}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
