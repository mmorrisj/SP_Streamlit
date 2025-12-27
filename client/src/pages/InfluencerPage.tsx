import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell } from 'recharts'
import './Pages.css'
import './InfluencerPage.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a2c4e8']

interface InfluencerOverview {
  country: string
  total_documents: number
  total_recipients: number
  top_categories: { category: string; count: number }[]
  recent_activity_trend: { week: string; count: number }[]
  top_recipients: { country: string; count: number }[]
}

interface RecentActivity {
  activities: {
    doc_id: string
    title: string
    date: string
    distilled_text: string
    event_name: string
    salience_justification: string
    recipient_country: string
  }[]
  total: number
}

interface InfluencerEvent {
  id: string
  event_name: string
  event_date: string
  summary: string
  initiating_country: string
  total_mentions: number
}

const fetchInfluencerOverview = async (country: string): Promise<InfluencerOverview> => {
  const response = await fetch(`http://localhost:8000/api/influencer/${country}/overview`)
  if (!response.ok) throw new Error('Failed to fetch overview')
  return response.json()
}

const fetchRecentActivities = async (country: string): Promise<RecentActivity> => {
  const response = await fetch(`http://localhost:8000/api/influencer/${country}/recent-activities?limit=10`)
  if (!response.ok) throw new Error('Failed to fetch activities')
  return response.json()
}

const fetchInfluencerEvents = async (country: string): Promise<{ events: InfluencerEvent[] }> => {
  const response = await fetch(`http://localhost:8000/api/influencer/${country}/events?limit=8`)
  if (!response.ok) throw new Error('Failed to fetch events')
  return response.json()
}

export default function InfluencerPage() {
  const { country } = useParams<{ country: string }>()

  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['influencerOverview', country],
    queryFn: () => fetchInfluencerOverview(country!),
    enabled: !!country,
  })

  const { data: activities, isLoading: activitiesLoading } = useQuery({
    queryKey: ['recentActivities', country],
    queryFn: () => fetchRecentActivities(country!),
    enabled: !!country,
  })

  const { data: events, isLoading: eventsLoading } = useQuery({
    queryKey: ['influencerEvents', country],
    queryFn: () => fetchInfluencerEvents(country!),
    enabled: !!country,
  })

  if (overviewLoading) {
    return (
      <div className="page">
        <div className="loading">Loading {country} data...</div>
      </div>
    )
  }

  if (!overview) {
    return (
      <div className="page">
        <div className="error">
          <h3>No data available for {country}</h3>
        </div>
      </div>
    )
  }

  return (
    <div className="page influencer-page">
      <header className="influencer-header">
        <div className="influencer-title">
          <h1>{country}</h1>
          <p className="influencer-subtitle">Soft Power Activities & Influence</p>
        </div>
        <div className="influencer-stats-inline">
          <div className="inline-stat">
            <span className="inline-stat-value">{overview.total_documents.toLocaleString()}</span>
            <span className="inline-stat-label">Documents</span>
          </div>
          <div className="inline-stat">
            <span className="inline-stat-value">{overview.total_recipients}</span>
            <span className="inline-stat-label">Recipients</span>
          </div>
        </div>
      </header>

      {/* Overview Section */}
      <div className="section">
        <h2>Activity Overview</h2>
        <div className="charts-grid">
          <div className="chart-card">
            <h3>Recent Activity Trend</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={overview.recent_activity_trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="week" tick={{ fontSize: 11 }} />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#1a365d" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-card">
            <h3>Top Categories</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={overview.top_categories}
                  dataKey="count"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={(entry: any) => `${entry.category}`}
                >
                  {overview.top_categories.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Top Recipients */}
      <div className="section">
        <h2>Top Recipients</h2>
        <div className="chart-card">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={overview.top_recipients} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="country" type="category" width={120} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#1a365d" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Events */}
      {!eventsLoading && events && events.events.length > 0 && (
        <div className="section">
          <h2>Recent Events</h2>
          <div className="events-grid">
            {events.events.map((event) => (
              <div key={event.id} className="event-card">
                <div className="event-header">
                  <h4>{event.event_name}</h4>
                  <span className="event-date">{event.event_date}</span>
                </div>
                {event.summary && (
                  <p className="event-summary">{event.summary}</p>
                )}
                <div className="event-meta">
                  <span>{event.total_mentions} mentions</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Activities */}
      {!activitiesLoading && activities && activities.activities.length > 0 && (
        <div className="section">
          <h2>Recent Activities</h2>
          <div className="activities-list">
            {activities.activities.slice(0, 6).map((activity) => (
              <div key={activity.doc_id} className="activity-card">
                <div className="activity-header">
                  <h4>{activity.title || 'Untitled'}</h4>
                  <div className="activity-meta">
                    <span className="activity-date">{activity.date}</span>
                    <span className="activity-recipient">{activity.recipient_country}</span>
                  </div>
                </div>
                {activity.distilled_text && (
                  <p className="activity-text">{activity.distilled_text}</p>
                )}
                {activity.event_name && (
                  <div className="activity-event">
                    <strong>Event:</strong> {activity.event_name}
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
