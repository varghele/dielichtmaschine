# OpenGL / ModernGL Gotchas

Companion to [qt-gotchas.md](qt-gotchas.md). Same purpose: surface the
non-obvious traps in the 3D pipeline so they don't get re-discovered
the expensive way. Each entry has a workaround the codebase already
uses.

---

## 1. `ctx.depth_mask = X` is a no-op in moderngl 5.11.x

**Symptom:** opaque fragments drawn *after* a "no-depth-write" pass
(beams, floor projections, HDR tonemap quad, any transparent overlay)
fail their depth-test where the no-write pass went, and silently
disappear. Looks like z-fighting but no debug tool flags it.

**Why:** in moderngl 5.11.x `Context.depth_mask` is *not* a property —
`hasattr(moderngl.Context, 'depth_mask')` is `False`. Assigning
`ctx.depth_mask = False` just stores it on the instance as a regular
Python attribute and never calls `glDepthMask`. So every "additive,
no depth write" pass was actually writing depth.

This was the root cause of the **chassis-vanishes-behind-beams** bug in
the embedded visualizer (fixed May 2026). The two-pass chassis-on-top
flow was correct; the chassis depth-test was failing because the
prior beam pass had stamped a closer depth into the buffer where it
overlapped chassis pixels in screen space.

**How to apply / workaround:**

Always go through `visualizer/renderer/gl_state.py::set_depth_mask`.
It calls `glDepthMask` directly via ctypes against the platform GL
library (opengl32.dll on Windows, libGL.so on Linux, OpenGL.framework
on macOS) and works against whatever GL context moderngl has made
current on this thread.

```python
from visualizer.renderer.gl_state import set_depth_mask

# Inside a "transparent / additive" pass:
set_depth_mask(False)
try:
    vao.render(...)
finally:
    set_depth_mask(True)
```

Sanity-check at any time:

```python
# In a unit test or REPL: writing identical fragments with the property
# and with the ctypes helper should give different depth-buffer states.
import moderngl, numpy as np
ctx = moderngl.create_standalone_context()
color = ctx.texture((4, 4), 4)
depth = ctx.depth_texture((4, 4))
fbo = ctx.framebuffer(color_attachments=[color], depth_attachment=depth)
# ... draw a fragment at depth 0.5 ...
ctx.depth_mask = False        # no-op
print(np.frombuffer(depth.read(), dtype='f4')[0])  # 0.5 (depth still written)
```

If moderngl is upgraded and `Context.depth_mask` becomes a real
property, `set_depth_mask` can collapse to `ctx.depth_mask = enabled`.
Detect by `hasattr(moderngl.Context, 'depth_mask')`.

---

## 2. The chassis-on-top render order is intentional

**Symptom:** the Mac Aura moving wash (and similar one-fixture moving
washes) render with a slightly darker lens area than the legacy
renderer — block-mean RMS ~0.08 in the parity test
(`test_fixture_renderer_parity.py`).

**Why:** `FixtureManager.render` does two passes — pass 1 calls
`render_lighting` on every fixture (additive beams + floor projection,
no depth write), pass 2 calls `render_chassis` on every fixture
(opaque body, with depth). The lens slab in pass 2 overwrites pixels
that the same fixture's beam tip already lit additively in pass 1.

Legacy single-pass (`chassis` then `beam additive on top`) had the
opposite ordering: the lens area was both chassis-color AND beam-tip
brightness, summed. Composable's chassis-on-top keeps the chassis at
its native color regardless of beam overlap, which is the whole point
of the bug fix — but the lens specifically appears at native chassis
color instead of native + beam tip.

**How to apply:** parity tolerances are sized for this divergence:

```python
HISTOGRAM_TOLERANCE = 0.15
BLOCK_MEAN_TOLERANCE = 0.085   # Mac Aura observed ~0.078; legacy fixtures all < 0.01
```

Don't tighten `BLOCK_MEAN_TOLERANCE` below 0.085 unless Mac Aura
specifically gets a per-fixture exemption. Inverse: if the
non-Mac-Aura fixtures drift above 0.01-0.03 block-mean, *that's* a
real regression worth investigating.

