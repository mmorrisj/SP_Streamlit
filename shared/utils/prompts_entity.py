"""
Entity extraction prompts for soft power network mapping.

This module contains prompts for extracting organizations, companies, and key persons
from document distilled_text fields, along with their roles and topics of influence.
"""

# Role labels - function the entity plays in soft power transactions
ROLE_LABELS = [
    # Diplomatic roles
    "HEAD_OF_STATE",       # Presidents, prime ministers, monarchs
    "DIPLOMAT",            # Ambassadors, foreign ministers, envoys
    "NEGOTIATOR",          # Officials involved in crafting agreements
    "GOVERNMENT_OFFICIAL", # Ministers, agency heads, bureaucrats
    "LEGISLATOR",          # Parliament/congress members

    # Economic roles
    "FINANCIER",           # Banks, funds, lenders providing capital
    "INVESTOR",            # Entities providing equity/FDI
    "CONTRACTOR",          # Companies executing projects
    "DEVELOPER",           # Construction/infrastructure builders
    "TRADE_PARTNER",       # Import/export entities
    "OPERATOR",            # Entities running ongoing operations

    # Military roles
    "MILITARY_OFFICIAL",   # Generals, defense ministers
    "DEFENSE_SUPPLIER",    # Arms/equipment sellers
    "TRAINER",             # Military training providers

    # Cultural/Social roles
    "CULTURAL_INSTITUTION", # Museums, cultural institutes, exchange programs
    "EDUCATOR",            # Universities, schools, training organizations
    "MEDIA_ENTITY",        # Broadcasters, publishers, news outlets
    "RELIGIOUS_ENTITY",    # Religious organizations or leaders
    "HUMANITARIAN",        # Aid organizations, NGOs

    # Transaction-specific roles
    "BENEFICIARY",         # Recipient of investment/aid/assistance
    "HOST",                # Entity hosting event or project
    "LOCAL_PARTNER",       # In-country partner or joint venture
    "FACILITATOR",         # Broker, intermediary, matchmaker
    "SIGNATORY",           # Party signing an agreement
]

# Topic labels - domain of influence the entity operates in
TOPIC_LABELS = [
    # Economic topics
    "INFRASTRUCTURE",      # Roads, ports, bridges, buildings
    "ENERGY",              # Oil, gas, nuclear, renewables
    "FINANCE",             # Banking, loans, currency swaps
    "TRADE",               # Import/export, free trade agreements
    "TECHNOLOGY",          # Tech transfer, R&D partnerships
    "TELECOMMUNICATIONS",  # 5G, satellites, internet infrastructure
    "TRANSPORTATION",      # Rail, aviation, shipping
    "AGRICULTURE",         # Food security, farming, irrigation
    "MINING",              # Resource extraction, minerals
    "MANUFACTURING",       # Industrial production, factories

    # Diplomatic topics
    "BILATERAL_RELATIONS", # Country-to-country diplomatic ties
    "MULTILATERAL_FORUMS", # BRICS, SCO, UN, regional bodies
    "CONFLICT_MEDIATION",  # Peace talks, ceasefires, de-escalation
    "TREATY_NEGOTIATION",  # Formal international agreements

    # Military topics
    "ARMS_TRADE",          # Weapons sales, military equipment
    "MILITARY_COOPERATION", # Joint exercises, base access
    "DEFENSE_TRAINING",    # Military education, officer exchanges
    "SECURITY_ASSISTANCE", # Counterterrorism, intelligence sharing

    # Social topics
    "EDUCATION",           # Schools, universities, scholarships
    "HEALTHCARE",          # Hospitals, medical aid, pharmaceuticals
    "CULTURE",             # Arts, heritage, language (Confucius Institutes)
    "MEDIA",               # Broadcasting, journalism, film
    "RELIGION",            # Religious diplomacy, pilgrimage
    "HUMANITARIAN_AID",    # Disaster relief, refugee assistance
    "TOURISM",             # Travel promotion, hospitality
]

