import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, Users, Globe, FileBarChart, MessageSquare, Shield, X, Loader2, Zap, TrendingUp, Flame, Bell, Bot, Database, UploadCloud, BookOpenText } from 'lucide-react'
import AlertBell from './AlertBell'
import { useAuth } from '../contexts/AuthContext'
import { useReportGeneration } from '../contexts/ReportGenerationContext'
import './Layout.css'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/documents', label: 'Documents', icon: FileText },
  { path: '/events', label: 'Events', icon: Zap },
  { path: '/summaries', label: 'Summaries', icon: TrendingUp },
  { path: '/bilateral', label: 'Bilateral', icon: Users },
  { path: '/chat', label: 'Research', icon: MessageSquare },
  { path: '/agent', label: 'Agent', icon: Bot },
  { path: '/report', label: 'Publication', icon: FileBarChart },
]

const intelligenceItems = [
  { path: '/intel-reports', label: 'Intel Reports', icon: BookOpenText },
  { path: '/events/comparison', label: 'Country Comparison', icon: Globe },
  { path: '/events/materiality', label: 'Materiality Map', icon: Flame },
  { path: '/competing/Egypt', label: 'Competing Influence', icon: TrendingUp },
  { path: '/alerts', label: 'Alerts', icon: Bell },
]

const influencers = [
  { country: 'China', path: '/influencer/China' },
  { country: 'Iran', path: '/influencer/Iran' },
  { country: 'Russia', path: '/influencer/Russia' },
  { country: 'Turkey', path: '/influencer/Turkey' },
  { country: 'United States', path: '/influencer/United States' },
]


export default function Layout() {
  const { user } = useAuth()
  const { status, streamPhase, progressPct, cancelGeneration } = useReportGeneration()

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

          <div className="nav-section">
            <div className="nav-section-title">
              <Zap size={16} />
              <span>Intelligence</span>
            </div>
            {intelligenceItems.map(({ path, label }) => (
              <NavLink
                key={path}
                to={path}
                className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
              >
                <span>{label}</span>
              </NavLink>
            ))}
          </div>

          {/* Data section — analyst and admin only */}
          {(user?.role === 'admin' || user?.role === 'analyst') && (
            <div className="nav-section">
              <div className="nav-section-title">
                <Database size={16} />
                <span>Data</span>
              </div>
              <NavLink
                to="/ingestion"
                className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
              >
                <UploadCloud size={16} />
                <span>Ingestion</span>
              </NavLink>
            </div>
          )}

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

        {/* Report generation progress widget */}
        {status === 'generating' && (
          <NavLink to="/report" className="report-progress-widget">
            <div className="rpw-header">
              <div className="rpw-label">
                <Loader2 size={14} className="rpw-spinner" />
                <span>Generating Report</span>
              </div>
              <button
                className="rpw-cancel"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); cancelGeneration(); }}
                title="Cancel generation"
              >
                <X size={12} />
              </button>
            </div>
            {streamPhase && (
              <div className="rpw-phase">{streamPhase}</div>
            )}
            <div className="rpw-bar">
              <div className="rpw-fill" style={{ width: `${progressPct}%` }} />
            </div>
            <div className="rpw-pct">{progressPct}%</div>
          </NavLink>
        )}

        {/* User section at bottom */}
        <div className="user-section">
          <div className="user-info-row">
            <div className="user-info">
              <span className="user-name">{user?.display_name || user?.username}</span>
              <span className="user-role">{user?.role}</span>
            </div>
            <AlertBell />
          </div>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
