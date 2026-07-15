import { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import GeoBlocked from './components/GeoBlocked'
import Landing from './pages/Landing'
import AuthCallback from './pages/AuthCallback'
import Dashboard from './pages/Dashboard'
import MatchLobby from './pages/MatchLobby'
import MatchResult from './pages/MatchResult'
import Wallet from './pages/Wallet'

export default function App() {
  const [blocked, setBlocked] = useState(false)

  // The axios interceptor fires this on any 451 response.
  useEffect(() => {
    const onBlocked = () => setBlocked(true)
    window.addEventListener('geo-blocked', onBlocked)
    return () => window.removeEventListener('geo-blocked', onBlocked)
  }, [])

  if (blocked) {
    return <GeoBlocked />
  }

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/match/:id"
        element={
          <ProtectedRoute>
            <MatchLobby />
          </ProtectedRoute>
        }
      />
      <Route
        path="/match/:id/result"
        element={
          <ProtectedRoute>
            <MatchResult />
          </ProtectedRoute>
        }
      />
      <Route
        path="/wallet"
        element={
          <ProtectedRoute>
            <Wallet />
          </ProtectedRoute>
        }
      />
      {/* Unknown routes fall back to the landing page. */}
      <Route path="*" element={<Landing />} />
    </Routes>
  )
}
