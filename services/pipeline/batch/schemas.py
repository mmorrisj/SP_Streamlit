"""
JSON Schema definitions for OpenAI Structured Outputs.

Each schema enforces the exact output format expected by batch result processors,
eliminating JSON parsing failures and guaranteeing field presence/types.

Usage with OpenAI Batch API:
    response_format={
        "type": "json_schema",
        "json_schema": SCHEMA_CLUSTER_DECONFLICT
    }

See: https://platform.openai.com/docs/guides/structured-outputs
"""

# -- Cluster Deconfliction --
SCHEMA_CLUSTER_DECONFLICT = {
    "name": "cluster_deconflict",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "same_event": {"type": "boolean"},
            "groups": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"}
                }
            },
            "stages_identified": {
                "type": "array",
                "items": {"type": "string"}
            },
            "confidence": {"type": "number"}
        },
        "required": ["reasoning", "same_event", "groups", "stages_identified", "confidence"],
        "additionalProperties": False
    }
}

# -- Canonical Event Deconfliction --
_SPLIT_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "indices": {
            "type": "array",
            "items": {"type": "integer"}
        },
        "canonical_name": {"type": "string"}
    },
    "required": ["indices", "canonical_name"],
    "additionalProperties": False
}

SCHEMA_CANONICAL_DECONFLICT = {
    "name": "canonical_deconflict",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "same_event": {"type": "boolean"},
            "best_canonical_name": {"type": ["string", "null"]},
            "reasoning": {"type": "string"},
            "should_split": {"type": "boolean"},
            "split_groups": {
                "type": "array",
                "items": _SPLIT_GROUP_SCHEMA
            }
        },
        "required": ["same_event", "best_canonical_name", "reasoning", "should_split", "split_groups"],
        "additionalProperties": False
    }
}

# -- Entity Extraction (shared schema for events and documents) --
_ENTITY_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_name": {"type": "string"},
        "role": {"type": "string"},
        "country_affiliation": {"type": "string"},
        "context_snippet": {"type": "string"}
    },
    "required": ["entity_name", "role", "country_affiliation", "context_snippet"],
    "additionalProperties": False
}

SCHEMA_ENTITY_EXTRACT = {
    "name": "entity_extract",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "persons": {"type": "array", "items": _ENTITY_ITEM_SCHEMA},
            "organizations": {"type": "array", "items": _ENTITY_ITEM_SCHEMA},
            "companies": {"type": "array", "items": _ENTITY_ITEM_SCHEMA},
            "locations": {"type": "array", "items": _ENTITY_ITEM_SCHEMA}
        },
        "required": ["persons", "organizations", "companies", "locations"],
        "additionalProperties": False
    }
}

# -- Materiality Scoring (events and summaries) --
SCHEMA_SCORE_MATERIALITY = {
    "name": "score_materiality",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "material_score": {"type": "number"},
            "justification": {"type": "string"}
        },
        "required": ["material_score", "justification"],
        "additionalProperties": False
    }
}

# -- Entity Deconfliction --
SCHEMA_ENTITY_DECONFLICT = {
    "name": "entity_deconflict",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "same_entity": {"type": "boolean"},
            "explanation": {"type": "string"},
            "canonical_name": {"type": "string"},
            "primary_role": {"type": "string"},
            "country_affiliation": {"type": "string"},
            "groups": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"}
                }
            }
        },
        "required": ["same_entity", "explanation", "canonical_name", "primary_role", "country_affiliation", "groups"],
        "additionalProperties": False
    }
}

# -- Canonical Entity Deconfliction --
_ENTITY_SPLIT_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "indices": {
            "type": "array",
            "items": {"type": "integer"}
        },
        "canonical_name": {"type": "string"},
        "primary_role": {"type": "string"}
    },
    "required": ["indices", "canonical_name", "primary_role"],
    "additionalProperties": False
}

