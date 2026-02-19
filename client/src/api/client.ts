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
  id: string
  event_name: string
  event_date: string | null
  initiating_country: string | null
  recipient_country: string | null
  category: string | null
  description?: string | null
  last_mention_date?: string | null
  total_articles?: number
  total_mention_days?: number
  story_phase?: string | null
  material_score?: number | null
  source_count?: number
  primary_categories?: Record<string, number>
  primary_recipients?: Record<string, number>
  narrative_overview?: string | null
  narrative_outcomes?: string | null
  source_link?: string | null
}

export interface EventsListResponse {
  events: Event[]
  total: number
}

export interface Summary {
  id: string
  summary_type: string
  period_start: string
  period_end: string
  content: string
  country: string
  overview: string | null
  outcomes: string | null
  progression: string | null
  strategic: string | null
  source_link: string | null
  source_count: number | null
  citations: string[]
  count_by_category: Record<string, number>
  count_by_subcategory: Record<string, number>
  count_by_recipient: Record<string, number>
  count_by_source: Record<string, number>
  material_score: number | null
  material_justification: string | null
  canonical_event_id: string | null
  first_observed_date: string | null
  last_observed_date: string | null
  total_documents: number
}

export interface SummariesListResponse {
  summaries: Summary[]
  total: number
}

// Dashboard Intelligence
export interface DashboardIntelligenceItem {
  id: string
  event_name: string
  country: string
  period_start: string | null
  period_end: string | null
  overview: string
  material_score: number | null
  count_by_category: Record<string, number>
  count_by_recipient: Record<string, number>
  canonical_event_id: string | null
}

export interface DashboardIntelligence {
  weekly: DashboardIntelligenceItem[]
  monthly: DashboardIntelligenceItem[]
  period_stats: { country: string; period_type: string; event_count: number; avg_materiality: number | null }[]
}

// Cross-Period Event View
export interface CrossPeriodEntry {
  id: string
  period_start: string | null
  period_end: string | null
  overview: string
  outcomes: string
  progression: string
  strategic: string
  material_score: number | null
  count_by_category: Record<string, number>
  count_by_recipient: Record<string, number>
  source_link: string | null
  source_count: number | null
  citations: string[]
}

export interface CrossPeriodData {
  event_id: string
  event_name: string
  initiating_country: string
  story_phase: string | null
  material_score: number | null
  total_articles: number
  first_mention_date: string | null
  last_mention_date: string | null
  periods: {
    daily: CrossPeriodEntry[]
    weekly: CrossPeriodEntry[]
    monthly: CrossPeriodEntry[]
    yearly: CrossPeriodEntry[]
  }
}

// Country Comparison
export interface CountryNarrative {
  overview: string
  outcomes: string
  material_score: number | null
  count_by_category: Record<string, number>
  period_start: string | null
}

export interface EventComparison {
  event_name: string
  countries: string[]
  country_count: number
  latest_date: string | null
  avg_materiality: number | null
  country_narratives: Record<string, CountryNarrative>
}

export interface EventComparisonResponse {
  comparisons: EventComparison[]
}

// Materiality Heatmap
export interface HeatmapDay {
  date: string
  event_count: number
  avg_materiality: number | null
  max_materiality: number | null
  total_docs: number
}

export interface MonthlyMatrixEntry {
  country: string
  month: string
  event_count: number
  avg_materiality: number | null
  total_docs: number
}

