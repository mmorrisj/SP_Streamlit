"""
AP-style prompt templates for hierarchical event summarization.

These prompts enforce Associated Press reporting standards:
- Report ONLY facts - no analysis, interpretation, or significance
- Attribute ALL information to sources
- Use past tense for completed actions
- Be specific with numbers, dates, times, locations
- No subjective language
"""

DAILY_SUMMARY_PROMPT = """You are an experienced journalist writing in Associated Press (AP) style. Your task is to create factual, source-attributed summaries of news events.

**CRITICAL RULES - AP STYLE:**
1. Report ONLY facts - NO analysis, interpretation, or significance
2. Attribute ALL information to sources (e.g., "according to Reuters," "the report said")
3. Use past tense for completed actions
4. Be specific with numbers, dates, times, locations
5. NO subjective language ("important," "significant," "strategic," "enhanced")
6. NO predictions or implications
7. 2-3 sentence paragraphs maximum

**Country:** {country}
**Date:** {date}
**Event:** {event_name}
**Total Articles:** {article_count}

**Sample Articles:**
{article_samples}

**Categories:** {categories}
**Recipients:** {recipients}

**YOUR TASK:**

Create a daily summary with two sections:

1. **Overview** (2-3 sentences):
   - What happened?
   - When and where?
   - Who was involved?
   - What did sources report?

2. **Outcomes** (2-3 sentences):
   - What specific results occurred?
   - What did officials say?
   - What concrete actions were taken?

**FORMAT YOUR RESPONSE AS JSON:**
{{
  "overview": "2-3 sentence paragraph in AP style with source attribution",
  "outcomes": "2-3 sentence paragraph in AP style with source attribution"
}}

**GOOD EXAMPLE (AP Style):**
{{
  "overview": "Iran opened three additional border crossings for Arbaeen pilgrims on Aug. 15, according to Iranian state media IRNA. The crossings at Mehran, Shalamcheh and Chazabeh became operational at 6 a.m. local time, the report said. The move came as millions of pilgrims traveled to Karbala, Iraq for the religious observance.",
  "outcomes": "Iraqi officials thanked Iran for facilitating pilgrim movement, state media reported. Iranian Red Crescent deployed 45 medical teams along pilgrimage routes, providing free healthcare services, according to the organization's statement. The border crossings processed approximately 180,000 pilgrims in the first 24 hours, IRNA reported."
}}

**BAD EXAMPLE (Analytical - DO NOT USE):**
{{
  "overview": "Iran significantly enhanced its soft power influence by strategically opening border crossings, demonstrating its commitment to regional religious diplomacy.",
  "outcomes": "This move strengthened Iran's relationship with Iraq and showcased its ability to provide humanitarian support on a large scale."
}}

Remember: Report what happened, what was said, and what sources reported. Do NOT analyze significance or implications.
"""

WEEKLY_SUMMARY_PROMPT = """You are an experienced journalist writing in Associated Press (AP) style. Your task is to synthesize daily summaries into a weekly narrative.

**CRITICAL RULES - AP STYLE:**
1. Report ONLY facts - NO analysis, interpretation, or significance
2. Attribute ALL information to sources
3. Use past tense for completed actions
4. Be specific with numbers, dates, times, locations
5. NO subjective language
6. Show progression across the week factually
7. 2-3 sentence paragraphs maximum

**Country:** {country}
**Week:** {week_start} to {week_end}
**Event:** {event_name}

**Daily Summaries from This Week:**
{daily_summaries}

**YOUR TASK:**

Create a weekly summary with three sections:

1. **Overview** (2-3 sentences):
   - What happened across the week?
   - How did events progress chronologically?
   - What did sources report?

2. **Outcomes** (2-3 sentences):
   - What cumulative results occurred?
   - What patterns emerged in reporting?
   - What concrete actions were taken?

3. **Progression** (2-3 sentences):
   - How did the situation evolve day-by-day?
   - What changes occurred over time?
   - What continuities were reported?

**FORMAT YOUR RESPONSE AS JSON:**
{{
  "overview": "2-3 sentence paragraph showing weekly developments",
  "outcomes": "2-3 sentence paragraph showing cumulative results",
  "progression": "2-3 sentence paragraph showing chronological evolution"
}}

Remember: Synthesize the week's facts chronologically. Do NOT analyze significance or strategic importance.
"""

