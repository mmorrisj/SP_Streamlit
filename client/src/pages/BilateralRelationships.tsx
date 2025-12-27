import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Users } from 'lucide-react'
import './Pages.css'

interface BilateralData {
  initiating_country: string
  recipient_country: string
  count: number
}

export default function BilateralRelationships() {
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
        <p>Analysis of diplomatic interactions between countries</p>
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
                    <tr key={idx}>
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
