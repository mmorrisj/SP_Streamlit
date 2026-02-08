import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface DocumentStats {
  total_documents: number
  total_events: number
  documents_by_week: { week: string; count: number }[]
  documents_by_week_by_influencer: Record<string, { week: string; count: number }[]>
  documents_by_week_by_recipient: Record<string, { week: string; by_influencer: Record<string, number> }[]>
  top_countries: { country: string; count: number }[]
  top_recipients: { country: string; count: number }[]
  category_distribution: { category: string; count: number }[]
  subcategory_distribution: { subcategory: string; count: number }[]
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
  recipients: string[]
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

export const fetchDocumentStats = async (filters?: {
  country?: string
  category?: string
  start_date?: string
  end_date?: string
  influencer_country?: string
  recipient_country?: string
}): Promise<DocumentStats> => {
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

export interface BilateralMapData {
  influencer: string
  recipients: {
    country: string
    document_count: number
    event_count: number
    avg_materiality: number
  }[]
}

export const fetchBilateralMapData = async (influencer?: string): Promise<BilateralMapData> => {
  const { data } = await api.get('/bilateral-map-data', {
    params: { influencer: influencer || 'ALL' }
  })
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

// ============================================================
// Report / Publication types and API functions
// ============================================================

export interface ReportConfig {
  influencers: string[]
  recipients: string[]
  categories: string[]
  date_range: { min: string; max: string }
}

export interface EventEntity {
  name: string
  entity_type: string
  role: string | null
}

export interface ReportEvent {
  event_name: string
  first_mention_date: string
  last_mention_date: string
  article_count: number
  materiality_score: number
  overview: string | null
  outcomes: string | null
  material_justification: string | null
  key_entities: EventEntity[]
  doc_ids: string[]
}

export interface ReportCategory {
  category: string
  narrative: string | null
  events: ReportEvent[]
}

export interface ReportCitation {
  citation_number: number
  doc_id: string
  headline: string
  source_name: string
  published_date: string
  categories: string[]
  recipients: string[]
  repo_hyperlink: string
}

export interface ReportCitationEvent {
  event_name: string
  materiality_score: number
  date_range: string
  citations: ReportCitation[]
}

export interface ReportCitationGroup {
  category: string
  events: ReportCitationEvent[]
}

export interface ReportEntity {
  name: string
  entity_type: string
  role: string
  total_documents: number
  total_mention_days: number
  first_mention_date: string
  last_mention_date: string
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
  summary: string | null
  citation_numbers: number[]
  doc_ids: string[]
}

export interface ReportEntityGroup {
  entity_type: string
  type_label: string
  entities: ReportEntity[]
}

export interface ReportMetrics {
  total_documents: number
  total_events: number
  category_distribution: { category: string; count: number }[]
  subcategory_distribution: { subcategory: string; count: number }[]
  recipient_distribution: { recipient: string; count: number }[]
  materiality_histogram: { bin: string; count: number }[]
}

export interface MaterialityTrendPoint {
  month: string
  avg_score: number
  event_count: number
}

export interface SignificantChange {
  recipient: string
  month: string
  previous_score: number
  current_score: number
  delta: number
  direction: 'increase' | 'decrease'
}

export interface MaterialityTrends {
  trend_start: string
  recipient_series: Record<string, MaterialityTrendPoint[]>
  overall_series: MaterialityTrendPoint[]
  significant_changes: SignificantChange[]
}

export interface ReportData {
  country: string
  title: string
  period_start: string
  period_end: string
  recipient_filter: string
  generated_at: string
  overall_summary: string | null
  categories: ReportCategory[]
  entities: ReportEntityGroup[]
  metrics: ReportMetrics
  materiality_trends: MaterialityTrends
  citations_by_event: ReportCitationGroup[]
}

export interface ReportRequest {
  country: string
  start_date: string
  end_date: string
  recipient?: string
  top_events?: number
  model?: string
}

export const fetchReportConfig = async (): Promise<ReportConfig> => {
  const { data } = await api.get('/report/config')
  return data
}

export const generateReport = async (request: ReportRequest): Promise<ReportData> => {
  const { data } = await api.post('/report/generate', request, {
    timeout: 600000
  })
  return data
}

// ============================================================
// SSE Streaming for Report Generation
// ============================================================

export interface SSECallbacks {
  onSkeleton: (report: ReportData) => void
  onEventNarrative: (data: { category: string; event_index: number; overview: string; outcomes: string }) => void
  onCategoryNarrative: (data: { category: string; narrative: string }) => void
  onOverallSynthesis: (data: { overall_summary: string }) => void
  onEntitySummary: (data: { entity_type_index: number; entity_index: number; summary: string }) => void
  onTitle: (data: { title: string }) => void
  onComplete: () => void
  onError: (error: string) => void
}

export async function generateReportStream(
  request: ReportRequest,
  callbacks: SSECallbacks,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch('/api/report/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Server error ${response.status}: ${text}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No readable stream')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Process complete SSE messages (separated by double newlines)
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || '' // Keep the incomplete part

      for (const part of parts) {
        if (!part.trim()) continue

        let eventType = ''
        let eventData = ''

        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            eventData = line.slice(6)
          }
        }

        if (!eventType || !eventData) continue

        try {
          const payload = JSON.parse(eventData)

          switch (eventType) {
            case 'skeleton':
              callbacks.onSkeleton(payload)
              break
            case 'event_narrative':
              callbacks.onEventNarrative(payload)
              break
            case 'category_narrative':
              callbacks.onCategoryNarrative(payload)
              break
            case 'overall_synthesis':
              callbacks.onOverallSynthesis(payload)
              break
            case 'entity_summary':
              callbacks.onEntitySummary(payload)
              break
            case 'title':
              callbacks.onTitle(payload)
              break
            case 'complete':
              callbacks.onComplete()
              break
            case 'error':
              callbacks.onError(payload.error || 'Unknown streaming error')
              break
          }
        } catch {
          // Skip malformed JSON
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ============================================================
// Word Document Export
// ============================================================

export async function exportReportToDocx(report: ReportData): Promise<void> {
  const response = await fetch('/api/report/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(report),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Export failed: ${response.status} — ${text}`)
  }

  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${report.country}_Report_${report.period_start}.docx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

// ============================================================
// Report Validation Types and Streaming
// ============================================================

export type ValidationStatus = 'green' | 'yellow' | 'red' | 'pending'

export interface SectionValidation {
  section_type: string
  section_id: string
  status: ValidationStatus
  claims_validated: number
  uncited_claims: number
  issues: string[]
  summary: string
}

export interface ValidationCallbacks {
  onStart: (data: { total_sections: number }) => void
  onSectionValidated: (data: SectionValidation) => void
  onComplete: (data: { overall_status: ValidationStatus; validated_at: string }) => void
  onError: (error: string) => void
}

export async function validateReportStream(
  report: ReportData,
  callbacks: ValidationCallbacks,
  model: string = 'gpt-4o-mini',
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch('/api/report/validate/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ report, model }),
    signal,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Validation error ${response.status}: ${text}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No readable stream')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Process complete SSE messages (separated by double newlines)
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (!part.trim()) continue

        let eventType = ''
        let eventData = ''

        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            eventData = line.slice(6)
          }
        }

        if (!eventType || !eventData) continue

        try {
          const payload = JSON.parse(eventData)

          switch (eventType) {
            case 'validation_start':
              callbacks.onStart(payload)
              break
            case 'section_validated':
              callbacks.onSectionValidated(payload)
              break
            case 'validation_complete':
              callbacks.onComplete(payload)
              break
            case 'error':
              callbacks.onError(payload.error || 'Unknown validation error')
              break
          }
        } catch (parseError) {
          console.error('Failed to parse validation SSE payload:', parseError)
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export default api
