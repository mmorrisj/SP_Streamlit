import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, ExternalLink, Calendar, Globe, Tag, TrendingUp } from 'lucide-react'
import { Summary, fetchSummaries } from '../api/client'
import './Pages.css'

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

function SummaryCard({ summary }: { summary: Summary }) {
  const [expanded, setExpanded] = useState(false)

  const topCategories = Object.entries(summary.count_by_category || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  const topRecipients = Object.entries(summary.count_by_recipient || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 4)

  return (
    <div className="summary-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
      <div className="summary-header" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <Calendar size={16} style={{ color: '#64748b' }} />
        <span className="summary-period" style={{ fontWeight: 500 }}>
          {summary.period_start === summary.period_end
            ? summary.period_start
            : `${summary.period_start} — ${summary.period_end}`}
        </span>
        <span className="badge" style={{ marginLeft: 'auto' }}>{summary.country}</span>
        {summary.material_score !== null && (
          <span style={{
            fontSize: '0.75rem',
            padding: '2px 8px',
            borderRadius: '4px',
            backgroundColor: summary.material_score >= 3 ? '#dcfce7' : '#f1f5f9',
            color: summary.material_score >= 3 ? '#166534' : '#475569',
          }}>
            {summary.material_score.toFixed(1)}
          </span>
        )}
      </div>

      <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem', lineHeight: 1.4 }}>
        {summary.content}
      </h3>

      {summary.overview && (
        <p style={{ color: '#334155', lineHeight: 1.6, margin: '0 0 0.5rem' }}>
          {summary.overview}
        </p>
      )}

      {summary.outcomes && expanded && (
        <div style={{ margin: '0.75rem 0', padding: '0.75rem', backgroundColor: '#f8fafc', borderRadius: '6px', borderLeft: '3px solid #3b82f6' }}>
          <p style={{ margin: 0, color: '#475569', lineHeight: 1.6, fontSize: '0.9rem' }}>
            <strong>Outcomes:</strong> {summary.outcomes}
          </p>
        </div>
      )}

      {(topCategories.length > 0 || topRecipients.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', margin: '0.75rem 0' }}>
          {topCategories.map(([cat, count]) => (
            <span key={cat} style={{
              fontSize: '0.75rem',
              padding: '2px 8px',
              borderRadius: '4px',
              backgroundColor: `${CATEGORY_COLORS[cat] || '#94a3b8'}20`,
              color: CATEGORY_COLORS[cat] || '#475569',
              border: `1px solid ${CATEGORY_COLORS[cat] || '#94a3b8'}40`,
            }}>
              <Tag size={10} style={{ marginRight: 4, verticalAlign: 'middle' }} />
              {cat} ({count})
            </span>
          ))}
          {topRecipients.map(([rec, count]) => (
            <span key={rec} style={{
              fontSize: '0.75rem',
              padding: '2px 8px',
              borderRadius: '4px',
              backgroundColor: '#eff6ff',
              color: '#1e40af',
            }}>
              <Globe size={10} style={{ marginRight: 4, verticalAlign: 'middle' }} />
              {rec} ({count})
            </span>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.8rem', color: '#64748b' }}>
        {summary.source_count !== null && (
          <span>
            <FileText size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />
            {summary.source_count} sources
          </span>
        )}

        {summary.source_link && (
          <a
            href={summary.source_link}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: '#3b82f6', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}
          >
            <ExternalLink size={12} />
            View Sources
          </a>
        )}

        {(summary.outcomes || (summary.citations && summary.citations.length > 0)) && (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              background: 'none', border: 'none', color: '#3b82f6',
              cursor: 'pointer', fontSize: '0.8rem', padding: 0, marginLeft: 'auto',
            }}
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>

      {expanded && summary.citations && summary.citations.length > 0 && (
        <div style={{ marginTop: '0.75rem', padding: '0.75rem', backgroundColor: '#fafafa', borderRadius: '6px', fontSize: '0.8rem' }}>
          <strong style={{ color: '#475569' }}>Citations:</strong>
          <ul style={{ margin: '0.25rem 0 0', paddingLeft: '1.25rem', color: '#64748b', lineHeight: 1.6 }}>
            {summary.citations.slice(0, 5).map((cite, i) => (
              <li key={i}>{cite}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function Summaries() {
  const [summaryType, setSummaryType] = useState('daily')
  const [countryFilter, setCountryFilter] = useState('ALL')

  const { data, isLoading } = useQuery({
    queryKey: ['summaries', summaryType, countryFilter],
    queryFn: async () => {
      const params = new URLSearchParams({ type: summaryType })
      if (countryFilter !== 'ALL') params.set('country', countryFilter)
      const response = await fetch(`/api/summaries?${params}`)
      return response.json()
    },
  })

  // Extract unique countries from results for the filter
  const countries = Array.from(
    new Set((data?.summaries || []).map((s: Summary) => s.country).filter(Boolean))
  ).sort() as string[]

  return (
    <div className="page">
      <header className="page-header">
        <h1>
          <TrendingUp size={28} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          Event Briefings
        </h1>
        <p>AP-style event summaries with source attribution</p>
      </header>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <div className="filter-tabs">
          {['daily', 'weekly', 'monthly'].map((type) => (
            <button
              key={type}
              className={`tab ${summaryType === type ? 'active' : ''}`}
              onClick={() => setSummaryType(type)}
            >
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </button>
          ))}
        </div>

        {countries.length > 1 && (
          <select
            value={countryFilter}
            onChange={e => setCountryFilter(e.target.value)}
            style={{
              padding: '0.375rem 0.75rem', borderRadius: '6px',
              border: '1px solid #d1d5db', fontSize: '0.875rem',
            }}
          >
            <option value="ALL">All Countries</option>
            {countries.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
      </div>

      {isLoading ? (
        <div className="loading">Loading summaries...</div>
      ) : (
        <div className="summaries-list">
          {data?.summaries?.length > 0 ? (
            data.summaries.map((summary: Summary) => (
              <SummaryCard key={summary.id} summary={summary} />
            ))
          ) : (
            <div className="empty-state-card">
              <FileText size={48} />
              <h3>No Summaries Available</h3>
              <p>Summaries will appear here once they are generated.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
