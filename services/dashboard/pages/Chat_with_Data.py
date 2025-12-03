"""
Chat with Soft Power Data

An interactive conversational interface powered by RAG and LLM agents.
Ask questions about events, trends, relationships, and soft power activities.
"""

import streamlit as st
from datetime import datetime
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.agent.soft_power_agent import create_agent


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

# Sidebar with example questions and settings
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

# Chat input
if prompt := st.chat_input("Ask a question about soft power data..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response_text, sources = st.session_state.agent.query(
                    prompt,
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
