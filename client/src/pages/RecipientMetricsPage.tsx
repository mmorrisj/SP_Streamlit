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
import { ArrowLeft, FileText, Globe, TrendingUp, Calendar } from 'lucide-react'
import { fetchRecipientMetrics } from '../api/client'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a8c5e8', '#c3daf7']
const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Military: '#8b1a1a',
  Social: '#1a5f1a',
  Diplomacy: '#5f1a5f',
}

export default function RecipientMetricsPage() {
  const { country } = useParams<{ country: string }>()
  const navigate = useNavigate()

  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['recipientMetrics', country],
    queryFn: () => fetchRecipientMetrics(country!),
    enabled: !!country,
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
        <h1>{metrics.recipient} - Recipient Metrics</h1>
        <p>Engagement from all influencers targeting {metrics.recipient}</p>
      </header>

      {/* Key Stats */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={24} color="#1a365d" />
            <h3>Total Documents</h3>
          </div>
          <p className="stat-value">{metrics.total_documents.toLocaleString()}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Globe size={24} color="#2d4a7c" />
            <h3>Active Influencers</h3>
          </div>
          <p className="stat-value">{metrics.influencer_breakdown.length}</p>
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
            <Calendar size={24} color="#6b8cbe" />
            <h3>Recent Events</h3>
          </div>
          <p className="stat-value">{metrics.recent_events.length}</p>
        </div>
      </div>

      {/* Monthly Trend */}
      <div className="chart-card">
        <h3>📈 Monthly Activity Trend</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={metrics.monthly_trend}>
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
        {/* Influencer Breakdown */}
        <div className="chart-card">
          <h3>🌍 Influencer Engagement</h3>
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginBottom: '1rem' }}>
            Which influencers are engaging with {metrics.recipient}
          </p>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={metrics.influencer_breakdown} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="influencer" type="category" width={100} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number) => value.toLocaleString()} />
              <Bar dataKey="count" fill="#1a365d" name="Documents" />
            </BarChart>
          </ResponsiveContainer>
        </div>

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
                label={(entry) => `${entry.category}`}
              >
                {metrics.category_breakdown.map((entry) => (
                  <Cell
                    key={`cell-${entry.category}`}
                    fill={CATEGORY_COLORS[entry.category] || COLORS[0]}
                  />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => value.toLocaleString()} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Subcategories */}
      <div className="chart-card">
        <h3>🔍 Top 15 Subcategories</h3>
        <ResponsiveContainer width="100%" height={450}>
          <BarChart data={metrics.subcategory_breakdown.slice(0, 15)} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="subcategory" type="category" width={150} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number) => value.toLocaleString()} />
            <Bar dataKey="count" fill="#4a6fa5" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* News Source Distribution */}
      <div className="chart-card" style={{ marginTop: '2rem' }}>
        <h3>📰 Top 20 News Sources</h3>
        <ResponsiveContainer width="100%" height={500}>
          <BarChart data={metrics.source_breakdown.slice(0, 20)} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="source" type="category" width={150} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number) => value.toLocaleString()} />
            <Bar dataKey="count" fill="#2d4a7c" name="Documents" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Recent Events */}
      {metrics.recent_events.length > 0 && (
        <div className="section" style={{ marginTop: '2rem' }}>
          <h2 style={{ marginBottom: '1rem', color: '#1e293b' }}>Recent Events Involving {metrics.recipient}</h2>
          <div style={{ display: 'grid', gap: '1rem' }}>
            {metrics.recent_events.map((event) => (
              <div
                key={event.id}
                className="chart-card"
                style={{ background: 'linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                  <h4 style={{ color: '#1e293b', margin: 0, flex: 1 }}>{event.event_name}</h4>
                  <span style={{ fontSize: '0.875rem', color: '#64748b', marginLeft: '1rem' }}>
                    {new Date(event.event_date).toLocaleDateString()}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                  <span
                    style={{
                      background: '#1a365d',
                      color: 'white',
                      padding: '0.25rem 0.75rem',
                      borderRadius: '9999px',
                      fontSize: '0.813rem',
                      fontWeight: 500,
                    }}
                  >
                    {event.influencer}
                  </span>
                  <span
                    style={{
                      background: '#e2e8f0',
                      color: '#1e293b',
                      padding: '0.25rem 0.75rem',
                      borderRadius: '9999px',
                      fontSize: '0.813rem',
                    }}
                  >
                    {event.total_mentions} mentions
                  </span>
                </div>

                {event.summary && (
                  <p style={{ fontSize: '0.938rem', color: '#475569', lineHeight: 1.6, margin: 0 }}>
                    {event.summary}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Insights */}
      <div className="chart-card" style={{ background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)', marginTop: '2rem' }}>
        <h3 style={{ color: '#1e293b' }}>💡 Key Insights for {metrics.recipient}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Primary Influencer
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.influencer_breakdown[0]?.influencer}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {metrics.influencer_breakdown[0]?.count.toLocaleString()} documents
            </div>
          </div>

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
              Engagement Diversity
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.influencer_breakdown.length} influencers
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              Average {Math.round(metrics.total_documents / metrics.influencer_breakdown.length)} docs per influencer
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
