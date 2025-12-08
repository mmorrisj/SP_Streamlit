# AP-Style Factual Summary Pipeline
## Objective Reporting Without Analysis

## Core Principle

**Report facts, not analysis.** Summaries must follow Associated Press (AP) reporting standards:
- ✅ Report what happened, who said what, when, where
- ✅ Attribute statements to sources ("according to," "officials said," etc.)
- ✅ Use neutral, factual language
- ❌ No analysis, interpretation, or strategic significance
- ❌ No subjective descriptors (e.g., "significant," "important," "strategic")
- ❌ No explanations of intent or impact

---

## AP Style Guidelines for Summaries

### **Format Requirements**

**Overview: 2-3 sentence paragraph**
- First sentence: Main factual development (who, what, when, where)
- Second sentence: Key details or follow-up actions
- Third sentence (optional): Additional factual context

**Outcomes: 2-3 sentence paragraph**
- Concrete, verifiable facts only
- Direct quotes or paraphrased statements from officials
- Specific numbers, dates, locations

### **Writing Standards**

✅ **Good (AP Style):**
```
Iran opened three additional border crossings for Arbaeen pilgrims on Aug. 15,
according to Iranian state media IRNA. The crossings at Mehran, Shalamcheh and
Chazabeh became operational at 6 a.m. local time. Iraqi officials thanked Iran
for the coordination in a joint statement issued the same day.
```

❌ **Bad (Analytical Style):**
```
Iran significantly enhanced its soft power influence by strategically opening
border crossings, demonstrating its commitment to regional religious diplomacy.
This move strengthened Iran's position as protector of Shia practices and
improved its relationship with Iraq.
```

### **Attribution Requirements**

Every claim must be attributed:
- "according to [source]"
- "[official name/title] said"
- "[organization] reported"
- "state media [name] said"
- "a statement said"

---

## Updated LLM Prompts (AP-Style)

### **Daily Summary Prompt**

```python
DAILY_SUMMARY_AP_STYLE = """
You are writing factual news briefs following Associated Press (AP) style guidelines.

CRITICAL RULES:
1. Report ONLY facts - no analysis, interpretation, or significance
2. Attribute ALL information to sources (use article sources provided)
3. Use past tense for completed actions
4. Be specific with numbers, dates, times, locations
5. No subjective language ("important," "significant," "strategic")
6. No speculation about intent, impact, or future implications

EVENT: {event_name}
DATE: {date}
COUNTRY: {country}

SOURCE ARTICLES:
[1] {article_1_title} - {article_1_source} - {article_1_date}
    {article_1_excerpt}

[2] {article_2_title} - {article_2_source} - {article_2_date}
    {article_2_excerpt}

[3] {article_3_title} - {article_3_source} - {article_3_date}
    {article_3_excerpt}

TASK:
Write two factual paragraphs following AP style:

1. OVERVIEW (2-3 sentences):
   - First sentence: Main development (who, what, when, where)
   - Include attribution to source ([1], [2], etc.)
   - Additional factual details
   - NO analysis or interpretation

2. OUTCOMES (2-3 sentences):
   - Concrete results or statements
   - Official announcements or actions taken
   - Must be directly verifiable from sources
   - Include attribution

FORMAT YOUR RESPONSE AS JSON:
{{
  "overview": "Iran opened three additional border crossings for Arbaeen pilgrims on Aug. 15, according to Iranian state media IRNA [1]. The crossings at Mehran, Shalamcheh and Chazabeh became operational at 6 a.m. local time, the report said. The move came as millions of pilgrims traveled to Karbala, Iraq for the religious observance.",

  "outcomes": "Iraqi Foreign Ministry spokesman Ahmad al-Sahaf thanked Iran for the coordination in a statement issued Aug. 15 [2]. Iran deployed 45 medical teams along the routes, according to the Iranian Red Crescent [1]. The teams provided free medical services to pilgrims at 12 stations, the organization said.",

  "sources_used": [1, 2, 3]
}}

EXAMPLES OF GOOD AP STYLE:
✅ "Officials announced X on [date], according to [source]"
✅ "[Person/Org] said Y in a statement"
✅ "The meeting took place at [location], [source] reported"
✅ "Data showed [specific number/fact], according to [source]"

EXAMPLES TO AVOID:
❌ "This demonstrates Iran's strategic intent..."
❌ "The significant development showed..."
❌ "Iran enhanced its influence by..."
❌ "This will likely lead to..."

Remember: Report ONLY what sources say happened, not what it means or why it matters.
"""
```

---

## Example Outputs (AP-Style)

