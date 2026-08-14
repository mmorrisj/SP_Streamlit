import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

interface ProtectedRouteProps {
  children: ReactNode
  requiredRole?: 'admin' | 'analyst' | 'viewer'
}

const ROLE_HIERARCHY = {
  admin: 3,
  analyst: 2,
  viewer: 1
}

export default function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const { user, isLoading, isAuthenticated } = useAuth()

  if (isLoading) {
    return (
      <div className="loading-screen">
        <div className="loading">Loading...</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    // Enterprise gateway should always provide auth.
    // If we reach here, something is wrong with the gateway.
    return (
      <div className="loading-screen">
        <div className="loading">Authentication required. Please ensure you are accessing this application through the enterprise gateway.</div>
      </div>
    )
  }

  // Check role if required
  if (requiredRole && user) {
    const userLevel = ROLE_HIERARCHY[user.role]
    const requiredLevel = ROLE_HIERARCHY[requiredRole]

    if (userLevel < requiredLevel) {
      return <Navigate to="/" replace />
    }
  }

  return <>{children}</>
}
