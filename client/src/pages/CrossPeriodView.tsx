import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, Calendar, Zap, FileText, Tag, Globe, ExternalLink, Layers
} from 'lucide-react'
import { fetchEventAcrossPeriods } from '../api/client'
import type { CrossPeriodEntry } from '../api/client'
import PageGuide from '../components/PageGuide'
import { badgeStyleFor } from '../components/materialityBands'
import './Pages.css'

const PERIOD_LABELS: Record<string, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  yearly: 'Yearly',
}

const PERIOD_COLORS: Record<string, string> = {
  daily: '#3b82f6',
  weekly: '#8b5cf6',
  monthly: '#f59e0b',
  yearly: '#10b981',
}

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

// Citations may be strings (legacy) or objects with { citation | headline | source_name | ... }
function citationToText(c: unknown): string {
  if (typeof c === 'string') return c
  if (c && typeof c === 'object') {
    const o = c as Record<string, unknown>
    const pick = (k: string) => (typeof o[k] === 'string' ? (o[k] as string) : '')
    const formatted = pick('citation')
    if (formatted) return formatted
    const headline = pick('headline') || pick('title')
    const source = pick('source_name')
    const date = pick('published_date') || pick('date')
    const parts = [headline, source && `[${source}]`, date].filter(Boolean)
    if (parts.length) return parts.join(' ')
    return JSON.stringify(c)
  }
  return String(c)
}