# Entity type labels
ENTITY_TYPES = [
    "PERSON",              # Individual (official, executive, diplomat)
    "GOVERNMENT_AGENCY",   # Ministry, department, embassy
    "STATE_OWNED_ENTERPRISE", # Government-controlled company
    "PRIVATE_COMPANY",     # Privately owned business
    "MULTILATERAL_ORG",    # International body (UN, BRICS, SCO)
    "NGO",                 # Non-governmental organization
    "EDUCATIONAL_INSTITUTION", # University, school, research institute
    "FINANCIAL_INSTITUTION", # Bank, investment fund
    "MILITARY_UNIT",       # Armed forces, defense ministry
    "MEDIA_ORGANIZATION",  # News outlet, broadcaster
    "RELIGIOUS_ORGANIZATION", # Religious body, church, mosque
]

# Relationship type labels
RELATIONSHIP_TYPES = [
    "FUNDS",               # Provides money/financing to
    "INVESTS_IN",          # Makes equity investment in
    "CONTRACTS_WITH",      # Has contract/agreement with
    "PARTNERS_WITH",       # Forms partnership/JV with
    "SIGNS_AGREEMENT",     # Signs formal agreement with
    "MEETS_WITH",          # Has meeting/diplomatic encounter with
    "EMPLOYS",             # Has employment relationship with
    "OWNS",                # Has ownership stake in
    "REPRESENTS",          # Officially represents (person->org)
    "HOSTS",               # Hosts event/visit for
    "TRAINS",              # Provides training to
    "SUPPLIES",            # Provides goods/equipment to
    "MEDIATES",            # Mediates between parties
    "ANNOUNCES",           # Makes public announcement about
]


