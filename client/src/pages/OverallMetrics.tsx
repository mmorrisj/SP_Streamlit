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
import { Activity, TrendingUp, Globe, Users } from 'lucide-react'
import { fetchOverallMetrics } from '../api/client'
import { useDrilldown } from '../hooks/useDrilldown'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a8c5e8', '#c3daf7']
const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Military: '#8b1a1a',
  Social: '#1a5f1a',
  Diplomacy: '#5f1a5f',
}

export default function OverallMetrics() {
  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['overallMetrics'],
    queryFn: fetchOverallMetrics,
  })

  const openDrilldown = useDrilldown({
    page_source: 'Overall Metrics',
  })

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading overall metrics...</div>
      </div>
    )
  }

  if (error || !metrics) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load metrics</h3>
          <p>Make sure the API server is running</p>
        </div>
      </div>
    )
  }

  // Process category by influencer for stacked bar chart
  const categoryByInfluencerGrouped = metrics.category_by_influencer.reduce((acc, item) => {
    const existing = acc.find((x) => x.influencer === item.influencer)
    if (existing) {
      existing[item.category] = item.count
    } else {
      acc.push({
        influencer: item.influencer,
        [item.category]: item.count,
      })
    }
    return acc
  }, [] as any[])

  // Calculate percentages for category breakdown
  const totalCategoryDocs = metrics.category_breakdown.reduce((sum, cat) => sum + cat.count, 0)
  const categoryWithPercent = metrics.category_breakdown.map((cat) => ({
    ...cat,
    percent: ((cat.count / totalCategoryDocs) * 100).toFixed(1),
  }))

  return (
    <div className="page">
      <header className="page-header">
        <h1>Overall Soft Power Metrics</h1>
        <p>Comprehensive analysis across all influencers and recipients</p>
        <p style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.25rem' }}>
          Click any chart element to drill down into the underlying data
        </p>
      </header>

      {/* Key Stats */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Activity size={24} color="#1a365d" />
            <h3>Total Documents</h3>
          </div>
          <p className="stat-value">{metrics.total_documents.toLocaleString()}</p>
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginTop: '0.5rem' }}>
            Analyzed diplomatic documents
          </p>
        </div>

        {metrics.provenance && (
          <div className="stat-card" title="Documents not sourced from the initiating actor's own state media. Corrects for state-media volume.">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Activity size={24} color="#047857" />
              <h3>Corroborated</h3>
            </div>
            <p className="stat-value">{metrics.provenance.corroborated_documents.toLocaleString()}</p>
            <p style={{ fontSize: '0.875rem', fontWeight: 600, marginTop: '0.5rem', color: metrics.provenance.self_report_share >= 0.5 ? '#b91c1c' : '#047857' }}>
              {Math.round(metrics.provenance.self_report_share * 100)}% self-reported (state media)
            </p>
          </div>
        )}

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Globe size={24} color="#2d4a7c" />
            <h3>Bilateral Relationships</h3>
          </div>
          <p className="stat-value">{metrics.total_relationships}</p>
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginTop: '0.5rem' }}>
            Influencer-Recipient pairs
          </p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <TrendingUp size={24} color="#4a6fa5" />
            <h3>Active Influencers</h3>
          </div>
          <p className="stat-value">{metrics.active_influencers}</p>
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginTop: '0.5rem' }}>
            Countries with soft power activity
          </p>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Users size={24} color="#6b8cbe" />
            <h3>Recipient Countries</h3>
          </div>
          <p className="stat-value">{metrics.active_recipients}</p>
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginTop: '0.5rem' }}>
            Countries receiving influence
          </p>
        </div>
      </div>

      {/* Monthly Activity Trend */}
      <div className="chart-card">
        <h3>📈 Monthly Activity Trend</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart
            data={metrics.monthly_trend}
            onClick={(e) => {
              if (e?.activeLabel) {
                const month = e.activeLabel as string
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
        {/* Category Distribution */}
        <div className="chart-card">
          <h3>📊 Category Distribution</h3>
          <ResponsiveContainer width="100%" height={350}>
            <PieChart>
              <Pie
                data={categoryWithPercent}
                dataKey="count"
                nameKey="category"
                cx="50%"
                cy="50%"
                outerRadius={120}
                label={(entry: any) => `${entry.category}: ${entry.percent}%`}
                labelLine={{ stroke: '#666', strokeWidth: 1 }}
                onClick={(entry: any) => {
                  if (entry?.category) {
                    openDrilldown({ dimension: 'category', value: entry.category, chart_type: 'pie' })
                  }
                }}
                style={{ cursor: 'pointer' }}
              >
                {categoryWithPercent.map((entry) => (
                  <Cell
                    key={`cell-${entry.category}`}
                    fill={CATEGORY_COLORS[entry.category] || COLORS[0]}
                  />
                ))}
              </Pie>
              <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            </PieChart>
          </ResponsiveContainer>
          <div style={{ marginTop: '1rem', fontSize: '0.875rem', color: '#64748b' }}>
            Total: {totalCategoryDocs.toLocaleString()} documents
          </div>
        </div>

        {/* Influencer Comparison */}
        <div className="chart-card">
          <h3>🌍 Influencer Comparison</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart
              data={metrics.influencer_comparison}
              layout="vertical"
              onClick={(e) => {
                if (e?.activeLabel) {
                  openDrilldown({ dimension: 'initiating_country', value: e.activeLabel as string, chart_type: 'bar' })
                }
              }}
              style={{ cursor: 'pointer' }}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="influencer" type="category" width={100} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
              <Bar dataKey="count" fill="#1a365d" name="Documents">
                {metrics.influencer_comparison.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Subcategories */}
      <div className="chart-card">
        <h3>🔍 Top 20 Subcategories</h3>
        <ResponsiveContainer width="100%" height={500}>
          <BarChart
            data={metrics.subcategory_breakdown}
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
            <YAxis
              dataKey="subcategory"
              type="category"
              width={180}
              tick={{ fontSize: 11 }}
            />
            <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            <Bar dataKey="count" fill="#4a6fa5" name="Documents" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Category by Influencer - Stacked */}
      <div className="chart-card">
        <h3>📑 Category Distribution by Influencer</h3>
        <ResponsiveContainer width="100%" height={400}>
          <BarChart data={categoryByInfluencerGrouped}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="influencer" tick={{ fontSize: 12 }} />
            <YAxis />
            <Tooltip formatter={(value: number | undefined) => value?.toLocaleString() || '0'} />
            <Legend />
            {Object.keys(CATEGORY_COLORS).map((category) => (
              <Bar
                key={category}
                dataKey={category}
                stackId="a"
                fill={CATEGORY_COLORS[category]}
                name={category}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
        <div style={{ marginTop: '1rem', fontSize: '0.875rem', color: '#64748b', textAlign: 'center' }}>
          Stacked view showing category composition for each influencer
        </div>
      </div>

      {/* Insights Summary */}
      <div className="chart-card" style={{ background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)' }}>
        <h3 style={{ color: '#1e293b' }}>💡 Key Insights</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Most Active Category
            </div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.category_breakdown[0]?.category}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {metrics.category_breakdown[0]?.count.toLocaleString()} documents (
              {((metrics.category_breakdown[0]?.count / totalCategoryDocs) * 100).toFixed(1)}%)
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Top Influencer
            </div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.influencer_comparison[0]?.influencer}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {metrics.influencer_comparison[0]?.count.toLocaleString()} documents
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Top Subcategory
            </div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#1e293b' }}>
              {metrics.subcategory_breakdown[0]?.subcategory}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              {metrics.subcategory_breakdown[0]?.count.toLocaleString()} documents
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#475569', marginBottom: '0.5rem' }}>
              Average per Relationship
            </div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#1e293b' }}>
              {Math.round(metrics.total_documents / metrics.total_relationships).toLocaleString()}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#64748b' }}>
              documents per bilateral relationship
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
