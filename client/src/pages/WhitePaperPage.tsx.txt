import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchWhitePaper } from '../api/client'
import './Pages.css'
import './IntelReports.css'

export default function WhitePaperPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['whitepaper'],
    queryFn: fetchWhitePaper,
    staleTime: 60 * 60 * 1000,
  })

  if (isLoading) {
    return (
      <div className="page">
        <div className="loading">Loading white paper...</div>
      </div>
    )
  }

  if (error || !data?.markdown) {
    return (
      <div className="page">
        <div className="error">
          <h3>Unable to load the white paper</h3>
          <p>Make sure the API server is running</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page ir-viewer-page">
      <article className="ir-article" style={{ maxWidth: '900px', margin: '0 auto' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.markdown}</ReactMarkdown>
      </article>
    </div>
  )
}
