import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Calendar, FileText, Tag, Globe, Zap, ChevronDown,
  ArrowUpDown, Filter
} from 'lucide-react'
import { fetchEventsRich, fetchFilterOptions } from '../api/client'
import type { Event, EventsListResponse } from '../api/client'
import './Pages.css'

const PHASE_COLORS: Record<string, string> = {
  emerging: '#10b981',
  developing: '#3b82f6',
  peak: '#f59e0b',
  fading: '#94a3b8',
  dormant: '#d1d5db',
}

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

const PAGE_SIZE = 20

function EventCard({ event, onClick }: { event: Event; onClick: () => void }) {
  const topCategories = Object.entries(event.primary_categories || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  const topRecipients = Object.entries(event.primary_recipients || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  return (
    <div
      className="ev-card"
      onClick={onClick}
      style={{ cursor: 'pointer' }}
    >
      {/* Header row: date + country + phase badge */}
      <div className="ev-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Calendar size={14} style={{ color: '#64748b' }} />
          <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
            {event.event_date}
            {event.last_mention_date && event.last_mention_date !== event.event_date
              ? ` — ${event.last_mention_date}`
              : ''}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          {event.initiating_country && (
            <span className="ev-country-badge">{event.initiating_country}</span>
          )}
          {event.story_phase && (
            <span
              className="ev-phase-badge"
              style={{ backgroundColor: PHASE_COLORS[event.story_phase] || '#94a3b8' }}
            >
              {event.story_phase}
            </span>
          )}
        </div>
      </div>

      {/* Event name */}
      <h3 className="ev-card-title">{event.event_name}</h3>

      {/* Narrative overview */}
      {event.narrative_overview && (
        <p className="ev-card-overview">{event.narrative_overview}</p>
      )}

      {/* Category + Recipient tags */}
      {(topCategories.length > 0 || topRecipients.length > 0) && (
        <div className="ev-tags">
          {topCategories.map(([cat, count]) => (
            <span
              key={cat}
              className="ev-cat-tag"
              style={{
                backgroundColor: `${CATEGORY_COLORS[cat] || '#94a3b8'}18`,
                color: CATEGORY_COLORS[cat] || '#475569',
                border: `1px solid ${CATEGORY_COLORS[cat] || '#94a3b8'}40`,
              }}
            >
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

      {/* Footer metrics */}
      <div className="ev-card-footer">
        {event.total_articles != null && event.total_articles > 0 && (
          <span>
            <FileText size={12} style={{ marginRight: 3, verticalAlign: 'middle' }} />
            {event.total_articles} articles
          </span>
        )}
        {event.source_count != null && event.source_count > 0 && (
          <span>
            {event.source_count} sources
          </span>
        )}
        {event.material_score != null && (
          <span className="ev-materiality" style={{
            backgroundColor: event.material_score >= 3 ? '#dcfce7' : '#f1f5f9',
            color: event.material_score >= 3 ? '#166534' : '#475569',
          }}>
            <Zap size={10} style={{ marginRight: 2 }} />
            {event.material_score.toFixed(1)}
          </span>
        )}
        {event.total_mention_days != null && event.total_mention_days > 1 && (
          <span style={{ marginLeft: 'auto', color: '#94a3b8', fontSize: '0.75rem' }}>
            {event.total_mention_days} days tracked
          </span>
        )}
      </div>
    </div>
  )
}

const MATERIALITY_OPTIONS = [
  { value: '', label: 'Any Materiality' },
  { value: '3', label: 'Notable (3+)' },
  { value: '5', label: 'Significant (5+)' },
  { value: '7', label: 'Major (7+)' },
]

export default function Events() {
  const navigate = useNavigate()
  const [countryFilter, setCountryFilter] = useState('ALL')
  const [recipientFilter, setRecipientFilter] = useState('ALL')
  const [phaseFilter, setPhaseFilter] = useState('ALL')
  const [materialityFilter, setMaterialityFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [sortBy, setSortBy] = useState('recency')
  const [offset, setOffset] = useState(0)
  const [accumulated, setAccumulated] = useState<Event[]>([])

  const { data: filterOptions } = useQuery({
    queryKey: ['filterOptions'],
    queryFn: fetchFilterOptions,
  })

  const { data, isLoading, isFetching } = useQuery<EventsListResponse>({
    queryKey: ['events-rich', countryFilter, recipientFilter, phaseFilter, materialityFilter, startDate, endDate, sortBy, offset],
    queryFn: async () => {
      const params: Record<string, unknown> = {
        sort_by: sortBy,
        limit: PAGE_SIZE,
        offset,
      }
      if (countryFilter !== 'ALL') params.country = countryFilter
      if (recipientFilter !== 'ALL') params.recipient = recipientFilter
      if (phaseFilter !== 'ALL') params.story_phase = phaseFilter
      if (materialityFilter) params.min_materiality = Number(materialityFilter)
      if (startDate) params.start_date = startDate
      if (endDate) params.end_date = endDate
      return fetchEventsRich(params as Parameters<typeof fetchEventsRich>[0])
    },
    placeholderData: keepPreviousData,
  })

  // Accumulate results for "show more" pagination
  const events = offset === 0
    ? (data?.events || [])
    : [...accumulated, ...(data?.events || [])]

  const total = data?.total || 0
  const hasMore = events.length < total

  const handleShowMore = () => {
    setAccumulated(events)
    setOffset(events.length)
  }

  // Reset pagination when filters change
  const handleFilterChange = (setter: (v: string) => void, value: string) => {
    setter(value)
    setOffset(0)
    setAccumulated([])
  }

  const COUNTRIES = ['China', 'Iran', 'Russia', 'Turkey', 'United States']
  const PHASES = ['emerging', 'developing', 'peak', 'fading', 'dormant']

  return (
    <div className="page">
      <header className="page-header">
        <h1>
          <Zap size={28} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          Event Intelligence
        </h1>
        <p>Tracked diplomatic events with materiality scoring and narrative analysis</p>
      </header>

      {/* Filters row */}
      <div className="ev-filters">
        <div className="ev-filter-group">
          <Filter size={14} />
          <select
            value={countryFilter}
            onChange={e => handleFilterChange(setCountryFilter, e.target.value)}
          >
            <option value="ALL">All Influencers</option>
            {COUNTRIES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        <div className="ev-filter-group">
          <Globe size={14} />
          <select
            value={recipientFilter}
            onChange={e => handleFilterChange(setRecipientFilter, e.target.value)}
          >
            <option value="ALL">All Recipients</option>
            {(filterOptions?.recipients || []).map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        <div className="ev-filter-group">
          <Tag size={14} />
          <select
            value={phaseFilter}
            onChange={e => handleFilterChange(setPhaseFilter, e.target.value)}
          >
            <option value="ALL">All Phases</option>
            {PHASES.map(p => (
              <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
            ))}
          </select>
        </div>

        <div className="ev-filter-group">
          <Zap size={14} />
          <select
            value={materialityFilter}
            onChange={e => handleFilterChange(setMaterialityFilter, e.target.value)}
          >
            {MATERIALITY_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <div className="ev-filter-group">
          <Calendar size={14} />
          <input
            type="date"
            value={startDate}
            onChange={e => handleFilterChange(setStartDate, e.target.value)}
            title="Only show events active on or after this date"
          />
          <span style={{ color: '#94a3b8' }}>–</span>
          <input
            type="date"
            value={endDate}
            onChange={e => handleFilterChange(setEndDate, e.target.value)}
            title="Only show events active on or before this date"
          />
        </div>

        <div className="ev-filter-group">
          <ArrowUpDown size={14} />
          <select
            value={sortBy}
            onChange={e => handleFilterChange(setSortBy, e.target.value)}
          >
            <option value="recency">Most Recent</option>
            <option value="articles">Most Articles</option>
            <option value="materiality">Highest Materiality</option>
          </select>
        </div>

        {total > 0 && (
          <span className="ev-count">
            {total.toLocaleString()} events
          </span>
        )}
      </div>

      {/* Event list */}
      {isLoading && offset === 0 ? (
        <div className="loading">Loading events...</div>
      ) : events.length > 0 ? (
        <>
          <div className="ev-list">
            {events.map((event: Event) => (
              <EventCard
                key={event.id}
                event={event}
                onClick={() => navigate(`/events/${event.id}`)}
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
          <Calendar size={48} />
          <h3>No Events Found</h3>
          <p>
            {countryFilter !== 'ALL' || recipientFilter !== 'ALL' || phaseFilter !== 'ALL' || materialityFilter || startDate || endDate
              ? 'Try adjusting the filters to see more events.'
              : 'Events will appear here once they are tracked in the database.'}
          </p>
        </div>
      )}
    </div>
  )
}
