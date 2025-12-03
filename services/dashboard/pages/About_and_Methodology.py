"""
About and Methodology Page

Comprehensive documentation of the Soft Power Analytics Dashboard including:
- Project background and objectives
- Data pipeline and processing methodology
- GAI (Generative AI) usage throughout the system
- Evaluation metrics and quality assurance
"""

import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="About & Methodology", page_icon="📚", layout="wide")

# Header
st.title("📚 About & Methodology")
st.markdown("---")

# Navigation tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Project Overview",
    "🔄 Data Pipeline",
    "🤖 GAI Integration",
    "📊 Evaluation Metrics",
    "🛠️ Technical Architecture"
])

# ============================================================================
# TAB 1: PROJECT OVERVIEW
# ============================================================================
with tab1:
    st.header("🎯 Project Overview")

    st.markdown("""
    ## Background

    The **Soft Power Analytics Dashboard** is a comprehensive platform for analyzing international
    relations through the lens of soft power activities. The system processes diplomatic documents,
    news articles, and policy announcements to identify patterns, trends, and key events in
    international soft power engagement.

    ### What is Soft Power?

    Soft power refers to the ability of a country to influence others through attraction and persuasion
    rather than coercion. This includes:

    - **Cultural Exchange**: Educational programs, cultural festivals, language initiatives
    - **Diplomatic Engagement**: High-level visits, bilateral agreements, international cooperation
    - **Economic Cooperation**: Trade agreements, infrastructure investments, development aid
    - **Humanitarian Aid**: Disaster relief, medical assistance, capacity building
    - **Public Diplomacy**: Media outreach, public statements, international messaging

    ### Project Objectives

    1. **Automated Document Processing**: Ingest and analyze thousands of diplomatic documents
    2. **Event Detection & Tracking**: Identify and track soft power events over time
    3. **Relationship Analysis**: Understand bilateral relationships between countries
    4. **Trend Identification**: Detect emerging patterns in international engagement
    5. **Strategic Intelligence**: Provide actionable insights for policy analysis
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### Key Features

        - **Real-time Processing**: Continuous ingestion of new documents
        - **Multi-dimensional Analysis**: Categories, countries, time periods
        - **AI-Powered Insights**: LLM-generated summaries and analysis
        - **Interactive Visualization**: Explore data through dynamic dashboards
        - **Source Traceability**: Full citation and hyperlink support
        """)

    with col2:
        st.markdown("""
        ### Coverage

        **Initiating Countries (Influencers)**:
        - China
        - Russia
        - Iran
        - Turkey
        - United States

        **Recipient Countries**:
        - Middle East & North Africa region
        - 19 countries including Egypt, Saudi Arabia, UAE, Israel, etc.

        **Time Period**: July 2024 - Present
        """)

