# Leveraging Generative AI for Soft Power Analytics at Scale

## A Technical White Paper on Automating International Relations Analysis

---

**Author:** Matt Morris, Data Scientist

**Version:** 3.0

**Date:** May 2026

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Introduction and Background](#introduction-and-background)
3. [Technical Approach](#technical-approach)
4. [Model Evaluation and Performance](#model-evaluation-and-performance)
5. [System Architecture](#system-architecture)
6. [Prompt Engineering](#prompt-engineering)
7. [Event Processing Pipeline](#event-processing-pipeline)
8. [Entity and Relationship Extraction](#entity-and-relationship-extraction)
9. [Agentic RAG System](#agentic-rag-system)
10. [Interactive Visualization](#interactive-visualization)
11. [Alerting and Notifications](#alerting-and-notifications)
12. [Competing Influence Analysis](#competing-influence-analysis)
13. [Research Projects](#research-projects)
14. [Report Generation and Export](#report-generation-and-export)
15. [Techniques and Lessons Learned](#techniques-and-lessons-learned)
16. [Knowledge Distillation](#knowledge-distillation)
17. [Limitations and Future Directions](#limitations-and-future-directions)
18. [Conclusion](#conclusion)

---

## Executive Summary

This white paper presents a comprehensive framework for automating the analysis of soft power activities using Generative AI (GAI). The project aims to identify and categorize articles discussing soft power activities conducted by hard target countries towards Middle Eastern nations. Initially, a custom supervised topic model was planned, but advancements in generative AI models offered a more efficient solution.

Evaluations demonstrated that GAI models not only excelled in categorizing articles by soft power topics but also performed Named Entity Recognition (NER) tasks effectively. The decreasing costs of GAI made it the most timely and cost-effective approach for the project. With the more advanced capabilities offered by GAI, the project expanded its scope through innovative prompt engineering to not only categorize content, but also:

- Identify initiating and recipient countries of soft power interactions
- Extract specific project details including monetary values
- Determine geocoordinates for geographic visualization
- Track and consolidate events across large document corpora
- Generate automated summaries and insights
- **Extract entities and relationships** to build a network graph of actors involved in soft power transactions
- **Provide conversational access** to the data through an agentic RAG (Retrieval-Augmented Generation) interface
- **Visualize entity networks** through interactive graph visualizations
- **Alert analysts** to significant changes via configurable notification rules
- **Compare competing influence** across multiple countries in a single view
- **Support research workflows** with document collection and project-scoped analysis
- **Generate publication-ready reports** with Word document export

The black-box nature of GAI inference poses an ongoing risk that this project mitigates through periodic evaluations of GAI outputs to monitor performance, with exploration of training student models using GAI outputs as a contingency.

---

## Introduction and Background

### Project Origins

This project originated two and a half years ago as a follow-on to an earlier effort conducted during the COVID-19 pandemic. The initial project produced a product that mapped soft power investments by hard target countries toward Middle Eastern nations. While the outputs provided analysts with valuable insights into the reach of foreign influence activities, the process relied heavily on manual review and annotation. Analysts were responsible for categorizing articles, identifying the initiating and recipient countries, and labeling the relevant domains of soft power influence.

### The Case for Automation

This manual approach quickly revealed opportunities for automation. The repetitive and structured nature of categorization, country identification, and schema application made these tasks well-suited for natural language processing (NLP) techniques.

Initially, the plan was to employ traditional NLP methods and supervised training pipelines. The approach envisioned the development of a custom dataset through human annotation, followed by training a classification model to recognize soft power engagements according to a predefined schema. While this strategy was sound in principle, it carried significant costs and risks:

- The annotation process would have required thousands of labeled examples across multiple categories and subcategories
- The resulting model would likely need frequent retraining to adapt to evolving analytic requirements
- Time and resource investments would be substantial

### The Generative AI Pivot

At the time, ChatGPT-3.5 represented the state of the art in generative modeling. Early testing demonstrated strong potential but also revealed significant inconsistencies in outputs, along with high token costs that made scaling prohibitively expensive. This forced a critical decision point: whether to invest the project's limited resources in building annotated datasets and custom classifiers, or to accept the token costs and bet on future improvements in generative model performance.

Initial prompt engineering experiments proved decisive. With carefully structured instructions, ChatGPT-3.5 began closing the performance gap on fundamental tasks such as category classification and entity extraction. These early gains suggested that generative AI could outperform traditional NLP pipelines over the long term, particularly as newer models were released.

**The release of GPT-4 validated this decision.** Its dramatic increase in accuracy, consistency, and ability to follow complex prompt structures demonstrated that generative AI could meet the project's technical requirements far more effectively than traditional approaches.

### Defining Soft Power

Soft power is the ability of a country to shape the preferences and behaviors of other nations through appeal and attraction rather than coercion or payment. This influence is exerted through:

- Cultural diplomacy
- Values and policies
- Political ideals
- Educational exchanges
- Media and communications
- Economic partnerships

Soft power aims to build positive relationships and international cooperation by enhancing a country's reputation and credibility globally.

---

## Technical Approach

### Approach Philosophy

The project assessed the feasibility of using pretrained models through a phased evaluation:

1. **Zero-shot classification** and standard entity extraction models
2. **GAI models** such as GPT-3.5, GPT-4, Llama2, and Llama3
3. **Custom classification models** (contingency if other approaches proved insufficient)

### Comparative Analysis: Traditional ML vs. GAI

| Factor | Supervised/Trained ML Models | Prompt-Based GAI |
|--------|------------------------------|------------------|
| **Build Time** | 6+ months | 1 hour |
| **Build Cost** | $10,000s | $1s |
| **Run Cost** | $0 | $100s (decreasing quickly) |
| **Modification Agility** | Delayed, rigid | Immediate, flexible |
| **Performance** | Good for specific task | Excellent for many tasks |
| **Use Difficulty** | Data engineer/scientist required | Anyone who can type |

### GAI Capability Spectrum

The risk of inaccurate output and adverse effects of model bias increases as tasks move from factual to analytic:

**FACTUAL (Lower Risk):**
- Sentiment Tagging
- Thematic Categorization
- Quote Extraction

**MODERATE:**
- Salience Tagging
- Text Summary
- Event Tagging

**ANALYTIC (Higher Risk):**
- Findings Composition
- Prediction/Forecasting
- Intent Analysis

The Soft Power Project GAI prompts operate primarily in the factual to moderate range, focusing on categorization, extraction, and summarization tasks.

---

## Model Evaluation and Performance

### Proof-of-Concept Testing

The Global Chinese Development & Finance (GCDF) dataset provided the first benchmark for evaluation. Although the dataset was limited—containing only positive samples and summarized descriptions rather than full articles—it offered a controlled testbed for measuring whether GAI models could correctly identify soft power activities and apply structured labeling schemas.

### Models Evaluated

Multiple models were tested, including:
- GPT-3.5
- GPT-4
- LLaMA-2 (70B and 8B)
- LLaMA-3 (8B and 70B)
- Facebook's BART Large MNLI (zero-shot classification baseline)

Each model was evaluated on:
- Identifying whether a text described a soft power event (salience)
- Classifying events into categories and subcategories
- Extracting initiating and recipient countries
- Maintaining output consistency with structured JSON prompts

### Performance Results

#### Salience Detection

| Model | Salience Rate | Assessment |
|-------|---------------|------------|
| GPT-4 | 20-30% | Most conservative and reliable |
| GPT-3.5 | ~56% | Tended toward over-inclusion |
| LLaMA models | Variable | Closer to GPT-3.5 in permissiveness |
| Zero-shot (MNLI) | Inconsistent | Often misapplied categories |

#### Categorization and Sub-Categorization

- **GPT-4** achieved an F1 score of **0.865** with high precision (0.94) in mapping texts to soft power categories
- GPT-4 successfully applied detailed schemas, including sector-specific subcategories, without retraining
- GPT-3.5 and LLaMA models performed moderately well but were more sensitive to prompt errors and less consistent with output formatting

#### Entity Extraction

- All models performed near-perfectly in identifying initiating and recipient countries
- Errors occurred primarily when source text used regional rather than country-level references
- Monetary values and project names were extracted with high accuracy when explicitly present in text

#### Format Compliance

- GPT-4 consistently adhered to structured output formats (JSON), critical for downstream post-processing
- GPT-3.5 and LLaMA models occasionally drifted, omitting required fields or introducing narrative text despite prompt constraints

### Human vs. Model Labeling

Two labeling exercises were conducted to test alignment between human annotators and GAI outputs:

**Round 1:** Three annotators collaboratively labeled 100 documents. Results diverged significantly from model labels, with humans adopting a narrower interpretation of soft power. Analysts later reviewing disagreements often sided with the models, suggesting annotators under-flagged relevant cases.

**Round 2:** A separate set of 200 documents was labeled independently by three annotators. Divergence persisted, confirming variability in human interpretation. Despite this, models captured nearly 100% of human-identified true positives, with disagreements concentrated in borderline or "grey area" cases.

### Key Findings

- LLMs can reliably apply custom schemas without retraining
- GPT-4 outperformed other models in precision, consistency, and adherence to formatting
- Human annotators exhibited high variance in labeling, complicating efforts to establish definitive ground truth
- Analysts often judged model outputs as more accurate than first-pass human labels

---

## System Architecture

### High-Level Data Flow

```
DS&R Storage → Collections → GAI Salience & Extraction → Post-Processing →
Soft Power DB (pgvector) → Publication (Dashboard, Reports, Agent UI)
```

### Core Components

#### Data Layer
- **Document Metadata**: Source information and timestamps
- **GAI Extraction Data**: Structured outputs from analysis prompts
- **Embeddings**: Vector representations using all-MiniLM-L6-v2
  - Distilled Text Embeddings
  - Event Embeddings
  - Project Embeddings

#### Processing Layer
- **Activity Aggregation**: Document and GAI extractions parsed and grouped
- **Unique Event & Project Identification**: Clustering and deduplication
- **Summary Generation**: GAI-powered summarization at multiple temporal scales

#### Output Layer
- **Soft Power Database**: PostgreSQL with pgvector extension
- **Analytics Dashboard**: Streamlit-based interactive visualization
- **Summary Publications**: Weekly/Monthly overviews distributed to community
- **Soft Power Agent UI**: Dynamic interactions with data via prompts

### Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | SQLAlchemy 2.0, FastAPI |
| Database | PostgreSQL + pgvector |
| Frontend | Streamlit |
| AI/ML | OpenAI GPT models, sentence-transformers, HDBSCAN |
| Infrastructure | Docker Compose, Alembic migrations |
| Storage | AWS S3 |
| Embeddings | all-MiniLM-L6-v2 (open-source) |

---

## Prompt Engineering

### Verbose vs. Concise Prompts

**Concise prompts** tended to overgeneralize, particularly in salience detection. GPT-3.5 frequently labeled 50-60% of articles as soft power relevant when given short instructions.

**Verbose prompts**, which included detailed definitions of soft power, explicit schema rules, and examples of acceptable JSON outputs, significantly reduced false positives. GPT-4 in particular responded well to structured, multi-step instructions, demonstrating salience rates more in line with analyst expectations (20-30%).

### Structured Output Enforcement

Prompts that constrained models to return JSON outputs proved critical for pipeline integration. Including an explicit "ONLY output JSON" instruction and providing an example template greatly improved compliance across all models.

### Expanded Task Capabilities

Beyond salience and categorization, prompt engineering enabled additional tasks:

| Task | Description |
|------|-------------|
| **Summarization** | Distilled text retaining only soft power-relevant content |
| **Geolocation** | Inferring latitude/longitude when explicit coordinates were missing |
| **Monetary Extraction** | Normalizing funding amounts into USD |
| **Event Naming** | Creating descriptive titles for event-level tracking |

### Evolution with Newer Models

As newer models such as GPT-4o became available, instruction-following proved less of a bottleneck. The primary challenge shifted from writing detailed instructions to **context engineering**:

- **Context Window Management**: Efficiently chunking and distilling large corpora
- **Information Density**: Maximizing signal within constrained token budgets
- **Schema Alignment**: Designing context presentations that emphasized relationships

### Core Prompts

The system employs a series of specialized prompts:

1. **Salience Prompt**: Determines if text represents soft power activity
2. **Extraction Prompt**: Full categorization, entity extraction, and summarization
3. **Event Consolidation Prompt**: Groups related articles into unique events
4. **Unique Event Prompt**: Consolidates events across the corpus
5. **Event Update Prompt**: Identifies updates to existing events
6. **Final Event Summary Prompt**: Generates comprehensive event summaries
7. **Weekly/Monthly Summary Prompt**: Creates periodic analytical reports

---

## Event Processing Pipeline

### Workflow Steps

#### Step 1: Salience Run
NE_AUTO holdings are queried and results are run through GPT-3.5 turbo on ingest to detect articles relevant to the soft power project.

#### Step 2: Extraction Run
Salient articles are run through an extraction prompt using GPT-4o which:
- Categorizes articles according to the soft power schema
- Creates distilled versions containing only relevant content
- Identifies initiating and recipient countries
- Determines location (latitude-longitude)

#### Step 3: Unique Event Identification
Processing the entirety of distilled articles exceeds both context and output limits of current GAI models (128K token input, 10K token output). The solution:

1. Cluster corpus by cosine similarity into chunks of ~50 articles
2. Run each chunk through GAI to output event groupings
3. Assign Event IDs (EIDs) to consolidated articles

#### Step 4: Event Aggregation
To account for duplicative events across separate chunks:
- Another round of clustering and GAI aggregation on event objects
- Consolidated events assigned Soft Power IDs (SPIDs)
- SPIDs run through GAI for overarching event-name and event-summary

#### Step 5: Event Tracking
For subsequent data batches:
- Steps 1-3 repeated on new batch
- New events compared to existing SPIDs
- Updated SPIDs incorporate new information
- Truly new events processed through Step 4

#### Step 6: Findings by Country
SPIDs filtered by country and run through GAI to build weekly summaries with:
- Specific findings with source citations
- Hyperlinks to original documents via ATOM IDs

#### Step 7: Visualization
Dashboard enables dynamic manipulation of soft power data from country level down to individual articles.

#### Step 8: SME Review
Human intervention point where analysts can:
- Flag high-priority SPIDs for detailed tracking
- Split over-consolidated SPIDs
- Combine SPIDs that should be tracked as single events

### Deduplication Strategies

**Batch Deduplication (Deferred):**
- Occurs after weeks/months of data collected
- Events evaluated in context of larger dataset
- Minimizes fragmentation
- *Drawback*: Delays analyst access to consolidated events

**Real-Time Deduplication (Streaming):**
- Occurs as new articles are ingested
- Immediate comparison against existing SPIDs
- Near-instant enrichment of summaries
- *Drawback*: Risks over-consolidation due to limited historical context

---

## Entity and Relationship Extraction

Building on the foundational document categorization and event extraction capabilities, the system expanded to include comprehensive **entity and relationship extraction**. This enables the construction of a knowledge graph representing the actors, organizations, and connections underlying soft power activities.

### Motivation

While event-level analysis provides insights into *what* happened, understanding *who* is involved and *how they interact* requires a deeper level of extraction. Entity and relationship extraction enables:

- **Network Analysis**: Identifying key actors and their influence patterns
- **Connection Discovery**: Finding hidden relationships between entities across documents
- **Temporal Tracking**: Monitoring how entity involvement evolves over time
- **Financial Flow Mapping**: Tracing monetary relationships between organizations

### Entity Taxonomy

The system extracts 11 types of entities:

| Entity Type | Description | Examples |
|-------------|-------------|----------|
| **PERSON** | Individual officials, executives, diplomats | Wang Yi, Crown Prince Mohammed bin Salman |
| **GOVERNMENT_AGENCY** | Ministries, departments, embassies | Ministry of Foreign Affairs, USAID |
| **STATE_OWNED_ENTERPRISE** | Government-controlled companies | China National Petroleum Corporation, Saudi Aramco |
| **PRIVATE_COMPANY** | Privately owned businesses | Huawei, Siemens |
| **MULTILATERAL_ORG** | International bodies | UN, BRICS, SCO, African Union |
| **NGO** | Non-governmental organizations | Red Cross, Doctors Without Borders |
| **EDUCATIONAL_INSTITUTION** | Universities, research institutes | Confucius Institute, Cairo University |
| **FINANCIAL_INSTITUTION** | Banks, investment funds | China Development Bank, World Bank |
| **MILITARY_UNIT** | Armed forces, defense ministries | People's Liberation Army |
| **MEDIA_ORGANIZATION** | News outlets, broadcasters | CGTN, Al Jazeera |
| **RELIGIOUS_ORGANIZATION** | Religious bodies | Al-Azhar University |

### Role Labels (25 Types)

Each entity is assigned a role describing their function in the soft power transaction:

**Diplomatic Roles:**
- HEAD_OF_STATE, DIPLOMAT, NEGOTIATOR, GOVERNMENT_OFFICIAL, LEGISLATOR

**Economic Roles:**
- FINANCIER, INVESTOR, CONTRACTOR, DEVELOPER, TRADE_PARTNER, OPERATOR

**Military Roles:**
- MILITARY_OFFICIAL, DEFENSE_SUPPLIER, TRAINER

**Cultural/Social Roles:**
- CULTURAL_INSTITUTION, EDUCATOR, MEDIA_ENTITY, RELIGIOUS_ENTITY, HUMANITARIAN

**Transaction-Specific Roles:**
- BENEFICIARY, HOST, LOCAL_PARTNER, FACILITATOR, SIGNATORY

### Topic Labels (30 Types)

Entities are tagged with the domain of influence they operate in:

**Economic Topics:**
- INFRASTRUCTURE, ENERGY, FINANCE, TRADE, TECHNOLOGY, TELECOMMUNICATIONS, TRANSPORTATION, AGRICULTURE, MINING, MANUFACTURING

**Diplomatic Topics:**
- BILATERAL_RELATIONS, MULTILATERAL_FORUMS, CONFLICT_MEDIATION, TREATY_NEGOTIATION

**Military Topics:**
- ARMS_TRADE, MILITARY_COOPERATION, DEFENSE_TRAINING, SECURITY_ASSISTANCE

**Social Topics:**
- EDUCATION, HEALTHCARE, CULTURE, MEDIA, RELIGION, HUMANITARIAN_AID, TOURISM

### Relationship Types (14 Types)

The system captures directed relationships between entities:

| Relationship Type | Description |
|-------------------|-------------|
| **FUNDS** | Provides money/financing to |
| **INVESTS_IN** | Makes equity investment in |
| **CONTRACTS_WITH** | Has contract/agreement with |
| **PARTNERS_WITH** | Forms partnership/JV with |
| **SIGNS_AGREEMENT** | Signs formal agreement with |
| **MEETS_WITH** | Has meeting/diplomatic encounter with |
| **EMPLOYS** | Has employment relationship with |
| **OWNS** | Has ownership stake in |
| **REPRESENTS** | Officially represents (person → organization) |
| **HOSTS** | Hosts event/visit for |
| **TRAINS** | Provides training to |
| **SUPPLIES** | Provides goods/equipment to |
| **MEDIATES** | Mediates between parties |
| **ANNOUNCES** | Makes public announcement about |

### Extraction Pipeline

The entity extraction pipeline operates as follows:

```
Documents → Entity Extraction (GPT-4o-mini) → Validation →
Deduplication → Database Storage → Relationship Aggregation
```

**Step 1: Document Selection**
- Query documents with `salience_bool = true` and valid `distilled_text`
- Filter by country, date range, or specific document IDs
- Automatically skip already-processed documents (incremental processing)

**Step 2: LLM Extraction**
- Format prompt with document context (initiating/recipient country, category)
- Call GPT-4o-mini to extract entities and relationships
- Parse structured JSON output

**Step 3: Validation**
- Validate entity types against defined taxonomy
- Validate role labels and topic labels
- Validate relationship types and ensure source/target entities exist
- Log warnings for invalid or missing fields

**Step 4: Deduplication**
- Match entities by canonical name (case-insensitive)
- Match by aliases (stored as array)
- For persons, match by name + country combination
- Use `ON CONFLICT DO NOTHING` for document-entity pairs

**Step 5: Relationship Aggregation**
- Aggregate relationship observations across documents
- Track `observation_count` and `document_count`
- Maintain `first_observed` and `last_observed` dates
- Sum `total_value_usd` for financial relationships
- Store sample evidence (up to 10 document IDs per relationship)

### Database Schema

The entity system uses three core tables:

**`entities`** - Canonical, deduplicated entities
- UUID primary key
- `canonical_name`, `entity_type`, `country`
- `aliases` (array for deduplication)
- `mention_count`, `first_seen_date`, `last_seen_date`
- `primary_topics` (JSONB) - aggregated topic usage
- `primary_roles` (JSONB) - aggregated role usage

**`document_entities`** - Links documents to entities
- Foreign keys to `documents` and `entities`
- `side` (initiating/recipient/third_party)
- `role_label`, `topic_label`, `role_description`
- `confidence` score and `extraction_method`

**`entity_relationships`** - Aggregated relationships
- Source and target entity foreign keys
- `relationship_type`
- `observation_count`, `document_count`
- `total_value_usd` (for financial relationships)
- `sample_doc_ids` (array of evidence)

### Parallel Processing

The extraction pipeline supports parallel processing for improved throughput:

```bash
# Sequential processing (default)
python services/pipeline/entities/entity_extraction.py --country China --limit 100

# Parallel processing with 4 workers
python services/pipeline/entities/entity_extraction.py --country China --limit 100 --parallel-workers 4

# Force reprocess already-extracted documents
python services/pipeline/entities/entity_extraction.py --country China --reprocess
```

### Entity Resolution

A separate entity resolution prompt handles deduplication of extracted entities:

- Identifies abbreviated vs. full names (CNPC vs. China National Petroleum Corporation)
- Matches with/without titles (President Xi vs. Xi Jinping)
- Handles transliteration variations
- Groups merge candidates with confidence scores

---

## Agentic RAG System

To enable dynamic, conversational access to the soft power data, the project developed an **Agentic RAG (Retrieval-Augmented Generation)** system. This system combines semantic search with structured analytics tools, allowing users to ask natural language questions and receive data-driven answers.

### Architecture Overview

The agentic system follows a three-step process:

```
User Query → Tool Selection (LLM) → Tool Execution → Response Generation (LLM)
```

**Step 1: Tool Selection**
- The LLM analyzes the user's query to determine which tools would be most helpful
- Returns a JSON array of tool names to invoke

**Step 2: Tool Execution**
- Selected tools are executed with appropriate parameters
- Results are aggregated from multiple tools when needed

**Step 3: Response Generation**
- Tool results are formatted as context for the LLM
- The LLM synthesizes a coherent, factual response
- Sources are tracked for attribution

### Available Tools

The agent has access to seven specialized tools:

| Tool | Purpose | Use Cases |
|------|---------|-----------|
| **search_events** | Semantic search across event summaries | "What events involve China and Africa?" |
| **search_documents** | Search source documents | "Find detailed information about BRI projects" |
| **get_country_stats** | Activity statistics for a country | "How active is Russia in Latin America?" |
| **get_bilateral_summary** | Relationship summary between countries | "What is China's relationship with Egypt?" |
| **get_trending_events** | Currently trending events | "What are the latest soft power activities?" |
| **get_category_trends** | Category trend analysis | "How has economic cooperation evolved?" |
| **compare_countries** | Compare activity across countries | "Compare China and Russia's influence" |

### Query Engine

The RAG query engine provides semantic search capabilities using vector embeddings:

**Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional)

**Vector Stores:**
- `chunk_store` - Document chunk embeddings
- `summary_store` - Event summary embeddings
- `daily_store`, `weekly_store`, `monthly_store`, `yearly_store` - Period-specific stores

**Search Capabilities:**
- Similarity search with relevance scores
- Filtering by country, category, date range
- Deduplication of document results
- Hybrid search across events and documents

### Conversation Management

The agent maintains conversation history for context-aware responses:

```python
class SoftPowerAgent:
    def __init__(self):
        self.query_engine = QueryEngine()
        self.conversation_history = []
        self.tools = {
            'search_events': self._search_events,
            'search_documents': self._search_documents,
            # ... additional tools
        }
```

Each conversation turn records:
- User query with timestamp
- Assistant response with timestamp
- Sources used for the response

### System Prompt

The agent operates under a specialized system prompt that defines its role:

> You are an expert analyst specializing in soft power and international relations. You have access to a comprehensive database of soft power activities, including event summaries, source documents, bilateral relationship summaries, and activity statistics and trends.

Guidelines include:
- Always use tools to gather data before answering
- Combine multiple tool results for comprehensive answers
- Be specific with dates, countries, and categories
- Format responses clearly with sections and bullet points
- Include relevant metrics and statistics

### Analytics Tools

Beyond semantic search, the agent can invoke structured analytics:

**Country Activity Stats:**
```python
get_country_activity_stats(country, start_date, end_date)
# Returns: Events by type, top categories, top recipients
```

**Bilateral Relationship Summary:**
```python
get_bilateral_relationship_summary(initiating_country, recipient_country)
# Returns: Relationship metrics, key events, document counts
```

**Trending Events:**
```python
get_trending_events(country, period_type, limit, days)
# Returns: Events ranked by document count/recency
```

**Category Trends:**
```python
get_category_trends(category, country, date_range)
# Returns: Monthly activity, top events, trend direction
```

**Country Comparison:**
```python
compare_countries(countries, date_range)
# Returns: Comparative statistics across selected countries
```

### Layered RAG Context Architecture

A key enhancement to the RAG system is the **three-layer context injection** that provides richer, more accurate responses by combining multiple information sources:

```
User Query → Layer 1: Strategic Context (SQL) →
             Layer 2: Event Discovery (Semantic) →
             Layer 3: Document Chunks (Semantic) →
             LLM Response Generation
```

**Layer 1: Strategic Context (Deterministic SQL)**

Pre-analyzed strategic summaries retrieved via direct database lookup:
- **Bilateral Relationship Summaries**: Overview, key themes, trend analysis for country pairs
- **Country-Category Summaries**: Aggregated insights per influencer-category combination
- **Period Summaries**: Time-based analytical products

```python
def gather_strategic_context(influencer, recipient, category) -> str:
    # SQL lookup of BilateralRelationshipSummary
    # SQL lookup of CountryCategorySummary
    # SQL lookup of PeriodSummary
    return formatted_strategic_context
```

**Layer 2: Event Summary Discovery (Semantic Search)**

Semantic search across event summary embeddings:
- Daily, weekly, and monthly event collections
- Filtered by inferred or explicit country/category
- Returns top-k most relevant event summaries

**Layer 3: Document Chunk Search (Semantic Search)**

Traditional RAG retrieval over source documents:
- Chunked document embeddings in pgvector
- Entity-aware boosting for matched entities
- Deduplication to prevent redundant sources

**Benefits of Layered Context:**

| Layer | Source | Latency | Coverage |
|-------|--------|---------|----------|
| Strategic | SQL lookup | <50ms | Pre-analyzed summaries |
| Event | Semantic search | ~200ms | Consolidated events |
| Document | Semantic search | ~300ms | Raw source material |

This architecture ensures responses are grounded in both high-level analytical products and specific source evidence.

---

## Interactive Visualization

The system provides two primary user interfaces for interacting with soft power data: a **conversational chat interface** and an **entity network visualization**.

### Chat with Data Interface

The "Chat with Data" page provides a conversational interface powered by the agentic RAG system.

**Features:**
- Real-time chat with conversation history
- Sidebar filters for date range, initiating country, and recipient countries
- Query context enhancement (filters automatically added to queries)
- Source attribution with expandable details
- Example queries to guide users

**User Experience:**
1. User enters a natural language question
2. Active filters are automatically included in the query context
3. Agent processes query using tools and semantic search
4. Response displayed with markdown formatting
5. Sources shown in expandable section with relevance scores

**Example Queries:**
- "What recent events involve China and Africa?"
- "How has China's engagement with Latin America evolved?"
- "What is the relationship between China and Egypt?"
- "What cultural events has Turkey organized recently?"

**Filter Integration:**
```python
def build_filter_context():
    filters = st.session_state.filters
    context_parts = []

    if filters['start_date'] or filters['end_date']:
        context_parts.append(f"Date range: {filters['start_date']} to {filters['end_date']}")

    if filters['initiating_country']:
        context_parts.append(f"Initiating country: {filters['initiating_country']}")

    if filters['recipient_countries']:
        recipients = ", ".join(filters['recipient_countries'])
        context_parts.append(f"Recipient countries: {recipients}")

    return "ACTIVE FILTERS: " + "; ".join(context_parts)
```

### Entity Network Visualization

The "Entity Network" page provides an interactive graph visualization of entities and their relationships using **pyvis**.

**Visual Encoding:**
- **Node Size**: Based on mention count (more mentions = larger node)
- **Node Color**: Based on entity type (11 distinct colors)
- **Edge Width**: Based on observation count
- **Edge Color**: Based on relationship type
- **Arrow Direction**: Shows relationship direction (source → target)

**Entity Type Colors:**

| Entity Type | Color |
|-------------|-------|
| PERSON | Red (#FF6B6B) |
| GOVERNMENT_AGENCY | Teal (#4ECDC4) |
| STATE_OWNED_ENTERPRISE | Blue (#45B7D1) |
| PRIVATE_COMPANY | Orange (#FFA07A) |
| MULTILATERAL_ORG | Green (#98D8C8) |
| FINANCIAL_INSTITUTION | Light Green (#6BCB77) |
| EDUCATIONAL_INSTITUTION | Yellow (#FFD93D) |
| NGO | Purple (#C7CEEA) |
| MILITARY_UNIT | Pink (#FF6B9D) |
| MEDIA_ORGANIZATION | Violet (#C780E8) |
| RELIGIOUS_ORGANIZATION | Brown (#DDA15E) |

**Relationship Type Colors:**

| Relationship Type | Color |
|-------------------|-------|
| FUNDS | Green |
| INVESTS_IN | Teal |
| PARTNERS_WITH | Yellow |
| MEETS_WITH | Red |
| REPRESENTS | Purple |
| SUPPLIES | Orange |
| CONTRACTS_WITH | Blue |
| SIGNS_AGREEMENT | Light Green |

**Interactive Features:**
- **Hover**: View entity/relationship details in tooltip
- **Click and Drag**: Reposition nodes
- **Scroll**: Zoom in/out
- **Click Node**: Highlight connected edges
- **Physics Toggle**: Enable/disable force-directed layout

**Sidebar Filters:**
- Country filter (multi-select)
- Entity type filter
- Relationship type filter
- Minimum mention threshold (slider)
- Maximum entities to display (slider)
- Graph height adjustment
- Physics and label toggles

**Metrics Dashboard:**
- Total entities displayed
- Total relationships displayed
- Average connections per entity
- Entity type diversity count

**Top Entities Table:**
Shows the top 10 most connected entities with:
- Entity name
- Entity type
- Country affiliation
- Mention count
- Connection count

**Sample Data Mode:**
For demonstration purposes, the visualization includes sample data when no entities are present in the database, featuring 10 sample entities with realistic relationships (e.g., China Development Bank, Saudi Aramco, Wang Yi).

### Technical Implementation

The network visualization is generated dynamically:

```python
def create_network_graph(entities, relationships, height_px, physics, show_labels):
    net = Network(
        height=f"{height_px}px",
        width="100%",
        bgcolor="#1E1E1E",
        font_color="white",
        directed=True
    )

    # Configure physics for force-directed layout
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.3,
          "springLength": 150
        }
      }
    }
    """)

    # Add nodes with size/color based on entity attributes
    for entity in entities:
        size = 10 + (entity['mentions'] * 1.5)
        color = get_entity_color(entity['type'])
        net.add_node(entity['id'], label=entity['name'], size=size, color=color)

    # Add directed edges with tooltips
    for rel in relationships:
        width = 1 + (rel['count'] * 0.5)
        net.add_edge(rel['source'], rel['target'],
                     title=rel['type'], width=width,
                     arrows={'to': {'enabled': True}})

    return net.generate_html()
```

---

## Alerting and Notifications

The platform includes a comprehensive **alerting system** that enables analysts to receive proactive notifications when significant changes occur in the soft power landscape. This shifts the analyst workflow from reactive querying to proactive monitoring.

### Alert Condition Types

The system supports four types of configurable alert conditions:

| Condition Type | Description | Example Parameters |
|----------------|-------------|-------------------|
| **Materiality Spike** | Detects when materiality scores exceed baseline | `threshold_z: 2.0`, `window_days: 7`, `country: "China"` |
| **Volume Surge** | Alerts on unusual document volume | `threshold_z: 2.0`, `window_days: 7`, `country: "Russia"` |
| **New Entity** | Triggers when a new entity appears | `country: "China"`, `entity_type: "person"` |
| **New Event** | Alerts on new high-materiality events | `country: "Iran"`, `min_materiality: 3.0` |

### Notification Channels

Alerts can be delivered through multiple channels:

- **In-App (AlertBell)**: Visual notification indicator in the application header
- **Email**: Configurable email addresses for alert delivery
- **Slack**: Webhook integration for team notification channels

### Alert Severity Levels

| Severity | Use Case | Visual Indicator |
|----------|----------|------------------|
| **Info** | Routine changes worth noting | Blue |
| **Warning** | Significant changes requiring attention | Orange |
| **Critical** | Major developments requiring immediate review | Red |

### Alert Rule Configuration

Each alert rule specifies:

```python
class AlertRule:
    name: str                    # "China Military Activity Spike"
    condition_type: str          # "materiality_spike"
    condition_params: dict       # {"threshold_z": 2.0, "window_days": 7}
    channels: List[str]          # ["in_app", "slack"]
    channel_config: dict         # {"slack_webhook_url": "..."}
    severity: str                # "warning"
    cooldown_minutes: int        # 60 (prevent alert fatigue)
    is_enabled: bool             # True
```

### Background Evaluation

Alert rules are evaluated on a configurable schedule using **APScheduler**:

1. Background worker queries database for enabled rules
2. Each rule's condition is evaluated against current data
3. If triggered and cooldown has elapsed, alert is created
4. Notifications dispatched to configured channels
5. Alert history recorded for audit trail

### Alert History and Acknowledgment

All triggered alerts are stored in `AlertHistory` with:
- Timestamp and severity
- Title and detailed message
- Context data (what triggered the alert)
- Channels notified
- Acknowledgment status and timestamp

Analysts can acknowledge alerts to track review status and clear notification indicators.

---

## Competing Influence Analysis

A key analytical capability is the **Competing Influence Overlay**, which enables side-by-side comparison of multiple influencer countries' activities within a single recipient country.

### Purpose

Traditional analysis examines one influencer-recipient pair at a time. The Competing Influence view answers:
- How do China, Russia, Iran, Turkey, and the US compete for influence in Egypt?
- Which influencer dominates in which category?
- How have influence patterns shifted over time?

### Visualization Components

**1. Stacked Area Chart**

Shows document volume over time for all five influencers:
- X-axis: Time (monthly buckets)
- Y-axis: Document count
- Colors: Distinct color per influencer (China=red, Russia=blue, etc.)
- Interaction: Hover for exact values, click to filter

**2. Category Heatmap**

Matrix visualization showing activity intensity:

| Category | China | Iran | Russia | Turkey | US |
|----------|-------|------|--------|--------|-----|
| Economic | High | Low | Medium | Low | Medium |
| Military | Medium | Medium | High | Low | High |
| Social | High | Low | Low | Medium | Low |
| Diplomacy | High | Medium | High | Medium | High |

Cell color intensity based on document count, enabling quick pattern recognition.

**3. Per-Influencer Event Listing**

Expandable sections showing top events for each influencer:
- Event name and date range
- Document count and materiality score
- Category breakdown
- Click-through to event details

**4. RAG Comparative Assessment**

AI-generated analysis comparing influencer strategies:
- Streaming response generation
- Grounded in retrieved documents
- Source citations with relevance scores
- Exportable for reports

### Data Structure

```python
class CompetingInfluenceSummary:
    recipient: str                           # "Egypt"
    influencer_summary: List[InfluencerStats]  # Per-influencer metrics
    category_matrix: List[CategoryRow]        # Heatmap data
    monthly_trends: List[MonthlyData]         # Time series
    top_events: Dict[str, List[Event]]        # Events by influencer
```

### Recipient Countries

The Competing Influence view is available for all 18 recipient countries in the Middle East and North Africa region, with data filtered by the selected recipient.

---

## Research Projects

The **Research Projects** feature supports analyst workflows for collecting, organizing, and analyzing source documents across multiple queries.

### Motivation

Analysts often need to:
- Collect relevant documents across multiple search sessions
- Build a corpus for a specific research question
- Generate reports from curated sources only
- Share document collections with colleagues

Research Projects provide a structured way to accomplish these tasks.

### Project Workflow

```
Chat/Search → Find Relevant Document → Add to Project →
Repeat → Project-Scoped Analysis → Generate Report
```

**Step 1: Create Project**
- Name and description
- Status tracking (active/archived)
- User ownership

**Step 2: Collect Documents**
- From chat responses, click "Add to Project"
- From search results, select and add
- Metadata cached at collection time
- Source query recorded for context

**Step 3: Project-Scoped Chat**
- RAG queries restricted to project documents only
- Focused analysis without corpus noise
- Higher relevance for specific questions

**Step 4: Report Generation**
- Generate reports from project documents
- All citations from curated sources
- Export to Word document

### Database Schema

**`research_projects`** table:
```python
class ResearchProject:
    id: UUID
    user_id: UUID                # Owner
    name: str                    # "Iran Nuclear Analysis Q1 2026"
    description: Optional[str]
    status: ProjectStatus        # ACTIVE or ARCHIVED
    created_at: datetime
    updated_at: datetime
```

**`project_documents`** table:
```python
class ProjectDocument:
    id: UUID
    project_id: UUID             # Parent project
    doc_id: str                  # Reference to documents table
    # Cached metadata (snapshot at collection)
    title: str
    source_name: str
    date: date
    initiating_country: str
    recipient_country: str
    category: str
    excerpt: str
    # Context
    source_query: str            # Query that found this document
    notes: str                   # Analyst annotations
    added_at: datetime
```

### User Interface

**ProjectDrawer Component:**
- Side panel accessible from Research page
- List of user's projects with document counts
- Create new project
- View/manage project documents
- Delete or archive projects

**Document Collection:**
- "Add to Project" button on search results
- Project selector dropdown
- Optional notes field
- Confirmation feedback

---

## Report Generation and Export

The platform provides comprehensive **report generation** capabilities for creating publication-ready documents with LLM-generated narratives, metrics, and citations.

### Report Types

**1. Country Reports**
- Single influencer country analysis
- Configurable date range
- All categories or filtered
- Top events and trends

**2. Bilateral Reports**
- Specific influencer-recipient pair
- Relationship summary and trajectory
- Key events and actors
- Category breakdown

**3. Thematic Reports**
- Category-focused (e.g., "Military Cooperation")
- Cross-country comparisons
- Trend analysis

### Report Sections

Reports are generated with configurable sections:

| Section | Content | Toggle |
|---------|---------|--------|
| **Executive Summary** | AI-generated overview | Always included |
| **Events** | Top events with descriptions | Configurable |
| **Entities** | Key actors and organizations | Configurable |
| **Metrics** | Document counts, materiality scores | Configurable |
| **Persons** | Notable individuals mentioned | Configurable |
| **Citations** | Source documents with hyperlinks | Always included |

### LLM Narrative Generation

Each report section uses specialized prompts:

```python
def generate_event_narrative(event_data, citations) -> str:
    prompt = f"""
    Generate a concise analytical narrative for this soft power event.
    
    Event: {event_data['name']}
    Date Range: {event_data['start']} to {event_data['end']}
    Category: {event_data['category']}
    Materiality: {event_data['materiality_score']}
    
    Source excerpts:
    {formatted_citations}
    
    Write 2-3 sentences describing the significance and key actors.
    Include citation numbers [1], [2] where appropriate.
    """
    return gai(system_prompt, prompt, model="gpt-4o")
```

### Citation Management

All claims are traced to source documents:

```python
def build_hyperlink(doc_id: str, display_text: str) -> str:
    # Generates clickable link to source document
    return f"[{display_text}](/document/{doc_id})"
```

Citations include:
- Document title and source
- Publication date
- Relevance score
- Direct link to full text

### Word Document Export

Reports can be exported to Microsoft Word format (.docx):

**Template-Based Generation:**
- Professional formatting with headers and styles
- Table of contents generation
- Embedded metrics tables
- Formatted citation lists
- Section breaks and page numbers

**Export Options:**
- Full report or selected sections
- With or without source excerpts
- Reviewer validation copy (includes confidence scores)

### Materiality Scoring Enhancement

Report generation leverages improved materiality scoring with **10 granular anchors**:

| Score | Description | Dollar Threshold |
|-------|-------------|------------------|
| 1-2 | Routine diplomatic activity | < $1M |
| 3-4 | Notable but limited impact | $1M - $50M |
| 5-6 | Significant regional event | $50M - $500M |
| 7-8 | Major bilateral development | $500M - $5B |
| 9-10 | Strategic/transformative event | > $5B |

This prevents score clustering and provides better differentiation for report prioritization.

---

## Techniques and Lessons Learned

### Model Strategy & Cost Optimization

**Matched model to task:**
| Task | Model |
|------|-------|
| Salience filtering | GPT-4o-mini |
| Full extraction | GPT-4o |
| Deduplication, sourcing, clustering | GPT-4.1 |

**Open-source embeddings** (MiniLM-L6-v2) for chunking and retrieval significantly reduced token costs.

### Scalable High-Signal Artifacts

- Distilled texts into signal-only summaries for model efficiency
- Daily → Weekly → Monthly roll-ups provided scalable and traceable insights
- Used proxy identifiers to avoid token overflow from long UUIDs

### Output Structuring & Formatting

- Enforced JSON schemas for reliable machine-readable output
- Prompt precision mattered—quotation style, placeholder use (`<initiating_country>`)
- Embedding markdown metrics/charts in prompts boosted ranking task accuracy

### Sourcing & Claim Verification

- Split summarization from sourcing to improve citation fidelity
- Applied TF-IDF narrowing before model claim sourcing
- Deduplication consolidated events while preserving all underlying sources

### Context Window Management

- Preprocessing, chunking, clustering reduced raw reporting overload
- Deduplication avoided event inflation from redundant coverage
- Tiered summarization ensured detailed enrichment only for high-volume events

### Human-in-the-Loop & Governance

- Analysts validated high-stakes events and anomalies
- Risk controls prevented unchecked propagation of hallucinated content
- Selective validation combined with confidence metrics

---

## Knowledge Distillation

### Approach

To reduce long-term costs and enable offline deployment, the project explored **knowledge distillation**—training smaller, specialized models on GAI-generated labels.

### Classification Distillation Results

When evaluated against GPT-4o's synthetic labels, the **DistilBERT student model** achieved:

| Metric | Score |
|--------|-------|
| Overall F1 | 0.81 |
| Precision | 0.82 |
| Recall | 0.82 |

**Performance by Category:**

| Category | F1 Score |
|----------|----------|
| Transportation and Public Works | ~0.97 |
| International Affairs | >0.95 |
| Science & Technology | >0.95 |
| Agriculture & Food | >0.95 |
| Government Operations & Politics | ~0.71 |

Across 19 Congressional topics, the student model sustained high accuracy with 15 categories exceeding 0.80 F1 score.

### Implications

Knowledge distillation provides a viable path toward:
- Reduced inference costs
- Offline deployment capability
- Faster processing times
- Reduced dependency on commercial APIs

---

## Limitations and Future Directions

### Current Limitations

#### Deduplication Fidelity
- **Current**: Monthly fidelity, not ground-truth index
- **Challenge**: Over/under merging events
- **Future**: Hierarchical schemas + batch reprocessing + SME adjudication

#### Human-in-the-Loop Validation
- **Current**: Limited analyst manpower
- **Challenge**: Continuous review not feasible
- **Future**: Selective validation + confidence metrics + reinforcement learning

#### Evaluation & Ground Truth Gaps
- **Current**: No balanced dataset; high human variance
- **Challenge**: Evaluation remains iterative
- **Future**: Build balanced corpus; overlap checks; refine schema with SME input

#### Cost & Scaling
- **Current**: GPT-4.1 performance high, costs remain high
- **Challenge**: Large-scale ingestion not sustainable long-term
- **Future**: Hybrid frontier + student/open-source models

### Risk Management

The project implemented a comprehensive risk management framework:

| Risk | Mitigation |
|------|------------|
| Model hallucination | Human validation checkpoints |
| Output inconsistency | Structured JSON enforcement |
| Cost overruns | Model tiering by task complexity |
| Black-box concerns | Periodic evaluation and student model contingency |
| Schema drift | Continuous prompt refinement |

---

## Conclusion

This project demonstrates that Generative AI can effectively replace traditional supervised NLP pipelines for complex analytical tasks when:

1. **Proper risk mitigation** strategies are in place
2. **Prompt engineering** is carefully crafted and iteratively refined
3. **Human oversight** validates critical outputs
4. **Architecture** enables scalable processing and traceability

The adoption of GAI has enabled:
- **Dramatic reduction** in development time (months → hours)
- **Flexible adaptation** to evolving analytic requirements
- **Expanded capabilities** beyond original project scope
- **Scalable processing** of large document corpora
- **Entity and relationship extraction** to build comprehensive knowledge graphs
- **Conversational access** to data through an agentic RAG interface
- **Interactive visualizations** for exploring entity networks
- **Proactive alerting** for significant changes in soft power activities
- **Competing influence analysis** comparing multiple countries simultaneously
- **Research project workflows** for curated document analysis
- **Publication-ready reports** with Word document export

The system has evolved from a document categorization tool to a comprehensive soft power analytics platform that includes:

| Capability | Technology | Purpose |
|------------|------------|---------|
| Document Categorization | GPT-4o + custom prompts | Classify and extract soft power activities |
| Event Consolidation | GPT-4.1 + embeddings | Group related coverage into unique events |
| Entity Extraction | GPT-4o-mini + validation | Identify actors and organizations |
| Relationship Mapping | GPT-4o-mini + aggregation | Build network graph of interactions |
| Conversational Interface | Agentic RAG + tool selection | Natural language data access |
| Layered RAG Context | SQL + semantic search | Three-tier context for accurate responses |
| Network Visualization | Pyvis + React | Interactive entity exploration |
| Alerting System | APScheduler + Slack/Email | Proactive analyst notifications |
| Competing Influence | Recharts + RAG assessment | Multi-influencer comparison |
| Research Projects | Project-scoped RAG | Curated document collections |
| Report Generation | GPT-4o + python-docx | Publication-ready Word export |

As GAI technology continues to advance with improved accuracy, reduced costs, and expanded context windows, the framework established by this project positions the soft power analytics capability for continued evolution and enhancement.

The combination of frontier models for complex reasoning, open-source embeddings for efficient retrieval, distilled student models for cost-effective deployment, layered RAG architecture for grounded responses, and comprehensive analyst workflows represents a sustainable, adaptable approach to AI-powered analysis at scale.

---

## Appendix: Category Schema

### Primary Categories

1. **Economic**: Use of economic tools and policies to influence other countries' behaviors and attitudes
   - Trade, Food, Finance, Technology, Transportation, Tourism, Industrial, Raw Materials, Infrastructure

2. **Social**: Use of cultural, ideological, and social tools to influence behaviors and attitudes
   - Cultural, Education, Healthcare, Housing, Media, Politics, Religious, Aid/Donation

3. **Diplomacy**: Use of diplomatic channels and international relations
   - Multilateral/Bilateral Commitments, International Negotiations, Conflict Resolution, Global Governance Participation, Diaspora Engagement

4. **Military**: Strategic use of military resources to build goodwill without direct conflict
   - Sales, Joint Exercises, Training, Conferences

---

## Appendix: GAI Workflow Lifecycle

### Phase 1: Exploration & Experimentation
- Run small-scale PoCs with sandbox environments
- Test prompt designs, evaluate output quality, document caveats
- Establish early human-in-the-loop validation checkpoints

### Phase 2: Implementation into Development Pipeline
- Programmatic integration of GAI via API into dev workflows
- Refine model selection by task; optimize latency and cost
- Deploy supporting infrastructure (vector DBs, observability, monitoring)
- Demonstrate value at scale (tens of thousands of samples)
- Apply governance & risk management frameworks

### Phase 3: Maintenance & Evaluation
- Continuously update prompts and workflows as requirements emerge
- Monitor for model drift, data quality issues, and compliance risks
- Introduce feedback loops from user edits or analyst corrections
- Periodically evaluate against benchmarks and update documentation

### Phase 4: Distillation & Specialization
- Fine-tune SLMs or student models on production-generated datasets
- Build lightweight, domain-specific models for efficiency and portability
- Retire or replace outdated models with updated baselines
- Continue human validation and governance oversight

---

## Appendix: Entity and Relationship Schema

### Entity Types (11)

| Type | Description |
|------|-------------|
| PERSON | Individual officials, executives, diplomats |
| GOVERNMENT_AGENCY | Ministries, departments, embassies |
| STATE_OWNED_ENTERPRISE | Government-controlled companies |
| PRIVATE_COMPANY | Privately owned businesses |
| MULTILATERAL_ORG | International bodies (UN, BRICS, SCO) |
| NGO | Non-governmental organizations |
| EDUCATIONAL_INSTITUTION | Universities, research institutes |
| FINANCIAL_INSTITUTION | Banks, investment funds |
| MILITARY_UNIT | Armed forces, defense ministries |
| MEDIA_ORGANIZATION | News outlets, broadcasters |
| RELIGIOUS_ORGANIZATION | Religious bodies |

### Role Labels (25)

**Diplomatic:** HEAD_OF_STATE, DIPLOMAT, NEGOTIATOR, GOVERNMENT_OFFICIAL, LEGISLATOR

**Economic:** FINANCIER, INVESTOR, CONTRACTOR, DEVELOPER, TRADE_PARTNER, OPERATOR

**Military:** MILITARY_OFFICIAL, DEFENSE_SUPPLIER, TRAINER

**Cultural/Social:** CULTURAL_INSTITUTION, EDUCATOR, MEDIA_ENTITY, RELIGIOUS_ENTITY, HUMANITARIAN

**Transaction:** BENEFICIARY, HOST, LOCAL_PARTNER, FACILITATOR, SIGNATORY

### Topic Labels (30)

**Economic:** INFRASTRUCTURE, ENERGY, FINANCE, TRADE, TECHNOLOGY, TELECOMMUNICATIONS, TRANSPORTATION, AGRICULTURE, MINING, MANUFACTURING

**Diplomatic:** BILATERAL_RELATIONS, MULTILATERAL_FORUMS, CONFLICT_MEDIATION, TREATY_NEGOTIATION

**Military:** ARMS_TRADE, MILITARY_COOPERATION, DEFENSE_TRAINING, SECURITY_ASSISTANCE

**Social:** EDUCATION, HEALTHCARE, CULTURE, MEDIA, RELIGION, HUMANITARIAN_AID, TOURISM

### Relationship Types (14)

| Type | Description |
|------|-------------|
| FUNDS | Provides money/financing to |
| INVESTS_IN | Makes equity investment in |
| CONTRACTS_WITH | Has contract/agreement with |
| PARTNERS_WITH | Forms partnership/JV with |
| SIGNS_AGREEMENT | Signs formal agreement with |
| MEETS_WITH | Has meeting/diplomatic encounter with |
| EMPLOYS | Has employment relationship with |
| OWNS | Has ownership stake in |
| REPRESENTS | Officially represents (person → org) |
| HOSTS | Hosts event/visit for |
| TRAINS | Provides training to |
| SUPPLIES | Provides goods/equipment to |
| MEDIATES | Mediates between parties |
| ANNOUNCES | Makes public announcement about |

---

## Appendix: Alert Condition Reference

### Alert Condition Types

| Condition | Parameters | Evaluation Logic |
|-----------|------------|------------------|
| `materiality_spike` | `threshold_z`, `window_days`, `country`, `category` | Z-score of current materiality vs. rolling window |
| `volume_surge` | `threshold_z`, `window_days`, `country` | Z-score of document count vs. rolling window |
| `new_entity` | `country`, `entity_type` | First appearance of entity in database |
| `new_event` | `country`, `min_materiality` | New event exceeding materiality threshold |

### Notification Channel Configuration

| Channel | Config Fields | Example |
|---------|---------------|---------|
| `in_app` | None required | In-app AlertBell indicator |
| `email` | `email` | `analyst@organization.gov` |
| `slack` | `slack_webhook_url` | `https://hooks.slack.com/services/...` |

### Severity Guidelines

| Severity | Use Case | Cooldown |
|----------|----------|----------|
| `info` | Routine monitoring, FYI alerts | 60 min |
| `warning` | Notable changes requiring review | 30 min |
| `critical` | Major developments, immediate attention | 15 min |

---

*This white paper synthesizes findings from the Soft Power Analytics Project, documenting technical approaches, evaluation results, and lessons learned in applying Generative AI to international relations analysis. Version 3.0 includes expanded coverage of alerting and notifications, competing influence analysis, research project workflows, layered RAG architecture, and publication-ready report generation capabilities.*
