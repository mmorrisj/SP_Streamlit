import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { ArrowRight, FileText, Calendar } from 'lucide-react'
import './BilateralPage.css'

interface BilateralOverview {
  influencer: string
  recipient: string
  total_documents: number
  top_categories: Array<{ category: string; count: number }>
  activity_trend: Array<{ week: string; count: number }>
  recent_activities: Array<{
    doc_id: string
    title: string
    date: string
    distilled_text: string
    event_name: string | null
    salience_justification: string | null
  }>
  recent_events: Array<{
    id: string
    event_name: string
    event_date: string
    summary: string
    total_mentions: number
  }>
}

const COLORS = ['#1a365d', '#2d4a7c', '#4a90e2', '#7bb3ff', '#a8d0ff']

async function fetchBilateralOverview(influencer: string, recipient: string): Promise<BilateralOverview> {
  const response = await fetch(`/api/bilateral/${influencer}/${recipient}`)
  if (!response.ok) throw new Error('Failed to fetch bilateral data')
  return response.json()
}

export default function BilateralPage() {
  const { influencer, recipient } = useParams<{ influencer: string; recipient: string }>()

  const { data: overview, isLoading } = useQuery({
    queryKey: ['bilateralOverview', influencer, recipient],
    queryFn: () => fetchBilateralOverview(influencer!, recipient!),
    enabled: !!influencer && !!recipient,
  })

  if (isLoading) {
    return (
      <div className="page bilateral-page">
        <div className="loading">Loading bilateral relationship data...</div>
      </div>
    )
  }

  if (!overview) {
    return (
      <div className="page bilateral-page">
        <div className="error">Failed to load bilateral relationship data</div>
      </div>
    )
  }

  return (
    <div className="page bilateral-page">
      <header className="bilateral-header">
        <div className="bilateral-title">
          <h1>{overview.influencer}</h1>
          <ArrowRight size={40} className="arrow-icon" />
          <h1>{overview.recipient}</h1>
        </div>
        <div className="bilateral-stats">
          <div className="stat-item">
            <FileText size={24} />
            <div>
              <div className="stat-value">{overview.total_documents.toLocaleString()}</div>
              <div className="stat-label">Total Documents</div>
            </div>
          </div>
          <div className="stat-item">
            <Calendar size={24} />
            <div>
              <div className="stat-value">{overview.recent_events.length}</div>
              <div className="stat-label">Recent Events</div>
            </div>
          </div>
          <div className="stat-item">
            <div style={{ fontSize: '24px' }}>📊</div>
            <div>
              <div className="stat-value">{overview.top_categories.length}</div>
              <div className="stat-label">Active Categories</div>
            </div>
          </div>
        </div>
      </header>

      {/* Key Insights */}
      <div className="chart-card" style={{ background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)', border: '1px solid #bae6fd' }}>
        <h3 style={{ color: '#0c4a6e', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          💡 Key Insights
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1', fontWeight: 600, marginBottom: '0.5rem' }}>Most Active Category</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0c4a6e' }}>
              {overview.top_categories[0]?.category || 'N/A'}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1' }}>
              {overview.top_categories[0]?.count.toLocaleString() || 0} documents
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1', fontWeight: 600, marginBottom: '0.5rem' }}>Recent Activity</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0c4a6e' }}>
              {overview.activity_trend[overview.activity_trend.length - 1]?.count || 0}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1' }}>
              documents this week
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1', fontWeight: 600, marginBottom: '0.5rem' }}>Activity Trend</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0c4a6e' }}>
              {overview.activity_trend.length > 1
                ? (overview.activity_trend[overview.activity_trend.length - 1]?.count || 0) > (overview.activity_trend[overview.activity_trend.length - 2]?.count || 0)
                  ? '📈 Increasing'
                  : '📉 Decreasing'
                : '➡️ Stable'
              }
            </div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1' }}>
              over last 12 weeks
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1', fontWeight: 600, marginBottom: '0.5rem' }}>Weekly Average</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0c4a6e' }}>
              {Math.round(overview.activity_trend.reduce((sum, item) => sum + item.count, 0) / Math.max(overview.activity_trend.length, 1))}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#0369a1' }}>
              documents per week
            </div>
          </div>
        </div>
      </div>

      {/* Activity Trend */}
      <div className="chart-card">
        <h3>Activity Trend (Last 12 Weeks)</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={overview.activity_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="week" tick={{ fontSize: 12 }} />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="count" stroke="#1a365d" strokeWidth={2} name="Documents" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Top Categories */}
      <div className="chart-card">
        <h3>Top Categories</h3>
        <div className="charts-row">
          <div className="chart-half">
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={overview.top_categories}
                  dataKey="count"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={(entry: any) => entry.category}
                >
                  {overview.top_categories.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-half">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={overview.top_categories} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="category" width={100} />
                <Tooltip />
                <Bar dataKey="count" fill="#1a365d" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Recent Events */}
      {overview.recent_events.length > 0 && (
        <div className="section">
          <h2>
            <Calendar size={24} />
            Recent Events
          </h2>
          <div className="events-grid">
            {overview.recent_events.map((event) => (
              <div key={event.id} className="event-card">
                <div className="event-header">
                  <h4>{event.event_name}</h4>
                  <span className="event-date">{new Date(event.event_date).toLocaleDateString()}</span>
                </div>
                <p className="event-summary">{event.summary}</p>
                <div className="event-footer">
                  <span className="mention-count">{event.total_mentions} mentions</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Activities */}
      <div className="section">
        <h2>
          <FileText size={24} />
          Recent Activities
        </h2>
        <div className="activities-list">
          {overview.recent_activities.map((activity) => (
            <div key={activity.doc_id} className="activity-card">
              <div className="activity-header">
                <h4>{activity.title}</h4>
                <span className="activity-date">{new Date(activity.date).toLocaleDateString()}</span>
              </div>
              {activity.distilled_text && (
                <p className="activity-text">{activity.distilled_text}</p>
              )}
              {activity.event_name && (
                <div className="activity-meta">
                  <span className="event-tag">
                    <Calendar size={14} />
                    {activity.event_name}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
