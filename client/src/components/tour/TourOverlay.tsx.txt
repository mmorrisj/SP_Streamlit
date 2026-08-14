import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import type { TourStep } from './tourSteps'
import './GuidedTour.css'

const SPOT_PAD = 6 // px of breathing room around the spotlit element
const TIP_WIDTH = 340
const VIEW_MARGIN = 12 // min distance between tooltip and viewport edge
const GAP = 14 // distance between spotlight and tooltip
const FIND_TIMEOUT_MS = 3500 // give lazy-loaded targets a chance before falling back

interface TargetRect {
  top: number
  left: number
  width: number
  height: number
}

interface Props {
  steps: TourStep[]
  index: number
  onIndex: (i: number) => void
  onClose: (completed: boolean) => void
}

export default function TourOverlay({ steps, index, onIndex, onClose }: Props) {
  const step = steps[index]
  const navigate = useNavigate()
  const location = useLocation()
  const [rect, setRect] = useState<TargetRect | null>(null)
  // Target never appeared (empty data, hidden section) — show the step centered instead.
  const [missing, setMissing] = useState(!step.target)
  const tipRef = useRef<HTMLDivElement>(null)
  const [tipSize, setTipSize] = useState({ w: TIP_WIDTH, h: 180 })

  const isLast = index === steps.length - 1
  const next = useCallback(() => {
    if (isLast) onClose(true)
    else onIndex(index + 1)
  }, [isLast, index, onIndex, onClose])
  const back = useCallback(() => {
    if (index > 0) onIndex(index - 1)
  }, [index, onIndex])

  // Steps can live on other pages — navigate there first.
  useEffect(() => {
    if (step.route && location.pathname !== step.route) navigate(step.route)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index])

  // Find the target and keep tracking it: the page may still be loading data,
  // scrolling, or reflowing, so re-measure on an interval rather than once.
  useEffect(() => {
    setRect(null)
    setMissing(!step.target)
    if (!step.target) return
    let cancelled = false
    let scrolled = false
    const started = Date.now()

    const measure = () => {
      if (cancelled) return
      const el = document.querySelector(step.target!)
      if (el) {
        const r = el.getBoundingClientRect()
        if (!scrolled && (r.top < 0 || r.bottom > window.innerHeight)) {
          scrolled = true
          // Tall sections get pinned to the top of the viewport; small targets center.
          const block = r.height > window.innerHeight * 0.6 ? 'start' : 'center'
          el.scrollIntoView({ block, behavior: 'smooth' })
        }
        setMissing(false)
        setRect(prev => {
          const nextRect = { top: r.top, left: r.left, width: r.width, height: r.height }
          const same =
            prev &&
            Math.abs(prev.top - nextRect.top) < 1 &&
            Math.abs(prev.left - nextRect.left) < 1 &&
            Math.abs(prev.width - nextRect.width) < 1 &&
            Math.abs(prev.height - nextRect.height) < 1
          return same ? prev : nextRect
        })
      } else if (Date.now() - started > FIND_TIMEOUT_MS) {
        setMissing(true)
      }
    }

    measure()
    const timer = window.setInterval(measure, 150)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [index, step.target, location.pathname])

  // Keyboard navigation
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose(false)
      else if (e.key === 'ArrowRight' || e.key === 'Enter') next()
      else if (e.key === 'ArrowLeft') back()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [next, back, onClose])

  // Measure the tooltip so placement math can center and clamp it properly.
  useLayoutEffect(() => {
    const el = tipRef.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    if (Math.abs(width - tipSize.w) > 1 || Math.abs(height - tipSize.h) > 1) {
      setTipSize({ w: width, h: height })
    }
  }, [index, tipSize.w, tipSize.h])

  const centered = missing || !rect
  // Clamp spotlights taller than the viewport so the frame stays visible.
  const spot = rect
    ? {
        ...rect,
        height: Math.min(rect.height, window.innerHeight - Math.max(rect.top, 0) - VIEW_MARGIN * 2),
      }
    : null
  let tipStyle: React.CSSProperties
  if (centered) {
    tipStyle = { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
  } else {
    const rect = spot!
    const placement = step.placement || 'bottom'
    let top: number
    let left: number
    if (placement === 'right') {
      left = rect.left + rect.width + SPOT_PAD + GAP
      top = rect.top + rect.height / 2 - tipSize.h / 2
    } else if (placement === 'left') {
      left = rect.left - SPOT_PAD - GAP - tipSize.w
      top = rect.top + rect.height / 2 - tipSize.h / 2
    } else if (placement === 'top') {
      top = rect.top - SPOT_PAD - GAP - tipSize.h
      left = rect.left + rect.width / 2 - tipSize.w / 2
    } else {
      top = rect.top + rect.height + SPOT_PAD + GAP
      left = rect.left + rect.width / 2 - tipSize.w / 2
    }
    left = Math.min(Math.max(VIEW_MARGIN, left), window.innerWidth - tipSize.w - VIEW_MARGIN)
    top = Math.min(Math.max(VIEW_MARGIN, top), window.innerHeight - tipSize.h - VIEW_MARGIN)
    tipStyle = { top, left }
  }

  const progressPct = ((index + 1) / steps.length) * 100

  return (
    <div className="tour-root" role="dialog" aria-modal="true" aria-label="Guided tour">
      {centered ? (
        <div className="tour-backdrop" />
      ) : (
        <div
          className="tour-spotlight"
          style={{
            top: spot!.top - SPOT_PAD,
            left: spot!.left - SPOT_PAD,
            width: spot!.width + SPOT_PAD * 2,
            height: spot!.height + SPOT_PAD * 2,
          }}
        />
      )}
      <div className="tour-tooltip" ref={tipRef} style={{ ...tipStyle, width: TIP_WIDTH }}>
        <button className="tour-close" onClick={() => onClose(false)} aria-label="Exit tour">
          <X size={14} />
        </button>
        <div className="tour-step-count">
          Step {index + 1} of {steps.length}
        </div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-controls">
          <button className="tour-skip" onClick={() => onClose(false)}>
            Skip tour
          </button>
          <div className="tour-nav-buttons">
            {index > 0 && (
              <button className="tour-back" onClick={back}>
                Back
              </button>
            )}
            <button className="tour-next" onClick={next}>
              {isLast ? 'Finish' : 'Next'}
            </button>
          </div>
        </div>
        <div className="tour-progress">
          <div className="tour-progress-fill" style={{ width: `${progressPct}%` }} />
        </div>
      </div>
    </div>
  )
}
