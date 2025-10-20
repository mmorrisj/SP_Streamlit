import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from shared.utils.utils import Config
from backend.scripts.models import DailySummary, WeeklySummary, DailyEventSummary
from sqlalchemy import select, and_, or_, func, desc, text
from db import engine
import requests
from dotenv import load_dotenv
import os
import json
import altair as alt
from typing import List, Dict, Any
import psycopg2
from sentence_transformers import SentenceTransformer

load_dotenv()

# Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
cfg = Config.from_yaml()
FASTAPI_URL = f"http://host.docker.internal:5002/query"

# Page config
st.set_page_config(
    page_title="Direct Vector RAG", 
    page_icon="🎯", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .vector-result {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .similarity-score {
        background-color: #e8f5e8;
        border: 1px solid #4caf50;
        border-radius: 4px;
        padding: 0.3rem;
        margin: 0.2rem 0;
        font-family: monospace;
        font-size: 0.9rem;
    }
    .context-preview {
        background-color: #f8f9fa;
        border-left: 4px solid #1f77b4;
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 0 8px 8px 0;
        max-height: 400px;
        overflow-y: auto;
    }
</style>
""", unsafe_allow_html=True)

class DirectVectorRAG:
    """RAG engine using direct pgvector queries (no LangChain dependency)"""
    
    def __init__(self):
        self.engine = engine
        self.max_context_length = 4000
        # Initialize embedding model
        try:
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception:
            # Fallback if sentence-transformers not available
            self.embedding_model = None
            st.warning("Sentence transformers not available. Vector search disabled.")
    
    @st.cache_data(ttl=300)
    def get_query_embedding(_self, query: str) -> np.ndarray:
        """Generate embedding for user query"""
        if _self.embedding_model is None:
            return np.array([])
        return _self.embedding_model.encode([query])[0]
    
    def get_available_collections(self) -> List[str]:
        """Get list of available vector collections"""
        sql = text("SELECT name FROM langchain_pg_collection ORDER BY name")
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql)
                return [row[0] for row in result]
        except Exception:
            return []
    
    from sqlalchemy import text

    def search_vector_collection(
        self, query_embedding: np.ndarray, collection_name: str, 
        countries: List[str], start_date: date, end_date: date, limit: int = 5
    ) -> List[Dict]:
        if len(query_embedding) == 0:
            return []

        # If you DON'T have the pgvector adapter registered, set this to True
        USE_STRING_LITERAL_VECTOR = False

        if USE_STRING_LITERAL_VECTOR:
            embedding_param = "[" + ", ".join(f"{float(x):.6f}" for x in query_embedding.tolist()) + "]"
            emb_expr = ":embedding::vector"
        else:
            embedding_param = query_embedding.tolist()
            emb_expr = ":embedding"

        sql = """
            SELECT 
                cmetadata,
                document AS content,
                embedding <-> {emb} AS distance
            FROM langchain_pg_embedding
            WHERE collection_id = (
                SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name
            )
        """.format(emb=emb_expr)

        conds = []
        params = {
            "collection_name": collection_name,
            "embedding": embedding_param,
            "limit": int(limit)
        }

        if countries:
            conds.append("(cmetadata->>'initiating_country') = ANY(:countries)")
            params["countries"] = countries

        if start_date and end_date:
            conds.append("""
            (
            (cmetadata ? 'report_date' AND (cmetadata->>'report_date')::date BETWEEN :start_date AND :end_date)
            OR
            (cmetadata ? 'date'        AND (cmetadata->>'date')::date        BETWEEN :start_date AND :end_date)
            )
            """)
            params["start_date"] = start_date
            params["end_date"] = end_date

        if conds:
            sql += " AND " + " AND ".join(conds)

        sql += f" ORDER BY embedding <-> {emb_expr} LIMIT :limit"

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params)

                out = []
                for row in result:
                    metadata = row[0] or {}
                    content = row[1] or ""
                    distance = float(row[2]) if row[2] is not None else 1.0

                    # IMPORTANT: if your index/opclass is L2, 1 - distance is NOT a true similarity.
                    # Prefer score = 1 / (1 + distance) OR switch to cosine (<=>) and then sim = 1 - dist.
                    score = 1.0 / (1.0 + distance)

                    out.append({
                        "content": content,
                        "metadata": metadata,
                        "distance": distance,
                        "similarity": score,
                        "collection": collection_name
                    })
                return out
        except Exception as e:
            st.error(f"Vector search failed for {collection_name}: {e}")
            return []
        
    def hybrid_search(self, query: str, countries: List[str], recipients: List[str],
                     categories: List[str], start_date: date, end_date: date,
                     collections_to_search: List[str], k_per_collection: int = 3) -> Dict[str, Any]:
        """Perform hybrid search across selected collections"""
        
        if self.embedding_model is None:
            return self.fallback_to_sql_search(query, countries, start_date, end_date)
        
        # Generate query embedding
        query_embedding = self.get_query_embedding(query)
        
        all_results = []
        search_metadata = {
            "query": query,
            "collections_searched": [],
            "total_results": 0,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
        }
        
        # Search each selected collection
        for collection in collections_to_search:
            try:
                collection_results = self.search_vector_collection(
                    query_embedding, collection, countries, start_date, end_date, k_per_collection
                )
                
                if collection_results:
                    all_results.extend(collection_results)
                    search_metadata["collections_searched"].append(collection)
                    
            except Exception as e:
                st.warning(f"Failed to search {collection}: {e}")
        
        # Sort all results by similarity and take top results
        all_results.sort(key=lambda x: x["similarity"], reverse=True)
        top_results = all_results[:k_per_collection * len(collections_to_search)]
        
        search_metadata["total_results"] = len(top_results)
        
        # Build context
        context = self._build_context_from_results(top_results)
        
        return {
            "context": context,
            "results": top_results,
            "metadata": search_metadata
        }
    
    def fallback_to_sql_search(self, query: str, countries: List[str], 
                              start_date: date, end_date: date) -> Dict[str, Any]:
        """Fallback to SQL-based search when embeddings not available"""
        
        # Search daily summaries with text matching
        stmt = select(
            DailySummary.date,
            DailySummary.initiating_country,
            DailySummary.aggregate_summary
        ).where(
            and_(
                DailySummary.initiating_country.in_(countries),
                DailySummary.date.between(start_date, end_date),
                DailySummary.aggregate_summary.isnot(None),
                or_(
                    DailySummary.aggregate_summary.ilike(f"%{word}%") 
                    for word in query.split()[:3]  # Use first 3 words
                )
            )
        ).order_by(desc(DailySummary.date)).limit(10)
        
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(stmt, conn)
            
            results = []
            for _, row in df.iterrows():
                results.append({
                    "content": row['aggregate_summary'],
                    "metadata": {
                        "date": row['date'].isoformat(),
                        "initiating_country": row['initiating_country']
                    },
                    "similarity": 0.5,  # Default similarity for text search
                    "collection": "sql_fallback"
                })
            
            context = "\n\n".join([r["content"] for r in results])
            
            return {
                "context": context,
                "results": results,
                "metadata": {
                    "query": query,
                    "collections_searched": ["sql_fallback"],
                    "total_results": len(results),
                    "note": "Fallback to SQL text search (vector embeddings not available)"
                }
            }
            
        except Exception as e:
            st.error(f"Fallback search failed: {e}")
            return {"context": "", "results": [], "metadata": {}}
    
    def _build_context_from_results(self, results: List[Dict]) -> str:
        """Build context string from search results"""
        if not results:
            return ""
        
        context_parts = []
        
        # Group by collection for organization
        by_collection = {}
        for result in results:
            collection = result["collection"]
            if collection not in by_collection:
                by_collection[collection] = []
            by_collection[collection].append(result)
        
        for collection, coll_results in by_collection.items():
            # Add section header
            if "daily" in collection:
                context_parts.append("## Recent Daily Intelligence")
            elif "weekly" in collection:
                context_parts.append("## Weekly Analysis")
            elif "monthly" in collection:
                context_parts.append("## Monthly Trends")
            else:
                context_parts.append(f"## {collection.title()} Results")
            
            # Add top results from this collection
            for result in coll_results[:3]:
                metadata = result["metadata"]
                content = result["content"]
                similarity = result["similarity"]
                
                # Format metadata
                meta_info = []
                if "event_name" in metadata:
                    meta_info.append(f"Event: {metadata['event_name']}")
                if "initiating_country" in metadata:
                    meta_info.append(f"Country: {metadata['initiating_country']}")
                if "report_date" in metadata:
                    meta_info.append(f"Date: {metadata['report_date']}")
                elif "date" in metadata:
                    meta_info.append(f"Date: {metadata['date']}")
                
                meta_str = " | ".join(meta_info) if meta_info else "Source"
                context_parts.append(f"**{meta_str}** (Similarity: {similarity:.3f}): {content}")
        
        full_context = "\n\n".join(context_parts)
        
        # Truncate if needed
        if len(full_context) > self.max_context_length:
            full_context = full_context[:self.max_context_length] + "\n[Context truncated]"
        
        return full_context

def query_gai_via_gateway(prompt: str, model: str = "gpt-4o") -> str:
    """Query GAI service"""
    payload = {"prompt": prompt, "model": model}
    try:
        res = requests.post(FASTAPI_URL, json=payload, timeout=30)
        res.raise_for_status()
        return res.json().get("response", "No response received")
    except Exception as e:
        return f"[Error]: {e}"

# Initialize RAG engine
@st.cache_resource
def get_direct_rag_engine():
    return DirectVectorRAG()

rag_engine = get_direct_rag_engine()

# Main UI
st.markdown('<h1 class="main-header">🎯 Direct Vector RAG</h1>', unsafe_allow_html=True)

# Get available collections
available_collections = rag_engine.get_available_collections()

# Sidebar
with st.sidebar:
    st.header("🔍 Search Configuration")
    
    # Standard filters
    country_options = cfg.influencers
    selected_countries = st.multiselect(
        "Initiating Countries", 
        country_options, 
        default=country_options[:2] if country_options else []
    )
    
    # Date range
    default_start = date.today() - timedelta(days=90)
    start_date = st.date_input("Start Date", default_start)
    end_date = st.date_input("End Date", date.today())
    
    # Vector collection selection
    if available_collections:
        st.subheader("Vector Collections")
        selected_collections = st.multiselect(
            "Collections to Search",
            available_collections,
            default=available_collections[:3] if len(available_collections) >= 3 else available_collections,
            help="Select which vector collections to search"
        )
        
        k_per_collection = st.slider(
            "Results per Collection",
            min_value=1,
            max_value=10,
            value=3
        )
    else:
        st.warning("No vector collections found")
        selected_collections = []
        k_per_collection = 3
    
    # Show collection info
    if available_collections:
        st.info(f"Found {len(available_collections)} vector collections")
        with st.expander("Available Collections"):
            for collection in available_collections:
                st.write(f"• {collection}")

# Main query interface
user_query = st.text_area(
    "Your Query:",
    height=100,
    placeholder="Enter your question for semantic vector search...",
    help="This will perform semantic similarity search across your vector collections"
)

# Search execution
if st.button("🚀 Execute Search", type="primary"):
    if not user_query.strip():
        st.warning("Please enter a search query.")
    elif not selected_countries:
        st.warning("Please select at least one initiating country.")
    elif not selected_collections:
        st.warning("Please select at least one vector collection to search.")
    else:
        with st.spinner("🔍 Searching vector collections..."):
            # Perform search
            search_results = rag_engine.hybrid_search(
                user_query, 
                selected_countries, 
                [], [], # recipients, categories not implemented in this version
                start_date, 
                end_date,
                selected_collections,
                k_per_collection
            )
        
        if not search_results["context"].strip():
            st.error("❌ No relevant results found. Try different search terms or date range.")
        else:
            # Show search metadata
            metadata = search_results["metadata"]
            col1, col2, col3 = st.columns(3)
            col1.metric("Collections Searched", len(metadata.get("collections_searched", [])))
            col2.metric("Results Found", metadata.get("total_results", 0))
            col3.metric("Context Length", f"{len(search_results['context']):,}")
            
            # Show search results
            if search_results["results"]:
                st.subheader("🎯 Top Semantic Matches")
                
                for i, result in enumerate(search_results["results"][:5]):
                    with st.expander(f"Result {i+1} - {result['collection']} (Similarity: {result['similarity']:.3f})"):
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.write(result["content"][:500] + "..." if len(result["content"]) > 500 else result["content"])
                        
                        with col2:
                            st.markdown(f'<div class="similarity-score">Similarity: {result["similarity"]:.3f}</div>', 
                                      unsafe_allow_html=True)
                            
                            # Show metadata
                            metadata_display = result["metadata"]
                            if metadata_display:
                                st.json(metadata_display)
            
            # Generate AI response
            enhanced_prompt = f"""You are a geopolitical analyst. Based on the vector search results below, provide a comprehensive analysis.

The following content was retrieved using semantic similarity search from multiple intelligence collections:

{search_results["context"]}

User Query: {user_query}

Analysis:"""
            
            with st.spinner("🤖 Generating analysis..."):
                ai_response = query_gai_via_gateway(enhanced_prompt)
            
            st.subheader("📊 AI Analysis")
            st.markdown(ai_response)

else:
    # Show instructions when no query
    st.info("""
    **How to use Direct Vector RAG:**
    
    1. **Select countries** to filter results by initiating country
    2. **Choose date range** for temporal filtering  
    3. **Select vector collections** to search (daily, weekly, monthly events)
    4. **Enter your query** - works best with conceptual questions
    5. **Execute search** to find semantically similar content
    
    This system searches pre-computed vector embeddings for semantic similarity, 
    not just keyword matching.
    """)

# Footer
st.markdown("---")
st.caption("🎯 Direct pgvector RAG | No LangChain dependency | Pure SQL + embeddings")