export interface MaterialityHeatmapData {
  daily_heatmap: Record<string, HeatmapDay[]>
  monthly_matrix: MonthlyMatrixEntry[]
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

export const fetchEventsRich = async (params?: {
  country?: string
  story_phase?: string
  sort_by?: string
  limit?: number
  offset?: number
}): Promise<EventsListResponse> => {
  const { data } = await api.get('/events', { params })
  return { events: data.events || [], total: data.total || 0 }
}

export const fetchSummaries = async (type?: string): Promise<Summary[]> => {
  const { data} = await api.get('/summaries', { params: { type } })
  return data.summaries || []
}

export const fetchSummariesRich = async (params?: {
  type?: string
  country?: string
  limit?: number
  offset?: number
}): Promise<SummariesListResponse> => {
  const { data } = await api.get('/summaries', { params })
  return { summaries: data.summaries || [], total: data.total || 0 }
}

export const fetchDashboardIntelligence = async (): Promise<DashboardIntelligence> => {
  const { data } = await api.get('/dashboard/intelligence')
  return data
}

export const fetchEventAcrossPeriods = async (eventId: string): Promise<CrossPeriodData> => {
  const { data } = await api.get(`/events/${eventId}/across-periods`)
  return data
}

export const fetchEventComparison = async (limit?: number): Promise<EventComparisonResponse> => {
  const { data } = await api.get('/events/comparison', { params: { limit } })
  return data
}

export const fetchMaterialityHeatmap = async (): Promise<MaterialityHeatmapData> => {
  const { data } = await api.get('/events/materiality-heatmap')
  return data
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

// ============================================================
// Influencer Page Types and API functions
// ============================================================

export interface InfluencerOverview {
  country: string
  total_documents: number
  total_recipients: number
  total_events: number
  total_entities: number
  avg_material_score: number | null
  top_categories: { category: string; count: number }[]
  recent_activity_trend: { week: string; count: number }[]
  top_recipients: { country: string; count: number }[]
  source_breakdown: { source: string; count: number }[]
}

export interface InfluencerEvent {
  id: string
  event_name: string
  description: string | null
  initiating_country: string
  first_mention_date: string | null
  last_mention_date: string | null
  total_articles: number
  total_mention_days: number
  story_phase: string | null
  material_score: number | null
  material_justification: string | null
  peak_mention_date: string | null
  peak_daily_article_count: number
  source_count: number
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
  narrative_overview: string | null
  narrative_outcomes: string | null
  source_link: string | null
}

export interface InfluencerEventsResponse {
  events: InfluencerEvent[]
  total: number
}

export interface InfluencerEntity {
  id: string
  canonical_name: string
  entity_type: string | null
  primary_role: string | null
  entity_description: string | null
  total_documents: number
  total_mention_days: number
  first_mention_date: string | null
  last_mention_date: string | null
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
}

export interface InfluencerEntitiesResponse {
  entities: InfluencerEntity[]
  total: number
}

export interface BilateralSummary {
  recipient_country: string
  total_documents: number
  total_daily_events: number
  first_interaction_date: string | null
  last_interaction_date: string | null
  count_by_category: Record<string, number>
  overview: string
  key_themes: string[]
  current_status: string
  material_score_avg: number | null
}

export interface InfluencerBilateralSummariesResponse {
  summaries: BilateralSummary[]
}

export const fetchInfluencerOverview = async (country: string): Promise<InfluencerOverview> => {
  const { data } = await api.get(`/influencer/${country}/overview`)
  return data
}

export const fetchInfluencerEvents = async (
  country: string,
  params?: { limit?: number; offset?: number; sort_by?: string }
): Promise<InfluencerEventsResponse> => {
  const { data } = await api.get(`/influencer/${country}/events`, { params })
  return data
}

export const fetchInfluencerEntities = async (
  country: string,
  params?: { limit?: number; offset?: number; entity_type?: string; sort_by?: string }
): Promise<InfluencerEntitiesResponse> => {
  const { data } = await api.get(`/influencer/${country}/entities`, { params })
  return data
}

export const fetchInfluencerBilateralSummaries = async (
  country: string
): Promise<InfluencerBilateralSummariesResponse> => {
  const { data } = await api.get(`/influencer/${country}/bilateral-summaries`)
  return data
}

// ============================================================
// Influencer Page - Phase 2 (Category, Sources, Timeline)
// ============================================================

export interface CategoryStrategySummary {
  category: string
  total_documents: number
  total_daily_events: number
  count_by_recipient: Record<string, number>
  count_by_subcategory: Record<string, number>
  activity_by_month: Record<string, number>
  overview: string
  key_strategies: string[]
  trend_analysis: string
  top_recipients: { country: string; focus_areas: string; intensity: string }[]
  major_initiatives: { name: string; description: string; timeframe: string }[]
  material_score_avg: number | null
}

export interface InfluencerCategorySummariesResponse {
  summaries: CategoryStrategySummary[]
}

export interface SourceDetail {
  source_name: string
  doc_count: number
  first_date: string | null
  last_date: string | null
}

export interface InfluencerSourcesResponse {
  sources: SourceDetail[]
  total_sources: number
  top_geofocus: { geofocus: string; count: number }[]
  top_medium: { medium: string; count: number }[]
}

export interface TimelineItem {
  date: string | null
  event_name: string
  headline: string | null
  summary: string | null
  article_count: number
  news_intensity: string | null
  mention_context: string | null
  story_phase: string | null
  material_score: number | null
  source_count: number
  categories: string[]
  recipients: string[]
  source_link: string | null
}

export interface InfluencerTimelineResponse {
  items: TimelineItem[]
  total: number
}

export const fetchInfluencerCategorySummaries = async (
  country: string
): Promise<InfluencerCategorySummariesResponse> => {
  const { data } = await api.get(`/influencer/${country}/category-summaries`)
  return data
}

export const fetchInfluencerSources = async (
  country: string,
  params?: { limit?: number }
): Promise<InfluencerSourcesResponse> => {
  const { data } = await api.get(`/influencer/${country}/sources`, { params })
  return data
}

export const fetchInfluencerTimeline = async (
  country: string,
  params?: { limit?: number; offset?: number }
): Promise<InfluencerTimelineResponse> => {
  const { data } = await api.get(`/influencer/${country}/timeline`, { params })
  return data
}

// ============================================================
// Bilateral Detail Page Types and API functions
// ============================================================

export interface BilateralEnhancedOverview {
  influencer: string
  recipient: string
  total_documents: number
  total_events: number
  total_entities: number
  avg_material_score: number | null
  first_interaction_date: string | null
  last_interaction_date: string | null
  weekly_average: number
  top_categories: { category: string; count: number }[]
  activity_trend: { week: string; count: number }[]
  source_breakdown: { source: string; count: number }[]
}

export interface BilateralRelationshipProfile {
  overview: string
  key_themes: string[]
  major_initiatives: { name: string; description: string; timeframe: string }[]
  trend_analysis: string
  current_status: string
  notable_developments: string[]
  material_assessment: { score: number; justification: string } | null
  count_by_category: Record<string, number>
  count_by_subcategory: Record<string, number>
  activity_by_month: Record<string, number>
  material_score_histogram: Record<string, number> | null
  material_score_avg: number | null
  material_score_median: number | null
}

export interface BilateralCatSummary {
  category: string
  total_documents: number
  total_daily_events: number
  first_interaction_date: string | null
  last_interaction_date: string | null
  count_by_subcategory: Record<string, number>
  count_by_source: Record<string, number>
  activity_by_month: Record<string, number>
  overview: string
  key_focus_areas: string[]
  major_initiatives: { name: string; description: string; timeframe: string }[]
  interaction_patterns: string
  trend_analysis: string
  impact_assessment: string
  material_assessment: { score: number; justification: string } | null
  material_score_avg: number | null
}

export interface BilateralCategorySummariesResp {
  summaries: BilateralCatSummary[]
}

export interface BilateralEvent {
  id: string
  event_name: string
  description: string | null
  initiating_country: string
  first_mention_date: string | null
  last_mention_date: string | null
  total_articles: number
  total_mention_days: number
  story_phase: string | null
  material_score: number | null
  material_justification: string | null
  peak_mention_date: string | null
  peak_daily_article_count: number
  source_count: number
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
  narrative_overview: string | null
  narrative_outcomes: string | null
  source_link: string | null
}

export interface BilateralEventsResp {
  events: BilateralEvent[]
  total: number
}

export interface BilateralEntity {
  id: string
  canonical_name: string
  entity_type: string | null
  primary_role: string | null
  entity_description: string | null
  total_documents: number
  total_mention_days: number
  first_mention_date: string | null
  last_mention_date: string | null
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
}

export interface BilateralEntitiesResp {
  entities: BilateralEntity[]
  total: number
}

export interface BilateralSourcesResp {
  sources: { source: string; count: number }[]
  total_sources: number
}

export const fetchBilateralEnhancedOverview = async (
  influencer: string,
  recipient: string
): Promise<BilateralEnhancedOverview> => {
  const { data } = await api.get(`/bilateral/${influencer}/${recipient}/enhanced-overview`)
  return data
}

export const fetchBilateralRelationshipProfile = async (
  influencer: string,
  recipient: string
): Promise<BilateralRelationshipProfile> => {
  const { data } = await api.get(`/bilateral/${influencer}/${recipient}/relationship-profile`)
  return data
}

export const fetchBilateralCategorySummaries = async (
  influencer: string,
  recipient: string
): Promise<BilateralCategorySummariesResp> => {
  const { data } = await api.get(`/bilateral/${influencer}/${recipient}/category-summaries`)
  return data
}

export const fetchBilateralEvents = async (
  influencer: string,
  recipient: string,
  params?: { limit?: number; offset?: number; sort_by?: string }
): Promise<BilateralEventsResp> => {
  const { data } = await api.get(`/bilateral/${influencer}/${recipient}/events`, { params })
  return data
}

export const fetchBilateralEntities = async (
  influencer: string,
  recipient: string,
  params?: { limit?: number; offset?: number; entity_type?: string; sort_by?: string }
): Promise<BilateralEntitiesResp> => {
  const { data } = await api.get(`/bilateral/${influencer}/${recipient}/entities`, { params })
  return data
}

export const fetchBilateralSources = async (
  influencer: string,
  recipient: string
): Promise<BilateralSourcesResp> => {
  const { data } = await api.get(`/bilateral/${influencer}/${recipient}/sources`)
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

export interface EventDetailMention {
  date: string | null
  headline: string | null
  summary: string | null
  article_count: number
  news_intensity: string | null
  mention_context: string | null
  source_names: string[]
}

export interface EventDetail {
  id: string
  event_name: string
  description: string | null
  initiating_country: string
  first_mention_date: string | null
  last_mention_date: string | null
  total_articles: number
  total_mention_days: number
  story_phase: string | null
  material_score: number | null
  material_justification: string | null
  peak_mention_date: string | null
  peak_daily_article_count: number
  source_count: number
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
  alternative_names: string[]
  narrative_overview: string | null
  narrative_outcomes: string | null
  source_link: string | null
  source_count_from_summary: number | null
  citations: string[]
  daily_mentions: EventDetailMention[]
}

export const fetchEventDetail = async (eventId: string): Promise<EventDetail> => {
  const { data } = await api.get(`/events/${eventId}`)
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
