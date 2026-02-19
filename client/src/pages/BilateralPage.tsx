import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import {
  ArrowRight,
  FileText,
  Calendar,
  Users,
  Activity,
  ChevronDown,
  ChevronUp,
  Zap,
  Target,
  BarChart3,
  Newspaper,
} from 'lucide-react'
import {
  fetchBilateralEnhancedOverview,
  fetchBilateralRelationshipProfile,
  fetchBilateralCategorySummaries,
  fetchBilateralEvents,
  fetchBilateralEntities,
  fetchBilateralSources,
} from '../api/client'
import type {
  BilateralEvent,
  BilateralEntity,
  BilateralCatSummary,
} from '../api/client'
import './BilateralPage.css'

// ─── Constants ────────────────────────────────────────────────────
const COLORS = ['#1a365d', '#2d4a7c', '#4a90e2', '#7bb3ff', '#a8d0ff', '#c3daf7']

const PHASE_COLORS: Record<string, string> = {
  emerging: '#f59e0b',
  developing: '#3b82f6',
  established: '#10b981',
  escalating: '#ef4444',
  declining: '#6b7280',
  resolved: '#8b5cf6',
}

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#1a365d',
  Military: '#8b1a1a',
  Social: '#1a5f1a',
  Diplomacy: '#5f1a5f',
}

const ENTITY_TYPE_LABELS: Record<string, string> = {
  person: 'Person',
  organization: 'Organization',
  company: 'Company',
  government_body: 'Gov Body',
  military_unit: 'Military',
  media_outlet: 'Media',
  political_party: 'Party',
  ngo: 'NGO',
  educational_institution: 'Education',
  other: 'Other',
}

const ROLE_LABELS: Record<string, string> = {
  government_official: 'Gov Official',
  diplomat: 'Diplomat',
  military_leader: 'Military Leader',
  business_executive: 'Business Exec',
  journalist: 'Journalist',
  activist: 'Activist',
  academic: 'Academic',
  religious_leader: 'Religious Leader',
  other: 'Other',
}

// ─── Section IDs ──────────────────────────────────────────────────
const SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'profile', label: 'AI Profile' },
  { id: 'categories', label: 'Categories' },
  { id: 'events', label: 'Events' },
  { id: 'actors', label: 'Actors' },
  { id: 'impact', label: 'Impact' },
  { id: 'sources', label: 'Sources' },
]

// ─── Sub-components ───────────────────────────────────────────────

function EventCard({ event }: { event: BilateralEvent }) {
  const navigate = useNavigate()
  const topCategory = event.primary_categories
    ? Object.entries(event.primary_categories).sort((a, b) => b[1] - a[1])[0]?.[0]
    : null

  return (
    <div className="bl-event-card" style={{ cursor: 'pointer' }} onClick={() => navigate(`/events/${event.id}`)}>
      <div className="bl-event-card-header">
        <h4>{event.event_name}</h4>
        {event.story_phase && (
          <span
            className="bl-phase-badge"
            style={{ background: PHASE_COLORS[event.story_phase] || '#6b7280' }}
          >
            {event.story_phase}
          </span>
        )}
      </div>
      {event.description && (
        <p className="bl-event-description">{event.description}</p>
      )}
      {event.narrative_outcomes && (
        <p style={{ color: '#475569', fontSize: '0.85rem', lineHeight: 1.5, margin: '0.25rem 0 0.5rem', fontStyle: 'italic' }}>
          {event.narrative_outcomes.slice(0, 200)}{event.narrative_outcomes.length > 200 ? '...' : ''}
        </p>
      )}
      <div className="bl-event-meta">
        {event.first_mention_date && (
          <span className="bl-meta-item">
            <Calendar size={13} />
            {event.first_mention_date}
            {event.last_mention_date && event.last_mention_date !== event.first_mention_date
              ? ` — ${event.last_mention_date}`
              : ''}
          </span>
        )}
        <span className="bl-meta-item">
          <FileText size={13} />
          {event.total_articles} articles
        </span>
        {event.material_score !== null && (
          <span className="bl-meta-item bl-materiality">
            <Zap size={13} />
            {event.material_score.toFixed(1)}
          </span>
        )}
        {topCategory && (
          <span
            className="bl-category-chip"
            style={{ background: CATEGORY_COLORS[topCategory] || '#475569' }}
          >
            {topCategory}
          </span>
        )}
        {event.source_link && (
          <a
            href={event.source_link}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{ color: '#3b82f6', fontSize: '0.8rem', textDecoration: 'none', marginLeft: 'auto' }}
          >
            View Sources
          </a>
        )}
      </div>
    </div>
  )
}

