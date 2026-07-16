import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import InlineError from '../components/InlineError'
import Logo from '../components/Logo'

// The backend completes FACEIT OAuth and redirects here with ?token=<jwt>.
export default function AuthCallback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { fetchMe } = useAuth()
  const [error, setError] = useState('')

  useEffect(() => {
    const token = params.get('token')
    const err = params.get('error')
    if (err) {
      setError(err)
      return
    }
    if (!token) {
      setError('No session token returned from FACEIT.')
      return
    }
    localStorage.setItem('token', token)
    // Land on the tables — signing in is a means to an end, and the end is
    // taking a seat. The CTA that started this promised exactly that.
    fetchMe().finally(() => navigate('/tables', { replace: true }))
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
