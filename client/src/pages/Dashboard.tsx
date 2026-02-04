import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, Legend } from 'recharts'
import { fetchDocumentStats, fetchFilterOptions } from '../api/client'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a5c4e0', '#c4d9ed', '#e0ebf5']
const INFLUENCER_COLORS: Record<string, string> = {
  'China': '#e74c3c',
  'Russia': '#3498db',
  'Iran': '#f39c12',
  'Turkey': '#9b59b6',
  'United States': '#2ecc71'
}

// Muted/lighter colors for recipients
const RECIPIENT_COLORS: Record<string, string> = {
  'Egypt': '#34495e',
  'Ethiopia': '#7f8c8d',
  'Kenya': '#95a5a6',
  'Nigeria': '#bdc3c7',
  'South Africa': '#2c3e50',
  'Algeria': '#1abc9c',
  'Morocco': '#16a085',
  'Tanzania': '#27ae60',
  'Sudan': '#229954',
  'Uganda': '#f39c12',
  'Ghana': '#d68910',
  'Mozambique': '#e67e22',
  'Angola': '#ca6f1e',
  'Somalia': '#e74c3c',
  'Zambia': '#ec7063',
  'Zimbabwe': '#af7ac5',
  'Mali': '#8e44ad',
  'Rwanda': '#5499c7',
  'Tunisia': '#5dade2',
  'Senegal': '#48c9b0'
}

