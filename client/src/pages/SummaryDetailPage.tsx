import { useQuery } from '@tanstack/react-query'
import { useSearchParams, Link } from 'react-router-dom'
import { ArrowLeft, Calendar, FileText, ExternalLink } from 'lucide-react'
import './Pages.css'

interface Citation {
  citation_number: number | string
  doc_id?: string
  headline?: string
  source_name?: string
  source_url?: string
  published_date?: string
  salience?: number
  categories?: string[]
  recipients?: string[]
  excerpt?: string
  date?: string
  summary_excerpt?: string
  total_documents?: number
  doc_ids?: string[]
  daily_citations?: any[]
  weekly_citations?: any[]
  monthly_citations?: any[]
  period_start?: string
  period_end?: string
  month_name?: string
  weeks_covered?: number
}

interface Metrics {
  total_documents: number
  categories?: Record<string, number>
  recipients?: Record<string, number>
  sources?: Record<string, number>
  days_with_activity?: number
  weeks_covered?: number
  months_covered?: number
  avg_salience?: number
}

interface SummaryDetail {
  date?: string
  period_start?: string
  period_end?: string
  influencer: string
  recipient?: string
  summary: string
  citations: Citation[]
  metrics: Metrics
  doc_ids?: string[]
  generated_at: string
}

export default function SummaryDetailPage() {
  const [searchParams] = useSearchParams()
  const influencer = searchParams.get('influencer') || ''
  const filename = searchParams.get('filename') || ''
  const recipient = searchParams.get('recipient') || undefined

  const { data, isLoading } = useQuery({
    queryKey: ['document-summary-detail', influencer, filename, recipient],
    queryFn: async () => {
      const params = new URLSearchParams({
        influencer,
        filename,
        ...(recipient && { recipient }),
      })
      const response = await fetch(`/api/document-summaries/detail?${params}`)
      return response.json()
    },
    enabled: !!influencer && !!filename,
  })

  const summary: SummaryDetail | null = data?.summary || null

  if (isLoading) {
    return <div className="loading">Loading summary...</div>
  }

  if (!summary) {
    return <div className="error">Summary not found</div>
  }

  const formatDate = (dateStr: string) => {
    if (!dateStr) return ''
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    })
  }

  // Determine summary level from filename or structure
  const getLevel = () => {
    if (filename.startsWith('overall_')) return 'Overall'
    if (filename.includes('_to_')) {
      return filename.split('_to_')[0].split('-').length === 3 ? 'Weekly' : 'Monthly'
    }
    return 'Daily'
  }

  const level = getLevel()

  return (
    <div className="page">
      <div className="page-header">
        <Link to="/document-summaries" className="back-button">
          <ArrowLeft size={20} />
          Back to Summaries
        </Link>

        <div className="summary-detail-header">
          <div className="summary-title">
            <h1>
              {summary.date && formatDate(summary.date)}
              {summary.period_start && summary.period_end && (
                `${formatDate(summary.period_start)} - ${formatDate(summary.period_end)}`
              )}
            </h1>
            <span className="summary-level-badge">{level} Summary</span>
          </div>

          <p className="summary-relationship">
            {summary.influencer}
            {summary.recipient ? ` → ${summary.recipient}` : ' (all recipients)'}
          </p>
        </div>
      </div>

      {/* Metrics Section */}
      <div className="metrics-grid">
        <div className="metric-card">
          <FileText size={24} />
          <div>
            <div className="metric-value">{summary.metrics.total_documents}</div>
            <div className="metric-label">Total Documents</div>
          </div>
        </div>

        {summary.metrics.days_with_activity && (
          <div className="metric-card">
            <Calendar size={24} />
            <div>
              <div className="metric-value">{summary.metrics.days_with_activity}</div>
              <div className="metric-label">Days with Activity</div>
            </div>
          </div>
        )}

        {summary.metrics.weeks_covered && (
          <div className="metric-card">
            <Calendar size={24} />
            <div>
              <div className="metric-value">{summary.metrics.weeks_covered}</div>
              <div className="metric-label">Weeks Covered</div>
            </div>
          </div>
        )}

        {summary.metrics.months_covered && (
          <div className="metric-card">
            <Calendar size={24} />
            <div>
              <div className="metric-value">{summary.metrics.months_covered}</div>
              <div className="metric-label">Months Covered</div>
            </div>
          </div>
        )}
      </div>

      {/* Summary Text */}
      <div className="summary-content">
        <h2>Summary</h2>
        <div className="summary-text">
          {summary.summary.split('\n').map((paragraph, idx) => (
            <p key={idx}>{paragraph}</p>
          ))}
        </div>
      </div>

      {/* Categories Breakdown */}
      {summary.metrics.categories && Object.keys(summary.metrics.categories).length > 0 && (
        <div className="breakdown-section">
          <h2>Category Breakdown</h2>
          <div className="breakdown-grid">
            {Object.entries(summary.metrics.categories)
              .sort(([, a], [, b]) => b - a)
              .map(([category, count]) => (
                <div key={category} className="breakdown-item">
                  <span className="breakdown-label">{category}</span>
                  <span className="breakdown-value">{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Recipients Breakdown */}
      {summary.metrics.recipients && Object.keys(summary.metrics.recipients).length > 0 && (
        <div className="breakdown-section">
          <h2>Recipient Countries</h2>
          <div className="breakdown-grid">
            {Object.entries(summary.metrics.recipients)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 10)
              .map(([recip, count]) => (
                <div key={recip} className="breakdown-item">
                  <span className="breakdown-label">{recip}</span>
                  <span className="breakdown-value">{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Citations Section */}
      <div className="citations-section">
        <h2>Citations ({summary.citations.length})</h2>
        <div className="citations-list">
          {summary.citations.map((citation, idx) => (
            <div key={idx} className="citation-card">
              <div className="citation-header">
                <span className="citation-number">[{citation.citation_number}]</span>

                {citation.doc_id && (
                  <div className="citation-meta">
                    <span>{citation.source_name}</span>
                    {citation.published_date && (
                      <span>{formatDate(citation.published_date)}</span>
                    )}
                    {citation.salience && (
                      <span className="salience-badge">Salience: {citation.salience}/100</span>
                    )}
                  </div>
                )}

                {citation.date && (
                  <span className="citation-date">{formatDate(citation.date)}</span>
                )}

                {citation.period_start && citation.period_end && (
                  <span className="citation-period">
                    {formatDate(citation.period_start)} - {formatDate(citation.period_end)}
                  </span>
                )}

                {citation.month_name && (
                  <span className="citation-month">{citation.month_name}</span>
                )}
              </div>

              <div className="citation-body">
                {citation.headline && <h4>{citation.headline}</h4>}

                {citation.summary_excerpt && (
                  <p className="citation-excerpt">{citation.summary_excerpt}</p>
                )}

                {citation.excerpt && (
                  <p className="citation-excerpt">{citation.excerpt}</p>
                )}

                {citation.categories && citation.categories.length > 0 && (
                  <div className="citation-tags">
                    {citation.categories.map((cat) => (
                      <span key={cat} className="tag">{cat}</span>
                    ))}
                  </div>
                )}

                {citation.recipients && citation.recipients.length > 0 && (
                  <div className="citation-recipients">
                    Recipients: {citation.recipients.join(', ')}
                  </div>
                )}

                {citation.total_documents && (
                  <div className="citation-doc-count">
                    {citation.total_documents} documents
                  </div>
                )}

                {citation.source_url && (
                  <a
                    href={citation.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="citation-link"
                  >
                    <ExternalLink size={16} />
                    View Source
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
