import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { TOUR_STEPS } from './tourSteps'
import TourOverlay from './TourOverlay'

const STORAGE_KEY = 'guidedTourState'

interface TourContextValue {
  startTour: () => void
  isActive: boolean
}

const TourContext = createContext<TourContextValue>({ startTour: () => {}, isActive: false })

// eslint-disable-next-line react-refresh/only-export-components
export const useTour = () => useContext(TourContext)

function readState(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeState(value: string) {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // localStorage unavailable — the tour just won't remember it ran
  }
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [active, setActive] = useState(false)
  const [index, setIndex] = useState(0)

  const steps = useMemo(
    () =>
      TOUR_STEPS.filter(step => {
        if (!step.minRole) return true
        if (step.minRole === 'analyst') return user?.role === 'analyst' || user?.role === 'admin'
        return user?.role === 'admin'
      }),
    [user?.role]
  )

  const startTour = useCallback(() => {
    setIndex(0)
    setActive(true)
  }, [])

  // Auto-launch once for first-time users, after the app has had a moment to render.
  useEffect(() => {
    if (readState()) return
    const timer = window.setTimeout(() => {
      setIndex(0)
      setActive(true)
    }, 1200)
    return () => window.clearTimeout(timer)
  }, [])

  const close = useCallback((completed: boolean) => {
    setActive(false)
    writeState(completed ? 'completed' : 'dismissed')
  }, [])

  return (
    <TourContext.Provider value={{ startTour, isActive: active }}>
      {children}
      {active && steps.length > 0 && (
        <TourOverlay
          steps={steps}
          index={Math.min(index, steps.length - 1)}
          onIndex={setIndex}
          onClose={close}
        />
      )}
    </TourContext.Provider>
  )
}
