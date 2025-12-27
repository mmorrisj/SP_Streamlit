import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, Calendar, Users, Folder, BarChart3 } from 'lucide-react'
import './Layout.css'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/documents', label: 'Documents', icon: FileText },
  { path: '/events', label: 'Events', icon: Calendar },
  { path: '/summaries', label: 'Summaries', icon: Folder },
  { path: '/bilateral', label: 'Bilateral', icon: Users },
  { path: '/categories', label: 'Categories', icon: BarChart3 },
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
        </nav>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