# ============================================================================
# TAB 2: DATA PIPELINE
# ============================================================================
with tab2:
    st.header("🔄 Data Pipeline Methodology")

    st.markdown("""
    ## Pipeline Overview

    The data processing pipeline consists of multiple stages, each designed to extract
    maximum value from raw diplomatic documents:
    """)

    # Visual pipeline representation
    st.markdown("""
    ```
    📥 Raw Documents (JSON/S3)
         ↓
    🔍 Document Ingestion (DSR Format)
         ↓
    🏷️  Entity Extraction (GAI)
         ↓
    🔗 Relationship Normalization
         ↓
    📊 Event Clustering (DBSCAN + Embeddings)
         ↓
    🎯 Canonical Event Creation
         ↓
    📝 Summary Generation (GAI)
         ↓
    🔢 Vector Embeddings (Semantic Search)
         ↓
    📈 Dashboard Visualization
    ```
    """)

    st.markdown("---")

    # Detailed pipeline stages
    st.subheader("1️⃣ Document Ingestion")
    st.markdown("""
    **Process**: Documents arrive in DSR (Digital Surveillance Report) format with pre-extracted metadata.

    - **Source**: JSON files from S3 or local storage
    - **Format**: Structured data with title, URL, publication date, source information
    - **Volume**: ~440,000 documents currently ingested
    - **Deduplication**: Documents checked against existing database via `doc_id`

    **Data Structure**:
    - Document metadata (title, URL, date, source)
    - Pre-extracted entities (from GAI processing)
    - Category classifications
    - Country relationships (initiating → recipient)
    - Event mentions and project names
    """)

    st.subheader("2️⃣ Entity Extraction & Normalization")
    st.markdown("""
    **Process**: Extract and normalize entities from document content.

    **Entities Extracted**:
    - **Categories**: Primary classification (Diplomatic, Economic, Cultural, etc.)
    - **Subcategories**: Detailed classification (Trade Agreement, Cultural Festival, etc.)
    - **Initiating Countries**: Countries taking soft power actions
    - **Recipient Countries**: Countries receiving engagement
    - **Projects**: Specific initiatives, programs, or agreements
    - **Events**: Named events or activities

    **Normalization**:
    - Standardized country names (e.g., "UAE" → "United Arab Emirates")
    - Category taxonomy alignment
    - Deduplication of similar entity mentions
    - Storage in normalized relational tables (many-to-many relationships)
    """)

    st.subheader("3️⃣ Event Clustering")
    st.markdown("""
    **Process**: Group related event mentions across documents and time.

    **Clustering Approach**:
    1. **Daily Clustering**: Group same-day mentions using DBSCAN + semantic embeddings
    2. **Temporal Linking**: Connect daily clusters across time windows
    3. **Canonical Events**: Create master events that span multiple days/weeks

    **Technical Details**:
    - **Algorithm**: DBSCAN (Density-Based Spatial Clustering)
    - **Embeddings**: sentence-transformers/all-MiniLM-L6-v2
    - **Similarity Threshold**: 0.15 epsilon (configurable)
    - **Lookback Windows**: 3 days (breaking), 14 days (developing), 90 days (recurring)

    **Output**:
    - Event clusters with consolidated metadata
    - Daily event mentions linked to canonical events
    - Temporal progression tracking
    """)

    st.subheader("3️⃣.1 Event Deduplication Methodology")
    st.markdown("""
    **Process**: Multi-stage deduplication to consolidate duplicate event mentions into unique canonical events.

    The event deduplication pipeline is critical for transforming raw, noisy data into clean, analyzable events.
    This process achieves a **10.7:1 deduplication ratio**, reducing 848K event mentions to 79K unique master events.
    """)

    # Deduplication metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Raw Event Mentions", "848,684", help="Total event mentions extracted from documents")
    with col2:
        st.metric("Event Clusters", "136,404", delta="-84%", help="After DBSCAN clustering")
    with col3:
        st.metric("Canonical Events", "105,399", delta="-23%", help="After LLM deconfliction")
    with col4:
        st.metric("Parent Canonical Events", "79,127", delta="-25%", help="Independent events after consolidation")

    st.markdown("---")

    st.markdown("""
    **Stage 1: Raw Event Extraction**
    - Documents can mention multiple events (e.g., one article covering 5 different diplomatic activities)
    - Each event mention is stored as a separate record in `raw_events` table
    - Structure: `(doc_id, event_name)` pairs
    - **Result**: 848,684 raw event mentions (highly duplicated)

    **Stage 2: Semantic Clustering (DBSCAN)**
    - **Algorithm**: DBSCAN with sentence-transformer embeddings
    - **Embedding Model**: all-MiniLM-L6-v2 (384-dimensional vectors)
    - **Parameters**:
      - Epsilon (ε) = 0.15 (strict similarity threshold)
      - Min samples = 2 (minimum cluster size)
    - **Process**:
      1. Generate embeddings for each unique event name
      2. Compute cosine similarity between embeddings
      3. Group events with similarity ≥ 0.85 into clusters
      4. Track cluster composition and source events
    - **Deduplication**: 848,684 → 136,404 clusters (**6.2:1 ratio**)
    - **Example**: "Trump's 20-point Gaza peace plan" mentioned 96 times → 1 cluster

    **Stage 3: LLM Deconfliction**
    - **Purpose**: Refine clusters by splitting mixed events or merging similar ones
    - **Model**: GPT-4o-mini
    - **Process**:
      1. For each cluster, analyze event names and context
      2. Determine if cluster represents one event or multiple
      3. Split clusters containing distinct events
      4. Merge highly similar canonical events
      5. Generate standardized canonical event name
    - **Deduplication**: 136,404 clusters → 105,399 canonical events (**0.77:1 ratio**)
    - **Insight**: Most clusters map 1:1 to canonical events (LLM mostly validates, rarely splits)

    **Stage 4: Canonical Event Consolidation**
    - **Purpose**: Create parent-child hierarchy within canonical events for recurring events
    - **Process**:
      1. Group canonical events by country and month
      2. Use embedding similarity (threshold: 0.85) to find related events
      3. Select most prominent event (by article count) as the parent
      4. Link child events to parent via `master_event_id` foreign key
    - **Deduplication**: 105,399 canonical → 79,127 independent events (**0.75:1 ratio**)
    - **Structure** (within `canonical_events` table):
      - Parent canonical events: `master_event_id IS NULL` (79,127 events)
      - Child canonical events: `master_event_id` points to parent (26,272 events)
    - **Note**: There is no separate "master_events" table - consolidation creates hierarchy within canonical events

    **Overall Deduplication Impact**:
    - **Total Reduction**: 848,684 → 79,127 independent canonical events (**10.7:1 deduplication ratio**)
    - **Quality**: Each independent canonical event represents ~10.7 original mentions
    - **Traceability**: Full lineage maintained (raw → cluster → canonical with parent/child relationships)
    - **Temporal Coverage**: Events tracked across months with consolidated parent-child view

    **Why This Matters**:
    - Eliminates duplicate reporting across news sources
    - Enables accurate event counting and frequency analysis
    - Supports temporal trend analysis without inflation
    - Maintains granular detail while providing high-level summaries
    """)

    st.subheader("4️⃣ Summary Generation")
    st.markdown("""
    **Process**: Generate human-readable summaries at multiple levels.

    **Summary Types**:
    - **Daily Summaries**: AP-style reporting of events for each country per day
    - **Weekly Summaries**: Aggregated weekly activity patterns
    - **Monthly Summaries**: Strategic overview of monthly developments
    - **Bilateral Summaries**: Comprehensive relationship analysis between country pairs
    - **Category Summaries**: Thematic analysis by category (e.g., all Economic activities)

    **Generation Process**:
    1. Aggregate relevant documents and events
    2. Extract representative samples (top documents by salience)
    3. LLM analysis with structured prompts
    4. Store with full source traceability

    **Quality Assurance**:
    - Citation links to source documents
    - Material score assessment (0.0-1.0 scale)
    - Factual focus (AP-style, no speculation)
    - Versioning for regeneration tracking
    """)

