import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
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
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { ArrowLeft, FileText, Globe, TrendingUp } from 'lucide-react'
import { fetchInfluencerMetrics } from '../api/client'
import { useDrilldown } from '../hooks/useDrilldown'
import PageGuide from '../components/PageGuide'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a8c5e8', '#c3daf7']
const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Military: '#8b1a1a',
  Social: '#1a5f1a',
  Diplomacy: '#5f1a5f',
}

export default function InfluencerMetricsPage() {
  const { country } = useParams<{ country: string }>()
  const navigate = useNavigate()

  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['influencerMetrics', country],
    queryFn: () => fetchInfluencerMetrics(country!),
    enabled: !!country,
  })

  const openDrilldown = useDrilldown({
    initiating_country: country,
    page_source: 'Influencer Metrics',
  })

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading metrics for {country}...</div>
      </div>
    )
  }

  if (error || !metrics) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load metrics</h3>
          <p>Failed to load data for {country}</p>
        </div>
      </div>
    )
  }

  const totalCategoryDocs = metrics.category_breakdown.reduce((sum, cat) => sum + cat.count, 0)

  return (
    <div className="page">
      <header className="page-header">
        <button
          onClick={() => navigate('/metrics')}
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
          Back to Overall Metrics
        </button>
        <h1>{metrics.influencer} - Detailed Metrics</h1>
        <p>Comprehensive breakdown of soft power activities and engagements</p>
        <p style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.25rem' }}>
          Click any chart element to drill down into the underlying data
        </p>
      </header>

      <PageGuide page="influencer-metrics" />

      {/* Key Stats */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={24} color="#1a365d" />
            <h3>Total Documents</h3>
          </div>
          <p className="stat-value">{metrics.total_documents.toLocaleString()}</p>
        </div>

        {metrics.provenance && (
          <div className="stat-card" title="Documents not sourced from this actor's own state media (source geo-focus). Corrects for state-media volume.">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <FileText size={24} color="#047857" />
              <h3>Corroborated</h3>
            </div>
            <p className="stat-value">{metrics.provenance.corroborated_documents.toLocaleString()}</p>
            <p style={{ fontSize: '0.8rem', fontWeight: 600, margin: '0.15rem 0 0', color: metrics.provenance.self_report_share >= 0.5 ? '#b91c1c' : '#047857' }}>
              {Math.round(metrics.provenance.self_report_share * 100)}% self-reported
            </p>
          </div>
        )}

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Globe size={24} color="#2d4a7c" />
            <h3>Recipient Countries</h3>
          </div>
          <p className="stat-value">{metrics.recipient_breakdown.length}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <TrendingUp size={24} color="#4a6fa5" />
            <h3>Active Categories</h3>
          </div>
          <p className="stat-value">{metrics.category_breakdown.length}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '24px' }}>📊</span>
            <h3>Subcategories</h3>
          </div>
          <p className="stat-value">{metrics.subcategory_breakdown.length}</p>
        </div>
      </div>

      {/* Monthly Trend */}
      <div className="chart-card">
        <h3>📈 Monthly Activity Trend</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart
            data={metrics.monthly_trend}
            onClick={(e) => {
              if (e?.activeLabel) {
                const month = e.activeLabel as string
                // Format to YYYY-MM
                const d = new Date(month)
                const formatted = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
                openDrilldown({ dimension: 'month', value: formatted, chart_type: 'line' })
              }
            }}
            style={{ cursor: 'pointer' }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 12 }}
              tickFormatter={(value) => {
                const date = new Date(value)
                return date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
              }}
            />
            <YAxis />
            <Tooltip
              labelFormatter={(value) => {
                const date = new Date(value as string)
                return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="count"
              stroke="#1a365d"
              strokeWidth={3}
              name="Documents"
              dot={{ fill: '#1a365d', r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="charts-grid">
        {/* Category Breakdown */}
        <div className="chart-card">
          <h3>📊 Category Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={metrics.category_breakdown}
                dataKey="count"
                nameKey="category"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry: any) => `${entry.category}`}
                onClick={(entry: any) => {
                  if (entry?.category) {
                    openDrilldown({ dimension: 'category', value: entry.category, chart_type: 'pie' })
                  }
                }}
                style={{ cursor: 'pointer' }}
              >
                {metrics.category_breakdown.map((entry) => (
                  <Cell
                    key={`cell-${entry.category}`}
                    fill={CATEGORY_COLORS[entry.category] || COLORS[0]}
                  />
                ))}
              </Pie>
              <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Top Recipients */}
        <div className="chart-card">
          <h3>🌍 Top 10 Recipients</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={metrics.recipient_breakdown.slice(0, 10)}
              layout="vertical"
              onClick={(e) => {
                if (e?.activeLabel) {
                  openDrilldown({ dimension: 'recipient_country', value: e.activeLabel as string, chart_type: 'bar' })
                }
              }}
              style={{ cursor: 'pointer' }}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="recipient" type="category" width={100} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
              <Bar dataKey="count" fill="#1a365d" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Subcategories */}
      <div className="chart-card">
        <h3>🔍 Top 15 Subcategories</h3>
        <ResponsiveContainer width="100%" height={450}>
          <BarChart
            data={metrics.subcategory_breakdown.slice(0, 15)}
            layout="vertical"
            onClick={(e) => {
              if (e?.activeLabel) {
                openDrilldown({ dimension: 'subcategory', value: e.activeLabel as string, chart_type: 'bar' })
              }
            }}
            style={{ cursor: 'pointer' }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="subcategory" type="category" width={150} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            <Bar dataKey="count" fill="#4a6fa5" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* News Source Distribution */}
      <div className="chart-card">
        <h3>📰 Top 20 News Sources</h3>
        <ResponsiveContainer width="100%" height={500}>
          <BarChart
            data={metrics.source_breakdown.slice(0, 20)}
            layout="vertical"
            onClick={(e) => {
              if (e?.activeLabel) {
                openDrilldown({ dimension: 'source', value: e.activeLabel as string, chart_type: 'bar' })
              }
            }}
            style={{ cursor: 'pointer' }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="source" type="category" width={150} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            <Bar dataKey="count" fill="#2d4a7c" name="Documents" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Insights */}
      <div className="chart-card" style={{ background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)' }}>
        <h3 style={{ color: '#1e293b' }}>💡 Key Insights for {metrics.influencer}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Primary Focus Area
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.category_breakdown[0]?.category}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {((metrics.category_breakdown[0]?.count / totalCategoryDocs) * 100).toFixed(1)}% of activity
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Top Recipient
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.recipient_breakdown[0]?.recipient}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {metrics.recipient_breakdown[0]?.count.toLocaleString()} documents
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Most Common Activity
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.subcategory_breakdown[0]?.subcategory}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {metrics.subcategory_breakdown[0]?.count.toLocaleString()} documents
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Engagement Breadth
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.recipient_breakdown.length} countries
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              Average {Math.round(metrics.total_documents / metrics.recipient_breakdown.length)} docs per country
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
