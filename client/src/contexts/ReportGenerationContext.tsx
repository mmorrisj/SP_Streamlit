import { createContext, useContext, useState, useRef, useCallback, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { generateReportStream } from '../api/client'
import type { ReportData, ReportRequest } from '../api/client'

type ReportGenerationStatus = 'idle' | 'generating' | 'complete' | 'error' | 'cancelled'

interface ReportGenerationContextType {
  // State
  status: ReportGenerationStatus
  report: ReportData | null
  request: ReportRequest | null
  error: string | null
  streamPhase: string
  narrativesDone: number
  narrativesTotal: number
  progressPct: number

  // Actions
  startGeneration: (request: ReportRequest) => void
  cancelGeneration: () => void
  clearReport: () => void
  dismissError: () => void
}

const ReportGenerationContext = createContext<ReportGenerationContextType | undefined>(undefined)

export function ReportGenerationProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()

  const [status, setStatus] = useState<ReportGenerationStatus>('idle')
  const [report, setReport] = useState<ReportData | null>(null)
  const [request, setRequest] = useState<ReportRequest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [streamPhase, setStreamPhase] = useState('')
  const [narrativesDone, setNarrativesDone] = useState(0)
  const [narrativesTotal, setNarrativesTotal] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  // Mirror status in a ref so the startGeneration callback can check it without stale closures
  const statusRef = useRef<ReportGenerationStatus>('idle')
  statusRef.current = status

  const progressPct = narrativesTotal > 0 ? Math.round((narrativesDone / narrativesTotal) * 100) : 0

  const startGeneration = useCallback((req: ReportRequest) => {
    if (statusRef.current === 'generating') return

    setStatus('generating')
    setReport(null)
    setRequest(req)
    setError(null)
    setStreamPhase('Loading data...')
    setNarrativesDone(0)
    setNarrativesTotal(0)

    const controller = new AbortController()
    abortRef.current = controller

    generateReportStream(req, {
      onSkeleton: (skeleton) => {
        setReport(skeleton)
        const totalEvents = skeleton.categories.reduce((s, c) => s + c.events.length, 0)
        const totalCats = skeleton.categories.length
        setNarrativesTotal(totalEvents + totalCats + 2)
        setStreamPhase('Generating narratives...')
      },

      onEventNarrative: ({ category, event_index, overview, outcomes }) => {
        setReport(prev => {
          if (!prev) return prev
          return {
            ...prev,
            categories: prev.categories.map(cat => {
              if (cat.category !== category) return cat
              return {
                ...cat,
                events: cat.events.map((evt, idx) =>
                  idx === event_index ? { ...evt, overview, outcomes } : evt
                ),
              }
            }),
          }
        })
        setNarrativesDone(n => n + 1)
      },

      onCategoryNarrative: ({ category, narrative }) => {
        setReport(prev => {
          if (!prev) return prev
          return {
            ...prev,
            categories: prev.categories.map(cat =>
              cat.category === category ? { ...cat, narrative } : cat
            ),
          }
        })
        setNarrativesDone(n => n + 1)
      },

      onOverallSynthesis: ({ overall_summary }) => {
        setReport(prev => prev ? { ...prev, overall_summary } : prev)
        setNarrativesDone(n => n + 1)
        setStreamPhase('Finishing up...')
      },

      onEntitySummary: ({ entity_type_index, entity_index, summary }) => {
        setReport(prev => {
          if (!prev) return prev
          return {
            ...prev,
            entities: prev.entities.map((group, gi) => {
              if (gi !== entity_type_index) return group
              return {
                ...group,
                entities: group.entities.map((ent, ei) =>
                  ei === entity_index ? { ...ent, summary } : ent
                ),
              }
            }),
          }
        })
      },

      onTitle: ({ title }) => {
        setReport(prev => prev ? { ...prev, title } : prev)
        setNarrativesDone(n => n + 1)
      },

      onComplete: () => {
        setStatus('complete')
        setStreamPhase('')
        toast.success('Report generation complete!', {
          description: 'Your publication is ready to view.',
          action: {
            label: 'View Report',
            onClick: () => navigate('/report'),
          },
          duration: 10000,
        })
      },

      onError: (errMsg) => {
        setError(errMsg)
        setStatus('error')
        toast.error('Report generation failed', {
          description: errMsg,
          duration: 8000,
        })
      },
    }, controller.signal).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setStatus('cancelled')
        setStreamPhase('Cancelled')
        return
      }
      const msg = err instanceof Error ? err.message : 'Failed to generate report'
      setError(msg)
      setStatus('error')
      toast.error('Report generation failed', {
        description: msg,
        duration: 8000,
      })
    })
  }, [navigate])

  const cancelGeneration = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  const clearReport = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setStatus('idle')
    setReport(null)
    setRequest(null)
    setError(null)
    setStreamPhase('')
    setNarrativesDone(0)
    setNarrativesTotal(0)
  }, [])

  const dismissError = useCallback(() => {
    setError(null)
  }, [])

  return (
    <ReportGenerationContext.Provider value={{
      status,
      report,
      request,
      error,
      streamPhase,
      narrativesDone,
      narrativesTotal,
      progressPct,
      startGeneration,
      cancelGeneration,
      clearReport,
      dismissError,
    }}>
      {children}
    </ReportGenerationContext.Provider>
  )
}

export function useReportGeneration() {
  const context = useContext(ReportGenerationContext)
  if (context === undefined) {
    throw new Error('useReportGeneration must be used within a ReportGenerationProvider')
  }
  return context
}
