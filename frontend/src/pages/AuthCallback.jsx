import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import InlineError from '../components/InlineError'
import Logo from '../components/Logo'

export default function AuthCallback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { fetchMe } = useAuth()
  const [error, setError] = useState('')

  useEffect(() => {
    const err = params.get('error')
    if (err) {
      setError(err)
      return
    }

    const code = params.get('code')
    if (!code) {
      setError('No code returned from authentication.')
      return
    }

    // Exchange the code for a token via the shared API client so the request
    // hits the backend (API_BASE), not the frontend origin.
    client
      .post('/auth/exchange', { code })
      .then(({ data }) => {
        const token = data.access_token
        if (!token) {
          throw new Error('No token in response')
        }
        localStorage.setItem('token', token)
        // Land on the tables — signing in is a means to an end, and the end is
        // taking a seat. The CTA that started this promised exactly that.
        return fetchMe().finally(() => navigate('/tables', { replace: true }))
      })
      .catch((err) => {
        console.error(err)
        const detail = err?.response?.data?.detail
        setError(detail || err.message || 'Authentication failed')
      })
  }, [params, fetchMe, navigate])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <Logo to="/" />
      {error ? (
        <>
          <InlineError message={error} />
          <button
            type="button"
            onClick={() => navigate('/')}
            className="text-sm text-accent hover:underline"
          >
            Back to home
          </button>
        </>
      ) : (
        <p className="text-sm text-muted">Signing you in…</p>
      )}
    </div>
  )
}