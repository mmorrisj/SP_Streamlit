import { useQuery } from '@tanstack/react-query'
import { Database } from 'lucide-react'
import { fetchDataCoverage } from '../api/client'
import './DataCoverageBadge.css'

/**
 * Small badge showing how current the corpus is. Ingestion lags the wall
 * clock, so surfaces that interpret "recent" show this next to their header:
 * "Data through 2026-07-08" (amber with a lag note when >7 days behind).
 */
export default function DataCoverageBadge() {
  const { data } = useQuery({
    queryKey: ['data-coverage'],
    queryFn: fetchDataCoverage,
    staleTime: 5 * 60 * 1000,
  })

  if (!data?.max_date) return null
  const behind = data.days_behind ?? 0
  const lagging = behind > 7

  return (
    <span
      className={`coverage-badge ${lagging ? 'coverage-badge-lagging' : ''}`}
      title={
        `Corpus: ${data.total_documents.toLocaleString()} documents, ` +
        `${data.min_date} → ${data.max_date}.` +
        (behind > 1
          ? ` Ingestion is ${behind} days behind today — there is no data yet for the most recent ${behind} days; "recent" is interpreted relative to ${data.max_date}.`
          : ' Coverage is current.')
      }
    >
      <Database size={12} />
      Data through {data.max_date}
      {lagging && <span className="coverage-badge-lag">{behind}d behind</span>}
    </span>
  )
}
