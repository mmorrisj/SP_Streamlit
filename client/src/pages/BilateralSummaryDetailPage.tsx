import { useQuery } from '@tanstack/react-query'
import { useSearchParams, Link } from 'react-router-dom'
import { ArrowLeft, Calendar, FileText, ExternalLink, Users } from 'lucide-react'
import PageGuide from '../components/PageGuide'
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
}

interface Metrics {
  total_documents: number
  categories?: Record<string, number>
  sources?: Record<string, number>
}

interface BilateralSummaryDetail {
  period_start: string
  period_end: string
  month_name: string
  influencer: string
  recipient: string
  category?: string
  summary: string
  citations: Citation[]
  metrics: Metrics
  generation_approach?: string
  generated_at: string
}

export default function BilateralSummaryDetailPage() {
  const [searchParams] = useSearchParams()
  const influencer = searchParams.get('influencer') || ''
  const filename = searchParams.get('filename') || ''

  const { data, isLoading } = useQuery({
    queryKey: ['bilateral-summary-detail', influencer, filename],
    queryFn: async () => {
      const params = new URLSearchParams({ influencer, filename })
      const response = await fetch(`/api/bilateral-summaries/detail?${params}`)
      return response.json()
    },
    enabled: !!influencer && !!filename,
  })

  const summary: BilateralSummaryDetail | null = data?.summary || null

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

  return (
    <div className="page">
      <div className="page-header">
        <Link to="/bilateral-summaries" className="back-button">
          <ArrowLeft size={20} />
          Back to Bilateral Summaries
        </Link>

        <div className="summary-detail-header">
          <div className="summary-title">
            <h1>{summary.month_name}</h1>
            <span className="summary-level-badge">
              {summary.category || 'All Categories'}
            </span>
          </div>

          <p className="summary-relationship">
            <Users size={20} />
            {summary.influencer} → {summary.recipient}
          </p>
        </div>
      </div>

      <PageGuide page="bilateral-summary-detail" />

      {/* Metrics Section */}
      <div className="metrics-grid">
        <div className="metric-card">
          <FileText size={24} />
          <div>
            <div className="metric-value">{summary.metrics.total_documents}</div>
            <div className="metric-label">Total Documents</div>
          </div>
        </div>

        {summary.generation_approach && (
          <div className="metric-card">
            <Calendar size={24} />
            <div>
              <div className="metric-value">{summary.generation_approach}</div>
              <div className="metric-label">Generation Method</div>
            </div>
          </div>
        )}
      </div>

      {/* Summary Text */}
      <div className="summary-content">
        <h2>Summary</h2>
        <div className="summary-text">
          {summary.summary.split('\n\n').filter(p => p.trim()).map((paragraph, idx) => (
            <p key={idx}>{paragraph.trim()}</p>
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

      {/* Sources Breakdown */}
      {summary.metrics.sources && Object.keys(summary.metrics.sources).length > 0 && (
        <div className="breakdown-section">
          <h2>Top Sources</h2>
          <div className="breakdown-grid">
            {Object.entries(summary.metrics.sources)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 10)
              .map(([source, count]) => (
                <div key={source} className="breakdown-item">
                  <span className="breakdown-label">{source}</span>
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
              </div>

              <div className="citation-body">
                {citation.headline && <h4>{citation.headline}</h4>}

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
