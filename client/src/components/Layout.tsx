import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, Calendar, Users, Folder, BarChart3, Globe } from 'lucide-react'
import './Layout.css'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/documents', label: 'Documents', icon: FileText },
  { path: '/events', label: 'Events', icon: Calendar },
  { path: '/summaries', label: 'Summaries', icon: Folder },
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
        </nav>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
