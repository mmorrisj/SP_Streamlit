import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import { Plus, Edit2, Trash2, Key, Shield, Eye, BarChart3, X } from 'lucide-react'
import './UserManagementPage.css'

interface User {
  id: string
  username: string
  role: string
  display_name: string | null
  is_active: boolean
  force_password_change: boolean
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
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [resetPasswordUser, setResetPasswordUser] = useState<User | null>(null)

  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const { data } = await api.get('/admin/users')
      return data.users as User[]
    }
  })

  const createMutation = useMutation({
    mutationFn: async (userData: Record<string, unknown>) => {
      await api.post('/admin/users', userData)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setShowCreateModal(false)
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

  const resetPasswordMutation = useMutation({
    mutationFn: async ({ userId, password }: { userId: string, password: string }) => {
      await api.post(`/admin/users/${userId}/reset-password`, { new_password: password })
    },
    onSuccess: () => {
      setResetPasswordUser(null)
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
            <p>Manage system users and permissions</p>
          </div>
          <button
            className="create-button"
            onClick={() => setShowCreateModal(true)}
          >
            <Plus size={18} />
            Create User
          </button>
        </div>
      </header>

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
                        title="Edit"
                      >
                        <Edit2 size={16} />
                      </button>
                      <button
                        onClick={() => setResetPasswordUser(user)}
                        className="action-btn reset"
                        title="Reset Password"
                      >
                        <Key size={16} />
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

      {showCreateModal && (
        <UserFormModal
          title="Create User"
          onClose={() => {
            setShowCreateModal(false)
            createMutation.reset()
          }}
          onSubmit={(data) => createMutation.mutate(data)}
          isLoading={createMutation.isPending}
          error={createMutation.error as Error | null}
        />
      )}

      {editingUser && (
        <UserFormModal
          title="Edit User"
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

      {resetPasswordUser && (
        <ResetPasswordModal
          username={resetPasswordUser.username}
          onClose={() => {
            setResetPasswordUser(null)
            resetPasswordMutation.reset()
          }}
          onSubmit={(password) => resetPasswordMutation.mutate({
            userId: resetPasswordUser.id,
            password
          })}
          isLoading={resetPasswordMutation.isPending}
          error={resetPasswordMutation.error as Error | null}
        />
      )}
    </div>
  )
}

interface UserFormModalProps {
  title: string
  user?: User
  onClose: () => void
  onSubmit: (data: Record<string, unknown>) => void
  isLoading: boolean
  error: Error | null
}

function UserFormModal({ title, user, onClose, onSubmit, isLoading, error }: UserFormModalProps) {
  const [username, setUsername] = useState(user?.username || '')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState(user?.display_name || '')
  const [role, setRole] = useState(user?.role || 'viewer')
  const [isActive, setIsActive] = useState(user?.is_active ?? true)
  const [forcePasswordChange, setForcePasswordChange] = useState(user?.force_password_change ?? true)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: Record<string, unknown> = {
      role,
      display_name: displayName || null,
      is_active: isActive,
      force_password_change: forcePasswordChange
    }
    if (!user) {
      data.username = username
      data.password = password
    }
    onSubmit(data)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="close-btn" onClick={onClose}><X size={20} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          {error && (
            <div className="modal-error">
              {(error as unknown as { response?: { data?: { detail?: string } } }).response?.data?.detail || error.message}
            </div>
          )}

          {!user && (
            <>
              <div className="form-group">
                <label>Username</label>
                <input
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  required
                  minLength={3}
                />
              </div>
              <div className="form-group">
                <label>Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
            </>
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
          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                checked={forcePasswordChange}
                onChange={e => setForcePasswordChange(e.target.checked)}
              />
              Force Password Change on Next Login
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

interface ResetPasswordModalProps {
  username: string
  onClose: () => void
  onSubmit: (password: string) => void
  isLoading: boolean
  error: Error | null
}

function ResetPasswordModal({ username, onClose, onSubmit, isLoading, error }: ResetPasswordModalProps) {
  const [password, setPassword] = useState('')

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Reset Password</h2>
          <button className="close-btn" onClick={onClose}><X size={20} /></button>
        </div>
        <p className="modal-subtitle">Set a new password for <strong>{username}</strong></p>
        <form onSubmit={(e) => { e.preventDefault(); onSubmit(password) }}>
          {error && (
            <div className="modal-error">
              {(error as unknown as { response?: { data?: { detail?: string } } }).response?.data?.detail || error.message}
            </div>
          )}
          <div className="form-group">
            <label>New Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="cancel-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="submit-btn" disabled={isLoading}>
              {isLoading ? 'Resetting...' : 'Reset Password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
