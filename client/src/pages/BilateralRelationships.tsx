import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Users, Zap, FileText, Activity } from 'lucide-react'
import PageGuide from '../components/PageGuide'
import './Pages.css'

interface BilateralData {
  initiating_country: string
  recipient_country: string
  count: number
  event_count: number
  avg_materiality: number | null
}

const INFLUENCER_ORDER = ['China', 'Iran', 'Russia', 'Turkey', 'United States']
const INFLUENCER_COLORS: Record<string, string> = {
  'China': '#e74c3c',
  'Russia': '#3498db',
  'Iran': '#f39c12',
  'Turkey': '#9b59b6',
  'United States': '#2ecc71',
}

function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

export default function BilateralRelationships() {
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['bilateral'],
    queryFn: async () => {
      const response = await fetch('/api/bilateral')
      return response.json()
    },
  })

  const relationships: BilateralData[] = data?.relationships || []

  const { influencers, recipients, cellMap, colMax } = useMemo(() => {
    const cellMap = new Map<string, BilateralData>()
    const recipientTotals = new Map<string, number>()
    const present = new Set<string>()
    for (const rel of relationships) {
      cellMap.set(`${rel.initiating_country}|${rel.recipient_country}`, rel)
      present.add(rel.initiating_country)
      recipientTotals.set(
        rel.recipient_country,
        (recipientTotals.get(rel.recipient_country) || 0) + rel.count
      )
    }
    const influencers = INFLUENCER_ORDER.filter(i => present.has(i))
    const recipients = [...recipientTotals.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([r]) => r)
    // Normalize cell shading within each influencer column, not globally —
    // raw volumes across actors reflect source composition (attention bias),
    // so each column shows that influencer's own focus distribution instead.
    const colMax = new Map<string, number>()
    for (const inf of influencers) {
      const max = Math.max(
        1,
        ...relationships.filter(r => r.initiating_country === inf).map(r => r.count)
      )
      colMax.set(inf, max)
    }
    return { influencers, recipients, cellMap, colMax }
  }, [relationships])

  const byInfluencer = useMemo(() => {
    const groups = new Map<string, BilateralData[]>()
    for (const rel of relationships) {
      const list = groups.get(rel.initiating_country) || []
      list.push(rel)
      groups.set(rel.initiating_country, list)
    }
    for (const list of groups.values()) list.sort((a, b) => b.count - a.count)
    return groups
  }, [relationships])

  return (
    <div className="page">
      <header className="page-header">
        <h1>Bilateral Relationships</h1>
        <p>Analysis of diplomatic interactions between countries.</p>
      </header>

      <PageGuide page="bilateral" />

      {isLoading ? (
        <div className="loading">Loading bilateral data...</div>
      ) : relationships.length === 0 ? (
        <div className="empty-state-card">
          <Users size={48} />
          <h3>No bilateral relationship data available yet.</h3>
        </div>
      ) : (
        <>
          {/* Influencer × Recipient intensity matrix */}
          <div className="chart-card full-width" style={{ marginBottom: '2rem' }}>
            <h3>Relationship Matrix</h3>
            <p style={{ fontSize: '0.8rem', color: '#64748b', margin: '0 0 1rem' }}>
              Cell shading shows each influencer's own focus across recipients (normalized per column,
              since raw cross-actor volumes reflect source composition). Click a cell for the full
              relationship profile.
            </p>
            <div style={{ overflowX: 'auto' }}>
              <table className="bl-matrix">
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Recipient</th>
                    {influencers.map(inf => (
                      <th key={inf}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                          <span style={{ width: 9, height: 9, borderRadius: '50%', background: INFLUENCER_COLORS[inf] }} />
                          {inf}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {recipients.map(rec => (
                    <tr key={rec}>
                      <td style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>{rec}</td>
                      {influencers.map(inf => {
                        const cell = cellMap.get(`${inf}|${rec}`)
                        if (!cell) return <td key={inf} className="bl-matrix-cell bl-matrix-empty">—</td>
                        const intensity = Math.sqrt(cell.count / (colMax.get(inf) || 1))
                        return (
                          <td
                            key={inf}
                            className="bl-matrix-cell"
                            style={{ backgroundColor: hexToRgba(INFLUENCER_COLORS[inf] || '#64748b', 0.08 + 0.55 * intensity) }}
                            title={`${inf} → ${rec}: ${cell.count.toLocaleString()} documents, ${cell.event_count} events${cell.avg_materiality != null ? `, avg materiality ${cell.avg_materiality}` : ''}`}
                            onClick={() => navigate(`/bilateral/${inf}/${rec}`)}
                          >
                            {cell.count.toLocaleString()}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Per-influencer groups */}
          {influencers.map(inf => {
            const rels = byInfluencer.get(inf) || []
            if (rels.length === 0) return null
            return (
              <div key={inf} style={{ marginBottom: '2rem' }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem',
                  paddingBottom: '0.4rem', borderBottom: `2px solid ${INFLUENCER_COLORS[inf] || '#cbd5e1'}`,
                }}>
                  <span style={{ width: 11, height: 11, borderRadius: '50%', background: INFLUENCER_COLORS[inf] || '#64748b' }} />
                  <h2 style={{ margin: 0, fontSize: '1.1rem', color: '#1e293b' }}>{inf}</h2>
                  <span style={{ fontSize: '0.8rem', color: '#64748b' }}>{rels.length} relationships</span>
                </div>
                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Recipient</th>
                        <th><FileText size={13} style={{ marginRight: 4, verticalAlign: 'middle' }} />Documents</th>
                        <th><Activity size={13} style={{ marginRight: 4, verticalAlign: 'middle' }} />Events</th>
                        <th><Zap size={13} style={{ marginRight: 4, verticalAlign: 'middle' }} />Avg Materiality</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rels.map(rel => (
                        <tr
                          key={rel.recipient_country}
                          onClick={() => navigate(`/bilateral/${rel.initiating_country}/${rel.recipient_country}`)}
                          style={{ cursor: 'pointer' }}
                          className="clickable-row"
                        >
                          <td>{rel.recipient_country}</td>
                          <td>{rel.count.toLocaleString()}</td>
                          <td>{rel.event_count.toLocaleString()}</td>
                          <td>{rel.avg_materiality != null ? rel.avg_materiality.toFixed(1) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}
