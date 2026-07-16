import { Suspense, useEffect, useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'

const SPIN_END = 0.55
const YAW_AIM = Math.PI * 1.5
const YAW_REST_OFFSET = Math.PI / 2

// How far behind the measured eyepiece the camera settles at full dolly.
const EYE_STANDOFF = 1.35

// Driver value by which the camera has slid onto the scope's optical axis.
// Deliberately well before DOLLY_END: being on-axis is what keeps the glass
// concentric with the rifle's housing ring, and that has to be true while the
// rifle is still on screen (it fades out around 0.74–0.80).
const ALIGN_END = 0.67

// Camera finishes its dolly (t=1) at this driver value; it then holds while
// the end-bloom carries the circle to fullscreen and the text settles in.
const DOLLY_END = 0.88
const FULLSCREEN_START = 0.94

// Points sampled around the eyepiece rim to fit the on-screen circle. The rim
// is 608 verts; 48 reproduces the same centre/radius to 0.1px for a fraction
// of the work.
const RING_SAMPLES = 48

// awp.glb's lens cone is not concentric with the housing it sits in: the
// rifle's silver rim opening is offset from the glass and very slightly wider.
// The sight picture has to fill the RIM (that's the hole you look through),
// not the glass — otherwise a crescent of dark scope body shows between the
// two on the offset side. A bigger radius alone can't close it: measured from
// the glass's centre the rim's inner edge runs 142.8→162.8px, so any circle
// wide enough to cover the far side buries the rim on the near side.
//
// Measured off the render by least-squares-fitting the rim's inner edge (120
// radial samples) and comparing to the projected glass, at two zooms:
//   driver 0.711  r=66.0   Δ(-2.2,+2.9)px  ratio 1.0101
//   driver 0.762  r=151.1  Δ(-5.0,+7.1)px  ratio 1.0107
// The deltas scale with the radius, so it's a fixed offset in the model rather
// than parallax or a lighting artefact. Held as a fraction of the rim radius
// in the rim's own plane (the long-axis component came out 0, as a pure
// concentricity error should), so it survives any pose or zoom.
// Re-exporting awp.glb invalidates these — re-measure, don't nudge.
const BORE_OFFSET_U = 0.0332
const BORE_OFFSET_W = -0.0455
const BORE_SCALE = 1.0104

const lerp = (a, b, t) => a + (b - a) * t
const clamp01 = (t) => Math.min(1, Math.max(0, t))
const norm = (v, a, b) => clamp01((v - a) / (b - a))
const smooth = (t) => t * t * (3 - 2 * t)
const coverRadius = (cx, cy, w, h) =>
  Math.max(
    Math.hypot(cx, cy),
    Math.hypot(w - cx, cy),
    Math.hypot(cx, h - cy),
    Math.hypot(w - cx, h - cy)
  )

// Reusable scratch so the projection allocates nothing per frame.
const _v = new THREE.Vector3()
const _cA = new THREE.Vector3()
const _cB = new THREE.Vector3()
const _px = new Float64Array(RING_SAMPLES * 2)

function WeaponModel({ driver, scopeWrapRef, crosshairRef }) {
  const { scene } = useGLTF('/awp.glb')
  const pose = useRef()
  const float = useRef()
  const damped = useRef(null)

  const { model, scale, center, lensMesh, lensRings } = useMemo(() => {
    const box = new THREE.Box3().setFromObject(scene)
    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    scene.position.sub(center)

    // The scope is a separate mesh — authored as `Sphere002`, renamed by the
    // GLTF exporter (here: `Sphere_Material004_0`). Match the "sphere" stem
    // so it survives re-exports.
    let lensMesh = null
    scene.traverse((o) => {
      if (!lensMesh && o.isMesh && /sphere/i.test(o.name)) lensMesh = o
    })

    // That mesh is the scope tube, and — measured, not assumed — it is a
    // truncated cone: two flat rims of 608 verts each, joined down a long
    // axis. The rims are NOT the same size (local radius 1.0 at the objective,
    // 0.733 at the eyepiece), so any single radius taken from the bounding box
    // is wrong for at least one end, and a bounding sphere is wrong for both
    // (it circumscribes the tube's length).
    //
    // So don't derive a radius at all — keep the rims themselves. Each frame
    // we project the real rim verts and fit the circle to where they actually
    // land, which is the rendered glass by construction: taper, perspective
    // and off-axis view all fall out of it for free.
    let lensRings = null
    if (lensMesh) {
      const g = lensMesh.geometry
      if (!g.boundingBox) g.computeBoundingBox()
      const bb = g.boundingBox
      const sz = bb.getSize(new THREE.Vector3())

      // Long axis = the barrel; the other two span each rim's plane.
      let long = 'x'
      if (sz.y > sz.x && sz.y > sz.z) long = 'y'
      else if (sz.z > sz.x && sz.z > sz.y) long = 'z'
      const [u, w] = ['x', 'y', 'z'].filter((a) => a !== long)
      const mid = (bb.min[long] + bb.max[long]) / 2

      const pos = g.attributes.position
      const groups = [[], []]
      for (let i = 0; i < pos.count; i++) {
        const p = new THREE.Vector3().fromBufferAttribute(pos, i)
        groups[p[long] < mid ? 0 : 1].push(p)
      }

      if (groups[0].length >= RING_SAMPLES && groups[1].length >= RING_SAMPLES) {
        const centroid = (ring) =>
          ring
            .reduce((acc, q) => acc.add(q), new THREE.Vector3())
            .divideScalar(ring.length)
        // Walk the rim by angle so the samples are spread around it evenly
        // rather than clustering wherever the exporter happened to emit verts.
        const evenly = (ring) => {
          const sorted = [...ring].sort(
            (a, b) => Math.atan2(a[w], a[u]) - Math.atan2(b[w], b[u])
          )
          const out = []
          for (let i = 0; i < RING_SAMPLES; i++) {
            out.push(sorted[Math.floor((i * sorted.length) / RING_SAMPLES)])
          }
          return out
        }
        lensRings = groups.map((ring) => {
          const c = centroid(ring)
          const r =
            ring.reduce((acc, q) => acc + Math.hypot(q[u] - c[u], q[w] - c[w]), 0) /
            ring.length
          // Where the housing's rim opening sits, relative to this rim.
          const bore = c.clone()
          bore[u] += BORE_OFFSET_U * r
          bore[w] += BORE_OFFSET_W * r
          return { pts: evenly(ring), center: c, bore }
        })
      }
    }

    return { model: scene, scale: 20 / Math.max(size.x, size.y, size.z), center, lensMesh, lensRings }
  }, [scene])

  // Dev-only: expose R3F's frame-advance so the render loop can be stepped
  // for verification when the tab is backgrounded and rAF is paused.
  const advance = useThree((s) => s.advance)
  const camDbg = useThree((s) => s.camera)
  useEffect(() => {
    if (!import.meta.env.DEV) return
    window.__r3fAdvance = advance
    window.__lensMesh = lensMesh
    window.__scene = model
    window.__lensInfo = () => {
      if (!lensMesh || !lensRings) return { found: false }
      lensMesh.updateWorldMatrix(true, false)
      const m = lensMesh.matrixWorld
      const a = lensRings[0].center.clone().applyMatrix4(m)
      const b = lensRings[1].center.clone().applyMatrix4(m)
      const near = a.distanceTo(camDbg.position) < b.distanceTo(camDbg.position) ? 0 : 1
      return {
        found: true,
        name: lensMesh.name,
        samples: RING_SAMPLES,
        eyepieceRing: near,
        eyepieceWorld: (near ? b : a).toArray().map((v) => +v.toFixed(2)),
        camDist: +(near ? b : a).distanceTo(camDbg.position).toFixed(2),
        driver: +driver.current.progress.toFixed(3),
      }
    }
  }, [advance, camDbg, lensMesh, lensRings, model])

  useFrame((state, delta) => {
    const p = driver.current.progress
    const cam = state.camera

    let yaw
    let pitch = 0
    let roll = 0
    let posX
    let posY
    let camZ
    let camY = 1.2
    let camX = 0
    let lookY = 0
    let shakeX = 0
    let shakeY = 0
    let fov = 38

    const bell = Math.sin(norm(p, 0.35, 0.65) * Math.PI)
    const scaleMul = 1 - 0.25 * bell

    if (p < SPIN_END) {
      const t = smooth(norm(p, 0, SPIN_END))
      yaw = lerp(YAW_AIM - Math.PI * 2 + YAW_REST_OFFSET, YAW_AIM, t)
      pitch = Math.sin(t * Math.PI) * 0.1
      roll = -0.12 * (1 - t)
      posX = lerp(4.2, 0, t)
      posY = lerp(-2.8, 0, t)
      camZ = lerp(26, 18.5, t)
    } else {
      // Scope dive — the camera's position/aim are retargeted onto the
      // MEASURED eyepiece further below (the lens has to be located from the
      // posed geometry first). Here we only hold the rifle still, apply the
      // settle shake, and narrow the FOV. Completes (t=1) at DOLLY_END.
      const t = norm(p, SPIN_END, DOLLY_END)
      const tFov = smooth(smooth(t))

      yaw = YAW_AIM
      posX = 0
      posY = 0

      const shake = Math.max(0, 1 - t / 0.15)
      const sf = state.clock.elapsedTime * 30
      shakeX = Math.sin(sf) * 0.045 * shake
      shakeY = Math.cos(sf * 1.13) * 0.03 * shake

      fov = lerp(38, 12, tFov)
    }

    if (!damped.current) {
      damped.current = {
        yaw, pitch, roll, posX, posY,
        camX, camY, camZ,
        lookX: 0, lookY, lookZ: 0,
        fov, scaleMul,
      }
    }
    const s = damped.current
    const k = 1 - Math.exp(-14 * Math.min(delta, 0.1))
    s.yaw += (yaw - s.yaw) * k
    s.pitch += (pitch - s.pitch) * k
    s.roll += (roll - s.roll) * k
    s.posX += (posX - s.posX) * k
    s.posY += (posY - s.posY) * k
    s.fov += (fov - s.fov) * k
    s.scaleMul += (scaleMul - s.scaleMul) * k
    // Spin phase drives the camera from fixed values; the scope phase
    // retargets it onto the measured eyepiece once the pose is applied.
    if (p < SPIN_END) {
      s.camX += (camX - s.camX) * k
      s.camY += (camY - s.camY) * k
      s.camZ += (camZ - s.camZ) * k
      s.lookY += (lookY - s.lookY) * k
    }

    if (pose.current) {
      pose.current.rotation.set(s.pitch, -Math.PI / 2 + s.yaw, s.roll)
      pose.current.scale.setScalar(scale * s.scaleMul)
    }

    if (float.current) {
      const idle = 1 - clamp01(p * 4)
      const t = state.clock.elapsedTime
      float.current.position.x = s.posX
      float.current.position.y = s.posY + Math.sin(t * 1.2) * 0.22 * idle
      float.current.rotation.z = Math.sin(t * 0.7) * 0.02 * idle
    }

    // ── Locate the REAL eyepiece from the scope mesh (pose is now applied) ──
    // Both rims in world space; the eyepiece is whichever is nearer the camera
    // — that's the end you look into. Measured from the geometry every frame,
    // so the camera below dives at the ACTUAL glass, not a guessed point.
    let eye = null
    let ring = null
    if (lensMesh && lensRings) {
      lensMesh.updateWorldMatrix(true, false)
      const m = lensMesh.matrixWorld
      _cA.copy(lensRings[0].center).applyMatrix4(m)
      _cB.copy(lensRings[1].center).applyMatrix4(m)
      const aNear =
        _cA.distanceToSquared(cam.position) < _cB.distanceToSquared(cam.position)
      eye = aNear ? _cA : _cB
      ring = aNear ? lensRings[0] : lensRings[1]
    }

    // Retarget the scope dive onto the measured eyepiece. Without this the
    // camera aims at a hardcoded point that misses the real glass by enough
    // to push it outside the narrowed FOV entirely.
    //
    // Line up with the optical axis (ALIGN_END) well before finishing the push
    // in (DOLLY_END). Sharing one ramp for both leaves the camera off-axis for
    // most of the dive, and off-axis the rifle's housing ring — which sits at a
    // different depth than the glass — drifts sideways from the lens and opens
    // a dark crescent of bore between the rim and the sight picture. Once camX/Y
    // and lookX/Y/Z all sit on the eyepiece, the camera is on the axis at any
    // dolly distance and the two stay concentric.
    if (eye && p >= SPIN_END) {
      const tAlign = smooth(norm(p, SPIN_END, ALIGN_END))
      const tIn = smooth(norm(p, SPIN_END, DOLLY_END))
      s.camX += (lerp(0, eye.x, tAlign) - s.camX) * k
      s.camY += (lerp(1.2, eye.y, tAlign) - s.camY) * k
      s.camZ += (lerp(18.5, eye.z + EYE_STANDOFF, tIn) - s.camZ) * k
      s.lookX += (lerp(0, eye.x, tAlign) - s.lookX) * k
      s.lookY += (lerp(1.2, eye.y, tAlign) - s.lookY) * k
      s.lookZ += (lerp(0, eye.z, tAlign) - s.lookZ) * k
    } else {
      s.lookX += (0 - s.lookX) * k
      s.lookZ += (0 - s.lookZ) * k
    }

    cam.position.set(s.camX + shakeX, s.camY + shakeY, s.camZ)
    cam.lookAt(s.lookX, s.lookY, s.lookZ)
    cam.fov = s.fov
    cam.updateProjectionMatrix()
    cam.updateMatrixWorld()

    // ── Project the REAL rim and drive the CSS scope circle ──
    // Transform each cached rim vert by the mesh's CURRENT world matrix (pose
    // rotation, scale and float all baked in) and project it through the
    // CURRENT camera — the exact matrices this frame renders with. Fitting the
    // circle to where those verts actually land means it cannot drift off the
    // glass: no aperture guess, no fudge factor, no assumption that the tube
    // is a cylinder or that we're looking straight down it.
    //
    // Past DOLLY_END the circle lerps out to a guaranteed fullscreen cover and
    // settles to screen centre, so the reveal always lands square even if the
    // dolly stops short of the glass.
    if (ring && scopeWrapRef?.current) {
      const wrap = scopeWrapRef.current
      const wrapRect = wrap.getBoundingClientRect()
      const canvasRect = state.gl.domElement.getBoundingClientRect()
      const w = wrapRect.width || state.size.width
      const h = wrapRect.height || state.size.height
      const canvasW = canvasRect.width || state.size.width
      const canvasH = canvasRect.height || state.size.height
      const offX = canvasRect.left - wrapRect.left
      const offY = canvasRect.top - wrapRect.top

      const m = lensMesh.matrixWorld
      let sx = 0
      let sy = 0
      for (let i = 0; i < RING_SAMPLES; i++) {
        _v.copy(ring.pts[i]).applyMatrix4(m).project(cam)
        const x = offX + (_v.x * 0.5 + 0.5) * canvasW
        const y = offY + (-_v.y * 0.5 + 0.5) * canvasH
        _px[i * 2] = x
        _px[i * 2 + 1] = y
        sx += x
        sy += y
      }
      // Radius: fit to the rim verts about their own projected centroid, then
      // open out to the housing's opening.
      const rimCx = sx / RING_SAMPLES
      const rimCy = sy / RING_SAMPLES
      let radius = 0
      for (let i = 0; i < RING_SAMPLES; i++) {
        radius += Math.hypot(_px[i * 2] - rimCx, _px[i * 2 + 1] - rimCy)
      }
      radius = (radius / RING_SAMPLES) * BORE_SCALE

      // Centre on the housing's opening rather than the glass, so no crescent
      // of scope body shows between the rim and the sight picture.
      _v.copy(ring.bore).applyMatrix4(m).project(cam)
      let cx = offX + (_v.x * 0.5 + 0.5) * canvasW
      let cy = offY + (-_v.y * 0.5 + 0.5) * canvasH

      const fs = smooth(norm(p, DOLLY_END, FULLSCREEN_START))
      if (fs > 0) {
        const centerCx = offX + canvasW / 2
        const centerCy = offY + canvasH / 2
        cx = lerp(cx, centerCx, fs)
        cy = lerp(cy, centerCy, fs)
        radius = lerp(radius, coverRadius(centerCx, centerCy, w, h) + 8, fs)
      }

      if (Number.isFinite(cx) && Number.isFinite(cy) && Number.isFinite(radius)) {
        if (p >= FULLSCREEN_START) {
          wrap.style.clipPath = 'inset(0)'
          wrap.style.webkitClipPath = 'inset(0)'
        } else {
          const clip = `circle(${radius}px at ${cx}px ${cy}px)`
          wrap.style.clipPath = clip
          wrap.style.webkitClipPath = clip
        }

        // The reticle IS the circle — same centre, same diameter — so its own
        // round clip keeps the hairlines inside the glass and off the black
        // surround at every size. GSAP owns only its opacity.
        const crosshair = crosshairRef?.current
        if (crosshair) {
          crosshair.style.left = `${cx}px`
          crosshair.style.top = `${cy}px`
          crosshair.style.width = `${radius * 2}px`
          crosshair.style.height = `${radius * 2}px`
        }
      }
    }
  })

  return (
    <group ref={float}>
      <group ref={pose} scale={scale}>
        <primitive object={model} />
      </group>
    </group>
  )
}

useGLTF.preload('/awp.glb')

export default function WeaponCanvas({ driver, scopeWrapRef, crosshairRef }) {
  return (
    <Canvas
      camera={{ fov: 38, position: [0, 1.2, 26], near: 0.1, far: 200 }}
      dpr={[1, 1.75]}
      gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
    >
      <ambientLight intensity={1.2} />
      <directionalLight position={[6, 8, 8]} intensity={3.0} color="#ffffff" />
      <directionalLight position={[8, 2, 10]} intensity={1.8} color="#ffffff" />
      <directionalLight position={[-8, 3, -6]} intensity={1.0} color="#c8dce6" />
      <directionalLight position={[0, 10, 0]} intensity={1.2} color="#ffffff" />
      <pointLight position={[-6, -2, 6]} intensity={200} color="#E8450A" distance={40} />
      <Suspense fallback={null}>
        <WeaponModel driver={driver} scopeWrapRef={scopeWrapRef} crosshairRef={crosshairRef} />
      </Suspense>
    </Canvas>
  )
}
