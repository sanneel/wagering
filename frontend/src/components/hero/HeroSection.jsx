import { Suspense, lazy, useLayoutEffect, useRef } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import HeroCopy from './HeroCopy'

// The WebGL canvas is heavy and desktop-only; load it lazily so mobile and
// the initial paint aren't blocked by three.js.
const WeaponCanvas = lazy(() => import('./WeaponCanvas'))

gsap.registerPlugin(ScrollTrigger)

if (import.meta.env.DEV) {
  window.__gsap = gsap
  window.__ScrollTrigger = ScrollTrigger
}

export default function HeroSection({ onFaceit, onDemo, demoBusy, demoErr }) {
  const sectionRef = useRef(null)
  const driver = useRef({ progress: 0 })
  // The 3D scope circle is projected from the real lens mesh each frame
  // (see WeaponCanvas); this ref hands the DOM node to that render loop so
  // it can drive clip-path directly, glued to the glass.
  const scopeWrapRef = useRef(null)
  const crosshairRef = useRef(null)

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const mm = gsap.matchMedia()

      mm.add(
        {
          full: '(min-width: 1024px) and (prefers-reduced-motion: no-preference)',
          compact: '(max-width: 1023px) and (prefers-reduced-motion: no-preference)',
        },
        (mmCtx) => {
          const { full, compact } = mmCtx.conditions

          if (full || compact) {
            gsap.from('.js-copy > *', {
              y: 24,
              autoAlpha: 0,
              duration: 0.8,
              stagger: 0.07,
              ease: 'power3.out',
            })
          }

          if (!full) return 

          const tl = gsap.timeline({
            defaults: { ease: 'none' },
            scrollTrigger: {
              trigger: sectionRef.current,
              start: 'top top',
              end: '+=280%',
              scrub: 0.8,
              pin: true,
              anticipatePin: 1,
            },
          })

          // ── Phase 1: 3D weapon driver ──
          // Drives the whole 3D choreography. Spin owns driver 0→0.55
          // (timeline 0→~0.50), the scope dive owns 0.55→1 (timeline
          // ~0.50→0.90). The camera completes its dolly at driver 0.85 and
          // the projected lens circle blooms to fullscreen by driver 1.
          tl.to(driver.current, { progress: 1, duration: 0.9 }, 0)

          // Hero copy fades out early
          tl.to('.js-copy', { autoAlpha: 0, y: -50, duration: 0.08 }, 0.02)
          tl.to('.js-hint', { autoAlpha: 0, duration: 0.05 }, 0.02)

          // Warm glow behind the rifle mid-rotation
          tl.fromTo('.js-zoomglow', { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.12 }, 0.08)
          tl.to('.js-zoomglow', { autoAlpha: 0, duration: 0.08 }, 0.40)

          // Floor glow fades
          tl.to('.js-floor', { opacity: 0, duration: 0.15 }, 0.38)

          // ── Graffiti tags — spray-painted in sync with the spin ──
          // Each tag lands from a different corner, arriving rotated in the
          // direction of the rifle's turn and settling to its own crooked
          // hand-tacked tilt (-6°, +5°, -3°). The numeral spray-pops from a
          // blurred oversize, the scribble underline draws on, and the tag
          // tumbles away as the next beat arrives — the whole thing feels
          // choreographed with the weapon's motion instead of sitting on top.
          const stepTweens = (cls, startAt, exitAt, from, to, exitTo) => {
            tl.fromTo(cls, from, { ...to, duration: 0.06, ease: 'back.out(1.7)' }, startAt)
            tl.fromTo(
              `${cls} .js-step-num`,
              { scale: 1.35, filter: 'blur(8px)', autoAlpha: 0 },
              { scale: 1, filter: 'blur(0px)', autoAlpha: 1, duration: 0.05, ease: 'power3.out' },
              startAt + 0.01
            )
            tl.fromTo(
              `${cls} .js-step-scribble`,
              { strokeDashoffset: 260 },
              { strokeDashoffset: 0, duration: 0.07, ease: 'power2.out' },
              startAt + 0.02
            )
            tl.to(cls, { ...exitTo, duration: 0.04, ease: 'power2.in' }, exitAt)
          }
          stepTweens(
            '.js-step1', 0.06, 0.17,
            { autoAlpha: 0, x: -90, y: 12, rotate: -22, scale: 0.86 },
            { autoAlpha: 1, x: 0, y: 0, rotate: -6, scale: 1 },
            { autoAlpha: 0, x: -60, y: -20, rotate: -18 }
          )
          stepTweens(
            '.js-step2', 0.21, 0.32,
            { autoAlpha: 0, x: 110, y: -8, rotate: 22, scale: 0.86 },
            { autoAlpha: 1, x: 0, y: 0, rotate: 5, scale: 1 },
            { autoAlpha: 0, x: 70, y: -14, rotate: 16 }
          )
          stepTweens(
            '.js-step3', 0.36, 0.47,
            { autoAlpha: 0, x: -40, y: 80, rotate: -18, scale: 0.86 },
            { autoAlpha: 1, x: 0, y: 0, rotate: -3, scale: 1 },
            { autoAlpha: 0, x: 30, y: -50, rotate: 12 }
          )

          // ── Phase 2: Scope reveal (clip-path is projection-driven) ──
          // The scope circle is GLUED to the real 3D lens by WeaponCanvas,
          // which projects the lens mesh to screen space and writes clip-path
          // every frame. So GSAP here only handles the timed layers ON that
          // circle — opacity, focus-pull blur, black surround, reticle. It
          // never touches clip-path, so nothing can desync from the 3D.
          //
          // The dive runs driver 0.55→0.85 ≈ timeline 0.50→0.77; the
          // projected circle starts as a small speck over the real eyepiece
          // and grows with the camera, then blooms past the screen edges on
          // its own before the final copy lands.
          // Sight picture fades up at timeline 0.45 ≈ driver 0.50 — while the
          // rifle is still turning, before it comes round to face us. The clip
          // circle is fitted to the real lens rim every frame, so even at this
          // oblique angle the picture lands inside the glass and rides the
          // rotation in; there's nothing special about the head-on pose.
          tl.fromTo(
            '.js-scopeview',
            { autoAlpha: 0 },
            { autoAlpha: 1, duration: 0.05, ease: 'power1.out' },
            0.45
          )

          // Focus pull - starts as a blurred smudge in the turning glass and
          // resolves by the time the zoom has settled, just before the reticle.
          tl.fromTo(
            '.js-scopeshot',
            { filter: 'blur(30px) brightness(0.35) saturate(0.5)', scale: 1.3 },
            { filter: 'blur(0px) brightness(1) saturate(1.05)', scale: 1, duration: 0.22, ease: 'power2.out' },
            0.45
          )

          // Black surround fades in after the sight picture has settled into the scope.
          tl.fromTo(
            '.js-scopeblack',
            { autoAlpha: 0 },
            { autoAlpha: 1, duration: 0.05, ease: 'power1.in' },
            0.66
          )
          // 3D rifle steps aside so the sight picture is unobstructed.
          tl.to('.js-weapon', { autoAlpha: 0, duration: 0.05 }, 0.67)

          // Reticle. WeaponCanvas sizes and centres it on the live projected
          // circle every frame, so it always sits inside the glass; GSAP only
          // fades it. It must be fully gone by timeline 0.80 — that is driver
          // ≈0.89, right where the circle starts blooming past the screen
          // edges — otherwise the hairlines ride the bloom out and end up
          // stranded across the fullscreen shot.
          tl.fromTo(
            '.js-crosshair',
            { autoAlpha: 0 },
            { autoAlpha: 1, duration: 0.05, ease: 'power2.out' },
            0.68
          )
          tl.to('.js-crosshair', { autoAlpha: 0, duration: 0.03, ease: 'power2.in' }, 0.77)

          // Phase 3: Fullscreen
          // Lens vignette clears before the clip is released to fullscreen.
          tl.to('.js-lensvignette', { autoAlpha: 0, duration: 0.08 }, 0.78)
          // Scrim for the end copy — only once the circle has gone fullscreen.
          tl.fromTo('.js-scopegrad', { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.05 }, 0.86)
          // ── Phase 4: Fullscreen CS2 — text settles in once the circle has
          // bloomed past the screen edges (driver 1 ≈ timeline 0.90) ──
          tl.fromTo(
            '.js-scopelabel',
            { autoAlpha: 0, y: 30 },
            { autoAlpha: 1, y: 0, duration: 0.05, ease: 'power3.out' },
            0.90
          )
          tl.fromTo(
            '.js-scopeheading',
            { autoAlpha: 0, y: 40 },
            { autoAlpha: 1, y: 0, duration: 0.06, ease: 'power3.out' },
            0.92
          )
          tl.fromTo(
            '.js-scopebody',
            { autoAlpha: 0, y: 24 },
            { autoAlpha: 1, y: 0, duration: 0.05, ease: 'power3.out' },
            0.94
          )

          // Hold the fullscreen view so it doesn't vanish instantly
          tl.to({}, { duration: 0.04 }, 0.97)

          // Scroll progress rail
          const total = tl.duration()
          tl.fromTo(
            '.js-progressfill',
            { scaleY: 0 },
            { scaleY: 1, duration: total, ease: 'none' },
            0
          )
          tl.to('.js-progresstrack', { autoAlpha: 0, duration: 0.06 }, total - 0.12)
        }
      )
    }, sectionRef)

    return () => ctx.revert()
  }, [])

  return (
    <section
      ref={sectionRef}
      className="relative h-screen overflow-hidden bg-graphite-950"
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(120% 90% at 60% 42%, transparent 52%, rgba(0,0,0,0.55) 100%)',
        }}
      />
      <div className="js-floor pointer-events-none absolute left-1/2 top-[56%] h-[24rem] w-[72rem] -translate-x-1/2 rounded-[100%] bg-accent/[0.08] blur-3xl" />
      <div
        className="js-zoomglow pointer-events-none absolute inset-0 opacity-0"
        style={{
          background:
            'radial-gradient(48% 56% at 50% 48%, rgba(232,69,10,0.20) 0%, rgba(232,69,10,0.06) 46%, transparent 74%)',
        }}
      />

      <div className="js-weapon pointer-events-none absolute inset-0 hidden lg:block">
        <Suspense fallback={<WeaponPoster />}>
          <WeaponCanvas driver={driver} scopeWrapRef={scopeWrapRef} crosshairRef={crosshairRef} />
        </Suspense>
      </div>
      <div className="lg:hidden">
        <WeaponPoster />
      </div>

      <div className="relative z-10 mx-auto flex h-full max-w-6xl items-center px-6">
        <HeroCopy
          onFaceit={onFaceit}
          onDemo={onDemo}
          demoBusy={demoBusy}
          demoErr={demoErr}
        />
      </div>

      {/* Graffiti tags — spray-painted onto the scene mid-spin, each in a
          different corner with its own hand-tacked tilt. Positioned so the
          rifle never covers the copy. */}
      <StepCard
        n="01"
        title="Connect FACEIT"
        body="Sign in with your FACEIT account. No passwords stored."
        className="js-step1 left-[6%] top-[18%]"
      />
      <StepCard
        n="02"
        title="Lock your stake"
        body="Both stakes into escrow before the server starts."
        className="js-step2 right-[6%] top-[26%]"
      />
      <StepCard
        n="03"
        title="Winner takes it"
        body="Play the 1v1. The pot, minus 10% rake, lands in seconds."
        className="js-step3 bottom-[16%] left-[8%]"
      />

      {/* ── Scope view overlay ── */}
      <div
        className="js-scopeview pointer-events-none absolute left-1/2 top-0 z-20 hidden -translate-x-1/2 opacity-0 lg:block"
        style={{ width: '100vw', height: '100vh' }}
      >
        {/* Solid black surround — starts transparent so the small preview
            disc appears to sit inside the 3D scope's lens; GSAP fades it in
            once the 3D weapon has stepped aside. */}
        <div className="js-scopeblack absolute inset-0 bg-black opacity-0" />

        <div
          ref={scopeWrapRef}
          className="js-scopewrap absolute inset-0 overflow-hidden"
          style={{ clipPath: 'circle(0px at 50% 50%)' }}
        >
          <img
            src="/scope-shot.jpg"
            alt="CS2 Background"
            draggable={false}
            className="js-scopeshot h-full w-full select-none object-cover object-center"
          />
          <div
            className="js-lensvignette absolute inset-0"
            style={{
              background:
                'radial-gradient(circle 34vmin at 50% 50%, transparent 62%, rgba(0,0,0,0.55) 100%), rgba(180,140,80,0.07)',
            }}
          />
        </div>

        {/* Reticle. Sized and centred on the live projected circle by
            WeaponCanvas; `rounded-full overflow-hidden` then trims the
            hairlines to exactly that circle, so they read as etched on the
            glass and never spill onto the black surround. Starts at 0 so
            nothing flashes before the first projected frame lands. */}
        <div
          ref={crosshairRef}
          className="js-crosshair absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-full opacity-0"
          style={{ width: 0, height: 0 }}
        >
          <div
            className="absolute left-0 top-1/2 w-full -translate-y-[0.5px]"
            style={{ height: '1px', background: 'rgba(255,255,255,0.5)' }}
          />
          <div
            className="absolute left-1/2 top-0 h-full -translate-x-[0.5px]"
            style={{ width: '1px', background: 'rgba(255,255,255,0.5)' }}
          />
          <div
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white"
            style={{ width: '4px', height: '4px' }}
          />
        </div>

        <div className="absolute inset-0 flex flex-col items-center justify-end pb-[14vh]">
          {/* Scrim for the end copy. NOT clipped to the scope circle, so it
              must stay at 0 until the reveal is basically over — the sight
              picture now fades up while the rifle is still spinning, and this
              would otherwise darken the whole stage from that point on. */}
          <div
            className="js-scopegrad absolute inset-0 opacity-0"
            style={{
              background:
                'linear-gradient(to bottom, transparent 30%, rgba(6,7,9,0.3) 55%, rgba(6,7,9,0.85) 100%)',
            }}
          />
          <div className="relative text-center">
            <p className="js-scopelabel text-[10px] font-medium uppercase tracking-[0.3em] text-steel-400 opacity-0">
              Match settled
            </p>
            <h2 className="js-scopeheading mt-2 font-display text-4xl font-semibold uppercase leading-none tracking-tight text-white opacity-0 xl:text-6xl">
              Winner takes
              <br />
              <span className="text-accent">the pot.</span>
            </h2>
            <p className="js-scopebody mx-auto mt-4 max-w-xs text-sm leading-relaxed text-steel-300 opacity-0">
              Both stakes in escrow from lock to last kill. 10% rake — the
              rest pays out in seconds.
            </p>
          </div>
        </div>
      </div>

      <div className="js-progresstrack pointer-events-none absolute right-3 top-1/2 z-30 h-[38vh] w-[3px] -translate-y-1/2 overflow-hidden rounded-full bg-white/10 hidden lg:block">
        <div className="js-progressfill h-full w-full origin-top scale-y-0 rounded-full bg-accent" />
      </div>

      <div className="js-hint absolute inset-x-0 bottom-6 z-10 flex flex-col items-center gap-1 text-steel-500">
        <span className="text-[10px] uppercase tracking-[0.3em]">Scroll</span>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M3 6l5 5 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    </section>
  )
}

