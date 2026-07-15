import { Link } from 'react-router-dom'

export default function Logo({ to = '/', light = false }) {
  return (
    <Link
      to={to}
      className={`text-lg font-semibold tracking-tight ${light ? 'text-white' : 'text-ink'}`}
    >
      1v1<span className="text-accent">wager</span>
    </Link>
  )
}
