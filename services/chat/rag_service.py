"""
RAG Service for Chat functionality.
Provides semantic search and LLM-powered response generation.

SOTA techniques:
- HyDE (Hypothetical Document Embeddings) for query expansion
- Cross-encoder reranking for precision after retrieval
- Hybrid search (BM25 + vector) via PostgreSQL tsvector + RRF fusion
- Token-aware context packing (fills model context window intelligently)
"""
import os
import re
import json
import yaml
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

import tiktoken
from sqlalchemy import text
import torch
import requests as http_requests

from shared.database.database import get_engine
from shared.utils.model_cache import get_hf_embeddings
from shared.utils.utils import gai

logger = logging.getLogger(__name__)

# Load RAG configuration from config.yaml
CONFIG_PATH = Path(__file__).parent.parent.parent / "shared" / "config" / "config.yaml"
with open(CONFIG_PATH, 'r') as f:
    _CONFIG = yaml.safe_load(f)
RAG_CONFIG = _CONFIG.get('rag', {})

# RAG configuration defaults (from config.yaml)
CHAT_DOCUMENT_LIMIT = RAG_CONFIG.get('chat_document_limit', 50)
ENTITY_MATCH_LIMIT = RAG_CONFIG.get('entity_match_limit', 15)
ENTITY_BOOST_FACTOR = RAG_CONFIG.get('entity_boost_factor', 0.15)
FUZZY_MATCH_THRESHOLD = RAG_CONFIG.get('fuzzy_match_threshold', 0.7)
SEMANTIC_MATCH_THRESHOLD = RAG_CONFIG.get('semantic_match_threshold', 0.6)

# Token-aware context packing
MAX_CONTEXT_TOKENS = RAG_CONFIG.get('max_context_tokens', 80000)
MAX_FULL_TEXT_DOCS = RAG_CONFIG.get('max_full_text_docs', 8)
TRUNCATED_DOC_CHARS = RAG_CONFIG.get('truncated_doc_chars', 500)