SCHEMA_CANONICAL_ENTITY_DECONFLICT = {
    "name": "canonical_entity_deconflict",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "same_entity": {"type": "boolean"},
            "best_canonical_name": {"type": ["string", "null"]},
            "best_primary_role": {"type": "string"},
            "reasoning": {"type": "string"},
            "should_split": {"type": "boolean"},
            "split_groups": {
                "type": "array",
                "items": _ENTITY_SPLIT_GROUP_SCHEMA
            }
        },
        "required": ["same_entity", "best_canonical_name", "best_primary_role", "reasoning", "should_split", "split_groups"],
        "additionalProperties": False
    }
}

# -- Daily Summary --
SCHEMA_DAILY_SUMMARY = {
    "name": "daily_summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "outcomes": {"type": "string"}
        },
        "required": ["overview", "outcomes"],
        "additionalProperties": False
    }
}

# -- Weekly Summary --
SCHEMA_WEEKLY_SUMMARY = {
    "name": "weekly_summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "outcomes": {"type": "string"},
            "progression": {"type": "string"}
        },
        "required": ["overview", "outcomes", "progression"],
        "additionalProperties": False
    }
}

# -- Monthly Summary --
SCHEMA_MONTHLY_SUMMARY = {
    "name": "monthly_summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "monthly_overview": {"type": "string"},
            "key_outcomes": {"type": "string"},
            "strategic_significance": {"type": "string"}
        },
        "required": ["monthly_overview", "key_outcomes", "strategic_significance"],
        "additionalProperties": False
    }
}

# -- Entity Description --
_KEY_ACTIVITIES_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_function": {"type": "string"},
        "notable_actions": {"type": "array", "items": {"type": "string"}},
        "key_relationships": {"type": "array", "items": {"type": "string"}},
        "geographic_focus": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["primary_function", "notable_actions", "key_relationships", "geographic_focus"],
    "additionalProperties": False
}

SCHEMA_ENTITY_DESCRIPTION = {
    "name": "entity_description",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "entity_description": {"type": "string"},
            "key_activities": _KEY_ACTIVITIES_SCHEMA
        },
        "required": ["entity_description", "key_activities"],
        "additionalProperties": False
    }
}

# -- Relationship Classification --
SCHEMA_RELATIONSHIP_CLASSIFICATION = {
    "name": "relationship_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "relationship_type": {"type": "string"},
            "relationship_description": {"type": "string"}
        },
        "required": ["relationship_type", "relationship_description"],
        "additionalProperties": False
    }
}

# -- Bilateral Summary --
_MAJOR_INITIATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "timeframe": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["name", "description", "timeframe", "categories"],
    "additionalProperties": False
}

_MATERIAL_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "justification": {"type": "string"}
    },
    "required": ["score", "justification"],
    "additionalProperties": False
}

SCHEMA_BILATERAL_SUMMARY = {
    "name": "bilateral_summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "key_themes": {"type": "array", "items": {"type": "string"}},
            "major_initiatives": {"type": "array", "items": _MAJOR_INITIATIVE_SCHEMA},
            "trend_analysis": {"type": "string"},
            "current_status": {"type": "string"},
            "notable_developments": {"type": "array", "items": {"type": "string"}},
            "material_assessment": _MATERIAL_ASSESSMENT_SCHEMA
        },
        "required": ["overview", "key_themes", "major_initiatives", "trend_analysis",
                      "current_status", "notable_developments", "material_assessment"],
        "additionalProperties": False
    }
}


# -- Event Rename (specificity improvement) --
SCHEMA_EVENT_RENAME = {
    "name": "event_rename",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "specific_event_name": {"type": "string"},
            "reasoning": {"type": "string"},
            "confidence": {"type": "number"}
        },
        "required": ["specific_event_name", "reasoning", "confidence"],
        "additionalProperties": False
    }
}


