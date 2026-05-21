"""Prompt skeletons for proposition-level extraction.

Inputs are docs already filtered as soft-power relevant upstream, so there
is no relevance gate. Field names match shared/models/proposition_models.py.
"""

PROPOSITION_PROMPT_VERSION = "v0.7"


proposition_extraction_prompt = '''You are an expert in international relations tracking inter-country soft-power engagements. The provided text has already been identified as soft-power relevant. Decompose it into ATOMIC PROPOSITIONS: each proposition expresses ONE claim about ONE actor doing/saying/committing ONE thing toward ONE recipient.

==============================
LANGUAGE
==============================
The source text may be in ANY language (English, Arabic, Chinese, Russian, etc.). ALL OUTPUT FIELDS MUST BE IN ENGLISH. NO EXCEPTIONS. This includes:
- proposition_text, subject, predicate, object: English paraphrase/translation.
- initiator_actor, recipient_actor, third_parties: English names. Transliterate person names (e.g., "Amr Talaat") and translate organization/ministry names ("Ministry of Foreign Affairs of China", "Egyptian Space Agency"). Use the most common English form when one exists.
- entities (persons, organizations, projects, locations): English/transliterated.
- evidence_span.text: English translation of the source quote (NOT the original-language verbatim). If you want to preserve the verbatim source for traceability, put it in an optional "text_original" field. Default to English-only.
Country names: use standard English country names ("China", "Egypt", "Saudi Arabia") regardless of source language.

==============================
ATOMICITY (read carefully)
==============================
- One subject, one predicate, one object per proposition.
- A predicate MUST be a SINGLE verb phrase. If it contains "and" (e.g., "presented and proposed", "will visit and meet"), SPLIT it into two propositions.
- If a sentence chains multiple actions across the same actors (e.g., "China pledged $10M AND signed an MOU"), output TWO propositions.
- Do NOT merge separate actions across sentences just because they share actors.
- Skip sentences with no soft-power content; do NOT emit a proposition for them.

==============================
WHAT COUNTS AS A SOFT-POWER PROPOSITION
==============================
Emit propositions ONLY for explicit ACTS, STATEMENTS, or COMMITMENTS by an identifiable actor toward another actor or audience. Acceptable claim sources:
- An actor does something: "Minister X visited Y", "China signed an MOU with Egypt".
- An actor says/affirms/announces something: "Lin Xin expressed appreciation for cooperation".
- An actor commits to or proposes something: "Talaat proposed future joint plans".
- An instrument's stated purpose: "The Forum aims to exchange best practices" (the act is the convening; the purpose is its soft-power intent).

DO NOT emit propositions for:
- Editorial/positioning claims about a country's general standing or capability ("Egypt continues to strengthen its leading position in space"). These are author framing, not acts of soft power.
- Background context about historical relations unless tied to a specific present act.
- Generic capability descriptions ("The Egyptian Space Agency operates several labs") unless they describe a concrete act being shown/used in the engagement.
- Speculation or analyst commentary about consequences ("This visit could lead to...").
- DOMESTIC POLICY OR INTERNAL AFFAIRS: any claim where the initiator_country and recipient_country would be the SAME country (e.g. China imposes a tax on its own citizens; Iran addresses its own population; a head of state congratulates a domestic newspaper). Soft power flows BETWEEN countries; it is not a domestic act. If the only recipient of an action is the initiator country itself (or the initiator country's own institutions, citizens, or media), DROP the proposition.
- Multilateral statements with no identifiable foreign recipient ("China affirmed it is ready to work with all countries to promote peace") unless a specific foreign actor or country is named.
- ACTS BY PRIVATE INDIVIDUALS WITH NO STATE LINK: celebrities (actors, athletes, musicians, social-media figures) expressing personal opinions or running personal charity drives; private companies acting purely commercially without state backing; independent artists, journalists, or activists. These are personal acts, not country-level soft power. Drop the proposition.
  EXCEPTION — KEEP if the individual is acting in an official state, ministry, SOE, or state-affiliated NGO capacity (presidents, ministers, ambassadors, state-media editors, state-owned enterprise executives acting in their official role).
  Examples to DROP: "Jackie Chan expressed sorrow over Gaza"; "Hollywood actors raised $2M for Palestine"; "an Egyptian researcher published a book about China" (private scholar, no state link).
  Examples to KEEP: "Xi Jinping sent a congratulatory message" (head of state); "Lin Xin expressed appreciation" (vice minister); "Sinopec announced a refinery investment" (state-owned enterprise); "Confucius Institute opened a branch" (state-affiliated cultural body).

When in doubt: does this proposition describe a specific act, statement, or commitment by an identifiable state/ministry/SOE/multilateral actor toward an identifiable foreign actor or country? If the actor is a private individual or company with no state link, drop it.

==============================
SOFT-POWER DIRECTION (read carefully)
==============================
The fields `initiator_country` and `recipient_country` describe the SOFT-POWER DIRECTION, NOT the grammatical subject of the sentence.
- `initiator_country` = the country EXERTING influence (whose attraction, persuasion, inducement, or coercion is at work).
- `recipient_country` = the country being INFLUENCED.

The grammatical subject of the proposition often is a person/agency of a DIFFERENT country than the soft-power initiator. That is fine and expected.

WORKED EXAMPLE OF THE INVERSION
Source sentence: "Egypt's Minister of Communications traveled to Beijing to participate in the Forum on China-Africa Digital Cooperation organized by China's Ministry of Industry."
- subject: "Egypt's Minister of Communications" (grammatical actor)
- predicate: "traveled to participate in"
- object: "Forum on China-Africa Digital Cooperation"
- initiator_country: "China"   <-- China is exerting attraction by hosting the forum
- recipient_country: "Egypt"   <-- Egypt is being influenced
- initiator_actor: "Ministry of Industry and Information Technology of China"
- recipient_actor: "Ministry of Communications and Information Technology of Egypt"

WORKED EXAMPLE OF PASSIVE ADMIRATION (also inverts direction)
Source sentence: "Egyptian professors and Saudi research centers conduct studies to understand Chinese policies and society."
- subject: "Egyptian professors and Saudi research centers" (grammatical actor)
- predicate: "conduct studies to understand"
- object: "Chinese policies and society"
- initiator_country: "China"   <-- China is the SOURCE of attraction; its policies are being studied
- recipient_country: "Egypt" (or "Saudi Arabia" — one proposition per recipient)
- mechanism: "attraction"

Rule of thumb: if the grammatical subject is INFLUENCED BY, DRAWN TO, STUDYING, ADMIRING, IMITATING, or LEARNING FROM the grammatical object's country, the OBJECT'S country is the initiator (it is the source of attraction) and the SUBJECT'S country is the recipient (it is the audience being influenced).

If a proposition is purely a statement BY the initiator country (e.g., "Lin Xin expressed appreciation for cooperation"), the speaker's country is still the initiator IF the statement is a soft-power instrument (praise, framing, commitment-signaling).

==============================
PER-PROPOSITION FIELDS
==============================

PROPOSITION STRUCTURE
- proposition_text: 1-sentence natural-language paraphrase of the claim, self-contained.
- subject: the grammatical acting entity (string).
- predicate: a SINGLE verb phrase (lowercased, no "and").
- object: the target/thing acted on (string).
- claim_type: one of [action, commitment, statement, outcome, perception, capability].
- tense: one of [past, present, future].
- modality: one of [actual, planned, proposed, denied, speculative].
  Use "actual" only for events the text reports as having occurred. Use "planned"/"proposed" for pledges, announcements, scheduled visits, and proposed agreements.

ACTORS
- initiator_country: country exerting soft power (see direction rules above) - or null.
- initiator_actor: specific entity (e.g., "Ministry of Foreign Affairs of China", "Sinopec").
- initiator_actor_type: one of [state, ministry, SOE, company, NGO, individual, multilateral].
- recipient_country: country being influenced - or null.
- recipient_actor / recipient_actor_type: same pattern.
- third_parties: list of other involved actors (brokers, co-financiers, multilateral bodies).

TAXONOMY (closed enums - use "other" if nothing fits, do NOT invent values)

sp_domain - the channel of soft-power influence (REQUIRED). One of:
  economic_aid          - foreign aid, ODA, development assistance (non-loan)
  investment            - FDI, joint ventures, equity stakes
  trade                 - trade agreements, market access, tariff arrangements
  diplomatic_engagement - state visits, treaties, MOUs, summits, declarations
  cultural              - arts, sports, language, food, religion-adjacent culture
  educational           - scholarships, university partnerships, academic exchange
  media_information     - broadcasting, news, social media campaigns, narrative
  science_technology    - joint R&D, tech transfer, lab partnerships, standards
  health                - medical aid, vaccines, hospital construction, training
  humanitarian          - disaster relief, refugee assistance, food aid in crisis
  security_military     - military cooperation, training, arms sales, exercises
  governance            - institution-building, election support, legal aid
  religious             - mosque/church/temple projects, clergy training
  other                 - use only if none of the above fit

instrument_type - the specific mechanism (REQUIRED). One of:
  state_visit            - high-level travel, in-person meetings
  bilateral_agreement    - MOU, treaty, signed bilateral deal
  multilateral_forum     - summits, conferences, regional bodies (FOCAC, BRI forums, BRICS)
  loan                   - concessional or commercial lending
  grant                  - non-repayable funds
  debt_relief            - cancellation, restructuring
  direct_investment      - FDI, equity, joint venture funding
  infrastructure_project - roads, ports, power, telecom builds
  scholarship            - funded study abroad
  exchange_program       - non-degree academic/professional/youth exchange
  cultural_event         - festivals, exhibitions, performances, sporting events
  language_institute     - Confucius Institute, Goethe-Institut, Alliance Francaise, etc.
  media_broadcast        - state media outreach, op-eds, content distribution
  joint_research         - co-authored research, joint labs
  training_program       - professional/technical training delivered abroad
  aid_delivery           - shipment of supplies, medical missions
  statement              - public declarations, press releases, speeches as soft-power acts
  sanctions              - economic restrictions, asset freezes
  other                  - use if none above fit

mechanism - the Nye-style influence type (REQUIRED). One of:
  attraction  - values/culture/lifestyle appeal that the recipient is drawn to
  persuasion  - argumentation, framing, normative pressure, diplomatic discourse
  inducement  - tangible rewards: payments, projects, market access, gifts
  coercion    - threats, sanctions, conditional withdrawal of benefits

ENTITIES (named entities tied to THIS proposition only)
- entities: object with keys persons, organizations, projects, locations - each a list of strings.

QUANTITATIVE ANCHORS
- monetary_value: numeric amount as stated (no symbols), or null.
- currency: ISO currency code (USD, CNY, EUR, ...), or null.
- monetary_value_usd: best-effort USD conversion, or null if unstated and uncomputable.
- quantity / quantity_unit: e.g., 500 / "scholarships", 2 / "GW".
- timeframe: free-text duration ("over 5 years", "by 2030"), or null.

SCORING (0..1 unless noted)
- valence: -1..+1, sentiment of the action toward the recipient.
- salience_score: how prominent this claim is in the document (0=incidental, 1=headline).
- materiality_score: how concrete vs symbolic (0=rhetoric only, 1=binding/executed action with quantitative anchor).
- confidence: your confidence in the extraction.

TEMPORAL
- event_date: YYYY-MM-DD if stated; else best inferred date.
- date_precision: one of [day, month, quarter, year, unknown].

GEO
- location_name: city/region/country where the action occurs.
- lat_long: "lat,long" string if known.
- geo_scope: one of [bilateral, regional, multilateral, global].

EVIDENCE
- evidence_span: {"text": "<English quote / translation of the supporting source span, <=300 chars>"}
  Optionally include "text_original" with the verbatim source-language span for traceability:
    {"text": "<English>", "text_original": "<verbatim source>"}
  The "text" field MUST be English regardless of source language.

==============================
OUTPUT FORMAT
==============================
Return ONLY this JSON object:
{
  "doc_id": "<echo of provided doc_id>",
  "propositions": [ { ...fields above... }, ... ]
}

If the document contains no atomic soft-power claims after decomposition, return "propositions": [].

IMPORTANT: ONLY output the JSON. No prose, no markdown fences, no commentary.'''


# Stage-2 LLM-deconflict prompt skeleton (mirrors llm_deconflict_canonical_events.py).
proposition_consolidation_prompt = '''You are reviewing a candidate group of soft-power propositions that an embedding-similarity step has clustered together. Determine whether they describe the SAME underlying claim (same initiator_country, same recipient_country, same action, same object) at varying levels of specificity or paraphrase.

INPUT
A JSON list of candidate propositions, each with: id, proposition_text, initiator_country, recipient_country, sp_domain, instrument_type, event_date, monetary_value_usd.

TASK
1. Decide which propositions belong together as one canonical claim.
2. For each canonical group, pick the most informative proposition_text as the canonical_text.
3. Propositions that do NOT belong to the dominant group should be returned as their own singleton groups (do not drop them).

OUTPUT
{
  "groups": [
    {
      "canonical_text": "<chosen text>",
      "proposition_ids": ["<uuid>", "<uuid>"],
      "justification": "<short reason>"
    }
  ]
}

IMPORTANT: ONLY output the JSON.'''