export default function Dashboard() {
  const [selectedInfluencers, setSelectedInfluencers] = useState<Record<string, boolean>>({
    'China': true,
    'Russia': true,
    'Iran': true,
    'Turkey': true,
    'United States': true
  })
  const [selectedRecipients, setSelectedRecipients] = useState<Record<string, boolean>>({})
  const [showTotal, setShowTotal] = useState<boolean>(true)
  const [filterInfluencer, setFilterInfluencer] = useState<string>('ALL')
  const [filterRecipient, setFilterRecipient] = useState<string>('ALL')

  // Fetch filter options
  const { data: filterOptions } = useQuery({
    queryKey: ['filterOptions'],
    queryFn: fetchFilterOptions,
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['documentStats', filterInfluencer, filterRecipient],
    queryFn: () => fetchDocumentStats({
      influencer_country: filterInfluencer !== 'ALL' ? filterInfluencer : undefined,
      recipient_country: filterRecipient !== 'ALL' ? filterRecipient : undefined
    }),
  })

  // Merge weekly data for influencers and recipients (filtered client-side)
  const mergedWeeklyData = useMemo(() => {
    if (!data?.documents_by_week || !data?.documents_by_week_by_influencer || !data?.documents_by_week_by_recipient) return []

    const weekMap = new Map<string, any>()

    // Add total count for each week
    data.documents_by_week.forEach(item => {
      weekMap.set(item.week, { week: item.week, Total: item.count })
    })

    // Add influencer-specific counts
    Object.entries(data.documents_by_week_by_influencer).forEach(([influencer, weeks]) => {
      weeks.forEach(item => {
        const existing = weekMap.get(item.week) || { week: item.week, Total: 0 }
        weekMap.set(item.week, { ...existing, [influencer]: item.count })
      })
    })

    // Get list of selected influencers for filtering recipient data
    const activeInfluencers = Object.entries(selectedInfluencers)
      .filter(([_, isSelected]) => isSelected)
      .map(([influencer]) => influencer)

    // Add recipient-specific counts (filtered by selected influencers)
    Object.entries(data.documents_by_week_by_recipient).forEach(([recipient, weeks]: [string, any[]]) => {
      weeks.forEach(weekData => {
        const existing = weekMap.get(weekData.week) || { week: weekData.week, Total: 0 }

        // Sum up counts from only the selected influencers
        const recipientCount = activeInfluencers.reduce((sum, influencer) => {
          return sum + (weekData.by_influencer?.[influencer] || 0)
        }, 0)

        weekMap.set(weekData.week, { ...existing, [recipient]: recipientCount })
      })
    })

    return Array.from(weekMap.values()).sort((a, b) => a.week.localeCompare(b.week))
  }, [data, selectedInfluencers])

  const toggleInfluencer = (influencer: string) => {
    setSelectedInfluencers(prev => ({ ...prev, [influencer]: !prev[influencer] }))
  }

  const toggleRecipient = (recipient: string) => {
    setSelectedRecipients(prev => ({ ...prev, [recipient]: !prev[recipient] }))
  }

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading dashboard data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load data</h3>
          <p>Make sure the API server is running</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Soft Power Dashboard</h1>
        <p>Analytics overview of diplomatic documents and events</p>
      </header>

      {/* Filter Controls */}
      <div style={{
        marginBottom: '1.5rem',
        padding: '1rem',
        backgroundColor: '#f8f9fa',
        borderRadius: '8px',
        display: 'flex',
        gap: '2rem',
        alignItems: 'center',
        flexWrap: 'wrap'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label style={{ fontWeight: 600 }}>Influencer:</label>
          <select
            value={filterInfluencer}
            onChange={(e) => setFilterInfluencer(e.target.value)}
            style={{ padding: '0.5rem', borderRadius: '4px', border: '1px solid #cbd5e0' }}
          >
            <option value="ALL">All Influencers</option>
            {(filterOptions?.countries || []).map(country => (
              <option key={country} value={country}>{country}</option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label style={{ fontWeight: 600 }}>Recipient:</label>
          <select
            value={filterRecipient}
            onChange={(e) => setFilterRecipient(e.target.value)}
            style={{ padding: '0.5rem', borderRadius: '4px', border: '1px solid #cbd5e0' }}
          >
            <option value="ALL">All Recipients</option>
            {(filterOptions?.recipients || []).map(country => (
              <option key={country} value={country}>{country}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Documents per Week with Toggles */}
      <div className="chart-card" style={{ marginBottom: '2rem' }}>
        <h3>Documents per Week</h3>

        {/* Total Toggle */}
        <div style={{ marginBottom: '1rem', paddingBottom: '0.5rem', borderBottom: '1px solid #e2e8f0' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={showTotal}
              onChange={() => setShowTotal(!showTotal)}
            />
            <span style={{
              width: '12px',
              height: '12px',
              backgroundColor: '#1a365d',
              borderRadius: '2px'
            }} />
            <span>Total Documents</span>
          </label>
        </div>

        {/* Influencer Toggles */}
        <div style={{ marginBottom: '1rem', paddingBottom: '0.5rem', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.9rem', color: '#4a5568' }}>Influencers:</div>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            {Object.entries(selectedInfluencers).map(([influencer, selected]) => (
              <label key={influencer} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggleInfluencer(influencer)}
                />
                <span style={{
                  width: '12px',
                  height: '12px',
                  backgroundColor: INFLUENCER_COLORS[influencer] || '#666',
                  borderRadius: '2px'
                }} />
                <span>{influencer}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Recipient Toggles */}
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.9rem', color: '#4a5568' }}>Recipients:</div>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            {(filterOptions?.recipients || []).map(recipient => (
              <label key={recipient} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={selectedRecipients[recipient] || false}
                  onChange={() => toggleRecipient(recipient)}
                />
                <span style={{
                  width: '12px',
                  height: '12px',
                  backgroundColor: RECIPIENT_COLORS[recipient] || '#95a5a6',
                  borderRadius: '2px'
                }} />
                <span>{recipient}</span>
              </label>
            ))}
          </div>
        </div>

        <ResponsiveContainer width="100%" height={400}>
          <LineChart data={mergedWeeklyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="week" tick={{ fontSize: 12 }} />
            <YAxis />
            <Tooltip />
            <Legend />

            {/* Total line */}
            {showTotal && (
              <Line
                type="monotone"
                dataKey="Total"
                stroke="#1a365d"
                strokeWidth={3}
                dot={false}
                name="Total Documents"
              />
            )}

            {/* Influencer lines */}
            {Object.entries(selectedInfluencers).map(([influencer, selected]) =>
              selected ? (
                <Line
                  key={influencer}
                  type="monotone"
                  dataKey={influencer}
                  stroke={INFLUENCER_COLORS[influencer] || '#666'}
                  strokeWidth={2}
                  dot={false}
                  name={influencer}
                />
              ) : null
            )}

            {/* Recipient lines */}
            {Object.entries(selectedRecipients).map(([recipient, selected]) =>
              selected ? (
                <Line
                  key={recipient}
                  type="monotone"
                  dataKey={recipient}
                  stroke={RECIPIENT_COLORS[recipient] || '#95a5a6'}
                  strokeWidth={2}
                  dot={false}
                  name={recipient}
                />
              ) : null
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <h3>Total Documents</h3>
          <p className="stat-value">{data?.total_documents?.toLocaleString() || 0}</p>
        </div>
        <div className="stat-card">
          <h3>Total Events</h3>
          <p className="stat-value">{data?.total_events?.toLocaleString() || 0}</p>
        </div>
      </div>

      <div className="charts-grid">

        {/* Top Influencers */}
        <div className="chart-card">
          <h3>Top Influencers by Document Count</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data?.top_countries || []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="country" type="category" width={100} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#1a365d" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Top Recipients */}
        <div className="chart-card">
          <h3>Top Recipients by Document Count</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data?.top_recipients || []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="country" type="category" width={100} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#2d4a7c" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Category Distribution */}
        <div className="chart-card">
          <h3>Category Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={data?.category_distribution || []}
                dataKey="count"
                nameKey="category"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry: any) => {
                  const total = (data?.category_distribution || []).reduce((sum, item) => sum + item.count, 0)
                  const percent = ((entry.count / total) * 100).toFixed(0)
                  return `${entry.category} (${percent}%)`
                }}
              >
                {(data?.category_distribution || []).map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Subcategory Distribution */}
        <div className="chart-card">
          <h3>Top Subcategories</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={data?.subcategory_distribution || []}
                dataKey="count"
                nameKey="subcategory"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry: any) => {
                  const total = (data?.subcategory_distribution || []).reduce((sum, item) => sum + item.count, 0)
                  const percent = ((entry.count / total) * 100).toFixed(0)
                  return `${entry.subcategory} (${percent}%)`
                }}
              >
                {(data?.subcategory_distribution || []).map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
