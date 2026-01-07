import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Users, FileText, TrendingUp } from 'lucide-react'
import './Pages.css'

interface BilateralSummary {
  filename: string
  recipient: string
  category?: string
  month: string
  month_name: string
  total_documents: number
}

export default function BilateralSummariesPage() {
  const [influencer, setInfluencer] = useState('China')
  const [month, setMonth] = useState<string>('')
  const [recipient, setRecipient] = useState<string>('')
  const [category, setCategory] = useState<string>('')

  // Get available months
  const { data: monthsData } = useQuery({
    queryKey: ['bilateral-months', influencer],
    queryFn: async () => {
      const response = await fetch(`/api/bilateral-summaries/available-months?influencer=${influencer}`)
      return response.json()
    },
  })

  // Get summaries list
  const { data, isLoading } = useQuery({
    queryKey: ['bilateral-summaries-list', influencer, month, recipient, category],
    queryFn: async () => {
      const params = new URLSearchParams({ influencer })
      if (month) params.append('month', month)
      if (recipient) params.append('recipient', recipient)
      if (category) params.append('category', category)

      const response = await fetch(`/api/bilateral-summaries/list?${params}`)
      return response.json()
    },
    enabled: !!influencer,
  })

  const summaries: BilateralSummary[] = data?.summaries || []

  // Get unique recipients from summaries for filter
  const uniqueRecipients = Array.from(new Set(summaries.map(s => s.recipient))).sort()

  const categories = ['Economic', 'Diplomacy', 'Social', 'Military']

  return (
    <div className="page">
      <header className="page-header">
        <h1>Bilateral Summaries</h1>
        <p>Category-specific bilateral relationship assessments</p>
      </header>

      <div className="filters">
        <div className="filter-group">
          <label>Influencer:</label>
          <select
            value={influencer}
            onChange={(e) => {
              setInfluencer(e.target.value)
              setMonth('')
              setRecipient('')
            }}
          >
            <option value="China">China</option>
            <option value="Russia">Russia</option>
            <option value="Iran">Iran</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Month:</label>
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          >
            <option value="">All Months</option>
            {monthsData?.months?.map((m: string) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Recipient:</label>
          <select
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
          >
            <option value="">All Recipients</option>
            {uniqueRecipients.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Category:</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All Categories</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="loading">Loading summaries...</div>
      ) : summaries.length === 0 ? (
        <div className="empty-state">
          <FileText size={48} />
          <h3>No Summaries Found</h3>
          <p>No bilateral summaries available for the selected filters</p>
        </div>
      ) : (
        <div className="summaries-grid">
          {summaries.map((summary) => (
            <Link
              key={summary.filename}
              to={`/bilateral-summaries/detail?influencer=${influencer}&filename=${encodeURIComponent(summary.filename)}`}
              className="summary-card"
            >
              <div className="summary-card-header">
                <div className="summary-icon">
                  {summary.category ? <TrendingUp size={24} /> : <Users size={24} />}
                </div>
                <div className="summary-meta">
                  <span className="summary-level">
                    {summary.category || 'All Categories'}
                  </span>
                  <span className="summary-docs">{summary.total_documents} docs</span>
                </div>
              </div>

              <div className="summary-card-body">
                <h3>{summary.recipient}</h3>
                <p className="summary-relationship">
                  {influencer} → {summary.recipient}
                </p>
                <p className="summary-date">{summary.month_name}</p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
