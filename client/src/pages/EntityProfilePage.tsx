import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts'
import {
  ArrowLeft, FileText, Calendar, Globe, Zap, Users, Loader2,
  ChevronDown, ChevronUp, ExternalLink, Sparkles,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { fetchEntityProfile } from '../api/client'
import type { EntityRelationshipData, AssociatedEventData } from '../api/client'
import PageGuide from '../components/PageGuide'
import './EntityProfilePage.css'

interface AssessmentSource {
  citation_number: number
  doc_id: string | null
  content: string
  title: string | null
  source_name: string | null
  date: string | null
  initiating_country: string | null
  recipient_country: string | null
  category: string | null
  relevance_score: number
}

const TYPE_LABELS: Record<string, string> = {
  PERSON: 'Person',
  ORGANIZATION: 'Organization',
  COMPANY: 'Company',
  LOCATION: 'Location',
  OTHER: 'Other',
}

const ROLE_LABELS: Record<string, string> = {
  GOVERNMENT_OFFICIAL: 'Government Official',
  DIPLOMAT: 'Diplomat',
  BUSINESS_LEADER: 'Business Leader',
  CULTURAL_FIGURE: 'Cultural Figure',
  MILITARY_OFFICIAL: 'Military Official',
  ACADEMIC: 'Academic',
  MEDIA_FIGURE: 'Media Figure',
  CIVIL_SOCIETY: 'Civil Society',
  IMPLEMENTING_ORGANIZATION: 'Implementing Org',
  FUNDING_ORGANIZATION: 'Funding Org',
  RECIPIENT_INSTITUTION: 'Recipient Institution',
  INFRASTRUCTURE_PROJECT: 'Infrastructure Project',
  VENUE: 'Venue',
  OTHER: 'Other',
}

export default function EntityProfilePage() {
  const { entityId } = useParams<{ entityId: string }>()
  const navigate = useNavigate()

  // Assessment state
  const [assessmentContent, setAssessmentContent] = useState('')
  const [assessmentSources, setAssessmentSources] = useState<AssessmentSource[]>([])
  const [assessmentLoading, setAssessmentLoading] = useState(false)
  const [assessmentGenerated, setAssessmentGenerated] = useState(false)
  const [sourcesExpanded, setSourcesExpanded] = useState(false)

  const { data: entity, isLoading } = useQuery({
    queryKey: ['entity-profile', entityId],
    queryFn: () => fetchEntityProfile(entityId!),
    enabled: !!entityId,
    staleTime: 5 * 60 * 1000,
  })

  const generateAssessment = useCallback(async () => {
    if (!entityId || assessmentLoading) return

    setAssessmentLoading(true)
    setAssessmentContent('')
    setAssessmentSources([])
    setAssessmentGenerated(true)

    const token = localStorage.getItem('token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

    try {
      const response = await fetch(`/api/entity/${entityId}/assessment`, {
        method: 'POST',
        headers,
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'sources') {
              setAssessmentSources(event.sources || [])
            } else if (event.type === 'content') {
              setAssessmentContent(prev => prev + event.content)
            }
          } catch { /* skip */ }
        }
      }
    } catch (err) {
      setAssessmentContent(prev => prev + `\n\n[Error: ${err}]`)
    } finally {
      setAssessmentLoading(false)
    }
  }, [entityId, assessmentLoading])

  if (isLoading) {
    return <div className="entity-profile-page"><div className="loading-state"><Loader2 className="spin" size={24} /> Loading entity profile...</div></div>
  }

  if (!entity) {
    return <div className="entity-profile-page"><div className="empty-state">Entity not found</div></div>
  }

  // Prepare chart data
  const categoryData = Object.entries(entity.primary_categories)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({ name, value }))

  const recipientData = Object.entries(entity.primary_recipients)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, value]) => ({ name, value }))

  const topCategory = categoryData[0]?.name || null
  const topRecipient = recipientData[0]?.name || null

  return (
    <div className="entity-profile-page">
      {/* Back button */}
      <button className="back-btn" onClick={() => navigate(-1)}>
        <ArrowLeft size={16} /> Back
      </button>

      {/* Section 1: Header */}
      <div className="entity-header-card">
        <div className="entity-header-top">
          <div className="entity-badges">
            {entity.entity_type && (
              <span className={`type-badge type-${entity.entity_type.toLowerCase()}`}>
                {TYPE_LABELS[entity.entity_type] || entity.entity_type}
              </span>
            )}
            {entity.primary_role && (
              <span className="role-badge">
                {ROLE_LABELS[entity.primary_role] || entity.primary_role}
              </span>
            )}
          </div>
          <h1>{entity.canonical_name}</h1>
          {entity.alternative_names.length > 0 && (
            <p className="alt-names">Also known as: {entity.alternative_names.join(', ')}</p>
          )}
        </div>

        {entity.entity_description && (
          <p className="entity-desc">{entity.entity_description}</p>
        )}

      <PageGuide page="entity-profile" />

        <div className="kpi-grid">
          <div className="kpi-card">
            <FileText size={16} />
            <div className="kpi-value">{entity.total_documents.toLocaleString()}</div>
            <div className="kpi-label">Documents</div>
          </div>
          <div className="kpi-card">
            <Calendar size={16} />
            <div className="kpi-value">{entity.total_mention_days}</div>
            <div className="kpi-label">Active Days</div>
          </div>
          <div className="kpi-card">
            <Globe size={16} />
            <div className="kpi-value">{entity.initiating_country}</div>
            <div className="kpi-label">Primary Country</div>
          </div>
          {topCategory && (
            <div className="kpi-card">
              <Zap size={16} />
              <div className="kpi-value">{topCategory}</div>
              <div className="kpi-label">Top Category</div>
            </div>
          )}
          {topRecipient && (
            <div className="kpi-card">
              <Users size={16} />
              <div className="kpi-value">{topRecipient}</div>
              <div className="kpi-label">Top Recipient</div>
            </div>
          )}
        </div>

        <div className="date-range">
          {entity.first_mention_date} — {entity.last_mention_date}
        </div>
      </div>

      {/* Section 2: Category & Recipient Charts */}
      <div className="charts-row">
        {categoryData.length > 0 && (
          <div className="chart-card">
            <h3>Category Breakdown</h3>
            <ResponsiveContainer width="100%" height={Math.max(120, categoryData.length * 40)}>
              <BarChart data={categoryData} layout="vertical" margin={{ left: 80 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={75} />
                <Tooltip />
                <Bar dataKey="value" name="Documents" fill="#1a365d" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {recipientData.length > 0 && (
          <div className="chart-card">
            <h3>Top Recipients</h3>
            <ResponsiveContainer width="100%" height={Math.max(120, recipientData.length * 40)}>
              <BarChart data={recipientData} layout="vertical" margin={{ left: 100 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={95} />
                <Tooltip />
                <Bar dataKey="value" name="Mentions" fill="#059669" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Section 3: Activity Timeline */}
      {entity.monthly_activity.length > 0 && (
        <div className="section-card">
          <h3>Activity Timeline</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={entity.monthly_activity}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="month"
                tickFormatter={(v: string) => {
                  if (!v) return ''
                  const d = new Date(v)
                  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
                }}
                tick={{ fontSize: 11 }}
              />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                labelFormatter={(v: string) =>
                  v ? new Date(v).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) : ''
                }
              />
              <Line type="monotone" dataKey="count" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} name="Documents" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Section 4: Connections */}
      {entity.relationships.length > 0 && (
        <div className="section-card">
          <h3>Connections ({entity.relationships.length})</h3>
          <div className="connections-list">
            {entity.relationships.map((rel: EntityRelationshipData, idx: number) => (
              <div
                key={idx}
                className="connection-card"
                onClick={() => navigate(`/entity/${rel.related_entity_id}`)}
              >
                <div className="connection-header">
                  <span className={`type-dot type-${(rel.related_entity_type || '').toLowerCase()}`} />
                  <span className="connection-name">{rel.related_entity_name}</span>
                  <span className="connection-type">{rel.relationship_type.replace(/_/g, ' ')}</span>
                </div>
                <div className="connection-meta">
                  <span>{rel.co_occurrence_count} co-occurrences</span>
                  {rel.first_co_occurrence && rel.last_co_occurrence && (
                    <span>{rel.first_co_occurrence} — {rel.last_co_occurrence}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Section 5: Associated Events */}
      {entity.associated_events.length > 0 && (
        <div className="section-card">
          <h3>Associated Events ({entity.associated_events.length})</h3>
          <div className="events-list">
            {entity.associated_events.map((ev: AssociatedEventData) => (
              <div
                key={ev.id}
                className="event-row"
                onClick={() => navigate(`/events/${ev.id}`)}
              >
                <span className="event-row-name">{ev.event_name}</span>
                <div className="event-row-meta">
                  {ev.date && <span>{ev.date}</span>}
                  {ev.material_score != null && (
                    <span className="mat-score">{ev.material_score.toFixed(1)}</span>
                  )}
                  {ev.story_phase && (
                    <span className={`phase-badge phase-${ev.story_phase}`}>{ev.story_phase}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Section 6: RAG Assessment */}
      <div className="section-card assessment-section">
        <div className="assessment-header">
          <h3><Sparkles size={16} /> Intelligence Assessment</h3>
          {!assessmentGenerated && (
            <button className="generate-btn" onClick={generateAssessment} disabled={assessmentLoading}>
              {assessmentLoading ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
              Generate Assessment
            </button>
          )}
          {assessmentGenerated && !assessmentLoading && (
            <button className="regen-btn" onClick={generateAssessment}>Regenerate</button>
          )}
        </div>

        {!assessmentGenerated && !assessmentLoading && (
          <p className="assessment-placeholder">
            Click "Generate Assessment" to produce a RAG-powered analysis of this entity's influence, with source citations.
          </p>
        )}

        {(assessmentContent || assessmentLoading) && (
          <div className="assessment-content">
            {assessmentContent ? (
              <ReactMarkdown>{assessmentContent}</ReactMarkdown>
            ) : (
              <div className="assessment-loading">
                <Loader2 size={20} className="spin" />
                <span>Analyzing sources...</span>
              </div>
            )}
            {assessmentLoading && assessmentContent && (
              <Loader2 size={16} className="spin" style={{ display: 'inline-block', marginLeft: 4 }} />
            )}
          </div>
        )}

        {assessmentSources.length > 0 && !assessmentLoading && (
          <div className="assessment-sources">
            <button className="sources-toggle-btn" onClick={() => setSourcesExpanded(!sourcesExpanded)}>
              {sourcesExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              {assessmentSources.length} Sources
            </button>
            {sourcesExpanded && (
              <div className="assessment-sources-list">
                {assessmentSources.map((src, idx) => (
                  <div key={idx} className="src-card">
                    <div className="src-card-header">
                      <span className="src-num">[{src.citation_number}]</span>
                      <span className="src-ttl">{src.title || 'Untitled'}</span>
                      <span className="src-scr">{(src.relevance_score * 100).toFixed(0)}%</span>
                    </div>
                    <div className="src-meta">
                      {src.source_name && <span>{src.source_name}</span>}
                      {src.date && <span>{src.date}</span>}
                      {src.category && <span className="src-cat">{src.category}</span>}
                    </div>
                    {src.content && (
                      <p className="src-excerpt">{src.content.slice(0, 250)}{src.content.length > 250 ? '...' : ''}</p>
                    )}
                    {src.doc_id && (
                      <a href={`/documents?doc_id=${src.doc_id}`} className="src-link">
                        <ExternalLink size={12} /> View Document
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
