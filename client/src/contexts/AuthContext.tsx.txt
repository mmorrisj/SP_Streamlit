import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import api from '../api/client'

export interface User {
  id: string
  username: string
  role: 'admin' | 'analyst' | 'viewer'
  display_name: string | null
}

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const fetchUser = async () => {
    try {
      // The enterprise gateway injects the JWT header on every request.
      // We just call /auth/me to get the current user identity and role.
      const { data } = await api.get('/auth/me')
      setUser(data)
    } catch {
      // If the enterprise JWT is missing or invalid, the user isn't authenticated.
      // This shouldn't happen in normal operation since the gateway handles auth.
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchUser()
  }, [])

  return (
    <AuthContext.Provider value={{
      user,
      isLoading,
      isAuthenticated: !!user,
      refreshUser: fetchUser,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
