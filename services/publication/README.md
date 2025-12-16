# Publication Service

This service generates formatted Word document summaries from the soft power analytics database. It replaces the deprecated `summary_template` pipeline with a modern, service-oriented architecture using current database models.

## Overview

The publication service:
1. Queries event summaries and documents from the database using current models
2. Uses AI (GPT) to consolidate events and generate narratives
3. Identifies source documents for each section (overview and outcome)
4. Builds two versions of Word documents:
   - **Reviewer Version**: Includes visible document citations under each section for verification
   - **Summary Version**: Clean version with end notes section

## Architecture

### Components

```
services/publication/
├── __init__.py                  # Package initialization
├── query_builder.py             # Database queries using SQLAlchemy 2.0
├── summary_generator.py         # AI-powered summary generation
├── document_builder.py          # Word document construction
├── publication_service.py       # Main orchestrator
├── generate_publication.py      # CLI script
├── templates/
│   ├── GAI_Summary_Template.docx  # Word template
│   └── atom.png                   # Icon for hyperlinks
├── output/                      # Generated documents
└── README.md                    # This file
```

### Database Models Used

- **EventSummary**: Consolidated event summaries with period types (daily/weekly/monthly/yearly)
- **PeriodSummary**: Aggregated summaries across all events for a time period
- **EventSourceLink**: Traceability links between events and source documents
- **Document**: Core document model with all metadata
- **Category, Subcategory, InitiatingCountry, RecipientCountry**: Normalized relationships

## Usage

### Basic Command

```bash
python services/publication/generate_publication.py \
  --country China \
  --start 2024-10-01 \
  --end 2024-10-31
```

### Advanced Options

```bash
python services/publication/generate_publication.py \
  --country China \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --categories "Economic,Diplomacy,Social,Military" \
  --recipients "United States,Japan,South Korea" \
  --period-type monthly \
  --model gpt-4 \
  --max-sources 15 \
  --output services/publication/output
```

### Command-Line Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--country` | Yes | - | Initiating country (e.g., China, Russia) |
| `--start` | Yes | - | Start date (YYYY-MM-DD) |
| `--end` | Yes | - | End date (YYYY-MM-DD) |
| `--categories` | No | Economic,Diplomacy,Social,Military | Categories to include |
| `--recipients` | No | All | Filter by recipient countries |
| `--period-type` | No | monthly | Period type: daily, weekly, monthly, yearly |
| `--model` | No | gpt-4 | GPT model for AI generation |
| `--template` | No | services/publication/templates/... | Word template path |
| `--output` | No | services/publication/output | Output directory |
| `--max-sources` | No | 10 | Max source documents per section |
| `--no-consolidation` | No | False | Skip event consolidation |

## Document Versions

### Reviewer Version

The reviewer version includes:
- Event headings organized by category
- Overview section with narrative summary
- **Visible document citations** immediately following the overview
- Outcome section with narrative summary
- **Visible document citations** immediately following the outcome
- Hyperlinked icons (if atom.png available) for quick access to sources

**Purpose**: Allows subject matter experts to quickly verify facts and review source documents.

### Summary Version

The summary version includes:
- Event headings organized by category
- Overview and outcome sections (clean, without inline citations)
- **End Notes section** at the end with all citations organized by:
  - Category
  - Event
  - Deduplicated list of source documents

**Purpose**: Clean, professional report for distribution and reading.

## Template Structure

The Word template (`GAI_Summary_Template.docx`) uses placeholders:

### Global Placeholders
- `{{country}}`: Initiating country name
- `{{date}}`: Full date range
- `{{summary_title}}`: AI-generated publication title

### Category Section Placeholders
- `{{economic_event_section}}`: Economic category events
- `{{diplomatic_event_section}}`: Diplomacy category events
- `{{social_event_section}}`: Social category events
- `{{military_event_section}}`: Military category events

## Workflow

### Step-by-Step Process

1. **Query Event Summaries**: Fetch EventSummary records matching the criteria
2. **Organize by Category**: Group events by primary category
3. **Consolidate Duplicates**: Use AI to identify and merge duplicate events
4. **Fetch Source Documents**: Query EventSourceLink and Document tables
5. **Identify Sources**: Use AI to identify which documents support each section
6. **Format Citations**: Create formatted citation strings
7. **Generate Title**: Use AI to create descriptive publication title
8. **Build Documents**: Create both reviewer and summary versions

## AI Integration

The service uses GPT models for several tasks:

### Title Generation
```python
generate_publication_title(event_summaries, start_date, end_date)
```
Creates a concise, descriptive title for the publication.

