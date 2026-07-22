import type { CSSProperties } from 'react'
import { BookOpenText, Database, Cpu, AlertTriangle, Compass } from 'lucide-react'
import './Pages.css'

const sectionStyle: CSSProperties = {
  background: 'white',
  padding: '2rem',
  borderRadius: '12px',
  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
  marginBottom: '2rem',
}

const h2Style: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '0.5rem',
  fontSize: '1.25rem',
  color: '#1a365d',
  marginBottom: '1rem',
}

const pStyle: CSSProperties = { color: '#333', lineHeight: 1.7, marginBottom: '0.75rem' }
const liStyle: CSSProperties = { color: '#333', lineHeight: 1.7, marginBottom: '0.35rem' }

export default function AboutMethodologyPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>About &amp; Methodology</h1>
        <p>What this platform is, how to use it, and how its analysis is produced</p>
      </header>

      <div style={sectionStyle}>
        <h2 style={h2Style}><BookOpenText size={20} /> What This Platform Is</h2>
        <p style={pStyle}>
          The Soft Power Analytics platform analyzes international relations through the lens of{' '}
          <strong>soft power</strong> — a country's ability to influence others through attraction and
          persuasion rather than coercion: cultural exchange, diplomatic engagement, economic
          cooperation, humanitarian aid, and public diplomacy. It continuously processes diplomatic
          documents, news reporting, and policy announcements to identify, track, and summarize soft
          power events over time.
        </p>
        <p style={pStyle}>
          <strong>Coverage:</strong> activity initiated by China, Russia, Iran, Turkey, and the United
          States toward recipient countries across the Middle East and North Africa, from July 2024 to
          present. The United States is only incidentally captured in this rival-centric corpus, so
          most "recent activity" views focus on the other four influencers.
        </p>
      </div>

      <div style={sectionStyle}>
        <h2 style={h2Style}><Compass size={20} /> How to Use the Platform</h2>
        <ul style={{ paddingLeft: '1.25rem' }}>
          <li style={liStyle}><strong>Dashboard</strong> — the landing overview: recent weekly and monthly intelligence, activity and momentum indicators, and document trends. Click any event card to open its full detail.</li>
          <li style={liStyle}><strong>Publication</strong> — generate and export structured analytical reports for a country and time period.</li>
          <li style={liStyle}><strong>Research</strong> — a chat assistant that answers questions over the corpus using semantic search with cited sources.</li>
          <li style={liStyle}><strong>Agent</strong> — a multi-step research agent for deeper, tasked analysis.</li>
          <li style={liStyle}><strong>Events</strong> — browse tracked events with filters; each event links back to its source documents.</li>
          <li style={liStyle}><strong>Documents</strong> — search and inspect the underlying document corpus directly.</li>
          <li style={liStyle}><strong>Insights</strong> — analytical views: period summaries, bilateral relationship analysis, insight reports, country comparison, materiality mapping, competing influence, and alerting.</li>
          <li style={liStyle}><strong>Influencers</strong> — one profile page per initiating country.</li>
        </ul>
        <p style={{ ...pStyle, marginBottom: 0 }}>
          Throughout the app, generated narratives carry citations back to source documents — use them
          to verify any claim before relying on it.
        </p>
      </div>

      <div style={sectionStyle}>
        <h2 style={h2Style}><Database size={20} /> Data Pipeline Methodology</h2>
        <p style={pStyle}>Documents flow through a multi-stage pipeline before anything appears in the UI:</p>
        <ol style={{ paddingLeft: '1.25rem' }}>
          <li style={liStyle}><strong>Ingestion</strong> — raw documents are imported, screened for relevance (salience), and structured.</li>
          <li style={liStyle}><strong>Extraction</strong> — an LLM extracts categories, initiating and recipient countries, events, entities, and projects from each document.</li>
          <li style={liStyle}><strong>Event clustering</strong> — same-day reports are grouped into candidate events using vector embeddings and DBSCAN clustering; an LLM then validates each cluster and creates one canonical event per real-world occurrence.</li>
          <li style={liStyle}><strong>Cross-day consolidation</strong> — canonical events are compared across the whole dataset by embedding similarity, LLM-validated, and merged so a multi-day story becomes a single master event rather than duplicates.</li>
          <li style={liStyle}><strong>Summarization</strong> — AP-style narratives are generated per event at daily, weekly (Monday–Sunday), and monthly (calendar month) levels, each layer synthesizing the one below it. Bilateral and category summaries are generated the same way.</li>
          <li style={liStyle}><strong>Materiality scoring</strong> — each event is scored 1.0–10.0 for how concrete it is: 1–3 symbolic or rhetorical (statements, visits, ceremonies), 4–6 mixed (MOUs, training programs, pilot projects), 7–10 substantive (funded infrastructure, major trade or defense deals, direct financial commitments).</li>
        </ol>
        <p style={{ ...pStyle, marginBottom: 0 }}>
          Every event and summary retains links to its source documents, so all generated analysis is
          traceable to underlying reporting.
        </p>
      </div>

      <div style={sectionStyle}>
        <h2 style={h2Style}><Cpu size={20} /> Generative AI Integration</h2>
        <p style={pStyle}>
          Large language models are used at most pipeline stages: document analysis and entity
          extraction, event cluster validation and deduplication, daily/weekly/monthly narrative
          generation, bilateral and category analysis, materiality scoring, and the Research and Agent
          assistants. Embedding models power clustering and semantic search. Prompts constrain outputs
          to a factual, AP journalism style with required citations, and LLM validation passes check the
          clustering stages — but the outputs remain machine-generated.
        </p>
      </div>

      <div style={{ ...sectionStyle, borderLeft: '4px solid #d97706' }}>
        <h2 style={h2Style}><AlertTriangle size={20} /> Limitations &amp; Caveats</h2>
        <ul style={{ paddingLeft: '1.25rem', marginBottom: 0 }}>
          <li style={liStyle}><strong>Generated content</strong> — summaries, scores, and analyses are produced by AI models and can contain errors, omissions, or hallucinated details. Verify against the cited source documents.</li>
          <li style={liStyle}><strong>Source bias</strong> — the corpus reflects the editorial choices, state influence, and framing of its underlying sources; state-affiliated media in particular presents events favorably to its sponsor.</li>
          <li style={liStyle}><strong>Collection bias</strong> — coverage is shaped by what was collected: the corpus is rival-centric, MENA-focused, and begins in July 2024. Absence of evidence here is not evidence of absence.</li>
          <li style={liStyle}><strong>Model bias</strong> — LLMs carry biases from their training data that can influence categorization, salience judgments, and narrative emphasis.</li>
          <li style={liStyle}><strong>Scores are estimates</strong> — materiality and salience are model judgments on defined rubrics, useful for triage and comparison, not ground truth.</li>
          <li style={liStyle}><strong>Ingestion lag</strong> — data trails the present; check the "Data through" badge on the Dashboard before interpreting recent gaps as real declines.</li>
        </ul>
      </div>
    </div>
  )
}