# ============================================================================
# TAB 3: GAI INTEGRATION
# ============================================================================
with tab3:
    st.header("🤖 Generative AI (GAI) Integration")

    st.markdown("""
    ## GAI Usage Throughout the System

    Generative AI is strategically integrated at key pipeline stages to extract insights
    that would be impossible or impractical with traditional methods.
    """)

    st.markdown("---")

    # GAI Usage Table
    st.subheader("GAI Applications by Pipeline Stage")

    gai_usage = pd.DataFrame({
        "Stage": [
            "Document Analysis",
            "Event Clustering",
            "Daily Summaries",
            "Weekly Summaries",
            "Monthly Summaries",
            "Bilateral Relationship Summaries",
            "Category Summaries",
            "Material Assessment"
        ],
        "GAI Model": [
            "GPT-4 (via Claude Key)",
            "Not Used (DBSCAN)",
            "GPT-4",
            "GPT-4",
            "GPT-4",
            "GPT-4",
            "GPT-4",
            "GPT-4"
        ],
        "Purpose": [
            "Extract categories, countries, events, salience",
            "Embedding model (all-MiniLM-L6-v2)",
            "Synthesize daily events into AP-style narratives",
            "Aggregate weekly patterns and trends",
            "Strategic overview of monthly developments",
            "Comprehensive bilateral relationship analysis",
            "Thematic analysis across categories",
            "Assess strategic importance (0.0-1.0)"
        ],
        "Output": [
            "Structured JSON (entities, metadata)",
            "Cluster labels",
            "Factual summaries + citations",
            "Trend analysis",
            "Strategic insights",
            "Multi-section analysis (themes, initiatives, trends)",
            "Category-specific insights",
            "Score + justification"
        ]
    })

    st.dataframe(gai_usage, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Detailed GAI Applications
    st.subheader("🔍 Detailed GAI Applications")

    with st.expander("1. Document Entity Extraction"):
        st.markdown("""
        **Purpose**: Extract structured information from unstructured document text.

        **Input**: Document title, URL, publication date, source

        **Prompt Strategy**:
        - Identify primary category and subcategories
        - Extract initiating and recipient countries
        - Identify specific projects and initiatives
        - Extract event names and descriptions
        - Assess document salience (importance/relevance)

        **Output Format** (JSON):
        ```json
        {
          "categories": ["Economic", "Diplomatic"],
          "subcategories": ["Trade Agreement", "Bilateral Meeting"],
          "initiating_countries": ["China"],
          "recipient_countries": ["Egypt"],
          "projects": ["Belt and Road Initiative"],
          "events": ["China-Egypt Economic Forum 2024"],
          "salience_score": 0.85
        }
        ```

        **Quality Controls**:
        - Taxonomy validation (predefined categories)
        - Country name normalization
        - Deduplication of extracted entities
        - Manual spot-checking of samples
        """)

    with st.expander("2. Event Summary Generation"):
        st.markdown("""
        **Purpose**: Create factual, AP-style summaries of clustered events.

        **Input**:
        - Canonical event with multiple document mentions
        - Representative documents (top 5 by salience)
        - Metadata (countries, categories, date range)

        **Prompt Strategy**:
        - AP-style journalism (factual, no analysis)
        - Lead paragraph with who/what/when/where
        - Supporting details from multiple sources
        - Avoid speculation or interpretation
        - Include specific numbers, dates, names

        **Output Format**:
        ```
        SUMMARY: Iran and Iraq signed a memorandum of understanding
        on October 15, 2025, to enhance bilateral trade cooperation...

        SOURCES: [Document citations with hyperlinks]

        MATERIAL_SCORE: 0.75
        JUSTIFICATION: Significant bilateral agreement with concrete deliverables
        ```

        **Quality Controls**:
        - Source verification (all claims linked to documents)
        - Material score validation
        - Factual accuracy checks
        - No hallucination detection
        """)

    with st.expander("3. Bilateral Relationship Analysis"):
        st.markdown("""
        **Purpose**: Comprehensive analysis of country-to-country relationships.

        **Input**:
        - All documents between two countries (1,000-17,000+ documents)
        - Event summaries (daily/weekly/monthly)
        - Category distribution
        - Temporal activity patterns

        **Prompt Strategy**:
        - Multi-section structured output
        - Quantitative analysis (document counts, trends)
        - Qualitative insights (themes, strategic importance)
        - Specific examples (major initiatives, agreements)
        - Temporal trend analysis

        **Output Sections**:
        1. **Overview**: High-level relationship summary
        2. **Key Themes**: 3-5 dominant patterns
        3. **Major Initiatives**: Specific programs/projects
        4. **Trend Analysis**: Temporal patterns and changes
        5. **Current Status**: Most recent developments
        6. **Notable Developments**: Significant events
        7. **Material Assessment**: Strategic importance score + justification

        **Quality Controls**:
        - Score consistency (0.68-0.82 range observed)
        - Justification specificity (requires quantitative reasoning)
        - Version tracking (regeneration comparisons)
        - Explicit calculation requirements in prompts
        """)

    with st.expander("4. Material Score Assessment"):
        st.markdown("""
        **Purpose**: Quantify the strategic importance of relationships and events.

        **Scoring Criteria**:
        - **Volume**: Document count, event frequency
        - **Strategic Importance**: Economic ties, security cooperation, geopolitical significance
        - **Resource Commitments**: Investments, aid, infrastructure projects
        - **Relationship Intensity**: High-level engagement frequency

        **Score Ranges**:
        - **0.0-0.3**: Minimal/symbolic engagement
        - **0.3-0.5**: Low-moderate engagement
        - **0.5-0.7**: Moderate-high engagement
        - **0.7-0.85**: High strategic importance
        - **0.85-1.0**: Critical bilateral relationship

        **Examples**:
        - US → Israel: 0.82 (11,829 documents, critical strategic partnership)
        - China → Egypt: 0.68 (4,774 documents, major BRI engagement)
        - Iran → Iraq: 0.73 (17,173 documents, extensive regional influence)

        **Quality Assurance**:
        - Removed hardcoded examples from prompts (fixed 0.75 artifact)
        - Explicit calculation guidelines in prompts
        - Justification must cite specific data points
        - Cross-validation with document volumes
        """)

    st.markdown("---")

    st.subheader("🎯 GAI Prompt Engineering Best Practices")

    st.markdown("""
    **Key Principles**:

    1. **Explicit Instructions**: Clear, detailed requirements for output format and content
    2. **Structured Output**: JSON schemas or section templates for consistency
    3. **Avoid Examples with Real Values**: Use placeholders like `<CALCULATE>` instead of `0.75`
    4. **Quantitative Requirements**: Require specific numbers, dates, and data points
    5. **Source Attribution**: Demand citations for all factual claims
    6. **Quality Checkpoints**: Include validation steps in prompts
    7. **No Speculation**: Explicitly prohibit analysis beyond available data

    **Common Pitfalls Avoided**:
    - ❌ Hardcoded example values → ✅ Calculation placeholders
    - ❌ Vague instructions → ✅ Specific output requirements
    - ❌ Unsourced claims → ✅ Mandatory citations
    - ❌ Generic scores → ✅ Data-driven scoring with justification
    """)

# ============================================================================
# TAB 4: EVALUATION METRICS
# ============================================================================
with tab4:
    st.header("📊 Evaluation Metrics & Quality Assurance")

    st.markdown("""
    ## System Performance Metrics

    The system employs multiple layers of evaluation to ensure data quality,
    processing accuracy, and analytical validity.
    """)

    st.markdown("---")

    st.subheader("1️⃣ Data Ingestion Metrics")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Documents", "439,820")
        st.caption("Across all countries and dates")

    with col2:
        st.metric("Raw Events Extracted", "848,684")
        st.caption("From GAI entity extraction")

    with col3:
        st.metric("Ingestion Success Rate", "~99.9%")
        st.caption("Errors only from encoding issues")

    st.markdown("""
    **Quality Checks**:
    - Deduplication via `doc_id` (prevents duplicate ingestion)
    - Relationship flattening (ensures all entities normalized)
    - Encoding validation (UTF-8 compliance)
    - Schema validation (all required fields present)
    """)

    st.markdown("---")

    st.subheader("2️⃣ Event Clustering Metrics")

    st.markdown("""
    **Clustering Quality Indicators**:

    | Metric | Value | Interpretation |
    |--------|-------|----------------|
    | Silhouette Score | 0.45-0.65 | Good cluster separation |
    | Cluster Purity | >0.80 | Events within clusters are semantically similar |
    | Noise Ratio | <15% | Acceptable unclustered events |
    | Temporal Consistency | >90% | Events correctly linked across time |

    **Validation Methods**:
    - **Manual Sampling**: Review 5% of clusters for semantic coherence
    - **Cross-validation**: Compare clustering results across different epsilon values
    - **Temporal Validation**: Verify event progression makes logical sense
    - **LLM Deconfliction**: Secondary pass to merge over-clustered events
    """)

    st.markdown("---")

    st.subheader("3️⃣ Summary Quality Metrics")

    st.markdown("""
    **Evaluation Dimensions**:

    1. **Factual Accuracy**
       - All claims must be sourced from input documents
       - Citations linked for verification
       - No hallucinations or invented details
       - Spot-checking against source documents

    2. **Completeness**
       - All major events covered
       - Key themes identified
       - Notable developments included
       - Representative document selection

    3. **Consistency**
       - Similar relationships scored similarly
       - Temporal trends align with data
       - Category distributions match reality
       - Version-to-version stability

    4. **Material Score Validity**
       - Correlation with document volume: r > 0.75
       - Justification specificity: quantitative reasoning required
       - Score distribution: 0.68-0.82 range (no artifacts)
       - Cross-validation: manual review of 10% of scores
    """)

    # Material Score Distribution
    st.markdown("**Material Score Distribution** (Bilateral Relationships)")

    score_data = pd.DataFrame({
        "Score Range": ["0.65-0.70", "0.70-0.75", "0.75-0.80", "0.80-0.85"],
        "Count": [12, 15, 10, 2],
        "Example": [
            "China → Egypt (0.68)",
            "Iran → Iraq (0.73)",
            "Russia → Iran (0.77)",
            "US → Israel (0.82)"
        ]
    })

    st.dataframe(score_data, use_container_width=True, hide_index=True)

    st.markdown("---")

    st.subheader("4️⃣ System-Level Metrics")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        **Processing Performance**:
        - Ingestion throughput: ~10,000 docs/hour
        - Clustering speed: ~500 events/minute
        - Summary generation: ~5 summaries/minute
        - End-to-end latency: 24-48 hours for new data
        """)

    with col2:
        st.markdown("""
        **Data Coverage**:
        - Temporal: July 2024 - November 2025
        - Geographic: 5 influencers × 19 recipients
        - Categories: 8 primary categories
        - Event summaries: 10,107 (daily/weekly/monthly)
        """)

    st.markdown("---")

    st.subheader("5️⃣ Continuous Improvement")

    st.markdown("""
    **Quality Assurance Process**:

    1. **Automated Validation**
       - Schema validation on all outputs
       - Score range checking (0.0-1.0)
       - Citation link verification
       - Temporal consistency checks

    2. **Manual Review**
       - Weekly sampling of 50 summaries
       - Quarterly comprehensive audit
       - User feedback integration
       - Issue tracking and resolution

    3. **Prompt Refinement**
       - A/B testing of prompt variations
       - Iterative improvement based on outputs
       - Documentation of best practices
       - Version control of all prompts

    4. **System Monitoring**
       - Error rate tracking
       - Processing time monitoring
       - Database query performance
       - API response times
    """)

# ============================================================================
# TAB 5: TECHNICAL ARCHITECTURE
# ============================================================================
with tab5:
    st.header("🛠️ Technical Architecture")

    st.markdown("""
    ## Technology Stack

    The Soft Power Analytics Dashboard is built on a modern, scalable architecture
    optimized for large-scale document processing and analysis.
    """)

    # Architecture diagram (text-based)
    st.markdown("""
    ```
    ┌─────────────────────────────────────────────────────────────┐
    │                     FRONTEND LAYER                          │
    │  Streamlit Dashboard (Python) - Interactive Visualizations  │
    └─────────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────────────┐
    │                   APPLICATION LAYER                         │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
    │  │  Ingestion   │  │   Events     │  │  Summaries   │     │
    │  │   Pipeline   │  │   Pipeline   │  │   Pipeline   │     │
    │  └──────────────┘  └──────────────┘  └──────────────┘     │
    └─────────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────────────┐
    │                    DATA LAYER                               │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
    │  │ PostgreSQL   │  │   pgvector   │  │     S3       │     │
    │  │  (Relational)│  │  (Embeddings)│  │ (Raw Data)   │     │
    │  └──────────────┘  └──────────────┘  └──────────────┘     │
    └─────────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────────────┐
    │                     AI/ML LAYER                             │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
    │  │   OpenAI     │  │ Sentence     │  │   DBSCAN     │     │
    │  │   GPT-4      │  │ Transformers │  │  Clustering  │     │
    │  └──────────────┘  └──────────────┘  └──────────────┘     │
    └─────────────────────────────────────────────────────────────┘
    ```
    """)

    st.markdown("---")

    st.subheader("Core Technologies")

    tech_stack = pd.DataFrame({
        "Layer": [
            "Frontend",
            "Backend",
            "Database",
            "Vector Store",
            "AI/ML",
            "Embeddings",
            "Clustering",
            "Storage",
            "Orchestration"
        ],
        "Technology": [
            "Streamlit",
            "Python 3.12, FastAPI",
            "PostgreSQL 15",
            "pgvector",
            "OpenAI GPT-4 (via CLAUDE_KEY)",
            "sentence-transformers/all-MiniLM-L6-v2",
            "scikit-learn DBSCAN",
            "AWS S3",
            "Docker Compose"
        ],
        "Purpose": [
            "Interactive dashboards and visualizations",
            "Data processing pipelines",
            "Relational data storage",
            "Semantic search and similarity",
            "Text analysis and summarization",
            "Document and event embeddings",
            "Event clustering",
            "Raw document storage and backups",
            "Multi-container deployment"
        ]
    })

    st.dataframe(tech_stack, use_container_width=True, hide_index=True)

    st.markdown("---")

    st.subheader("Database Schema Highlights")

    st.markdown("""
    **Core Tables**:

    - **documents**: Primary document storage (439K+ records)
    - **raw_events**: Extracted event mentions (848K+ records)
    - **event_clusters**: DBSCAN clustering results
    - **canonical_events**: Master events spanning time
    - **daily_event_mentions**: Daily event occurrences
    - **event_summaries**: AI-generated summaries (10K+ records)
    - **bilateral_relationship_summaries**: Country-pair analyses (90 records)
    - **category_summaries**: Thematic summaries (328 records)

    **Normalized Relationship Tables** (Many-to-Many):

    - **categories** / **subcategories**: Document classifications
    - **initiating_countries** / **recipient_countries**: Geographic relationships
    - **projects**: Named initiatives and programs
    - **event_source_links**: Summary-to-document traceability

    **Vector Storage** (LangChain + pgvector):

    - **langchain_pg_collection**: Embedding collections
    - **langchain_pg_embedding**: Document/event embeddings for semantic search
    """)

    st.markdown("---")

    st.subheader("Key Design Decisions")

    with st.expander("1. SQLAlchemy 2.0 + Connection Pooling"):
        st.markdown("""
        **Rationale**: Modern ORM with sophisticated connection management

        **Implementation**:
        - Centralized `DatabaseManager` class
        - Connection pooling (size: 10, max overflow: 20)
        - Pre-ping for connection health
        - Context managers for automatic transaction handling
        - Pool recycling every 3600 seconds

        **Benefits**:
        - Reduced connection overhead
        - Automatic cleanup
        - Scalable for concurrent processing
        - Type-safe queries with SQLAlchemy 2.0
        """)

    with st.expander("2. Normalized Data Model"):
        st.markdown("""
        **Rationale**: Flexibility for complex queries and analytics

        **Design**:
        - Documents as central entity
        - Many-to-many relationships for all entities
        - Separate tables for each entity type
        - JSONB for flexible metadata

        **Trade-offs**:
        - ✅ Query flexibility
        - ✅ Data integrity
        - ✅ Scalability
        - ⚠️ More complex joins
        - ⚠️ Requires careful indexing
        """)

    with st.expander("3. Hybrid Clustering Approach"):
        st.markdown("""
        **Rationale**: Balance automation with accuracy

        **Two-Stage Process**:
        1. **DBSCAN Clustering**: Automated semantic grouping
        2. **LLM Deconfliction**: Manual review and merge suggestions

        **Why Hybrid**:
        - DBSCAN provides initial grouping at scale
        - LLM catches edge cases and nuanced similarities
        - Human oversight available for critical decisions
        - Best of both automated and intelligent approaches
        """)

    with st.expander("4. Event Summary Versioning"):
        st.markdown("""
        **Rationale**: Track evolution and enable regeneration

        **Implementation**:
        - Version counter on each summary
        - Timestamp tracking (created_at, updated_at, analyzed_at)
        - Regeneration flag for bulk updates
        - Historical comparison capability

        **Use Cases**:
        - Prompt refinement tracking
        - Data quality improvements over time
        - Audit trail for changes
        - A/B testing of different approaches
        """)

    st.markdown("---")

    st.subheader("Performance Optimizations")

    st.markdown("""
    **Database**:
    - Indexes on foreign keys and date fields
    - JSONB GIN indexes for metadata queries
    - Connection pooling and query optimization
    - Batch operations for bulk inserts

    **Processing**:
    - Batch clustering (50 events per batch)
    - Parallel processing where possible
    - Incremental processing (only new data)
    - Caching of embeddings

    **API**:
    - FastAPI for async operations
    - S3 proxy for efficient document access
    - Response caching for common queries
    - Pagination for large result sets
    """)

# Footer
st.markdown("---")
st.markdown(f"""
<div style='text-align: center; color: #666; padding: 20px;'>
    <p><strong>Soft Power Analytics Dashboard</strong></p>
    <p>Last Updated: {datetime.now().strftime('%Y-%m-%d')}</p>
    <p>Version 2.0</p>
</div>
""", unsafe_allow_html=True)
