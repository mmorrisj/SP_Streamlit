import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { fetchUnreadAlertCount, fetchAlertHistory, acknowledgeAlert } from '../api/client'
import type { AlertHistory } from '../api/client'
import './AlertBell.css'

export default function AlertBell() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const { data: unreadCount = 0 } = useQuery({
    queryKey: ['alerts', 'unread-count'],
    queryFn: fetchUnreadAlertCount,
    refetchInterval: 30_000,
  })

  const { data: recentAlerts } = useQuery({
    queryKey: ['alerts', 'recent'],
    queryFn: () => fetchAlertHistory({ limit: 5 }),
    enabled: open,
  })

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleAcknowledge = async (e: React.MouseEvent, alertId: string) => {
    e.stopPropagation()
    await acknowledgeAlert(alertId)
  }

  const severityIcon: Record<string, string> = {
    info: 'info-badge',
    warning: 'warning-badge',
    critical: 'critical-badge',
  }

  return (
    <div className="alert-bell-container" ref={dropdownRef}>
      <button
        className="alert-bell-button"
        onClick={() => setOpen(!open)}
        title="Alerts"
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="alert-bell-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>
        )}
      </button>

      {open && (
        <div className="alert-bell-dropdown">
          <div className="alert-bell-header">
            <span>Alerts</span>
            <button
              className="alert-bell-view-all"
              onClick={() => { setOpen(false); navigate('/alerts') }}
            >
              View all
            </button>
          </div>

          <div className="alert-bell-list">
            {(!recentAlerts?.alerts || recentAlerts.alerts.length === 0) ? (
              <div className="alert-bell-empty">No alerts</div>
            ) : (
              recentAlerts.alerts.map((alert: AlertHistory) => (
                <div
                  key={alert.id}
                  className={`alert-bell-item ${!alert.acknowledged ? 'unread' : ''}`}
                  onClick={() => { setOpen(false); navigate('/alerts') }}
                >
                  <div className="alert-bell-item-header">
                    <span className={`severity-dot ${severityIcon[alert.severity]}`} />
                    <span className="alert-bell-item-title">{alert.title}</span>
                  </div>
                  <div className="alert-bell-item-message">{alert.message}</div>
                  <div className="alert-bell-item-footer">
                    <span className="alert-bell-item-time">
                      {alert.triggered_at
                        ? new Date(alert.triggered_at).toLocaleString()
                        : ''}
                    </span>
                    {!alert.acknowledged && (
                      <button
                        className="alert-bell-ack-btn"
                        onClick={(e) => handleAcknowledge(e, alert.id)}
                      >
                        Dismiss
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
