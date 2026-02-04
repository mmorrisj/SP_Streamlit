# Source Attribution System for Document-Based Summaries

**Last Updated**: January 2026

## Overview

The document-based hierarchical summary generator includes a **complete source attribution system** that allows analysts to validate every claim in the summaries by tracing citations all the way back to original source documents.

## Citation Chain Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    OVERALL SUMMARY (June-December 2025)                 │
│  Summary: "China expanded economic engagement [Month 1,2]..."          │
│  Citations: [                                                           │
│    {                                                                    │
│      "citation_number": "Month 1",                                      │
│      "month_name": "June 2025",                                         │
│      "monthly_citations": [ → links to weekly summaries ]              │
│    }                                                                    │
│  ]                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       MONTHLY SUMMARY (June 2025)                       │
│  Summary: "Week 2 saw major infrastructure deals [Week 2]..."          │
│  Citations: [                                                           │
│    {                                                                    │
│      "citation_number": "Week 2",                                       │
│      "period_start": "2025-06-08",                                      │
│      "weekly_citations": [ → links to daily summaries ]                │
│    }                                                                    │
│  ]                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     WEEKLY SUMMARY (June 8-14, 2025)                    │
│  Summary: "Day 3 featured major announcements [Day 3]..."              │
│  Citations: [                                                           │
│    {                                                                    │
│      "citation_number": "Day 3",                                        │
│      "date": "2025-06-10",                                              │
│      "daily_citations": [ → links to documents ]                       │
│    }                                                                    │
│  ]                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       DAILY SUMMARY (June 10, 2025)                     │
│  Summary: "China announced $2B infrastructure deal [1,2]..."           │
│  Citations: [                                                           │
│    {                                                                    │
│      "citation_number": 1,                                              │
│      "doc_id": "abc123",                                                │
│      "headline": "China Signs $2B Infrastructure Deal with Kenya",      │
│      "source_name": "Reuters",                                          │
│      "source_url": "https://reuters.com/...",                           │
│      "excerpt": "China and Kenya signed a $2 billion...",               │
│      "salience": 85,                                                    │
│      "categories": ["Economic", "Infrastructure"],                      │
│      "recipients": ["Kenya"]                                            │
│    },                                                                   │
│    {                                                                    │
│      "citation_number": 2,                                              │
│      "doc_id": "def456",                                                │
│      ...                                                                │
│    }                                                                    │
│  ]                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

## How It Works

### 1. Daily Summaries (Base Level)

**LLM Prompt**: Instructs model to cite every fact using numbered references [1], [2], etc.

**Example Output**:
```json
{
  "date": "2025-06-10",
  "country": "China",
  "summary": "China announced a $2B infrastructure deal with Kenya [1,2], marking a significant expansion of Belt and Road activities in East Africa [3]. Simultaneously, cultural exchanges increased with Ethiopia [4,5].",
  "citations": [
    {
      "citation_number": 1,
      "doc_id": "abc123",
      "headline": "China Signs $2B Infrastructure Deal with Kenya",
      "source_name": "Reuters",
      "source_url": "https://reuters.com/article/123",
      "published_date": "2025-06-10",
      "salience": 85,
      "categories": ["Economic", "Infrastructure"],
      "recipients": ["Kenya"],
      "excerpt": "China and Kenya signed a $2 billion infrastructure development agreement covering ports and railways..."
    },
    {
      "citation_number": 2,
      "doc_id": "def456",
      "headline": "Kenya Welcomes Chinese Infrastructure Investment",
      "source_name": "The Standard",
      "source_url": "https://standardmedia.co.ke/article/456",
      "published_date": "2025-06-10",
      "salience": 72,
      "categories": ["Economic", "Diplomacy"],
      "recipients": ["Kenya"],
      "excerpt": "President Ruto welcomed the Chinese delegation and praised the bilateral infrastructure partnership..."
    }
  ],
  "metrics": {
    "total_documents": 8,
    "categories": {"Economic": 4, "Diplomacy": 2, "Infrastructure": 3},
    "recipients": {"Kenya": 6, "Ethiopia": 2}
  },
  "doc_ids": ["abc123", "def456", "ghi789", ...],
  "generated_at": "2026-01-06T12:00:00Z"
}
```

### 2. Weekly Summaries (First Rollup)

**LLM Prompt**: Instructs model to cite using [Day 1], [Day 2], etc.

