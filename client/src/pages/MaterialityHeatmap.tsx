import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Flame, Calendar } from 'lucide-react'
import { fetchMaterialityHeatmap } from '../api/client'
import './Pages.css'

const COUNTRY_ORDER = ['China', 'Iran', 'Russia', 'Turkey', 'United States']

// material_score is a ~1-10 scale; monthly averages cluster in ~3.2-6.0, so the ramp is
// calibrated across that band (not 0-4, which made every cell red).
function getHeatColor(score: number | null): string {
  if (score == null) return '#f1f5f9'
  if (score >= 5.5) return '#b91c1c'  // deep red
  if (score >= 5.0) return '#f97316'  // orange
  if (score >= 4.5) return '#facc15'  // amber
  if (score >= 4.0) return '#a3e635'  // lime
  if (score >= 3.5) return '#4ade80'  // green
  return '#bbf7d0'                     // pale green (< 3.5)
}

function getTextColor(score: number | null): string {
  if (score == null) return '#94a3b8'
  if (score >= 5.0) return 'white'
  return '#1e293b'
}

export default function MaterialityHeatmap() {
  const { data, isLoading } = useQuery({
    queryKey: ['materiality-heatmap'],
    queryFn: fetchMaterialityHeatmap,
  })

  // Build monthly matrix grouped by country and month
  const matrixByCountry = useMemo(() => {
    if (!data?.monthly_matrix) return {}
    const grouped: Record<string, Record<string, { avg: number | null; count: number; docs: number }>> = {}
    for (const entry of data.monthly_matrix) {
      if (!grouped[entry.country]) grouped[entry.country] = {}
      grouped[entry.country][entry.month] = {
        avg: entry.avg_materiality,
        count: entry.event_count,
        docs: entry.total_docs,
      }
    }
    return grouped
  }, [data])

  // Get all unique months sorted
  const allMonths = useMemo(() => {
    if (!data?.monthly_matrix) return []
    const set = new Set(data.monthly_matrix.map(e => e.month))
    return Array.from(set).sort()
  }, [data])

  // Daily heatmap: get last 90 days for the "recent activity" strip
  const recentDailyByCountry = useMemo(() => {
    if (!data?.daily_heatmap) return {}
    const result: Record<string, { date: string; avg: number | null; count: number }[]> = {}
    for (const [country, days] of Object.entries(data.daily_heatmap)) {
      result[country] = days.slice(-90).map(d => ({
        date: d.date,
        avg: d.avg_materiality,
        count: d.event_count,
      }))
    }
    return result
  }, [data])

  if (isLoading) return <div className="page"><div className="loading">Loading heatmap data...</div></div>

  return (
    <div className="page">
      <header className="page-header">
        <h1>
          <Flame size={28} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          Materiality Heatmap
        </h1>
        <p>Event materiality scores across countries and time periods</p>
      </header>

      {/* Monthly Matrix Table */}
      {allMonths.length > 0 && (
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ fontSize: '1.1rem', color: '#1a365d', marginBottom: '0.75rem' }}>
            <Calendar size={18} style={{ marginRight: 6, verticalAlign: 'middle' }} />
            Monthly Materiality Matrix
          </h2>
          <div className="table-container" style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ fontSize: '0.8rem', minWidth: '600px' }}>
              <thead>
                <tr>
                  <th style={{ position: 'sticky', left: 0, background: '#f8fafc', zIndex: 1 }}>Country</th>
                  {allMonths.map(m => (
                    <th key={m} style={{ textAlign: 'center', padding: '0.5rem 0.375rem', whiteSpace: 'nowrap' }}>
                      {m}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COUNTRY_ORDER.filter(c => matrixByCountry[c]).map(country => (
                  <tr key={country}>
                    <td style={{ fontWeight: 500, position: 'sticky', left: 0, background: 'white', zIndex: 1 }}>
                      {country}
                    </td>
                    {allMonths.map(month => {
                      const cell = matrixByCountry[country]?.[month]
                      return (
                        <td key={month} style={{
                          textAlign: 'center',
                          padding: '0.375rem',
                          backgroundColor: cell ? getHeatColor(cell.avg) : '#f8fafc',
                          color: cell ? getTextColor(cell.avg) : '#d1d5db',
                          fontWeight: cell?.avg != null && cell.avg >= 3 ? 600 : 400,
                          borderRadius: '2px',
                        }}>
                          {cell ? (
                            <div>
                              <div>{cell.avg != null ? cell.avg.toFixed(1) : '—'}</div>
                              <div style={{ fontSize: '0.65rem', opacity: 0.8 }}>{cell.count}e</div>
                            </div>
                          ) : '—'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', fontSize: '0.75rem', color: '#64748b', alignItems: 'center' }}>
            <span>Score:</span>
            {[
              { label: '< 3.5', color: '#bbf7d0' },
              { label: '3.5-4', color: '#4ade80' },
              { label: '4-4.5', color: '#a3e635' },
              { label: '4.5-5', color: '#facc15' },
              { label: '5-5.5', color: '#f97316' },
              { label: '5.5+', color: '#b91c1c' },
            ].map(({ label, color }) => (
              <span key={label} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                <span style={{ width: 14, height: 14, backgroundColor: color, borderRadius: 2, display: 'inline-block' }} />
                {label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Daily Activity Strips (last 90 days) */}
      {Object.keys(recentDailyByCountry).length > 0 && (
        <div>
          <h2 style={{ fontSize: '1.1rem', color: '#1a365d', marginBottom: '0.75rem' }}>
            Recent Daily Activity (Last 90 Days)
          </h2>
          {COUNTRY_ORDER.filter(c => recentDailyByCountry[c]).map(country => (
            <div key={country} style={{ marginBottom: '1rem' }}>
              <h3 style={{ fontSize: '0.9rem', color: '#475569', marginBottom: '0.375rem' }}>{country}</h3>
              <div style={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {(recentDailyByCountry[country] || []).map((day, i) => (
                  <div
                    key={i}
                    title={`${day.date}: ${day.avg != null ? day.avg.toFixed(1) : 'N/A'} (${day.count} events)`}
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      backgroundColor: getHeatColor(day.avg),
                      cursor: 'default',
                    }}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {allMonths.length === 0 && Object.keys(recentDailyByCountry).length === 0 && (
        <div className="empty-state-card">
          <Flame size={48} />
          <h3>No Materiality Data</h3>
          <p>Materiality scores will appear here once events have been analyzed.</p>
        </div>
      )}
    </div>
  )
}
