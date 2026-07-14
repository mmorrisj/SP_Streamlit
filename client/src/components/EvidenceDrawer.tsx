import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { X, ExternalLink, ShieldCheck, Megaphone, CalendarDays, Newspaper } from 'lucide-react'
import { fetchIntelEvidence } from '../api/client'
import { ACTOR_COLORS } from './reportFigures/builders'
import './EvidenceDrawer.css'

interface EvidenceDrawerProps {
  name: string
  actor?: string
  onClose: () => void
}

/**
 * Slide-in evidence panel: traces a named initiative back to its canonical
 * event and the source documents behind it (event_source traceability chain).
 */
export default function EvidenceDrawer({ name, actor, onClose }: EvidenceDrawerProps) {
  const [thirdPartyOnly, setThirdPartyOnly] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['intel-evidence', name, actor],
    queryFn: () => fetchIntelEvidence(name, actor),
    staleTime: 5 * 60 * 1000,
  })

  const docs = (data?.documents ?? []).filter((d) => !thirdPartyOnly || !d.self_reported)
  const accent = (actor && ACTOR_COLORS[actor]) || '#1a365d'

  return (
    <div className="ev-overlay" onClick={onClose}>
      <aside className="ev-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="ev-header" style={{ borderTopColor: accent }}>
          <div className="ev-header-row">
            <span className="ev-actor" style={{ background: accent }}>
              {data?.initiating_country ?? actor ?? ''}
            </span>
            <button className="ev-close" onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
          </div>
          <h2>{data?.canonical_name ?? name}</h2>
          {data && (
            <div className="ev-meta">
              <span><CalendarDays size={13} /> {data.first_mention_date}
                {data.last_mention_date && data.last_mention_date !== data.first_mention_date
                  ? ` → ${data.last_mention_date}` : ''}</span>
              {data.material_score != null && (
                <span title={data.material_justification ?? undefined}>
                  material {data.material_score.toFixed(1)}/10
                </span>
              )}
            </div>
          )}
        </div>

        {isLoading && <div className="ev-loading">Tracing sources…</div>}
        {!!error && <div className="ev-loading">No matching event found in the corpus.</div>}

        {data && (
          <div className="ev-body">
            <div className="ev-stats">
              <div className="ev-stat">
                <span className="ev-stat-n">{data.total_docs.toLocaleString()}</span>
                <span className="ev-stat-l">documents</span>
              </div>
              <div className="ev-stat">
                <span className="ev-stat-n">{data.third_party_docs.toLocaleString()}</span>
                <span className="ev-stat-l">third-party</span>
              </div>
              <div className="ev-stat">
                <span className="ev-stat-n">{data.distinct_sources}</span>
                <span className="ev-stat-l">outlets</span>
              </div>
            </div>

            {data.top_recipients.length > 0 && (
              <div className="ev-recipients">
                {data.top_recipients.map((r) => <span key={r} className="ev-chip">{r}</span>)}
              </div>
            )}

            {data.description && <p className="ev-desc">{data.description}</p>}

            {data.sources.length > 0 && (
              <div className="ev-sources">
                <div className="ev-section-title"><Newspaper size={13} /> Top outlets</div>
                <div className="ev-source-list">
                  {data.sources.map((s) => (
                    <span key={s.source_name}
                      className={`ev-chip ${s.self_reported ? 'ev-chip-self' : ''}`}
                      title={s.self_reported ? "includes the initiator's own media" : 'independent outlet'}>
                      {s.source_name} · {s.docs}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="ev-doclist-header">
              <div className="ev-section-title">Source documents ({docs.length})</div>
              <label className="ev-filter">
                <input type="checkbox" checked={thirdPartyOnly}
                  onChange={(e) => setThirdPartyOnly(e.target.checked)} />
                third-party only
              </label>
            </div>

            <div className="ev-doclist">
              {docs.map((d) => (
                <div key={d.doc_id} className="ev-doc">
                  <div className="ev-doc-top">
                    <span className="ev-doc-source">
                      {d.self_reported
                        ? <Megaphone size={12} className="ev-ico-self" />
                        : <ShieldCheck size={12} className="ev-ico-third" />}
                      {d.source_name ?? 'unknown source'}
                    </span>
                    <span className="ev-doc-date">{d.date}</span>
                  </div>
                  {d.title && <div className="ev-doc-title">{d.title}</div>}
                  {d.snippet && <div className="ev-doc-snippet">{d.snippet}…</div>}
                </div>
              ))}
            </div>

            <Link to={`/events/${data.event_id}`} className="ev-event-link">
              <ExternalLink size={14} /> Open full event page
            </Link>
          </div>
        )}
      </aside>
    </div>
  )
}