function EntityCard({ entity }: { entity: BilateralEntity }) {
  return (
    <div className="bl-entity-card">
      <div className="bl-entity-header">
        <h4>{entity.canonical_name}</h4>
        {entity.entity_type && (
          <span className={`bl-entity-type-badge bl-etype-${entity.entity_type}`}>
            {ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type}
          </span>
        )}
      </div>
      {entity.primary_role && (
        <div className="bl-entity-role">
          {ROLE_LABELS[entity.primary_role] || entity.primary_role}
        </div>
      )}
      {entity.entity_description && (
        <p className="bl-entity-desc">
          {entity.entity_description.length > 200
            ? entity.entity_description.slice(0, 200) + '...'
            : entity.entity_description}
        </p>
      )}
      <div className="bl-entity-meta">
        <span><FileText size={13} /> {entity.total_documents} docs</span>
        {entity.first_mention_date && (
          <span>
            <Calendar size={13} />
            {entity.first_mention_date}
            {entity.last_mention_date && entity.last_mention_date !== entity.first_mention_date
              ? ` — ${entity.last_mention_date}`
              : ''}
          </span>
        )}
      </div>
    </div>
  )
}

function CategoryCard({ summary, expanded, onToggle }: {
  summary: BilateralCatSummary
  expanded: boolean
  onToggle: () => void
}) {
  const monthData = Object.entries(summary.activity_by_month || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-12)
    .map(([month, count]) => ({
      month: month.slice(0, 7),
      count,
    }))

  const topSubcategories = Object.entries(summary.count_by_subcategory || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)

  return (
    <div className={`bl-cat-card ${expanded ? 'expanded' : ''}`}>
      <div className="bl-cat-card-header" onClick={onToggle}>
        <div className="bl-cat-card-title">
          <span
            className="bl-cat-dot"
            style={{ background: CATEGORY_COLORS[summary.category] || '#475569' }}
          />
          <h4>{summary.category}</h4>
          <span className="bl-cat-doc-count">{summary.total_documents.toLocaleString()} docs</span>
          {summary.material_score_avg !== null && (
            <span className="bl-cat-mat-score">
              <Zap size={12} /> {summary.material_score_avg.toFixed(1)}
            </span>
          )}
        </div>
        {expanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
      </div>

      {expanded && (
        <div className="bl-cat-card-body">
          {summary.overview && (
            <p className="bl-cat-overview">{summary.overview}</p>
          )}

          {summary.key_focus_areas.length > 0 && (
            <div className="bl-cat-themes">
              <strong>Focus Areas:</strong>
              <div className="bl-theme-tags">
                {summary.key_focus_areas.map((area, i) => (
                  <span key={i} className="bl-theme-tag">{area}</span>
                ))}
              </div>
            </div>
          )}

          {summary.interaction_patterns && (
            <div className="bl-cat-section">
              <strong>Interaction Patterns</strong>
              <p>{summary.interaction_patterns}</p>
            </div>
          )}

          {summary.impact_assessment && (
            <div className="bl-cat-section">
              <strong>Impact Assessment</strong>
              <p>{summary.impact_assessment}</p>
            </div>
          )}

          {topSubcategories.length > 0 && (
            <div className="bl-cat-section">
              <strong>Top Subcategories</strong>
              <div className="bl-subcat-bars">
                {topSubcategories.map(([subcat, count]) => (
                  <div key={subcat} className="bl-subcat-row">
                    <span className="bl-subcat-label">{subcat}</span>
                    <div className="bl-subcat-bar-track">
                      <div
                        className="bl-subcat-bar-fill"
                        style={{
                          width: `${(count / topSubcategories[0][1]) * 100}%`,
                          background: CATEGORY_COLORS[summary.category] || '#475569',
                        }}
                      />
                    </div>
                    <span className="bl-subcat-count">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {summary.major_initiatives.length > 0 && (
            <div className="bl-cat-section">
              <strong>Major Initiatives</strong>
              <div className="bl-initiatives">
                {summary.major_initiatives.map((init, i) => (
                  <div key={i} className="bl-initiative-item">
                    <span className="bl-init-name">{init.name}</span>
                    <span className="bl-init-desc">{init.description}</span>
                    {init.timeframe && (
                      <span className="bl-init-time">{init.timeframe}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {monthData.length > 0 && (
            <div className="bl-cat-section">
              <strong>Monthly Activity Trend</strong>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={monthData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar
                    dataKey="count"
                    fill={CATEGORY_COLORS[summary.category] || '#475569'}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main Page Component ──────────────────────────────────────────

export default function BilateralPage() {
  const { influencer, recipient } = useParams<{ influencer: string; recipient: string }>()

  // Section nav state
  const [activeSection, setActiveSection] = useState('overview')
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

  // Events state
  const [eventSort, setEventSort] = useState('recency')
  const [eventOffset, setEventOffset] = useState(0)
  const [allEvents, setAllEvents] = useState<BilateralEvent[]>([])

  // Entities state
  const [entityType, setEntityType] = useState<string | undefined>(undefined)
  const [entitySort, setEntitySort] = useState('documents')
  const [entityOffset, setEntityOffset] = useState(0)
  const [allEntities, setAllEntities] = useState<BilateralEntity[]>([])

  // Category expand state
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)

  // Intersection observer for sticky nav
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id)
          }
        }
      },
      { rootMargin: '-100px 0px -60% 0px', threshold: 0.1 }
    )

    SECTIONS.forEach(({ id }) => {
      const el = sectionRefs.current[id]
      if (el) observer.observe(el)
    })

    return () => observer.disconnect()
  }, [])

  // ─── Data fetching ─────────────────────────────────────────────

  const { data: overview, isLoading: loadingOverview } = useQuery({
    queryKey: ['bilateralEnhancedOverview', influencer, recipient],
    queryFn: () => fetchBilateralEnhancedOverview(influencer!, recipient!),
    enabled: !!influencer && !!recipient,
  })

  const { data: profile } = useQuery({
    queryKey: ['bilateralProfile', influencer, recipient],
    queryFn: () => fetchBilateralRelationshipProfile(influencer!, recipient!),
    enabled: !!influencer && !!recipient,
  })

  const { data: catSummaries } = useQuery({
    queryKey: ['bilateralCatSummaries', influencer, recipient],
    queryFn: () => fetchBilateralCategorySummaries(influencer!, recipient!),
    enabled: !!influencer && !!recipient,
  })

  const { data: eventsData } = useQuery({
    queryKey: ['bilateralEvents', influencer, recipient, eventSort, eventOffset],
    queryFn: () =>
      fetchBilateralEvents(influencer!, recipient!, {
        limit: 10,
        offset: eventOffset,
        sort_by: eventSort,
      }),
    enabled: !!influencer && !!recipient,
  })

  const { data: entitiesData } = useQuery({
    queryKey: ['bilateralEntities', influencer, recipient, entityType, entitySort, entityOffset],
    queryFn: () =>
      fetchBilateralEntities(influencer!, recipient!, {
        limit: 20,
        offset: entityOffset,
        entity_type: entityType,
        sort_by: entitySort,
      }),
    enabled: !!influencer && !!recipient,
  })

  const { data: sourcesData } = useQuery({
    queryKey: ['bilateralSources', influencer, recipient],
    queryFn: () => fetchBilateralSources(influencer!, recipient!),
    enabled: !!influencer && !!recipient,
  })

  // Accumulate events
  useEffect(() => {
    if (eventsData?.events) {
      if (eventOffset === 0) {
        setAllEvents(eventsData.events)
      } else {
        setAllEvents((prev) => [...prev, ...eventsData.events])
      }
    }
  }, [eventsData, eventOffset])

  // Reset events on sort change
  useEffect(() => {
    setEventOffset(0)
    setAllEvents([])
  }, [eventSort])

  // Accumulate entities
  useEffect(() => {
    if (entitiesData?.entities) {
      if (entityOffset === 0) {
        setAllEntities(entitiesData.entities)
      } else {
        setAllEntities((prev) => [...prev, ...entitiesData.entities])
      }
    }
  }, [entitiesData, entityOffset])

  // Reset entities on filter/sort change
  useEffect(() => {
    setEntityOffset(0)
    setAllEntities([])
  }, [entityType, entitySort])

  // ─── Loading / Error states ────────────────────────────────────
  if (loadingOverview) {
    return (
      <div className="page bilateral-page">
        <div className="loading">Loading bilateral relationship data...</div>
      </div>
    )
  }

  if (!overview) {
    return (
      <div className="page bilateral-page">
        <div className="error">Failed to load data for {influencer} → {recipient}</div>
      </div>
    )
  }

  // ─── Derived data ──────────────────────────────────────────────
  const categoryPieData = overview.top_categories.map((c) => ({
    ...c,
    fill: CATEGORY_COLORS[c.category] || COLORS[0],
  }))

  // Material histogram data for impact section
  const histogramData = profile?.material_score_histogram
    ? Object.entries(profile.material_score_histogram)
        .sort(([a], [b]) => parseFloat(a) - parseFloat(b))
        .map(([score, count]) => ({ score, count }))
    : []

  // Activity by month for profile section
  const monthlyActivityData = profile?.activity_by_month
    ? Object.entries(profile.activity_by_month)
        .sort(([a], [b]) => a.localeCompare(b))
        .slice(-18)
        .map(([month, count]) => ({ month: month.slice(0, 7), count }))
    : []

  // ─── Render ────────────────────────────────────────────────────
  return (
    <div className="page bilateral-page">
      {/* Header */}
      <header className="bl-header">
        <div className="bl-title-row">
          <h1>{influencer}</h1>
          <ArrowRight size={36} className="bl-arrow" />
          <h1>{recipient}</h1>
        </div>
        <div className="bl-header-stats">
          <span><FileText size={16} /> {overview.total_documents.toLocaleString()} documents</span>
          <span><Activity size={16} /> {overview.total_events} events</span>
          <span><Users size={16} /> {overview.total_entities} entities</span>
          {overview.avg_material_score !== null && (
            <span><Zap size={16} /> {overview.avg_material_score.toFixed(1)} avg materiality</span>
          )}
          {overview.first_interaction_date && (
            <span><Calendar size={16} /> {overview.first_interaction_date} — {overview.last_interaction_date}</span>
          )}
        </div>
      </header>

      {/* Sticky Section Nav */}
      <nav className="bl-section-nav">
        {SECTIONS.map(({ id, label }) => (
          <a
            key={id}
            href={`#${id}`}
            className={`bl-section-nav-item ${activeSection === id ? 'active' : ''}`}
            onClick={(e) => {
              e.preventDefault()
              sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }}
          >
            {label}
          </a>
        ))}
      </nav>

      {/* ===== 1. OVERVIEW ===== */}
      <section id="overview" ref={(el) => { sectionRefs.current['overview'] = el }}>
        <h2 className="bl-section-title"><BarChart3 size={22} /> Executive Overview</h2>

        {/* KPI Row */}
        <div className="bl-kpi-row">
          <div className="bl-kpi-card">
            <div className="bl-kpi-value">{overview.total_documents.toLocaleString()}</div>
            <div className="bl-kpi-label">Total Documents</div>
          </div>
          <div className="bl-kpi-card">
            <div className="bl-kpi-value">{overview.total_events}</div>
            <div className="bl-kpi-label">Events</div>
          </div>
          <div className="bl-kpi-card">
            <div className="bl-kpi-value">{overview.total_entities}</div>
            <div className="bl-kpi-label">Key Actors</div>
          </div>
          <div className="bl-kpi-card">
            <div className="bl-kpi-value">{overview.avg_material_score?.toFixed(1) ?? 'N/A'}</div>
            <div className="bl-kpi-label">Avg Materiality</div>
          </div>
          <div className="bl-kpi-card">
            <div className="bl-kpi-value">{overview.weekly_average}</div>
            <div className="bl-kpi-label">Weekly Average</div>
          </div>
        </div>

        {/* Activity Trend */}
        <div className="bl-chart-card">
          <h3>Activity Trend (Last 12 Weeks)</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={overview.activity_trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="week" tick={{ fontSize: 11 }} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="count" stroke="#1a365d" strokeWidth={2} name="Documents" dot={{ fill: '#1a365d', r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Category pie + top categories bar side by side */}
        <div className="bl-charts-row">
          <div className="bl-chart-card bl-chart-half">
            <h3>Category Distribution</h3>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={categoryPieData}
                  dataKey="count"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={(props: any) => props.category}
                >
                  {categoryPieData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill || COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="bl-chart-card bl-chart-half">
            <h3>Top Categories</h3>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={overview.top_categories} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="category" width={100} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#1a365d" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* ===== 2. AI RELATIONSHIP PROFILE ===== */}
      <section id="profile" ref={(el) => { sectionRefs.current['profile'] = el }}>
        <h2 className="bl-section-title"><Target size={22} /> AI Relationship Profile</h2>

        {profile ? (
          <div className="bl-profile-content">
            {/* Overview */}
            {profile.overview && (
              <div className="bl-profile-block">
                <h3>Overview</h3>
                <p>{profile.overview}</p>
              </div>
            )}

            {/* Key Themes */}
            {profile.key_themes.length > 0 && (
              <div className="bl-profile-block">
                <h3>Key Themes</h3>
                <div className="bl-theme-tags">
                  {profile.key_themes.map((theme, i) => (
                    <span key={i} className="bl-theme-tag">{theme}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Trend Analysis */}
            {profile.trend_analysis && (
              <div className="bl-profile-block">
                <h3>Trend Analysis</h3>
                <p>{profile.trend_analysis}</p>
              </div>
            )}

            {/* Current Status */}
            {profile.current_status && (
              <div className="bl-profile-block bl-status-block">
                <h3>Current Status</h3>
                <p>{profile.current_status}</p>
              </div>
            )}

            {/* Notable Developments */}
            {profile.notable_developments.length > 0 && (
              <div className="bl-profile-block">
                <h3>Notable Developments</h3>
                <ul className="bl-developments-list">
                  {profile.notable_developments.map((dev, i) => (
                    <li key={i}>{dev}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Major Initiatives */}
            {profile.major_initiatives.length > 0 && (
              <div className="bl-profile-block">
                <h3>Major Initiatives</h3>
                <div className="bl-initiatives">
                  {profile.major_initiatives.map((init, i) => (
                    <div key={i} className="bl-initiative-item">
                      <span className="bl-init-name">{init.name}</span>
                      <span className="bl-init-desc">{init.description}</span>
                      {init.timeframe && (
                        <span className="bl-init-time">{init.timeframe}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Monthly Activity Chart */}
            {monthlyActivityData.length > 0 && (
              <div className="bl-chart-card">
                <h3>Monthly Activity (from AI summary)</h3>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={monthlyActivityData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" fill="#2d4a7c" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        ) : (
          <div className="bl-empty">No AI relationship profile available for this pair.</div>
        )}
      </section>

      {/* ===== 3. CATEGORY DEEP-DIVE ===== */}
      <section id="categories" ref={(el) => { sectionRefs.current['categories'] = el }}>
        <h2 className="bl-section-title"><BarChart3 size={22} /> Category Deep-Dive</h2>

        {catSummaries && catSummaries.summaries.length > 0 ? (
          <div className="bl-cat-list">
            {catSummaries.summaries.map((summary) => (
              <CategoryCard
                key={summary.category}
                summary={summary}
                expanded={expandedCategory === summary.category}
                onToggle={() =>
                  setExpandedCategory(
                    expandedCategory === summary.category ? null : summary.category
                  )
                }
              />
            ))}
          </div>
        ) : (
          <div className="bl-empty">No category-specific analysis available for this pair.</div>
        )}
      </section>

      {/* ===== 4. EVENT INTELLIGENCE ===== */}
      <section id="events" ref={(el) => { sectionRefs.current['events'] = el }}>
        <h2 className="bl-section-title"><Calendar size={22} /> Event Intelligence</h2>

        <div className="bl-controls">
          <label>Sort by:</label>
          <select value={eventSort} onChange={(e) => setEventSort(e.target.value)}>
            <option value="recency">Most Recent</option>
            <option value="articles">Most Articles</option>
            <option value="materiality">Highest Materiality</option>
          </select>
          {eventsData && (
            <span className="bl-total-label">{eventsData.total} total events</span>
          )}
        </div>

        <div className="bl-events-list">
          {allEvents.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>

        {eventsData && allEvents.length < eventsData.total && (
          <button
            className="bl-show-more"
            onClick={() => setEventOffset((prev) => prev + 10)}
          >
            Show More Events
          </button>
        )}

        {allEvents.length === 0 && (
          <div className="bl-empty">No events found for this bilateral pair.</div>
        )}
      </section>

      {/* ===== 5. KEY ACTORS & ENTITIES ===== */}
      <section id="actors" ref={(el) => { sectionRefs.current['actors'] = el }}>
        <h2 className="bl-section-title"><Users size={22} /> Key Actors &amp; Entities</h2>

        <div className="bl-controls">
          <div className="bl-filter-tabs">
            {[
              { value: undefined, label: 'All' },
              { value: 'person', label: 'People' },
              { value: 'organization', label: 'Organizations' },
              { value: 'company', label: 'Companies' },
            ].map((tab) => (
              <button
                key={tab.label}
                className={`bl-filter-tab ${entityType === tab.value ? 'active' : ''}`}
                onClick={() => setEntityType(tab.value)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="bl-sort-group">
            <label>Sort:</label>
            <select value={entitySort} onChange={(e) => setEntitySort(e.target.value)}>
              <option value="documents">Most Documents</option>
              <option value="recency">Most Recent</option>
            </select>
          </div>
          {entitiesData && (
            <span className="bl-total-label">{entitiesData.total} total</span>
          )}
        </div>

        <div className="bl-entities-grid">
          {allEntities.map((entity) => (
            <EntityCard key={entity.id} entity={entity} />
          ))}
        </div>

        {entitiesData && allEntities.length < entitiesData.total && (
          <button
            className="bl-show-more"
            onClick={() => setEntityOffset((prev) => prev + 20)}
          >
            Show More Entities
          </button>
        )}

        {allEntities.length === 0 && (
          <div className="bl-empty">No entities found for this bilateral pair.</div>
        )}
      </section>

      {/* ===== 6. MATERIAL IMPACT ANALYSIS ===== */}
      <section id="impact" ref={(el) => { sectionRefs.current['impact'] = el }}>
        <h2 className="bl-section-title"><Zap size={22} /> Material Impact Analysis</h2>

        {profile ? (
          <div className="bl-impact-content">
            {/* Score cards */}
            <div className="bl-impact-scores">
              <div className="bl-impact-card">
                <div className="bl-impact-value">
                  {profile.material_score_avg?.toFixed(2) ?? 'N/A'}
                </div>
                <div className="bl-impact-label">Average Score</div>
              </div>
              <div className="bl-impact-card">
                <div className="bl-impact-value">
                  {profile.material_score_median?.toFixed(2) ?? 'N/A'}
                </div>
                <div className="bl-impact-label">Median Score</div>
              </div>
              {profile.material_assessment && (
                <div className="bl-impact-card">
                  <div className="bl-impact-value">
                    {profile.material_assessment.score?.toFixed(2) ?? 'N/A'}
                  </div>
                  <div className="bl-impact-label">AI Assessment</div>
                </div>
              )}
            </div>

            {/* Material assessment justification */}
            {profile.material_assessment?.justification && (
              <div className="bl-profile-block">
                <h3>Material Assessment</h3>
                <p>{profile.material_assessment.justification}</p>
              </div>
            )}

            {/* Histogram */}
            {histogramData.length > 0 && (
              <div className="bl-chart-card">
                <h3>Material Score Distribution</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={histogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="score" label={{ value: 'Score', position: 'insideBottom', offset: -5 }} />
                    <YAxis label={{ value: 'Events', angle: -90, position: 'insideLeft' }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#f59e0b" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Category breakdown from profile */}
            {Object.keys(profile.count_by_category).length > 0 && (
              <div className="bl-chart-card">
                <h3>Documents by Category</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    data={Object.entries(profile.count_by_category)
                      .sort((a, b) => b[1] - a[1])
                      .map(([category, count]) => ({ category, count }))}
                    layout="vertical"
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis type="category" dataKey="category" width={100} tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="count">
                      {Object.entries(profile.count_by_category)
                        .sort((a, b) => b[1] - a[1])
                        .map(([cat], i) => (
                          <Cell key={i} fill={CATEGORY_COLORS[cat] || COLORS[i % COLORS.length]} />
                        ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        ) : (
          <div className="bl-empty">No material impact data available for this pair.</div>
        )}
      </section>

      {/* ===== 7. SOURCE INTELLIGENCE ===== */}
      <section id="sources" ref={(el) => { sectionRefs.current['sources'] = el }}>
        <h2 className="bl-section-title"><Newspaper size={22} /> Source Intelligence</h2>

        {sourcesData && sourcesData.sources.length > 0 ? (
          <>
            <div className="bl-source-kpi">
              <div className="bl-kpi-card">
                <div className="bl-kpi-value">{sourcesData.total_sources}</div>
                <div className="bl-kpi-label">Total Sources</div>
              </div>
              <div className="bl-kpi-card">
                <div className="bl-kpi-value">
                  {sourcesData.sources[0]?.source || 'N/A'}
                </div>
                <div className="bl-kpi-label">Top Source</div>
              </div>
              <div className="bl-kpi-card">
                <div className="bl-kpi-value">
                  {sourcesData.sources[0]?.count.toLocaleString() || 0}
                </div>
                <div className="bl-kpi-label">Top Source Docs</div>
              </div>
            </div>

            <div className="bl-chart-card">
              <h3>Top 15 Sources</h3>
              <ResponsiveContainer width="100%" height={Math.max(300, sourcesData.sources.slice(0, 15).length * 32)}>
                <BarChart data={sourcesData.sources.slice(0, 15)} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="source" width={160} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#2d4a7c" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Source table */}
            <div className="bl-source-table-wrap">
              <table className="bl-source-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Source</th>
                    <th>Documents</th>
                    <th>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {sourcesData.sources.slice(0, 30).map((s, i) => {
                    const totalDocs = sourcesData.sources.reduce((sum, x) => sum + x.count, 0)
                    return (
                      <tr key={s.source}>
                        <td>{i + 1}</td>
                        <td>{s.source}</td>
                        <td>{s.count.toLocaleString()}</td>
                        <td>{((s.count / totalDocs) * 100).toFixed(1)}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="bl-empty">No source data available.</div>
        )}
      </section>
    </div>
  )
}
