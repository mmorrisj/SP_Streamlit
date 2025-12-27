import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import './Pages.css'

interface Summary {
  id: number
  summary_type: string
  period_start: string
  period_end: string
  content: string
  country: string
}

export default function Summaries() {
  const [summaryType, setSummaryType] = useState('daily')

  const { data, isLoading } = useQuery({
    queryKey: ['summaries', summaryType],
    queryFn: async () => {
      const response = await fetch(`/api/summaries?type=${summaryType}`)
      return response.json()
    },
  })

  return (
    <div className="page">
      <header className="page-header">
        <h1>Summaries</h1>
        <p>Daily, weekly, and monthly analytical summaries</p>
      </header>

      <div className="filter-tabs">
        {['daily', 'weekly', 'monthly'].map((type) => (
          <button
            key={type}
            className={`tab ${summaryType === type ? 'active' : ''}`}
            onClick={() => setSummaryType(type)}
          >
            {type.charAt(0).toUpperCase() + type.slice(1)}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="loading">Loading summaries...</div>
      ) : (
        <div className="summaries-list">
          {data?.summaries?.length > 0 ? (
            data.summaries.map((summary: Summary) => (
              <div key={summary.id} className="summary-card">
                <div className="summary-header">
                  <FileText size={20} />
                  <span className="summary-period">
                    {summary.period_start} - {summary.period_end}
                  </span>
                  <span className="badge">{summary.country}</span>
                </div>
                <p className="summary-content">{summary.content}</p>
              </div>
            ))
          ) : (
            <div className="empty-state-card">
              <FileText size={48} />
              <h3>No Summaries Available</h3>
              <p>Summaries will appear here once they are generated.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
