import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, Calendar, Users, Folder, BarChart3, Globe, TrendingUp, BookOpen, ArrowLeftRight, Activity } from 'lucide-react'
import './Layout.css'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/metrics', label: 'Metrics', icon: TrendingUp },
  { path: '/timeline', label: 'Timeline', icon: Activity },
  { path: '/documents', label: 'Documents', icon: FileText },
  { path: '/events', label: 'Events', icon: Calendar },
  { path: '/summaries', label: 'Event Summaries', icon: Folder },
  { path: '/document-summaries', label: 'Coverage Summaries', icon: BookOpen },
  { path: '/bilateral-summaries', label: 'Bilateral Summaries', icon: ArrowLeftRight },
  { path: '/bilateral', label: 'Bilateral', icon: Users },
  { path: '/categories', label: 'Categories', icon: BarChart3 },
]

const influencers = [
  { country: 'China', path: '/influencer/China' },
  { country: 'Iran', path: '/influencer/Iran' },
  { country: 'Russia', path: '/influencer/Russia' },
  { country: 'Turkey', path: '/influencer/Turkey' },
  { country: 'United States', path: '/influencer/United States' },
]

const recipients = [
  { country: 'Bahrain', path: '/metrics/recipient/Bahrain' },
  { country: 'Cyprus', path: '/metrics/recipient/Cyprus' },
  { country: 'Egypt', path: '/metrics/recipient/Egypt' },
  { country: 'Iran', path: '/metrics/recipient/Iran' },
  { country: 'Iraq', path: '/metrics/recipient/Iraq' },
  { country: 'Israel', path: '/metrics/recipient/Israel' },
  { country: 'Jordan', path: '/metrics/recipient/Jordan' },
  { country: 'Kuwait', path: '/metrics/recipient/Kuwait' },
  { country: 'Lebanon', path: '/metrics/recipient/Lebanon' },
  { country: 'Libya', path: '/metrics/recipient/Libya' },
  { country: 'Oman', path: '/metrics/recipient/Oman' },
  { country: 'Palestine', path: '/metrics/recipient/Palestine' },
  { country: 'Qatar', path: '/metrics/recipient/Qatar' },
  { country: 'Saudi Arabia', path: '/metrics/recipient/Saudi Arabia' },
  { country: 'Syria', path: '/metrics/recipient/Syria' },
  { country: 'Turkey', path: '/metrics/recipient/Turkey' },
  { country: 'United Arab Emirates', path: '/metrics/recipient/United Arab Emirates' },
  { country: 'UAE', path: '/metrics/recipient/UAE' },
  { country: 'Yemen', path: '/metrics/recipient/Yemen' },
]

export default function Layout() {
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
              <Globe size={16} />
              <span>Recipients</span>
            </div>
            {recipients.map(({ country, path }) => (
              <NavLink
                key={path}
                to={path}
                className={({ isActive }) => `nav-item nav-sub-item ${isActive ? 'active' : ''}`}
              >
                <span>{country}</span>
              </NavLink>
            ))}
          </div>
        </nav>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
