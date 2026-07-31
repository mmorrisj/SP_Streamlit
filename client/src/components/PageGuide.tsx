import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Info, ChevronDown, ChevronUp } from 'lucide-react'
import { PAGE_GUIDES } from './pageGuides'
import './PageGuide.css'

const STORAGE_KEY = 'pageGuideState'

function readOpen(page: string): boolean {
  try {
    const map = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    // First visit to a page: expanded. Afterwards, remember the user's choice.
    return map[page] !== 'collapsed'
  } catch {
    return true
  }
}

function writeOpen(page: string, open: boolean) {
  try {
    const map = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    map[page] = open ? 'open' : 'collapsed'
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    // localStorage unavailable — guide just won't remember state
  }
}

export default function PageGuide({ page }: { page: string }) {
  const guide = PAGE_GUIDES[page]
  const [open, setOpen] = useState(() => readOpen(page))

  if (!guide) return null

  const toggle = () => {
    setOpen(!open)
    writeOpen(page, !open)
  }

  return (
    <div className="page-guide">
      <button className="page-guide-toggle" onClick={toggle} aria-expanded={open}>
        <Info size={14} />
        <span>About this page</span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="page-guide-body">
          <p><strong>What you're seeing:</strong> {guide.what}</p>
          <p><strong>How to use it:</strong> {guide.how}</p>
          <p className="page-guide-learn">
            <Link to={guide.learnMore || '/about'}>Learn more in About &amp; Methodology →</Link>
          </p>
        </div>
      )}
    </div>
  )
}