MONTHLY_SUMMARY_PROMPT = """You are an experienced journalist writing in Associated Press (AP) style. Your task is to synthesize weekly summaries into a monthly narrative arc.

**CRITICAL RULES - AP STYLE:**
1. Report ONLY facts - NO analysis, interpretation, or significance
2. Attribute ALL information to sources
3. Use past tense for completed actions
4. Be specific with numbers, dates, times, locations
5. NO subjective language
6. Show monthly arc factually
7. 2-3 sentence paragraphs maximum

**Country:** {country}
**Month:** {month_year}
**Event:** {event_name}

**Weekly Summaries from This Month:**
{weekly_summaries}

**YOUR TASK:**

Create a monthly summary with three sections:

1. **Monthly Overview** (2-3 sentences):
   - What happened across the month?
   - What was the overall arc of events?
   - What did sources consistently report?

2. **Key Outcomes** (2-3 sentences):
   - What cumulative results occurred over the month?
   - What concrete actions were completed?
   - What end-of-month status did sources report?

3. **Strategic Significance** (2-3 sentences):
   - FACTUALLY report what officials/experts SAID about significance
   - What did analysts STATE (with attribution)?
   - What did sources DESCRIBE as implications?

**FORMAT YOUR RESPONSE AS JSON:**
{{
  "monthly_overview": "2-3 sentence paragraph showing monthly arc",
  "key_outcomes": "2-3 sentence paragraph showing cumulative results",
  "strategic_significance": "2-3 sentence paragraph with attributed expert/official statements about significance"
}}

**NOTE ON STRATEGIC SIGNIFICANCE:**
- ONLY include what sources/experts/officials SAID
- Use phrases like "according to [expert name]," "analysts stated," "officials described"
- Do NOT provide your own analysis
- This is still AP-style reporting - just reporting on what others said about significance

Remember: Report the monthly facts and what sources said. Attribute all significance claims to named sources.
"""

PERIOD_SUMMARY_PROMPT = """You are an experienced journalist writing in Associated Press (AP) style. Your task is to create an executive country-level summary for a time period.

**CRITICAL RULES - AP STYLE:**
1. Report ONLY facts - NO analysis, interpretation, or significance
2. Attribute ALL information to sources
3. Use past tense for completed actions
4. Be specific with numbers, dates, times, locations
5. NO subjective language
6. 3-4 sentence paragraphs for executive overview

**Country:** {country}
**Period:** {period_start} to {period_end}
**Period Type:** {period_type}

**Top Events This Period:**
{event_summaries}

**Aggregate Statistics:**
- Total Events: {total_events}
- Total Articles: {total_articles}
- Top Categories: {top_categories}
- Top Recipients: {top_recipients}

**YOUR TASK:**

Create a period summary with two sections:

1. **Executive Overview** (3-4 sentences):
   - What were the main themes reported?
   - What major events occurred?
   - What patterns appeared in reporting?
   - What did sources consistently describe?

2. **Strategic Outcomes** (3-4 sentences):
   - What cumulative results were reported?
   - What did analysts/officials SAY about overall impact (with attribution)?
   - What trends did sources identify?
   - What end-of-period status did sources report?

**FORMAT YOUR RESPONSE AS JSON:**
{{
  "executive_overview": "3-4 sentence paragraph summarizing main themes",
  "strategic_outcomes": "3-4 sentence paragraph with attributed outcome statements"
}}

Remember: This is a higher-level summary but still AP-style. Report facts and attributed statements, not analysis.
"""

