import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Users } from 'lucide-react'
import './Pages.css'

interface BilateralData {
  initiating_country: string
  recipient_country: string
  count: number
}

export default function BilateralRelationships() {
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['bilateral'],
    queryFn: async () => {
      const response = await fetch('/api/bilateral')
      return response.json()
    },
  })

  return (
    <div className="page">
      <header className="page-header">
        <h1>Bilateral Relationships</h1>
        <p>Analysis of diplomatic interactions between countries.</p>
        <div style={{
          background: '#e0f2fe',
          padding: '0.75rem 1rem',
          borderRadius: '8px',
          marginTop: '1rem',
          border: '1px solid #bae6fd',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem'
        }}>
          <Users size={18} style={{ color: '#0c4a6e' }} />
          <span style={{ color: '#0c4a6e', fontWeight: 500 }}>💡 Click any relationship below to see detailed analytics, trends, and document summaries</span>
        </div>
      </header>

      {isLoading ? (
        <div className="loading">Loading bilateral data...</div>
      ) : (
        <>
          <div className="chart-card full-width">
            <h3>Relationship Intensity</h3>
            {data?.relationships?.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <BarChart data={data.relationships.slice(0, 15)}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis 
                    dataKey={(d: BilateralData) => `${d.initiating_country} → ${d.recipient_country}`} 
                    tick={{ fontSize: 10 }}
                    angle={-45}
                    textAnchor="end"
                    height={100}
                  />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="count" fill="#1a365d" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart">
                <Users size={48} />
                <p>No bilateral relationship data available yet.</p>
              </div>
            )}
          </div>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Initiating Country</th>
                  <th>Recipient Country</th>
                  <th>Interaction Count</th>
                </tr>
              </thead>
              <tbody>
                {data?.relationships?.length > 0 ? (
                  data.relationships.map((rel: BilateralData, idx: number) => (
                    <tr
                      key={idx}
                      onClick={() => navigate(`/bilateral/${rel.initiating_country}/${rel.recipient_country}`)}
                      style={{ cursor: 'pointer' }}
                      className="clickable-row"
                    >
                      <td>{rel.initiating_country}</td>
                      <td>{rel.recipient_country}</td>
                      <td>{rel.count}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={3} className="empty-state">
                      No bilateral data found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
