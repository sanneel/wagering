import { Suspense, useEffect, useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'

const SPIN_END = 0.55
const YAW_AIM = Math.PI * 1.5
const YAW_REST_OFFSET = Math.PI / 2

// How far behind the measured eyepiece the camera settles at full dolly.
const EYE_STANDOFF = 1.35

// Camera finishes its dolly (t=1) at this driver value; it then holds while
// the end-bloom carries the circle to fullscreen and the text settles in.
const DOLLY_END = 0.88
const FULLSCREEN_START = 0.94

// The scope mesh gives us the outside of the tube end. Use the inner glass
// area for the sight picture so it sits inside the model instead of covering
// the full orange ring.
const LENS_FILL = 0.68

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

// Reusable scratch objects so the projection allocates nothing per frame.
const _endA = new THREE.Vector3()
const _endB = new THREE.Vector3()
const _scale = new THREE.Vector3()
const _right = new THREE.Vector3()
const _vC = new THREE.Vector3()
const _vR = new THREE.Vector3()

function WeaponModel({ driver, scopeWrapRef, crosshairRef }) {
  const { scene } = useGLTF('/awp.glb')
  const pose = useRef()
  const float = useRef()
  const damped = useRef(null)

  const { model, scale, center, lensMesh, lensLocal } = useMemo(() => {
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

    // That mesh is the whole scope TUBE, not a flat lens: measured local
    // extents are ~4.9 long by ~0.85 square. So its bounding *sphere* would
    // circumscribe the tube's LENGTH (radius ≈ half of 4.9) — wildly too big
    // for the glass. Instead derive the real aperture from the local bbox:
    // the long axis is the tube's barrel, the glass is the disc at either
    // end-cap, and the aperture radius is half the cross-section. We cache
    // both end-caps in LOCAL space and each frame pick whichever is nearer
    // the camera — that's the eyepiece you're looking into.
    let lensLocal = null
    if (lensMesh) {
      const g = lensMesh.geometry
      if (!g.boundingBox) g.computeBoundingBox()
      const bb = g.boundingBox
      const sz = bb.getSize(new THREE.Vector3())
      const mid = bb.getCenter(new THREE.Vector3())

      let long = 'x'
      if (sz.y > sz.x && sz.y > sz.z) long = 'y'
      else if (sz.z > sz.x && sz.z > sz.y) long = 'z'
      const cross = ['x', 'y', 'z'].filter((a) => a !== long)

      const endA = mid.clone()
      endA[long] = bb.min[long]
      const endB = mid.clone()
      endB[long] = bb.max[long]
      // Half the mean cross-section = the aperture radius.
      const radius = (sz[cross[0]] + sz[cross[1]]) / 4

      lensLocal = { endA, endB, radius }
    }

    return { model: scene, scale: 20 / Math.max(size.x, size.y, size.z), center, lensMesh, lensLocal }
  }, [scene])

  // Dev-only: expose R3F's frame-advance so the render loop can be stepped
  // for verification when the tab is backgrounded and rAF is paused.
  const advance = useThree((s) => s.advance)
  useEffect(() => {
    if (!import.meta.env.DEV) return
    window.__r3fAdvance = advance
    window.__lensInfo = (camPos) => {
      if (!lensMesh || !lensLocal) return { found: false }
      lensMesh.updateWorldMatrix(true, false)
      const m = lensMesh.matrixWorld
      const a = lensLocal.endA.clone().applyMatrix4(m)
      const b = lensLocal.endB.clone().applyMatrix4(m)
      const s = new THREE.Vector3().setFromMatrixScale(m)
      return {
        found: true,
        name: lensMesh.name,
        localRadius: +lensLocal.radius.toFixed(3),
        worldScale: +Math.max(s.x, s.y, s.z).toFixed(3),
        worldRadius: +(lensLocal.radius * Math.max(s.x, s.y, s.z)).toFixed(3),
        endA: a.toArray().map((v) => +v.toFixed(2)),
        endB: b.toArray().map((v) => +v.toFixed(2)),
        driver: +driver.current.progress.toFixed(3),
      }
    }
  }, [advance, lensMesh, model])

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

    // ── Measure the REAL eyepiece from the scope mesh (pose is now applied) ──
    // The tube's two end-caps in world space; the eyepiece is whichever is
    // nearer the camera. This is measured from the geometry every frame, so
    // the camera below dives at the ACTUAL glass rather than a guessed point.
    let eye = null
    let eyeRadius = 0
    if (lensMesh && lensLocal) {
      lensMesh.updateWorldMatrix(true, false)
      const m = lensMesh.matrixWorld
      _endA.copy(lensLocal.endA).applyMatrix4(m)
      _endB.copy(lensLocal.endB).applyMatrix4(m)
      eye =
        _endA.distanceToSquared(cam.position) < _endB.distanceToSquared(cam.position)
          ? _endA
          : _endB
      _scale.setFromMatrixScale(m)
      eyeRadius = lensLocal.radius * Math.max(_scale.x, _scale.y, _scale.z) * LENS_FILL
    }

    // Retarget the scope dive onto the measured eyepiece. Without this the
    // camera aims at a hardcoded point that misses the real glass by enough
    // to push it outside the narrowed FOV entirely.
    if (eye && p >= SPIN_END) {
      const tIn = smooth(norm(p, SPIN_END, DOLLY_END))
      s.camX += (lerp(0, eye.x, tIn) - s.camX) * k
      s.camY += (lerp(1.2, eye.y, tIn) - s.camY) * k
      s.camZ += (lerp(18.5, eye.z + EYE_STANDOFF, tIn) - s.camZ) * k
      s.lookX += (lerp(0, eye.x, tIn) - s.lookX) * k
      s.lookY += (lerp(1.2, eye.y, tIn) - s.lookY) * k
      s.lookZ += (lerp(0, eye.z, tIn) - s.lookZ) * k
    } else {
      s.lookX += (0 - s.lookX) * k
      s.lookZ += (0 - s.lookZ) * k
    }

    cam.position.set(s.camX + shakeX, s.camY + shakeY, s.camZ)
    cam.lookAt(s.lookX, s.lookY, s.lookZ)
    cam.fov = s.fov
    cam.updateProjectionMatrix()
    cam.updateMatrixWorld()

    // ── Project the REAL lens geometry and drive the CSS scope circle ──
    // Take `Sphere002`'s cached local bounding sphere, transform it by the
    // mesh's CURRENT world matrix (so pose rotation/scale/float are all
    // baked in), and project it through the CURRENT camera. Both are the
    // exact matrices this frame renders with, so the circle is glued to the
    // rendered glass pixel-for-pixel through any FOV or damping.
    //
    // Radius: offset the world centre along the camera's RIGHT vector by the
    // sphere's world radius and project that too — the screen distance
    // between the two IS the on-screen radius, correct for any orientation.
    //
    // Past DOLLY_END the circle lerps out to a guaranteed fullscreen so the
    // reveal always lands even if the dolly stops short.
    if (eye && scopeWrapRef?.current) {
      const wrap = scopeWrapRef.current
      const wrapRect = wrap.getBoundingClientRect()
      const canvasRect = state.gl.domElement.getBoundingClientRect()
      const w = wrapRect.width || state.size.width
      const h = wrapRect.height || state.size.height
      const canvasW = canvasRect.width || state.size.width
      const canvasH = canvasRect.height || state.size.height

      // Offset along the camera's RIGHT vector so the measured radius is the
      // on-screen one, correct for any lens orientation.
      _right.setFromMatrixColumn(cam.matrixWorld, 0).normalize()
      _vC.copy(eye)
      _vR.copy(eye).addScaledVector(_right, eyeRadius)
      _vC.project(cam)
      _vR.project(cam)

      const projectedCx = canvasRect.left + (_vC.x * 0.5 + 0.5) * canvasW - wrapRect.left
      const projectedCy = canvasRect.top + (-_vC.y * 0.5 + 0.5) * canvasH - wrapRect.top
      const projectedRx = canvasRect.left + (_vR.x * 0.5 + 0.5) * canvasW - wrapRect.left
      const projectedRy = canvasRect.top + (-_vR.y * 0.5 + 0.5) * canvasH - wrapRect.top

      const lock = smooth(norm(p, SPIN_END + 0.03, DOLLY_END))
      const centerCx = canvasRect.left + canvasW / 2 - wrapRect.left
      const centerCy = canvasRect.top + canvasH / 2 - wrapRect.top
      const cx = lerp(projectedCx, centerCx, lock)
      const cy = lerp(projectedCy, centerCy, lock)
      let radius = Math.hypot(projectedRx - projectedCx, projectedRy - projectedCy)
      radius *= lerp(0.72, 1, lock)

      const fs = smooth(norm(p, DOLLY_END, FULLSCREEN_START))
      const full = coverRadius(cx, cy, w, h) + 8
      radius = lerp(radius, full, fs)

      if (Number.isFinite(cx) && Number.isFinite(cy) && Number.isFinite(radius)) {
        if (p >= FULLSCREEN_START) {
          wrap.style.clipPath = 'inset(0)'
          wrap.style.webkitClipPath = 'inset(0)'
        } else {
          const clip = `circle(${radius}px at ${cx}px ${cy}px)`
          wrap.style.clipPath = clip
          wrap.style.webkitClipPath = clip
        }

        const crosshair = crosshairRef?.current
        if (crosshair) {
          const reticleSize = Math.min(Math.max(radius * 2, 64), Math.min(w, h) * 0.62)
          crosshair.style.left = `${cx}px`
          crosshair.style.top = `${cy}px`
          crosshair.style.width = `${reticleSize}px`
          crosshair.style.height = `${reticleSize}px`
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
