import { useEffect, useState } from 'react'

// A one-time 18+ confirmation. Real-money wagering is age-restricted; this is a
// baseline gate (not identity verification — that's KYC at withdrawal). The
// choice is remembered so it isn't shown on every visit.
const KEY = 'ageConfirmed'

export default function AgeGate({ children }) {
  const [confirmed, setConfirmed] = useState(true)

  useEffect(() => {
    setConfirmed(localStorage.getItem(KEY) === 'true')
  }, [])

  if (confirmed) return children

  return (
    <>
      {children}
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-graphite-950/95 px-6 backdrop-blur">
        <div className="w-full max-w-md rounded-2xl border border-line-dark bg-graphite-900 p-8 text-center">
          <div className="font-display text-2xl font-semibold text-white">
            Are you 18 or older?
          </div>
          <p className="mt-3 text-sm leading-relaxed text-steel-400">
            1v1wager is a real-money skill-wagering platform. You must be 18+ (or
            the legal age where you live) and in a permitted region to play.
            Wagering involves financial risk — only stake what you can afford to
            lose.
          </p>
          <div className="mt-6 flex flex-col gap-3">
            <button
              type="button"
              onClick={() => {
                localStorage.setItem(KEY, 'true')
                setConfirmed(true)
              }}
              className="w-full rounded-md bg-accent px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-dark"
            >
              I&apos;m 18 or older — enter
            </button>
            <a
              href="https://www.begambleaware.org/"
              className="w-full rounded-md border border-line-dark px-4 py-3 text-sm font-medium text-steel-300 transition-colors hover:text-white"
            >
              I&apos;m under 18 — leave
            </a>
          </div>
          <p className="mt-4 text-[11px] leading-relaxed text-steel-600">
            By entering you agree to the Terms and confirm you are not in a
            restricted region.
          </p>
        </div>
      </div>
    </>
  )
}
