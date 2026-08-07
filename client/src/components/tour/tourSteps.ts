/**
 * Step script for the guided product tour, centralized like pageGuides.ts so
 * the narrative reads as one voice and edits happen in one place.
 *
 * Each step either spotlights an element (`target` is a CSS selector, usually
 * a [data-tour] attribute) or renders as a centered card when `target` is
 * omitted or the element never appears. `route` navigates before the step is
 * shown, so the tour can walk across pages.
 */
export interface TourStep {
  id: string
  title: string
  body: string
  /** CSS selector to spotlight; omit for a centered card */
  target?: string
  /** Route to navigate to before showing this step */
  route?: string
  placement?: 'top' | 'bottom' | 'left' | 'right'
  /** Only include the step for users at or above this role */
  minRole?: 'analyst' | 'admin'
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to Soft Power Analytics',
    body:
      'This platform turns open-source reporting into a structured picture of soft power activity — ' +
      'tracked events, AI-generated narratives, and quantitative metrics for China, Iran, Russia, ' +
      'Turkey, and the United States. This quick tour shows you where everything lives. ' +
      'Use Next and Back, or press Esc to exit at any time.',
  },
  {
    id: 'dashboard',
    target: '[data-tour="nav-dashboard"]',
    route: '/',
    placement: 'right',
    title: 'The Dashboard',
    body:
      'Your daily starting point: the latest weekly and monthly event narratives for each influencer, ' +
      'activity and materiality indicators, events contested by multiple influencers, and document ' +
      'volume trends.',
  },
  {
    id: 'coverage',
    target: '[data-tour="dashboard-coverage"]',
    route: '/',
    placement: 'bottom',
    title: 'How current is the data?',
    body:
      'Every corpus has a cutoff. The "Data through" badge shows how recent the underlying reporting ' +
      'is — check it before reading a quiet chart as a real lull in activity.',
  },
  {
    id: 'intelligence',
    target: '[data-tour="dashboard-intelligence"]',
    route: '/',
    placement: 'top',
    title: 'Recent Intelligence',
    body:
      'AI-generated event narratives, one column per influencer, rolled up weekly and monthly. ' +
      'Click any card to open the full event record with its materiality score and source documents.',
  },
  {
    id: 'page-guide',
    target: '[data-tour="page-guide"]',
    route: '/',
    placement: 'bottom',
    title: 'Guides on every page',
    body:
      'Each page carries an "About this page" panel explaining what you are seeing and how to use it. ' +
      'Collapse it once you know your way around — it remembers your choice per page.',
  },
  {
    id: 'events',
    target: '[data-tour="nav-events"]',
    placement: 'right',
    title: 'Consolidated Events',
    body:
      'Each card is one real-world event, deduplicated across days and articles by a two-stage ' +
      'pipeline, with a dollar-anchored materiality score (1–10), a lifecycle phase, and full ' +
      'traceability to its sources.',
  },
  {
    id: 'documents',
    target: '[data-tour="nav-documents"]',
    placement: 'right',
    title: 'The Document Corpus',
    body:
      'The media reporting and policy announcements everything else is built from. Every citation in ' +
      'a generated narrative leads back to a document here.',
  },
  {
    id: 'influencers',
    target: '[data-tour="nav-influencers"]',
    placement: 'right',
    title: 'Influencer Profiles',
    body:
      'One profile per initiating country: headline metrics, activity trends, top recipient ' +
      'relationships, key events, and generated narratives.',
  },
  {
    id: 'insights',
    target: '[data-tour="nav-insights"]',
    placement: 'right',
    title: 'Deeper Analysis',
    body:
      'Purpose-built views for specific questions: hierarchical summaries, the bilateral relationship ' +
      'matrix, side-by-side country comparison, materiality mapping, competing influence on a single ' +
      'recipient, and configurable alerts.',
  },
  {
    id: 'intel-reports',
    target: '[data-tour="nav-intel-reports"]',
    placement: 'right',
    title: 'Insight Reports',
    body:
      'Pre-generated analytic assessments from an agentic investigation pipeline in which every ' +
      'finding passes adversarial verification — with interactive figures and click-through evidence ' +
      'tracing.',
  },
  {
    id: 'research',
    target: '[data-tour="nav-research"]',
    placement: 'right',
    title: 'Research Assistant',
    body:
      'Ask questions about the corpus in plain language. Answers come from semantic search with ' +
      'citations you can follow to verify — the fastest route from question to sourced answer.',
  },
  {
    id: 'agent',
    target: '[data-tour="nav-agent"]',
    placement: 'right',
    title: 'Analytics Agent',
    body:
      'For harder questions: an agentic assistant with direct access to analytics tools that works ' +
      'through events, relationships, trends, and comparisons in multiple steps.',
  },
  {
    id: 'publication',
    target: '[data-tour="nav-publication"]',
    placement: 'right',
    title: 'Publication Reports',
    body:
      'Generate publication-ready analytical reports for a chosen influencer and period — narrative ' +
      'sections over the top events, metrics, and entities, with managed citations and export to Word.',
  },
  {
    id: 'ingestion',
    target: '[data-tour="nav-data"]',
    placement: 'right',
    minRole: 'analyst',
    title: 'Data Ingestion',
    body:
      'As an analyst you can upload document exports, validate them against the database, and run ' +
      'them into the processing pipeline. New documents flow into events and summaries on the next ' +
      'pipeline runs.',
  },
  {
    id: 'about',
    target: '[data-tour="nav-about"]',
    placement: 'right',
    title: 'Trust, but verify',
    body:
      'Content on this platform is AI-generated from open-source reporting and can contain errors ' +
      'and source bias. About & Methodology documents how everything is produced — and every claim ' +
      'links back to its source documents so you can check it.',
  },
  {
    id: 'finish',
    title: "You're all set",
    body:
      'Retake this tour anytime with the "Take the tour" button at the bottom of the sidebar. ' +
      'A good first step: open a weekly narrative on the Dashboard and follow the event through to ' +
      'its source documents.',
  },
]