entity_extraction_prompt = '''You are an expert at identifying key actors in international soft power activities. Your task is to extract all significant entities (persons, organizations, companies) from the provided text, characterize their role in the soft power exchange, AND identify the relationships between them.

CONTEXT:
- Initiating Country: {initiating_country}
- Recipient Country: {recipient_country}
- Category: {category}
- Subcategory: {subcategory}

TEXT TO ANALYZE:
{distilled_text}

INSTRUCTIONS:
Extract every significant entity mentioned in the text. For each entity provide:

1. **name**: The entity's full name as mentioned (standardize to English)
2. **entity_type**: One of: PERSON, GOVERNMENT_AGENCY, STATE_OWNED_ENTERPRISE, PRIVATE_COMPANY, MULTILATERAL_ORG, NGO, EDUCATIONAL_INSTITUTION, FINANCIAL_INSTITUTION, MILITARY_UNIT, MEDIA_ORGANIZATION, RELIGIOUS_ORGANIZATION
3. **country**: The country the entity is affiliated with
4. **side**: Whether the entity is on the "initiating" or "recipient" side of the soft power exchange
5. **role_label**: The function this entity plays. Choose from:
   - Diplomatic: HEAD_OF_STATE, DIPLOMAT, NEGOTIATOR, GOVERNMENT_OFFICIAL, LEGISLATOR
   - Economic: FINANCIER, INVESTOR, CONTRACTOR, DEVELOPER, TRADE_PARTNER, OPERATOR
   - Military: MILITARY_OFFICIAL, DEFENSE_SUPPLIER, TRAINER
   - Cultural/Social: CULTURAL_INSTITUTION, EDUCATOR, MEDIA_ENTITY, RELIGIOUS_ENTITY, HUMANITARIAN
   - Transaction: BENEFICIARY, HOST, LOCAL_PARTNER, FACILITATOR, SIGNATORY
6. **topic_label**: The domain of influence. Choose from:
   - Economic: INFRASTRUCTURE, ENERGY, FINANCE, TRADE, TECHNOLOGY, TELECOMMUNICATIONS, TRANSPORTATION, AGRICULTURE, MINING, MANUFACTURING
   - Diplomatic: BILATERAL_RELATIONS, MULTILATERAL_FORUMS, CONFLICT_MEDIATION, TREATY_NEGOTIATION
   - Military: ARMS_TRADE, MILITARY_COOPERATION, DEFENSE_TRAINING, SECURITY_ASSISTANCE
   - Social: EDUCATION, HEALTHCARE, CULTURE, MEDIA, RELIGION, HUMANITARIAN_AID, TOURISM
7. **role_description**: A brief (1-2 sentence) description of what this entity did or their involvement
8. **title**: For PERSON entities only - their official title/position (e.g., "Foreign Minister", "CEO")
9. **parent_organization**: For PERSON entities - the organization they represent, if mentioned

RELATIONSHIP EXTRACTION:
After extracting entities, identify relationships between them. For each relationship provide:

1. **source_entity**: Name of the entity initiating/performing the action (must match an entity name above)
2. **target_entity**: Name of the entity receiving/affected by the action (must match an entity name above)
3. **relationship_type**: One of:
   - FUNDS: Provides money/financing to
   - INVESTS_IN: Makes equity investment in
   - CONTRACTS_WITH: Has contract/agreement with
   - PARTNERS_WITH: Forms partnership/JV with
   - SIGNS_AGREEMENT: Signs formal agreement with
   - MEETS_WITH: Has meeting/diplomatic encounter with
   - EMPLOYS: Has employment relationship with
   - OWNS: Has ownership stake in
   - REPRESENTS: Officially represents (person->org)
   - HOSTS: Hosts event/visit for
   - TRAINS: Provides training to
   - SUPPLIES: Provides goods/equipment to
   - MEDIATES: Mediates between parties
   - ANNOUNCES: Makes public announcement about
4. **relationship_description**: Brief description of the specific interaction
5. **monetary_value**: If a financial relationship, the value in USD (null if not applicable)
6. **confidence**: HIGH, MEDIUM, or LOW based on how explicit the relationship is in the text

EXTRACTION RULES:
- Extract ALL named entities, even if mentioned briefly
- For persons, always try to identify their title and organization
- If an entity appears multiple times with different roles, create separate entries
- Infer the side (initiating/recipient) from context - entities from {initiating_country} are "initiating", entities from {recipient_country} are "recipient"
- Third-party entities (neither initiating nor recipient country) should use "third_party" for side
- Be specific with role_label - choose the most precise label for the context
- The topic_label should reflect what domain this entity operates in for THIS transaction
- For relationships, only extract those explicitly stated or strongly implied in the text
- Persons often REPRESENT organizations - capture these relationships

OUTPUT FORMAT:
Return a JSON object with the following structure:
{{
  "entities": [
    {{
      "name": "China National Petroleum Corporation",
      "entity_type": "STATE_OWNED_ENTERPRISE",
      "country": "China",
      "side": "initiating",
      "role_label": "CONTRACTOR",
      "topic_label": "ENERGY",
      "role_description": "Signed agreement to develop oil field infrastructure",
      "title": null,
      "parent_organization": null
    }},
    {{
      "name": "Wang Yi",
      "entity_type": "PERSON",
      "country": "China",
      "side": "initiating",
      "role_label": "DIPLOMAT",
      "topic_label": "BILATERAL_RELATIONS",
      "role_description": "Met with counterpart to discuss strategic partnership",
      "title": "Foreign Minister",
      "parent_organization": "Ministry of Foreign Affairs"
    }},
    {{
      "name": "Saudi Aramco",
      "entity_type": "STATE_OWNED_ENTERPRISE",
      "country": "Saudi Arabia",
      "side": "recipient",
      "role_label": "LOCAL_PARTNER",
      "topic_label": "ENERGY",
      "role_description": "Joint venture partner for refinery project",
      "title": null,
      "parent_organization": null
    }},
    {{
      "name": "Ministry of Foreign Affairs",
      "entity_type": "GOVERNMENT_AGENCY",
      "country": "China",
      "side": "initiating",
      "role_label": "GOVERNMENT_OFFICIAL",
      "topic_label": "BILATERAL_RELATIONS",
      "role_description": "Chinese foreign ministry overseeing diplomatic engagement",
      "title": null,
      "parent_organization": null
    }}
  ],
  "relationships": [
    {{
      "source_entity": "China National Petroleum Corporation",
      "target_entity": "Saudi Aramco",
      "relationship_type": "PARTNERS_WITH",
      "relationship_description": "Formed joint venture for refinery development project",
      "monetary_value": null,
      "confidence": "HIGH"
    }},
    {{
      "source_entity": "Wang Yi",
      "target_entity": "Ministry of Foreign Affairs",
      "relationship_type": "REPRESENTS",
      "relationship_description": "Foreign Minister representing the ministry in negotiations",
      "monetary_value": null,
      "confidence": "HIGH"
    }}
  ],
  "entity_count": 4,
  "relationship_count": 2,
  "primary_transaction_type": "ENERGY",
  "extraction_notes": "Brief note on any ambiguities or assumptions made"
}}

IMPORTANT:
- Output ONLY valid JSON
- Extract entities even if information is partial - use null for unknown fields
- Do not invent entities not mentioned in the text
- Standardize country names (e.g., "PRC" -> "China", "UAE" -> "United Arab Emirates")
- All relationship source_entity and target_entity names MUST match entity names in the entities array
'''