**Example Output**:
```json
{
  "period_start": "2025-06-08",
  "period_end": "2025-06-14",
  "country": "China",
  "summary": "Major infrastructure developments dominated the week [Day 3,4], with significant announcements in Kenya and Tanzania [Day 3]. Cultural diplomacy intensified in Ethiopia [Day 5,6].",
  "citations": [
    {
      "citation_number": "Day 3",
      "date": "2025-06-10",
      "summary_excerpt": "China announced a $2B infrastructure deal with Kenya [1,2], marking a significant expansion...",
      "total_documents": 8,
      "doc_ids": ["abc123", "def456", ...],
      "daily_citations": [ /* full daily citations array from Day 3 */ ]
    }
  ],
  "metrics": { ... }
}
```

### 3. Monthly Summaries (Second Rollup)

**LLM Prompt**: Instructs model to cite using [Week 1], [Week 2], etc.

**Example Output**:
```json
{
  "period_start": "2025-06-01",
  "period_end": "2025-06-30",
  "country": "China",
  "summary": "June marked a significant escalation in China's economic engagement with East Africa [Week 2,3], featuring multiple billion-dollar infrastructure commitments [Week 2]...",
  "citations": [
    {
      "citation_number": "Week 2",
      "period_start": "2025-06-08",
      "period_end": "2025-06-14",
      "summary_excerpt": "Major infrastructure developments dominated the week [Day 3,4]...",
      "total_documents": 52,
      "daily_dates": ["2025-06-08", "2025-06-09", "2025-06-10", ...],
      "weekly_citations": [ /* full weekly citations array */ ]
    }
  ],
  "metrics": { ... }
}
```

### 4. Overall Summary (Final Rollup)

**LLM Prompt**: Instructs model to cite using [Month 1], [Month 2], etc.

**Example Output**:
```json
{
  "period_start": "2025-06-01",
  "period_end": "2025-12-31",
  "country": "China",
  "summary": "China's H2 2025 soft power strategy emphasized economic infrastructure [Month 1,2,3] with sustained focus on East Africa and Southeast Asia [Month 1,4,6]...",
  "citations": [
    {
      "citation_number": "Month 1",
      "month_name": "June 2025",
      "period_start": "2025-06-01",
      "period_end": "2025-06-30",
      "summary_excerpt": "June marked a significant escalation in China's economic engagement...",
      "total_documents": 215,
      "weeks_covered": 5,
      "monthly_citations": [ /* full monthly citations array */ ]
    }
  ],
  "metrics": { ... }
}
```

## Validation Workflow

### For Analysts: How to Validate a Claim

**Example**: You're reading the overall summary and see:
> "China's H2 2025 soft power strategy emphasized economic infrastructure [Month 1,2,3]..."

**Validation Steps**:

1. **Check Overall Summary Citations**
   - Open `overall_2025-06-01_to_2025-12-31.json`
   - Find citation [Month 1] in the `citations` array
   - Note: June 2025 had 215 documents across 5 weeks

2. **Drill Down to Monthly Summary**
   - Look at `monthly_citations` in Month 1's citation object
   - Or open `monthly/2025-06.json` directly
   - Find claims about infrastructure emphasis
   - Note which weeks ([Week 2], [Week 3]) support this

3. **Drill Down to Weekly Summary**
   - Look at `weekly_citations` from the relevant weeks
   - Or open `weekly/2025-06-08_to_2025-06-14.json`
   - Find specific infrastructure deals
   - Note which days ([Day 3], [Day 4]) had the key events

4. **Drill Down to Daily Summary**
   - Look at `daily_citations` from the relevant day
   - Or open `daily/2025-06-10.json`
   - Find the specific document citations [1], [2]
   - See doc_ids, headlines, sources

5. **Verify Source Documents**
   - Use the `doc_id` values (e.g., "abc123", "def456")
   - Query the database: `SELECT * FROM documents WHERE doc_id = 'abc123'`
   - Or use the `source_url` to view the original article
   - Read the `excerpt` provided in the citation
   - Check if the claim is supported by the document

### Example Validation Query

```sql
-- Get full document details for a citation
SELECT
    doc_id,
    headline,
    source_name,
    source_url,
    published_date,
    full_text_extract,
    salience_rating
FROM documents
WHERE doc_id = 'abc123';
```

## File Organization