# -- Proposition Extraction --
# Schema matches the v0.5 prompt in shared/utils/prompts_proposition.py.
# json_schema strict mode requires every property in `required` and every
# optional field declared with a nullable type union, so all fields are
# listed here and nullable ones use ["type", "null"].
_PROPOSITION_ENTITIES_SCHEMA = {
    "type": "object",
    "properties": {
        "persons":       {"type": "array", "items": {"type": "string"}},
        "organizations": {"type": "array", "items": {"type": "string"}},
        "projects":      {"type": "array", "items": {"type": "string"}},
        "locations":     {"type": "array", "items": {"type": "string"}},
    },
    "required": ["persons", "organizations", "projects", "locations"],
    "additionalProperties": False,
}

_EVIDENCE_SPAN_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "text_original": {"type": ["string", "null"]},
    },
    "required": ["text", "text_original"],
    "additionalProperties": False,
}

_PROPOSITION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "proposition_text":      {"type": "string"},
        "subject":               {"type": "string"},
        "predicate":             {"type": "string"},
        "object":                {"type": "string"},
        "claim_type":            {"type": "string", "enum": ["action", "commitment", "statement", "outcome", "perception", "capability"]},
        "tense":                 {"type": "string", "enum": ["past", "present", "future"]},
        "modality":              {"type": "string", "enum": ["actual", "planned", "proposed", "denied", "speculative"]},

        "initiator_country":     {"type": ["string", "null"]},
        "initiator_actor":       {"type": ["string", "null"]},
        "initiator_actor_type":  {"type": ["string", "null"]},
        "recipient_country":     {"type": ["string", "null"]},
        "recipient_actor":       {"type": ["string", "null"]},
        "recipient_actor_type":  {"type": ["string", "null"]},
        "third_parties":         {"type": "array", "items": {"type": "string"}},

        "sp_domain":             {"type": "string", "enum": ["economic_aid", "investment", "trade", "diplomatic_engagement", "cultural", "educational", "media_information", "science_technology", "health", "humanitarian", "security_military", "governance", "religious", "other"]},
        "instrument_type":       {"type": "string", "enum": ["state_visit", "bilateral_agreement", "multilateral_forum", "loan", "grant", "debt_relief", "direct_investment", "infrastructure_project", "scholarship", "exchange_program", "cultural_event", "language_institute", "media_broadcast", "joint_research", "training_program", "aid_delivery", "statement", "sanctions", "other"]},
        "mechanism":             {"type": "string", "enum": ["attraction", "persuasion", "inducement", "coercion"]},

        "entities":              _PROPOSITION_ENTITIES_SCHEMA,

        "monetary_value":        {"type": ["number", "null"]},
        "currency":              {"type": ["string", "null"]},
        "monetary_value_usd":    {"type": ["number", "null"]},
        "quantity":              {"type": ["number", "null"]},
        "quantity_unit":         {"type": ["string", "null"]},
        "timeframe":             {"type": ["string", "null"]},

        "valence":               {"type": ["number", "null"]},
        "salience_score":        {"type": ["number", "null"]},
        "materiality_score":     {"type": ["number", "null"]},
        "confidence":            {"type": ["number", "null"]},

        "event_date":            {"type": ["string", "null"]},
        # date_precision: one of day|month|quarter|year|unknown (enforced via prompt; null allowed)
        "date_precision":        {"type": ["string", "null"]},

        "location_name":         {"type": ["string", "null"]},
        "lat_long":              {"type": ["string", "null"]},
        # geo_scope: one of bilateral|regional|multilateral|global (enforced via prompt; null allowed)
        "geo_scope":             {"type": ["string", "null"]},

        "evidence_span":         _EVIDENCE_SPAN_SCHEMA,
    },
    "required": [
        "proposition_text", "subject", "predicate", "object",
        "claim_type", "tense", "modality",
        "initiator_country", "initiator_actor", "initiator_actor_type",
        "recipient_country", "recipient_actor", "recipient_actor_type",
        "third_parties",
        "sp_domain", "instrument_type", "mechanism",
        "entities",
        "monetary_value", "currency", "monetary_value_usd",
        "quantity", "quantity_unit", "timeframe",
        "valence", "salience_score", "materiality_score", "confidence",
        "event_date", "date_precision",
        "location_name", "lat_long", "geo_scope",
        "evidence_span",
    ],
    "additionalProperties": False,
}

