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
  documents: {
    what:
      'The underlying document corpus — the media reporting and policy announcements every event, summary, and ' +
      'metric in the platform is built from. Each document carries its AI-extracted categories, countries, and ' +
      'salience assessment.',
    how:
      'Search by keyword and filter the list; click a document to see its full extracted detail. When a ' +
      'generated narrative elsewhere cites a document, this is where the citation leads.',
  },
  'document-summaries': {
    what:
      'Hierarchical AI-generated coverage summaries — rollups of all reporting for an influencer (or ' +
      'influencer–recipient pair) over a day, week, or month, with full source attribution.',
    how:
      'Filter by influencer, recipient, and period, then open a summary card to read the full narrative with ' +
      'its citations.',
  },
  'summary-detail': {
    what:
      'The full text of one coverage summary: narrative sections, document counts, category breakdowns, and ' +
      'the source citations behind each claim.',
    how:
      'Follow citation links to the underlying documents to verify claims; use the back button to return to ' +
      'the summary list.',
  },
  'bilateral-summaries': {
    what:
      'Monthly, category-specific assessments of bilateral relationships — AI-generated analyses of one ' +
      'influencer’s activity toward one recipient within a category (Economic, Diplomacy, Military, Social).',
    how:
      'Filter by pair, category, and month; open a card for the full assessment and its sources.',
  },
  'bilateral-summary-detail': {
    what:
      'One month’s bilateral assessment in full: the narrative analysis, key developments, and source ' +
      'citations for the selected pair and category.',
    how:
      'Follow citations to source documents; use the back button to return to the list.',
  },
  'bilateral-profile': {
    what:
      'The complete profile of one influencer → recipient relationship: activity metrics and trends, tracked ' +
      'events, involved entities, source composition, and AI-generated relationship narratives.',
    how:
      'Work down the page from headline metrics to events and entities; click any event or entity for its own ' +
      'detail page.',
  },
  'bilateral-metrics': {
    what:
      'Quantitative metrics for one influencer → recipient pair: document volumes over time and ' +
      'category/subcategory breakdowns, without the narrative layer.',
    how:
      'Use the charts to compare periods and categories; return to the bilateral profile for the narrative view.',
  },
  categories: {
    what:
      'How the corpus distributes across the soft power category schema — the primary categories (Economic, ' +
      'Diplomacy, Military, Social) and their subcategories, as assigned by the extraction model.',
    how:
      'Compare category volumes and drill into subcategory distributions to see where activity concentrates.',
  },
  'influencer-profile': {
    what:
      'One influencer’s soft power activity in profile: headline metrics, activity trends, top recipient ' +
      'relationships, key events, and generated narratives for the selected country.',
    how:
      'Switch influencers from the sidebar; click a recipient relationship or event to drill into its detail.',
  },
  'overall-metrics': {
    what:
      'System-wide quantitative metrics across all influencers and recipients: document and event volumes, ' +
      'category distributions, and comparative activity levels. Raw counts reflect media attention, not ' +
      'verified activity — mind the source-composition bias.',
    how:
      'Use the charts to compare influencers at a glance, then follow into an influencer profile or metrics ' +
      'page for the detailed breakdown.',
  },
  'influencer-metrics': {
    what:
      'A detailed quantitative breakdown for one influencer: volumes over time, category and subcategory ' +
      'splits, and top recipient engagements.',
    how:
      'Compare periods and categories with the charts; click through to bilateral pages for pair-level analysis.',
  },
  'recipient-metrics': {
    what:
      'Engagement from all influencers targeting one recipient country: who is active, in what categories, ' +
      'and how activity has trended.',
    how:
      'Compare influencer footprints in the charts; use Competing Influence for the side-by-side narrative view.',
  },
  'event-detail': {
    what:
      'The full record of one consolidated event: its narrative summaries, materiality score with written ' +
      'justification, category and recipient breakdowns, mention timeline, and every source document.',
    how:
      'Read the narrative, then verify against the source documents listed below it. Use the across-periods ' +
      'view to see how coverage evolved from daily to weekly to monthly summaries.',
  },
  'cross-period': {
    what:
      'One event’s narrative followed across summary levels — how the story reads in daily, weekly, and ' +
      'monthly AI-generated summaries as coverage accumulated.',
    how:
      'Compare the period columns to see how the narrative sharpened or shifted; return to the event detail ' +
      'for sources.',
  },
  'timeline-comparison': {
    what:
      'Activity trends for multiple influencers over time on one chart, for comparing the rhythm and scale of ' +
      'their engagement.',
    how:
      'Toggle influencers on and off and adjust the period to compare trajectories; volumes reflect media ' +
      'attention, so mind source-composition bias when comparing actors.',
  },
  agent: {
    what:
      'An agentic research assistant with direct access to analytics tools over the corpus — it can query ' +
      'events, relationships, trends, and comparisons in multiple steps to answer harder questions than ' +
      'single-pass search.',
    how:
      'Give it a task in plain language and watch it work through the steps. Outputs are generated — verify ' +
      'cited data before relying on it.',
  },
  drilldown: {
    what:
      'The documents behind a chart: this page lists the underlying corpus slice for a metric you clicked ' +
      'elsewhere, so aggregate numbers stay traceable to sources.',
    how:
      'Review the matching documents and open any of them for full detail; adjust filters to widen or narrow ' +
      'the slice.',
  },
  'entity-profile': {
    what:
      'One resolved entity (person, organization, or location) consolidated from every mention across the ' +
      'corpus: its roles, relationships, connected entities, and the events it appears in.',
    how:
      'Explore the connection graph and event list; click a connected entity or event to continue the thread.',
  },
  'data-ingestion': {
    what:
      'The ingestion workspace for analysts: upload document exports, validate them against the database, and ' +
      'run them into the processing pipeline.',
    how:
      'Upload a file, review the validation report (parse results, duplicates), then start ingestion and ' +
      'monitor progress. New documents flow into events and summaries on the next pipeline runs.',
  },
  'user-management': {
    what:
      'Administration of user accounts, roles, and permissions. Users are auto-provisioned on first access ' +
      'via the enterprise gateway.',
    how:
      'Change a user’s role to adjust their access: viewers see analysis pages, analysts also get data ' +
      'ingestion, admins get user management.',
  },
}
