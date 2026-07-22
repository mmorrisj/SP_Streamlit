import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell
} from 'recharts'
import {
  fetchInfluencerOverview,
  fetchInfluencerEvents,
  fetchInfluencerEntities,
  fetchInfluencerBilateralSummaries,
  fetchInfluencerCategorySummaries,
  fetchInfluencerSources,
  fetchInfluencerTimeline,
} from '../api/client'
import { useDrilldown } from '../hooks/useDrilldown'
import type {
  InfluencerEvent,
  InfluencerEntity,
  BilateralSummary,
  CategoryStrategySummary,
  TimelineItem,
} from '../api/client'
import PageGuide from '../components/PageGuide'
import './Pages.css'
import './InfluencerPage.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a2c4e8']

const PHASE_COLORS: Record<string, string> = {
  emerging: '#22c55e',
  developing: '#3b82f6',
  peak: '#f59e0b',
  fading: '#94a3b8',
  dormant: '#cbd5e1',
}

const ENTITY_TYPE_LABELS: Record<string, string> = {
  person: 'Person',
  organization: 'Organization',
  company: 'Company',
  location: 'Location',
  other: 'Other',
}

const ROLE_LABELS: Record<string, string> = {
  government_official: 'Government Official',
  diplomat: 'Diplomat',
  business_leader: 'Business Leader',
  military_leader: 'Military Leader',
  religious_leader: 'Religious Leader',
  media_figure: 'Media Figure',
  academic: 'Academic',
  ngo_leader: 'NGO Leader',
  international_org: 'International Org',
  other: 'Other',
}

const SECTION_IDS = ['overview', 'events', 'entities', 'bilateral', 'categories', 'sources', 'timeline'] as const

const INTENSITY_COLORS: Record<string, string> = {
  breaking: '#ef4444',
  developing: '#f59e0b',
  'follow-up': '#3b82f6',
  recap: '#94a3b8',
}

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Social: '#059669',
  Military: '#dc2626',
  Diplomacy: '#7c3aed',
}

