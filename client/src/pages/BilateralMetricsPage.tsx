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
import { ArrowLeft, ArrowRight, FileText, TrendingUp } from 'lucide-react'
import { fetchBilateralMetrics } from '../api/client'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a8c5e8', '#c3daf7']
const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Military: '#8b1a1a',
  Social: '#1a5f1a',
  Diplomacy: '#5f1a5f',
}

export default function BilateralMetricsPage() {
  const { influencer, recipient } = useParams<{ influencer: string; recipient: string }>()
  const navigate = useNavigate()

  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['bilateralMetrics', influencer, recipient],
    queryFn: () => fetchBilateralMetrics(influencer!, recipient!),
    enabled: !!influencer && !!recipient,
  })

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading bilateral metrics...</div>
      </div>
    )
  }

  if (error || !metrics) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load metrics</h3>
          <p>Failed to load data for {influencer} → {recipient}</p>
        </div>
      </div>
    )
  }

  const totalCategoryDocs = metrics.category_breakdown.reduce((sum, cat) => sum + cat.count, 0)

  return (
    <div className="page">
      <header className="page-header">
        <button
          onClick={() => navigate('/bilateral')}
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
          Back to Bilateral Relationships
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <h1>{metrics.influencer}</h1>
          <ArrowRight size={40} color="#1a365d" />
          <h1>{metrics.recipient}</h1>
        </div>
        <p>Detailed metrics and category/subcategory breakdown</p>
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

        {metrics.provenance && (
          <div className="stat-card" title="Documents not sourced from this influencer's own state media. Corrects for state-media volume.">
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
            <span style={{ fontSize: '24px' }}>📊</span>
            <h3>Active Categories</h3>
          </div>
          <p className="stat-value">{metrics.category_breakdown.length}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '24px' }}>🔍</span>
            <h3>Subcategories</h3>
          </div>
          <p className="stat-value">{metrics.subcategory_breakdown.length}</p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <TrendingUp size={24} color="#4a6fa5" />
            <h3>Recent Highlights</h3>
          </div>
          <p className="stat-value">{metrics.recent_highlights.length}</p>
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
                label={(entry: any) => `${entry.category}: ${entry.count}`}
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

        {/* Top Subcategories Overall */}
        <div className="chart-card">
          <h3>🔍 Top 10 Subcategories</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={metrics.subcategory_breakdown.slice(0, 10)} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="subcategory" type="category" width={120} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
              <Bar dataKey="count" fill="#4a6fa5" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* News Source Distribution */}
      <div className="chart-card" style={{ marginTop: '2rem' }}>
        <h3>📰 Top 20 News Sources</h3>
        <ResponsiveContainer width="100%" height={500}>
          <BarChart data={metrics.source_breakdown.slice(0, 20)} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="source" type="category" width={150} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            <Bar dataKey="count" fill="#2d4a7c" name="Documents" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Recent Highlights */}
      {metrics.recent_highlights.length > 0 && (
        <div className="section" style={{ marginTop: '2rem' }}>
          <h2 style={{ marginBottom: '1rem', color: '#1e293b' }}>Recent Document Highlights</h2>
          <div style={{ display: 'grid', gap: '1rem' }}>
            {metrics.recent_highlights.map((doc) => (
              <div
                key={doc.doc_id}
                className="chart-card"
                style={{ background: 'linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                  <h4 style={{ color: '#1e293b', margin: 0, flex: 1 }}>{doc.title}</h4>
                  <span style={{ fontSize: '0.875rem', color: '#64748b', marginLeft: '1rem' }}>
                    {new Date(doc.date).toLocaleDateString()}
                  </span>
                </div>

                {doc.distilled_text && (
                  <p style={{ fontSize: '0.938rem', color: '#475569', lineHeight: 1.6, marginBottom: '0.75rem' }}>
                    {doc.distilled_text}
                  </p>
                )}

                {doc.salience_justification && (
                  <div
                    style={{
                      background: '#f1f5f9',
                      padding: '0.75rem',
                      borderRadius: '0.375rem',
                      marginBottom: '0.75rem',
                    }}
                  >
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem' }}>
                      Salience Justification
                    </div>
                    <p style={{ fontSize: '0.875rem', color: '#64748b', margin: 0, lineHeight: 1.5 }}>
                      {doc.salience_justification}
                    </p>
                  </div>
                )}

                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                  {doc.category && (
                    <span
                      style={{
                        background: CATEGORY_COLORS[doc.category] || '#e2e8f0',
                        color: 'white',
                        padding: '0.25rem 0.75rem',
                        borderRadius: '9999px',
                        fontSize: '0.813rem',
                        fontWeight: 500,
                      }}
                    >
                      {doc.category}
                    </span>
                  )}
                  {doc.subcategory && (
                    <span
                      style={{
                        background: '#e2e8f0',
                        color: '#1e293b',
                        padding: '0.25rem 0.75rem',
                        borderRadius: '9999px',
                        fontSize: '0.813rem',
                      }}
                    >
                      {doc.subcategory}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key Insights */}
      <div className="chart-card" style={{ background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)', marginTop: '2rem' }}>
        <h3 style={{ color: '#1e293b' }}>💡 Key Insights</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Primary Category
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.category_breakdown[0]?.category}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {((metrics.category_breakdown[0]?.count / totalCategoryDocs) * 100).toFixed(1)}% of all documents
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Top Subcategory
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
              Activity Diversity
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.subcategory_breakdown.length} types
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              of soft power activities
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Recent Activity
            </div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.monthly_trend[metrics.monthly_trend.length - 1]?.count || 0}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              documents last month
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
