# Leveraging Generative AI for Soft Power Analytics at Scale

## A Technical White Paper on Automating International Relations Analysis

---

**Author:** Matt Morris, Data Scientist

**Version:** 1.0

**Date:** December 2024

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Introduction and Background](#introduction-and-background)
3. [Technical Approach](#technical-approach)
4. [Model Evaluation and Performance](#model-evaluation-and-performance)
5. [System Architecture](#system-architecture)
6. [Prompt Engineering](#prompt-engineering)
7. [Event Processing Pipeline](#event-processing-pipeline)
8. [Techniques and Lessons Learned](#techniques-and-lessons-learned)
9. [Knowledge Distillation](#knowledge-distillation)
10. [Limitations and Future Directions](#limitations-and-future-directions)
11. [Conclusion](#conclusion)

---

## Executive Summary

This white paper presents a comprehensive framework for automating the analysis of soft power activities using Generative AI (GAI). The project aims to identify and categorize articles discussing soft power activities conducted by hard target countries towards Middle Eastern nations. Initially, a custom supervised topic model was planned, but advancements in generative AI models offered a more efficient solution.

Evaluations demonstrated that GAI models not only excelled in categorizing articles by soft power topics but also performed Named Entity Recognition (NER) tasks effectively. The decreasing costs of GAI made it the most timely and cost-effective approach for the project. With the more advanced capabilities offered by GAI, the project expanded its scope through innovative prompt engineering to not only categorize content, but also:

- Identify initiating and recipient countries of soft power interactions
- Extract specific project details including monetary values
- Determine geocoordinates for geographic visualization
- Track and consolidate events across large document corpora
- Generate automated summaries and insights

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

As GAI technology continues to advance with improved accuracy, reduced costs, and expanded context windows, the framework established by this project positions the soft power analytics capability for continued evolution and enhancement.

The combination of frontier models for complex reasoning, open-source embeddings for efficient retrieval, and distilled student models for cost-effective deployment represents a sustainable, adaptable approach to AI-powered analysis at scale.

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

*This white paper synthesizes findings from the Soft Power Analytics Project, documenting technical approaches, evaluation results, and lessons learned in applying Generative AI to international relations analysis.*