function PeriodCard({ entry, periodType }: { entry: CrossPeriodEntry; periodType: string }) {
  const [expanded, setExpanded] = useState(false)
  const topCats = Object.entries(entry.count_by_category || {}).sort(([,a],[,b]) => b - a).slice(0, 3)
  const topRecs = Object.entries(entry.count_by_recipient || {}).sort(([,a],[,b]) => b - a).slice(0, 3)

  return (
    <div style={{
      padding: '1rem',
      borderLeft: `3px solid ${PERIOD_COLORS[periodType] || '#94a3b8'}`,
      backgroundColor: '#fafafa',
      borderRadius: '0 8px 8px 0',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <Calendar size={13} style={{ color: '#64748b' }} />
        <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>
          {entry.period_start}{entry.period_end && entry.period_end !== entry.period_start ? ` — ${entry.period_end}` : ''}
        </span>
        {entry.material_score != null && (
          <span style={{
            fontSize: '0.7rem', padding: '1px 6px', borderRadius: '3px',
            ...badgeStyleFor(entry.material_score),
          }}>
            <Zap size={9} style={{ marginRight: 1 }} />{entry.material_score.toFixed(1)}
          </span>
        )}
        {entry.source_count != null && (
          <span style={{ fontSize: '0.78rem', color: '#64748b', marginLeft: 'auto' }}>
            <FileText size={11} style={{ marginRight: 2 }} />{entry.source_count} sources
          </span>
        )}
      </div>

      {entry.overview && (
        <p style={{ margin: '0 0 0.375rem', color: '#334155', lineHeight: 1.6, fontSize: '0.875rem' }}>
          {expanded ? entry.overview : entry.overview.slice(0, 250) + (entry.overview.length > 250 ? '...' : '')}
        </p>
      )}

      {expanded && (
        <>
          {entry.outcomes && (
            <div className="summ-section summ-outcomes">
              <strong>Outcomes:</strong> {entry.outcomes}
            </div>
          )}
          {entry.progression && (
            <div className="summ-section summ-progression">
              <strong>Progression:</strong> {entry.progression}
            </div>
          )}
          {entry.strategic && (
            <div className="summ-section summ-strategic">
              <strong>Strategic:</strong> {entry.strategic}
            </div>
          )}
          {entry.citations && entry.citations.length > 0 && (
            <div className="summ-citations">
              <strong>Citations:</strong>
              <ul>
                {entry.citations.slice(0, 5).map((c, i) => <li key={i}>{citationToText(c)}</li>)}
              </ul>
            </div>
          )}
        </>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.375rem' }}>
        {topCats.map(([cat, count]) => (
          <span key={cat} style={{
            fontSize: '0.68rem', padding: '1px 5px', borderRadius: '3px',
            backgroundColor: `${CATEGORY_COLORS[cat] || '#94a3b8'}18`,
            color: CATEGORY_COLORS[cat] || '#475569',
          }}>
            <Tag size={8} style={{ marginRight: 2 }} />{cat} ({count})
          </span>
        ))}
        {topRecs.map(([rec, count]) => (
          <span key={rec} style={{
            fontSize: '0.68rem', padding: '1px 5px', borderRadius: '3px',
            backgroundColor: '#eff6ff', color: '#1e40af',
          }}>
            <Globe size={8} style={{ marginRight: 2 }} />{rec} ({count})
          </span>
        ))}

        {entry.source_link && (
          <a href={entry.source_link} target="_blank" rel="noopener noreferrer"
            style={{ fontSize: '0.78rem', color: '#3b82f6', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 2, marginLeft: 'auto' }}>
            <ExternalLink size={11} /> Sources
          </a>
        )}

        {(entry.outcomes || entry.progression || entry.strategic || (entry.citations && entry.citations.length > 0)) && (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer', fontSize: '0.78rem', padding: 0, marginLeft: entry.source_link ? '0.5rem' : 'auto' }}
          >
            {expanded ? 'Less' : 'More'}
          </button>
        )}
      </div>
    </div>
  )
}

export default function CrossPeriodView() {
  const { eventId } = useParams<{ eventId: string }>()
  const navigate = useNavigate()

  const { data, isLoading, error } = useQuery({
    queryKey: ['cross-period', eventId],
    queryFn: () => fetchEventAcrossPeriods(eventId!),
    enabled: !!eventId,
  })

  if (isLoading) return <div className="page"><div className="loading">Loading cross-period data...</div></div>
  if (error || !data) return (
    <div className="page">
      <button onClick={() => navigate(-1)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#3b82f6', display: 'flex', alignItems: 'center', gap: 4, marginBottom: '1rem' }}>
        <ArrowLeft size={16} /> Back
      </button>
      <div className="empty-state-card">
        <h3>No Cross-Period Data</h3>
        <p>This event does not have summaries across multiple time periods.</p>
      </div>
    </div>
  )

  const periodOrder = ['daily', 'weekly', 'monthly', 'yearly'] as const

  return (
    <div className="page" style={{ maxWidth: '900px' }}>
      <button
        onClick={() => navigate(-1)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#3b82f6', display: 'flex', alignItems: 'center', gap: 4, marginBottom: '1.5rem', fontSize: '0.9rem', padding: 0 }}
      >
        <ArrowLeft size={16} /> Back
      </button>

      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ margin: '0 0 0.5rem', fontSize: '1.4rem', lineHeight: 1.3 }}>
          <Layers size={22} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          {data.event_name}
        </h1>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap', color: '#64748b', fontSize: '0.85rem' }}>
          <span>{data.initiating_country}</span>
          {data.story_phase && (
            <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px', backgroundColor: '#3b82f6', color: 'white' }}>
              {data.story_phase}
            </span>
          )}
          {data.material_score != null && (
            <span>Materiality: {data.material_score.toFixed(1)}</span>
          )}
          <span>{data.total_articles} articles</span>
          {data.first_mention_date && <span>{data.first_mention_date} — {data.last_mention_date}</span>}
        </div>
      </div>

      <PageGuide page="cross-period" />

      {/* Period sections */}
      {periodOrder.map(period => {
        const entries = data.periods[period] || []
        if (entries.length === 0) return null
        return (
          <div key={period} style={{ marginBottom: '1.5rem' }}>
            <h2 style={{
              fontSize: '1.05rem', marginBottom: '0.75rem',
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              color: PERIOD_COLORS[period],
            }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                backgroundColor: PERIOD_COLORS[period], display: 'inline-block',
              }} />
              {PERIOD_LABELS[period]} Summaries ({entries.length})
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {entries.map((entry, i) => (
                <PeriodCard key={i} entry={entry} periodType={period} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