// Graffiti tag — hand-tagged step callout: oversized italic numeral with a
// paint drip, a scribbled underline that draws on, uppercase stencil title,
// no box. Reads like something sprayed onto the stage rather than a card.
// Base rotation (`tilt`) gives each tag its own crooked hand-tacked feel.
function StepCard({ n, title, body, className }) {
  // GSAP owns the rotation; base tilt is written by the timeline end state.
  return (
    <div
      className={`pointer-events-none absolute z-10 hidden w-[22rem] opacity-0 lg:block ${className}`}
    >
      {/* Big italic numeral with a paint drip. text-stroke gives it that
          spray-can outline; the offset shadow is the classic tag shadow. */}
      <div className="relative inline-block leading-none">
        <span
          className="js-step-num relative block font-display text-[10.5rem] font-black italic leading-[0.85] text-accent"
          style={{
            textShadow:
              '5px 5px 0 rgba(0,0,0,0.85), 10px 10px 0 rgba(232,69,10,0.15)',
            WebkitTextStroke: '1px rgba(255,255,255,0.12)',
            letterSpacing: '-0.04em',
          }}
        >
          {n}
        </span>
        {/* Paint drip trailing off the numeral */}
        <span
          className="absolute h-12 w-[4px] bg-accent"
          style={{
            left: '58%',
            top: '86%',
            boxShadow: '0 7px 0 -1px #E8450A, 0 14px 0 -2px #E8450A',
            transform: 'rotate(2deg)',
          }}
        />
      </div>

      {/* Scribbled underline — GSAP draws on the stroke as the tag appears */}
      <svg
        className="mt-1 block w-56 overflow-visible"
        viewBox="0 0 240 20"
        fill="none"
        aria-hidden="true"
      >
        <path
          className="js-step-scribble"
          d="M2 12 C 30 4, 60 18, 92 8 S 150 18, 180 6 S 220 16, 238 10"
          stroke="#E8450A"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray="260"
          strokeDashoffset="260"
          style={{
            filter: 'drop-shadow(0 0 6px rgba(232,69,10,0.6))',
          }}
        />
      </svg>

      {/* Stencil title — condensed italic, aggressive tracking */}
      <h3
        className="mt-3 font-display text-[2.4rem] font-black italic uppercase leading-[0.95] text-white"
        style={{
          textShadow: '2px 2px 0 rgba(0,0,0,0.9)',
          letterSpacing: '-0.01em',
        }}
      >
        {title}
      </h3>
      <p
        className="mt-2 max-w-[18rem] text-sm leading-snug text-steel-300"
        style={{ textShadow: '1px 1px 0 rgba(0,0,0,0.8)' }}
      >
        {body}
      </p>
    </div>
  )
}

function WeaponPoster() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center lg:justify-end">
      <img
        src="/awp.png"
        alt="AWP Asiimov, 1v1wager edition"
        draggable={false}
        className="w-[min(86vw,60rem)] select-none opacity-90"
        style={{ filter: 'drop-shadow(0 40px 80px rgba(0,0,0,0.55))' }}
      />
    </div>
  )
}