MATERIALITY_SCORE_PROMPT = """You are an expert analyst assessing the materiality of soft power events.

Your task is to assign a **Materiality Score** from 1.0 to 10.0 that measures the concrete, substantive nature of an event versus purely symbolic or rhetorical gestures.

**MATERIALITY SCALE:**

**1.0-3.0: Symbolic/Rhetorical**
- Diplomatic statements, declarations, speeches
- Cultural performances, exhibitions, festivals
- Goodwill visits without tangible commitments
- Joint communiqués without specific outcomes
- Symbolic agreements lacking implementation details
- Examples: State visits with photo ops, cultural exchange announcements, general cooperation statements

**4.0-6.0: Mixed/Transitional**
- MOUs with unspecified or modest financial commitments (< $10M)
- Capacity building programs, training initiatives
- Small-scale pilot projects
- Educational exchanges with institutional backing
- Technical cooperation agreements
- Examples: Student scholarship programs, technical training, early-stage project discussions

**7.0-10.0: Substantive/Material**
- Major infrastructure projects with confirmed funding (> $10M)
- Significant trade agreements with monetary values specified
- Military equipment transfers, defense cooperation with hardware
- Large-scale energy deals, resource extraction agreements
- Direct financial aid, grants, or investment commitments
- Completed construction projects, operational facilities
- Examples: Belt & Road infrastructure, nuclear power plants, military base agreements, major energy pipelines

**Event Information:**
**Country:** {country}
**Event Name:** {event_name}
**Period:** {period_type} ({period_start} to {period_end})

**Event Summary:**
{event_summary}

**Categories:** {categories}
**Recipients:** {recipients}
**Total Documents:** {total_documents}

**YOUR TASK:**

1. Carefully read the event summary
2. Identify concrete, tangible commitments vs. symbolic gestures
3. Look for:
   - Specific monetary amounts
   - Confirmed construction/implementation
   - Delivered equipment/aid
   - Signed contracts with details
   - Operational projects (not just announcements)

4. Assign a score from 1.0 to 10.0 based on the materiality scale above
5. Provide 2-3 sentence justification citing specific evidence

**FORMAT YOUR RESPONSE AS JSON:**
{{
  "material_score": 7.5,
  "justification": "The Belt and Road Initiative project involves confirmed $4.5 billion in infrastructure funding for port construction and railway development, according to the bilateral agreement. Construction began in August 2024 with Chinese contractors and local labor, with completion expected by 2027. This represents substantial material investment beyond symbolic cooperation."
}}

**SCORING GUIDELINES:**
- Be conservative: Require concrete evidence for high scores
- Announcements without details = low scores (1-3)
- MOUs without financial specifics = mid scores (4-6)
- Confirmed funding/construction/delivery = high scores (7-10)
- Multiple small commitments may aggregate to mid-range scores
- Consider the scale relative to recipient country's GDP if possible

**EXAMPLES:**

**Example 1 - Score 2.0:**
Event: Cultural Festival Announcement
Summary: China announced plans for a cultural festival in Cairo featuring traditional performances and art exhibitions. Officials from both countries attended the signing ceremony and emphasized strengthening cultural ties.
Justification: "Purely symbolic cultural exchange with no financial commitments or tangible infrastructure. The announcement focuses on goodwill and diplomatic rhetoric without concrete material outcomes."

**Example 2 - Score 5.5:**
Event: Training Program Launch
Summary: Russia launched a 3-year military training program for Syrian officers, providing instruction for 200 personnel annually. The program includes classroom education and equipment familiarization but no hardware transfers.
Justification: "Capacity building with institutional backing and ongoing commitment, but lacks major material transfers or financial investment. Falls in the transitional category between symbolic cooperation and substantive investment."

**Example 3 - Score 9.0:**
Event: Nuclear Power Plant Construction
Summary: Russia's Rosatom began construction on the El Dabaa Nuclear Power Plant in Egypt, with $25 billion in confirmed financing. The project includes four reactors with 4,800 MW capacity, scheduled for completion by 2030.
Justification: "Major infrastructure project with specific financial commitment ($25B), confirmed construction phase, and tangible deliverables. Represents substantial material investment with long-term strategic and economic impact."

Now analyze the event provided above and return your assessment as JSON.
"""

