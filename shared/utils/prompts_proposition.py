"""Prompt skeletons for proposition-level extraction.

Two-stage prompt design:
  1. relevance_gate_prompt  - cheap first pass; decide if doc has any soft-power signal
  2. proposition_extraction_prompt - decompose doc into atomic propositions

Both return strict JSON. Field names match shared/models/proposition_models.py.
"""

PROPOSITION_PROMPT_VERSION = "v0.1"


relevance_gate_prompt = '''You are an expert in international relations and soft power analysis. Soft power is the ability of one country to shape the preferences and behaviors of another through cultural, economic, diplomatic, informational, or technological means rather than coercion.

Read the provided text and decide whether it contains ANY soft-power-relevant content involving one country acting toward another (including statements, commitments, actions, or perceptions).

Output ONLY this JSON:
{"is_softpower_relevant": true|false, "relevance_justification": "<<=200 chars explaining the decision>"}

IMPORTANT: ONLY return the JSON. No extra text.'''


proposition_extraction_prompt = '''You are an expert in international relations tracking inter-country soft-power engagements. Your task is to decompose the provided text into ATOMIC PROPOSITIONS: each proposition expresses ONE claim about ONE actor doing/saying/committing ONE thing toward ONE recipient.

Rules for atomicity:
- One subject, one predicate, one object per proposition.
- If a sentence contains multiple claims (e.g., "{country_a} pledged $10M AND signed an MOU"), output TWO propositions.
- Do NOT merge separate actions across sentences just because they share actors.
- Skip content that is not soft-power relevant (sports scores, weather, unrelated domestic news).

For EACH proposition, extract the fields below. Use null when a value is not stated; do not invent.

PROPOSITION STRUCTURE
- proposition_text: 1-sentence natural-language paraphrase of the claim, self-contained.
- subject: the acting entity (string).
- predicate: the action/relation (verb phrase, lowercased).
- object: the target/thing acted on (string).
- claim_type: one of [action, commitment, statement, outcome, perception, capability].
- tense: one of [past, present, future].
- modality: one of [actual, planned, proposed, denied, speculative].
  Use "actual" only for events the text reports as having occurred. Use "planned"/"proposed" for pledges and announcements.

ACTORS
- initiator_country: ISO country name of the initiating state (or null).
- initiator_actor: specific entity (e.g., "Ministry of Foreign Affairs of {country}", "Sinopec").
- initiator_actor_type: one of [state, ministry, SOE, company, NGO, individual, multilateral].
- recipient_country: ISO country name of the recipient (or null).
- recipient_actor / recipient_actor_type: same pattern.
- third_parties: list of other involved actors (brokers, co-financiers, multilateral bodies).

CATEGORIZATION (use the project taxonomy)
- category: one of [Economic, Social, Diplomacy, Military].
- subcategory: per the project taxonomy (Trade, Finance, Infrastructure, Cultural, Education, Media, ...).
- soft_power_dimension: one of [cultural, political_values, foreign_policy, economic, security, informational, technological].
- instrument_type: one of [aid, investment, MOU, cultural_exchange, scholarship, infrastructure, military_coop, media, sanctions, statement, other].
- mechanism: one of [attraction, persuasion, coercion, co_option].

ENTITIES (named entities tied to THIS proposition only)
- entities: object with keys persons, organizations, projects, locations - each a list of strings.

QUANTITATIVE ANCHORS
- monetary_value: numeric amount as stated (no symbols), or null.
- currency: ISO currency code (USD, CNY, EUR, ...), or null.
- monetary_value_usd: best-effort conversion to USD, or null if unstated and uncomputable.
- quantity / quantity_unit: e.g., 500 / "scholarships", 2 / "GW".
- timeframe: free-text duration ("over 5 years", "by 2030"), or null.

SCORING (0..1 unless noted)
- valence: -1..+1, sentiment of the action toward the recipient (positive=friendly/beneficial, negative=hostile/coercive).
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
- evidence_span: object {"text": "<verbatim quote, <=300 chars>"}. Character offsets may be added by the post-processor.

OUTPUT FORMAT
Return ONLY this JSON object:
{
  "doc_id": "<echo of provided doc_id>",
  "is_softpower_relevant": true|false,
  "relevance_justification": "<short reason>",
  "propositions": [ { ...fields above... }, ... ]
}

If is_softpower_relevant is false, "propositions" MUST be an empty list.

IMPORTANT: ONLY output the JSON. No prose, no markdown fences, no commentary.'''


# Stage-2 LLM-deconflict prompt skeleton (mirrors llm_deconflict_canonical_events.py).
proposition_consolidation_prompt = '''You are reviewing a candidate group of soft-power propositions that an embedding-similarity step has clustered together. Determine whether they describe the SAME underlying claim (same actors, same action, same object) at varying levels of specificity or paraphrase.

INPUT
A JSON list of candidate propositions, each with: id, proposition_text, initiator_country, recipient_country, category, instrument_type, event_date, monetary_value_usd.

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
