import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ComposedChart, Line, Bar, BarChart, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, Cell,
} from 'recharts'
import { Flame, Sparkles, Loader2, MessageCircle } from 'lucide-react'
import { fetchMaterialityAnalysis, generateMaterialitySummary } from '../api/client'
import PageGuide from '../components/PageGuide'
import { BAND_COLORS, BAND_LABELS, badgeStyleFor } from '../components/materialityBands'
import './Pages.css'

const INFLUENCERS = ['China', 'Iran', 'Russia', 'Turkey', 'United States']
const RECIPIENTS = ['Bahrain', 'Cyprus', 'Egypt', 'Iran', 'Iraq', 'Israel', 'Jordan', 'Kuwait',
  'Lebanon', 'Libya', 'Oman', 'Palestine', 'Qatar', 'Saudi Arabia', 'Syria',
  'Turkey', 'United Arab Emirates', 'Yemen']
const COLORS: Record<string, string> = {
  China: '#dc2626', Iran: '#059669', Russia: '#2563eb', Turkey: '#d97706', 'United States': '#7c3aed',
}
// score -> color for histogram bars (cool = low materiality, hot = high)
function barColor(score: number): string {
  if (score >= 7) return '#b91c1c'
  if (score >= 6) return '#ea580c'
  if (score >= 5) return '#f97316'
  if (score >= 4) return '#facc15'
  if (score >= 3) return '#a3e635'
  return '#86efac'
}

