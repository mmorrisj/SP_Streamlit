import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, Users, Globe, FileBarChart, MessageSquare, Shield, X, Loader2, Zap, TrendingUp, Flame, Bell, Bot, Database, UploadCloud, BookOpenText, Info } from 'lucide-react'
import AlertBell from './AlertBell'
import { useAuth } from '../contexts/AuthContext'
import { useReportGeneration } from '../contexts/ReportGenerationContext'
import { TourProvider } from './tour/TourContext'
import TourButton from './tour/TourButton'
import './Layout.css'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard, tour: 'nav-dashboard' },
  { path: '/report', label: 'Publication', icon: FileBarChart, tour: 'nav-publication' },
  { path: '/chat', label: 'Research', icon: MessageSquare, tour: 'nav-research' },
  { path: '/agent', label: 'Agent', icon: Bot, tour: 'nav-agent' },
  { path: '/events', label: 'Events', icon: Zap, tour: 'nav-events' },
  { path: '/documents', label: 'Documents', icon: FileText, tour: 'nav-documents' },
  { path: '/about', label: 'About & Methodology', icon: Info, tour: 'nav-about' },
]

const intelligenceItems = [
  { path: '/intel-reports', label: 'Insight Reports', icon: BookOpenText, tour: 'nav-intel-reports' },
  { path: '/summaries', label: 'Summaries', icon: TrendingUp, tour: undefined },
  { path: '/bilateral', label: 'Bilateral', icon: Users, tour: undefined },
  { path: '/events/comparison', label: 'Country Comparison', icon: Globe, tour: undefined },
  { path: '/events/materiality', label: 'Materiality Map', icon: Flame, tour: undefined },
  { path: '/competing/Egypt', label: 'Competing Influence', icon: TrendingUp, tour: undefined },
  { path: '/alerts', label: 'Alerts', icon: Bell, tour: undefined },
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
    <TourProvider>
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">
          <h1>Soft Power</h1>
          <span>Analytics</span>
        </div>
        <nav className="nav">
          {navItems.map(({ path, label, icon: Icon, tour }) => (
            <NavLink
              key={path}
              to={path}
              data-tour={tour}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <Icon size={20} />
              <span>{label}</span>
            </NavLink>
          ))}

          <div className="nav-section" data-tour="nav-influencers">
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

          <div className="nav-section" data-tour="nav-insights">
            <div className="nav-section-title">
              <Zap size={16} />
              <span>Insights</span>
            </div>
            {intelligenceItems.map(({ path, label, tour }) => (
              <NavLink
                key={path}
                to={path}
                data-tour={tour}
                className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
              >
                <span>{label}</span>
              </NavLink>
            ))}
          </div>

          {/* Data section — analyst and admin only */}
          {(user?.role === 'admin' || user?.role === 'analyst') && (
            <div className="nav-section" data-tour="nav-data">
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

          <NavLink
            to="/whitepaper"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <BookOpenText size={20} />
            <span>White Paper</span>
          </NavLink>

          <TourButton />
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
        <footer className="gai-caveat">
          Content on this platform is generated with AI from open-source reporting. Summaries, scores,
          and analyses may contain errors and reflect biases inherent in the underlying sources and
          models — verify against cited source documents before relying on them.{' '}
          <NavLink to="/about">About &amp; Methodology</NavLink>
        </footer>
      </main>
    </div>
    </TourProvider>
  )
}