# Reranking configuration
ENABLE_RERANKING = RAG_CONFIG.get('enable_reranking', True)
RERANK_MODEL = RAG_CONFIG.get('rerank_model', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
RERANK_TOP_K = RAG_CONFIG.get('rerank_top_k', 15)
RERANK_CANDIDATE_K = RAG_CONFIG.get('rerank_candidate_k', 50)

# HyDE configuration
ENABLE_HYDE = RAG_CONFIG.get('enable_hyde', True)
HYDE_MODEL = RAG_CONFIG.get('hyde_model', 'gpt-4o-mini')

# Hybrid search configuration
ENABLE_HYBRID_SEARCH = RAG_CONFIG.get('enable_hybrid_search', True)
HYBRID_BM25_WEIGHT = RAG_CONFIG.get('hybrid_bm25_weight', 0.3)
HYBRID_VECTOR_WEIGHT = RAG_CONFIG.get('hybrid_vector_weight', 0.7)

# Backward compat
MAX_CONTEXT_CHARS = RAG_CONFIG.get('max_context_chars', 4000)

# Token encoder for context packing
_token_encoder = None

def _get_token_encoder():
    global _token_encoder
    if _token_encoder is None:
        try:
            _token_encoder = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            _token_encoder = tiktoken.get_encoding("cl100k_base")
    return _token_encoder

def count_tokens(text_str: str) -> int:
    """Count tokens in a string using tiktoken."""
    return len(_get_token_encoder().encode(text_str))


# =============================================================================
# Entity-Aware Search - Soft boost and context injection
# =============================================================================

@dataclass
class MatchedEntity:
    """An entity matched from the query."""
    entity_id: str
    canonical_name: str
    entity_type: str
    primary_role: Optional[str]
    entity_description: Optional[str]
    initiating_country: str
    total_documents: int
    first_mention_date: str
    last_mention_date: str
    match_type: str  # "exact", "fuzzy", "semantic"
    match_score: float


def search_entities(
    query: str,
    top_k: int = ENTITY_MATCH_LIMIT,
    semantic_threshold: float = SEMANTIC_MATCH_THRESHOLD,
    fuzzy_threshold: float = FUZZY_MATCH_THRESHOLD
) -> List[MatchedEntity]:
    """
    Search for entities matching the query using fuzzy and semantic matching.

    Args:
        query: The search query
        top_k: Maximum number of entities to return
        semantic_threshold: Minimum cosine similarity for semantic matches
        fuzzy_threshold: Minimum trigram similarity for fuzzy matches

    Returns:
        List of matched entities with match metadata
    """
    matched = []
    query_lower = query.lower()

    # Generate query embedding for semantic search
    embeddings = get_embedding_function()
    query_embedding = embeddings.embed_query(query)
    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

    engine = get_engine()

    with engine.connect() as conn:
        # Step 1: Try exact substring match on canonical_name (case-insensitive)
        exact_sql = """
            SELECT
                id::text as entity_id,
                canonical_name,
                entity_type,
                primary_role,
                entity_description,
                initiating_country,
                total_documents,
                first_mention_date::text,
                last_mention_date::text,
                1.0 as match_score
            FROM canonical_entities
            WHERE master_entity_id IS NULL  -- Only master entities
              AND (
                  LOWER(canonical_name) LIKE :query_pattern
                  OR EXISTS (
                      SELECT 1 FROM unnest(alternative_names) AS alt
                      WHERE LOWER(alt) LIKE :query_pattern
                  )
              )
            ORDER BY total_documents DESC
            LIMIT :limit
        """

        rows = conn.execute(text(exact_sql), {
            "query_pattern": f"%{query_lower}%",
            "limit": top_k
        }).mappings().all()

        seen_ids = set()
        for row in rows:
            seen_ids.add(row["entity_id"])
            matched.append(MatchedEntity(
                entity_id=row["entity_id"],
                canonical_name=row["canonical_name"],
                entity_type=str(row["entity_type"]),
                primary_role=str(row["primary_role"]) if row["primary_role"] else None,
                entity_description=row["entity_description"],
                initiating_country=row["initiating_country"],
                total_documents=row["total_documents"],
                first_mention_date=row["first_mention_date"],
                last_mention_date=row["last_mention_date"],
                match_type="exact",
                match_score=1.0
            ))

        # Step 2: Fuzzy match using pg_trgm similarity (if not enough exact matches)
        if len(matched) < top_k:
            fuzzy_sql = """
                SELECT
                    id::text as entity_id,
                    canonical_name,
                    entity_type,
                    primary_role,
                    entity_description,
                    initiating_country,
                    total_documents,
                    first_mention_date::text,
                    last_mention_date::text,
                    similarity(LOWER(canonical_name), :query) as match_score
                FROM canonical_entities
                WHERE master_entity_id IS NULL
                  AND id::text NOT IN :seen_ids
                  AND similarity(LOWER(canonical_name), :query) >= :threshold
                ORDER BY match_score DESC, total_documents DESC
                LIMIT :limit
            """

            try:
                rows = conn.execute(text(fuzzy_sql), {
                    "query": query_lower,
                    "seen_ids": tuple(seen_ids) if seen_ids else ('',),
                    "threshold": fuzzy_threshold,
                    "limit": top_k - len(matched)
                }).mappings().all()

                for row in rows:
                    seen_ids.add(row["entity_id"])
                    matched.append(MatchedEntity(
                        entity_id=row["entity_id"],
                        canonical_name=row["canonical_name"],
                        entity_type=str(row["entity_type"]),
                        primary_role=str(row["primary_role"]) if row["primary_role"] else None,
                        entity_description=row["entity_description"],
                        initiating_country=row["initiating_country"],
                        total_documents=row["total_documents"],
                        first_mention_date=row["first_mention_date"],
                        last_mention_date=row["last_mention_date"],
                        match_type="fuzzy",
                        match_score=float(row["match_score"])
                    ))
            except Exception:
                # pg_trgm might not be installed, rollback and skip fuzzy matching
                conn.rollback()

        # Step 3: Semantic search using embedding similarity (if still not enough)
        if len(matched) < top_k:
            # Use a CTE to calculate similarity only for entities with embeddings
            semantic_sql = f"""
                WITH entity_scores AS (
                    SELECT
                        id::text as entity_id,
                        canonical_name,
                        entity_type,
                        primary_role,
                        entity_description,
                        initiating_country,
                        total_documents,
                        first_mention_date::text,
                        last_mention_date::text,
                        1 - (embedding_vector::vector <=> '{embedding_str}'::vector) as similarity
                    FROM canonical_entities
                    WHERE master_entity_id IS NULL
                      AND embedding_vector IS NOT NULL
                )
                SELECT * FROM entity_scores
                WHERE entity_id NOT IN :seen_ids
                  AND similarity >= :threshold
                ORDER BY similarity DESC
                LIMIT :limit
            """

            try:
                rows = conn.execute(text(semantic_sql), {
                    "seen_ids": tuple(seen_ids) if seen_ids else ('',),
                    "threshold": semantic_threshold,
                    "limit": top_k - len(matched)
                }).mappings().all()

                for row in rows:
                    matched.append(MatchedEntity(
                        entity_id=row["entity_id"],
                        canonical_name=row["canonical_name"],
                        entity_type=str(row["entity_type"]),
                        primary_role=str(row["primary_role"]) if row["primary_role"] else None,
                        entity_description=row["entity_description"],
                        initiating_country=row["initiating_country"],
                        total_documents=row["total_documents"],
                        first_mention_date=row["first_mention_date"],
                        last_mention_date=row["last_mention_date"],
                        match_type="semantic",
                        match_score=float(row["similarity"])
                    ))
            except Exception:
                # pgvector might not work as expected, rollback and skip semantic matching
                conn.rollback()

    return matched


def get_entity_doc_ids(entity_ids: List[str], limit: int = 100) -> List[str]:
    """
    Get document IDs that mention the given entities.

    Args:
        entity_ids: List of canonical entity IDs
        limit: Maximum number of doc_ids to return

    Returns:
        List of document IDs
    """
    if not entity_ids:
        return []

    engine = get_engine()

    with engine.connect() as conn:
        # Join through daily_entity_mentions to get doc_ids
        # doc_ids is an ARRAY column, so we use unnest to get individual values
        sql = """
            SELECT DISTINCT unnest(dem.doc_ids) as doc_id
            FROM daily_entity_mentions dem
            WHERE dem.canonical_entity_id::text IN :entity_ids
            LIMIT :limit
        """

        rows = conn.execute(text(sql), {
            "entity_ids": tuple(entity_ids),
            "limit": limit
        }).fetchall()

        return [row[0] for row in rows]


def build_entity_context(matched_entities: List[MatchedEntity]) -> str:
    """
    Build a context string with entity profiles to inject into the LLM prompt.

    Args:
        matched_entities: List of entities matched from the query

    Returns:
        Formatted entity context string
    """
    if not matched_entities:
        return ""

    lines = ["RELEVANT ENTITIES:", ""]

    for ent in matched_entities:
        profile = f"• **{ent.canonical_name}** ({ent.entity_type})"
        if ent.primary_role:
            profile += f" - {ent.primary_role}"
        profile += f"\n  Country: {ent.initiating_country}"
        profile += f" | Mentioned in {ent.total_documents} documents"
        profile += f" | Active: {ent.first_mention_date} to {ent.last_mention_date}"

        if ent.entity_description:
            # Truncate description to keep context manageable
            desc = ent.entity_description[:300]
            if len(ent.entity_description) > 300:
                desc += "..."
            profile += f"\n  {desc}"

        lines.append(profile)
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Query Intelligence - Automatic filter extraction from natural language
# =============================================================================

@dataclass
class QueryIntent:
    """Extracted intent and filters from a natural language query."""
    original_query: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    influencers: List[str] = field(default_factory=list)
    recipients: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    temporal_context: Optional[str] = None  # "recent", "historical", etc.
    confidence_notes: List[str] = field(default_factory=list)


# Known countries and their aliases
COUNTRY_ALIASES = {
    # Influencers
    "china": "China",
    "chinese": "China",
    "prc": "China",
    "beijing": "China",
    "russia": "Russia",
    "russian": "Russia",
    "moscow": "Russia",
    "kremlin": "Russia",
    "iran": "Iran",
    "iranian": "Iran",
    "tehran": "Iran",
    "persia": "Iran",
    "turkey": "Turkey",
    "turkish": "Turkey",
    "ankara": "Turkey",
    "türkiye": "Turkey",
    "united states": "United States",
    "us": "United States",
    "usa": "United States",
    "america": "United States",
    "american": "United States",
    "washington": "United States",
    # Recipients (Middle East & Africa)
    "egypt": "Egypt",
    "egyptian": "Egypt",
    "cairo": "Egypt",
    "saudi arabia": "Saudi Arabia",
    "saudi": "Saudi Arabia",
    "riyadh": "Saudi Arabia",
    "uae": "United Arab Emirates",
    "emirates": "United Arab Emirates",
    "dubai": "United Arab Emirates",
    "abu dhabi": "United Arab Emirates",
    "qatar": "Qatar",
    "qatari": "Qatar",
    "doha": "Qatar",
    "israel": "Israel",
    "israeli": "Israel",
    "tel aviv": "Israel",
    "jerusalem": "Israel",
    "iraq": "Iraq",
    "iraqi": "Iraq",
    "baghdad": "Iraq",
    "syria": "Syria",
    "syrian": "Syria",
    "damascus": "Syria",
    "lebanon": "Lebanon",
    "lebanese": "Lebanon",
    "beirut": "Lebanon",
    "jordan": "Jordan",
    "jordanian": "Jordan",
    "amman": "Jordan",
    "yemen": "Yemen",
    "yemeni": "Yemen",
    "libya": "Libya",
    "libyan": "Libya",
    "tripoli": "Libya",
    "kuwait": "Kuwait",
    "kuwaiti": "Kuwait",
    "oman": "Oman",
    "omani": "Oman",
    "muscat": "Oman",
    "bahrain": "Bahrain",
    "bahraini": "Bahrain",
    "manama": "Bahrain",
    "palestine": "Palestine",
    "palestinian": "Palestine",
    "gaza": "Palestine",
    "west bank": "Palestine",
    "cyprus": "Cyprus",
    # Africa
    "africa": None,  # Continent, not a specific country
    "african": None,
    "nigeria": "Nigeria",
    "nigerian": "Nigeria",
    "south africa": "South Africa",
    "kenya": "Kenya",
    "kenyan": "Kenya",
    "ethiopia": "Ethiopia",
    "ethiopian": "Ethiopia",
    "sudan": "Sudan",
    "sudanese": "Sudan",
    "morocco": "Morocco",
    "moroccan": "Morocco",
    "algeria": "Algeria",
    "algerian": "Algeria",
    "tunisia": "Tunisia",
    "tunisian": "Tunisia",
    "djibouti": "Djibouti",
    "somalia": "Somalia",
    "somali": "Somalia",
    "eritrea": "Eritrea",
}

# Influencer countries (for directional queries like "China's influence in...")
INFLUENCER_COUNTRIES = {"China", "Russia", "Iran", "Turkey", "United States"}

# Category keywords and their mappings
CATEGORY_KEYWORDS = {
    # Economic
    "economic": "Economic",
    "economy": "Economic",
    "trade": "Economic",
    "investment": "Economic",
    "infrastructure": "Economic",
    "bri": "Economic",  # Belt and Road Initiative
    "belt and road": "Economic",
    "port": "Economic",
    "railway": "Economic",
    "construction": "Economic",
    "loan": "Economic",
    "debt": "Economic",
    "business": "Economic",
    "commercial": "Economic",
    "financial": "Economic",
    # Military
    "military": "Military",
    "defense": "Military",
    "defence": "Military",
    "weapon": "Military",
    "arms": "Military",
    "naval": "Military",
    "army": "Military",
    "troops": "Military",
    "base": "Military",
    "exercise": "Military",
    "training": "Military",
    "security": "Military",
    # Diplomacy
    "diplomacy": "Diplomacy",
    "diplomatic": "Diplomacy",
    "embassy": "Diplomacy",
    "ambassador": "Diplomacy",
    "summit": "Diplomacy",
    "treaty": "Diplomacy",
    "agreement": "Diplomacy",
    "bilateral": "Diplomacy",
    "multilateral": "Diplomacy",
    "foreign minister": "Diplomacy",
    "state visit": "Diplomacy",
    # Social
    "social": "Social",
    "cultural": "Social",
    "culture": "Social",
    "education": "Social",
    "university": "Social",
    "scholarship": "Social",
    "student": "Social",
    "confucius": "Social",  # Confucius Institute
    "media": "Social",
    "humanitarian": "Social",
    "aid": "Social",
    "health": "Social",
    "hospital": "Social",
    "religious": "Social",
    "mosque": "Social",
    "church": "Social",
}

# Temporal patterns and their date calculations
# Order matters - more specific patterns should come before general ones
TEMPORAL_PATTERNS = [
    # Specific time periods (check these first)
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+(?:6|six)\s+months?\b', 'recent', 180),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+(?:3|three)\s+months?\b', 'recent', 90),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+(?:2|two)\s+months?\b', 'recent', 60),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+(?:few\s+)?months?\b', 'recent', 90),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+(?:few\s+)?weeks?\b', 'recent', 21),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+week\b', 'recent', 7),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+(?:few\s+)?days?\b', 'recent', 7),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+year\b', 'recent', 365),
    (r'\b(?:last|past|over\s+the\s+(?:last|past))\s+month\b', 'recent', 30),
    # Recent/current keywords
    (r'\b(recently|recent|lately|latest|current|now)\b', 'recent', 30),
    # This period
    (r'\bthis\s+year\b', 'this_year', 0),  # Special handling
    (r'\bthis\s+month\b', 'this_month', 0),  # Special handling
    (r'\bthis\s+week\b', 'this_week', 0),  # Special handling
    # Specific years
    (r'\b2024\b', 'year_2024', 0),
    (r'\b2025\b', 'year_2025', 0),
    (r'\b2026\b', 'year_2026', 0),
    # Historical
    (r'\bhistorical(?:ly)?\b', 'historical', None),
    (r'\bover\s+the\s+years?\b', 'historical', None),
    (r'\blong[\s-]term\b', 'historical', None),
]


