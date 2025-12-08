"""
Chat with Soft Power Data

An interactive conversational interface powered by RAG and LLM agents.
Ask questions about events, trends, relationships, and soft power activities.
"""

import streamlit as st
from datetime import datetime, date, timedelta
import sys
from pathlib import Path
import yaml

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import agent - handle module not found gracefully
try:
    from services.agent.soft_power_agent import create_agent
except ModuleNotFoundError as e:
    st.error(f"""
    **Agent module not found.** This feature requires the agentic capabilities to be installed.

    Error: {str(e)}

    Project root: {project_root}
    Python path: {sys.path[:3]}

    Please ensure you're running from the correct directory and the `services/agent` module exists.
    """)
    st.stop()


# Load config for country lists
@st.cache_data
def load_config():
    config_path = project_root / "shared" / "config" / "config.yaml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

config = load_config()
INFLUENCERS = config.get('influencers', [])
RECIPIENTS = config.get('recipients', [])

# Page configuration
st.set_page_config(
    page_title="Chat with Data",
    page_icon="💬",
    layout="wide"
)

st.title("💬 Chat with Soft Power Data")
st.markdown("""
Ask questions about soft power activities, events, trends, and bilateral relationships.
The AI agent uses semantic search and analytics tools to provide accurate, data-driven answers.
""")

# Initialize session state
if 'agent' not in st.session_state:
    with st.spinner("Initializing AI agent..."):
        st.session_state.agent = create_agent()

if 'messages' not in st.session_state:
    st.session_state.messages = []

# Initialize filter state
if 'filters' not in st.session_state:
    st.session_state.filters = {
        'start_date': date(2024, 8, 1),
        'end_date': date.today(),
        'initiating_country': None,
        'recipient_countries': []
    }

# Sidebar with filters
st.sidebar.header("🔍 Query Filters")

# Date range filter
st.sidebar.subheader("Date Range")
col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input(
        "Start Date",
        value=st.session_state.filters['start_date'],
        min_value=date(2024, 1, 1),
        max_value=date.today(),
        key="filter_start_date"
    )
with col2:
    end_date = st.date_input(
        "End Date",
        value=st.session_state.filters['end_date'],
        min_value=date(2024, 1, 1),
        max_value=date.today(),
        key="filter_end_date"
    )

# Country filters
st.sidebar.subheader("Countries")
initiating_country = st.sidebar.selectbox(
    "Initiating Country",
    options=[None] + INFLUENCERS,
    index=0,
    help="Select an influencer country or leave blank for all"
)

recipient_countries = st.sidebar.multiselect(
    "Recipient Country/ies",
    options=RECIPIENTS,
    default=st.session_state.filters['recipient_countries'],
    help="Select one or more recipient countries"
)

# Update filters in session state
st.session_state.filters.update({
    'start_date': start_date,
    'end_date': end_date,
    'initiating_country': initiating_country,
    'recipient_countries': recipient_countries
})

# Show active filters
if any([initiating_country, recipient_countries, start_date != date(2024, 8, 1) or end_date != date.today()]):
    st.sidebar.markdown("**Active Filters:**")
    if start_date or end_date:
        st.sidebar.info(f"📅 {start_date} to {end_date}")
    if initiating_country:
        st.sidebar.info(f"🌍 Initiating: {initiating_country}")
    if recipient_countries:
        recipients_str = ", ".join(recipient_countries)
        st.sidebar.info(f"🎯 Recipients: {recipients_str}")

st.sidebar.markdown("---")

# Example questions
st.sidebar.header("💡 Example Questions")
st.sidebar.markdown("""
**Event Queries:**
- What recent events involve China and Africa?
- What happened in Iran's diplomatic activities last month?
- Show me economic cooperation events from October 2025

**Trend Analysis:**
- What are the trending soft power events this month?
- How has China's engagement with Latin America evolved?
- Compare Russia and China's soft power activities

**Bilateral Relations:**
- What is the relationship between China and Egypt?
- How strong is Iran's relationship with Venezuela?

**Category Specific:**
- What cultural events has Turkey organized recently?
- Show me military cooperation activities
- Analyze economic development projects
""")

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Clear Conversation"):
    st.session_state.agent.clear_history()
    st.session_state.messages = []
    st.rerun()

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        # Show sources if available
        if message["role"] == "assistant" and message.get("sources"):
            with st.expander("📚 Sources"):
                for idx, source in enumerate(message["sources"][:5], 1):
                    if 'event_name' in source:
                        # Event source
                        st.markdown(f"""
**{idx}. {source['event_name']}**
- Country: {source.get('country', 'N/A')}
- Period: {source.get('period_start', 'N/A')} to {source.get('period_end', 'N/A')}
- Relevance Score: {source.get('relevance_score', 0):.3f}
""")
                    elif 'title' in source:
                        # Document source
                        st.markdown(f"""
**{idx}. {source['title']}**
- Source: {source.get('source', 'N/A')}
- Date: {source.get('date', 'N/A')}
- Relevance Score: {source.get('relevance_score', 0):.3f}
""")

# Build filter context string
def build_filter_context():
    """Build a context string from active filters to pass to the agent."""
    filters = st.session_state.filters
    context_parts = []

    if filters['start_date'] or filters['end_date']:
        context_parts.append(f"Date range: {filters['start_date']} to {filters['end_date']}")

    if filters['initiating_country']:
        context_parts.append(f"Initiating country: {filters['initiating_country']}")

    if filters['recipient_countries']:
        recipients = ", ".join(filters['recipient_countries'])
        context_parts.append(f"Recipient countries: {recipients}")

    if context_parts:
        return "ACTIVE FILTERS: " + "; ".join(context_parts)
    return ""

# Chat input
if prompt := st.chat_input("Ask a question about soft power data..."):
    # Build enhanced prompt with filter context
    filter_context = build_filter_context()
    enhanced_prompt = f"{filter_context}\n\n{prompt}" if filter_context else prompt

    # Add user message (show original, not enhanced)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)
        if filter_context:
            st.caption(f"🔍 {filter_context}")

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response_text, sources = st.session_state.agent.query(
                    enhanced_prompt,
                    conversation_context=st.session_state.messages
                )

                st.markdown(response_text)

                # Show sources
                if sources:
                    with st.expander("📚 Sources"):
                        for idx, source in enumerate(sources[:5], 1):
                            if 'event_name' in source:
                                # Event source
                                st.markdown(f"""
**{idx}. {source['event_name']}**
- Country: {source.get('country', 'N/A')}
- Period: {source.get('period_start', 'N/A')} to {source.get('period_end', 'N/A')}
- Relevance Score: {source.get('relevance_score', 0):.3f}
""")
                            elif 'title' in source:
                                # Document source
                                st.markdown(f"""
**{idx}. {source['title']}**
- Source: {source.get('source', 'N/A')}
- Date: {source.get('date', 'N/A')}
- Relevance Score: {source.get('relevance_score', 0):.3f}
""")

                # Add assistant message to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "sources": sources
                })

            except Exception as e:
                error_message = f"I encountered an error processing your question: {str(e)}"
                st.error(error_message)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_message,
                    "sources": []
                })

# Footer
st.markdown("---")
st.caption("""
💡 **How it works:** Your questions are processed by an AI agent that uses semantic search to find relevant
events and documents, then synthesizes the information into clear, accurate answers. All responses are grounded
in the actual data.
""")
