import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  FileText, ExternalLink, Calendar, Globe, Tag,
  TrendingUp, ChevronDown, Zap, BarChart3
} from 'lucide-react'
import { fetchSummariesRich } from '../api/client'
import type { Summary, SummariesListResponse } from '../api/client'
import './Pages.css'

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

const PAGE_SIZE = 20

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

function SummaryCard({ summary, onEventClick }: {
  summary: Summary
  onEventClick?: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  const topCategories = Object.entries(summary.count_by_category || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 4)

  const topRecipients = Object.entries(summary.count_by_recipient || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 4)

  const topSources = Object.entries(summary.count_by_source || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  const hasExpandable = summary.outcomes || summary.progression || summary.strategic
    || (summary.citations && summary.citations.length > 0)
    || summary.material_justification

  return (
    <div
      className="summ-card"
      style={{
        cursor: summary.canonical_event_id ? 'pointer' : undefined,
        borderLeft: summary.material_score != null && summary.material_score >= 3
          ? '3px solid #22c55e'
          : '3px solid transparent',
      }}
      onClick={() => {
        if (summary.canonical_event_id && onEventClick) {
          onEventClick(summary.canonical_event_id)
        }
      }}
    >
      {/* Header: period + country + materiality */}
      <div className="summ-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Calendar size={14} style={{ color: '#64748b' }} />
          <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>
            {summary.period_start === summary.period_end
              ? summary.period_start
              : `${summary.period_start} — ${summary.period_end}`}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          <span className="badge">{summary.country}</span>
          {summary.material_score != null && (
            <span className="summ-materiality" style={{
              backgroundColor: summary.material_score >= 3 ? '#dcfce7' : '#f1f5f9',
              color: summary.material_score >= 3 ? '#166534' : '#475569',
            }}>
              <Zap size={10} style={{ marginRight: 2 }} />
              {summary.material_score.toFixed(1)}
            </span>
          )}
        </div>
      </div>

      {/* Event name */}
      <h3 className="summ-title">{summary.content}</h3>

      {/* Overview */}
      {summary.overview && (
        <p className="summ-overview">
          {expanded ? summary.overview : summary.overview.slice(0, 300) + (summary.overview.length > 300 ? '...' : '')}
        </p>
      )}

      {/* Expanded sections */}
      {expanded && (
        <>
          {summary.outcomes && (
            <div className="summ-section summ-outcomes">
              <strong>Outcomes:</strong> {summary.outcomes}
            </div>
          )}

          {summary.progression && (
            <div className="summ-section summ-progression">
              <strong>Progression:</strong> {summary.progression}
            </div>
          )}

          {summary.strategic && (
            <div className="summ-section summ-strategic">
              <strong>Strategic Significance:</strong> {summary.strategic}
            </div>
          )}

          {summary.material_justification && (
            <div className="summ-section summ-materiality-just">
              <strong>Materiality Assessment:</strong> {summary.material_justification}
            </div>
          )}

          {summary.citations && summary.citations.length > 0 && (
            <div className="summ-citations">
              <strong>Citations:</strong>
              <ul>
                {summary.citations.slice(0, 5).map((cite, i) => (
                  <li key={i}>{citationToText(cite)}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {/* Tags row */}
      {(topCategories.length > 0 || topRecipients.length > 0) && (
        <div className="ev-tags" style={{ marginTop: '0.5rem' }}>
          {topCategories.map(([cat, count]) => (
            <span key={cat} className="ev-cat-tag" style={{
              backgroundColor: `${CATEGORY_COLORS[cat] || '#94a3b8'}18`,
              color: CATEGORY_COLORS[cat] || '#475569',
              border: `1px solid ${CATEGORY_COLORS[cat] || '#94a3b8'}40`,
            }}>
              <Tag size={10} style={{ marginRight: 3 }} />
              {cat} ({count})
            </span>
          ))}
          {topRecipients.map(([rec, count]) => (
            <span key={rec} className="ev-rec-tag">
              <Globe size={10} style={{ marginRight: 3 }} />
              {rec} ({count})
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="ev-card-footer" style={{ marginTop: '0.5rem' }}>
        {summary.source_count != null && summary.source_count > 0 && (
          <span>
            <FileText size={12} style={{ marginRight: 3, verticalAlign: 'middle' }} />
            {summary.source_count} sources
          </span>
        )}

        {topSources.length > 0 && (
          <span style={{ color: '#94a3b8' }}>
            {topSources.map(([s]) => s).join(', ')}
          </span>
        )}

        {summary.source_link && (
          <a
            href={summary.source_link}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{ color: '#3b82f6', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 3 }}
          >
            <ExternalLink size={12} /> View
          </a>
        )}

        {hasExpandable && (
          <button
            className="summ-toggle"
            onClick={e => { e.stopPropagation(); setExpanded(!expanded) }}
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>
    </div>
  )
}

export default function Summaries() {
  const navigate = useNavigate()
  const [summaryType, setSummaryType] = useState('daily')
  const [countryFilter, setCountryFilter] = useState('ALL')
  const [offset, setOffset] = useState(0)
  const [accumulated, setAccumulated] = useState<Summary[]>([])

  const { data, isLoading, isFetching } = useQuery<SummariesListResponse>({
    queryKey: ['summaries-rich', summaryType, countryFilter, offset],
    queryFn: () => {
      const params: Record<string, unknown> = {
        type: summaryType,
        limit: PAGE_SIZE,
        offset,
      }
      if (countryFilter !== 'ALL') params.country = countryFilter
      return fetchSummariesRich(params as Parameters<typeof fetchSummariesRich>[0])
    },
    placeholderData: keepPreviousData,
  })

  const summaries = offset === 0
    ? (data?.summaries || [])
    : [...accumulated, ...(data?.summaries || [])]

  const total = data?.total || 0
  const hasMore = summaries.length < total

  const handleShowMore = () => {
    setAccumulated(summaries)
    setOffset(summaries.length)
  }

  const handleTypeChange = (type: string) => {
    setSummaryType(type)
    setOffset(0)
    setAccumulated([])
  }

  const handleCountryChange = (value: string) => {
    setCountryFilter(value)
    setOffset(0)
    setAccumulated([])
  }

  const COUNTRIES = ['China', 'Iran', 'Russia', 'Turkey', 'United States']

  return (
    <div className="page">
      <header className="page-header">
        <h1>
          <TrendingUp size={28} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          Event Briefings
        </h1>
        <p>AP-style event summaries across daily, weekly, monthly, and yearly periods</p>
      </header>

      {/* Period type tabs + country filter */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="filter-tabs">
          {['daily', 'weekly', 'monthly', 'yearly'].map((type) => (
            <button
              key={type}
              className={`tab ${summaryType === type ? 'active' : ''}`}
              onClick={() => handleTypeChange(type)}
            >
              <BarChart3 size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} />
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </button>
          ))}
        </div>

        <select
          value={countryFilter}
          onChange={e => handleCountryChange(e.target.value)}
          style={{
            padding: '0.375rem 0.75rem', borderRadius: '6px',
            border: '1px solid #d1d5db', fontSize: '0.85rem',
          }}
        >
          <option value="ALL">All Countries</option>
          {COUNTRIES.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        {total > 0 && (
          <span className="ev-count">
            {total.toLocaleString()} summaries
          </span>
        )}
      </div>

      {/* Summary list */}
      {isLoading && offset === 0 ? (
        <div className="loading">Loading summaries...</div>
      ) : summaries.length > 0 ? (
        <>
          <div className="summaries-list">
            {summaries.map((summary: Summary) => (
              <SummaryCard
                key={summary.id}
                summary={summary}
                onEventClick={(id) => navigate(`/events/${id}`)}
              />
            ))}
          </div>

          {hasMore && (
            <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
              <button
                className="ev-show-more"
                onClick={handleShowMore}
                disabled={isFetching}
              >
                {isFetching ? 'Loading...' : (
                  <>
                    Show More <ChevronDown size={16} style={{ verticalAlign: 'middle' }} />
                  </>
                )}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state-card">
          <FileText size={48} />
          <h3>No Summaries Available</h3>
          <p>
            {countryFilter !== 'ALL'
              ? 'No summaries found for this country and period type.'
              : 'Summaries will appear here once they are generated.'}
          </p>
        </div>
      )}
    </div>
  )
}
