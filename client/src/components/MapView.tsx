import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchBilateralMapData } from '../api/client'

const INFLUENCER_COLORS: Record<string, string> = {
  'China': '#e74c3c',
  'Russia': '#3498db',
  'Iran': '#f39c12',
  'Turkey': '#9b59b6',
  'United States': '#2ecc71',
  'ALL': '#34495e'
}

interface MapViewProps {
  influencers: string[]
}

export default function MapView({ influencers }: MapViewProps) {
  const [selectedInfluencer, setSelectedInfluencer] = useState<string>('ALL')
  const [selectedMetric, setSelectedMetric] = useState<'document_count' | 'event_count' | 'avg_materiality'>('document_count')

  const { data: mapData, isLoading, error } = useQuery({
    queryKey: ['bilateralMapData', selectedInfluencer],
    queryFn: () => fetchBilateralMapData(selectedInfluencer === 'ALL' ? undefined : selectedInfluencer),
  })

  const getMetricLabel = (metric: string): string => {
    switch (metric) {
      case 'document_count': return 'Document Count'
      case 'event_count': return 'Event Count'
      case 'avg_materiality': return 'Avg. Materiality'
      default: return metric
    }
  }

  if (error) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: '#e74c3c' }}>
        Error loading map data. Please ensure the API server is running.
      </div>
    )
  }

  const sortedRecipients = mapData?.recipients?.sort((a, b) => b[selectedMetric] - a[selectedMetric]) || []
  const maxValue = sortedRecipients[0]?.[selectedMetric] || 1

  return (
    <div style={{ width: '100%' }}>
      {/* Controls */}
      <div style={{
        marginBottom: '1.5rem',
        display: 'flex',
        gap: '2rem',
        alignItems: 'center',
        flexWrap: 'wrap',
        padding: '1rem 1.5rem',
        backgroundColor: '#f8f9fa',
        borderRadius: '8px',
        border: '1px solid #e0e0e0'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label style={{ fontWeight: 600, fontSize: '0.95rem', color: '#2c3e50' }}>Influencer:</label>
          <select
            value={selectedInfluencer}
            onChange={(e) => setSelectedInfluencer(e.target.value)}
            style={{
              padding: '0.6rem 1.2rem',
              borderRadius: '6px',
              border: '1px solid #cbd5e0',
              fontSize: '0.95rem',
              cursor: 'pointer',
              backgroundColor: 'white',
              fontWeight: 500
            }}
          >
            <option value="ALL">All Influencers</option>
            {influencers.map(inf => (
              <option key={inf} value={inf}>{inf}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label style={{ fontWeight: 600, fontSize: '0.95rem', color: '#2c3e50' }}>Metric:</label>
          <select
            value={selectedMetric}
            onChange={(e) => setSelectedMetric(e.target.value as any)}
            style={{
              padding: '0.6rem 1.2rem',
              borderRadius: '6px',
              border: '1px solid #cbd5e0',
              fontSize: '0.95rem',
              cursor: 'pointer',
              backgroundColor: 'white',
              fontWeight: 500
            }}
          >
            <option value="document_count">Document Count</option>
            <option value="event_count">Event Count</option>
            <option value="avg_materiality">Avg. Materiality Score</option>
          </select>
        </div>

        <div style={{
          marginLeft: 'auto',
          padding: '0.5rem 1rem',
          backgroundColor: INFLUENCER_COLORS[selectedInfluencer],
          color: 'white',
          borderRadius: '6px',
          fontSize: '0.9rem',
          fontWeight: 600
        }}>
          {selectedInfluencer === 'ALL' ? 'All Influencers' : selectedInfluencer} → Recipients
        </div>
      </div>

      {/* Visualization */}
      <div style={{
        backgroundColor: 'white',
        borderRadius: '8px',
        border: '1px solid #e0e0e0',
        padding: '2rem',
        boxShadow: '0 2px 8px rgba(0,0,0,0.08)'
      }}>
        <h3 style={{
          margin: '0 0 1.5rem 0',
          fontSize: '1.3rem',
          color: '#2c3e50',
          borderBottom: '3px solid ' + INFLUENCER_COLORS[selectedInfluencer],
          paddingBottom: '0.75rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>Recipients by {getMetricLabel(selectedMetric)}</span>
          <span style={{ fontSize: '0.9rem', color: '#7f8c8d', fontWeight: 500 }}>
            {sortedRecipients.length} countries
          </span>
        </h3>

        {isLoading ? (
          <div style={{
            textAlign: 'center',
            padding: '4rem',
            color: '#666',
            fontSize: '1.1rem'
          }}>
            Loading data...
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))',
            gap: '1rem'
          }}>
            {sortedRecipients.map((recipient, idx) => {
              const value = recipient[selectedMetric]
              const percentage = (value / maxValue) * 100

              return (
                <div
                  key={recipient.country}
                  style={{
                    padding: '1rem',
                    backgroundColor: '#f8f9fa',
                    borderRadius: '8px',
                    border: '1px solid #e9ecef',
                    transition: 'all 0.2s',
                    cursor: 'pointer'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = '#e3f2fd'
                    e.currentTarget.style.transform = 'scale(1.02)'
                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = '#f8f9fa'
                    e.currentTarget.style.transform = 'scale(1)'
                    e.currentTarget.style.boxShadow = 'none'
                  }}
                >
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '0.75rem'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span style={{
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        color: '#7f8c8d',
                        backgroundColor: 'white',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '4px',
                        minWidth: '30px',
                        textAlign: 'center'
                      }}>
                        #{idx + 1}
                      </span>
                      <span style={{
                        fontSize: '1.1rem',
                        fontWeight: 600,
                        color: '#2c3e50'
                      }}>
                        {recipient.country}
                      </span>
                    </div>
                    <span style={{
                      fontSize: '1.2rem',
                      fontWeight: 700,
                      color: INFLUENCER_COLORS[selectedInfluencer],
                      backgroundColor: 'white',
                      padding: '0.4rem 0.8rem',
                      borderRadius: '6px'
                    }}>
                      {value.toLocaleString()}
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div style={{
                    width: '100%',
                    height: '12px',
                    backgroundColor: '#e9ecef',
                    borderRadius: '6px',
                    overflow: 'hidden',
                    position: 'relative'
                  }}>
                    <div style={{
                      width: `${percentage}%`,
                      height: '100%',
                      backgroundColor: INFLUENCER_COLORS[selectedInfluencer],
                      borderRadius: '6px',
                      transition: 'width 0.3s ease'
                    }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