### Event Consolidation
```python
consolidate_duplicate_events(event_summaries, categories)
```
Identifies duplicate or overlapping events that should be merged.

### Source Identification
```python
identify_source_documents(event_summary, documents, summary_text)
```
Determines which documents best support a given summary text.

### Narrative Generation (Optional)
```python
generate_event_narrative(event_name, documents, category)
```
Creates overview and outcome narratives from documents (if not using existing EventSummary narratives).

## Database Requirements

### Prerequisites

The service requires that **EventSummary** data exists in the database for the specified period. If no EventSummary records are found:

1. Run the event summarization pipeline first
2. Or use the event processing scripts to generate summaries:
   ```bash
   python services/pipeline/events/process_date_range.py --start 2024-10-01 --end 2024-10-31
   ```

### Key Tables

- `event_summaries`: Must contain events for the specified country and date range
- `event_source_links`: Links events to source documents
- `documents`: Contains the actual document content and metadata
- `categories`, `initiating_countries`, `recipient_countries`: Normalized relationships

## Configuration

### Environment Variables

Required:
- `CLAUDE_KEY`: OpenAI API key for GPT models
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`: Database credentials

Optional:
- `DB_HOST`, `DB_PORT`: Database connection details

### Config File

Uses `shared/config/config.yaml` for:
- Default categories list
- Default recipient countries
- Model configuration
- Processing parameters

## Output

Generated files are saved to the output directory with naming convention:

```
{country}_{start_date}_{end_date}_Reviewer.docx
{country}_{start_date}_{end_date}_Summary.docx
```

Example:
```
China_2024-10-01_2024-10-31_Reviewer.docx
China_2024-10-01_2024-10-31_Summary.docx
```

## Error Handling

The service handles common errors gracefully:

- **No event summaries found**: Provides clear message and exit code
- **Template not found**: Validates template path before processing
- **AI generation errors**: Falls back to default values or continues without optional features
- **Database errors**: Proper session management with automatic rollback

## Development

### Adding New Features

To extend the service:

1. **New queries**: Add methods to `PublicationQueryBuilder`
2. **New AI features**: Add methods to `SummaryGenerator`
3. **Document formatting**: Modify `DocumentBuilder` methods
4. **Workflow changes**: Update `PublicationService.generate_publication()`

### Testing

```bash
# Test with sample data
python services/publication/generate_publication.py \
  --country China \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --categories Economic \
  --max-sources 5
```

## Migration from Deprecated Pipeline

This service replaces `summary_template/summary_publication.py` with:

### Key Improvements

1. **Modern Architecture**: Service-oriented design with clear separation of concerns
2. **Current Models**: Uses EventSummary, PeriodSummary, and current SQLAlchemy 2.0 models
3. **Better Session Management**: Proper use of context managers and connection pooling
4. **Modular Design**: Separate query, generation, and building components
5. **CLI Interface**: Clear command-line interface with validation
6. **Error Handling**: Comprehensive error handling and user feedback

### Differences

| Feature | Deprecated | New Service |
|---------|-----------|-------------|
| Models | Old Flask-SQLAlchemy | SQLAlchemy 2.0 |
| Event Data | CountrySummary, RecipientSummary | EventSummary, PeriodSummary |
| Architecture | Monolithic script | Modular services |
| Session Mgmt | Manual, error-prone | Context managers |
| CLI | Hardcoded variables | argparse with validation |
| Sourcing | Manual TF-IDF | AI-powered identification |

## Troubleshooting

### Common Issues

**Problem**: "No event summaries found"
- **Solution**: Generate EventSummary data first using event processing pipeline

**Problem**: "Template file not found"
- **Solution**: Ensure `GAI_Summary_Template.docx` exists in templates directory

**Problem**: "AI generation timeout"
- **Solution**: Reduce max_sources or use a faster model (gpt-3.5-turbo)

**Problem**: "Database connection error"
- **Solution**: Check environment variables and database is running

## Future Enhancements

Potential improvements:

- [ ] Parallel AI generation for multiple events
- [ ] Caching of AI responses to reduce costs
- [ ] Custom template support via command line
- [ ] PDF export option
- [ ] Email distribution integration
- [ ] Scheduled automatic generation
- [ ] Multi-language support
- [ ] Interactive web interface

## Support

For issues or questions:
1. Check CLAUDE.md for general architecture
2. Review database schema in shared/models/models.py
3. Check logs for detailed error messages
4. Verify EventSummary data exists for the period
