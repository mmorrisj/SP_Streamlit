import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, Users, Globe, FileBarChart, MessageSquare, LogOut, Shield } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import './Layout.css'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/documents', label: 'Documents', icon: FileText },
  { path: '/bilateral', label: 'Bilateral', icon: Users },
  { path: '/chat', label: 'Research', icon: MessageSquare },
  { path: '/report', label: 'Publication', icon: FileBarChart },
]

const influencers = [
  { country: 'China', path: '/influencer/China' },
  { country: 'Iran', path: '/influencer/Iran' },
  { country: 'Russia', path: '/influencer/Russia' },
  { country: 'Turkey', path: '/influencer/Turkey' },
  { country: 'United States', path: '/influencer/United States' },
]


export default function Layout() {
  const { user, logout } = useAuth()

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">
          <h1>Soft Power</h1>
          <span>Analytics</span>
        </div>
        <nav className="nav">
          {navItems.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <Icon size={20} />
              <span>{label}</span>
            </NavLink>
          ))}

          <div className="nav-section">
            <div className="nav-section-title">
              <Globe size={16} />
              <span>Influencers</span>
            </div>
            {influencers.map(({ country, path }) => (
              <NavLink
                key={path}
                to={path}
                className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
              >
                <span>{country}</span>
              </NavLink>
            ))}
          </div>

          {/* Admin section */}
          {user?.role === 'admin' && (
            <div className="nav-section">
              <div className="nav-section-title">
                <Shield size={16} />
                <span>Admin</span>
              </div>
              <NavLink
                to="/admin/users"
                className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
              >
                <span>User Management</span>
              </NavLink>
            </div>
          )}
        </nav>

        {/* User section at bottom */}
        <div className="user-section">
          <div className="user-info">
            <span className="user-name">{user?.display_name || user?.username}</span>
            <span className="user-role">{user?.role}</span>
          </div>
          <button onClick={logout} className="logout-button">
            <LogOut size={18} />
            <span>Logout</span>
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