export default function InfluencerPage() {
  const { country } = useParams<{ country: string }>()
  const navigate = useNavigate()

  // Sticky nav active section
  const [activeSection, setActiveSection] = useState<string>('overview')
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

  // Event state
  const [eventSort, setEventSort] = useState<string>('recency')
  const [eventOffset, setEventOffset] = useState(0)
  const [allEvents, setAllEvents] = useState<InfluencerEvent[]>([])

  // Entity state
  const [entityType, setEntityType] = useState<string | undefined>(undefined)
  const [entitySort, setEntitySort] = useState<string>('documents')
  const [entityOffset, setEntityOffset] = useState(0)
  const [allEntities, setAllEntities] = useState<InfluencerEntity[]>([])

  // Timeline state
  const [timelineOffset, setTimelineOffset] = useState(0)
  const [allTimelineItems, setAllTimelineItems] = useState<TimelineItem[]>([])

  // Category Strategy state
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)

  // Reset state when country changes
  useEffect(() => {
    setEventOffset(0)
    setAllEvents([])
    setEntityOffset(0)
    setAllEntities([])
    setEntityType(undefined)
    setEventSort('recency')
    setEntitySort('documents')
    setTimelineOffset(0)
    setAllTimelineItems([])
    setExpandedCategory(null)
  }, [country])

  // ---- Queries ----

  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['influencerOverview', country],
    queryFn: () => fetchInfluencerOverview(country!),
    enabled: !!country,
  })

  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ['influencerEvents', country, eventSort, eventOffset],
    queryFn: () => fetchInfluencerEvents(country!, { limit: 10, offset: eventOffset, sort_by: eventSort }),
    enabled: !!country,
  })

  const { data: entitiesData, isLoading: entitiesLoading } = useQuery({
    queryKey: ['influencerEntities', country, entityType, entitySort, entityOffset],
    queryFn: () => fetchInfluencerEntities(country!, { limit: 20, offset: entityOffset, entity_type: entityType, sort_by: entitySort }),
    enabled: !!country,
  })

  const { data: bilateralData, isLoading: bilateralLoading } = useQuery({
    queryKey: ['influencerBilateral', country],
    queryFn: () => fetchInfluencerBilateralSummaries(country!),
    enabled: !!country,
  })

  const { data: categoryData, isLoading: categoryLoading } = useQuery({
    queryKey: ['influencerCategories', country],
    queryFn: () => fetchInfluencerCategorySummaries(country!),
    enabled: !!country,
  })

  const { data: sourcesData, isLoading: sourcesLoading } = useQuery({
    queryKey: ['influencerSources', country],
    queryFn: () => fetchInfluencerSources(country!, { limit: 25 }),
    enabled: !!country,
  })

  const { data: timelineData, isLoading: timelineLoading } = useQuery({
    queryKey: ['influencerTimeline', country, timelineOffset],
    queryFn: () => fetchInfluencerTimeline(country!, { limit: 30, offset: timelineOffset }),
    enabled: !!country,
  })

  // Accumulate events on "show more"
  useEffect(() => {
    if (eventsData?.events) {
      if (eventOffset === 0) {
        setAllEvents(eventsData.events)
      } else {
        setAllEvents(prev => [...prev, ...eventsData.events])
      }
    }
  }, [eventsData, eventOffset])

  // Accumulate entities on "show more"
  useEffect(() => {
    if (entitiesData?.entities) {
      if (entityOffset === 0) {
        setAllEntities(entitiesData.entities)
      } else {
        setAllEntities(prev => [...prev, ...entitiesData.entities])
      }
    }
  }, [entitiesData, entityOffset])

  // Reset accumulation on sort/filter change
  useEffect(() => {
    setEventOffset(0)
    setAllEvents([])
  }, [eventSort])

  useEffect(() => {
    setEntityOffset(0)
    setAllEntities([])
  }, [entityType, entitySort])

  // Accumulate timeline items on "show more"
  useEffect(() => {
    if (timelineData?.items) {
      if (timelineOffset === 0) {
        setAllTimelineItems(timelineData.items)
      } else {
        setAllTimelineItems(prev => [...prev, ...timelineData.items])
      }
    }
  }, [timelineData, timelineOffset])

  // ---- Intersection Observer for sticky nav ----
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id)
          }
        }
      },
      { rootMargin: '-120px 0px -60% 0px', threshold: 0 }
    )

    for (const id of SECTION_IDS) {
      const el = sectionRefs.current[id]
      if (el) observer.observe(el)
    }

    return () => observer.disconnect()
  }, [overview]) // re-attach after data loads

  const scrollToSection = useCallback((id: string) => {
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const openDrilldown = useDrilldown({
    initiating_country: country,
    page_source: 'Influencer Profile',
  })

  // Helper: top N from Record<string, number>
  const topEntries = (obj: Record<string, number>, n: number) =>
    Object.entries(obj).sort(([, a], [, b]) => b - a).slice(0, n)

  // ---- Render ----

  if (overviewLoading) {
    return (
      <div className="page">
        <div className="loading">Loading {country} data...</div>
      </div>
    )
  }

  if (!overview) {
    return (
      <div className="page">
        <div className="error">
          <h3>No data available for {country}</h3>
        </div>
      </div>
    )
  }

  return (
    <div className="page influencer-page">
      {/* Header */}
      <header className="influencer-header">
        <div className="influencer-title">
          <h1>{country}</h1>
          <p className="influencer-subtitle">Soft Power Activities & Influence</p>
        </div>
        <div className="influencer-stats-inline">
          <div className="inline-stat">
            <span className="inline-stat-value">{overview.total_documents.toLocaleString()}</span>
            <span className="inline-stat-label">Documents</span>
          </div>
          <div className="inline-stat">
            <span className="inline-stat-value">{overview.total_events.toLocaleString()}</span>
            <span className="inline-stat-label">Events</span>
          </div>
          <div className="inline-stat">
            <span className="inline-stat-value">{overview.total_entities.toLocaleString()}</span>
            <span className="inline-stat-label">Entities</span>
          </div>
          <div className="inline-stat">
            <span className="inline-stat-value">{overview.total_recipients}</span>
            <span className="inline-stat-label">Recipients</span>
          </div>
          {overview.avg_material_score !== null && (
            <div className="inline-stat">
              <span className="inline-stat-value">{overview.avg_material_score}</span>
              <span className="inline-stat-label">Avg Materiality</span>
            </div>
          )}
        </div>
      </header>

      <PageGuide page="influencer-profile" />

      {/* Sticky Section Nav */}
      <nav className="section-nav">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'events', label: 'Events' },
          { id: 'entities', label: 'Key Actors' },
          { id: 'bilateral', label: 'Bilateral' },
          { id: 'categories', label: 'Categories' },
          { id: 'sources', label: 'Sources' },
          { id: 'timeline', label: 'Timeline' },
        ].map(({ id, label }) => (
          <button
            key={id}
            className={`section-nav-btn ${activeSection === id ? 'active' : ''}`}
            onClick={() => scrollToSection(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* ===== 1. OVERVIEW SECTION ===== */}
      <section id="overview" ref={el => { sectionRefs.current.overview = el }} className="inf-section">
        <h2 className="inf-section-title">Activity Overview</h2>

        {/* Activity Trend */}
        <div className="chart-card full-width">
          <h3>Weekly Activity Trend</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={overview.recent_activity_trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="week" tick={{ fontSize: 11 }} />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#1a365d" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="charts-grid">
          {/* Category Donut */}
          <div className="chart-card">
            <h3>Categories</h3>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={overview.top_categories}
                  dataKey="count"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={90}
                  label={(props: any) =>
                    `${props.category} ${(props.percent * 100).toFixed(0)}%`
                  }
                  onClick={(entry: any) => {
                    if (entry?.category) {
                      openDrilldown({ dimension: 'category', value: entry.category, chart_type: 'pie' })
                    }
                  }}
                  style={{ cursor: 'pointer' }}
                >
                  {overview.top_categories.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Top Recipients Bar */}
          <div className="chart-card">
            <h3>Top Recipients</h3>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={overview.top_recipients}
                layout="vertical"
                onClick={(e) => {
                  if (e?.activeLabel) {
                    openDrilldown({ dimension: 'recipient_country', value: e.activeLabel as string, chart_type: 'bar' })
                  }
                }}
                style={{ cursor: 'pointer' }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="country" type="category" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#1a365d" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Source Breakdown */}
        {overview.source_breakdown.length > 0 && (
          <div className="chart-card full-width">
            <h3>Top Sources</h3>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart
                data={overview.source_breakdown}
                layout="vertical"
                onClick={(e) => {
                  if (e?.activeLabel) {
                    openDrilldown({ dimension: 'source', value: e.activeLabel as string, chart_type: 'bar' })
                  }
                }}
                style={{ cursor: 'pointer' }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="source" type="category" width={180} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#4a6fa5" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* ===== 2. EVENT INTELLIGENCE ===== */}
      <section id="events" ref={el => { sectionRefs.current.events = el }} className="inf-section">
        <div className="inf-section-header">
          <h2 className="inf-section-title">Event Intelligence</h2>
          <div className="sort-controls">
            <span className="sort-label">Sort by:</span>
            {(['recency', 'articles', 'materiality'] as const).map(s => (
              <button
                key={s}
                className={`sort-btn ${eventSort === s ? 'active' : ''}`}
                onClick={() => setEventSort(s)}
              >
                {s === 'recency' ? 'Recent' : s === 'articles' ? 'Articles' : 'Materiality'}
              </button>
            ))}
          </div>
        </div>

        {eventsLoading && allEvents.length === 0 ? (
          <div className="loading">Loading events...</div>
        ) : (
          <>
            <div className="events-grid">
              {allEvents.map((event) => (
                <EventCard key={event.id} event={event} />
              ))}
            </div>

            {eventsData && allEvents.length < eventsData.total && (
              <div className="show-more-container">
                <button
                  className="show-more-btn"
                  onClick={() => setEventOffset(prev => prev + 10)}
                  disabled={eventsLoading}
                >
                  {eventsLoading ? 'Loading...' : `Show more (${allEvents.length} of ${eventsData.total})`}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {/* ===== 3. KEY ACTORS & ENTITIES ===== */}
      <section id="entities" ref={el => { sectionRefs.current.entities = el }} className="inf-section">
        <div className="inf-section-header">
          <h2 className="inf-section-title">Key Actors & Entities</h2>
          <div className="sort-controls">
            <span className="sort-label">Sort:</span>
            {(['documents', 'recency'] as const).map(s => (
              <button
                key={s}
                className={`sort-btn ${entitySort === s ? 'active' : ''}`}
                onClick={() => setEntitySort(s)}
              >
                {s === 'documents' ? 'Most Active' : 'Recent'}
              </button>
            ))}
          </div>
        </div>

        {/* Entity Type Filter Tabs */}
        <div className="entity-type-tabs">
          {[
            { value: undefined, label: 'All' },
            { value: 'person', label: 'People' },
            { value: 'organization', label: 'Organizations' },
            { value: 'company', label: 'Companies' },
          ].map(({ value, label }) => (
            <button
              key={label}
              className={`tab ${entityType === value ? 'active' : ''}`}
              onClick={() => setEntityType(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {entitiesLoading && allEntities.length === 0 ? (
          <div className="loading">Loading entities...</div>
        ) : (
          <>
            <div className="entities-grid">
              {allEntities.map((entity) => (
                <EntityCard key={entity.id} entity={entity} topEntries={topEntries} />
              ))}
            </div>

            {entitiesData && allEntities.length < entitiesData.total && (
              <div className="show-more-container">
                <button
                  className="show-more-btn"
                  onClick={() => setEntityOffset(prev => prev + 20)}
                  disabled={entitiesLoading}
                >
                  {entitiesLoading ? 'Loading...' : `Show more (${allEntities.length} of ${entitiesData.total})`}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {/* ===== 4. BILATERAL RELATIONSHIPS ===== */}
      <section id="bilateral" ref={el => { sectionRefs.current.bilateral = el }} className="inf-section">
        <h2 className="inf-section-title">Bilateral Relationships</h2>

        {bilateralLoading ? (
          <div className="loading">Loading bilateral data...</div>
        ) : bilateralData && bilateralData.summaries.length > 0 ? (
          <div className="bilateral-grid">
            {bilateralData.summaries.map((summary) => (
              <BilateralCard
                key={summary.recipient_country}
                summary={summary}
                influencer={country!}
                onNavigate={() => navigate(`/bilateral/${country}/${summary.recipient_country}`)}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p>No bilateral summaries available yet.</p>
          </div>
        )}
      </section>

      {/* ===== 5. CATEGORY STRATEGY ===== */}
      <section id="categories" ref={el => { sectionRefs.current.categories = el }} className="inf-section">
        <h2 className="inf-section-title">Category Strategy</h2>

        {categoryLoading ? (
          <div className="loading">Loading category data...</div>
        ) : categoryData && categoryData.summaries.length > 0 ? (
          <div className="category-strategy-grid">
            {categoryData.summaries.map((cat) => (
              <CategoryStrategyCard
                key={cat.category}
                summary={cat}
                isExpanded={expandedCategory === cat.category}
                onToggle={() => setExpandedCategory(
                  expandedCategory === cat.category ? null : cat.category
                )}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p>No category summaries available yet.</p>
          </div>
        )}
      </section>

      {/* ===== 6. SOURCE INTELLIGENCE ===== */}
      <section id="sources" ref={el => { sectionRefs.current.sources = el }} className="inf-section">
        <h2 className="inf-section-title">Source Intelligence</h2>

        {sourcesLoading ? (
          <div className="loading">Loading source data...</div>
        ) : sourcesData ? (
          <>
            {/* KPI row */}
            <div className="source-kpi-row">
              <div className="source-kpi">
                <span className="source-kpi-value">{sourcesData.total_sources}</span>
                <span className="source-kpi-label">Unique Sources</span>
              </div>
              <div className="source-kpi">
                <span className="source-kpi-value">{sourcesData.top_geofocus.length}</span>
                <span className="source-kpi-label">Geographic Regions</span>
              </div>
              <div className="source-kpi">
                <span className="source-kpi-value">{sourcesData.top_medium.length}</span>
                <span className="source-kpi-label">Media Types</span>
              </div>
            </div>

            <div className="charts-grid">
              {/* Top Sources */}
              <div className="chart-card">
                <h3>Top Sources by Coverage</h3>
                <ResponsiveContainer width="100%" height={Math.max(280, sourcesData.sources.length * 28)}>
                  <BarChart
                    data={sourcesData.sources.slice(0, 15)}
                    layout="vertical"
                    onClick={(e) => {
                      if (e?.activeLabel) {
                        openDrilldown({ dimension: 'source', value: e.activeLabel as string, chart_type: 'bar' })
                      }
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis dataKey="source_name" type="category" width={160} tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="doc_count" fill="#1a365d" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Geographic Focus */}
              {sourcesData.top_geofocus.length > 0 && (
                <div className="chart-card">
                  <h3>Geographic Focus</h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie
                        data={sourcesData.top_geofocus.slice(0, 8)}
                        dataKey="count"
                        nameKey="geofocus"
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={85}
                        label={(props: any) => props.geofocus}
                      >
                        {sourcesData.top_geofocus.slice(0, 8).map((_, i) => (
                          <Cell key={`geo-${i}`} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Media Type breakdown */}
            {sourcesData.top_medium.length > 0 && (
              <div className="chart-card full-width">
                <h3>Media Type Distribution</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={sourcesData.top_medium}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="medium" tick={{ fontSize: 11 }} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" fill="#4a6fa5" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Source Table */}
            <div className="source-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Documents</th>
                    <th>First Seen</th>
                    <th>Last Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {sourcesData.sources.map((src) => (
                    <tr key={src.source_name}>
                      <td>{src.source_name}</td>
                      <td><strong>{src.doc_count.toLocaleString()}</strong></td>
                      <td>{src.first_date}</td>
                      <td>{src.last_date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      {/* ===== 7. ACTIVITY TIMELINE ===== */}
      <section id="timeline" ref={el => { sectionRefs.current.timeline = el }} className="inf-section">
        <h2 className="inf-section-title">Activity Timeline</h2>

        {timelineLoading && allTimelineItems.length === 0 ? (
          <div className="loading">Loading timeline...</div>
        ) : allTimelineItems.length > 0 ? (
          <>
            <div className="timeline-feed">
              {allTimelineItems.map((item, idx) => (
                <TimelineCard key={`${item.date}-${item.event_name}-${idx}`} item={item} />
              ))}
            </div>

            {timelineData && allTimelineItems.length < timelineData.total && (
              <div className="show-more-container">
                <button
                  className="show-more-btn"
                  onClick={() => setTimelineOffset(prev => prev + 30)}
                  disabled={timelineLoading}
                >
                  {timelineLoading ? 'Loading...' : `Show more (${allTimelineItems.length} of ${timelineData.total})`}
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="empty-state">
            <p>No timeline data available yet.</p>
          </div>
        )}
      </section>
    </div>
  )
}


// ---- Sub-components ----

function EventCard({ event }: { event: InfluencerEvent }) {
  const navigate = useNavigate()
  const topRecipients = Object.entries(event.primary_recipients || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  const topCategories = Object.entries(event.primary_categories || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  return (
    <div className="event-card-rich" style={{ cursor: 'pointer' }} onClick={() => navigate(`/events/${event.id}`)}>
      <div className="event-card-header">
        <h4>{event.event_name}</h4>
        {event.story_phase && (
          <span
            className="phase-badge"
            style={{ backgroundColor: PHASE_COLORS[event.story_phase] || '#94a3b8' }}
          >
            {event.story_phase}
          </span>
        )}
      </div>

      {event.description && (
        <p className="event-description">{event.description.slice(0, 300)}{event.description.length > 300 ? '...' : ''}</p>
      )}

      {event.narrative_outcomes && (
        <p style={{ color: '#475569', fontSize: '0.85rem', lineHeight: 1.5, margin: '0.25rem 0 0.5rem', fontStyle: 'italic' }}>
          {event.narrative_outcomes.slice(0, 200)}{event.narrative_outcomes.length > 200 ? '...' : ''}
        </p>
      )}

      <div className="event-metrics-row">
        <div className="event-metric">
          <span className="event-metric-value">{event.total_articles}</span>
          <span className="event-metric-label">articles</span>
        </div>
        <div className="event-metric">
          <span className="event-metric-value">{event.total_mention_days}</span>
          <span className="event-metric-label">days</span>
        </div>
        {event.material_score !== null && (
          <div className="event-metric">
            <span className="event-metric-value">{event.material_score}</span>
            <span className="event-metric-label">materiality</span>
          </div>
        )}
        <div className="event-metric">
          <span className="event-metric-value">{event.source_count}</span>
          <span className="event-metric-label">sources</span>
        </div>
      </div>

      <div className="event-date-range">
        {event.first_mention_date} — {event.last_mention_date}
        {event.peak_mention_date && (
          <span className="event-peak"> (peak: {event.peak_mention_date})</span>
        )}
        {event.source_link && (
          <a
            href={event.source_link}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{ marginLeft: '0.75rem', color: '#3b82f6', fontSize: '0.8rem', textDecoration: 'none' }}
          >
            View Sources
          </a>
        )}
      </div>

      {(topCategories.length > 0 || topRecipients.length > 0) && (
        <div className="event-tags">
          {topCategories.map(([cat]) => (
            <span key={cat} className="tag cat-tag">{cat}</span>
          ))}
          {topRecipients.map(([rec]) => (
            <span key={rec} className="tag rec-tag">{rec}</span>
          ))}
        </div>
      )}
    </div>
  )
}


function EntityCard({
  entity,
  topEntries,
}: {
  entity: InfluencerEntity
  topEntries: (obj: Record<string, number>, n: number) => [string, number][]
}) {
  const navigate = useNavigate()
  const topCats = topEntries(entity.primary_categories || {}, 3)
  const topRecs = topEntries(entity.primary_recipients || {}, 3)

  return (
    <div
      className="entity-card"
      style={{ cursor: 'pointer' }}
      onClick={() => navigate(`/entity/${entity.id}`)}
    >
      <div className="entity-card-header">
        <div className="entity-name-row">
          {entity.entity_type && (
            <span className={`entity-type-badge ${entity.entity_type}`}>
              {ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type}
            </span>
          )}
          <h4>{entity.canonical_name}</h4>
        </div>
        {entity.primary_role && (
          <span className="entity-role">
            {ROLE_LABELS[entity.primary_role] || entity.primary_role}
          </span>
        )}
      </div>

      {entity.entity_description && (
        <p className="entity-description">
          {entity.entity_description.slice(0, 200)}{entity.entity_description.length > 200 ? '...' : ''}
        </p>
      )}

      <div className="entity-metrics-row">
        <div className="event-metric">
          <span className="event-metric-value">{entity.total_documents}</span>
          <span className="event-metric-label">documents</span>
        </div>
        <div className="event-metric">
          <span className="event-metric-value">{entity.total_mention_days}</span>
          <span className="event-metric-label">active days</span>
        </div>
      </div>

      <div className="entity-date-range">
        {entity.first_mention_date} — {entity.last_mention_date}
      </div>

      {(topCats.length > 0 || topRecs.length > 0) && (
        <div className="event-tags">
          {topCats.map(([cat]) => (
            <span key={cat} className="tag cat-tag">{cat}</span>
          ))}
          {topRecs.map(([rec]) => (
            <span key={rec} className="tag rec-tag">{rec}</span>
          ))}
        </div>
      )}
    </div>
  )
}


function BilateralCard({
  summary,
  onNavigate,
}: {
  summary: BilateralSummary
  influencer: string
  onNavigate: () => void
}) {
  const totalCat = Object.values(summary.count_by_category || {}).reduce((a, b) => a + b, 0) || 1
  const categoryBars = Object.entries(summary.count_by_category || {})
    .sort(([, a], [, b]) => b - a)

  return (
    <div className="bilateral-card" onClick={onNavigate}>
      <div className="bilateral-card-header">
        <h4>{summary.recipient_country}</h4>
        <span className="bilateral-doc-count">{summary.total_documents.toLocaleString()} docs</span>
      </div>

      {/* Category mini-bars */}
      <div className="category-mini-bars">
        {categoryBars.map(([cat, count], i) => (
          <div key={cat} className="mini-bar-row">
            <span className="mini-bar-label">{cat}</span>
            <div className="mini-bar-track">
              <div
                className="mini-bar-fill"
                style={{
                  width: `${(count / totalCat) * 100}%`,
                  backgroundColor: COLORS[i % COLORS.length],
                }}
              />
            </div>
            <span className="mini-bar-count">{count}</span>
          </div>
        ))}
      </div>

      {summary.overview && (
        <p className="bilateral-overview">
          {summary.overview.slice(0, 180)}{summary.overview.length > 180 ? '...' : ''}
        </p>
      )}

      {summary.key_themes && summary.key_themes.length > 0 && (
        <div className="event-tags">
          {summary.key_themes.slice(0, 3).map(theme => (
            <span key={theme} className="tag cat-tag">{theme}</span>
          ))}
        </div>
      )}

      <div className="bilateral-card-footer">
        <span className="view-details">View details &rarr;</span>
      </div>
    </div>
  )
}


function CategoryStrategyCard({
  summary,
  isExpanded,
  onToggle,
}: {
  summary: CategoryStrategySummary
  isExpanded: boolean
  onToggle: () => void
}) {
  const topRecipients = Object.entries(summary.count_by_recipient || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5)

  const topSubcategories = Object.entries(summary.count_by_subcategory || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6)

  // Build monthly trend for sparkline
  const monthlyData = Object.entries(summary.activity_by_month || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-12)
    .map(([month, count]) => ({ month: month.slice(0, 7), count }))

  return (
    <div className={`category-strategy-card ${isExpanded ? 'expanded' : ''}`}>
      <div className="cat-strat-header" onClick={onToggle}>
        <div className="cat-strat-title-row">
          <span
            className="cat-strat-color"
            style={{ backgroundColor: CATEGORY_COLORS[summary.category] || '#475569' }}
          />
          <h3>{summary.category}</h3>
          <span className="cat-strat-docs">{summary.total_documents.toLocaleString()} docs</span>
        </div>
        <span className="cat-strat-expand">{isExpanded ? '−' : '+'}</span>
      </div>

      {summary.overview && (
        <p className="cat-strat-overview">
          {isExpanded ? summary.overview : `${summary.overview.slice(0, 150)}${summary.overview.length > 150 ? '...' : ''}`}
        </p>
      )}

      {/* Key strategies shown even when collapsed */}
      {summary.key_strategies && summary.key_strategies.length > 0 && (
        <div className="event-tags">
          {summary.key_strategies.slice(0, isExpanded ? 10 : 3).map(strat => (
            <span key={strat} className="tag cat-tag">{strat}</span>
          ))}
        </div>
      )}

      {isExpanded && (
        <div className="cat-strat-details">
          {/* Mini monthly trend */}
          {monthlyData.length > 0 && (
            <div className="cat-strat-chart">
              <h4>Monthly Trend</h4>
              <ResponsiveContainer width="100%" height={150}>
                <BarChart data={monthlyData}>
                  <XAxis dataKey="month" tick={{ fontSize: 9 }} />
                  <YAxis hide />
                  <Tooltip />
                  <Bar
                    dataKey="count"
                    fill={CATEGORY_COLORS[summary.category] || '#475569'}
                    radius={[2, 2, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Subcategory breakdown */}
          {topSubcategories.length > 0 && (
            <div className="cat-strat-breakdown">
              <h4>Subcategories</h4>
              <div className="breakdown-grid">
                {topSubcategories.map(([sub, count]) => (
                  <div key={sub} className="breakdown-item">
                    <span className="breakdown-label">{sub}</span>
                    <span className="breakdown-value">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top recipients for this category */}
          {topRecipients.length > 0 && (
            <div className="cat-strat-breakdown">
              <h4>Top Recipients</h4>
              <div className="breakdown-grid">
                {topRecipients.map(([rec, count]) => (
                  <div key={rec} className="breakdown-item">
                    <span className="breakdown-label">{rec}</span>
                    <span className="breakdown-value">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Trend analysis */}
          {summary.trend_analysis && (
            <div className="cat-strat-trend">
              <h4>Trend Analysis</h4>
              <p>{summary.trend_analysis}</p>
            </div>
          )}

          {/* Major initiatives */}
          {summary.major_initiatives && summary.major_initiatives.length > 0 && (
            <div className="cat-strat-initiatives">
              <h4>Major Initiatives</h4>
              {summary.major_initiatives.slice(0, 5).map((init, i) => (
                <div key={i} className="initiative-item">
                  <strong>{init.name}</strong>
                  {init.timeframe && <span className="initiative-timeframe">{init.timeframe}</span>}
                  {init.description && <p>{init.description}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function TimelineCard({ item }: { item: TimelineItem }) {
  return (
    <div className="timeline-item">
      <div className="timeline-marker">
        <div className="timeline-dot" />
        <div className="timeline-line" />
      </div>
      <div className="timeline-content">
        <div className="timeline-date-row">
          <span className="timeline-date">{item.date}</span>
          {item.news_intensity && (
            <span
              className="intensity-badge"
              style={{ backgroundColor: INTENSITY_COLORS[item.news_intensity] || '#94a3b8' }}
            >
              {item.news_intensity}
            </span>
          )}
          {item.story_phase && (
            <span
              className="phase-badge"
              style={{ backgroundColor: PHASE_COLORS[item.story_phase] || '#94a3b8' }}
            >
              {item.story_phase}
            </span>
          )}
          {item.mention_context && (
            <span className="context-badge">{item.mention_context}</span>
          )}
        </div>

        <h4 className="timeline-event-name">{item.event_name}</h4>

        {item.headline && (
          <p className="timeline-headline">{item.headline}</p>
        )}

        {item.summary && (
          <p className="timeline-summary">
            {item.summary.slice(0, 200)}{item.summary.length > 200 ? '...' : ''}
          </p>
        )}

        <div className="timeline-meta-row">
          <span className="timeline-meta">{item.article_count} articles</span>
          <span className="timeline-meta">{item.source_count} sources</span>
          {item.material_score !== null && (
            <span className="timeline-meta">materiality: {item.material_score}</span>
          )}
          {item.source_link && (
            <a
              href={item.source_link}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#3b82f6', fontSize: '0.8rem', textDecoration: 'none' }}
            >
              View Sources
            </a>
          )}
        </div>

        {(item.categories.length > 0 || item.recipients.length > 0) && (
          <div className="event-tags">
            {item.categories.map(cat => (
              <span key={cat} className="tag cat-tag">{cat}</span>
            ))}
            {item.recipients.map(rec => (
              <span key={rec} className="tag rec-tag">{rec}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
