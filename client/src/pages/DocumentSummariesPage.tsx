import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FileText, Calendar, TrendingUp } from 'lucide-react'
import PageGuide from '../components/PageGuide'
import './Pages.css'

interface Summary {
  filename: string
  date?: string
  period_start?: string
  period_end?: string
  influencer: string
  recipient?: string
  total_documents: number
}

export default function DocumentSummariesPage() {
  const [influencer, setInfluencer] = useState('China')
  const [recipient, setRecipient] = useState<string>('')
  const [level, setLevel] = useState<'daily' | 'weekly' | 'monthly' | 'overall'>('daily')

  // Get available influencers
  const { data: influencersData } = useQuery({
    queryKey: ['available-summary-influencers'],
    queryFn: async () => {
      const response = await fetch('/api/document-summaries/available-influencers')
      return response.json()
    },
  })

  // Get available recipients for selected influencer
  const { data: recipientsData } = useQuery({
    queryKey: ['available-summary-recipients', influencer],
    queryFn: async () => {
      const response = await fetch(`/api/document-summaries/available-recipients?influencer=${influencer}`)
      return response.json()
    },
    enabled: !!influencer,
  })

  // Get summaries list
  const { data, isLoading } = useQuery({
    queryKey: ['document-summaries-list', influencer, recipient, level],
    queryFn: async () => {
      const params = new URLSearchParams({
        influencer,
        level,
        ...(recipient && { recipient }),
      })
      const response = await fetch(`/api/document-summaries/list?${params}`)
      return response.json()
    },
    enabled: !!influencer,
  })

  const summaries: Summary[] = data?.summaries || []

  const formatDate = (dateStr: string) => {
    if (!dateStr) return ''
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  const formatPeriod = (start: string, end: string) => {
    return `${formatDate(start)} - ${formatDate(end)}`
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Coverage Summaries</h1>
        <p>Hierarchical summaries with full source attribution</p>
      </header>

      <PageGuide page="document-summaries" />

      <div className="filters">
        <div className="filter-group">
          <label>Influencer:</label>
          <select
            value={influencer}
            onChange={(e) => setInfluencer(e.target.value)}
          >
            {influencersData?.influencers?.map((inf: string) => (
              <option key={inf} value={inf}>{inf}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Recipient (optional):</label>
          <select
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
          >
            <option value="">All Recipients</option>
            {recipientsData?.recipients?.map((rec: string) => (
              <option key={rec} value={rec}>{rec}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Level:</label>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value as any)}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="overall">Overall</option>
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="loading">Loading summaries...</div>
      ) : summaries.length === 0 ? (
        <div className="empty-state">
          <FileText size={48} />
          <h3>No Summaries Found</h3>
          <p>No {level} summaries available for {influencer} {recipient ? `→ ${recipient}` : '(all recipients)'}</p>
        </div>
      ) : (
        <div className="summaries-grid">
          {summaries.map((summary) => (
            <Link
              key={summary.filename}
              to={`/document-summaries/detail?influencer=${influencer}&filename=${encodeURIComponent(summary.filename)}${recipient ? `&recipient=${recipient}` : ''}`}
              className="summary-card"
            >
              <div className="summary-card-header">
                <div className="summary-icon">
                  {level === 'daily' && <Calendar size={24} />}
                  {level === 'weekly' && <TrendingUp size={24} />}
                  {level === 'monthly' && <TrendingUp size={24} />}
                  {level === 'overall' && <FileText size={24} />}
                </div>
                <div className="summary-meta">
                  <span className="summary-level">{level}</span>
                  <span className="summary-docs">{summary.total_documents} docs</span>
                </div>
              </div>

              <div className="summary-card-body">
                {summary.date && (
                  <h3>{formatDate(summary.date)}</h3>
                )}
                {summary.period_start && summary.period_end && (
                  <h3>{formatPeriod(summary.period_start, summary.period_end)}</h3>
                )}

                <p className="summary-relationship">
                  {summary.influencer} {summary.recipient ? `→ ${summary.recipient}` : '(all recipients)'}
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
