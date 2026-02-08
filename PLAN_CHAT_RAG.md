# Chat/RAG Feature Implementation Plan

## Overview
Build a chatbot interface that allows users to query and research the underlying soft power data using Retrieval Augmented Generation (RAG).

---

## Existing Infrastructure (What We Have)

### Embeddings
- **470k+ document embeddings** stored in pgvector
- **Collection**: `chunk_embeddings` (document chunks)
- **Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional)
- **Access**: `services/pipeline/embeddings/embedding_vectorstore.py`

### LLM Integration
- **Provider**: Azure OpenAI (with fallback to direct OpenAI)
- **Default Model**: `gpt-4o-mini`
- **Function**: `gai()` in `shared/utils/utils.py`
- **Config**: `shared/config/config.yaml`

### Database
- PostgreSQL with pgvector extension
- Full document corpus with metadata (country, category, date, salience)
- Event summaries with source traceability

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    ChatPage.tsx                           │   │
│  │  - Message list (user/assistant)                         │   │
│  │  - Input box with send button                            │   │
│  │  - Source citations panel                                │   │
│  │  - Filter controls (country, date range)                 │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  POST /api/chat                                           │   │
│  │  - Receives: message, conversation_id, filters           │   │
│  │  - Returns: response, sources, conversation_id           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              RAG Pipeline (services/chat/)                │   │
│  │                                                           │   │
│  │  1. Query Embedding                                       │   │
│  │     - Embed user query using same model                   │   │
│  │                                                           │   │
│  │  2. Vector Search                                         │   │
│  │     - Similarity search in pgvector                       │   │
│  │     - Apply metadata filters (country, date)              │   │
│  │     - Return top-k relevant chunks                        │   │
│  │                                                           │   │
│  │  3. Context Assembly                                      │   │
│  │     - Fetch full document context                         │   │
│  │     - Include conversation history                        │   │
│  │     - Build prompt with retrieved documents               │   │
│  │                                                           │   │
│  │  4. LLM Generation                                        │   │
│  │     - Call gai() with context + query                     │   │
│  │     - Generate response with citations                    │   │
│  │                                                           │   │
│  │  5. Response Formatting                                   │   │
│  │     - Parse citations from response                       │   │
│  │     - Link to source documents                            │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Data Layer                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐   │
│  │    pgvector     │  │    Documents    │  │ Conversations  │   │
│  │  (embeddings)   │  │   (metadata)    │  │   (history)    │   │
│  └─────────────────┘  └─────────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Steps

### Phase 1: Backend RAG Service

#### 1.1 Create Chat Service Module
**File**: `services/chat/rag_service.py`

```python
class RAGService:
    def __init__(self):
        self.vectorstore = get_chunk_vectorstore()
        self.embeddings = get_embeddings_model()

    async def search(self, query: str, filters: dict, k: int = 10):
        """Semantic search with metadata filtering"""

    async def generate_response(self, query: str, context: list, history: list):
        """Generate LLM response with retrieved context"""

    def format_citations(self, response: str, sources: list):
        """Parse and format source citations"""
```

#### 1.2 Create Chat API Endpoint
**File**: `server/main.py` (add endpoints)

```python
@app.post("/api/chat")
async def chat(request: ChatRequest):
    # 1. Retrieve relevant documents
    # 2. Build context with conversation history
    # 3. Generate response
    # 4. Return with sources

@app.get("/api/chat/history/{conversation_id}")
async def get_chat_history(conversation_id: str):
    # Return conversation history

@app.delete("/api/chat/history/{conversation_id}")
async def clear_chat_history(conversation_id: str):
    # Clear conversation
```

#### 1.3 Conversation Storage
**Option A**: In-memory (simple, loses on restart)
**Option B**: Database table (persistent)
**Option C**: Redis (fast, can expire)

**Recommendation**: Start with in-memory for MVP, add database later.

---

### Phase 2: Frontend Chat Interface

#### 2.1 Create Chat Page
**File**: `client/src/pages/ChatPage.tsx`

Components:
- `ChatMessages` - Scrollable message list
- `ChatInput` - Text input with send button
- `SourcePanel` - Expandable citations panel
- `FilterBar` - Country/date filters

#### 2.2 Add to Navigation
**File**: `client/src/components/Layout.tsx`

```typescript
{ path: '/chat', label: 'Research', icon: MessageSquare }
```