SCHEMA_PROPOSITION_EXTRACT = {
    "name": "proposition_extract",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
            "propositions": {"type": "array", "items": _PROPOSITION_ITEM_SCHEMA},
        },
        "required": ["doc_id", "propositions"],
        "additionalProperties": False,
    }
}


# ===================================================================
# Mapping from job type to schema (used by generate_batch_requests)
# ===================================================================
def get_response_format_for_job_type(job_type: str) -> dict:
    """
    Get the structured output response_format dict for a given job type.

    Returns a json_schema response_format if a schema is defined,
    otherwise falls back to {"type": "json_object"}.
    """
    from services.pipeline.batch.batch_config import (
        JOB_TYPE_CLUSTER_DECONFLICT,
        JOB_TYPE_CANONICAL_DECONFLICT,
        JOB_TYPE_ENTITY_EXTRACT,
        JOB_TYPE_SCORE_MATERIALITY,
        JOB_TYPE_DAILY_ENTITY_EXTRACT,
        JOB_TYPE_ENTITY_DECONFLICT,
        JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
        JOB_TYPE_GENERATE_DAILY_SUMMARY,
        JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
        JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
        JOB_TYPE_SCORE_SUMMARY_MATERIALITY,
        JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
        JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
        JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS,
        JOB_TYPE_EVENT_RENAME,
        JOB_TYPE_PROPOSITION_EXTRACT,
    )

    _SCHEMA_MAP = {
        JOB_TYPE_CLUSTER_DECONFLICT: SCHEMA_CLUSTER_DECONFLICT,
        JOB_TYPE_CANONICAL_DECONFLICT: SCHEMA_CANONICAL_DECONFLICT,
        JOB_TYPE_ENTITY_EXTRACT: SCHEMA_ENTITY_EXTRACT,
        JOB_TYPE_SCORE_MATERIALITY: SCHEMA_SCORE_MATERIALITY,
        JOB_TYPE_DAILY_ENTITY_EXTRACT: SCHEMA_ENTITY_EXTRACT,  # Same schema
        JOB_TYPE_ENTITY_DECONFLICT: SCHEMA_ENTITY_DECONFLICT,
        JOB_TYPE_CANONICAL_ENTITY_DECONFLICT: SCHEMA_CANONICAL_ENTITY_DECONFLICT,
        JOB_TYPE_GENERATE_DAILY_SUMMARY: SCHEMA_DAILY_SUMMARY,
        JOB_TYPE_GENERATE_WEEKLY_SUMMARY: SCHEMA_WEEKLY_SUMMARY,
        JOB_TYPE_GENERATE_MONTHLY_SUMMARY: SCHEMA_MONTHLY_SUMMARY,
        JOB_TYPE_SCORE_SUMMARY_MATERIALITY: SCHEMA_SCORE_MATERIALITY,  # Same schema
        JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS: SCHEMA_ENTITY_DESCRIPTION,
        JOB_TYPE_GENERATE_BILATERAL_SUMMARIES: SCHEMA_BILATERAL_SUMMARY,
        JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS: SCHEMA_RELATIONSHIP_CLASSIFICATION,
        JOB_TYPE_EVENT_RENAME: SCHEMA_EVENT_RENAME,
        JOB_TYPE_PROPOSITION_EXTRACT: SCHEMA_PROPOSITION_EXTRACT,
    }

    schema = _SCHEMA_MAP.get(job_type)
    if schema:
        return {"type": "json_schema", "json_schema": schema}
    return {"type": "json_object"}
