import { useCallback, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  FileJson,
  FileSpreadsheet,
  Loader2,
  Play,
  UploadCloud,
  X,
  XCircle,
} from 'lucide-react'
import {
  cancelIngestionJob,
  fetchIngestionJob,
  fetchIngestionJobs,
  ingestionErrorsUrl,
  startIngestionJob,
  uploadIngestionFile,
  type IngestionJob,
} from '../api/client'
import PageGuide from '../components/PageGuide'
import './DataIngestionPage.css'

const ACTIVE_STATUSES = new Set(['uploaded', 'validating', 'loading', 'embedding'])
const TERMINAL_STATUSES = new Set(['completed', 'completed_with_errors', 'failed', 'cancelled', 'validation_failed'])

const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Uploaded',
  validating: 'Validating',
  ready: 'Ready to run',
  validation_failed: 'Validation failed',
  loading: 'Loading documents',
  embedding: 'Generating embeddings',
  completed: 'Completed',
  completed_with_errors: 'Completed with errors',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`ing-status ing-status-${status}`}>{STATUS_LABELS[status] || status}</span>
}

export default function DataIngestionPage() {
  const [tab, setTab] = useState<'new' | 'history'>('new')
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [embedNow, setEmbedNow] = useState(true)
  const [reflattenDuplicates, setReflattenDuplicates] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const { data: job } = useQuery({
    queryKey: ['ingestion-job', activeJobId],
    queryFn: () => fetchIngestionJob(activeJobId!),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? 2000 : false
    },
  })

  const { data: history } = useQuery({
    queryKey: ['ingestion-jobs'],
    queryFn: () => fetchIngestionJobs({ limit: 50 }),
    refetchInterval: tab === 'history' ? 5000 : false,
  })

  const uploadMutation = useMutation({
    mutationFn: uploadIngestionFile,
    onSuccess: (data) => {
      setActiveJobId(data.job_id)
      setTab('new')
      queryClient.invalidateQueries({ queryKey: ['ingestion-jobs'] })
    },
    onError: (error: unknown) => {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (error as Error).message
      toast.error(`Upload failed: ${detail}`)
    },
  })

  const startMutation = useMutation({
    mutationFn: () =>
      startIngestionJob(activeJobId!, {
        embed_now: embedNow,
        reflatten_duplicates: reflattenDuplicates,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ingestion-job', activeJobId] })
      queryClient.invalidateQueries({ queryKey: ['ingestion-jobs'] })
    },
    onError: (error: unknown) => {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (error as Error).message
      toast.error(`Could not start ingestion: ${detail}`)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelIngestionJob(jobId),
    onSuccess: () => {
      toast.info('Cancellation requested — the run will stop at the next batch boundary')
      queryClient.invalidateQueries({ queryKey: ['ingestion-job', activeJobId] })
      queryClient.invalidateQueries({ queryKey: ['ingestion-jobs'] })
    },
  })

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return
      const name = file.name.toLowerCase()
      if (!name.endsWith('.json') && !name.endsWith('.csv')) {
        toast.error('Unsupported file — drop a DSR results .json or an atom .csv file')
        return
      }
      uploadMutation.mutate(file)
    },
    [uploadMutation]
  )

  const resetWizard = () => {
    setActiveJobId(null)
    setEmbedNow(true)
    setReflattenDuplicates(false)
  }

  const report = job?.validation_report
  const progress = job?.progress

  return (
    <div className="page ingestion-page">
      <header className="page-header">
        <div className="header-content">
          <div>
            <h1>Data Ingestion</h1>
            <p>
              Upload a DSR <code>results.json</code> or atom <code>.csv</code> file, review the
              dry-run validation report, then run the load → flatten → embed pipeline.
            </p>
          </div>
        </div>
      </header>

      <PageGuide page="data-ingestion" />

      <div className="ing-tabs">
        <button className={tab === 'new' ? 'active' : ''} onClick={() => setTab('new')}>
          <UploadCloud size={16} /> New Run
        </button>
        <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>
          <Database size={16} /> History {history ? `(${history.total})` : ''}
        </button>
      </div>

      {tab === 'history' ? (
        <div className="ing-card">
          {!history || history.jobs.length === 0 ? (
            <div className="ing-empty">No ingestion runs yet.</div>
          ) : (
            <table className="ing-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Loaded</th>
                  <th>Errors</th>
                  <th>By</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {history.jobs.map((row: IngestionJob) => (
                  <tr
                    key={row.id}
                    className="ing-row"
                    onClick={() => {
                      setActiveJobId(row.id)
                      setTab('new')
                    }}
                  >
                    <td className="ing-file-cell">{row.filename}</td>
                    <td>{row.file_type === 'dsr_json' ? 'DSR JSON' : 'Atom CSV'}</td>
                    <td><StatusBadge status={row.status} /></td>
                    <td>{row.progress?.loaded ?? '—'}</td>
                    <td>{row.error_count || 0}</td>
                    <td>{row.created_by || '—'}</td>
                    <td>{formatDate(row.created_at)}</td>
                    <td>
                      {row.error_count > 0 && (
                        <a
                          href={ingestionErrorsUrl(row.id)}
                          onClick={(e) => e.stopPropagation()}
                          title="Download error report"
                        >
                          <Download size={15} />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : !activeJobId ? (
        /* ---- Step 1: Upload ---- */
        <div
          className={`ing-dropzone ${dragOver ? 'drag-over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            handleFile(e.dataTransfer.files?.[0])
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,.csv"
            hidden
            onChange={(e) => {
              handleFile(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          {uploadMutation.isPending ? (
            <>
              <Loader2 size={40} className="ing-spin" />
              <p>Uploading…</p>
            </>
          ) : (
            <>
              <UploadCloud size={40} />
              <p>
                Drag &amp; drop a <strong>results.json</strong> or <strong>atom.csv</strong> file
              </p>
              <span>or click to browse</span>
            </>
          )}
        </div>
      ) : !job ? (
        <div className="ing-card ing-centered">
          <Loader2 size={24} className="ing-spin" />
        </div>
      ) : (
        <div className="ing-detail">
          {/* ---- File summary bar ---- */}
          <div className="ing-card ing-filebar">
            {job.file_type === 'dsr_json' ? <FileJson size={22} /> : <FileSpreadsheet size={22} />}
            <div className="ing-filebar-info">
              <strong>{job.filename}</strong>
              <span>
                {job.file_type === 'dsr_json' ? 'DSR results file' : 'Atom CSV'} ·{' '}
                {formatBytes(job.file_size_bytes)}
              </span>
            </div>
            <StatusBadge status={job.status} />
            <button className="ing-btn-ghost" onClick={resetWizard} title="Start over with a new file">
              <X size={16} />
            </button>
          </div>

          {/* ---- Step 2: Validating ---- */}
          {(job.status === 'uploaded' || job.status === 'validating') && (
            <div className="ing-card ing-centered">
              <Loader2 size={28} className="ing-spin" />
              <p>Validating file — parsing records and checking against the database…</p>
            </div>
          )}

          {job.status === 'validation_failed' && (
            <div className="ing-card ing-error-card">
              <XCircle size={20} />
              <div>
                <strong>This file could not be validated</strong>
                <p>{job.error_message}</p>
              </div>
            </div>
          )}

          {/* ---- Step 2/3: Review + configure ---- */}
          {job.status === 'ready' && report && (
            <>
              <div className="ing-stats-grid">
                <div className="ing-stat">
                  <span className="ing-stat-value">{report.total_records}</span>
                  <span className="ing-stat-label">Records in file</span>
                </div>
                {report.file_type === 'dsr_json' ? (
                  <>
                    <div className="ing-stat ing-stat-new">
                      <span className="ing-stat-value">{report.new_documents}</span>
                      <span className="ing-stat-label">New documents</span>
                    </div>
                    <div className="ing-stat">
                      <span className="ing-stat-value">{report.existing_documents}</span>
                      <span className="ing-stat-label">Already in database</span>
                    </div>
                  </>
                ) : (
                  <div className="ing-stat">
                    <span className="ing-stat-value">{report.parseable}</span>
                    <span className="ing-stat-label">Usable rows</span>
                  </div>
                )}
                <div className={`ing-stat ${report.parse_errors ? 'ing-stat-errors' : ''}`}>
                  <span className="ing-stat-value">{report.parse_errors}</span>
                  <span className="ing-stat-label">Parse errors</span>
                </div>
              </div>

              {(report.date_range || Object.keys(report.collections || {}).length > 0) && (
                <div className="ing-card ing-meta-row">
                  {report.date_range && (
                    <div>
                      <span className="ing-meta-label">Date range</span>
                      <span>
                        {report.date_range.min} → {report.date_range.max}
                      </span>
                    </div>
                  )}
                  {report.collections && Object.keys(report.collections).length > 0 && (
                    <div>
                      <span className="ing-meta-label">Collections</span>
                      <span>
                        {Object.entries(report.collections)
                          .map(([name, count]) => `${name} (${count})`)
                          .join(', ')}
                      </span>
                    </div>
                  )}
                  {report.top_initiating_countries && report.top_initiating_countries.length > 0 && (
                    <div>
                      <span className="ing-meta-label">Top initiators</span>
                      <span>
                        {report.top_initiating_countries
                          .slice(0, 5)
                          .map((c) => `${c.country} (${c.count})`)
                          .join(', ')}
                      </span>
                    </div>
                  )}
                  {report.top_recipient_countries && report.top_recipient_countries.length > 0 && (
                    <div>
                      <span className="ing-meta-label">Top recipients</span>
                      <span>
                        {report.top_recipient_countries
                          .slice(0, 5)
                          .map((c) => `${c.country} (${c.count})`)
                          .join(', ')}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {report.warnings.length > 0 && (
                <div className="ing-card ing-warnings">
                  {report.warnings.map((w) => (
                    <div key={w.code} className="ing-warning">
                      <AlertTriangle size={15} />
                      <span>
                        {w.message} — <strong>{w.count}</strong>
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {report.sample.length > 0 && (
                <div className="ing-card">
                  <h3>Sample ({report.sample.length} of {report.parseable})</h3>
                  <div className="ing-table-scroll">
                    <table className="ing-table">
                      <thead>
                        <tr>
                          {Object.keys(report.sample[0]).map((col) => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {report.sample.map((row, i) => (
                          <tr key={i}>
                            {Object.keys(report.sample[0]).map((col) => (
                              <td key={col}>{row[col] ?? '—'}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {report.runnable ? (
                <div className="ing-card ing-run-panel">
                  <h3>Run options</h3>
                  <label className="ing-option">
                    <input
                      type="checkbox"
                      checked={embedNow}
                      onChange={(e) => setEmbedNow(e.target.checked)}
                    />
                    <span>
                      Generate embeddings now
                      <small>Uncheck to load documents only and embed later (mirrors --no-embed)</small>
                    </span>
                  </label>
                  <label className="ing-option">
                    <input
                      type="checkbox"
                      checked={reflattenDuplicates}
                      onChange={(e) => setReflattenDuplicates(e.target.checked)}
                    />
                    <span>
                      Re-flatten relationships for the {report.existing_documents} document(s) already
                      in the database
                      <small>Re-runs category/country/event normalization for existing documents</small>
                    </span>
                  </label>
                  <div className="ing-run-actions">
                    <button
                      className="ing-btn-primary"
                      disabled={startMutation.isPending}
                      onClick={() => startMutation.mutate()}
                    >
                      {startMutation.isPending ? (
                        <Loader2 size={16} className="ing-spin" />
                      ) : (
                        <Play size={16} />
                      )}
                      Start ingestion ({report.new_documents} new documents)
                    </button>
                    <button className="ing-btn-secondary" onClick={resetWizard}>
                      Discard
                    </button>
                  </div>
                </div>
              ) : (
                <div className="ing-card ing-notice">
                  <AlertTriangle size={18} />
                  <p>{report.not_runnable_reason}</p>
                </div>
              )}
            </>
          )}

          {/* ---- Step 4: Progress ---- */}
          {(job.status === 'loading' || job.status === 'embedding') && progress && (
            <div className="ing-card">
              <div className="ing-progress-header">
                <h3>
                  <Loader2 size={18} className="ing-spin" />{' '}
                  {job.status === 'loading' ? 'Loading documents…' : 'Generating embeddings…'}
                </h3>
                <button
                  className="ing-btn-secondary"
                  disabled={job.cancel_requested}
                  onClick={() => cancelMutation.mutate(job.id)}
                >
                  {job.cancel_requested ? 'Stopping…' : 'Cancel'}
                </button>
              </div>
              <div className="ing-stages">
                <div className="ing-stage done">
                  <CheckCircle2 size={16} />
                  <span>Parse</span>
                  <em>
                    {progress.parsed} / {progress.total_records}
                  </em>
                </div>
                <div className={`ing-stage ${job.status === 'loading' ? 'active' : 'done'}`}>
                  {job.status === 'loading' ? (
                    <Loader2 size={16} className="ing-spin" />
                  ) : (
                    <CheckCircle2 size={16} />
                  )}
                  <span>Load &amp; flatten</span>
                  <em>
                    {progress.loaded} loaded · {progress.duplicates} duplicates · {progress.errors}{' '}
                    errors
                  </em>
                </div>
                <div className={`ing-stage ${job.status === 'embedding' ? 'active' : ''}`}>
                  {job.status === 'embedding' ? (
                    <Loader2 size={16} className="ing-spin" />
                  ) : (
                    <span className="ing-stage-dot" />
                  )}
                  <span>Embed</span>
                  <em>
                    {progress.embedded} / {progress.embed_total || '—'}
                  </em>
                </div>
              </div>
            </div>
          )}

          {/* ---- Step 5: Results ---- */}
          {TERMINAL_STATUSES.has(job.status) && job.status !== 'validation_failed' && (
            <div className="ing-card">
              <div className={`ing-result-header ${job.status}`}>
                {job.status === 'completed' ? <CheckCircle2 size={20} /> : job.status === 'cancelled' ? <X size={20} /> : <AlertTriangle size={20} />}
                <h3>{STATUS_LABELS[job.status]}</h3>
              </div>
              {job.error_message && <p className="ing-error-text">{job.error_message}</p>}
              {progress && (
                <div className="ing-stats-grid">
                  <div className="ing-stat ing-stat-new">
                    <span className="ing-stat-value">{progress.loaded}</span>
                    <span className="ing-stat-label">Documents loaded</span>
                  </div>
                  <div className="ing-stat">
                    <span className="ing-stat-value">{progress.duplicates}</span>
                    <span className="ing-stat-label">Duplicates skipped</span>
                  </div>
                  <div className="ing-stat">
                    <span className="ing-stat-value">{progress.embedded}</span>
                    <span className="ing-stat-label">Embedded</span>
                  </div>
                  <div className={`ing-stat ${job.error_count ? 'ing-stat-errors' : ''}`}>
                    <span className="ing-stat-value">{job.error_count}</span>
                    <span className="ing-stat-label">Errors</span>
                  </div>
                </div>
              )}
              <div className="ing-run-actions">
                {job.error_count > 0 && (
                  <a className="ing-btn-secondary" href={ingestionErrorsUrl(job.id)}>
                    <Download size={15} /> Download error report
                  </a>
                )}
                <button className="ing-btn-primary" onClick={resetWizard}>
                  <UploadCloud size={15} /> Ingest another file
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
