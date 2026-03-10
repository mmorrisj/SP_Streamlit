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
    }

    schema = _SCHEMA_MAP.get(job_type)
    if schema:
        return {"type": "json_schema", "json_schema": schema}
    return {"type": "json_object"}
