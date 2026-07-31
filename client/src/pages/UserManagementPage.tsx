import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import { Edit2, Trash2, Shield, Eye, BarChart3, X } from 'lucide-react'
import PageGuide from '../components/PageGuide'
import './UserManagementPage.css'

interface User {
  id: string
  username: string
  enterprise_id: string | null
  role: string
  display_name: string | null
  is_active: boolean
  created_at: string
  last_login: string | null
}

const ROLE_ICONS = {
  admin: Shield,
  analyst: BarChart3,
  viewer: Eye
}

const ROLE_COLORS = {
  admin: '#dc2626',
  analyst: '#2563eb',
  viewer: '#16a34a'
}

export default function UserManagementPage() {
  const [editingUser, setEditingUser] = useState<User | null>(null)

  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const { data } = await api.get('/admin/users')
      return data.users as User[]
    }
  })

  const updateMutation = useMutation({
    mutationFn: async ({ userId, updates }: { userId: string, updates: Record<string, unknown> }) => {
      await api.put(`/admin/users/${userId}`, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setEditingUser(null)
    }
  })

  const deleteMutation = useMutation({
    mutationFn: async (userId: string) => {
      await api.delete(`/admin/users/${userId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })

  if (isLoading) {
    return <div className="page"><div className="loading">Loading users...</div></div>
  }

  return (
    <div className="page user-management-page">
      <header className="page-header">
        <div className="header-content">
          <div>
            <h1>User Management</h1>
            <p>Manage user roles and permissions. Users are auto-provisioned when they first access the application via the enterprise gateway.</p>
          </div>
        </div>
      </header>

      <PageGuide page="user-management" />

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Display Name</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last Login</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.map(user => {
              const RoleIcon = ROLE_ICONS[user.role as keyof typeof ROLE_ICONS] || Eye
              return (
                <tr key={user.id}>
                  <td className="username-cell">{user.username}</td>
                  <td>{user.display_name || '-'}</td>
                  <td>
                    <span className="badge role-badge" style={{
                      background: `${ROLE_COLORS[user.role as keyof typeof ROLE_COLORS]}20`,
                      color: ROLE_COLORS[user.role as keyof typeof ROLE_COLORS]
                    }}>
                      <RoleIcon size={14} />
                      {user.role}
                    </span>
                  </td>
                  <td>
                    <span className={`badge status-badge ${user.is_active ? 'active' : 'inactive'}`}>
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>{user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}</td>
                  <td>
                    <div className="action-buttons">
                      <button
                        onClick={() => setEditingUser(user)}
                        className="action-btn edit"
                        title="Edit Role / Status"
                      >
                        <Edit2 size={16} />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Delete user ${user.username}?`)) {
                            deleteMutation.mutate(user.id)
                          }
                        }}
                        className="action-btn delete"
                        title="Delete"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {editingUser && (
        <UserEditModal
          user={editingUser}
          onClose={() => {
            setEditingUser(null)
            updateMutation.reset()
          }}
          onSubmit={(data) => updateMutation.mutate({ userId: editingUser.id, updates: data })}
          isLoading={updateMutation.isPending}
          error={updateMutation.error as Error | null}
        />
      )}
    </div>
  )
}

interface UserEditModalProps {
  user: User
  onClose: () => void
  onSubmit: (data: Record<string, unknown>) => void
  isLoading: boolean
  error: Error | null
}

function UserEditModal({ user, onClose, onSubmit, isLoading, error }: UserEditModalProps) {
  const [displayName, setDisplayName] = useState(user.display_name || '')
  const [role, setRole] = useState(user.role)
  const [isActive, setIsActive] = useState(user.is_active)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({
      role,
      display_name: displayName || null,
      is_active: isActive,
    })
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Edit User: {user.username}</h2>
          <button className="close-btn" onClick={onClose}><X size={20} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          {error && (
            <div className="modal-error">
              {(error as unknown as { response?: { data?: { detail?: string } } }).response?.data?.detail || error.message}
            </div>
          )}

          <div className="form-group">
            <label>Display Name</label>
            <input
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="form-group">
            <label>Role</label>
            <select value={role} onChange={e => setRole(e.target.value)}>
              <option value="viewer">Viewer</option>
              <option value="analyst">Analyst</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                checked={isActive}
                onChange={e => setIsActive(e.target.checked)}
              />
              Active
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="cancel-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="submit-btn" disabled={isLoading}>
              {isLoading ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
