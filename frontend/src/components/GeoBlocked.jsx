export default function GeoBlocked() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
      <h1 className="text-2xl font-semibold text-ink">
        Not available in your region
      </h1>
      <p className="mt-3 max-w-md text-sm text-muted">
        1v1wager isn&apos;t available where you are, or you appear to be
        connecting through a VPN or proxy. If you believe this is a mistake,
        turn off any VPN and reload.
      </p>
    </div>
  )
}