#### 2.3 Add Route
**File**: `client/src/App.tsx`

```typescript
<Route path="/chat" element={<ChatPage />} />
```

#### 2.4 API Client
**File**: `client/src/api/client.ts`

```typescript
export const sendChatMessage = async (message: string, conversationId?: string, filters?: ChatFilters) => {
    const response = await api.post('/chat', { message, conversation_id: conversationId, filters })
    return response.data
}
```

---

### Phase 3: RAG Prompt Engineering

#### 3.1 System Prompt
```
You are a research assistant specializing in soft power analysis and international relations.
You have access to a database of diplomatic documents, news articles, and analysis.

When answering questions:
1. Base your answers on the provided document context
2. Cite sources using [1], [2], etc. format
3. Be specific about countries, dates, and events
4. If information is not in the context, say so clearly
5. Provide balanced analysis when discussing geopolitical topics

Context Documents:
{retrieved_documents}

Conversation History:
{conversation_history}
```

#### 3.2 Query Enhancement
- Expand acronyms (BRI → Belt and Road Initiative)
- Add temporal context if missing
- Handle follow-up questions using conversation history

---

### Phase 4: Advanced Features (Future)

#### 4.1 Streaming Responses
- Use Server-Sent Events (SSE) for real-time response streaming
- Better UX for longer responses

#### 4.2 Multi-Modal Search
- Search across documents, events, and summaries
- Aggregate results from multiple collections

#### 4.3 Export & Share
- Export conversation as markdown/PDF
- Share research sessions

#### 4.4 Suggested Queries
- Show related questions
- Auto-complete based on corpus

---

## File Structure

```
services/
└── chat/
    ├── __init__.py
    ├── rag_service.py      # Core RAG logic
    ├── prompts.py          # System prompts
    └── conversation.py     # Conversation management

client/src/
├── pages/
│   └── ChatPage.tsx        # Main chat interface
├── components/
│   ├── ChatMessages.tsx    # Message display
│   ├── ChatInput.tsx       # Input component
│   └── SourcePanel.tsx     # Citations panel
└── api/
    └── client.ts           # Add chat endpoints
```

---

## API Contracts

### POST /api/chat

**Request:**
```json
{
  "message": "What infrastructure projects has China funded in Egypt?",
  "conversation_id": "uuid-optional",
  "filters": {
    "influencer": "China",
    "recipient": "Egypt",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01"
  }
}
```

**Response:**
```json
{
  "response": "China has funded several major infrastructure projects in Egypt, including...[1][2]",
  "conversation_id": "uuid",
  "sources": [
    {
      "citation_number": 1,
      "doc_id": "abc123",
      "title": "China-Egypt Infrastructure Agreement",
      "source_name": "Reuters",
      "date": "2024-03-15",
      "excerpt": "...",
      "relevance_score": 0.89
    }
  ],
  "metadata": {
    "documents_searched": 1000,
    "retrieval_time_ms": 150,
    "generation_time_ms": 2000
  }
}
```

---

## Dependencies

**Backend (already installed):**
- `langchain` - RAG orchestration
- `sentence-transformers` - Embeddings
- `pgvector` - Vector similarity search
- `openai` - LLM API

**Frontend (already installed):**
- `react` - UI framework
- `@tanstack/react-query` - Data fetching
- `lucide-react` - Icons

---

## Implementation Order

1. **Backend RAG Service** (2-3 hours)
   - Create `services/chat/rag_service.py`
   - Implement vector search with filters
   - Add LLM generation with context

2. **Chat API Endpoint** (1 hour)
   - Add `/api/chat` endpoint
   - Wire up RAG service
   - Handle conversation state

3. **Frontend Chat Page** (2-3 hours)
   - Create `ChatPage.tsx`
   - Build message display
   - Add input and send functionality
   - Display source citations

4. **Integration & Testing** (1-2 hours)
   - Connect frontend to backend
   - Test retrieval quality
   - Tune prompts

**Total Estimated Time**: 6-9 hours

---

## Questions to Clarify

1. **Conversation Persistence**: Should conversations persist across sessions?
2. **Authentication**: Is user-specific chat history needed?
3. **Filters**: Which filters should be available (country, date, category)?
4. **Export**: Should users be able to export chat transcripts?
5. **Rate Limiting**: Any limits on queries per user/session?