def analyze_query(query: str) -> QueryIntent:
    """
    Analyze a natural language query to extract implicit filters and intent.

    This function examines the query for:
    - Temporal indicators (recently, last month, this year, etc.)
    - Country references (influencers and recipients)
    - Category keywords (economic, military, etc.)

    Args:
        query: The user's natural language question

    Returns:
        QueryIntent with extracted filters and metadata
    """
    intent = QueryIntent(original_query=query)
    query_lower = query.lower()
    today = datetime.now()

    # =================================
    # 1. Extract temporal information
    # =================================
    for pattern, temporal_type, days in TEMPORAL_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            intent.temporal_context = temporal_type

            if temporal_type == 'recent' and days:
                intent.start_date = (today - timedelta(days=days)).strftime('%Y-%m-%d')
                intent.end_date = today.strftime('%Y-%m-%d')
                intent.confidence_notes.append(f"Temporal: '{temporal_type}' → last {days} days")

            elif temporal_type == 'this_year':
                intent.start_date = f"{today.year}-01-01"
                intent.end_date = today.strftime('%Y-%m-%d')
                intent.confidence_notes.append(f"Temporal: 'this year' → {today.year}")

            elif temporal_type == 'this_month':
                intent.start_date = today.strftime('%Y-%m-01')
                intent.end_date = today.strftime('%Y-%m-%d')
                intent.confidence_notes.append(f"Temporal: 'this month' → {today.strftime('%B %Y')}")

            elif temporal_type == 'this_week':
                start_of_week = today - timedelta(days=today.weekday())
                intent.start_date = start_of_week.strftime('%Y-%m-%d')
                intent.end_date = today.strftime('%Y-%m-%d')
                intent.confidence_notes.append("Temporal: 'this week'")

            elif temporal_type.startswith('year_'):
                year = temporal_type.split('_')[1]
                intent.start_date = f"{year}-01-01"
                intent.end_date = f"{year}-12-31"
                intent.confidence_notes.append(f"Temporal: year {year}")

            break  # Use first matching temporal pattern

    # =================================
    # 2. Extract country references
    # =================================
    # Look for possessive patterns like "China's", "Russian", etc.
    possessive_pattern = r"(\w+)(?:'s|')\s+(?:influence|role|activities|investments?|projects?|relations?|policy|policies|presence|engagement)"
    possessive_matches = re.findall(possessive_pattern, query_lower)

    # Also look for "by China", "from Russia", etc.
    by_from_pattern = r"(?:by|from|of)\s+(\w+(?:\s+\w+)?)"
    by_from_matches = re.findall(by_from_pattern, query_lower)

    # And "in Egypt", "to Saudi Arabia", etc.
    in_to_pattern = r"(?:in|to|with|towards?)\s+(\w+(?:\s+\w+)?)"
    in_to_matches = re.findall(in_to_pattern, query_lower)

    # Process possessive matches as potential influencers
    for match in possessive_matches:
        normalized = COUNTRY_ALIASES.get(match.lower())
        if normalized and normalized in INFLUENCER_COUNTRIES:
            if normalized not in intent.influencers:
                intent.influencers.append(normalized)
                intent.confidence_notes.append(f"Influencer (possessive): {normalized}")

    # Process by/from matches as potential influencers
    for match in by_from_matches:
        normalized = COUNTRY_ALIASES.get(match.lower())
        if normalized and normalized in INFLUENCER_COUNTRIES:
            if normalized not in intent.influencers:
                intent.influencers.append(normalized)
                intent.confidence_notes.append(f"Influencer (by/from): {normalized}")

    # Process in/to matches as potential recipients
    for match in in_to_matches:
        normalized = COUNTRY_ALIASES.get(match.lower())
        if normalized and normalized not in INFLUENCER_COUNTRIES:
            if normalized and normalized not in intent.recipients:
                intent.recipients.append(normalized)
                intent.confidence_notes.append(f"Recipient (in/to): {normalized}")

    # General country mention scan
    words = re.findall(r'\b[\w\s]+\b', query_lower)
    for i, word in enumerate(words):
        # Check single words
        normalized = COUNTRY_ALIASES.get(word.strip())
        if normalized:
            # Determine if influencer or recipient based on context
            if normalized in INFLUENCER_COUNTRIES:
                if normalized not in intent.influencers:
                    intent.influencers.append(normalized)
            elif normalized not in intent.recipients:
                intent.recipients.append(normalized)

        # Check two-word combinations (e.g., "Saudi Arabia", "United States")
        if i < len(words) - 1:
            two_word = f"{word.strip()} {words[i+1].strip()}"
            normalized = COUNTRY_ALIASES.get(two_word)
            if normalized:
                if normalized in INFLUENCER_COUNTRIES:
                    if normalized not in intent.influencers:
                        intent.influencers.append(normalized)
                elif normalized not in intent.recipients:
                    intent.recipients.append(normalized)

    # =================================
    # 3. Extract category references
    # =================================
    for keyword, category in CATEGORY_KEYWORDS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', query_lower):
            if category not in intent.categories:
                intent.categories.append(category)
                intent.confidence_notes.append(f"Category: {category} (keyword: '{keyword}')")

    return intent


def apply_query_intelligence(
    query: str,
    explicit_influencer: Optional[str] = None,
    explicit_recipient: Optional[str] = None,
    explicit_category: Optional[str] = None,
    explicit_start_date: Optional[str] = None,
    explicit_end_date: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], List[str]]:
    """
    Apply query intelligence, merging explicit filters with inferred ones.

    Explicit filters always take precedence over inferred ones.

    Returns:
        Tuple of (influencer, recipient, category, start_date, end_date, notes)
    """
    intent = analyze_query(query)

    # Use explicit values if provided, otherwise use inferred
    influencer = explicit_influencer or (intent.influencers[0] if intent.influencers else None)
    recipient = explicit_recipient or (intent.recipients[0] if intent.recipients else None)
    category = explicit_category or (intent.categories[0] if intent.categories else None)
    start_date = explicit_start_date or intent.start_date
    end_date = explicit_end_date or intent.end_date

    return influencer, recipient, category, start_date, end_date, intent.confidence_notes


# Lazy-loaded embedding function
_embedding_function = None

