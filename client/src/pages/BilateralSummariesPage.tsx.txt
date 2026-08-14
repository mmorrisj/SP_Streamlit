import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FileText, ExternalLink } from 'lucide-react'
import PageGuide from '../components/PageGuide'
import './Pages.css'

interface BilateralSummary {
  filename: string
  recipient: string
  category?: string
  month: string
  month_name: string
  total_documents: number
}

interface RecipientRow {
  recipient: string
  month_name: string
  combined?: BilateralSummary
  Economic?: BilateralSummary
  Diplomacy?: BilateralSummary
  Social?: BilateralSummary
  Military?: BilateralSummary
}

export default function BilateralSummariesPage() {
  const [influencer, setInfluencer] = useState('China')
  const [month, setMonth] = useState<string>('')
  const [recipient, setRecipient] = useState<string>('')

  // Get available months
  const { data: monthsData } = useQuery({
    queryKey: ['bilateral-months', influencer],
    queryFn: async () => {
      const response = await fetch(`/api/bilateral-summaries/available-months?influencer=${influencer}`)
      return response.json()
    },
  })

  // Get summaries list - don't filter by category on API side, we'll organize it client-side
  const { data, isLoading } = useQuery({
    queryKey: ['bilateral-summaries-list', influencer, month, recipient],
    queryFn: async () => {
      const params = new URLSearchParams({ influencer })
      if (month) params.append('month', month)
      if (recipient) params.append('recipient', recipient)

      const response = await fetch(`/api/bilateral-summaries/list?${params}`)
      return response.json()
    },
    enabled: !!influencer,
  })

  const summaries: BilateralSummary[] = data?.summaries || []

  // Get unique recipients from ALL summaries (before filtering)
  const { data: allData } = useQuery({
    queryKey: ['bilateral-summaries-all', influencer],
    queryFn: async () => {
      const response = await fetch(`/api/bilateral-summaries/list?influencer=${influencer}`)
      return response.json()
    },
    enabled: !!influencer,
  })

  const uniqueRecipients = useMemo((): string[] => {
    const allSummaries: BilateralSummary[] = allData?.summaries || []
    return Array.from(new Set(allSummaries.map((s) => s.recipient))).sort()
  }, [allData])

  // Group summaries by recipient
  const recipientRows = useMemo(() => {
    const grouped = new Map<string, RecipientRow>()

    summaries.forEach(summary => {
      const key = summary.recipient
      if (!grouped.has(key)) {
        grouped.set(key, {
          recipient: summary.recipient,
          month_name: summary.month_name
        })
      }

      const row = grouped.get(key)!
      if (summary.category) {
        row[summary.category as 'Economic' | 'Diplomacy' | 'Social' | 'Military'] = summary
      } else {
        row.combined = summary
      }
    })

    return Array.from(grouped.values()).sort((a, b) => a.recipient.localeCompare(b.recipient))
  }, [summaries])

  const renderSummaryCell = (summary?: BilateralSummary) => {
    if (!summary) {
      return <td style={{ textAlign: 'center', color: '#94a3b8' }}>—</td>
    }

    return (
      <td style={{ textAlign: 'center' }}>
        <Link
          to={`/bilateral-summaries/detail?influencer=${influencer}&filename=${encodeURIComponent(summary.filename)}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
            padding: '0.25rem 0.5rem',
            borderRadius: '4px',
            background: '#f1f5f9',
            color: '#1e293b',
            textDecoration: 'none',
            fontSize: '0.875rem',
            fontWeight: '500',
            transition: 'all 0.2s'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = '#e2e8f0'
            e.currentTarget.style.color = '#0f172a'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = '#f1f5f9'
            e.currentTarget.style.color = '#1e293b'
          }}
        >
          {summary.total_documents}
          <ExternalLink size={12} />
        </Link>
      </td>
    )
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Bilateral Summaries</h1>
        <p>Category-specific bilateral relationship assessments</p>
      </header>

      <PageGuide page="bilateral-summaries" />

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
            {uniqueRecipients.map((r: string) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="loading">Loading summaries...</div>
      ) : recipientRows.length === 0 ? (
        <div className="empty-state">
          <FileText size={48} />
          <h3>No Summaries Found</h3>
          <p>No bilateral summaries available for the selected filters</p>
        </div>
      ) : (
        <div style={{ marginTop: '2rem', overflowX: 'auto' }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            background: 'white',
            borderRadius: '8px',
            overflow: 'hidden',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
          }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                <th style={{ padding: '1rem', textAlign: 'left', fontWeight: '600', color: '#475569' }}>
                  Recipient
                </th>
                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: '600', color: '#475569' }}>
                  Combined
                </th>
                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: '600', color: '#475569' }}>
                  Economic
                </th>
                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: '600', color: '#475569' }}>
                  Diplomacy
                </th>
                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: '600', color: '#475569' }}>
                  Social
                </th>
                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: '600', color: '#475569' }}>
                  Military
                </th>
              </tr>
            </thead>
            <tbody>
              {recipientRows.map((row) => (
                <tr key={row.recipient} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '1rem', fontWeight: '500', color: '#1e293b' }}>
                    {row.recipient}
                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.25rem' }}>
                      {row.month_name}
                    </div>
                  </td>
                  {renderSummaryCell(row.combined)}
                  {renderSummaryCell(row.Economic)}
                  {renderSummaryCell(row.Diplomacy)}
                  {renderSummaryCell(row.Social)}
                  {renderSummaryCell(row.Military)}
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{
            marginTop: '1rem',
            padding: '0.75rem',
            background: '#f8fafc',
            borderRadius: '6px',
            fontSize: '0.875rem',
            color: '#64748b'
          }}>
            <strong>{recipientRows.length}</strong> recipient{recipientRows.length !== 1 ? 's' : ''} •
            <strong> {summaries.length}</strong> total summaries •
            Click document counts to view details
          </div>
        </div>
      )}
    </div>
  )
}
