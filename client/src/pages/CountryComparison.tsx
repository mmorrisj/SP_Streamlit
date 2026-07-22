import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Globe, Zap, Tag, Calendar, ChevronDown } from 'lucide-react'
import { fetchEventComparison } from '../api/client'
import type { EventComparison } from '../api/client'
import PageGuide from '../components/PageGuide'
import './Pages.css'

const CATEGORY_COLORS: Record<string, string> = {
  Economic: '#10b981',
  Diplomacy: '#06b6d4',
  Military: '#ef4444',
  Social: '#8b5cf6',
}

const COUNTRY_COLORS: Record<string, string> = {
  China: '#e74c3c',
  Russia: '#3498db',
  Iran: '#f39c12',
  Turkey: '#9b59b6',
  'United States': '#2ecc71',
}

function ComparisonCard({ comp }: { comp: EventComparison }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="comp-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
        <h3 style={{ margin: 0, fontSize: '1rem', lineHeight: 1.35, flex: 1 }}>{comp.event_name}</h3>
        <div style={{ display: 'flex', gap: '0.25rem', flexShrink: 0, marginLeft: '0.75rem' }}>
          {comp.avg_materiality != null && (
            <span style={{
              fontSize: '0.72rem', padding: '2px 7px', borderRadius: '4px',
              backgroundColor: comp.avg_materiality >= 3 ? '#dcfce7' : '#f1f5f9',
              color: comp.avg_materiality >= 3 ? '#166534' : '#475569',
            }}>
              <Zap size={10} style={{ marginRight: 2 }} />{comp.avg_materiality.toFixed(1)}
            </span>
          )}
        </div>
      </div>

      {/* Country pills */}
      <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
        {comp.countries.map(c => (
          <span key={c} style={{
            fontSize: '0.72rem', padding: '2px 8px', borderRadius: '4px',
            backgroundColor: `${COUNTRY_COLORS[c] || '#94a3b8'}20`,
            color: COUNTRY_COLORS[c] || '#475569',
            fontWeight: 500,
          }}>
            {c}
          </span>
        ))}
        {comp.latest_date && (
          <span style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 2 }}>
            <Calendar size={10} /> {comp.latest_date}
          </span>
        )}
      </div>

      {/* Country narratives */}
      {expanded && Object.entries(comp.country_narratives || {}).map(([country, narr]) => (
        <div key={country} style={{
          margin: '0.5rem 0', padding: '0.75rem', borderRadius: '6px',
          backgroundColor: '#f8fafc',
          borderLeft: `3px solid ${COUNTRY_COLORS[country] || '#94a3b8'}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <Globe size={13} style={{ color: COUNTRY_COLORS[country] || '#64748b' }} />
            <strong style={{ fontSize: '0.85rem', color: COUNTRY_COLORS[country] || '#1e293b' }}>{country}</strong>
            {narr.material_score != null && (
              <span style={{ fontSize: '0.68rem', padding: '1px 5px', borderRadius: '3px', backgroundColor: '#f1f5f9', color: '#475569' }}>
                {narr.material_score.toFixed(1)}
              </span>
            )}
            {narr.period_start && (
              <span style={{ fontSize: '0.72rem', color: '#94a3b8', marginLeft: 'auto' }}>{narr.period_start}</span>
            )}
          </div>
          {narr.overview && (
            <p style={{ margin: '0 0 0.25rem', fontSize: '0.85rem', color: '#334155', lineHeight: 1.55 }}>
              {narr.overview}
            </p>
          )}
          {narr.outcomes && (
            <p style={{ margin: 0, fontSize: '0.82rem', color: '#64748b', lineHeight: 1.5, fontStyle: 'italic' }}>
              Outcomes: {narr.outcomes}
            </p>
          )}
          {Object.keys(narr.count_by_category || {}).length > 0 && (
            <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', marginTop: '0.375rem' }}>
              {Object.entries(narr.count_by_category).sort(([,a],[,b]) => b - a).slice(0, 3).map(([cat, count]) => (
                <span key={cat} style={{
                  fontSize: '0.65rem', padding: '1px 5px', borderRadius: '3px',
                  backgroundColor: `${CATEGORY_COLORS[cat] || '#94a3b8'}18`,
                  color: CATEGORY_COLORS[cat] || '#475569',
                }}>
                  <Tag size={8} style={{ marginRight: 2 }} />{cat} ({count})
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer',
          fontSize: '0.82rem', padding: '0.25rem 0', display: 'flex', alignItems: 'center', gap: 4,
        }}
      >
        {expanded ? 'Hide Perspectives' : `Compare ${comp.country_count} Country Perspectives`}
        <ChevronDown size={14} style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>
    </div>
  )
}

export default function CountryComparison() {
  const [limit, setLimit] = useState(20)

  const { data, isLoading } = useQuery({
    queryKey: ['country-comparison', limit],
    queryFn: () => fetchEventComparison(limit),
  })

  const comparisons = data?.comparisons || []

  return (
    <div className="page">
      <header className="page-header">
        <h1>
          <Globe size={28} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          Country Comparison
        </h1>
        <p>Events tracked by multiple countries with comparative perspectives</p>
      </header>

      <PageGuide page="country-comparison" />

      {isLoading ? (
        <div className="loading">Loading comparisons...</div>
      ) : comparisons.length > 0 ? (
        <>
          <div className="ev-list">
            {comparisons.map((comp, i) => (
              <ComparisonCard key={i} comp={comp} />
            ))}
          </div>
          {comparisons.length >= limit && (
            <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
              <button
                className="ev-show-more"
                onClick={() => setLimit(prev => prev + 20)}
              >
                Show More <ChevronDown size={16} style={{ verticalAlign: 'middle' }} />
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state-card">
          <Globe size={48} />
          <h3>No Multi-Country Events</h3>
          <p>No events tracked by more than one country were found.</p>
        </div>
      )}
    </div>
  )
}
