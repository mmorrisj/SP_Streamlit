import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { BookOpenText, Database, Cpu, AlertTriangle, Compass, Scale } from 'lucide-react'
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
        <p>
          What this platform is, how to use it, and how its analysis is produced — condensed from the
          full <Link to="/whitepaper">technical white paper</Link>
        </p>
      </header>

      <div style={sectionStyle}>
        <h2 style={h2Style}><BookOpenText size={20} /> What This Platform Is</h2>
        <p style={pStyle}>
          The Soft Power Analytics platform analyzes international relations through the lens of{' '}
          <strong>soft power</strong> — a country's ability to shape the preferences and behaviors of
          other nations through appeal and attraction rather than coercion: cultural diplomacy,
          educational exchange, media and communications, and economic partnership. It continuously
          processes media reporting and policy announcements to identify, consolidate, and summarize
          soft power events over time.
        </p>
        <p style={pStyle}>
          <strong>Coverage:</strong> activity initiated by China, Russia, Iran, Turkey, and the United
          States toward Middle Eastern and North African nations. At current scale the platform manages
          roughly 765K documents spanning nearly two years of coverage, consolidated into ~11K canonical
          events and ~13.5K resolved entities, with full event-to-document traceability. The United
          States is only incidentally captured in this rival-centric corpus, so most "recent activity"
          views focus on the other four influencers. Check the "Data through" badge on the Dashboard for
          how current the corpus is right now.
        </p>
      </div>

      <div style={sectionStyle}>
        <h2 style={h2Style}><Compass size={20} /> How to Use the Platform</h2>
        <ul style={{ paddingLeft: '1.25rem' }}>
          <li style={liStyle}><strong>Dashboard</strong> — the landing overview: recent weekly and monthly intelligence, activity and momentum indicators, and document trends. Click any event card to open its full detail.</li>
          <li style={liStyle}><strong>Publication</strong> — generate and export publication-ready analytical reports (Word export) for a country and time period.</li>
          <li style={liStyle}><strong>Research</strong> — a chat assistant that answers questions over the corpus using retrieval-augmented generation with cited sources.</li>
          <li style={liStyle}><strong>Agent</strong> — an agentic assistant with direct data tools for deeper, multi-step tasked analysis.</li>
          <li style={liStyle}><strong>Events</strong> — browse consolidated canonical events with filters; each event links back to its source documents.</li>
          <li style={liStyle}><strong>Documents</strong> — search and inspect the underlying document corpus directly.</li>
          <li style={liStyle}><strong>Insights</strong> — analytical views: period summaries, bilateral relationship analysis, generated insight reports with click-through evidence tracing, country comparison, materiality mapping, competing influence, and configurable alerts.</li>
          <li style={liStyle}><strong>Influencers</strong> — one profile page per initiating country.</li>
          <li style={liStyle}><strong>White Paper</strong> — the full technical white paper behind this page.</li>
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
          <li style={liStyle}><strong>Salience screening</strong> — every ingested document is screened by a lightweight LLM to detect articles relevant to soft power activity.</li>
          <li style={liStyle}><strong>Extraction</strong> — salient articles are run through a stronger extraction model that categorizes them against the soft power schema, distills relevant content, identifies initiating and recipient countries, geolocates activity, and names the specific event.</li>
          <li style={liStyle}><strong>Daily event clustering</strong> — per country and day, event names are embedded (Nomic Embed Text) and clustered with DBSCAN; an LLM validates each cluster and creates one canonical event per real-world occurrence, linked to its source documents.</li>
          <li style={liStyle}><strong>Cross-temporal consolidation</strong> — canonical events are compared across the entire dataset by embedding similarity (cosine ≥ 0.85), grouped under a master event, LLM-validated, and merged so a multi-day story becomes a single event hierarchy rather than duplicates.</li>
          <li style={liStyle}><strong>Entity resolution</strong> — people, organizations, and locations are extracted, clustered, and consolidated the same two-stage way, then linked to events and each other to build the entity relationship network.</li>
          <li style={liStyle}><strong>Summarization</strong> — AP-style narratives are generated per event at daily, weekly (Monday–Sunday), and monthly (calendar month) levels, each layer synthesizing the one below it, with citations and hyperlinks to original documents. Bilateral and category summaries are generated the same way.</li>
          <li style={liStyle}><strong>SME review</strong> — a human-in-the-loop step where analysts flag high-priority events, split over-consolidated events, and merge events that should be tracked together.</li>
        </ol>
        <p style={{ ...pStyle, marginBottom: 0 }}>
          Every event and summary retains links to its source documents, so all generated analysis is
          traceable to underlying reporting.
        </p>
      </div>

      <div style={sectionStyle}>
        <h2 style={h2Style}><Scale size={20} /> Materiality &amp; Bias Control</h2>
        <p style={pStyle}>
          <strong>Materiality scoring.</strong> Each event is scored 1.0–10.0 for concrete significance
          using dollar-anchored bands: 1–2 routine diplomatic activity (&lt;$1M), 3–4 notable but
          limited impact ($1M–$50M), 5–6 significant regional event ($50M–$500M), 7–8 major bilateral
          development ($500M–$5B), 9–10 strategic or transformative (&gt;$5B). In practice scores range
          about 2–9 with a mean near 4.7. The score is an LLM judgment of significance, not a measured
          outcome, and each score is stored with its written justification.
        </p>
        <p style={{ ...pStyle, marginBottom: 0 }}>
          <strong>Source provenance.</strong> A media corpus records <em>attention</em>, not activity,
          and attention is unevenly supplied — this corpus over-indexes heavily on Iranian state media.
          To control for that, every document is classified as <em>self-reported</em> (the initiator's
          own media ecosystem) or <em>third-party</em> (recipient-country or neutral outlets), and
          cross-actor comparisons are computed on the third-party basis. The platform's honest unit of
          analysis is the <strong>corroborated initiative</strong>: a canonical event with at least 50%
          third-party coverage from at least 3 independent outlets. Article counts measure attention;
          corroborated initiatives measure independently attested activity.
        </p>
      </div>

      <div style={sectionStyle}>
        <h2 style={h2Style}><Cpu size={20} /> Generative AI Integration</h2>
        <p style={pStyle}>
          Generative AI runs through most of the pipeline: salience screening, extraction and
          categorization, event and entity cluster validation, narrative generation at every summary
          level, materiality scoring, the Research and Agent assistants, and the agentic investigation
          pipeline behind Insight Reports — where every finding passes adversarial verification before
          publication. Models are tiered by task complexity to balance quality and cost, with
          lightweight models on high-volume screening and stronger models on extraction and analysis.
          Open-source embedding models power clustering and semantic search. Structured JSON
          enforcement, citation requirements, periodic output evaluation, and SME review checkpoints
          guard quality — but the outputs remain machine-generated.
        </p>
      </div>

      <div style={{ ...sectionStyle, borderLeft: '4px solid #d97706' }}>
        <h2 style={h2Style}><AlertTriangle size={20} /> Limitations &amp; Caveats</h2>
        <ul style={{ paddingLeft: '1.25rem', marginBottom: 0 }}>
          <li style={liStyle}><strong>Media-source bias (the dominant limitation)</strong> — the corpus is media reporting, not ground truth, and its composition is skewed: Iranian state outlets contribute a large plurality of documents, while some tracked actors have no domestic outlets ingested at all. Raw volume comparisons across actors are structurally misleading; prefer the provenance-corrected views.</li>
          <li style={liStyle}><strong>Generated content</strong> — summaries, scores, and analyses are produced by AI models and can contain errors, omissions, or hallucinated details. Verify against the cited source documents.</li>
          <li style={liStyle}><strong>Monetary figures are announced, not verified</strong> — dollar amounts are captured for only about a quarter of documents, in inconsistent formats, and repeated coverage of the same deal can multi-count. Treat them as named-deal citations, not aggregate financial data.</li>
          <li style={liStyle}><strong>Deduplication fidelity</strong> — event consolidation can over- or under-merge; SME adjudication corrects errors but review capacity is limited.</li>
          <li style={liStyle}><strong>Scores are estimates</strong> — materiality and salience are model judgments on defined rubrics, useful for triage and comparison, not ground truth.</li>
          <li style={liStyle}><strong>Ingestion lag</strong> — data trails the present; check the "Data through" badge on the Dashboard before interpreting recent gaps as real declines.</li>
        </ul>
      </div>

      <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
        For the complete methodology — including model evaluations, prompt engineering, the entity and
        relationship schema, the agentic RAG architecture, and risk management — see the{' '}
        <Link to="/whitepaper">technical white paper</Link>.
      </p>
    </div>
  )
}
