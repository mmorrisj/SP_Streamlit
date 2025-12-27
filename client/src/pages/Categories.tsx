import { useQuery } from '@tanstack/react-query'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts'
import { BarChart3 } from 'lucide-react'
import './Pages.css'

const COLORS = ['#1a365d', '#2d4a7c', '#4a6fa5', '#6b8cbe', '#8ca9d4', '#a8c5e8', '#c4d9f2']

interface CategoryData {
  category: string
  count: number
}

interface SubcategoryData {
  subcategory: string
  count: number
}

export default function Categories() {
  const { data, isLoading } = useQuery({
    queryKey: ['categories'],
    queryFn: async () => {
      const response = await fetch('/api/categories')
      return response.json()
    },
  })

  return (
    <div className="page">
      <header className="page-header">
        <h1>Category Analysis</h1>
        <p>Distribution of documents across categories and subcategories</p>
      </header>

      {isLoading ? (
        <div className="loading">Loading category data...</div>
      ) : (
        <div className="charts-grid">
          <div className="chart-card">
            <h3>Category Distribution</h3>
            {data?.categories?.length > 0 ? (
              <ResponsiveContainer width="100%" height={350}>
                <PieChart>
                  <Pie
                    data={data.categories}
                    dataKey="count"
                    nameKey="category"
                    cx="50%"
                    cy="50%"
                    outerRadius={120}
                    label={({ category, percent }) => `${category} (${(percent * 100).toFixed(0)}%)`}
                  >
                    {data.categories.map((_: CategoryData, index: number) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart">
                <BarChart3 size={48} />
                <p>No category data available.</p>
              </div>
            )}
          </div>

          <div className="chart-card">
            <h3>Subcategory Breakdown</h3>
            {data?.subcategories?.length > 0 ? (
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={data.subcategories.slice(0, 10)} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="subcategory" type="category" width={120} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#2d4a7c" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart">
                <BarChart3 size={48} />
                <p>No subcategory data available.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
