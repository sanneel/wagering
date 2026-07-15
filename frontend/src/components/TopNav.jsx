import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Logo from './Logo'
import { useAuth } from '../context/AuthContext'
import { money } from '../lib/format'

export default function TopNav() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  // Close dropdown on outside click.
  useEffect(() => {
    function onClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const avatar = user?.avatar || user?.faceit_avatar
  const name = user?.faceit_username || 'Account'
  const initial = name.slice(0, 1).toUpperCase()

  return (
    <header className="border-b border-line">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <Logo to="/dashboard" />

        <div className="text-sm font-medium text-ink">
          {user ? money(user.balance) : '—'}
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/wallet"
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-dark"
          >
            Deposit
          </Link>

          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-line bg-gray-100 text-sm font-semibold text-muted"
              aria-label="Account menu"
            >
              {avatar ? (
                <img
                  src={avatar}
                  alt={name}
                  className="h-full w-full object-cover"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none'
                  }}
                />
              ) : (
                initial
              )}
            </button>

            {open && (
              <div className="absolute right-0 mt-2 w-40 rounded-md border border-line bg-white py-1 shadow-sm">
                <Link
                  to="/dashboard"
                  className="block px-4 py-2 text-sm text-ink hover:bg-gray-50"
                  onClick={() => setOpen(false)}
                >
                  Profile
                </Link>
                <Link
                  to="/wallet"
                  className="block px-4 py-2 text-sm text-ink hover:bg-gray-50"
                  onClick={() => setOpen(false)}
                >
                  Withdraw
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false)
                    logout()
                    navigate('/')
                  }}
                  className="block w-full px-4 py-2 text-left text-sm text-ink hover:bg-gray-50"
                >
                  Logout
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