### **Daily Summary: Arbaeen Pilgrimage Support (Aug 15, 2024)**

**Overview:**
Iran opened three additional border crossings for Arbaeen pilgrims on Aug. 15, according to Iranian state media IRNA. The crossings at Mehran, Shalamcheh and Chazabeh became operational at 6 a.m. local time, the report said. The move came as millions of pilgrims traveled to Karbala, Iraq for the religious observance marking the end of a 40-day mourning period.

**Outcomes:**
Iraqi Foreign Ministry spokesman Ahmad al-Sahaf thanked Iran for the coordination in a statement issued Aug. 15. Iran deployed 45 medical teams along pilgrimage routes, according to the Iranian Red Crescent. The teams provided free medical services at 12 stations between the border and Karbala, the organization said in a statement.

### **Daily Summary: Russia-Iran Defense Meeting (Aug 15, 2024)**

**Overview:**
Russian Deputy Defense Minister Alexander Fomin met with Iranian Defense Minister Mohammad Reza Ashtiani in Tehran on Aug. 15, Russia's Defense Ministry said in a statement. The officials discussed military-technical cooperation and regional security issues during a three-hour meeting, the statement said. Both sides signed a memorandum of understanding on defense cooperation, according to Iranian state media IRNA.

**Outcomes:**
The two countries agreed to establish a joint working group on unmanned aerial vehicle technology, the memorandum said. Russia will send technical advisers to Iran for defense industry projects, according to the agreement posted on the Defense Ministry website. Iranian and Russian naval forces will conduct joint exercises in the Caspian Sea in September, both defense ministries announced.

---

## Weekly Summary Prompt (AP-Style)

```python
WEEKLY_SUMMARY_AP_STYLE = """
You are consolidating daily news briefs into a weekly factual summary following AP style.

CRITICAL RULES:
1. Synthesize facts from multiple days without adding interpretation
2. Maintain all source attributions
3. Show chronological progression when relevant
4. No analysis of trends or significance
5. Report only what sources said/reported

EVENT: {event_name}
WEEK: {week_start} to {week_end}
COUNTRY: {country}

DAILY SUMMARIES:
{daily_summaries_with_sources}

TASK:
Consolidate the daily reports into two factual paragraphs:

1. OVERVIEW (2-3 sentences):
   - Synthesize main developments across the week
   - Maintain chronological flow if relevant
   - Keep all attributions
   - NO interpretation or significance statements

2. OUTCOMES (2-3 sentences):
   - Consolidate concrete results/statements
   - Remove duplicate information
   - Maintain source attribution
   - Only verifiable facts

FORMAT AS JSON:
{{
  "overview": "...",
  "outcomes": "...",
  "days_covered": 5,
  "primary_sources": ["IRNA", "Reuters", "AP"]
}}
"""
```

### **Example Weekly Output**

**Overview:**
Iran opened seven border crossings for Arbaeen pilgrims between Aug. 11-17, with the final three activated on Aug. 15, according to Iranian state media reports. The Iranian Red Crescent deployed 180 medical teams and established 47 service stations along pilgrimage routes during the week, the organization said in daily statements. Iraqi officials issued three joint statements with Iranian counterparts coordinating logistics and security, state media in both countries reported.

**Outcomes:**
More than 2.1 million pilgrims crossed into Iraq through the Iranian border points during the week, according to Iranian border control data cited by IRNA. The Iraqi Foreign Ministry thanked Iran for cooperation in statements issued Aug. 12, Aug. 14 and Aug. 17. Both countries agreed to maintain the additional crossings through Aug. 31, according to a joint statement from the interior ministries.

---

## Monthly Summary Prompt (AP-Style)

```python
MONTHLY_SUMMARY_AP_STYLE = """
You are writing a monthly factual summary following AP reporting standards.

CRITICAL RULES:
1. Consolidate weekly reports into monthly overview
2. Show progression/chronology when relevant
3. NO strategic analysis or interpretation
4. Report cumulative facts and official statements
5. Maintain attribution to sources

EVENT: {event_name}
MONTH: {month} {year}
COUNTRY: {country}

WEEKLY SUMMARIES:
{weekly_summaries}

TASK:
Write a monthly factual report in two paragraphs:

1. OVERVIEW (2-3 sentences):
   - Main developments across the month
   - Chronological progression if relevant
   - Official statements or announcements
   - Keep attributions

2. OUTCOMES (2-3 sentences):
   - Cumulative facts (totals, final counts)
   - Official results or conclusions
   - Final statements from officials
   - Verifiable end-of-month status

FORMAT AS JSON:
{{
  "overview": "...",
  "outcomes": "...",
  "total_articles": 89,
  "date_range": "2024-08-01 to 2024-08-31",
  "primary_sources": [...]
}}
"""
```

