import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import client from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchMe = useCallback(async () => {
    if (!localStorage.getItem('token')) {
      setUser(null)
      setLoading(false)
      return null
    }
    try {
      const { data } = await client.get('/me')
      setUser(data)
      return data
    } catch {
      // 401 handling lives in the axios interceptor; just clear local state.
      setUser(null)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMe()
  }, [fetchMe])

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    setUser(null)
    window.location.href = '/'
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, fetchMe, setUser, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
