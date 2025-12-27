export interface Document {
  id: number
  atom_id: string
  title: string
  body: string
  source_name: string
  source_date: string
  category: string
  subcategory: string
  initiating_country: string
  recipient_country: string
  salience_score: number
}

export interface Event {
  id: number
  event_name: string
  event_date: string
  initiating_country: string
  recipient_country: string
  category: string
  subcategory: string
  description: string
  document_count: number
}

export interface Summary {
  id: number
  summary_type: string
  period_start: string
  period_end: string
  content: string
  country: string
  category: string
}

export interface ChartData {
  name: string
  value: number
}

export interface TimeSeriesData {
  date: string
  value: number
}