export default function MaterialityHeatmap() {
  const [initiator, setInitiator] = useState('China')
  const [recipient, setRecipient] = useState('')          // '' = all recipients (country-level)
  const [summary, setSummary] = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['materiality-analysis', initiator, recipient],
    queryFn: () => fetchMaterialityAnalysis(initiator, recipient ? { recipient } : undefined),
  })

  const color = COLORS[initiator] || '#1a365d'
  const scopeLabel = recipient ? `${initiator} → ${recipient}` : `${initiator} (all recipients)`

  const buildContext = useMemo(() => () => {
    if (!data) return ''
    const s = data.stats
    const trend = data.trend.map(t =>
      `${t.month}: avg ${t.avg_materiality} (${t.event_count} events: ${t.symbolic_count} symbolic / ${t.developing_count} developing / ${t.substantive_count} substantive)`
    ).join('; ')
    const hist = data.histogram.map(h => `${h.bin}: ${h.count}`).join(', ')
    const tops = data.top_events.map(e =>
      `- "${e.event_name}" (score ${e.material_score}, ${e.date}): ${e.description || 'no description available'}`
    ).join('\n')
    const symbolic = data.symbolic_events.map(e =>
      `- "${e.event_name}" (score ${e.material_score}, ${e.date}, ${e.total_articles} articles): ${e.description || 'no description available'}`
    ).join('\n')
    return `Materiality analysis for ${scopeLabel}. material_score is a 1-10 significance scale, ` +
      `bucketed into bands: symbolic (<4: visits, statements, ceremonies — narrative projection), ` +
      `developing (4-7: MOUs, pilots, training), substantive (7+: funded projects, signed deals).\n` +
      `Events: ${s.event_count} (${s.bands.symbolic} symbolic / ${s.bands.developing} developing / ${s.bands.substantive} substantive). ` +
      `Avg: ${s.avg}, Median: ${s.median}, Range: ${s.min}-${s.max}.\n\n` +
      `Monthly trend — ${trend}.\n\n` +
      `Score distribution (bin: count) — ${hist}.\n\n` +
      `Top substantive events (use these to explain what drives materiality):\n${tops}\n\n` +
      `Top symbolic gestures by coverage volume (interpret as narrative projection / signaling; ` +
      `note whether gestures are converting into substantive follow-through):\n${symbolic}`
  }, [data, scopeLabel])

  async function onGenerate() {
    setSummaryLoading(true); setSummaryError(''); setSummary('')
    try {
      const res = await generateMaterialitySummary(buildContext())
      setSummary(res.summary || '')
    } catch {
      setSummaryError('Summary generation failed. Check the LLM proxy is running.')
    } finally {
      setSummaryLoading(false)
    }
  }

  const s = data?.stats
  const hasData = !!data && (data.stats.event_count > 0)

  return (
    <div className="page">
      <header className="page-header">
        <h1><Flame size={28} style={{ marginRight: 8, verticalAlign: 'middle' }} />Materiality Analysis</h1>
        <p>Event materiality trends, distribution, and standout events — by country or bilateral pair</p>
      </header>

      <PageGuide page="materiality" />

      {/* Controls */}
      <div className="chart-card compact" style={{ marginBottom: '1.25rem', display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'flex-end' }}>
        <label style={{ fontSize: '0.85rem', color: '#475569' }}>
          <div style={{ marginBottom: 4, fontWeight: 600 }}>Initiator</div>
          <select value={initiator} onChange={e => { setInitiator(e.target.value); if (e.target.value === recipient) setRecipient('') }}
            style={{ padding: '0.4rem 0.6rem', borderRadius: 6, border: '1px solid #cbd5e1', minWidth: 160 }}>
            {INFLUENCERS.map(i => <option key={i} value={i}>{i}</option>)}
          </select>
        </label>
        <label style={{ fontSize: '0.85rem', color: '#475569' }}>
          <div style={{ marginBottom: 4, fontWeight: 600 }}>Recipient (bilateral)</div>
          <select value={recipient} onChange={e => setRecipient(e.target.value)}
            style={{ padding: '0.4rem 0.6rem', borderRadius: 6, border: '1px solid #cbd5e1', minWidth: 200 }}>
            <option value="">All recipients (country-level)</option>
            {RECIPIENTS.filter(r => r !== initiator).map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <button onClick={onGenerate} disabled={!hasData || summaryLoading}
          style={{ marginLeft: 'auto', padding: '0.5rem 0.9rem', borderRadius: 6, border: 'none', cursor: hasData ? 'pointer' : 'not-allowed',
            background: hasData ? '#1a365d' : '#cbd5e1', color: '#fff', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {summaryLoading ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
          Generate Summary
        </button>
      </div>

      {isLoading && <div className="loading">Loading materiality data…</div>}

      {!isLoading && !hasData && (
        <div className="empty-state-card">
          <Flame size={48} />
          <h3>No materiality data</h3>
          <p>No scored events for {scopeLabel} in range.</p>
        </div>
      )}

      {hasData && s && (
        <>
          {/* Stats strip */}
          <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', marginBottom: '1.25rem' }}>
            {[
              { label: 'Scored events', val: s.event_count.toLocaleString(), col: color },
              { label: 'Avg materiality', val: s.avg?.toFixed(2) ?? '—', col: color },
              { label: 'Substantive (7+)', val: s.bands.substantive.toLocaleString(), col: BAND_COLORS.substantive },
              { label: 'Developing (4–7)', val: s.bands.developing.toLocaleString(), col: BAND_COLORS.developing },
              { label: 'Symbolic (<4)', val: s.bands.symbolic.toLocaleString(), col: BAND_COLORS.symbolic },
            ].map(c => (
              <div className="stat-card" key={c.label}>
                <h3 style={{ fontSize: '0.8rem' }}>{c.label}</h3>
                <p className="stat-value" style={{ color: c.col }}>{c.val}</p>
              </div>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: '1.25rem', marginBottom: '1.25rem' }}>
            {/* Trend */}
            <div className="chart-card">
              <h3>Materiality trend — {scopeLabel}</h3>
              <p style={{ fontSize: '0.78rem', color: '#64748b', margin: '0.15rem 0 0.5rem' }}>
                Monthly event mix by materiality band (stacked bars, right axis) with average
                materiality overlaid (line, left axis). Watch the mix: a shift from symbolic to
                substantive means gestures are converting into delivery.
              </p>
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={data.trend} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tick={{ fontSize: 9 }} />
                  <YAxis yAxisId="mat" domain={[0, 10]} tick={{ fontSize: 10 }}
                    label={{ value: 'avg materiality', angle: -90, position: 'insideLeft', style: { fontSize: 10 } }} />
                  <YAxis yAxisId="cnt" orientation="right" tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: '0.72rem' }} />
                  <Bar yAxisId="cnt" dataKey="symbolic_count" name={BAND_LABELS.symbolic} stackId="bands" fill={BAND_COLORS.symbolic} fillOpacity={0.55} />
                  <Bar yAxisId="cnt" dataKey="developing_count" name={BAND_LABELS.developing} stackId="bands" fill={BAND_COLORS.developing} fillOpacity={0.55} />
                  <Bar yAxisId="cnt" dataKey="substantive_count" name={BAND_LABELS.substantive} stackId="bands" fill={BAND_COLORS.substantive} fillOpacity={0.55} />
                  <Line yAxisId="mat" type="monotone" dataKey="avg_materiality" name="avg materiality"
                    stroke="#1e293b" strokeWidth={2.5} dot={{ r: 2 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Distribution */}
            <div className="chart-card">
              <h3>Score distribution</h3>
              <p style={{ fontSize: '0.78rem', color: '#64748b', margin: '0.15rem 0 0.5rem' }}>
                How events spread across the 1-10 materiality scale.
              </p>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={data.histogram} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="bin" tick={{ fontSize: 10 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="count" name="events" radius={[3, 3, 0, 0]}>
                    {data.histogram.map(h => <Cell key={h.bin} fill={barColor(h.score)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Substantive developments + Symbolic gestures */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem', marginBottom: '1.25rem' }}>
            <div className="chart-card">
              <h3 style={{ color: BAND_COLORS.substantive }}>Substantive developments</h3>
              <p style={{ fontSize: '0.78rem', color: '#64748b', margin: '0.15rem 0 0.25rem' }}>
                Highest-materiality events: funded projects, signed deals, delivered commitments.
              </p>
              <div style={{ marginTop: '0.5rem' }}>
                {data.top_events.map((e, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', padding: '0.5rem 0', borderBottom: '1px solid #f1f5f9' }}>
                    <span style={{ minWidth: 34, textAlign: 'center', fontWeight: 700, color: '#fff', background: barColor(e.material_score ?? 0), borderRadius: 4, padding: '0.1rem 0', flexShrink: 0 }}>
                      {e.material_score?.toFixed(1) ?? '—'}
                    </span>
                    <div style={{ fontSize: '0.82rem', minWidth: 0 }}>
                      <div style={{ fontWeight: 600 }}>{e.event_name}<span style={{ color: '#94a3b8', fontWeight: 400 }}> · {e.date}</span></div>
                      {e.description && (
                        <div style={{ color: '#64748b', fontSize: '0.76rem', marginTop: 2, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                          {e.description}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="chart-card">
              <h3 style={{ color: BAND_COLORS.symbolic }}>
                <MessageCircle size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                Symbolic gestures
              </h3>
              <p style={{ fontSize: '0.78rem', color: '#64748b', margin: '0.15rem 0 0.25rem' }}>
                Low-materiality events ranked by coverage volume — visits, statements, and ceremonies.
                These are narrative-projection signals: what the actor wants said.
              </p>
              <div style={{ marginTop: '0.5rem' }}>
                {data.symbolic_events.length === 0 && (
                  <p style={{ fontSize: '0.82rem', color: '#94a3b8' }}>No symbolic-band events in scope.</p>
                )}
                {data.symbolic_events.map((e, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', padding: '0.5rem 0', borderBottom: '1px solid #f1f5f9' }}>
                    <span style={{ minWidth: 34, textAlign: 'center', fontWeight: 700, borderRadius: 4, padding: '0.1rem 0', flexShrink: 0, fontSize: '0.8rem', ...badgeStyleFor(e.material_score) }}>
                      {e.material_score?.toFixed(1) ?? '—'}
                    </span>
                    <div style={{ fontSize: '0.82rem', minWidth: 0 }}>
                      <div style={{ fontWeight: 600 }}>
                        {e.event_name}
                        <span style={{ color: '#94a3b8', fontWeight: 400 }}> · {e.date} · {e.total_articles.toLocaleString()} articles</span>
                      </div>
                      {e.description && (
                        <div style={{ color: '#64748b', fontSize: '0.76rem', marginTop: 2, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                          {e.description}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Analytical Summary */}
          <div className="chart-card">
            <h3><Sparkles size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />Analytical Summary</h3>
            {!summary && !summaryLoading && !summaryError && (
              <p style={{ fontSize: '0.85rem', color: '#94a3b8', marginTop: '0.5rem' }}>
                Click <strong>Generate Summary</strong> for an LLM read of the trend, band mix, and standout events for {scopeLabel}.
              </p>
            )}
            {summaryLoading && <p style={{ color: '#64748b', marginTop: '0.5rem' }}><Loader2 size={14} className="spin" style={{ verticalAlign: 'middle' }} /> Analyzing…</p>}
            {summaryError && <p style={{ color: '#b91c1c', marginTop: '0.5rem', fontSize: '0.85rem' }}>{summaryError}</p>}
            {summary && <div style={{ fontSize: '0.85rem', lineHeight: 1.55, color: '#334155', whiteSpace: 'pre-wrap', marginTop: '0.5rem' }}>{summary}</div>}
          </div>
        </>
      )}
    </div>
  )
}
