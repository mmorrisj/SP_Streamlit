import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, Legend } from 'recharts'
import { Calendar, Zap, Tag, Globe, Info, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { fetchDocumentStats, fetchFilterOptions, fetchDashboardIntelligence, fetchEventComparison, fetchMaterialityAnalysis } from '../api/client'
import type { DashboardIntelligenceItem } from '../api/client'
import DataCoverageBadge from '../components/DataCoverageBadge'
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

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

const MENA_INFLUENCERS = ['China', 'Iran', 'Russia', 'Turkey']

function MaterialitySparkline({ trend, color }: { trend: { month: string; avg_materiality: number }[]; color: string }) {
  // Last 12 months of average materiality as a tiny inline SVG, scaled to the
  // series' own range so the shape stays readable.
  const points = trend.slice(-12).map(t => t.avg_materiality)
  if (points.length < 2) return null
  const w = 72, h = 18
  const min = Math.min(...points), max = Math.max(...points)
  const span = max - min || 1
  const step = w / (points.length - 1)
  const path = points
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`)
    .join(' ')
  const latest = points[points.length - 1]
  return (
    <span
      title={`Average materiality by month over the last ${points.length} months (higher = more substantive activity). Latest: ${latest.toFixed(1)}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', marginLeft: 'auto', cursor: 'help' }}
    >
      <svg width={w} height={h} style={{ display: 'block' }}>
        <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <span style={{ fontSize: '0.7rem', color: '#64748b' }}>{latest.toFixed(1)}</span>
    </span>
  )
}

function InfluencerActivityChips({ stats }: { stats: { country: string; period_type: string; event_count: number; avg_materiality: number | null }[] }) {
  // One chip per influencer from the daily-period rows: total tracked event
  // summaries and average materiality across the full corpus. Limited to the
  // same MENA-active influencers as the intelligence lists below.
  const daily = stats
    .filter(s => s.period_type.toLowerCase() === 'daily' && MENA_INFLUENCERS.includes(s.country))
    .sort((a, b) => MENA_INFLUENCERS.indexOf(a.country) - MENA_INFLUENCERS.indexOf(b.country))
  if (daily.length === 0) return null

  return (
    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
      {daily.map(s => (
        <span
          key={s.country}
          title={`${s.event_count.toLocaleString()} daily event summaries tracked for ${s.country} across the full corpus${s.avg_materiality != null ? `; average materiality score ${s.avg_materiality} (1–10 scale, higher = more substantive)` : ''}`}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
            padding: '0.3rem 0.7rem', borderRadius: '9999px', background: 'white',
            boxShadow: '0 1px 3px rgba(0,0,0,0.07)', fontSize: '0.8rem', color: '#334155', cursor: 'help',
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: INFLUENCER_COLORS[s.country], flexShrink: 0 }} />
          <span style={{ fontWeight: 600 }}>{s.country}</span>
          <span style={{ color: '#64748b' }}>{s.event_count.toLocaleString()} events</span>
          {s.avg_materiality != null && (
            <span style={{ color: '#64748b', display: 'inline-flex', alignItems: 'center', gap: 2 }}>
              <Zap size={11} />{s.avg_materiality.toFixed(1)}
            </span>
          )}
        </span>
      ))}
    </div>
  )
}

function MomentumChip({ influencer, change }: { influencer: string; change: number | null }) {
  if (change === null) return null
  const up = change > 0
  const flat = Math.abs(change) < 1
  const color = flat ? '#64748b' : up ? '#166534' : '#991b1b'
  const bg = flat ? '#f1f5f9' : up ? '#dcfce7' : '#fee2e2'
  const IconComp = flat ? Minus : up ? TrendingUp : TrendingDown
  return (
    <span
      title={`${influencer}: ${up ? '+' : ''}${change.toFixed(0)}% documents vs. the prior week`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
        padding: '0.2rem 0.6rem', borderRadius: '9999px',
        background: bg, color, fontSize: '0.78rem', fontWeight: 500, cursor: 'help',
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: INFLUENCER_COLORS[influencer] || '#64748b', flexShrink: 0 }} />
      {influencer}
      <IconComp size={12} />
      {up ? '+' : ''}{change.toFixed(0)}%
    </span>
  )
}

function SectionHeading({ title, caption, tooltip }: { title: string; caption: string; tooltip: string }) {
  return (
    <div style={{ marginBottom: '0.75rem' }}>
      <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.95rem', color: '#475569', margin: 0 }}>
        {title}
        <span title={tooltip} style={{ display: 'inline-flex', cursor: 'help', color: '#94a3b8' }}>
          <Info size={14} />
        </span>
      </h3>
      <p style={{ margin: '0.2rem 0 0', fontSize: '0.78rem', color: '#94a3b8' }}>{caption}</p>
    </div>
  )
}