def get_embedding_function():
    """Get or create the embedding function (lazy loading)."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = get_hf_embeddings()
    return _embedding_function


# =============================================================================
# Reranking - Cross-encoder for precision after initial retrieval
# =============================================================================

_reranker = None

def get_reranker():
    """Get or create the cross-encoder reranker (lazy loading).

    Tries the baked-in model path first (Docker image), then falls back to
    downloading from HuggingFace Hub (local dev).
    """
    global _reranker
    if _reranker is None and ENABLE_RERANKING:
        try:
            from sentence_transformers import CrossEncoder
            # Try baked-in path first (set during Docker build)
            baked_path = '/app/.cache/huggingface/models/ms-marco-MiniLM-L-6-v2'
            if os.path.isfile(os.path.join(baked_path, 'config.json')):
                _reranker = CrossEncoder(baked_path, max_length=512)
                logger.info(f"Loaded reranker model from baked-in path: {baked_path}")
            else:
                _reranker = CrossEncoder(RERANK_MODEL, max_length=512)
                logger.info(f"Loaded reranker model: {RERANK_MODEL}")
        except Exception as e:
            logger.warning(f"Failed to load reranker ({RERANK_MODEL}): {e}. Reranking disabled.")
            return None
    return _reranker


def rerank_results(
    query: str,
    results: List[Dict[str, Any]],
    top_k: int = RERANK_TOP_K
) -> List[Dict[str, Any]]:
    """
    Rerank search results using a cross-encoder model.

    Takes (query, document) pairs, scores them with a cross-encoder,
    and returns the top-k results sorted by cross-encoder score.
    """
    reranker = get_reranker()
    if reranker is None or not results:
        return results[:top_k]

    # Build (query, document) pairs for scoring
    pairs = []
    for doc in results:
        content = doc.get('content', '')[:1500]  # Limit input length for cross-encoder
        pairs.append((query, content))

    try:
        scores = reranker.predict(pairs, show_progress_bar=False)
        for doc, score in zip(results, scores):
            doc['rerank_score'] = float(score)
            # Keep original vector score for reference
            doc['vector_score'] = doc.get('relevance_score', 0)
            doc['relevance_score'] = float(score)

        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:top_k]
    except Exception as e:
        logger.warning(f"Reranking failed: {e}. Using original ranking.")
        return results[:top_k]


# =============================================================================
# HyDE - Hypothetical Document Embeddings for query expansion
# =============================================================================

def generate_hyde_document(query: str) -> Optional[str]:
    """
    Generate a hypothetical document that would answer the query.

    Uses a cheap LLM to generate a plausible answer, then embeds that
    answer instead of the raw query. This bridges the vocabulary gap
    between questions and documents.
    """
    if not ENABLE_HYDE:
        return None

    try:
        hyde_prompt = (
            "Write a short, factual paragraph (3-5 sentences) that would appear in a "
            "diplomatic intelligence document answering this question. Include specific "
            "names, dates, and details as if reporting real events. Do not hedge or "
            "qualify — write as if stating established facts.\n\n"
            f"Question: {query}"
        )

        hyde_doc = gai("You are a diplomatic intelligence analyst.", hyde_prompt, model=HYDE_MODEL)
        if isinstance(hyde_doc, str) and hyde_doc:
            logger.info(f"HyDE generated {len(hyde_doc)} char hypothetical document")
            return hyde_doc
        return None

    except Exception as e:
        logger.warning(f"HyDE generation failed: {e}. Using original query.")
        return None


def _get_proxy_stream_url():
    """Get the streaming proxy URL from environment."""
    api_url = os.getenv('API_URL', '').strip()
    if not api_url:
        fastapi_url = os.getenv('FASTAPI_URL', '').strip()
        if fastapi_url:
            api_url = fastapi_url.split('/proxy_query')[0].split('/material_query')[0]
        else:
            api_url = 'http://localhost:8000'
    return f"{api_url.rstrip('/')}/proxy_query_stream"


# =============================================================================
# Layered Context: Strategic summaries + Event discovery
# =============================================================================

def gather_strategic_context(
    influencer: Optional[str] = None,
    recipient: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """
    Deterministic SQL lookups for pre-analyzed strategic summaries.

    Queries BilateralRelationshipSummary, CountryCategorySummary, and
    PeriodSummary based on known keys. No vector search needed — these
    are established analytical products.

    Returns:
        Formatted string of strategic context for prompt injection.
    """
    engine = get_engine()
    parts = []

    with engine.connect() as conn:
        # 1. Bilateral relationship summary (if both countries specified)
        if influencer and recipient:
            row = conn.execute(text("""
                SELECT relationship_summary, material_score_avg,
                       total_documents, count_by_category
                FROM bilateral_relationship_summaries
                WHERE initiating_country = :inf
                  AND recipient_country = :rec
                  AND is_deleted = false
                LIMIT 1
            """), {"inf": influencer, "rec": recipient}).mappings().first()

            if row and row.get("relationship_summary"):
                summary = row["relationship_summary"]
                section = f"BILATERAL RELATIONSHIP: {influencer} → {recipient}\n"
                if isinstance(summary, dict):
                    if summary.get("overview"):
                        section += f"Overview: {summary['overview']}\n"
                    if summary.get("key_themes"):
                        themes = summary["key_themes"]
                        if isinstance(themes, list):
                            section += "Key Themes: " + "; ".join(str(t) for t in themes[:5]) + "\n"
                    if summary.get("trend_analysis"):
                        section += f"Trend: {summary['trend_analysis'][:500]}\n"
                    if summary.get("current_status"):
                        section += f"Current Status: {summary['current_status'][:300]}\n"
                if row.get("material_score_avg"):
                    section += f"Materiality Score: {row['material_score_avg']:.2f}\n"
                if row.get("total_documents"):
                    section += f"Total Documents: {row['total_documents']}\n"
                parts.append(section)

        # 2. Country-category summary (if country + category specified)
        if influencer and category:
            row = conn.execute(text("""
                SELECT category_summary, total_documents, count_by_recipient
                FROM country_category_summaries
                WHERE initiating_country = :inf
                  AND category = :cat
                  AND is_deleted = false
                LIMIT 1
            """), {"inf": influencer, "cat": category}).mappings().first()

            if row and row.get("category_summary"):
                summary = row["category_summary"]
                section = f"CATEGORY STRATEGY: {influencer} — {category}\n"
                if isinstance(summary, dict):
                    if summary.get("overview"):
                        section += f"Overview: {summary['overview'][:500]}\n"
                    if summary.get("key_strategies"):
                        strats = summary["key_strategies"]
                        if isinstance(strats, list):
                            section += "Strategies: " + "; ".join(str(s) for s in strats[:5]) + "\n"
                    if summary.get("effectiveness_assessment"):
                        section += f"Effectiveness: {summary['effectiveness_assessment'][:300]}\n"
                parts.append(section)

        # 3. If only recipient specified (no specific influencer), get all bilateral summaries for that recipient
        if recipient and not influencer:
            rows = conn.execute(text("""
                SELECT initiating_country, relationship_summary, material_score_avg, total_documents
                FROM bilateral_relationship_summaries
                WHERE recipient_country = :rec
                  AND is_deleted = false
                ORDER BY total_documents DESC
                LIMIT 5
            """), {"rec": recipient}).mappings().all()

            if rows:
                section = f"BILATERAL RELATIONSHIPS WITH {recipient}:\n"
                for r in rows:
                    summary = r.get("relationship_summary", {})
                    overview = ""
                    if isinstance(summary, dict):
                        overview = summary.get("current_status") or summary.get("overview", "")
                        if isinstance(overview, str):
                            overview = overview[:200]
                    section += f"- {r['initiating_country']}: {r.get('total_documents', 0)} docs"
                    if r.get("material_score_avg"):
                        section += f", materiality {r['material_score_avg']:.2f}"
                    if overview:
                        section += f" — {overview}"
                    section += "\n"
                parts.append(section)

    if not parts:
        return ""

    return "STRATEGIC CONTEXT (Pre-Analyzed):\n\n" + "\n---\n".join(parts)


def search_event_summaries(
    query: str,
    k: int = 10,
    influencer: Optional[str] = None,
    recipient: Optional[str] = None,
    collections: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Semantic search across event summary embedding collections.

    Searches daily/weekly/monthly event summary embeddings and returns
    the top matches with event metadata. Results are merged across
    collections using reciprocal rank fusion.

    Args:
        query: Search query
        k: Number of results to return
        influencer: Filter by initiating country
        recipient: Filter by recipient (checked against event_name text)
        collections: Which collections to search (default: daily + weekly)

    Returns:
        List of event summary results with metadata
    """
    if collections is None:
        collections = ["daily_event_embeddings", "weekly_event_embeddings"]

    embeddings = get_embedding_function()
    query_embedding = embeddings.embed_query(query)
    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

    engine = get_engine()
    all_results = []

    with engine.connect() as conn:
        for collection_name in collections:
            filter_sql = ""
            params = {"limit": k, "collection_name": collection_name}

            if influencer:
                filter_sql += " AND e.cmetadata->>'initiating_country' = :influencer"
                params["influencer"] = influencer

            sql = f"""
                SELECT
                    e.document as content,
                    e.cmetadata,
                    1 - (e.embedding <=> '{embedding_str}'::vector) AS similarity
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = :collection_name
                {filter_sql}
                ORDER BY e.embedding <=> '{embedding_str}'::vector ASC
                LIMIT :limit
            """

            try:
                rows = conn.execute(text(sql), params).mappings().all()

                for row in rows:
                    meta = row.get("cmetadata", {}) or {}
                    if isinstance(meta, str):
                        meta = json.loads(meta)

                    # Filter by recipient if specified (check event_name text)
                    if recipient and recipient.lower() not in (meta.get("event_name", "").lower()):
                        continue

                    all_results.append({
                        "content": row.get("content", ""),
                        "event_name": meta.get("event_name", ""),
                        "initiating_country": meta.get("initiating_country", ""),
                        "period_type": meta.get("period_type", ""),
                        "period_start": meta.get("period_start", ""),
                        "period_end": meta.get("period_end", ""),
                        "summary_id": meta.get("summary_id", ""),
                        "similarity": float(row.get("similarity", 0)),
                        "source_type": "event_summary",
                        "collection": collection_name,
                    })
            except Exception as e:
                logger.warning("Event summary search failed for %s: %s", collection_name, e)

    # Sort by similarity and take top k
    all_results.sort(key=lambda x: x["similarity"], reverse=True)
    return all_results[:k]


