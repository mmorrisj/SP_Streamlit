import { useMemo, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, Download } from 'lucide-react'
import { fetchIntelReport } from '../api/client'
import ReportFigure from '../components/ReportFigure'
import './Pages.css'
import './IntelReports.css'

interface TocEntry {
  id: string
  text: string
}

const slugify = (text: string): string =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')

/** Extract plain text from react-markdown children for heading ids. */
const childText = (children: React.ReactNode): string => {
  if (typeof children === 'string') return children
  if (Array.isArray(children)) return children.map(childText).join('')
  if (children && typeof children === 'object' && 'props' in children) {
    return childText((children as React.ReactElement<{ children?: React.ReactNode }>).props.children)
  }
  return ''
}

export default function IntelReportViewerPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  const { data: report, isLoading, error } = useQuery({
    queryKey: ['intel-report', slug],
    queryFn: () => fetchIntelReport(slug!),
    enabled: !!slug,
  })

  // Table of contents from ## headings (fenced code is not used in these reports)
  const toc: TocEntry[] = useMemo(() => {
    if (!report) return []
    return [...report.markdown.matchAll(/^## (.+)$/gm)].map((m) => {
      const text = m[1].replace(/[*_`]/g, '').trim()
      return { id: slugify(text), text }
    })
  }, [report])

  const components: Components = useMemo(() => ({
    h1: () => null, // title is rendered in the page header, not the body
    h2: ({ children }) => <h2 id={slugify(childText(children))}>{children}</h2>,
    // figures render interactive charts (recharts divs), which must not nest in <p>
    p: ({ node, children }) => {
      const hasImage = node?.children?.some(
        (c) => c.type === 'element' && c.tagName === 'img'
      )
      return hasImage ? <div className="ir-figure-block">{children}</div> : <p>{children}</p>
    },
    img: ({ src, alt }) => (
      <ReportFigure src={src ?? ''} alt={alt ?? ''} slug={slug ?? ''} />
    ),
    a: ({ href, children }) => {
      if (!href) return <span>{children}</span>
      if (href.startsWith('/intel-reports/')) {
        return <Link to={href}>{children}</Link>
      }
      if (href.endsWith('.csv')) {
        return (
          <a href={href} download className="ir-csv-link">
            <Download size={13} /> {children}
          </a>
        )
      }
      if (href.startsWith('#') || href.startsWith('/api/')) {
        return <a href={href}>{children}</a>
      }
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    },
    table: ({ children }) => (
      <div className="ir-table-wrap"><table>{children}</table></div>
    ),
  }), [slug])

  const scrollTo = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  if (isLoading) return <div className="page"><div className="loading">Loading report…</div></div>
  if (error || !report) {
    return (
      <div className="page">
        <div className="error">Report not found</div>
        <button className="ir-back-btn" onClick={() => navigate('/intel-reports')}>
          <ArrowLeft size={16} /> All reports
        </button>
      </div>
    )
  }

  return (
    <div className="page ir-viewer-page">
      <div className="ir-viewer-topbar">
        <Link to="/intel-reports" className="ir-back-btn">
          <ArrowLeft size={16} /> All reports
        </Link>
        <span className={`ir-badge ir-badge-${report.group.toLowerCase()}`}>{report.group}</span>
        <span className="ir-updated">Updated {report.updated}</span>
      </div>

      <div className="ir-viewer-layout">
        <article className="ir-article">
          <h1 className="ir-article-title">{report.title}</h1>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {report.markdown}
          </ReactMarkdown>
        </article>

        {toc.length > 1 && (
          <aside className="ir-toc">
            <div className="ir-toc-title">Contents</div>
            {toc.map((t) => (
              <button key={t.id} className="ir-toc-item" onClick={() => scrollTo(t.id)}>
                {t.text}
              </button>
            ))}
          </aside>
        )}
      </div>

    </div>
  )
}
