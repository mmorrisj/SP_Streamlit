import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line } from 'recharts'
import { fetchDocumentStats } from '../api/client'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4']

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['documentStats'],
    queryFn: () => fetchDocumentStats(),
  })

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading dashboard data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load data</h3>
          <p>Make sure the API server is running</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Soft Power Dashboard</h1>
        <p>Analytics overview of diplomatic documents and events</p>
      </header>

      <div className="stats-grid">
        <div className="stat-card">
          <h3>Total Documents</h3>
          <p className="stat-value">{data?.total_documents || 0}</p>
        </div>
        <div className="stat-card">
          <h3>Countries Analyzed</h3>
          <p className="stat-value">{data?.top_countries?.length || 0}</p>
        </div>
        <div className="stat-card">
          <h3>Categories</h3>
          <p className="stat-value">{data?.category_distribution?.length || 0}</p>
        </div>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <h3>Documents per Week</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data?.documents_by_week || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="week" tick={{ fontSize: 12 }} />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#1a365d" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Top Countries by Document Count</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data?.top_countries || []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="country" type="category" width={100} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#1a365d" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Category Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={data?.category_distribution || []}
                dataKey="count"
                nameKey="category"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry: any) => `${entry.category} (${((entry.percent || 0) * 100).toFixed(0)}%)`}
              >
                {(data?.category_distribution || []).map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
