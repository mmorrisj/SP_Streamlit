import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, Image as ImageIcon, Download, X, MousePointerClick } from 'lucide-react'
import { parseCsv } from './reportFigures/csv'
import { pickBuilder, ACTOR_COLORS } from './reportFigures/builders'
import EvidenceDrawer from './EvidenceDrawer'

interface ReportFigureProps {
  src: string
  alt: string
  slug: string
}

/** Accent color for single-actor reports, from the report slug. */
const accentForSlug = (slug: string): string => {
  const key = Object.keys(ACTOR_COLORS).find(
    (a) => slug.toLowerCase().replace(/_/g, ' ') === a.toLowerCase()
  )
  return key ? ACTOR_COLORS[key] : '#1a365d'
}

/**
 * A report figure: if the PNG has a sibling CSV whose shape matches a known
 * chart builder, render an interactive recharts version (toggleable back to
 * the static image); otherwise render the PNG with a zoom lightbox.
 */
export default function ReportFigure({ src, alt, slug }: ReportFigureProps) {
  const [mode, setMode] = useState<'chart' | 'image'>('chart')
  const [zoomed, setZoomed] = useState(false)
  const [drill, setDrill] = useState<{ name: string; actor?: string } | null>(null)

  const csvUrl = src.endsWith('.png') ? src.replace(/\.png$/, '.csv') : null

  const { data: table } = useQuery({
    queryKey: ['figure-csv', csvUrl],
    enabled: !!csvUrl,
    staleTime: Infinity,
    retry: false,
    queryFn: async () => {
      const res = await fetch(csvUrl!)
      if (!res.ok) throw new Error('no csv')
      return parseCsv(await res.text())
    },
  })

  const filename = src.split('/').pop() ?? src
  const builder = useMemo(
    () => (table ? pickBuilder(filename, table) : null),
    [table, filename]
  )

  const image = (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      className="ir-figure-img"
      onClick={() => setZoomed(true)}
    />
  )

  const lightbox = zoomed && (
    <div className="ir-lightbox" onClick={() => setZoomed(false)}>
      <button className="ir-lightbox-close" aria-label="Close"><X size={22} /></button>
      <img src={src} alt={alt} onClick={(e) => e.stopPropagation()} />
      {alt && <div className="ir-lightbox-caption">{alt}</div>}
    </div>
  )

  if (!builder) {
    return <span className="ir-figure">{image}{lightbox}</span>
  }

  const drillable = builder.key === 'initiative-bars'

  return (
    <span className="ir-figure ir-figure-interactive">
      <span className="ir-figure-toolbar">
        {drillable && mode === 'chart' && (
          <span className="ir-fig-hint">
            <MousePointerClick size={13} /> click a bar for sources
          </span>
        )}
        <button
          className={`ir-fig-btn ${mode === 'chart' ? 'active' : ''}`}
          onClick={() => setMode('chart')}
          title="Interactive chart"
        >
          <BarChart3 size={13} /> Chart
        </button>
        <button
          className={`ir-fig-btn ${mode === 'image' ? 'active' : ''}`}
          onClick={() => setMode('image')}
          title="Original figure"
        >
          <ImageIcon size={13} /> Figure
        </button>
        {csvUrl && (
          <a className="ir-fig-btn" href={csvUrl} download title="Download data">
            <Download size={13} /> Data
          </a>
        )}
      </span>
      {mode === 'chart' && table ? (
        <span className="ir-figure-chart">
          {builder.render(table, {
            accent: accentForSlug(slug),
            filename,
            onDrill: drillable ? setDrill : undefined,
          })}
        </span>
      ) : (
        image
      )}
      {lightbox}
      {drill && (
        <EvidenceDrawer name={drill.name} actor={drill.actor} onClose={() => setDrill(null)} />
      )}
    </span>
  )
}
