import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BookOpenText, Image as ImageIcon, CalendarDays } from 'lucide-react'
import { fetchIntelReports, type IntelReportMeta } from '../api/client'
import PageGuide from '../components/PageGuide'
import './Pages.css'
import './IntelReports.css'

const GROUP_ORDER: IntelReportMeta['group'][] = ['Theater', 'Initiator', 'Category', 'Recipient']

const GROUP_LABELS: Record<string, string> = {
  Theater: 'Theater Assessment',
  Initiator: 'By Influencer',
  Category: 'By Category (Cross-Actor)',
  Recipient: 'By Recipient (Who Courts Whom)',
}

export default function IntelReportsPage() {
  const { data: reports, isLoading, error } = useQuery({
    queryKey: ['intel-reports'],
    queryFn: fetchIntelReports,
  })

  if (isLoading) return <div className="page"><div className="loading">Loading reports…</div></div>
  if (error) return <div className="page"><div className="error">Failed to load reports</div></div>

  const groups = GROUP_ORDER
    .map((g) => ({ group: g, items: (reports ?? []).filter((r) => r.group === g) }))
    .filter((g) => g.items.length > 0)

  return (
    <div className="page">
      <div className="page-header">
        <h1>Insight Reports</h1>
        <p>
          Analytic insight reports generated from the corpus — provenance-normalized,
          initiative-grain analysis with verified findings. Media corpus 2024-08 onward.
        </p>
        <p className="ir-disclaimer">
          AI-assisted analytical products generated from open-source media with automated
          verification. Not intelligence community products; they do not represent IC
          tradecraft or review standards.
        </p>
      </div>

      <PageGuide page="intel-reports" />

      {groups.map(({ group, items }) => (
        <section key={group} className="ir-group">
          <h2 className="ir-group-title">{GROUP_LABELS[group] ?? group}</h2>
          <div className="cards-grid">
            {items.map((r) => (
              <Link key={r.slug} to={`/intel-reports/${r.slug}`} className={`ir-card ${group === 'Theater' ? 'ir-card-featured' : ''}`}>
                <div className="ir-card-header">
                  <BookOpenText size={18} />
                  <span className={`ir-badge ir-badge-${group.toLowerCase()}`}>{group}</span>
                </div>
                <h3>{r.title}</h3>
                {r.description && <p className="ir-card-desc">{r.description}</p>}
                <div className="ir-card-meta">
                  <span><CalendarDays size={14} /> {r.updated}</span>
                  {r.figure_count > 0 && <span><ImageIcon size={14} /> {r.figure_count} figures</span>}
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