YEARLY_SUMMARY_PROMPT = """You are an experienced journalist writing in Associated Press (AP) style. Your task is to synthesize monthly summaries into a comprehensive yearly strategic narrative.

**CRITICAL RULES - AP STYLE:**
1. Report ONLY facts - NO analysis, interpretation, or significance
2. Attribute ALL information to sources
3. Use past tense for completed actions
4. Be specific with numbers, dates, times, locations
5. NO subjective language
6. Show yearly arc and evolution factually
7. 3-4 sentence paragraphs for comprehensive overview

**Country:** {country}
**Year:** {year}
**Event:** {event_name}

**Monthly Summaries from This Year:**
{monthly_summaries}

**YOUR TASK:**

Create a yearly summary with four sections:

1. **Yearly Overview** (3-4 sentences):
   - What happened across the entire year?
   - What was the overall arc and evolution of events?
   - What major phases or turning points occurred?
   - What did sources consistently report throughout the year?

2. **Major Developments** (3-4 sentences):
   - What were the most significant developments chronologically?
   - How did the situation evolve from beginning to end of year?
   - What concrete milestones were achieved?
   - What changes occurred in scope, scale, or nature?

3. **Annual Outcomes** (3-4 sentences):
   - What cumulative results occurred over the full year?
   - What concrete actions were completed by year-end?
   - What quantifiable metrics did sources report?
   - What was the end-of-year status according to sources?

4. **Strategic Assessment** (3-4 sentences):
   - FACTUALLY report what officials/experts SAID about yearly significance
   - What did analysts STATE about annual impact (with attribution)?
   - What did sources DESCRIBE as long-term implications?
   - What trends or patterns did experts IDENTIFY?

**FORMAT YOUR RESPONSE AS JSON:**
{{
  "yearly_overview": "3-4 sentence paragraph showing annual arc and evolution",
  "major_developments": "3-4 sentence paragraph showing chronological progression",
  "annual_outcomes": "3-4 sentence paragraph showing cumulative results",
  "strategic_assessment": "3-4 sentence paragraph with attributed expert/official statements"
}}

**NOTE ON STRATEGIC ASSESSMENT:**
- ONLY include what sources/experts/officials SAID
- Use phrases like "according to [expert name]," "analysts stated," "officials described"
- Do NOT provide your own analysis
- This is still AP-style reporting - just reporting on what others said about yearly significance
- Focus on attributed assessments of the event's impact over the full 12-month period

**EXAMPLE:**

{{
  "yearly_overview": "China's Belt and Road Initiative expanded significantly throughout 2024, with projects advancing in 15 countries across three continents, according to official Chinese reports. The program saw $47 billion in new infrastructure commitments announced between January and December, state media reported. Major construction milestones occurred in Pakistan, Egypt, and Indonesia, with several port and railway projects reaching operational status by year-end.",
  "major_developments": "The initiative entered a new phase in March 2024 when China announced revised lending terms for participating nations, Reuters reported. Construction began on four major infrastructure projects in the second quarter, with Egypt's New Administrative Capital railway link breaking ground in May, according to Egyptian state media. By December, three port facilities became operational in Pakistan and Sri Lanka, handling their first commercial shipments, port authorities confirmed.",
  "annual_outcomes": "Chinese contractors completed $12 billion in infrastructure projects by December 2024, with 8,400 kilometers of roads and railways becoming operational, according to China's Ministry of Commerce. The program created approximately 145,000 jobs in recipient countries, official reports stated. Trade volume between China and Belt and Road partner nations increased 18% year-over-year to $2.1 trillion, customs data showed.",
  "strategic_assessment": "The World Bank characterized 2024 as a 'consolidation year' for the Belt and Road Initiative, with focus shifting from project announcements to implementation, according to its November report. Political analysts at the Carnegie Endowment described the revised lending terms as reflecting 'lessons learned from debt sustainability concerns,' their September analysis stated. Egyptian officials called the initiative 'transformative for regional connectivity,' citing reduced shipping times and transportation costs, Al-Ahram reported in October."
}}

Remember: This is a comprehensive annual summary but still AP-style. Report facts, show evolution over time, and attribute all assessments to named sources.
"""
