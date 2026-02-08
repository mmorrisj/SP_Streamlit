"""
RAG Service for Chat functionality.
Provides semantic search and LLM-powered response generation.
"""
import os
import re
import json
from typing import Optional, List, Dict, Any, Generator, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from openai import AzureOpenAI, OpenAI
from langchain_huggingface import HuggingFaceEmbeddings
from sqlalchemy import text
import torch

from shared.database.database import get_session, get_engine


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
    top_k: int = 5,
    semantic_threshold: float = 0.6,
    fuzzy_threshold: float = 0.7
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
                # pg_trgm might not be installed, skip fuzzy matching
                pass

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
                # pgvector might not work as expected, skip semantic matching
                pass

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


# Auto-detect device for embeddings
device = "cuda" if torch.cuda.is_available() else "cpu"

# Lazy-loaded embedding function
_embedding_function = None

def get_embedding_function():
    """Get or create the embedding function (lazy loading)."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": device}
        )
    return _embedding_function


def get_llm_client():
    """Get OpenAI client (Azure or direct)."""
    # Try Azure first
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")

    if azure_endpoint and azure_key:
        return AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version="2024-08-01-preview"
        ), "azure"

    # Fall back to OpenAI
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_PROJ_API")
    if openai_key:
        return OpenAI(api_key=openai_key), "openai"

    raise ValueError("No LLM API credentials found. Set AZURE_OPENAI_ENDPOINT/AZURE_OPENAI_API_KEY or OPENAI_API_KEY.")


def semantic_search(
    query: str,
    k: int = 10,
    influencer: Optional[str] = None,
    recipient: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Perform semantic search on document embeddings with optional filters.

    Args:
        query: Search query text
        k: Number of results to return
        influencer: Filter by initiating country
        recipient: Filter by recipient country
        category: Filter by category
        start_date: Filter by start date (YYYY-MM-DD)
        end_date: Filter by end date (YYYY-MM-DD)

    Returns:
        List of matching documents with metadata and relevance scores
    """
    # Generate query embedding
    embeddings = get_embedding_function()
    query_embedding = embeddings.embed_query(query)

    # Format embedding as PostgreSQL vector literal
    # pgvector expects format like '[0.1,0.2,0.3,...]'
    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

    # Build the SQL query with vector similarity search
    # Using pgvector's <=> operator for cosine distance
    # Note: embedding is interpolated directly since parameter binding doesn't work with ::vector cast
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
            r.content,
            r.cmetadata,
            r.similarity,
            d.doc_id,
            d.title,
            d.source_name,
            d.date,
            d.initiating_country,
            d.recipient_country,
            d.category,
            d.salience
        FROM ranked_docs r
        LEFT JOIN documents d ON r.cmetadata->>'doc_id' = d.doc_id
        WHERE 1=1
    """

    params = {
        "limit": k
    }

    # Add filters
    if influencer:
        sql += " AND d.initiating_country = :influencer"
        params["influencer"] = influencer

    if recipient:
        sql += " AND d.recipient_country = :recipient"
        params["recipient"] = recipient

    if category:
        sql += " AND d.category = :category"
        params["category"] = category

    if start_date:
        sql += " AND d.date >= :start_date"
        params["start_date"] = start_date

    if end_date:
        sql += " AND d.date <= :end_date"
        params["end_date"] = end_date

    sql += " ORDER BY r.distance ASC LIMIT :limit"

    results = []
    engine = get_engine()

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

        for idx, row in enumerate(rows, 1):
            results.append({
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
            })

    return results


def intelligent_search(
    query: str,
    k: int = 10,
    influencer: Optional[str] = None,
    recipient: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    apply_intelligence: bool = True,
    enable_entity_boost: bool = True,
    entity_boost_factor: float = 0.15
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

    if apply_intelligence:
        # Analyze query and merge with explicit filters
        inferred_inf, inferred_rec, inferred_cat, inferred_start, inferred_end, notes = apply_query_intelligence(
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
            matched_entities = search_entities(query, top_k=5)
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

    # Perform the actual search (fetch extra if we're doing entity boost)
    fetch_k = k + 5 if entity_doc_ids else k
    results = semantic_search(
        query=query,
        k=fetch_k,
        influencer=influencer,
        recipient=recipient,
        category=category,
        start_date=start_date,
        end_date=end_date
    )

    # Apply entity boost: increase relevance score for documents mentioning matched entities
    if entity_doc_ids and results:
        for doc in results:
            if doc.get("doc_id") in entity_doc_ids:
                doc["relevance_score"] = min(1.0, doc["relevance_score"] + entity_boost_factor)
                doc["entity_boosted"] = True

        # Re-sort by boosted relevance and take top k
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        results = results[:k]

        # Re-number citations after re-sorting
        for idx, doc in enumerate(results, 1):
            doc["citation_number"] = idx

    # Store matched entities in metadata for context injection
    metadata["_matched_entities_full"] = matched_entities

    return results, metadata


def build_context_prompt(
    query: str,
    documents: List[Dict[str, Any]],
    matched_entities: Optional[List[MatchedEntity]] = None
) -> str:
    """
    Build the context section of the prompt from retrieved documents and entities.

    Args:
        query: The user's query
        documents: Retrieved documents for context
        matched_entities: Optional list of matched entities for context injection

    Returns:
        Formatted context string for the LLM prompt
    """
    context_parts = []

    # Inject entity context if available
    if matched_entities:
        entity_context = build_entity_context(matched_entities)
        if entity_context:
            context_parts.append(entity_context)

    if not documents:
        if context_parts:
            context_parts.append("No relevant documents found in the database.")
            return "\n\n".join(context_parts)
        return "No relevant documents found in the database."

    doc_parts = []
    for doc in documents:
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

        doc_info += f"\n{doc.get('content', '')[:1500]}"  # Truncate long content
        doc_parts.append(doc_info)

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


def generate_response_stream(
    query: str,
    documents: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    matched_entities: Optional[List[MatchedEntity]] = None
) -> Generator[str, None, None]:
    """
    Generate a streaming response using the LLM.

    Args:
        query: User's question
        documents: Retrieved documents for context
        model: LLM model to use
        matched_entities: Optional list of matched entities for context injection

    Yields:
        Response text chunks
    """
    client, client_type = get_llm_client()

    # Build the context from documents and entities
    context = build_context_prompt(query, documents, matched_entities)

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

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]

    try:
        if client_type == "azure":
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", model)
            stream = client.chat.completions.create(
                model=deployment,
                messages=messages,
                stream=True,
                temperature=0.4,  # Lower temperature for more precise, factual responses
                max_tokens=4000
            )
        else:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.4,  # Lower temperature for more precise, factual responses
                max_tokens=4000
            )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    except Exception as e:
        yield f"\n\n[Error generating response: {str(e)}]"


def generate_response(
    query: str,
    documents: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    matched_entities: Optional[List[MatchedEntity]] = None
) -> str:
    """
    Generate a non-streaming response using the LLM.

    Args:
        query: User's question
        documents: Retrieved documents for context
        model: LLM model to use
        matched_entities: Optional list of matched entities for context injection

    Returns:
        Complete response text
    """
    response_parts = []
    for chunk in generate_response_stream(query, documents, model, matched_entities):
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
                lines.append(f"## User Question")
                lines.append(f"> {content}")
            else:
                lines.append(f"## Assistant Response")
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
