import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, Calendar, FileText, TrendingUp, ExternalLink,
  Clock, Tag, Globe, Zap, Newspaper
} from 'lucide-react'
import { fetchEventDetail } from '../api/client'
import type { EventDetail, EventDetailMention } from '../api/client'
import './Pages.css'

const PHASE_COLORS: Record<string, string> = {
  emerging: '#10b981',
  developing: '#3b82f6',
  peak: '#f59e0b',
  fading: '#94a3b8',
  dormant: '#d1d5db',
}

const INTENSITY_COLORS: Record<string, string> = {
  breaking: '#ef4444',
  developing: '#f59e0b',
  'follow-up': '#3b82f6',
  recap: '#94a3b8',
}

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

function MentionCard({ mention }: { mention: EventDetailMention }) {
  return (
    <div style={{
      padding: '1rem',
      borderLeft: `3px solid ${INTENSITY_COLORS[mention.news_intensity || ''] || '#d1d5db'}`,
      backgroundColor: '#fafafa',
      borderRadius: '0 6px 6px 0',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <Calendar size={14} style={{ color: '#64748b' }} />
        <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>{mention.date}</span>
        {mention.news_intensity && (
          <span style={{
            fontSize: '0.7rem', padding: '1px 6px', borderRadius: '3px',
            backgroundColor: INTENSITY_COLORS[mention.news_intensity] || '#94a3b8',
            color: 'white',
          }}>
            {mention.news_intensity}
          </span>
        )}
        {mention.mention_context && (
          <span style={{
            fontSize: '0.7rem', padding: '1px 6px', borderRadius: '3px',
            backgroundColor: '#e2e8f0', color: '#475569',
          }}>
            {mention.mention_context}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: '#64748b' }}>
          {mention.article_count} articles
        </span>
      </div>

      {mention.headline && (
        <p style={{ margin: '0 0 0.25rem', fontWeight: 500, fontSize: '0.9rem' }}>
          {mention.headline}
        </p>
      )}
      {mention.summary && (
        <p style={{ margin: 0, color: '#475569', fontSize: '0.85rem', lineHeight: 1.5 }}>
          {mention.summary}
        </p>
      )}
      {mention.source_names.length > 0 && (
        <div style={{ marginTop: '0.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
          {mention.source_names.slice(0, 5).map((src, i) => (
            <span key={i} style={{
              fontSize: '0.7rem', padding: '1px 6px', borderRadius: '3px',
              backgroundColor: '#eff6ff', color: '#1e40af',
            }}>
              {src}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function EventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>()
  const navigate = useNavigate()

  const { data: event, isLoading, error } = useQuery({
    queryKey: ['event-detail', eventId],
    queryFn: () => fetchEventDetail(eventId!),
    enabled: !!eventId,
  })

  if (isLoading) return <div className="page"><div className="loading">Loading event...</div></div>
  if (error || !event) return (
    <div className="page">
      <button onClick={() => navigate(-1)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#3b82f6', display: 'flex', alignItems: 'center', gap: 4, marginBottom: '1rem' }}>
        <ArrowLeft size={16} /> Back
      </button>
      <div className="empty-state-card">
        <h3>Event Not Found</h3>
        <p>This event may have been removed or consolidated.</p>
      </div>
    </div>
  )

  const topCategories = Object.entries(event.primary_categories || {})
    .sort(([, a], [, b]) => b - a)
  const topRecipients = Object.entries(event.primary_recipients || {})
    .sort(([, a], [, b]) => b - a)

  return (
    <div className="page" style={{ maxWidth: '900px' }}>
      {/* Back navigation */}
      <button
        onClick={() => navigate(-1)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#3b82f6', display: 'flex', alignItems: 'center', gap: 4,
          marginBottom: '1.5rem', fontSize: '0.9rem', padding: 0,
        }}
      >
        <ArrowLeft size={16} /> Back
      </button>

      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', marginBottom: '0.75rem' }}>
          <h1 style={{ margin: 0, fontSize: '1.5rem', lineHeight: 1.3, flex: 1 }}>
            {event.event_name}
          </h1>
          {event.story_phase && (
            <span style={{
              padding: '4px 12px', borderRadius: '4px', fontSize: '0.8rem',
              backgroundColor: PHASE_COLORS[event.story_phase] || '#94a3b8',
              color: 'white', whiteSpace: 'nowrap',
            }}>
              {event.story_phase}
            </span>
          )}
        </div>
        <p style={{ color: '#64748b', margin: 0, fontSize: '0.9rem' }}>
          {event.initiating_country}
        </p>
      </div>

      {/* Metrics row */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
        gap: '1rem', marginBottom: '1.5rem',
      }}>
        {[
          { icon: <FileText size={16} />, value: event.total_articles, label: 'Articles' },
          { icon: <Clock size={16} />, value: event.total_mention_days, label: 'Days Tracked' },
          { icon: <Zap size={16} />, value: event.material_score?.toFixed(1) || 'N/A', label: 'Materiality' },
          { icon: <Newspaper size={16} />, value: event.source_count || 0, label: 'Sources' },
          { icon: <TrendingUp size={16} />, value: event.peak_daily_article_count, label: 'Peak Day' },
        ].map((m, i) => (
          <div key={i} style={{
            padding: '1rem', backgroundColor: '#f8fafc', borderRadius: '8px',
            textAlign: 'center',
          }}>
            <div style={{ color: '#64748b', marginBottom: '0.25rem' }}>{m.icon}</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{m.value}</div>
            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* Date range */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        padding: '0.75rem 1rem', backgroundColor: '#f1f5f9', borderRadius: '6px',
        marginBottom: '1.5rem', fontSize: '0.9rem',
      }}>
        <Calendar size={16} style={{ color: '#64748b' }} />
        <span>{event.first_mention_date} — {event.last_mention_date}</span>
        {event.peak_mention_date && (
          <span style={{ color: '#64748b' }}>(peak: {event.peak_mention_date})</span>
        )}
        {event.source_link && (
          <a
            href={event.source_link}
            target="_blank"
            rel="noopener noreferrer"
            style={{ marginLeft: 'auto', color: '#3b82f6', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}
          >
            <ExternalLink size={14} /> View All Sources
          </a>
        )}
      </div>

      {/* Narrative */}
      {event.narrative_overview && (
        <div style={{ marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Overview</h2>
          <p style={{ color: '#334155', lineHeight: 1.7, margin: 0 }}>
            {event.narrative_overview}
          </p>
        </div>
      )}

      {event.narrative_outcomes && (
        <div style={{
          marginBottom: '1.5rem', padding: '1rem',
          backgroundColor: '#f0fdf4', borderRadius: '6px', borderLeft: '3px solid #22c55e',
        }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '0.5rem', color: '#166534' }}>Outcomes</h2>
          <p style={{ color: '#334155', lineHeight: 1.7, margin: 0 }}>
            {event.narrative_outcomes}
          </p>
        </div>
      )}

      {/* Materiality justification */}
      {event.material_justification && (
        <div style={{
          marginBottom: '1.5rem', padding: '1rem',
          backgroundColor: '#fffbeb', borderRadius: '6px', borderLeft: '3px solid #f59e0b',
        }}>
          <h3 style={{ fontSize: '0.95rem', marginBottom: '0.5rem', color: '#92400e' }}>
            Materiality Assessment ({event.material_score?.toFixed(1)})
          </h3>
          <p style={{ color: '#78350f', lineHeight: 1.6, margin: 0, fontSize: '0.9rem' }}>
            {event.material_justification}
          </p>
        </div>
      )}

      {/* Categories and Recipients */}
      {(topCategories.length > 0 || topRecipients.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
          {topCategories.length > 0 && (
            <div>
              <h3 style={{ fontSize: '0.95rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: 4 }}>
                <Tag size={14} /> Categories
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {topCategories.map(([cat, count]) => (
                  <div key={cat} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0.5rem', borderRadius: '4px', backgroundColor: '#f8fafc' }}>
                    <span style={{ color: CATEGORY_COLORS[cat] || '#475569', fontWeight: 500, fontSize: '0.85rem' }}>{cat}</span>
                    <span style={{ color: '#64748b', fontSize: '0.85rem' }}>{count} docs</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {topRecipients.length > 0 && (
            <div>
              <h3 style={{ fontSize: '0.95rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: 4 }}>
                <Globe size={14} /> Recipients
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {topRecipients.map(([rec, count]) => (
                  <div key={rec} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0.5rem', borderRadius: '4px', backgroundColor: '#f8fafc' }}>
                    <span style={{ fontWeight: 500, fontSize: '0.85rem' }}>{rec}</span>
                    <span style={{ color: '#64748b', fontSize: '0.85rem' }}>{count} docs</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Citations */}
      {event.citations && event.citations.length > 0 && (
        <div style={{ marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Citations</h2>
          <ul style={{ margin: 0, paddingLeft: '1.25rem', color: '#475569', lineHeight: 1.7, fontSize: '0.85rem' }}>
            {event.citations.map((cite, i) => (
              <li key={i}>{cite}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Alternative names */}
      {event.alternative_names && event.alternative_names.length > 0 && (
        <div style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '0.95rem', marginBottom: '0.5rem', color: '#64748b' }}>Also known as</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem' }}>
            {event.alternative_names.map((name, i) => (
              <span key={i} style={{
                fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px',
                backgroundColor: '#f1f5f9', color: '#475569',
              }}>
                {name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Daily mentions timeline */}
      {event.daily_mentions && event.daily_mentions.length > 0 && (
        <div>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '0.75rem' }}>
            Daily Coverage ({event.daily_mentions.length} days)
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {event.daily_mentions.map((mention, i) => (
              <MentionCard key={i} mention={mention} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
