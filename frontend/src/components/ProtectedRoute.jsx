import { Navigate } from 'react-router-dom'

// If there is no JWT in localStorage, bounce to the landing page.
export default function ProtectedRoute({ children }) {
  const token = localStorage.getItem('token')
  if (!token) {
    return <Navigate to="/" replace />
  }
  return children
}
