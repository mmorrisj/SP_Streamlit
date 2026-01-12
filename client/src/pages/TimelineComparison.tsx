import { useState, useMemo } from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { TrendingUp, Calendar, Users, BarChart3, ExternalLink } from 'lucide-react'
import { fetchInfluencerMetrics, fetchFilterOptions, fetchEventTimeline } from '../api/client'
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
  const [startDate, setStartDate] = useState<string>('2024-08-01')
  const [endDate, setEndDate] = useState<string>('2026-01-01')
  const [showEventGantt, setShowEventGantt] = useState<boolean>(true)
  const [consolidationLevel, setConsolidationLevel] = useState<'daily' | 'weekly' | 'monthly' | 'overall'>('monthly')

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

  // Fetch event timeline for the first selected influencer
  const { data: eventTimeline, isLoading: isLoadingEvents } = useQuery({
    queryKey: ['eventTimeline', selectedInfluencers[0], startDate, endDate, consolidationLevel],
    queryFn: () => fetchEventTimeline(selectedInfluencers[0] || 'China', startDate, endDate, consolidationLevel),
    enabled: selectedInfluencers.length > 0 && showEventGantt,
  })

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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label style={{ fontSize: '0.875rem', fontWeight: 500, color: '#666' }}>
              Event Consolidation Level
            </label>
            <select
              value={consolidationLevel}
              onChange={(e) => setConsolidationLevel(e.target.value as 'daily' | 'weekly' | 'monthly' | 'overall')}
              style={{
                padding: '0.5rem 0.75rem',
                border: '1px solid #ddd',
                borderRadius: '8px',
                fontSize: '1rem',
                backgroundColor: 'white',
                cursor: 'pointer',
              }}
            >
              <option value="daily">Daily (61 events)</option>
              <option value="weekly">Weekly (14 events)</option>
              <option value="monthly">Monthly (2 events)</option>
              <option value="overall">Overall</option>
            </select>
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

      {/* Event Timeline Gantt Chart */}
      {selectedInfluencers.length > 0 && showEventGantt && (
        <div className="chart-card full-width" style={{ marginTop: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
              <BarChart3 size={20} />
              Event Timeline - {selectedInfluencers[0]}
            </h3>
            <button
              onClick={() => setShowEventGantt(!showEventGantt)}
              style={{
                padding: '0.5rem 1rem',
                background: '#f8f9fa',
                border: '1px solid #ddd',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.875rem'
              }}
            >
              Hide Events
            </button>
          </div>

          {isLoadingEvents ? (
            <div style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>
              Loading event timeline...
            </div>
          ) : eventTimeline && eventTimeline.events.length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <div style={{ minWidth: '800px' }}>
                {/* Gantt Chart Header */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '300px 1fr',
                  borderBottom: '2px solid #ddd',
                  padding: '0.75rem 0',
                  fontWeight: 600,
                  fontSize: '0.875rem',
                  color: '#666'
                }}>
                  <div style={{ paddingLeft: '1rem' }}>Event Name</div>
                  <div style={{ paddingLeft: '1rem' }}>Timeline (Article Density)</div>
                </div>

                {/* Gantt Chart Rows */}
                {eventTimeline.events.map((event, idx) => {
                  // Calculate date range and bar position
                  const firstDate = new Date(event.date_range.first)
                  const lastDate = new Date(event.date_range.last === 'Unknown' ? event.date_range.first : event.date_range.last)
                  const rangeStart = new Date(startDate)
                  const rangeEnd = new Date(endDate)

                  // Calculate percentages for positioning
                  const totalRange = rangeEnd.getTime() - rangeStart.getTime()
                  const eventStart = ((firstDate.getTime() - rangeStart.getTime()) / totalRange) * 100
                  const eventWidth = ((lastDate.getTime() - firstDate.getTime()) / totalRange) * 100 || 2 // Minimum 2% width

                  // Get max article count for scaling
                  const articleCounts = Object.values(event.daily_article_counts)
                  const maxCount = Math.max(...articleCounts, 1)

                  // Color based on category
                  const categoryColors: Record<string, string> = {
                    'Economic': '#16a34a',
                    'Diplomacy': '#0891b2',
                    'Military': '#dc2626',
                    'Social': '#9333ea',
                    'Technology': '#ea580c'
                  }
                  const barColor = categoryColors[event.category] || '#666'

                  return (
                    <div
                      key={idx}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '300px 1fr',
                        borderBottom: '1px solid #eee',
                        padding: '0.75rem 0',
                        fontSize: '0.875rem'
                      }}
                    >
                      {/* Event Name Column */}
                      <div style={{
                        paddingLeft: '1rem',
                        paddingRight: '0.5rem',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.25rem'
                      }}>
                        <div style={{ fontWeight: 500, lineHeight: 1.3 }}>
                          {event.event_name}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#666' }}>
                          <span style={{
                            background: `${barColor}20`,
                            color: barColor,
                            padding: '2px 6px',
                            borderRadius: '4px',
                            marginRight: '0.5rem'
                          }}>
                            {event.category}
                          </span>
                          {event.materiality.toFixed(1)} materiality
                        </div>
                      </div>

                      {/* Timeline Bar Column */}
                      <div style={{ position: 'relative', paddingLeft: '1rem', paddingRight: '1rem' }}>
                        <div style={{
                          position: 'relative',
                          height: '40px',
                          background: '#f8f9fa',
                          borderRadius: '4px'
                        }}>
                          {/* Timeline Bar */}
                          <div
                            style={{
                              position: 'absolute',
                              left: `${Math.max(0, eventStart)}%`,
                              width: `${Math.min(100 - eventStart, eventWidth)}%`,
                              height: '100%',
                              background: `linear-gradient(to right, ${barColor}60, ${barColor})`,
                              borderRadius: '4px',
                              border: `1px solid ${barColor}`,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-around',
                              overflow: 'hidden'
                            }}
                          >
                            {/* Article density indicators */}
                            {Object.entries(event.daily_article_counts).map(([date, count], dIdx) => {
                              const datePos = new Date(date)
                              const relativePos = ((datePos.getTime() - firstDate.getTime()) / (lastDate.getTime() - firstDate.getTime())) * 100
                              const intensity = count / maxCount

                              return (
                                <div
                                  key={dIdx}
                                  title={`${date}: ${count} articles`}
                                  style={{
                                    position: 'absolute',
                                    left: `${relativePos}%`,
                                    width: '4px',
                                    height: `${20 + (intensity * 60)}%`,
                                    background: barColor,
                                    borderRadius: '2px',
                                    opacity: 0.7 + (intensity * 0.3)
                                  }}
                                />
                              )
                            })}
                          </div>

                          {/* Tooltip on hover */}
                          <div
                            title={`${event.event_name}\n${event.date_range.first} to ${event.date_range.last}\n${event.source_doc_ids.length} documents\n${event.event_summary.substring(0, 150)}...`}
                            style={{
                              position: 'absolute',
                              left: 0,
                              top: 0,
                              width: '100%',
                              height: '100%',
                              cursor: 'pointer'
                            }}
                            onClick={() => {
                              if (event.atom_search_url) {
                                window.open(event.atom_search_url, '_blank')
                              }
                            }}
                          />
                        </div>

                        {/* Date labels */}
                        <div style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: '0.7rem',
                          color: '#999',
                          marginTop: '0.25rem'
                        }}>
                          <span>{event.date_range.first}</span>
                          {event.date_range.last !== 'Unknown' && event.date_range.last !== event.date_range.first && (
                            <span>{event.date_range.last}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Legend */}
              <div style={{
                marginTop: '1.5rem',
                padding: '1rem',
                background: '#f8f9fa',
                borderRadius: '8px',
                fontSize: '0.875rem'
              }}>
                <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>Legend:</div>
                <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div style={{ width: '20px', height: '4px', background: '#16a34a', borderRadius: '2px' }} />
                    <span>Economic</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div style={{ width: '20px', height: '4px', background: '#0891b2', borderRadius: '2px' }} />
                    <span>Diplomacy</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div style={{ width: '20px', height: '4px', background: '#dc2626', borderRadius: '2px' }} />
                    <span>Military</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div style={{ width: '20px', height: '4px', background: '#9333ea', borderRadius: '2px' }} />
                    <span>Social</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <ExternalLink size={14} />
                    <span>Click event bar to view source documents in ATOM</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span>Bar height = article density for that date</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>
              No events found for this date range
            </div>
          )}
        </div>
      )}

      {!showEventGantt && selectedInfluencers.length > 0 && (
        <div style={{ marginTop: '2rem', textAlign: 'center' }}>
          <button
            onClick={() => setShowEventGantt(true)}
            style={{
              padding: '0.75rem 1.5rem',
              background: '#0369a1',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '1rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}
          >
            <BarChart3 size={20} />
            Show Event Timeline
          </button>
        </div>
      )}
    </div>
  )
}
