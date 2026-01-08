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

export interface OverallMetrics {
  total_documents: number
  total_relationships: number
  active_influencers: number
  active_recipients: number
  category_breakdown: { category: string; count: number }[]
  subcategory_breakdown: { subcategory: string; count: number }[]
  influencer_comparison: { influencer: string; count: number }[]
  monthly_trend: { month: string; count: number }[]
  category_by_influencer: { influencer: string; category: string; count: number }[]
}

export interface InfluencerMetrics {
  influencer: string
  total_documents: number
  category_breakdown: { category: string; count: number }[]
  subcategory_breakdown: { subcategory: string; count: number }[]
  recipient_breakdown: { recipient: string; count: number }[]
  monthly_trend: { month: string; count: number }[]
  source_breakdown: { source: string; count: number }[]
}

export interface BilateralMetrics {
  influencer: string
  recipient: string
  total_documents: number
  category_breakdown: { category: string; count: number }[]
  subcategory_breakdown: { subcategory: string; count: number }[]
  monthly_trend: { month: string; count: number }[]
  source_breakdown: { source: string; count: number }[]
  recent_highlights: {
    doc_id: string
    title: string
    date: string
    distilled_text: string
    salience_justification: string
    category: string
    subcategory: string
  }[]
}

export interface RecipientMetrics {
  recipient: string
  total_documents: number
  influencer_breakdown: { influencer: string; count: number }[]
  category_breakdown: { category: string; count: number }[]
  subcategory_breakdown: { subcategory: string; count: number }[]
  monthly_trend: { month: string; count: number }[]
  source_breakdown: { source: string; count: number }[]
  recent_events: {
    id: number
    event_name: string
    event_date: string
    summary: string
    influencer: string
    total_mentions: number
  }[]
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
  const { data} = await api.get('/summaries', { params: { type } })
  return data.summaries || []
}

export const fetchFilterOptions = async (): Promise<FilterOptions> => {
  const { data } = await api.get('/filters')
  return data
}

export const fetchOverallMetrics = async (): Promise<OverallMetrics> => {
  const { data } = await api.get('/metrics/overall')
  return data
}

export const fetchInfluencerMetrics = async (country: string): Promise<InfluencerMetrics> => {
  const { data } = await api.get(`/metrics/influencer/${country}`)
  return data
}

export const fetchBilateralMetrics = async (influencer: string, recipient: string): Promise<BilateralMetrics> => {
  const { data } = await api.get(`/metrics/bilateral/${influencer}/${recipient}`)
  return data
}

export const fetchRecipientMetrics = async (country: string): Promise<RecipientMetrics> => {
  const { data } = await api.get(`/metrics/recipient/${country}`)
  return data
}

export interface EventTimeline {
  event_name: string
  event_summary: string
  date_range: {
    first: string
    last: string
  }
  daily_article_counts: Record<string, number>
  materiality: number
  category: string
  recipients: string[]
  source_doc_ids: string[]
  atom_search_url: string
}

export interface EventTimelineResponse {
  events: EventTimeline[]
  country: string
  date_range: {
    start: string
    end: string
  }
}

export const fetchEventTimeline = async (
  country: string,
  startDate: string,
  endDate: string,
  level: string = 'monthly'
): Promise<EventTimelineResponse> => {
  const { data } = await api.get('/events/timeline', {
    params: {
      country,
      start_date: startDate,
      end_date: endDate,
      level
    }
  })
  return data
}

export default api