entity_resolution_prompt = '''You are an expert at entity resolution and deduplication. Given a list of extracted entities, identify which entries refer to the same real-world entity and propose a canonical name.

ENTITIES TO RESOLVE:
{entity_list}

For each group of duplicate entities, provide:
1. canonical_name: The standardized, official name to use
2. entity_type: The correct entity type
3. aliases: List of all name variations found
4. country: The country affiliation
5. merge_ids: List of entity IDs to merge

OUTPUT FORMAT:
{{
  "resolutions": [
    {{
      "canonical_name": "China National Petroleum Corporation",
      "entity_type": "STATE_OWNED_ENTERPRISE",
      "aliases": ["CNPC", "China National Petroleum Corp", "China National Petroleum Corporation (CNPC)"],
      "country": "China",
      "merge_ids": ["entity_1", "entity_5", "entity_12"]
    }}
  ],
  "no_duplicates": ["entity_2", "entity_3"]
}}

Consider these as potential duplicates:
- Abbreviated vs full names (CNPC vs China National Petroleum Corporation)
- With/without titles (President Xi vs Xi Jinping)
- Transliteration variations
- Common misspellings

IMPORTANT: Only merge entities that definitively refer to the same real-world entity.
'''


relationship_extraction_prompt = '''You are an expert at identifying relationships between entities in soft power transactions. Given a document with extracted entities, identify the relationships between them.

DOCUMENT CONTEXT:
- Date: {date}
- Initiating Country: {initiating_country}
- Recipient Country: {recipient_country}
- Category: {category}

EXTRACTED ENTITIES:
{entities_json}

ORIGINAL TEXT:
{distilled_text}

INSTRUCTIONS:
Identify relationships between the entities. For each relationship provide:

1. **source_entity**: Name of the entity initiating/performing the action
2. **target_entity**: Name of the entity receiving/affected by the action
3. **relationship_type**: One of:
   - FUNDS: Provides money/financing to
   - INVESTS_IN: Makes equity investment in
   - CONTRACTS_WITH: Has contract/agreement with
   - PARTNERS_WITH: Forms partnership/JV with
   - SIGNS_AGREEMENT: Signs formal agreement with
   - MEETS_WITH: Has meeting/diplomatic encounter with
   - EMPLOYS: Has employment relationship with
   - OWNS: Has ownership stake in
   - REPRESENTS: Officially represents (person->org)
   - HOSTS: Hosts event/visit for
   - TRAINS: Provides training to
   - SUPPLIES: Provides goods/equipment to
   - MEDIATES: Mediates between parties
   - ANNOUNCES: Makes public announcement about
4. **relationship_description**: Brief description of the specific interaction
5. **monetary_value**: If a financial relationship, the value in USD (null if not applicable)
6. **confidence**: HIGH, MEDIUM, or LOW based on how explicit the relationship is in the text

OUTPUT FORMAT:
{{
  "relationships": [
    {{
      "source_entity": "China Development Bank",
      "target_entity": "Egyptian Ministry of Finance",
      "relationship_type": "FUNDS",
      "relationship_description": "Provided $3 billion loan for infrastructure development",
      "monetary_value": 3000000000,
      "confidence": "HIGH"
    }},
    {{
      "source_entity": "Wang Yi",
      "target_entity": "Ministry of Foreign Affairs",
      "relationship_type": "REPRESENTS",
      "relationship_description": "Foreign Minister representing China in negotiations",
      "monetary_value": null,
      "confidence": "HIGH"
    }}
  ]
}}

IMPORTANT:
- Only extract relationships explicitly stated or strongly implied in the text
- A single document may have multiple relationships
- Persons often REPRESENT organizations - capture these
- Financial relationships should include monetary_value when mentioned
'''
