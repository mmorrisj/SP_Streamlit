import React, { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Download, Filter, Loader2, ExternalLink, X, ChevronDown, ChevronUp, FileBarChart, Plus, Check, FolderOpen } from 'lucide-react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import ChatReportModal from '../components/ChatReportModal'
import ProjectDrawer from '../components/ProjectDrawer'
import { addProjectDocument, fetchProject } from '../api/client'
import type { AddProjectDocumentRequest } from '../api/client'
import './Pages.css'
import './ChatPage.css'

interface ChatSource {
  citation_number: number
  doc_id: string | null
  content: string
  title: string | null
  source_name: string | null
  date: string | null
  initiating_country: string | null
  recipient_country: string | null
  category: string | null
  salience: number | null
  relevance_score: number
}

interface SearchMetadata {
  applied_filters: Record<string, string>
  inferred_filters: {
    influencers?: string[]
    recipients?: string[]
    categories?: string[]
    temporal_context?: string
    start_date?: string
    end_date?: string
  }
  inference_notes: string[]
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: ChatSource[]
  isStreaming?: boolean
  searchMetadata?: SearchMetadata
}

interface ChatFilters {
  influencers: string[]
  recipients: string[]
  categories: string[]
}

export default function ChatPage() {
  const queryClient = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [expandedSources, setExpandedSources] = useState<number | null>(null)

  // Research project state
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeProjectId, setActiveProjectId] = useState<string | null>(
    () => localStorage.getItem('activeProjectId')
  )
  const [projectMode, setProjectMode] = useState(false)
  const [collectedDocIds, setCollectedDocIds] = useState<Set<string>>(new Set())

  // Track active project's doc IDs for the + button state
  const { data: activeProjectData } = useQuery({
    queryKey: ['project', activeProjectId],
    queryFn: () => fetchProject(activeProjectId!),
    enabled: !!activeProjectId,
  })

  useEffect(() => {
    if (activeProjectData?.documents) {
      setCollectedDocIds(new Set(activeProjectData.documents.map(d => d.doc_id)))
    } else {
      setCollectedDocIds(new Set())
    }
  }, [activeProjectData])

  const handleSelectProject = (id: string | null) => {
    setActiveProjectId(id)
    if (id) {
      localStorage.setItem('activeProjectId', id)
    } else {
      localStorage.removeItem('activeProjectId')
      setProjectMode(false)
    }
  }

  const handleCollectSource = async (src: ChatSource, queryText: string) => {
    if (!activeProjectId || !src.doc_id) return
    const body: AddProjectDocumentRequest = {
      doc_id: src.doc_id,
      title: src.title,
      source_name: src.source_name,
      date: src.date,
      initiating_country: src.initiating_country,
      recipient_country: src.recipient_country,
      category: src.category,
      excerpt: src.content?.slice(0, 500),
      source_query: queryText,
    }
    await addProjectDocument(activeProjectId, body)
    setCollectedDocIds(prev => new Set(prev).add(src.doc_id!))
    queryClient.invalidateQueries({ queryKey: ['project', activeProjectId] })
    queryClient.invalidateQueries({ queryKey: ['projects'] })
    toast.success('Source added to project')
  }

  // Report modal state
  const [reportModalOpen, setReportModalOpen] = useState(false)
  const [reportModalContext, setReportModalContext] = useState<{
    query: string
    filters: {
      influencer?: string
      recipient?: string
      category?: string
      start_date?: string
      end_date?: string
    }
  }>({ query: '', filters: {} })

  // Filter state
  const [selectedInfluencer, setSelectedInfluencer] = useState<string>('')
  const [selectedRecipient, setSelectedRecipient] = useState<string>('')
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const sourceRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  // Fetch available filters
  const { data: filters } = useQuery<ChatFilters>({
    queryKey: ['chat-filters'],
    queryFn: async () => {
      const response = await fetch('/api/chat/filters')
      return response.json()
    }
  })

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inputValue.trim() || isLoading) return

    const userMessage = inputValue.trim()
    setInputValue('')

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])

    // Add placeholder for assistant response
    setMessages(prev => [...prev, { role: 'assistant', content: '', isStreaming: true }])

    setIsLoading(true)

    // Create abort controller for this request
    abortControllerRef.current = new AbortController()

    try {
      const chatUrl = projectMode && activeProjectId
        ? `/api/projects/${activeProjectId}/chat/stream`
        : '/api/chat/stream'

      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const token = localStorage.getItem('token')
      if (token) headers['Authorization'] = `Bearer ${token}`

      const response = await fetch(chatUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: userMessage,
          influencer: selectedInfluencer || undefined,
          recipient: selectedRecipient || undefined,
          category: selectedCategory || undefined,
          start_date: startDate || undefined,
          end_date: endDate || undefined
        }),
        signal: abortControllerRef.current.signal
      })

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No readable stream')

      const decoder = new TextDecoder()
      let buffer = ''
      let sources: ChatSource[] = []
      let fullContent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete SSE messages
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.trim()) continue

          for (const line of part.split('\n')) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))

                if (data.type === 'metadata') {
                  // Update message with search metadata (inferred filters)
                  setMessages(prev => {
                    const updated = [...prev]
                    const lastIdx = updated.length - 1
                    if (updated[lastIdx]?.role === 'assistant') {
                      updated[lastIdx] = {
                        ...updated[lastIdx],
                        searchMetadata: {
                          applied_filters: data.applied_filters,
                          inferred_filters: data.inferred_filters,
                          inference_notes: data.inference_notes
                        }
                      }
                    }
                    return updated
                  })
                } else if (data.type === 'sources') {
                  sources = data.sources
                  // Update message with sources
                  setMessages(prev => {
                    const updated = [...prev]
                    const lastIdx = updated.length - 1
                    if (updated[lastIdx]?.role === 'assistant') {
                      updated[lastIdx] = {
                        ...updated[lastIdx],
                        sources
                      }
                    }
                    return updated
                  })
                } else if (data.type === 'content') {
                  fullContent += data.content
                  // Update streaming content
                  setMessages(prev => {
                    const updated = [...prev]
                    const lastIdx = updated.length - 1
                    if (updated[lastIdx]?.role === 'assistant') {
                      updated[lastIdx] = {
                        ...updated[lastIdx],
                        content: fullContent
                      }
                    }
                    return updated
                  })
                } else if (data.type === 'done') {
                  // Mark streaming as complete
                  setMessages(prev => {
                    const updated = [...prev]
                    const lastIdx = updated.length - 1
                    if (updated[lastIdx]?.role === 'assistant') {
                      updated[lastIdx] = {
                        ...updated[lastIdx],
                        isStreaming: false
                      }
                    }
                    return updated
                  })
                }
              } catch {
                // Skip malformed JSON
              }
            }
          }
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        // Request was cancelled
        setMessages(prev => {
          const updated = [...prev]
          const lastIdx = updated.length - 1
          if (updated[lastIdx]?.role === 'assistant') {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: updated[lastIdx].content + '\n\n[Response cancelled]',
              isStreaming: false
            }
          }
          return updated
        })
      } else {
        console.error('Chat error:', error)
        setMessages(prev => {
          const updated = [...prev]
          const lastIdx = updated.length - 1
          if (updated[lastIdx]?.role === 'assistant') {
            updated[lastIdx] = {
              role: 'assistant',
              content: `Error: ${(error as Error).message}`,
              isStreaming: false
            }
          }
          return updated
        })
      }
    } finally {
      setIsLoading(false)
      abortControllerRef.current = null
    }
  }

  const handleExport = async (format: 'markdown' | 'json' | 'txt') => {
    try {
      const response = await fetch('/api/chat/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages, format })
      })

      if (!response.ok) throw new Error('Export failed')

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const ext = format === 'markdown' ? 'md' : format
      a.download = `chat_export_${new Date().toISOString().slice(0, 10)}.${ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Export error:', error)
    }
  }

  const clearChat = () => {
    setMessages([])
    setExpandedSources(null)
  }

  const toggleSources = (messageIdx: number) => {
    setExpandedSources(prev => prev === messageIdx ? null : messageIdx)
  }

  // Open report modal with context from a specific message
  const openReportModal = (messageIdx: number) => {
    const message = messages[messageIdx]
    // Find the user message that triggered this response (previous message)
    const userMessage = messages[messageIdx - 1]
    const query = userMessage?.content || ''

    // Extract filters from searchMetadata
    const appliedFilters = message?.searchMetadata?.applied_filters || {}
    const inferredFilters = message?.searchMetadata?.inferred_filters || {}

    setReportModalContext({
      query,
      filters: {
        influencer: appliedFilters.influencer || inferredFilters.influencers?.[0],
        recipient: appliedFilters.recipient || inferredFilters.recipients?.[0],
        category: appliedFilters.category || inferredFilters.categories?.[0],
        start_date: appliedFilters.start_date || inferredFilters.start_date,
        end_date: appliedFilters.end_date || inferredFilters.end_date,
      }
    })
    setReportModalOpen(true)
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'No date'
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  const activeFiltersCount = [
    selectedInfluencer,
    selectedRecipient,
    selectedCategory,
    startDate,
    endDate
  ].filter(Boolean).length

  // Handle citation click - expand sources and scroll to the cited source
  const handleCitationClick = useCallback((messageIdx: number, citationNum: number) => {
    // Expand sources panel for this message
    setExpandedSources(messageIdx)

    // Scroll to the source after a brief delay for the panel to expand
    setTimeout(() => {
      const sourceKey = `${messageIdx}-${citationNum}`
      const sourceEl = sourceRefs.current.get(sourceKey)
      if (sourceEl) {
        sourceEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
        // Add highlight effect
        sourceEl.classList.add('source-highlight')
        setTimeout(() => sourceEl.classList.remove('source-highlight'), 2000)
      }
    }, 100)
  }, [])

  // Create custom ReactMarkdown components that convert [1], [2] etc to clickable links
  const createMarkdownComponents = useCallback((messageIdx: number, sources: ChatSource[] | undefined): Components => {
    // Get valid citation numbers from sources
    const validCitations = new Set(sources?.map(s => s.citation_number) || [])

    return {
      // Process text nodes to find and replace citation patterns
      p: ({ children, ...props }) => {
        const processedChildren = processCitations(children, messageIdx, validCitations)
        return <p {...props}>{processedChildren}</p>
      },
      li: ({ children, ...props }) => {
        const processedChildren = processCitations(children, messageIdx, validCitations)
        return <li {...props}>{processedChildren}</li>
      },
      td: ({ children, ...props }) => {
        const processedChildren = processCitations(children, messageIdx, validCitations)
        return <td {...props}>{processedChildren}</td>
      }
    }
  }, [])

  // Process children to replace citation patterns with clickable links
  const processCitations = (children: React.ReactNode, messageIdx: number, validCitations: Set<number>): React.ReactNode => {
    if (!children) return children

    return React.Children.map(children, (child) => {
      if (typeof child === 'string') {
        // Match patterns like [1], [2], [1, 2], [1][2]
        const parts: React.ReactNode[] = []
        let lastIndex = 0
        const regex = /\[(\d+(?:\s*,\s*\d+)*)\]/g
        let match

        while ((match = regex.exec(child)) !== null) {
          // Add text before the match
          if (match.index > lastIndex) {
            parts.push(child.slice(lastIndex, match.index))
          }

          // Parse citation numbers (handles [1], [1, 2], etc)
          const citationNums = match[1].split(',').map(n => parseInt(n.trim(), 10))

          // Create clickable links for each citation
          citationNums.forEach((num, i) => {
            if (validCitations.has(num)) {
              parts.push(
                <button
                  key={`${match!.index}-${num}`}
                  className="citation-link"
                  onClick={(e) => {
                    e.preventDefault()
                    handleCitationClick(messageIdx, num)
                  }}
                  title={`View source ${num}`}
                >
                  [{num}]
                </button>
              )
            } else {
              parts.push(`[${num}]`)
            }
            // Add comma between multiple citations in same bracket
            if (i < citationNums.length - 1) {
              parts.push(' ')
            }
          })

          lastIndex = match.index + match[0].length
        }

        // Add remaining text
        if (lastIndex < child.length) {
          parts.push(child.slice(lastIndex))
        }

        return parts.length > 0 ? parts : child
      }

      // If it's a React element with children, process recursively
      if (React.isValidElement(child)) {
        const elementProps = child.props as { children?: React.ReactNode }
        if (elementProps.children) {
          return React.cloneElement(child, {
            ...elementProps,
            children: processCitations(elementProps.children, messageIdx, validCitations)
          } as React.Attributes)
        }
      }

      return child
    })
  }

  return (
    <div className="page chat-page">
      <div className="page-header">
        <div className="chat-header-row">
          <div>
            <h1>Research Assistant</h1>
            <p>Ask questions about soft power activities, bilateral relationships, and events</p>
          </div>
          <div className="chat-header-actions">
            <button
              className={`filter-toggle ${drawerOpen ? 'active' : ''}`}
              onClick={() => setDrawerOpen(!drawerOpen)}
            >
              <FolderOpen size={18} />
              Projects
              {activeProjectData?.document_count ? (
                <span className="filter-badge">{activeProjectData.document_count}</span>
              ) : null}
            </button>
            <button
              className={`filter-toggle ${showFilters ? 'active' : ''}`}
              onClick={() => setShowFilters(!showFilters)}
            >
              <Filter size={18} />
              Filters
              {activeFiltersCount > 0 && (
                <span className="filter-badge">{activeFiltersCount}</span>
              )}
            </button>
            {messages.length > 0 && (
              <>
                <div className="export-dropdown">
                  <button className="export-btn">
                    <Download size={18} />
                    Export
                  </button>
                  <div className="export-menu">
                    <button onClick={() => handleExport('markdown')}>Markdown</button>
                    <button onClick={() => handleExport('json')}>JSON</button>
                    <button onClick={() => handleExport('txt')}>Plain Text</button>
                  </div>
                </div>
                <button className="clear-btn" onClick={clearChat}>
                  <X size={18} />
                  Clear
                </button>
              </>
            )}
          </div>
        </div>

        {/* Filter Panel */}
        {showFilters && (
          <div className="filter-panel">
            <div className="filter-row">
              <div className="filter-group">
                <label>Influencer Country</label>
                <select
                  value={selectedInfluencer}
                  onChange={e => setSelectedInfluencer(e.target.value)}
                >
                  <option value="">All Influencers</option>
                  {filters?.influencers.map(inf => (
                    <option key={inf} value={inf}>{inf}</option>
                  ))}
                </select>
              </div>

              <div className="filter-group">
                <label>Recipient Country</label>
                <select
                  value={selectedRecipient}
                  onChange={e => setSelectedRecipient(e.target.value)}
                >
                  <option value="">All Recipients</option>
                  {filters?.recipients.map(rec => (
                    <option key={rec} value={rec}>{rec}</option>
                  ))}
                </select>
              </div>

              <div className="filter-group">
                <label>Category</label>
                <select
                  value={selectedCategory}
                  onChange={e => setSelectedCategory(e.target.value)}
                >
                  <option value="">All Categories</option>
                  {filters?.categories.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>

              <div className="filter-group">
                <label>Start Date</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={e => setStartDate(e.target.value)}
                />
              </div>

              <div className="filter-group">
                <label>End Date</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={e => setEndDate(e.target.value)}
                />
              </div>
            </div>

            {activeFiltersCount > 0 && (
              <button
                className="clear-filters-btn"
                onClick={() => {
                  setSelectedInfluencer('')
                  setSelectedRecipient('')
                  setSelectedCategory('')
                  setStartDate('')
                  setEndDate('')
                }}
              >
                Clear all filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Project mode indicator */}
      {projectMode && activeProjectData && (
        <div className="project-mode-banner">
          <FolderOpen size={14} />
          <span>Project mode: searching only within <strong>{activeProjectData.name}</strong> ({activeProjectData.document_count} docs)</span>
          <button onClick={() => setProjectMode(false)} className="exit-project-mode">Exit</button>
        </div>
      )}

      {/* Chat + Drawer layout */}
      <div className="chat-with-drawer">

      {/* Messages Container */}
      <div className="chat-container">
        <div className="messages-container">
          {messages.length === 0 ? (
            <div className="empty-chat">
              <div className="empty-icon">?</div>
              <h3>Start a Conversation</h3>
              <p>Ask about soft power activities, events, bilateral relationships, or search for specific topics in the document database.</p>
              <div className="example-queries">
                <p>Try asking:</p>
                <button onClick={() => setInputValue("What are China's major infrastructure projects in Africa?")}>
                  What are China's major infrastructure projects in Africa?
                </button>
                <button onClick={() => setInputValue("How has Russia's influence in the Middle East changed recently?")}>
                  How has Russia's influence in the Middle East changed recently?
                </button>
                <button onClick={() => setInputValue("What educational partnerships exist between Turkey and Central Asia?")}>
                  What educational partnerships exist between Turkey and Central Asia?
                </button>
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={idx} className={`message ${msg.role}`}>
                <div className="message-header">
                  <span className="message-role">
                    {msg.role === 'user' ? 'You' : 'Research Assistant'}
                  </span>
                </div>

                {/* Show inferred filters for assistant messages */}
                {msg.role === 'assistant' && msg.searchMetadata && Object.keys(msg.searchMetadata.applied_filters).length > 0 && (
                  <div className="inferred-filters-banner">
                    <span className="inferred-label">Search focused on:</span>
                    {msg.searchMetadata.applied_filters.influencer && (
                      <span className="inferred-tag influencer">{msg.searchMetadata.applied_filters.influencer}</span>
                    )}
                    {msg.searchMetadata.applied_filters.recipient && (
                      <span className="inferred-tag recipient">{msg.searchMetadata.applied_filters.recipient}</span>
                    )}
                    {msg.searchMetadata.applied_filters.category && (
                      <span className="inferred-tag category">{msg.searchMetadata.applied_filters.category}</span>
                    )}
                    {(msg.searchMetadata.applied_filters.start_date || msg.searchMetadata.applied_filters.end_date) && (
                      <span className="inferred-tag date">
                        {msg.searchMetadata.applied_filters.start_date && msg.searchMetadata.applied_filters.end_date
                          ? `${msg.searchMetadata.applied_filters.start_date} to ${msg.searchMetadata.applied_filters.end_date}`
                          : msg.searchMetadata.applied_filters.start_date
                            ? `From ${msg.searchMetadata.applied_filters.start_date}`
                            : `Until ${msg.searchMetadata.applied_filters.end_date}`
                        }
                      </span>
                    )}
                  </div>
                )}

                <div className="message-content">
                  {msg.role === 'assistant' ? (
                    <>
                      {msg.content ? (
                        <ReactMarkdown components={createMarkdownComponents(idx, msg.sources)}>
                          {msg.content}
                        </ReactMarkdown>
                      ) : (
                        msg.isStreaming && <span className="typing-indicator">...</span>
                      )}
                      {msg.isStreaming && <Loader2 className="streaming-indicator" size={16} />}
                    </>
                  ) : (
                    msg.content
                  )}
                </div>

                {/* Sources Panel */}
                {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && !msg.isStreaming && (
                  <div className="sources-section">
                    <button
                      className="sources-toggle"
                      onClick={() => toggleSources(idx)}
                    >
                      {expandedSources === idx ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      {msg.sources.length} Sources
                    </button>

                    {expandedSources === idx && (
                      <div className="sources-list">
                        {msg.sources.map((src, srcIdx) => (
                          <div
                            key={srcIdx}
                            className="source-card"
                            ref={(el) => {
                              if (el) {
                                sourceRefs.current.set(`${idx}-${src.citation_number}`, el)
                              }
                            }}
                          >
                            <div className="source-header">
                              <span className="source-number">[{src.citation_number}]</span>
                              <span className="source-title">{src.title || 'Untitled'}</span>
                              <span className="source-score">
                                {(src.relevance_score * 100).toFixed(0)}% match
                              </span>
                            </div>
                            <div className="source-meta">
                              {src.source_name && <span>{src.source_name}</span>}
                              {src.date && <span>{formatDate(src.date)}</span>}
                              {src.initiating_country && src.recipient_country && (
                                <span>{src.initiating_country} → {src.recipient_country}</span>
                              )}
                              {src.category && <span className="source-category">{src.category}</span>}
                            </div>
                            {src.content && (
                              <p className="source-excerpt">
                                {src.content.length > 300 ? src.content.slice(0, 300) + '...' : src.content}
                              </p>
                            )}
                            <div className="source-actions">
                              {src.doc_id && (
                                <a
                                  href={`/documents?doc_id=${src.doc_id}`}
                                  className="source-link"
                                >
                                  <ExternalLink size={14} />
                                  View Document
                                </a>
                              )}
                              {src.doc_id && activeProjectId && (
                                <button
                                  className={`collect-btn ${collectedDocIds.has(src.doc_id) ? 'collected' : ''}`}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    if (!collectedDocIds.has(src.doc_id!)) {
                                      const userQuery = idx > 0 ? messages[idx - 1]?.content : ''
                                      handleCollectSource(src, userQuery)
                                    }
                                  }}
                                  title={collectedDocIds.has(src.doc_id) ? 'Already in project' : 'Add to project'}
                                  disabled={collectedDocIds.has(src.doc_id)}
                                >
                                  {collectedDocIds.has(src.doc_id) ? <Check size={14} /> : <Plus size={14} />}
                                  {collectedDocIds.has(src.doc_id) ? 'Collected' : 'Collect'}
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Generate Report Button */}
                {msg.role === 'assistant' && !msg.isStreaming && msg.content && (
                  <div className="message-actions">
                    <button
                      className="generate-report-btn"
                      onClick={() => openReportModal(idx)}
                      title="Generate a comprehensive report based on this topic"
                    >
                      <FileBarChart size={16} />
                      Generate Full Report
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Form */}
        <form className="chat-input-form" onSubmit={handleSubmit}>
          <input
            type="text"
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            placeholder="Ask a question about soft power activities..."
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !inputValue.trim()}>
            {isLoading ? <Loader2 className="spin" size={20} /> : <Send size={20} />}
          </button>
        </form>
      </div>

      {/* Project Drawer */}
      <ProjectDrawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        activeProjectId={activeProjectId}
        onSelectProject={handleSelectProject}
        projectMode={projectMode}
        onToggleProjectMode={() => setProjectMode(!projectMode)}
        onGenerateReport={() => {
          // Open report modal with project context
          setReportModalContext({
            query: `Generate report from project "${activeProjectData?.name}"`,
            filters: {},
          })
          setReportModalOpen(true)
        }}
      />

      </div>{/* end chat-with-drawer */}

      {/* Report Modal */}
      <ChatReportModal
        isOpen={reportModalOpen}
        onClose={() => setReportModalOpen(false)}
        inferredFilters={reportModalContext.filters}
        query={reportModalContext.query}
      />
    </div>
  )
}