```
publications/china_2025_h2/
├── overall_2025-06-01_to_2025-12-31.json     # Final summary with [Month N] citations
├── monthly/
│   ├── 2025-06.json                          # June summary with [Week N] citations
│   ├── 2025-07.json                          # July summary
│   ├── 2025-08.json
│   ├── 2025-09.json
│   ├── 2025-10.json
│   ├── 2025-11.json
│   └── 2025-12.json
├── weekly/
│   ├── 2025-06-01_to_2025-06-07.json        # Week 1 with [Day N] citations
│   ├── 2025-06-08_to_2025-06-14.json        # Week 2
│   ├── 2025-06-15_to_2025-06-21.json        # Week 3
│   └── ...
└── daily/
    ├── 2025-06-01.json                       # Daily summary with [N] doc citations
    ├── 2025-06-02.json
    ├── 2025-06-03.json
    └── ...
```

## Benefits of This System

### 1. Complete Traceability
- **Every claim** can be traced to specific source documents
- No "orphaned" facts without attribution
- Clear chain of evidence for validation

### 2. Efficient Validation
- Analysts don't need to read 1000+ documents
- Follow citation chain from high-level claim → specific sources
- Only review relevant documents for questionable claims

### 3. Quality Assurance
- Easy to spot LLM hallucinations (claims without proper citations)
- Can verify if citations actually support the claims
- Builds confidence in AI-generated summaries

### 4. Reproducibility
- Citation chain documents the reasoning process
- Other analysts can verify conclusions
- Transparent methodology for publications

### 5. Flexibility
- Can start at any level (overall → monthly → weekly → daily → docs)
- Can validate specific claims without reading everything
- Citations preserved in JSON for programmatic access

## Usage Examples

### Generate Summaries with Full Attribution

```bash
# Generate complete hierarchy for China H2 2025
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2

# Output includes:
# - Daily summaries with document citations [1,2,3...]
# - Weekly summaries with day citations [Day 1, Day 2...]
# - Monthly summaries with week citations [Week 1, Week 2...]
# - Overall summary with month citations [Month 1, Month 2...]
```

### Validate a Specific Claim

```python
import json
from pathlib import Path

# 1. Read overall summary
overall = json.load(open('publications/china_2025_h2/overall_2025-06-01_to_2025-12-31.json'))

# 2. Find citation in summary text (e.g., [Month 1])
for citation in overall['citations']:
    if citation['citation_number'] == 'Month 1':
        print(f"Month: {citation['month_name']}")
        print(f"Documents: {citation['total_documents']}")

        # 3. Drill down to monthly citations
        for week_cit in citation['monthly_citations']:
            if week_cit['citation_number'] == 'Week 2':
                # 4. Drill down to weekly citations
                for day_cit in week_cit['weekly_citations']:
                    if day_cit['citation_number'] == 'Day 3':
                        # 5. Get document citations
                        for doc_cit in day_cit['daily_citations']:
                            print(f"\nDoc {doc_cit['citation_number']}:")
                            print(f"  ID: {doc_cit['doc_id']}")
                            print(f"  Headline: {doc_cit['headline']}")
                            print(f"  Source: {doc_cit['source_name']}")
                            print(f"  URL: {doc_cit['source_url']}")
                            print(f"  Excerpt: {doc_cit['excerpt'][:200]}...")
```

## Best Practices

### For Analysts

1. **Always verify high-salience claims** by following the citation chain
2. **Spot-check citations** to ensure they support the claims
3. **Look for citation density** - claims without citations are suspicious
4. **Use excerpts first** before fetching full documents
5. **Document any discrepancies** between summaries and source documents

### For Developers

1. **Maintain citation chain integrity** when modifying summary functions
2. **Test citation accuracy** with sample data
3. **Preserve doc_ids** throughout the entire chain
4. **Include enough context** in excerpts for validation
5. **Monitor LLM citation compliance** - not all models cite consistently

## Future Enhancements

### Potential Improvements

1. **Citation Highlighting**: Web UI that highlights citations and shows source on hover
2. **Automated Validation**: Script that checks if citations actually appear in referenced documents
3. **Citation Graph**: Visual graph showing citation density and chains
4. **Alternative Views**: Generate HTML with inline citations as hyperlinks
5. **Citation Statistics**: Track which documents are most-cited, citation coverage metrics

---

**For Questions**: See main documentation in [generate_document_based_summaries.py](generate_document_based_summaries.py)
