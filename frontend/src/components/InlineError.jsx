// Inline error text — never an alert().
export default function InlineError({ message }) {
  if (!message) return null
  return (
    <p className="text-sm text-loss" role="alert">
      {message}
    </p>
  )
}
