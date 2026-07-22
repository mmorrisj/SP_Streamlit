/**
 * Copy for the per-page "About this page" guides, centralized so voice and
 * terminology stay consistent and edits happen in one place. Keys are stable
 * page ids passed to <PageGuide page="..." />.
 */
export interface PageGuideContent {
  what: string
  how: string
  learnMore?: string // route; defaults to /about
}

export const PAGE_GUIDES: Record<string, PageGuideContent> = {
  dashboard: {
    what:
      'The latest intelligence across the four MENA-active influencers (China, Iran, Russia, Turkey): ' +
      'AI-generated weekly and monthly event narratives, per-influencer activity and materiality indicators, ' +
      'events contested by multiple influencers, and document volume trends. The "Data through" badge shows ' +
      'how current the corpus is.',
    how:
      'Click any event card to open its full detail with source documents. Toggle lines on the weekly chart ' +
      'to compare influencers and recipients, and hover the chips, sparklines, and section headings for ' +
      'definitions of each measure.',
  },
  events: {
    what:
      'Consolidated events from the two-stage deduplication pipeline — each card is one real-world event, ' +
      'possibly spanning many days and articles, with its article count, source count, materiality score ' +
      '(1–10, dollar-anchored), and a lifecycle phase derived from mention activity (emerging, developing, ' +
      'peak, fading, dormant).',
    how:
      'Filter by influencer, recipient, lifecycle phase, materiality threshold, or date range (events whose ' +
      'activity overlaps the range match), and sort by recency, article volume, or materiality. Click a card ' +
      'for the full event detail and its source documents.',
  },
  summaries: {
    what:
      'AI-generated, AP-style event summaries at daily, weekly (Monday–Sunday), and monthly (calendar month) ' +
      'levels — each level synthesizes the one below it. Summaries cover outcomes, progression, and strategic ' +
      'significance, with citations to source documents.',
    how:
      'Switch the period type, filter by country, and expand a summary to read its sections and citations. ' +
      'Cards link through to the underlying event where one is resolved.',
  },
  bilateral: {
    what:
      'Relationship-level analysis for each influencer → recipient pair, generated from all documents about ' +
      'that pair: key themes, initiatives, events, entities, and source composition.',
    how:
      'Click a relationship card to open its full profile with metrics, category breakdowns, tracked events, ' +
      'involved entities, and sources.',
  },
  research: {
    what:
      'A research assistant that answers questions over the document corpus using retrieval-augmented ' +
      'generation: it finds relevant documents by semantic search and generates an answer with citations.',
    how:
      'Ask in plain language about activities, relationships, or events. Follow the citations to verify — ' +
      'answers are generated and can contain errors. The "Data through" badge shows the corpus cutoff.',
  },
  publication: {
    what:
      'Publication-ready analytical reports for a chosen influencer and time period: LLM-generated narrative ' +
      'sections over the period’s top events, metrics, and entities, with full citation management.',
    how:
      'Configure the country, date range, recipient scope, and section toggles, then generate. Progress ' +
      'streams live (you can navigate away — the sidebar widget tracks it), and finished reports export to ' +
      'Word for editing and distribution.',
  },
  'intel-reports': {
    what:
      'Pre-generated analytic assessments produced by an agentic investigation pipeline in which every ' +
      'finding passes adversarial verification before publication. Reports include interactive figures and ' +
      'click-through evidence tracing to source data.',
    how:
      'Pick a report, navigate with the table of contents, and click figures or evidence links to inspect ' +
      'the underlying data behind each claim.',
  },
  'country-comparison': {
    what:
      'Events tracked under two or more initiating countries at once — the places where influencers are ' +
      'engaged in the same story — with each country’s narrative shown side by side.',
    how:
      'Browse the list to see who is competing where; expand an event to compare how each country’s ' +
      'activity around it differs.',
  },
  materiality: {
    what:
      'Materiality analysis — how substantive activity is versus symbolic, on the 1–10 dollar-anchored ' +
      'scale — shown as monthly trends, score distributions, and standout events for a country or bilateral pair.',
    how:
      'Choose a scope (country or pair) and date range. Scores are LLM judgments with written ' +
      'justifications, useful for triage and comparison rather than as ground truth.',
  },
  'competing-influence': {
    what:
      'All influencer activity targeting a single recipient country, side by side — who is engaging, in what ' +
      'categories, with what intensity and materiality.',
    how:
      'Switch the recipient to change scope. Click an influencer for the bilateral profile, or an event for ' +
      'its full detail.',
  },
  alerts: {
    what:
      'Configurable alert rules that watch the corpus for significant changes (activity spikes, high-materiality ' +
      'events, new relationships) plus the history of alerts they have triggered.',
    how:
      'Create a rule by choosing a condition type, threshold, and severity; triggered alerts appear here and ' +
      'in the bell menu, where they can be reviewed and acknowledged.',
  },
}
