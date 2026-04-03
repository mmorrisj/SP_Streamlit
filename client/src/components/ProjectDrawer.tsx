import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Trash2, FolderOpen, Plus, MessageSquare, FileBarChart, Archive, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import {
  fetchProjects, createProject, fetchProject, deleteProject,
  removeProjectDocument, updateProject,
} from '../api/client'
import type { ResearchProject, ProjectDocument } from '../api/client'
import './ProjectDrawer.css'

interface ProjectDrawerProps {
  isOpen: boolean
  onClose: () => void
  activeProjectId: string | null
  onSelectProject: (id: string | null) => void
  projectMode: boolean
  onToggleProjectMode: () => void
  onGenerateReport: () => void
}

export default function ProjectDrawer({
  isOpen,
  onClose,
  activeProjectId,
  onSelectProject,
  projectMode,
  onToggleProjectMode,
  onGenerateReport,
}: ProjectDrawerProps) {
  const queryClient = useQueryClient()
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [view, setView] = useState<'list' | 'detail'>('list')

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  const { data: activeProject } = useQuery({
    queryKey: ['project', activeProjectId],
    queryFn: () => fetchProject(activeProjectId!),
    enabled: !!activeProjectId,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['projects'] })
    if (activeProjectId) {
      queryClient.invalidateQueries({ queryKey: ['project', activeProjectId] })
    }
  }

  const handleCreate = async () => {
    if (!newProjectName.trim()) return
    const project = await createProject({ name: newProjectName.trim() })
    onSelectProject(project.id)
    setNewProjectName('')
    setShowCreateForm(false)
    setView('detail')
    invalidate()
    toast.success(`Project "${project.name}" created`)
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this project and all collected documents?')) return
    await deleteProject(id)
    if (activeProjectId === id) onSelectProject(null)
    invalidate()
    toast.success('Project deleted')
  }

  const handleRemoveDoc = async (docId: string) => {
    if (!activeProjectId) return
    await removeProjectDocument(activeProjectId, docId)
    invalidate()
    toast.success('Document removed')
  }

  const handleArchive = async () => {
    if (!activeProjectId) return
    await updateProject(activeProjectId, { status: 'archived' })
    onSelectProject(null)
    setView('list')
    invalidate()
    toast.success('Project archived')
  }

  if (!isOpen) return null

  return (
    <div className="project-drawer">
      <div className="drawer-header">
        <h3><FolderOpen size={18} /> Research Projects</h3>
        <button className="drawer-close" onClick={onClose}><X size={18} /></button>
      </div>

      {view === 'list' ? (
        /* Project List View */
        <div className="drawer-body">
          {/* Create form */}
          {showCreateForm ? (
            <div className="create-project-form">
              <input
                type="text"
                value={newProjectName}
                onChange={e => setNewProjectName(e.target.value)}
                placeholder="Project name..."
                autoFocus
                onKeyDown={e => e.key === 'Enter' && handleCreate()}
              />
              <div className="create-form-actions">
                <button onClick={() => setShowCreateForm(false)} className="btn-sm-cancel">Cancel</button>
                <button onClick={handleCreate} className="btn-sm-create">Create</button>
              </div>
            </div>
          ) : (
            <button className="new-project-btn" onClick={() => setShowCreateForm(true)}>
              <Plus size={16} /> New Project
            </button>
          )}

          {/* Project list */}
          <div className="project-list">
            {projects.filter(p => p.status === 'active').map((project: ResearchProject) => (
              <div
                key={project.id}
                className={`project-item ${activeProjectId === project.id ? 'active' : ''}`}
                onClick={() => { onSelectProject(project.id); setView('detail') }}
              >
                <div className="project-item-info">
                  <span className="project-item-name">{project.name}</span>
                  <span className="project-item-count">{project.document_count} docs</span>
                </div>
                <ChevronRight size={14} className="project-item-arrow" />
              </div>
            ))}
            {projects.filter(p => p.status === 'active').length === 0 && (
              <div className="drawer-empty">No active projects. Create one to start collecting documents.</div>
            )}
          </div>
        </div>
      ) : (
        /* Project Detail View */
        <div className="drawer-body">
          <button className="back-to-list" onClick={() => setView('list')}>
            All Projects
          </button>

          {activeProject && (
            <>
              <div className="project-detail-header">
                <h4>{activeProject.name}</h4>
                <span className="doc-count-badge">{activeProject.documents?.length || 0} documents</span>
              </div>

              {/* Action buttons */}
              <div className="project-actions">
                <button
                  className={`project-action-btn ${projectMode ? 'active' : ''}`}
                  onClick={onToggleProjectMode}
                  title="Chat using only these documents"
                >
                  <MessageSquare size={14} />
                  {projectMode ? 'Exit Project Chat' : 'Chat with Collection'}
                </button>
                <button
                  className="project-action-btn"
                  onClick={onGenerateReport}
                  disabled={!activeProject.documents?.length}
                >
                  <FileBarChart size={14} />
                  Generate Report
                </button>
              </div>

              {/* Document list */}
              <div className="project-doc-list">
                {(activeProject.documents || []).map((doc: ProjectDocument) => (
                  <div key={doc.id} className="project-doc-card">
                    <div className="project-doc-title">{doc.title || 'Untitled'}</div>
                    <div className="project-doc-meta">
                      {doc.source_name && <span>{doc.source_name}</span>}
                      {doc.date && <span>{doc.date}</span>}
                      {doc.category && <span className="project-doc-cat">{doc.category}</span>}
                    </div>
                    {doc.initiating_country && doc.recipient_country && (
                      <div className="project-doc-countries">
                        {doc.initiating_country} → {doc.recipient_country}
                      </div>
                    )}
                    <button
                      className="remove-doc-btn"
                      onClick={e => { e.stopPropagation(); handleRemoveDoc(doc.doc_id) }}
                      title="Remove from project"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
                {(!activeProject.documents || activeProject.documents.length === 0) && (
                  <div className="drawer-empty">
                    No documents collected yet. Use the + button on search results to add sources.
                  </div>
                )}
              </div>

              {/* Bottom actions */}
              <div className="project-bottom-actions">
                <button className="archive-btn" onClick={handleArchive}>
                  <Archive size={14} /> Archive Project
                </button>
                <button className="delete-btn" onClick={() => handleDelete(activeProject.id)}>
                  <Trash2 size={14} /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