function IntelCard({ item, onClick }: { item: DashboardIntelligenceItem; onClick?: () => void }) {
  const topCats = Object.entries(item.count_by_category || {}).sort(([,a],[,b]) => b - a).slice(0, 2)
  const topRecs = Object.entries(item.count_by_recipient || {}).sort(([,a],[,b]) => b - a).slice(0, 2)

  return (
    <div className="intel-card" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.375rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          <Calendar size={12} style={{ color: '#64748b' }} />
          <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
            {item.period_start}{item.period_end && item.period_end !== item.period_start ? ` — ${item.period_end}` : ''}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '0.25rem' }}>
          <span className="ev-country-badge">{item.country}</span>
          {item.material_score != null && (
            <span style={{
              fontSize: '0.68rem', padding: '1px 6px', borderRadius: '3px',
              backgroundColor: item.material_score >= 3 ? '#dcfce7' : '#f1f5f9',
              color: item.material_score >= 3 ? '#166534' : '#475569',
            }}>
              <Zap size={9} style={{ marginRight: 1 }} />{item.material_score.toFixed(1)}
            </span>
          )}
        </div>
      </div>
      <h4 style={{ margin: '0 0 0.25rem', fontSize: '0.88rem', lineHeight: 1.3, color: '#1e293b' }}>
        {item.event_name}
      </h4>
      {item.overview && (
        <p style={{ margin: '0 0 0.375rem', fontSize: '0.8rem', color: '#475569', lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {item.overview}
        </p>
      )}
      {(topCats.length > 0 || topRecs.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.2rem' }}>
          {topCats.map(([cat]) => (
            <span key={cat} style={{ fontSize: '0.65rem', padding: '1px 5px', borderRadius: '3px', backgroundColor: `${CATEGORY_COLORS[cat] || '#94a3b8'}18`, color: CATEGORY_COLORS[cat] || '#475569' }}>
              <Tag size={8} style={{ marginRight: 2 }} />{cat}
            </span>
          ))}
          {topRecs.map(([rec]) => (
            <span key={rec} style={{ fontSize: '0.65rem', padding: '1px 5px', borderRadius: '3px', backgroundColor: '#eff6ff', color: '#1e40af' }}>
              <Globe size={8} style={{ marginRight: 2 }} />{rec}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [selectedInfluencers, setSelectedInfluencers] = useState<Record<string, boolean>>({
    'China': true,
    'Russia': true,
    'Iran': true,
    'Turkey': true,
    'United States': true
  })
  const [selectedRecipients, setSelectedRecipients] = useState<Record<string, boolean>>({})
  const [showTotal, setShowTotal] = useState<boolean>(true)

  // Fetch filter options (still used for the recipient line toggles on the weekly chart)
  const { data: filterOptions } = useQuery({
    queryKey: ['filterOptions'],
    queryFn: fetchFilterOptions,
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['documentStats'],
    queryFn: () => fetchDocumentStats(),
  })

  const { data: intelligence } = useQuery({
    queryKey: ['dashboard-intelligence'],
    queryFn: fetchDashboardIntelligence,
  })

  // Top events tracked under multiple influencers (teaser for /events/comparison)
  const { data: contested } = useQuery({
    queryKey: ['dashboard-contested-events'],
    queryFn: () => fetchEventComparison(3),
    staleTime: 10 * 60 * 1000,
  })

  // Monthly avg-materiality trend per influencer, for the column-header sparklines
  const { data: materialityTrends } = useQuery({
    queryKey: ['dashboard-materiality-trends'],
    queryFn: async () => {
      const results = await Promise.all(
        MENA_INFLUENCERS.map(c => fetchMaterialityAnalysis(c).catch(() => null))
      )
      return Object.fromEntries(MENA_INFLUENCERS.map((c, i) => [c, results[i]?.trend || []]))
    },
    staleTime: 10 * 60 * 1000,
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

  // Week-over-week document momentum per influencer, from the two most recent
  // weeks in the already-loaded weekly series. The newest week can be partial
  // (ingestion lags), so treat these as directional.
  const momentum = useMemo(() => {
    const byInfluencer = data?.documents_by_week_by_influencer
    if (!byInfluencer) return []
    return Object.entries(byInfluencer)
      .filter(([influencer]) => INFLUENCER_COLORS[influencer])
      .map(([influencer, weeks]) => {
        const sorted = [...weeks].sort((a, b) => a.week.localeCompare(b.week))
        if (sorted.length < 2) return { influencer, change: null }
        const [prev, latest] = sorted.slice(-2)
        if (!prev.count) return { influencer, change: null }
        return { influencer, change: ((latest.count - prev.count) / prev.count) * 100 }
      })
  }, [data])

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
        <h1>Soft Power Dashboard <DataCoverageBadge /></h1>
        <p>Analytics overview of diplomatic documents and events</p>
      </header>

      {/* Recent Intelligence Section */}
      {intelligence && ((intelligence.weekly?.length || 0) > 0 || (intelligence.monthly?.length || 0) > 0) && (
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ fontSize: '1.25rem', color: '#1a365d', marginBottom: '1rem' }}>
            <Zap size={20} style={{ marginRight: 6, verticalAlign: 'middle' }} />
            Recent Intelligence
          </h2>
          {intelligence.period_stats && <InfluencerActivityChips stats={intelligence.period_stats} />}
          {/* Latest Weekly — one column per influencer, top 5 each */}
          {intelligence.weekly_by_influencer && Object.keys(intelligence.weekly_by_influencer).length > 0 && (
            <div style={{ marginBottom: '1.5rem' }}>
              <SectionHeading
                title="Latest Weekly by Influencer"
                caption="Each card summarizes one event's reporting across a Monday–Sunday week — the most recent weeks per influencer."
                tooltip="Weekly summaries are AI-generated narratives that synthesize an event's daily summaries over a Monday–Sunday week. An ongoing event produces a new weekly summary for each week it stays in the news."
              />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem', alignItems: 'start' }}>
                {MENA_INFLUENCERS
                  .filter(inf => (intelligence.weekly_by_influencer[inf]?.length || 0) > 0)
                  .map(inf => (
                    <div key={inf}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.6rem', paddingBottom: '0.35rem', borderBottom: `2px solid ${INFLUENCER_COLORS[inf] || '#cbd5e1'}` }}>
                        <span style={{ width: 10, height: 10, borderRadius: '50%', background: INFLUENCER_COLORS[inf] || '#64748b', flexShrink: 0 }} />
                        <span style={{ fontWeight: 600, fontSize: '0.85rem', color: '#1e293b' }}>{inf}</span>
                        {materialityTrends?.[inf] && (
                          <MaterialitySparkline trend={materialityTrends[inf]} color={INFLUENCER_COLORS[inf] || '#64748b'} />
                        )}
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {intelligence.weekly_by_influencer[inf].map(item => (
                          <IntelCard
                            key={item.id}
                            item={item}
                            onClick={item.canonical_event_id ? () => navigate(`/events/${item.canonical_event_id}`) : undefined}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}
          {/* Latest Monthly — blended MENA top 5 */}
          {intelligence.monthly && intelligence.monthly.length > 0 && (
            <div>
              <SectionHeading
                title="Latest Monthly"
                caption="Each card rolls one event's weekly summaries up into a calendar-month narrative — the most recent months across all influencers."
                tooltip="Monthly summaries are AI-generated narratives that synthesize an event's weekly summaries across a calendar month, showing how the event developed over the month rather than week to week."
              />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem', alignItems: 'start' }}>
                {intelligence.monthly.slice(0, 5).map(item => (
                  <IntelCard
                    key={item.id}
                    item={item}
                    onClick={item.canonical_event_id ? () => navigate(`/events/${item.canonical_event_id}`) : undefined}
                  />
                ))}
              </div>
            </div>
          )}
          {/* Contested events — tracked under multiple influencers */}
          {contested && contested.comparisons.length > 0 && (
            <div style={{ marginTop: '1.5rem' }}>
              <SectionHeading
                title="Contested Events"
                caption="Events where multiple influencers are simultaneously engaged — click a card for the side-by-side comparison."
                tooltip="These events appear in the reporting of two or more initiating countries at once, signaling active competition for the same story. The comparison page shows each country's narrative side by side."
              />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem', alignItems: 'start' }}>
                {contested.comparisons.slice(0, 3).map(comp => (
                  <div
                    key={comp.event_name}
                    className="intel-card"
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate('/events/comparison')}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.375rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                        {comp.countries.map(c => (
                          <span key={c} title={c} style={{ width: 9, height: 9, borderRadius: '50%', background: INFLUENCER_COLORS[c] || '#94a3b8' }} />
                        ))}
                        <span style={{ fontSize: '0.72rem', color: '#64748b' }}>{comp.country_count} influencers</span>
                      </div>
                      {comp.latest_date && (
                        <span style={{ fontSize: '0.72rem', color: '#64748b' }}>{comp.latest_date}</span>
                      )}
                    </div>
                    <h4 style={{ margin: 0, fontSize: '0.88rem', lineHeight: 1.3, color: '#1e293b' }}>
                      {comp.event_name}
                    </h4>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Documents per Week with Toggles */}
      <div className="chart-card" style={{ marginBottom: '2rem' }}>
        <h3>Documents per Week</h3>

        {/* Week-over-week momentum */}
        {momentum.some(m => m.change !== null) && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
            <span style={{ fontSize: '0.8rem', color: '#64748b' }}>vs. prior week:</span>
            {momentum.map(m => (
              <MomentumChip key={m.influencer} influencer={m.influencer} change={m.change} />
            ))}
          </div>
        )}

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

      <div className="charts-grid">

        {/* Top Influencers */}
        <div className="chart-card">
          <h3>Top Influencers by Document Count</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={data?.top_countries || []}
              layout="vertical"
            >
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
            <BarChart
              data={data?.top_recipients || []}
              layout="vertical"
            >
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
