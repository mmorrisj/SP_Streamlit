import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface DocumentStats {
  total_documents: number
  documents_by_week: { week: string; count: number }[]
  top_countries: { country: string; count: number }[]
  category_distribution: { category: string; count: number }[]
}

export interface Event {
  id: number
  event_name: string
  event_date: string | null
  initiating_country: string | null
  recipient_country: string | null
  category: string | null
  description?: string | null
}

export interface Summary {
  id: number
  summary_type: string
  period_start: string
  period_end: string
  content: string
  country: string
}

export interface FilterOptions {
  countries: string[]
  categories: string[]
  subcategories: string[]
  date_range: { min: string; max: string }
}

export const fetchDocumentStats = async (filters?: Record<string, unknown>): Promise<DocumentStats> => {
  const { data } = await api.get('/documents/stats', { params: filters })
  return data
}

export const fetchEvents = async (filters?: Record<string, unknown>): Promise<Event[]> => {
  const { data } = await api.get('/events', { params: filters })
  return data.events || []
}

export const fetchSummaries = async (type?: string): Promise<Summary[]> => {
  const { data } = await api.get('/summaries', { params: { type } })
  return data.summaries || []
}

export const fetchFilterOptions = async (): Promise<FilterOptions> => {
  const { data } = await api.get('/filters')
  return data
}

export default api
