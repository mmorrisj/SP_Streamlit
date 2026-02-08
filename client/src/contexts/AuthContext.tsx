import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import api from '../api/client'

export interface User {
  id: string
  username: string
  role: 'admin' | 'analyst' | 'viewer'
  display_name: string | null
  force_password_change: boolean
}

interface AuthContextType {
  user: User | null
  token: string | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  updateUser: (user: User) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    // Check for existing token on mount
    const storedToken = localStorage.getItem('auth_token')
    if (storedToken) {
      verifyToken(storedToken)
    } else {
      setIsLoading(false)
    }
  }, [])

  const verifyToken = async (storedToken: string) => {
    try {
      api.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`
      const { data } = await api.get('/auth/verify')
      setToken(storedToken)
      setUser(data)
    } catch {
      localStorage.removeItem('auth_token')
      delete api.defaults.headers.common['Authorization']
    } finally {
      setIsLoading(false)
    }
  }

  const login = async (username: string, password: string) => {
    const { data } = await api.post('/auth/login', { username, password })
    const { access_token, user: userData } = data

    localStorage.setItem('auth_token', access_token)
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
    setToken(access_token)
    setUser(userData)
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    delete api.defaults.headers.common['Authorization']
    setToken(null)
    setUser(null)
  }

  const updateUser = (updatedUser: User) => {
    setUser(updatedUser)
  }

  return (
    <AuthContext.Provider value={{
      user,
      token,
      isLoading,
      isAuthenticated: !!user,
      login,
      logout,
      updateUser
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