### **Example Monthly Output**

**Overview:**
Iran operated special border arrangements for Arbaeen pilgrims throughout August, opening seven border crossings and deploying 180 medical teams, according to Iranian state media reports and Red Crescent statements issued during the month. The pilgrimage period peaked Aug. 24-27 with the highest daily crossing numbers, border control data showed. Iraqi and Iranian officials held coordination meetings weekly and issued joint statements on logistics, security and healthcare cooperation, both governments' media offices reported.

**Outcomes:**
A total of 4.2 million pilgrims crossed from Iran into Iraq through the designated border points in August, according to final figures released by Iranian border authorities on Aug. 31. The Iranian Red Crescent said its teams provided medical services to 127,000 pilgrims at 47 stations during the month, according to the organization's final report. Iraqi Foreign Minister Fuad Hussein thanked Iran for the cooperation in a statement issued Aug. 30, calling the coordination "successful," state media reported.

---

## Implementation Changes

### **Updated Summary Generation Function**

```python
def generate_daily_summary_ap_style(country, date):
    """Generate AP-style factual daily summary."""

    with get_session() as session:
        # Get events active on this day
        active_events = get_active_master_events(country, date)

        for event in active_events[:10]:
            # Get doc_ids and sample articles
            doc_ids = get_event_doc_ids(session, event.id, date)
            sample_docs = get_sample_documents(session, doc_ids, limit=5)

            # Extract article information
            articles_info = []
            for i, doc in enumerate(sample_docs, 1):
                articles_info.append({
                    'number': i,
                    'title': doc.title,
                    'source': doc.source_name,
                    'date': str(doc.date),
                    'excerpt': doc.distilled_text[:500] if doc.distilled_text else ''
                })

            # Format prompt
            prompt = DAILY_SUMMARY_AP_STYLE.format(
                event_name=event.canonical_name,
                date=date,
                country=country,
                articles_info=articles_info
            )

            # Call LLM
            response = gai(
                sys_prompt="You are a factual news reporter following AP style guidelines.",
                user_prompt=prompt,
                model="gpt-4o"  # Use GPT-4 for better AP-style compliance
            )

            # Store summary
            event_summary = EventSummary(
                period_type=PeriodType.DAILY,
                period_start=date,
                period_end=date,
                event_name=event.canonical_name,
                initiating_country=country,
                narrative_summary={
                    'overview': response['overview'],
                    'outcomes': response['outcomes'],
                    'source_link': build_hyperlink(doc_ids),
                    'source_count': len(doc_ids),
                    'sources_used': response.get('sources_used', []),
                    'style': 'AP'  # Flag for AP-style summaries
                },
                ...
            )
            session.add(event_summary)
            session.flush()

            # Store source links
            for doc_id in doc_ids:
                link = EventSourceLink(
                    event_summary_id=event_summary.id,
                    doc_id=doc_id,
                    contribution_weight=1.0
                )
                session.add(link)

        session.commit()
```

---

## Quality Control Checklist

Before accepting any LLM-generated summary, verify:

### ✅ **AP-Style Compliance**
- [ ] No analytical language ("strategic," "significant," "important")
- [ ] No speculation about intent or impact
- [ ] No explanations of "why" or "what it means"
- [ ] All claims attributed to sources
- [ ] Past tense for completed actions
- [ ] Specific dates, times, numbers, locations
- [ ] 2-3 sentence paragraph structure

### ✅ **Factual Accuracy**
- [ ] Every fact traceable to source articles
- [ ] No invented details or assumptions
- [ ] Quotes/paraphrases match source material
- [ ] Numbers and dates correct
- [ ] Names and titles accurate

### ✅ **Source Attribution**
- [ ] Every claim has attribution
- [ ] Source names spelled correctly
- [ ] Attribution format follows AP style
- [ ] Multiple sources cited when available

---

## AP Style Quick Reference

### **Attribution Phrases**
- "according to [source]"
- "[official] said"
- "[source] reported"
- "a statement said"
- "officials announced"
- "data showed"
- "the report said"

### **Forbidden Phrases**
- ❌ "This demonstrates..."
- ❌ "The significant/important/strategic..."
- ❌ "In order to..."
- ❌ "This will likely..."
- ❌ "The move aimed to..."
- ❌ "Seeking to..."
- ❌ "The development reflects..."