---

## 3. `fbo.read()` returns rows bottom-up; PIL displays top-down

**Symptom:** images saved with `Image.fromarray(np.frombuffer(...))`
look vertically flipped compared to the OpenGL screen. A projection
helper that returns "FBO y from bottom" lines up with `image[y, x]`
*before* you save the PNG, then looks wrong once you open the file.

**Why:** `moderngl.Framebuffer.read()` returns pixels starting from
the bottom-left of the OpenGL screen. `np.frombuffer(...).reshape(H, W, 3)`
makes numpy row 0 = bottom of FBO. PIL's `Image.fromarray` treats row
0 as the top row of the saved PNG.

**How to apply:** debugging from saved PNGs, mentally flip Y. Or save
flipped:

```python
raw = fbo.read(components=3, dtype="f1")
img = np.frombuffer(raw, dtype="u1").reshape(H, W, 3)
# OpenGL → PIL convention: flip vertically when saving for visual inspection.
Image.fromarray(np.flipud(img)).save("debug.png")
```

But: don't flip inside the numpy array used for assertions. Tests
that project world → FBO-y-from-bottom and then index `img[y, x]`
work correctly *without* flipping (numpy and the projection share the
same convention).

---

## 4. Swapping two axes MIRRORS the world (stage -> scene mapping)

*Long form, plus the fixture-orientation half of the story:
[coordinate-frames-and-orientation.md](coordinate-frames-and-orientation.md).*

**Symptom:** the 3D scene looks subtly wrong in a way nobody can name.
Floor lettering renders as mirror writing. A mover aimed at a spike
mark appears to hit the mark's mirror image. "Point at the audience"
sends beams toward the back of the stage. Everything is nonetheless
self-consistent: beams DO land on their targets, so no test catches it.

**Why:** every renderer places geometry with

```python
glm.translate(m, glm.vec3(pos['x'], pos['z'], pos['y']))   # stage -> scene
```

i.e. stage `(x, y, z_height)` -> scene `(x, z_height, y)`. That SWAPS
two axes, and a two-axis swap has **determinant -1**: it is a
reflection, not a rotation. The scene was a mirror image of the real
stage. Self-consistency hides it - the solver
(`utils/orientation.py`) maps targets into the same mirrored frame, so
the closed loop works and only the comparison with reality (text,
left/right, the Stage tab) exposes it.

Compounding it: the default orbit camera (azimuth 45) then sat
*upstage*, so the first thing you saw was the band from behind.

**How to apply:**

- The correction is ONE change of basis on the view matrix
  (`visualizer/renderer/camera.py` `DISPLAY_FLIP` = `diag(1, 1, -1)`),
  giving stage -> display `(x, z, -y)`, determinant +1. No renderer, no
  model matrix and NO pan/tilt math changes, so DMX output is untouched.
- Face culling is never enabled in this renderer, so the reflected
  winding is harmless. If you ever enable `CULL_FACE`, revisit this.
- Consequence to remember: **the camera orbits in display space**, so a
  given azimuth now views the stage from the opposite side than it did
  before. Hand-placed cameras in tests need +180 degrees
  (`tests/visual/test_beam_chassis_occlusion.py`).
- Check handedness with a determinant assertion, not by eye:
  `tests/unit/test_display_frame.py`. And keep a piece of ASYMMETRIC
  geometry in the scene - the `v AUDIENCE v` stroke lettering on the
  apron (`visualizer/renderer/stage.py`) is the permanent witness. A
  mirrored world is instantly visible as backwards text; a symmetric
  grid tells you nothing.

---

## Adding new entries

If you spend more than 20 minutes diagnosing a GL or moderngl issue
that turns out to be a known trap of the library, add it here with:

- short Symptom (what looks broken)
- short Why (the underlying behavior)
- short How to apply (workaround / test for it / where the codebase
  handles it)

Keep entries terse — this is a reference, not a tutorial.
