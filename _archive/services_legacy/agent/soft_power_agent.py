"""
Soft Power Analytics Conversational Agent

An agentic Q&A system that combines RAG retrieval with structured analytics tools
to answer questions about soft power activities, events, and relationships.
"""

import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from shared.utils.utils import gai
from services.agent.query_engine import QueryEngine
from services.agent.tools.analytics_tools import (
    get_country_activity_stats,
    get_bilateral_relationship_summary,
    get_trending_events,
    get_category_trends,
    compare_countries
)


# System prompt for the agent
AGENT_SYSTEM_PROMPT = """You are an expert analyst specializing in soft power and international relations. You have access to a comprehensive database of soft power activities, including:

- Event summaries (daily, weekly, monthly) for major countries
- Source documents from news and diplomatic sources
- Bilateral relationship summaries
- Activity statistics and trends

Your role is to:
1. Answer questions accurately using the available data
2. Provide context and analysis when appropriate
3. Use tools to gather relevant information
4. Cite sources when making specific claims
5. Acknowledge limitations when data is insufficient

Available Tools:
- search_events: Semantic search across event summaries
- search_documents: Semantic search across source documents
- get_country_stats: Get activity statistics for a country
- get_bilateral_summary: Get relationship summary between two countries
- get_trending_events: Find currently trending events
- get_category_trends: Analyze trends for a specific category
- compare_countries: Compare activity across multiple countries

Guidelines:
- Always use tools to gather data before answering
- Combine multiple tool results for comprehensive answers
- Be specific with dates, countries, and categories
- Format responses clearly with sections and bullet points
- Include relevant metrics and statistics
"""


class SoftPowerAgent:
    """Conversational agent for soft power analytics."""

    def __init__(self):
        """Initialize the agent with query engine and tools."""
        self.query_engine = QueryEngine()
        self.conversation_history = []

        # Map tool names to functions
        self.tools = {
            'search_events': self._search_events,
            'search_documents': self._search_documents,
            'get_country_stats': self._get_country_stats,
            'get_bilateral_summary': self._get_bilateral_summary,
            'get_trending_events': self._get_trending_events,
            'get_category_trends': self._get_category_trends,
            'compare_countries': self._compare_countries
        }

    def _search_events(self, query: str, **kwargs) -> Dict:
        """Search event summaries."""
        return {'results': self.query_engine.search_event_summaries(query, **kwargs)}

    def _search_documents(self, query: str, **kwargs) -> Dict:
        """Search source documents."""
        return {'results': self.query_engine.search_documents(query, **kwargs)}

    def _get_country_stats(self, country: str, **kwargs) -> Dict:
        """Get country activity stats."""
        return get_country_activity_stats(country, **kwargs)

    def _get_bilateral_summary(self, initiating_country: str, recipient_country: str) -> Dict:
        """Get bilateral relationship summary."""
        result = get_bilateral_relationship_summary(initiating_country, recipient_country)
        return result if result else {'error': 'No bilateral summary found'}

    def _get_trending_events(self, **kwargs) -> Dict:
        """Get trending events."""
        return {'results': get_trending_events(**kwargs)}

    def _get_category_trends(self, category: str, **kwargs) -> Dict:
        """Get category trend analysis."""
        return get_category_trends(category, **kwargs)

    def _compare_countries(self, countries: List[str], **kwargs) -> Dict:
        """Compare activity across countries."""
        return compare_countries(countries, **kwargs)

    def query(
        self,
        user_query: str,
        conversation_context: Optional[List[Dict]] = None
    ) -> Tuple[str, List[Dict]]:
        """
        Process a user query using the agentic RAG system.

        Args:
            user_query: Natural language question
            conversation_context: Previous conversation history

        Returns:
            Tuple of (response_text, sources_used)
        """
        # Build conversation context
        context = conversation_context or self.conversation_history

        # Step 1: Determine which tools to use
        tool_selection_prompt = f"""Given this user query, determine which tools would be most helpful to answer it.

User Query: {user_query}

Available Tools:
- search_events: Semantic search for events (use for "what events", "what happened", "activities related to")
- search_documents: Search source documents (use for detailed information, specific quotes)
- get_country_stats: Statistics for a country (use for "how active", "statistics", "metrics")
- get_bilateral_summary: Relationship between countries (use for "relationship between", "interactions with")
- get_trending_events: Current trending events (use for "recent", "trending", "latest")
- get_category_trends: Category analysis (use for "trend in", "over time", specific categories)
- compare_countries: Country comparison (use for "compare", "difference between")

Return ONLY a JSON array of tool names to use, for example: ["search_events", "get_country_stats"]
"""

        tool_response = gai(
            sys_prompt="You are a tool selection expert. Return only valid JSON arrays.",
            user_prompt=tool_selection_prompt,
            model="gpt-4o-mini",
            use_proxy=True
        )

        # Parse tool selection
        try:
            if isinstance(tool_response, str):
                selected_tools = json.loads(tool_response)
            else:
                selected_tools = tool_response
        except (json.JSONDecodeError, TypeError):
            # Fallback to search if parsing fails
            selected_tools = ["search_events"]

        # Step 2: Execute selected tools
        tool_results = {}
        sources = []

        for tool_name in selected_tools:
            if tool_name not in self.tools:
                continue

            # Extract parameters from query (simplified - you could make this more sophisticated)
            try:
                if tool_name == 'search_events':
                    results = self.tools[tool_name](user_query, limit=5)
                    tool_results[tool_name] = results
                    if results.get('results'):
                        sources.extend(results['results'])

                elif tool_name == 'search_documents':
                    results = self.tools[tool_name](user_query, limit=5)
                    tool_results[tool_name] = results
                    if results.get('results'):
                        sources.extend(results['results'])

                elif tool_name in ['get_country_stats', 'get_bilateral_summary', 'compare_countries']:
                    # These require specific parameters - skip for now or use query analysis
                    # In production, you'd parse the query to extract country names
                    pass

                elif tool_name == 'get_trending_events':
                    results = self.tools[tool_name](limit=10)
                    tool_results[tool_name] = results

            except Exception as e:
                print(f"Error executing tool {tool_name}: {e}")
                continue

        # Step 3: Generate response using tool results
        response_prompt = f"""Answer the user's question using the retrieved information.

User Question: {user_query}

Retrieved Information:
{json.dumps(tool_results, indent=2, default=str)}

Guidelines:
1. Provide a clear, comprehensive answer
2. Reference specific events, dates, and statistics when available
3. Organize information logically with sections if needed
4. Be factual and avoid speculation
5. Acknowledge if information is incomplete

Format your response in clear markdown with:
- **Bold** for emphasis
- Bullet points for lists
- ### Headers for sections
"""

        response = gai(
            sys_prompt=AGENT_SYSTEM_PROMPT,
            user_prompt=response_prompt,
            model="gpt-4o-mini",
            use_proxy=True
        )

        # Extract text response
        if isinstance(response, dict):
            response_text = response.get('response', str(response))
        else:
            response_text = response

        # Update conversation history
        self.conversation_history.append({
            'role': 'user',
            'content': user_query,
            'timestamp': datetime.now().isoformat()
        })
        self.conversation_history.append({
            'role': 'assistant',
            'content': response_text,
            'timestamp': datetime.now().isoformat(),
            'sources': sources
        })

        return response_text, sources

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []

    def get_history(self) -> List[Dict]:
        """Get conversation history."""
        return self.conversation_history


def create_agent() -> SoftPowerAgent:
    """Factory function to create a new agent instance."""
    return SoftPowerAgent()
