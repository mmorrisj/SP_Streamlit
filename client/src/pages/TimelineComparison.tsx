import { useState, useMemo } from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { TrendingUp, Calendar, Users } from 'lucide-react'
import { fetchInfluencerMetrics, fetchFilterOptions } from '../api/client'
import './Pages.css'

const CHART_COLORS = [
  '#1a365d', // Dark blue
  '#dc2626', // Red
  '#16a34a', // Green
  '#9333ea', // Purple
  '#ea580c', // Orange
  '#0891b2', // Cyan
  '#ca8a04', // Yellow
  '#e11d48', // Pink
]

export default function TimelineComparison() {
  const [selectedInfluencers, setSelectedInfluencers] = useState<string[]>(['China'])
  const [startDate, setStartDate] = useState<string>('2024-01-01')
  const [endDate, setEndDate] = useState<string>('2024-12-31')

  // Fetch available countries for the dropdown
  const { data: filterOptions } = useQuery({
    queryKey: ['filterOptions'],
    queryFn: fetchFilterOptions,
  })

  // Fetch metrics for all selected influencers using useQueries
  const influencerQueries = useQueries({
    queries: selectedInfluencers.map(influencer => ({
      queryKey: ['influencerMetrics', influencer],
      queryFn: () => fetchInfluencerMetrics(influencer),
      enabled: selectedInfluencers.length > 0,
    })),
  })

  // Check if any queries are loading
  const isLoading = influencerQueries.some(query => query.isLoading)
  const hasError = influencerQueries.some(query => query.error)

  // Combine all influencer data into a single timeline dataset
  const combinedTimelineData = useMemo(() => {
    if (isLoading || hasError) return []

    // Get all unique months across all influencers
    const monthsSet = new Set<string>()
    influencerQueries.forEach(query => {
      query.data?.monthly_trend?.forEach(item => {
        const date = new Date(item.month)
        const queryDate = new Date(startDate)
        const queryEndDate = new Date(endDate)

        if (date >= queryDate && date <= queryEndDate) {
          monthsSet.add(item.month)
        }
      })
    })

    const sortedMonths = Array.from(monthsSet).sort()

    // Create combined data structure
    return sortedMonths.map(month => {
      const dataPoint: any = { month }

      selectedInfluencers.forEach((influencer, idx) => {
        const query = influencerQueries[idx]
        const monthData = query.data?.monthly_trend?.find(item => item.month === month)
        dataPoint[influencer] = monthData?.count || 0
      })

      return dataPoint
    })
  }, [influencerQueries, selectedInfluencers, startDate, endDate, isLoading, hasError])

  // Calculate summary statistics
  const summaryStats = useMemo(() => {
    return selectedInfluencers.map((influencer, idx) => {
      const query = influencerQueries[idx]
      const filteredData = query.data?.monthly_trend?.filter(item => {
        const date = new Date(item.month)
        return date >= new Date(startDate) && date <= new Date(endDate)
      }) || []

      const total = filteredData.reduce((sum, item) => sum + item.count, 0)
      const avg = filteredData.length > 0 ? total / filteredData.length : 0
      const max = Math.max(...filteredData.map(item => item.count), 0)

      return { influencer, total, avg, max }
    })
  }, [influencerQueries, selectedInfluencers, startDate, endDate])

  const handleInfluencerToggle = (country: string) => {
    setSelectedInfluencers(prev => {
      if (prev.includes(country)) {
        return prev.filter(c => c !== country)
      } else {
        return [...prev, country]
      }
    })
  }

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading timeline data...</div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <TrendingUp size={32} />
          Timeline Comparison
        </h1>
        <p>Compare activity trends across multiple influencers over time</p>
      </header>

      {/* Date Range Selection */}
      <div className="chart-card" style={{ marginBottom: '2rem' }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
          <Calendar size={20} />
          Date Range
        </h3>
        <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label style={{ fontSize: '0.875rem', fontWeight: 500, color: '#666' }}>
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              style={{
                padding: '0.5rem 0.75rem',
                border: '1px solid #ddd',
                borderRadius: '8px',
                fontSize: '1rem',
              }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label style={{ fontSize: '0.875rem', fontWeight: 500, color: '#666' }}>
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              style={{
                padding: '0.5rem 0.75rem',
                border: '1px solid #ddd',
                borderRadius: '8px',
                fontSize: '1rem',
              }}
            />
          </div>
        </div>
      </div>

      {/* Influencer Selection */}
      <div className="chart-card" style={{ marginBottom: '2rem' }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
          <Users size={20} />
          Select Influencers ({selectedInfluencers.length} selected)
        </h3>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
          gap: '0.75rem'
        }}>
          {filterOptions?.countries?.map(country => (
            <label
              key={country}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.5rem 0.75rem',
                background: selectedInfluencers.includes(country) ? '#e0f2fe' : '#f8f9fa',
                border: selectedInfluencers.includes(country) ? '2px solid #0369a1' : '1px solid #ddd',
                borderRadius: '8px',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <input
                type="checkbox"
                checked={selectedInfluencers.includes(country)}
                onChange={() => handleInfluencerToggle(country)}
                style={{ cursor: 'pointer' }}
              />
              <span style={{ fontWeight: selectedInfluencers.includes(country) ? 600 : 400 }}>
                {country}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Summary Statistics */}
      {selectedInfluencers.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
          gap: '1rem',
          marginBottom: '2rem'
        }}>
          {summaryStats.map((stat, idx) => (
            <div
              key={stat.influencer}
              className="stat-card"
              style={{ borderLeft: `4px solid ${CHART_COLORS[idx % CHART_COLORS.length]}` }}
            >
              <h3>{stat.influencer}</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '0.875rem', color: '#666' }}>Total Documents:</span>
                  <span style={{ fontWeight: 600 }}>{stat.total.toLocaleString()}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '0.875rem', color: '#666' }}>Monthly Average:</span>
                  <span style={{ fontWeight: 600 }}>{Math.round(stat.avg).toLocaleString()}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '0.875rem', color: '#666' }}>Peak Month:</span>
                  <span style={{ fontWeight: 600 }}>{stat.max.toLocaleString()}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Timeline Chart */}
      {selectedInfluencers.length > 0 ? (
        <div className="chart-card full-width">
          <h3>Activity Timeline</h3>
          <ResponsiveContainer width="100%" height={500}>
            <LineChart data={combinedTimelineData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 12 }}
                angle={-45}
                textAnchor="end"
                height={80}
              />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                contentStyle={{
                  background: 'white',
                  border: '1px solid #ddd',
                  borderRadius: '8px',
                  padding: '0.75rem'
                }}
              />
              <Legend
                wrapperStyle={{ paddingTop: '1rem' }}
                iconType="line"
              />
              {selectedInfluencers.map((influencer, idx) => (
                <Line
                  key={influencer}
                  type="monotone"
                  dataKey={influencer}
                  stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="empty-state-card">
          <Users size={48} style={{ opacity: 0.3 }} />
          <h3>No Influencers Selected</h3>
          <p>Please select at least one influencer to view the timeline comparison</p>
        </div>
      )}
    </div>
  )
}
