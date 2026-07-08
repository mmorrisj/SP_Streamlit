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
  citations: (string | Record<string, unknown>)[]
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
  citations: (string | Record<string, unknown>)[]
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
  provenance?: { total_documents: number; corroborated_documents: number; self_report_share: number }
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
  provenance?: { total_documents: number; corroborated_documents: number; self_report_share: number }
}

export interface BilateralMetrics {
  influencer: string
  recipient: string
  total_documents: number
  provenance?: { total_documents: number; corroborated_documents: number; self_report_share: number }
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
  provenance?: { total_documents: number; corroborated_documents: number; self_report_share: number }
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
  citations: (string | Record<string, unknown>)[]
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
  provenance?: {
    total_documents: number
    corroborated_documents: number
    self_report_share: number
  }
  category_distribution: { category: string; count: number; corroborated?: number }[]
  subcategory_distribution: { subcategory: string; count: number }[]
  recipient_distribution: { recipient: string; count: number; corroborated?: number }[]
  provenance_quadrant?: { recipient: string; raw: number; corroborated: number; corroborated_share: number }[]
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

export interface LookbackEvent {
  event_name: string
  description: string | null
  first_mention_date: string
  last_mention_date: string
  article_count: number
  materiality_score: number
  match_type: 'master_chain' | 'shared_entities' | 'category_recipient'
  shared_entities: string[]
}

export interface LookbackGroup {
  report_event_name: string
  report_event_category: string
  lookback_events: LookbackEvent[]
}

export interface HistoricalContext {
  lookback_start: string
  lookback_end: string
  groups: LookbackGroup[]
  narrative: string | null
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
  historical_context: HistoricalContext | null
}

export interface ReportRequest {
  country: string
  start_date: string
  end_date: string
  recipient?: string
  top_events?: number
  model?: string
  quarterly?: boolean
  // Section toggles (all default true)
  include_events?: boolean
  include_entities?: boolean
  include_metrics?: boolean
  include_persons?: boolean
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
  onHistoricalContext: (data: { narrative: string }) => void
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
            case 'historical_context':
              callbacks.onHistoricalContext(payload)
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
// Agent Report Workflow — SSE Streaming
// ============================================================
//
// Wire to POST /api/agent/workflows/report/stream. Emits five event
// kinds while the 12-stage DAG executes, so the UI can render a live
// timeline plus per-stage structured cards as data arrives instead of
// waiting ~5 minutes for the final response.

export interface AgentReportRequest {
  influencer?: string
  recipient?: string
  region?: string
  start_date: string
  end_date: string
  requested_product?: string
}

export interface WorkflowStartedPayload {
  run_id: string
  workflow: string
  inputs: Record<string, unknown>
  stage_names: string[]
}

export interface StageStartedPayload {
  run_id: string
  stage_name: string
  index: number
  total: number
}

export interface StageSkippedPayload extends StageStartedPayload {
  reason: string
}

export interface StageCompletePayload extends StageStartedPayload {
  status: 'succeeded' | 'failed'
  summary: string | null
  confidence: number | null
  notes: string[] | null
  output: Record<string, unknown> | null
  error: string | null
  latency_ms: number
}

export interface WorkflowCompletePayload {
  run_id: string
  status: string
  skipped_stages: string[]
  error: string | null
}

export interface AgentReportCallbacks {
  onWorkflowStarted?: (p: WorkflowStartedPayload) => void
  onStageStarted?: (p: StageStartedPayload) => void
  onStageSkipped?: (p: StageSkippedPayload) => void
  onStageComplete?: (p: StageCompletePayload) => void
  onWorkflowComplete?: (p: WorkflowCompletePayload) => void
  onWorkflowError?: (message: string) => void
}

// ============================================================
// Agent Chat — Intent classifier
// ============================================================
//
// POST /api/agent/chat. One LLM call server-side: classifies the user's
// message into an action + complete scope object. The chat is stateless on
// the server — the client maintains the thread + scope and sends them back
// each turn.

export interface ChatScope {
  influencer: string | null
  recipient: string | null
  region: string | null
  start_date: string | null
  end_date: string | null
  category: string | null
  subcategory: string | null
  category_mode: string  // "flat" | "filter"
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatTurnRequest {
  message: string
  history: ChatTurn[]
  current_scope: ChatScope
}

export interface ChatTurnResponse {
  action: 'propose_run' | 'update_scope' | 'clarify' | 'chat'
  workflow: string | null
  scope: ChatScope
  message: string
  ready_to_run: boolean
}

export async function sendAgentChat(
  request: ChatTurnRequest,
  signal?: AbortSignal,
): Promise<ChatTurnResponse> {
  const response = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Server error ${response.status}: ${text}`)
  }
  return response.json()
}

export async function streamAgentReport(
  request: AgentReportRequest,
  callbacks: AgentReportCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch('/api/agent/workflows/report/stream', {
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
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (!part.trim()) continue

        let eventType = ''
        let eventData = ''
        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim()
          else if (line.startsWith('data: ')) eventData = line.slice(6)
        }
        if (!eventType || !eventData) continue

        let payload: any
        try {
          payload = JSON.parse(eventData)
        } catch {
          continue
        }

        switch (eventType) {
          case 'workflow_started':
            callbacks.onWorkflowStarted?.(payload)
            break
          case 'stage_started':
            callbacks.onStageStarted?.(payload)
            break
          case 'stage_skipped':
            callbacks.onStageSkipped?.(payload)
            break
          case 'stage_complete':
            callbacks.onStageComplete?.(payload)
            break
          case 'workflow_complete':
            callbacks.onWorkflowComplete?.(payload)
            break
          case 'workflow_error':
            callbacks.onWorkflowError?.(payload.message || 'Unknown workflow error')
            break
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

// ============================================================
// Chart Drilldown Types and API functions
// ============================================================

/**
 * Tracks the original user query that generated the chart,
 * separate from which chart segment was clicked.
 */
export interface DrilldownQueryContext {
  initiating_country?: string
  recipient_country?: string
  category?: string
  subcategory?: string
  start_date?: string
  end_date?: string
  page_source?: string  // which page the drilldown was triggered from
}

/**
 * Describes which chart element the user clicked.
 */
export interface DrilldownChartSelection {
  dimension: 'category' | 'subcategory' | 'recipient_country' | 'initiating_country' | 'month' | 'source'
  value: string
  chart_type?: string  // e.g. 'pie', 'bar', 'line'
}

export interface DrilldownRequest {
  query_context: DrilldownQueryContext
  chart_selection: DrilldownChartSelection
  include_narrative?: boolean  // default true
}

export interface DrilldownMetrics {
  total_documents: number
  date_range: { min: string; max: string }
  category_distribution: { category: string; count: number }[]
  subcategory_distribution: { subcategory: string; count: number }[]
  recipient_distribution: { recipient: string; count: number }[]
  initiator_distribution: { initiator: string; count: number }[]
  monthly_trend: { month: string; count: number }[]
  top_sources: { source: string; count: number }[]
  avg_material_score: number | null
  material_score_distribution: { bin: string; count: number }[]
}

export interface DrilldownDocument {
  doc_id: string
  title: string
  date: string
  source_name: string | null
  category: string | null
  subcategory: string | null
  initiating_country: string | null
  recipient_country: string | null
  material_score: number | null
  distilled_text: string | null
}

export interface DrilldownResponse {
  query_context: DrilldownQueryContext
  chart_selection: DrilldownChartSelection
  metrics: DrilldownMetrics
  narrative: string | null
  narrative_model: string | null
  sample_documents: DrilldownDocument[]
  total_documents: number
}

export const fetchDrilldown = async (request: DrilldownRequest): Promise<DrilldownResponse> => {
  const { data } = await api.post('/drilldown', request)
  return data
}

// ============================================================================
// Entity Profile
// ============================================================================

export interface EntityRelationshipData {
  related_entity_id: string
  related_entity_name: string
  related_entity_type: string | null
  relationship_type: string
  direction: 'outgoing' | 'incoming'
  co_occurrence_count: number
  first_co_occurrence: string | null
  last_co_occurrence: string | null
  relationship_description: string | null
}

export interface AssociatedEventData {
  id: string
  event_name: string
  date: string | null
  material_score: number | null
  story_phase: string | null
  initiating_country: string | null
}

export interface EntityProfile {
  id: string
  canonical_name: string
  entity_type: string | null
  primary_role: string | null
  entity_description: string | null
  initiating_country: string
  country_affiliations: string[]
  alternative_names: string[]
  total_documents: number
  total_mention_days: number
  first_mention_date: string | null
  last_mention_date: string | null
  primary_categories: Record<string, number>
  primary_recipients: Record<string, number>
  key_activities: Record<string, unknown> | null
  relationships: EntityRelationshipData[]
  associated_events: AssociatedEventData[]
  monthly_activity: { month: string; count: number }[]
}

export const fetchEntityProfile = async (entityId: string): Promise<EntityProfile> => {
  const { data } = await api.get(`/entity/${entityId}`)
  return data
}

// ============================================================================
// Research Project & Document Collection
// ============================================================================

export interface ProjectDocument {
  id: string
  project_id: string
  doc_id: string
  title: string | null
  source_name: string | null
  date: string | null
  initiating_country: string | null
  recipient_country: string | null
  category: string | null
  excerpt: string | null
  source_query: string | null
  notes: string | null
  added_at: string | null
}

export interface ResearchProject {
  id: string
  user_id: string
  name: string
  description: string | null
  status: 'active' | 'archived'
  document_count: number
  created_at: string | null
  updated_at: string | null
  documents?: ProjectDocument[]
}

export interface AddProjectDocumentRequest {
  doc_id: string
  title?: string | null
  source_name?: string | null
  date?: string | null
  initiating_country?: string | null
  recipient_country?: string | null
  category?: string | null
  excerpt?: string | null
  source_query?: string | null
  notes?: string | null
}

export const fetchProjects = async (): Promise<ResearchProject[]> => {
  const { data } = await api.get('/projects')
  return data.projects || []
}

export const createProject = async (body: { name: string; description?: string }): Promise<ResearchProject> => {
  const { data } = await api.post('/projects', body)
  return data
}

export const fetchProject = async (projectId: string): Promise<ResearchProject> => {
  const { data } = await api.get(`/projects/${projectId}`)
  return data
}

export const updateProject = async (projectId: string, body: { name?: string; description?: string; status?: string }): Promise<ResearchProject> => {
  const { data } = await api.put(`/projects/${projectId}`, body)
  return data
}

export const deleteProject = async (projectId: string): Promise<void> => {
  await api.delete(`/projects/${projectId}`)
}

export const addProjectDocument = async (projectId: string, body: AddProjectDocumentRequest): Promise<ProjectDocument> => {
  const { data } = await api.post(`/projects/${projectId}/documents`, body)
  return data
}

export const removeProjectDocument = async (projectId: string, docId: string): Promise<void> => {
  await api.delete(`/projects/${projectId}/documents/${encodeURIComponent(docId)}`)
}

export const updateProjectDocumentNotes = async (projectId: string, docId: string, notes: string): Promise<ProjectDocument> => {
  const { data } = await api.put(`/projects/${projectId}/documents/${encodeURIComponent(docId)}`, { notes })
  return data
}

// ============================================================================
// Competing Influence Overlay
// ============================================================================

export interface CompetingInfluenceSummary {
  influencer: string
  doc_count: number
  corroborated: number
  self_report_share: number
  event_count: number
  top_category: string | null
  avg_materiality: number | null
}

export interface CompetingInfluenceEvent {
  id: string
  event_name: string
  date: string | null
  material_score: number | null
  story_phase: string | null
}

export interface CompetingInfluenceData {
  recipient: string
  total_documents: number
  influencer_summary: CompetingInfluenceSummary[]
  monthly_by_influencer: Record<string, unknown>[]
  category_matrix: Record<string, unknown>[]
  category_matrix_corroborated?: Record<string, unknown>[]
  recent_events: Record<string, CompetingInfluenceEvent[]>
}

export const fetchCompetingInfluence = async (
  recipient: string,
  params?: { start_date?: string; end_date?: string }
): Promise<CompetingInfluenceData> => {
  const { data } = await api.get(`/competing-influence/${encodeURIComponent(recipient)}`, { params })
  return data
}

// ============================================================================
// Alert interfaces and API functions
// ============================================================================

export interface AlertRule {
  id: string
  user_id: string
  name: string
  description: string | null
  condition_type: 'materiality_spike' | 'volume_surge' | 'new_entity' | 'new_event'
  condition_params: Record<string, unknown>
  channels: string[]
  channel_config: Record<string, unknown>
  severity: 'info' | 'warning' | 'critical'
  is_enabled: boolean
  cooldown_minutes: number
  last_evaluated_at: string | null
  last_triggered_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AlertHistory {
  id: string
  alert_rule_id: string
  triggered_at: string | null
  severity: 'info' | 'warning' | 'critical'
  title: string
  message: string
  context_data: Record<string, unknown>
  channels_notified: string[]
  acknowledged: boolean
  acknowledged_by: string | null
  acknowledged_at: string | null
}

export interface AlertRuleCreateRequest {
  name: string
  description?: string
  condition_type: string
  condition_params: Record<string, unknown>
  channels?: string[]
  channel_config?: Record<string, unknown>
  severity?: string
  cooldown_minutes?: number
}

export interface AlertRuleUpdateRequest {
  name?: string
  description?: string
  condition_type?: string
  condition_params?: Record<string, unknown>
  channels?: string[]
  channel_config?: Record<string, unknown>
  severity?: string
  cooldown_minutes?: number
  is_enabled?: boolean
}

export const fetchAlertRules = async (): Promise<AlertRule[]> => {
  const { data } = await api.get('/alerts/rules')
  return data.rules || []
}

export const createAlertRule = async (request: AlertRuleCreateRequest): Promise<AlertRule> => {
  const { data } = await api.post('/alerts/rules', request)
  return data
}

export const updateAlertRule = async (ruleId: string, request: AlertRuleUpdateRequest): Promise<AlertRule> => {
  const { data } = await api.put(`/alerts/rules/${ruleId}`, request)
  return data
}

export const deleteAlertRule = async (ruleId: string): Promise<void> => {
  await api.delete(`/alerts/rules/${ruleId}`)
}

export const fetchAlertHistory = async (params?: {
  limit?: number
  offset?: number
}): Promise<{ alerts: AlertHistory[]; total: number }> => {
  const { data } = await api.get('/alerts/history', { params })
  return data
}

export const acknowledgeAlert = async (alertId: string): Promise<void> => {
  await api.post(`/alerts/history/${alertId}/acknowledge`)
}

export const fetchUnreadAlertCount = async (): Promise<number> => {
  const { data } = await api.get('/alerts/unread-count')
  return data.count || 0
}

export const testAlertRule = async (ruleId: string): Promise<{ triggered: boolean; alert?: AlertHistory; message?: string }> => {
  const { data } = await api.post(`/alerts/test/${ruleId}`)
  return data
}

// ============================================================================
// Data Ingestion
// ============================================================================

export interface IngestionWarning {
  code: string
  message: string
  count: number
}

export interface IngestionValidationReport {
  file_type: 'dsr_json' | 'atom_csv'
  total_records: number
  parseable: number
  parse_errors: number
  new_documents?: number
  existing_documents?: number
  within_file_duplicates?: number
  date_range?: { min: string; max: string } | null
  collections?: Record<string, number>
  top_initiating_countries?: { country: string; count: number }[]
  top_recipient_countries?: { country: string; count: number }[]
  columns?: string[]
  warnings: IngestionWarning[]
  sample: Record<string, string | null>[]
  runnable: boolean
  not_runnable_reason: string | null
}

export interface IngestionProgress {
  stage: 'loading' | 'embedding' | 'done'
  total_records: number
  parsed: number
  loaded: number
  duplicates: number
  errors: number
  relationships: Record<string, number>
  embedded: number
  embed_total: number
}

export interface IngestionJob {
  id: string
  filename: string
  file_type: 'dsr_json' | 'atom_csv'
  file_size_bytes: number | null
  status:
    | 'uploaded'
    | 'validating'
    | 'ready'
    | 'validation_failed'
    | 'loading'
    | 'embedding'
    | 'completed'
    | 'completed_with_errors'
    | 'failed'
    | 'cancelled'
  cancel_requested: boolean
  options: Record<string, unknown> | null
  validation_report: IngestionValidationReport | null
  progress: IngestionProgress | null
  error_count: number
  error_message: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  created_by: string | null
}

export interface StartIngestionOptions {
  embed_now: boolean
  reflatten_duplicates: boolean
  doc_batch_size?: number
  embed_batch_size?: number
}

export const uploadIngestionFile = async (
  file: File
): Promise<{ job_id: string; file_type: string; size_bytes: number }> => {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/ingestion/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000,
  })
  return data
}

export const fetchIngestionJobs = async (params?: {
  limit?: number
  offset?: number
}): Promise<{ jobs: IngestionJob[]; total: number }> => {
  const { data } = await api.get('/ingestion/jobs', { params })
  return data
}

export const fetchIngestionJob = async (jobId: string): Promise<IngestionJob> => {
  const { data } = await api.get(`/ingestion/jobs/${jobId}`)
  return data
}

export const startIngestionJob = async (
  jobId: string,
  options: StartIngestionOptions
): Promise<{ job_id: string; status: string }> => {
  const { data } = await api.post(`/ingestion/jobs/${jobId}/start`, options)
  return data
}

export const cancelIngestionJob = async (
  jobId: string
): Promise<{ job_id: string; status: string; cancel_requested: boolean }> => {
  const { data } = await api.post(`/ingestion/jobs/${jobId}/cancel`)
  return data
}

export const ingestionErrorsUrl = (jobId: string): string =>
  `/api/ingestion/jobs/${jobId}/errors`

export default api