### **Neutral Verbs**
✅ Use: said, reported, announced, issued, showed, indicated, stated
❌ Avoid: claimed, alleged, insisted, sought to, aimed to

---

## Updated Dashboard Display

```python
def display_event_summary(event_summary):
    """Display AP-style factual summary."""

    st.subheader(event_summary.event_name)

    # Display overview
    st.markdown("**Overview:**")
    st.write(event_summary.narrative_summary['overview'])

    # Display outcomes
    st.markdown("**Outcomes:**")
    st.write(event_summary.narrative_summary['outcomes'])

    # Source link
    source_count = event_summary.narrative_summary.get('source_count', 0)
    source_link = event_summary.narrative_summary.get('source_link')

    if source_link:
        st.markdown(
            f"📰 **[View All {source_count} Source Articles]({source_link})**"
        )

    # Note about style
    st.caption("Summary follows AP reporting standards - factual reporting without analysis.")
```

---

## Example Monthly Report Format

```
┌────────────────────────────────────────────────────────────┐
│ IRAN - AUGUST 2024 FACTUAL SUMMARY                        │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ Top Events (by article coverage):                          │
│                                                             │
│ 1. Arbaeen Pilgrimage Support Services                    │
│    89 articles | Aug 1-31                                  │
│                                                             │
│    Overview:                                                │
│    Iran operated special border arrangements for Arbaeen   │
│    pilgrims throughout August, opening seven border         │
│    crossings and deploying 180 medical teams, according to │
│    Iranian state media reports and Red Crescent statements  │
│    issued during the month. The pilgrimage period peaked    │
│    Aug. 24-27 with the highest daily crossing numbers,     │
│    border control data showed. Iraqi and Iranian officials  │
│    held coordination meetings weekly and issued joint       │
│    statements on logistics, security and healthcare         │
│    cooperation, both governments' media offices reported.   │
│                                                             │
│    Outcomes:                                                │
│    A total of 4.2 million pilgrims crossed from Iran into   │
│    Iraq through the designated border points in August,     │
│    according to final figures released by Iranian border    │
│    authorities on Aug. 31. The Iranian Red Crescent said    │
│    its teams provided medical services to 127,000 pilgrims  │
│    at 47 stations during the month, according to the        │
│    organization's final report. Iraqi Foreign Minister      │
│    Fuad Hussein thanked Iran for the cooperation in a       │
│    statement issued Aug. 30, calling the coordination       │
│    "successful," state media reported.                      │
│                                                             │
│    📰 [View All 89 Source Articles]                        │
│                                                             │
│ ──────────────────────────────────────────────────────────│
│                                                             │
│ 2. Russia-Iran Defense Cooperation                         │
│    67 articles | Aug 5-28                                  │
│                                                             │
│    Overview:                                                │
│    Russian and Iranian defense officials held three         │
│    meetings in August to discuss military-technical         │
│    cooperation, both countries' defense ministries said in  │
│    statements. The officials signed memorandums on UAV      │
│    technology and air defense systems on Aug. 15 and Aug.   │
│    22, according to documents posted on official websites.  │
│    Both countries announced plans for joint naval exercises │
│    in the Caspian Sea scheduled for September, the          │
│    ministries said.                                         │
│                                                             │
│    Outcomes:                                                │
│    Russia agreed to send technical advisers to Iran for     │
│    defense industry projects, the Aug. 15 memorandum said.  │
│    Iranian Defense Minister Mohammad Reza Ashtiani said     │
│    the cooperation would include "technology transfer" in   │
│    a statement issued Aug. 22. Russian officials confirmed  │
│    plans to invest in an Iranian defense manufacturing      │
│    facility, according to an Aug. 28 announcement from      │
│    Russia's Federal Service for Military-Technical          │
│    Cooperation.                                             │
│                                                             │
│    📰 [View All 67 Source Articles]                        │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

---

## Cost Impact

AP-style prompts are slightly longer but cost remains similar:
- **Daily summaries:** ~$0.70 (vs $0.66)
- **Weekly summaries:** ~$0.35 (vs $0.30)
- **Monthly summaries:** ~$0.12 (vs $0.10)
- **Total: ~$1.17** (minimal increase)

---

## Key Takeaways

1. **Factual reporting only** - No analysis, interpretation, or strategic significance
2. **Strict attribution** - Every claim must cite a source
3. **AP-style paragraphs** - 2-3 sentences, past tense, specific details
4. **Verifiable facts** - Everything must be traceable to source articles
5. **Neutral language** - No subjective descriptors or speculation

This approach produces **credible, defensible summaries** suitable for professional briefings and official use.

Ready to implement with these AP-style constraints?
