import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, Search } from 'lucide-react'
import './Pages.css'

interface Document {
  id: number
  atom_id: string
  title: string
  source_name: string
  source_date: string
  category: string
  initiating_country: string
  recipient_country: string
}

export default function Documents() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const limit = 20

  const { data, isLoading } = useQuery({
    queryKey: ['documents', page, search],
    queryFn: async () => {
      const response = await fetch(`/api/documents?page=${page}&limit=${limit}&search=${search}`)
      return response.json()
    },
  })

  return (
    <div className="page">
      <header className="page-header">
        <h1>Documents</h1>
        <p>Browse and search diplomatic documents</p>
      </header>

      <div className="search-bar">
        <Search size={20} />
        <input
          type="text"
          placeholder="Search documents..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {isLoading ? (
        <div className="loading">Loading documents...</div>
      ) : (
        <>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Source</th>
                  <th>Date</th>
                  <th>Category</th>
                  <th>Countries</th>
                </tr>
              </thead>
              <tbody>
                {data?.documents?.length > 0 ? (
                  data.documents.map((doc: Document) => (
                    <tr key={doc.id}>
                      <td>
                        <div className="doc-title">
                          <FileText size={16} />
                          <span>{doc.title || 'Untitled'}</span>
                        </div>
                      </td>
                      <td>{doc.source_name}</td>
                      <td>{doc.source_date}</td>
                      <td>
                        <span className="badge">{doc.category}</span>
                      </td>
                      <td>{doc.initiating_country} → {doc.recipient_country}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="empty-state">
                      No documents found. Data will appear once documents are added to the database.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>
              Previous
            </button>
            <span>Page {page}</span>
            <button onClick={() => setPage(p => p + 1)} disabled={!data?.documents?.length}>
              Next
            </button>
          </div>
        </>
      )}
    </div>
  )
}