def format_event_context(event_results: List[Dict[str, Any]]) -> str:
    """Format event summary search results into a prompt context section."""
    if not event_results:
        return ""

    parts = []
    for i, event in enumerate(event_results, 1):
        entry = f"[E{i}] {event['event_name']}"
        if event.get("initiating_country"):
            entry += f" ({event['initiating_country']})"
        if event.get("period_start"):
            entry += f" — {event['period_start']}"
            if event.get("period_end") and event["period_end"] != event["period_start"]:
                entry += f" to {event['period_end']}"
        entry += f" [{event.get('period_type', 'daily')}]"
        entry += f"\n{event['content'][:600]}"
        if len(event.get("content", "")) > 600:
            entry += "..."
        parts.append(entry)

    return "RELEVANT EVENT SUMMARIES (Consolidated Analysis):\n\n" + "\n\n---\n\n".join(parts)


def semantic_search(
    query: str,
    k: int = 10,
    influencer: Optional[str] = None,
    recipient: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_hyde: bool = True,
    doc_id_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Perform semantic search on document embeddings with optional filters.

    Supports HyDE (Hypothetical Document Embeddings) for query expansion
    and hybrid BM25+vector search via Reciprocal Rank Fusion.

    Args:
        query: Search query text
        k: Number of results to return
        influencer: Filter by initiating country
        recipient: Filter by recipient country
        category: Filter by category
        start_date: Filter by start date (YYYY-MM-DD)
        end_date: Filter by end date (YYYY-MM-DD)
        use_hyde: Whether to apply HyDE query expansion

    Returns:
        List of matching documents with metadata and relevance scores
    """
    embeddings = get_embedding_function()

    # HyDE: generate hypothetical document and embed it for better retrieval
    hyde_doc = None
    if use_hyde and ENABLE_HYDE:
        hyde_doc = generate_hyde_document(query)

    if hyde_doc:
        # Embed the hypothetical answer (bridges question-document gap)
        query_embedding = embeddings.embed_query(hyde_doc)
    else:
        query_embedding = embeddings.embed_query(query)

    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

    # Build filter conditions (shared between vector and BM25 queries)
    filter_sql = ""
    params = {"limit": k}

    if influencer:
        filter_sql += " AND d.initiating_country = :influencer"
        params["influencer"] = influencer
    if recipient:
        filter_sql += " AND d.recipient_country = :recipient"
        params["recipient"] = recipient
    if category:
        filter_sql += " AND d.category = :category"
        params["category"] = category
    if start_date:
        filter_sql += " AND d.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        filter_sql += " AND d.date <= :end_date"
        params["end_date"] = end_date
    if doc_id_filter:
        # Scope search to specific document IDs (for research project mode)
        placeholders = ", ".join(f":did_{i}" for i in range(len(doc_id_filter)))
        filter_sql += f" AND d.doc_id IN ({placeholders})"
        for i, did in enumerate(doc_id_filter):
            params[f"did_{i}"] = did

    engine = get_engine()
    results = []

    with engine.connect() as conn:
        # --- Hybrid Search: BM25 + Vector via Reciprocal Rank Fusion ---
        if ENABLE_HYBRID_SEARCH:
            results = _hybrid_search(
                conn, query, embedding_str, filter_sql, params, k
            )
        else:
            # Pure vector search (original behavior)
            sql = f"""
                WITH ranked_docs AS (
                    SELECT
                        e.document as content,
                        e.cmetadata,
                        e.embedding <=> '{embedding_str}'::vector AS distance,
                        1 - (e.embedding <=> '{embedding_str}'::vector) AS similarity
                    FROM langchain_pg_embedding e
                    JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                    WHERE c.name = 'chunk_embeddings'
                )
                SELECT
                    r.content, r.cmetadata, r.similarity,
                    d.doc_id, d.title, d.source_name, d.date,
                    d.initiating_country, d.recipient_country,
                    d.category, d.salience
                FROM ranked_docs r
                LEFT JOIN documents d ON r.cmetadata->>'doc_id' = d.doc_id
                WHERE 1=1 {filter_sql}
                ORDER BY r.distance ASC LIMIT :limit
            """
            rows = conn.execute(text(sql), params).mappings().all()
            for idx, row in enumerate(rows, 1):
                results.append(_row_to_result(row, idx))

    return results


def _hybrid_search(
    conn,
    query: str,
    embedding_str: str,
    filter_sql: str,
    params: dict,
    k: int
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion combining BM25 (tsvector) and vector similarity.

    Falls back to pure vector search if tsvector column doesn't exist.
    """
    rrf_k = 60  # RRF constant (standard value)

    try:
        # Combined query: vector search + BM25 via tsvector on documents table
        # Uses RRF: score = sum(1 / (k + rank_i)) for each retrieval system
        hybrid_sql = f"""
            WITH vector_ranked AS (
                SELECT
                    e.document as content,
                    e.cmetadata,
                    1 - (e.embedding <=> '{embedding_str}'::vector) AS similarity,
                    ROW_NUMBER() OVER (ORDER BY e.embedding <=> '{embedding_str}'::vector ASC) AS v_rank
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = 'chunk_embeddings'
                ORDER BY e.embedding <=> '{embedding_str}'::vector ASC
                LIMIT :vector_limit
            ),
            bm25_ranked AS (
                SELECT
                    d.doc_id,
                    ts_rank_cd(d.search_vector, plainto_tsquery('english', :bm25_query)) AS bm25_score,
                    ROW_NUMBER() OVER (
                        ORDER BY ts_rank_cd(d.search_vector, plainto_tsquery('english', :bm25_query)) DESC
                    ) AS b_rank
                FROM documents d
                WHERE d.search_vector @@ plainto_tsquery('english', :bm25_query)
                ORDER BY bm25_score DESC
                LIMIT :bm25_limit
            )
            SELECT
                v.content, v.cmetadata, v.similarity,
                d.doc_id, d.title, d.source_name, d.date,
                d.initiating_country, d.recipient_country,
                d.category, d.salience,
                (
                    :vector_weight * (1.0 / (:rrf_k + v.v_rank)) +
                    COALESCE(:bm25_weight * (1.0 / (:rrf_k + b.b_rank)), 0)
                ) AS rrf_score
            FROM vector_ranked v
            LEFT JOIN documents d ON v.cmetadata->>'doc_id' = d.doc_id
            LEFT JOIN bm25_ranked b ON d.doc_id = b.doc_id
            WHERE 1=1 {filter_sql}
            ORDER BY rrf_score DESC
            LIMIT :limit
        """

        hybrid_params = {
            **params,
            "bm25_query": query,
            "vector_limit": k * 3,
            "bm25_limit": k * 3,
            "rrf_k": rrf_k,
            "vector_weight": HYBRID_VECTOR_WEIGHT,
            "bm25_weight": HYBRID_BM25_WEIGHT,
        }

        rows = conn.execute(text(hybrid_sql), hybrid_params).mappings().all()
        results = []
        for idx, row in enumerate(rows, 1):
            result = _row_to_result(row, idx)
            result['rrf_score'] = float(row.get('rrf_score', 0))
            results.append(result)
        return results

    except Exception as e:
        # tsvector column likely doesn't exist yet — fall back to pure vector
        logger.info(f"Hybrid search unavailable ({e}), falling back to vector-only search")
        conn.rollback()

        sql = f"""
            WITH ranked_docs AS (
                SELECT
                    e.document as content,
                    e.cmetadata,
                    e.embedding <=> '{embedding_str}'::vector AS distance,
                    1 - (e.embedding <=> '{embedding_str}'::vector) AS similarity
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = 'chunk_embeddings'
            )
            SELECT
                r.content, r.cmetadata, r.similarity,
                d.doc_id, d.title, d.source_name, d.date,
                d.initiating_country, d.recipient_country,
                d.category, d.salience
            FROM ranked_docs r
            LEFT JOIN documents d ON r.cmetadata->>'doc_id' = d.doc_id
            WHERE 1=1 {filter_sql}
            ORDER BY r.distance ASC LIMIT :limit
        """
        rows = conn.execute(text(sql), params).mappings().all()
        return [_row_to_result(row, idx) for idx, row in enumerate(rows, 1)]


def _row_to_result(row, idx: int) -> Dict[str, Any]:
    """Convert a database row to a standardized result dict."""
    return {
        "citation_number": idx,
        "doc_id": row.get("doc_id"),
        "content": row.get("content", ""),
        "title": row.get("title"),
        "source_name": row.get("source_name"),
        "date": str(row.get("date")) if row.get("date") else None,
        "initiating_country": row.get("initiating_country"),
        "recipient_country": row.get("recipient_country"),
        "category": row.get("category"),
        "salience": row.get("salience"),
        "relevance_score": float(row.get("similarity", 0))
    }


def intelligent_search(
    query: str,
    k: int = CHAT_DOCUMENT_LIMIT,
    influencer: Optional[str] = None,
    recipient: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    apply_intelligence: bool = True,
    enable_entity_boost: bool = True,
    entity_boost_factor: float = ENTITY_BOOST_FACTOR,
    doc_id_filter: Optional[List[str]] = None,
    include_strategic_context: bool = True,
    include_event_context: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Perform intelligent semantic search with automatic filter inference and entity boost.

    This wrapper analyzes the query for temporal keywords (recently, last month),
    country references, and category keywords, then applies appropriate filters.
    It also performs entity-aware search to boost documents mentioning matched entities.

    Explicit filters always override inferred ones.

    Args:
        query: Search query text
        k: Number of results to return
        influencer: Explicit filter by initiating country
        recipient: Explicit filter by recipient country
        category: Explicit filter by category
        start_date: Explicit filter by start date (YYYY-MM-DD)
        end_date: Explicit filter by end date (YYYY-MM-DD)
        apply_intelligence: Whether to apply query intelligence (default True)
        enable_entity_boost: Whether to boost documents mentioning matched entities (default True)
        entity_boost_factor: How much to boost entity-matched documents (default 0.15)

    Returns:
        Tuple of (search_results, metadata) where metadata includes:
        - applied_filters: Dict of filters that were applied
        - inferred_filters: Dict of filters inferred from query
        - confidence_notes: List of explanations for inferences
        - matched_entities: List of entities matched from the query
    """
    metadata = {
        "applied_filters": {},
        "inferred_filters": {},
        "confidence_notes": [],
        "matched_entities": []
    }

    if doc_id_filter:
        metadata["applied_filters"]["project_scoped"] = True
        metadata["applied_filters"]["project_doc_count"] = len(doc_id_filter)
        metadata["confidence_notes"].append(
            f"Project-scoped search: restricted to {len(doc_id_filter)} collected documents"
        )

    if apply_intelligence:
            query,
            explicit_influencer=influencer,
            explicit_recipient=recipient,
            explicit_category=category,
            explicit_start_date=start_date,
            explicit_end_date=end_date
        )

        # Track what was inferred vs explicit
        intent = analyze_query(query)
        metadata["inferred_filters"] = {
            "influencers": intent.influencers,
            "recipients": intent.recipients,
            "categories": intent.categories,
            "temporal_context": intent.temporal_context,
            "start_date": intent.start_date,
            "end_date": intent.end_date
        }
        metadata["confidence_notes"] = notes

        # Use merged values
        influencer = inferred_inf
        recipient = inferred_rec
        category = inferred_cat
        start_date = inferred_start
        end_date = inferred_end

    # Track what filters are actually being applied
    if influencer:
        metadata["applied_filters"]["influencer"] = influencer
    if recipient:
        metadata["applied_filters"]["recipient"] = recipient
    if category:
        metadata["applied_filters"]["category"] = category
    if start_date:
        metadata["applied_filters"]["start_date"] = start_date
    if end_date:
        metadata["applied_filters"]["end_date"] = end_date

    # Entity-aware search: find matched entities and their associated documents
    matched_entities = []
    entity_doc_ids = set()

    if enable_entity_boost:
        try:
            matched_entities = search_entities(query)  # Uses ENTITY_MATCH_LIMIT from config
            if matched_entities:
                entity_ids = [e.entity_id for e in matched_entities]
                entity_doc_ids = set(get_entity_doc_ids(entity_ids, limit=50))
                metadata["matched_entities"] = [
                    {
                        "entity_id": e.entity_id,
                        "canonical_name": e.canonical_name,
                        "entity_type": e.entity_type,
                        "match_type": e.match_type,
                        "match_score": e.match_score
                    }
                    for e in matched_entities
                ]
                metadata["confidence_notes"].append(
                    f"Entity boost: {len(matched_entities)} entities matched, {len(entity_doc_ids)} associated docs"
                )
        except Exception as e:
            # Entity search is optional, don't fail the main search
            metadata["confidence_notes"].append(f"Entity search skipped: {str(e)}")

    # Fetch more candidates than needed for reranking pipeline
    fetch_k = RERANK_CANDIDATE_K if ENABLE_RERANKING else (k + 5 if entity_doc_ids else k)
    results = semantic_search(
        query=query,
        k=fetch_k,
        influencer=influencer,
        recipient=recipient,
        category=category,
        start_date=start_date,
        end_date=end_date,
        use_hyde=True,
        doc_id_filter=doc_id_filter,
    )

    # Apply entity boost before reranking (so entity docs survive the cut)
    if entity_doc_ids and results:
        for doc in results:
            if doc.get("doc_id") in entity_doc_ids:
                doc["relevance_score"] = min(1.0, doc["relevance_score"] + entity_boost_factor)
                doc["entity_boosted"] = True

        results.sort(key=lambda x: x["relevance_score"], reverse=True)

    # Cross-encoder reranking: precision stage
    if ENABLE_RERANKING:
        results = rerank_results(query, results, top_k=RERANK_TOP_K)
        metadata["confidence_notes"].append(
            f"Reranking: {RERANK_MODEL}, top {RERANK_TOP_K} from {fetch_k} candidates"
        )
    else:
        results = results[:k]

    # Re-number citations after reranking/re-sorting
    for idx, doc in enumerate(results, 1):
        doc["citation_number"] = idx

    # Store matched entities in metadata for context injection
    metadata["_matched_entities_full"] = matched_entities

    # Layered context: gather strategic summaries and event summaries
    # These are injected into the prompt by build_context_prompt()
    if include_strategic_context:
        try:
            sc = gather_strategic_context(
                influencer=influencer,
                recipient=recipient,
                category=category,
            )
            if sc:
                metadata["_strategic_context"] = sc
                metadata["confidence_notes"].append(
                    "Strategic context injected: pre-analyzed bilateral/category summaries"
                )
        except Exception as e:
            logger.warning("Strategic context gathering failed: %s", e)

    if include_event_context and not doc_id_filter:
        # Skip event search when project-scoped (doc_id_filter set)
        try:
            event_results = search_event_summaries(
                query=query,
                k=8,
                influencer=influencer,
                recipient=recipient,
            )
            if event_results:
                ec = format_event_context(event_results)
                metadata["_event_context"] = ec
                metadata["confidence_notes"].append(
                    f"Event context injected: {len(event_results)} relevant event summaries"
                )
        except Exception as e:
            logger.warning("Event summary search failed: %s", e)

    return results, metadata


def build_context_prompt(
    query: str,
    documents: List[Dict[str, Any]],
    matched_entities: Optional[List[MatchedEntity]] = None,
    strategic_context: Optional[str] = None,
    event_context: Optional[str] = None,
) -> str:
    """
    Build the context section of the prompt from retrieved documents and entities.

    Uses layered context injection:
    1. Strategic context (pre-analyzed bilateral/category summaries) — deterministic
    2. Event summaries (discovered via embedding search) — consolidated analysis
    3. Entity context (matched entities from query) — actor profiles
    4. Source documents (chunk_embeddings) — primary evidence for citations

    Uses token-aware packing: top-ranked docs get full text, remaining docs
    get truncated summaries, all packed to fill the model's context window
    up to MAX_CONTEXT_TOKENS.

    Args:
        query: The user's query
        documents: Retrieved documents for context
        matched_entities: Optional list of matched entities for context injection
        strategic_context: Pre-formatted strategic summary text
        event_context: Pre-formatted event summary text

    Returns:
        Formatted context string for the LLM prompt
    """
    context_parts = []
    token_budget = MAX_CONTEXT_TOKENS

    # Layer 1: Strategic context (bilateral/category summaries)
    if strategic_context:
        context_parts.append(strategic_context)
        token_budget -= count_tokens(strategic_context)

    # Layer 2: Event summaries (discovered via embedding search)
    if event_context:
        context_parts.append(event_context)
        token_budget -= count_tokens(event_context)

    # Layer 3: Entity context (matched entity profiles)
    if matched_entities:
        entity_context = build_entity_context(matched_entities)
        if entity_context:
            context_parts.append(entity_context)
            token_budget -= count_tokens(entity_context)

    if not documents:
        if context_parts:
            context_parts.append("No relevant documents found in the database.")
            return "\n\n".join(context_parts)
        return "No relevant documents found in the database."

    doc_parts = []
    tokens_used = 0

    for i, doc in enumerate(documents):
        # Build document header (always included)
        doc_info = f"[{doc['citation_number']}] "
        if doc.get('title'):
            doc_info += f"{doc['title']}"
        if doc.get('source_name'):
            doc_info += f" ({doc['source_name']})"
        if doc.get('date'):
            doc_info += f" - {doc['date']}"
        if doc.get('initiating_country') and doc.get('recipient_country'):
            doc_info += f"\nCountries: {doc['initiating_country']} → {doc['recipient_country']}"
        if doc.get('category'):
            doc_info += f" | Category: {doc['category']}"
        if doc.get('entity_boosted'):
            doc_info += " [Entity-relevant]"

        # Token-aware content inclusion: full text for top docs, truncated for rest
        content = doc.get('content', '')
        if i < MAX_FULL_TEXT_DOCS:
            # Top-ranked docs get full content
            doc_info += f"\n{content}"
        else:
            # Lower-ranked docs get truncated content
            doc_info += f"\n{content[:TRUNCATED_DOC_CHARS]}"
            if len(content) > TRUNCATED_DOC_CHARS:
                doc_info += "..."

        doc_tokens = count_tokens(doc_info)

        # Stop if we'd exceed the token budget
        if tokens_used + doc_tokens > token_budget:
            # Try with truncated content as last resort
            if i < MAX_FULL_TEXT_DOCS and len(content) > TRUNCATED_DOC_CHARS:
                doc_info_truncated = doc_info.split('\n')
                doc_info_truncated = '\n'.join(doc_info_truncated[:-1]) + f"\n{content[:TRUNCATED_DOC_CHARS]}..."
                trunc_tokens = count_tokens(doc_info_truncated)
                if tokens_used + trunc_tokens <= token_budget:
                    doc_parts.append(doc_info_truncated)
                    tokens_used += trunc_tokens
                    continue
            break

        doc_parts.append(doc_info)
        tokens_used += doc_tokens

    logger.info(f"Context packing: {len(doc_parts)}/{len(documents)} docs, ~{tokens_used} tokens used of {token_budget} budget")

    context_parts.append("\n\n---\n\n".join(doc_parts))
    return "\n\n".join(context_parts)


SYSTEM_PROMPT = """You are a senior research analyst specializing in soft power dynamics and international relations, writing in Associated Press (AP) style.

You have access to a curated database of diplomatic documents, news articles, and geopolitical analysis covering how China, Russia, Iran, Turkey, and the United States project influence across the Middle East and Africa.

## WRITING STANDARDS (AP Style)

**Be Specific and Concrete:**
- Lead with the most newsworthy facts: WHO did WHAT, WHERE, WHEN, and WHY
- Include specific figures: dollar amounts, dates, quantities, percentages
- Name specific projects, agreements, officials, and organizations
- Provide precise geographic references (cities, provinces, regions)
- Use exact dates or timeframes rather than vague temporal language

**Avoid Generic Language:**
- NEVER use phrases like "significant developments," "notable progress," "growing ties," or "increased cooperation" without immediately providing concrete evidence
- Replace "various initiatives" with specific named projects
- Replace "several countries" with the actual country names
- Replace "recently" with actual dates or timeframes
- Replace "substantial investment" with dollar figures

**Structure for Substance:**
- Open with the single most important finding or fact
- Each paragraph should contain at least one specific, verifiable claim
- Support every assertion with cited evidence from the documents
- When comparing periods or countries, use specific metrics

**Citation Requirements:**
- Cite sources inline using [1], [2], etc. matching the provided citation numbers
- Place citations immediately after the specific claim they support
- When synthesizing from multiple sources, cite all relevant documents

**What to Avoid:**
- Filler phrases: "It's worth noting," "Interestingly," "It should be mentioned"
- Qualifiers without substance: "somewhat," "relatively," "fairly"
- Passive constructions when active is clearer
- Repetition of what the user already asked
- Generic concluding summaries that add no new information

**If Information is Limited:**
- State clearly what IS known from the sources
- Identify specific gaps: "The documents do not specify the contract value" rather than "Details are unclear"
- Do not speculate or fill gaps with generic statements"""


def generate_comparative_assessment_stream(
    recipient: str,
    documents: List[Dict[str, Any]],
    metrics_context: str,
    model: str = "gpt-4o-mini",
    matched_entities: Optional[List[MatchedEntity]] = None,
    strategic_context: Optional[str] = None,
    event_context: Optional[str] = None,
) -> Generator[str, None, None]:
    """
    Generate a streaming comparative assessment of all influencers' activity
    in a single recipient country. Uses RAG sources + pre-computed metrics.

    Args:
        recipient: The recipient country being analyzed
        documents: Retrieved documents for context (from RAG search)
        metrics_context: Pre-formatted string of aggregated metrics from the page
        model: LLM model to use
        matched_entities: Optional matched entities for context injection
        strategic_context: Pre-analyzed bilateral/category summary text
        event_context: Discovered event summary text

    Yields:
        Response text chunks
    """
    context = build_context_prompt(
        f"Compare influencer activities in {recipient}",
        documents,
        matched_entities,
        strategic_context=strategic_context,
        event_context=event_context,
    )

    user_message = f"""AGGREGATED METRICS FOR {recipient}:

{metrics_context}

---

CONTEXT DOCUMENTS:
{context}

---

RESEARCH QUESTION: Provide a comparative assessment of how China, Russia, Iran, Turkey, and the United States compete for influence in {recipient}.

INSTRUCTIONS:
Provide a structured comparative assessment following AP style guidelines. This assessment accompanies charts and tables the analyst has already reviewed, so your role is to interpret the data and add depth from the source documents. Your analysis must:
- Lead with the most significant competitive dynamic — which influencer dominates overall and why
- Compare influencers directly: who leads in which category and by what margin, referencing the metrics provided
- Identify where influencers compete head-to-head vs. occupy distinct niches
- Note any recent shifts in the competitive balance, citing specific events or developments from the source documents
- Reference the quantitative data provided (document counts, event counts, materiality scores) to ground your comparisons
- Cite source documents inline using [1], [2], etc. for specific claims beyond the aggregate metrics
- Conclude with a brief forward-looking assessment of competitive trends
- Avoid generic characterizations — every comparison must be grounded in the data or sources provided"""

    try:
        stream_url = _get_proxy_stream_url()
        payload = {
            "sys_prompt": SYSTEM_PROMPT,
            "prompt": user_message,
            "model": model,
            "temperature": 0.4,
            "max_tokens": 4000,
        }

        with http_requests.post(stream_url, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                if data.get("error"):
                    yield f"\n\n[Error generating assessment: {data['error']}]"
                    return
                if data.get("done"):
                    return
                if "content" in data:
                    yield data["content"]

    except Exception as e:
        yield f"\n\n[Error generating assessment: {str(e)}]"


def generate_entity_assessment_stream(
    entity_name: str,
    documents: List[Dict[str, Any]],
    metrics_context: str,
    model: str = "gpt-4o-mini",
    matched_entities: Optional[List[MatchedEntity]] = None,
    strategic_context: Optional[str] = None,
    event_context: Optional[str] = None,
) -> Generator[str, None, None]:
    """
    Generate a streaming assessment of an entity's influence and activities.

    Args:
        entity_name: The entity being assessed
        documents: Retrieved documents scoped to this entity
        metrics_context: Pre-formatted string of entity metrics
        model: LLM model to use
        matched_entities: Optional matched entities for context injection
        strategic_context: Pre-analyzed bilateral/category summary text
        event_context: Discovered event summary text

    Yields:
        Response text chunks
    """
    context = build_context_prompt(
        f"Assess {entity_name} influence and activities",
        documents,
        matched_entities,
        strategic_context=strategic_context,
        event_context=event_context,
    )

    user_message = f"""ENTITY PROFILE:

{metrics_context}

---

CONTEXT DOCUMENTS:
{context}

---

RESEARCH QUESTION: Provide a comprehensive assessment of {entity_name}'s role, influence, and activities in soft power dynamics.

INSTRUCTIONS:
Provide a structured assessment following AP style guidelines. This accompanies metrics and charts the analyst has already reviewed. Your analysis must:
- Summarize the entity's primary role and significance, grounding claims in the source documents
- Identify their dominant areas of activity, referencing the category breakdown provided
- Describe their geographic engagement pattern across recipient countries with specific examples
- Highlight key relationships and partnerships with other entities, citing source evidence
- Note temporal patterns — periods of high or low activity and any recent developments
- Reference the quantitative data provided (document counts, active days, category distribution)
- Cite source documents inline using [1], [2], etc. for specific claims
- Avoid generic characterizations — every claim must be grounded in data or sources"""

    try:
        stream_url = _get_proxy_stream_url()
        payload = {
            "sys_prompt": SYSTEM_PROMPT,
            "prompt": user_message,
            "model": model,
            "temperature": 0.4,
            "max_tokens": 4000,
        }

        with http_requests.post(stream_url, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                if data.get("error"):
                    yield f"\n\n[Error generating assessment: {data['error']}]"
                    return
                if data.get("done"):
                    return
                if "content" in data:
                    yield data["content"]

    except Exception as e:
        yield f"\n\n[Error generating assessment: {str(e)}]"


def generate_response_stream(
    query: str,
    documents: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    matched_entities: Optional[List[MatchedEntity]] = None,
    strategic_context: Optional[str] = None,
    event_context: Optional[str] = None,
) -> Generator[str, None, None]:
    """
    Generate a streaming response using the LLM via the proxy endpoint.

    Routes through /proxy_query_stream so LLM credentials and network
    access are handled by the FastAPI server, not the container directly.

    Args:
        query: User's question
        documents: Retrieved documents for context
        model: LLM model to use
        matched_entities: Optional list of matched entities for context injection
        strategic_context: Pre-analyzed bilateral/category summary text
        event_context: Discovered event summary text

    Yields:
        Response text chunks
    """
    # Build the layered context from all sources
    context = build_context_prompt(
        query, documents, matched_entities,
        strategic_context=strategic_context,
        event_context=event_context,
    )

    user_message = f"""CONTEXT DOCUMENTS:
{context}

---

RESEARCH QUESTION: {query}

INSTRUCTIONS:
Provide a detailed, analytically rigorous response following AP style guidelines. Your answer must:
- Lead with the most significant finding
- Include specific names, dates, figures, and locations from the sources
- Cite each factual claim with [1], [2], etc.
- Avoid generic characterizations—every statement should be substantive and verifiable
- If the sources lack specific information, state exactly what is missing rather than using vague language"""

    try:
        stream_url = _get_proxy_stream_url()
        payload = {
            "sys_prompt": SYSTEM_PROMPT,
            "prompt": user_message,
            "model": model,
            "temperature": 0.4,
            "max_tokens": 4000
        }

        with http_requests.post(stream_url, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                if data.get("error"):
                    yield f"\n\n[Error generating response: {data['error']}]"
                    return
                if data.get("done"):
                    return
                if "content" in data:
                    yield data["content"]

    except Exception as e:
        yield f"\n\n[Error generating response: {str(e)}]"


def generate_response(
    query: str,
    documents: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    matched_entities: Optional[List[MatchedEntity]] = None,
    strategic_context: Optional[str] = None,
    event_context: Optional[str] = None,
) -> str:
    """
    Generate a non-streaming response using the LLM.

    Args:
        query: User's question
        documents: Retrieved documents for context
        model: LLM model to use
        matched_entities: Optional list of matched entities for context injection
        strategic_context: Pre-analyzed bilateral/category summary text
        event_context: Discovered event summary text

    Returns:
        Complete response text
    """
    response_parts = []
    for chunk in generate_response_stream(
        query, documents, model, matched_entities,
        strategic_context=strategic_context,
        event_context=event_context,
    ):
        response_parts.append(chunk)
    return "".join(response_parts)


def format_export(messages: List[Dict[str, Any]], format_type: str = "markdown") -> str:
    """
    Format chat messages for export.

    Args:
        messages: List of chat messages with role, content, sources
        format_type: Export format (markdown, json, txt)

    Returns:
        Formatted export string
    """
    if format_type == "json":
        return json.dumps({
            "exported_at": datetime.now().isoformat(),
            "messages": messages
        }, indent=2)

    elif format_type == "markdown":
        lines = [
            "# Chat Export",
            f"*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "---",
            ""
        ]

        for msg in messages:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")

            if role == "User":
                lines.append("## User Question")
                lines.append(f"> {content}")
            else:
                lines.append("## Assistant Response")
                lines.append(content)

            # Add sources if present
            sources = msg.get("sources", [])
            if sources:
                lines.append("")
                lines.append("### Sources")
                for src in sources:
                    lines.append(f"- [{src.get('citation_number')}] {src.get('title', 'Untitled')} ({src.get('source_name', 'Unknown')}) - {src.get('date', 'No date')}")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    else:  # txt
        lines = [
            "CHAT EXPORT",
            f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 50,
            ""
        ]

        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")

            lines.append(f"[{role}]")
            lines.append(content)
            lines.append("")
            lines.append("-" * 50)
            lines.append("")

        return "\n".join(lines)
