# Coordinate frames, fixture orientation, and the open yoke question

Reference note. Written 2026-07-12 after fixing two coordinate bugs the
user found by eye ("everything is flipped"; "hanging fixtures behave
like wall-back"), and after discovering a third one that cannot be
settled without a real moving head.

Read this before touching anything that maps stage coordinates into the
3D scene, defines a mounting preset, or converts a target into pan and
tilt. The traps here are the kind that stay invisible for months because
every piece is self-consistent with every other piece.

Status summary:

| # | Issue | State |
|---|---|---|
| 1 | The 3D scene was a mirror image of the stage | FIXED (commit a373e4a) |
| 2 | Mounting presets: two contradictory tables, both wrong | FIXED (commit c5c72c1) |
| 3 | The pan/tilt yoke model may not describe a real mover | **OPEN**, needs hardware |

---

## 1. The three frames

There are three coordinate frames. Confusing them is the root of every
bug in this document.

**Stage frame** (config space, what the user thinks in, metres):

- `+X` stage right, centred on 0
- `+Y` upstage / away from the crowd. **The audience is at negative Y.**
- `+Z` up
- Right-handed.

This is what `Fixture.x/y/z`, `Spot`, `StageElement` and
`utils/position_presets.py` all speak. Note that `autogen/spatial.py`
uses its own 0..D depth convention internally. Do not mix them.

**Scene frame** (what every renderer's model matrix builds in, Y-up):

```python
glm.translate(m, glm.vec3(pos['x'], pos['z'], pos['y']))   # stage -> scene
```

so stage `(x, y, z)` becomes scene `(x, z, y)`. Note what this is: it
**swaps two axes**. A two-axis swap has determinant **-1**. It is a
reflection, not a rotation. The scene frame is a mirror image of the
stage.

**Display frame** (what the camera actually sees). The reflection is
undone once, at the view matrix:

```python
DISPLAY_FLIP = diag(1, 1, -1)     # visualizer/renderer/camera.py
view = glm.lookAt(...) * DISPLAY_FLIP
```

Composed, stage `(x, y, z)` -> display `(x, z, -y)`, determinant **+1**.
A proper rotation. The picture is finally a faithful copy of the stage
rather than its mirror.

---

## 2. The mirror bug (fixed)

**Symptom, as reported:** aim a mover at a spike mark and it appears to
hit the mark's mirror image. Aim at the audience and the beam flies
toward the back of the stage. Floor lettering renders backwards.

**Why it hid for so long:** the solver (`utils/orientation.py`) maps its
targets into the *same* mirrored scene frame that the renderer draws in.
Two mirrors cancel. So beams genuinely landed on their targets inside
the visualizer, every test passed, and the defect was only visible by
comparing against reality: text, left/right, and the Stage tab.

**The fix:** one change of basis on the view matrix (above). Deliberately
*not* a rewrite of the renderers' model matrices, because:

- No renderer, no model matrix, and above all **no pan/tilt math**
  changes, so the DMX we send the rig is provably untouched by this fix.
  (Verified: export hashes for all five demo rigs identical across it.)
- Face culling is never enabled in this renderer, so the reflected
  winding is harmless. **If you ever enable `CULL_FACE`, revisit this.**

**Two consequences to remember:**

1. **The camera orbits in display space.** A given azimuth now views the
   stage from the opposite side than it did before. The default azimuth
   45 used to sit upstage (looking at the band from behind); it now sits
   in the audience, which is what you want. Hand-placed cameras in tests
   needed +180 degrees (`tests/visual/test_beam_chassis_occlusion.py`,
   verified pixel-identical to the pre-fix framing).
2. **Keep asymmetric geometry in the scene.** The `v AUDIENCE v` stroke
   lettering on the downstage apron (`visualizer/renderer/stage.py`) is
   the permanent regression witness: a mirrored world is instantly
   visible as backwards text, whereas a symmetric grid tells you nothing.
   It is drawn as line segments through the grid pipeline, so it needs no
   fonts (the offscreen Qt platform on Windows has no font database) and
   no textures.

**Pinned by:** `tests/unit/test_display_frame.py` asserts the
determinant, not the appearance: scene frame is -1 (a reflection),
display frame is +1 (a rotation). Also `docs/gl-gotchas.md` #4.

---

## 3. The mounting presets (fixed)

**Symptom, as reported:** a fixture set to `hanging` in the config
behaves like `wall_back` in the visualizer.

**Two independent faults, both real:**

1. **Consumers ignored `mounting`.** Configs store
   `mounting: hanging` next to `yaw/pitch/roll: 0.0`. Both the
   visualizer payload and `calculate_pan_tilt` used the explicit angles
   and ignored the mounting string entirely. Zeroed angles mean "beam
   along +X" = pointing stage right = exactly what a wall mount does.
2. **The preset tables were wrong.** There were *two* of them, and
   neither was right:
   - The orientation dialog's `PRESET_VALUES` defined `hanging` as
     **pitch +90**. Pitch is a rotation about the X axis, and the beam
     starts along +X, so a pitch rotation **cannot move the beam at
     all**. Hanging and standing both aimed stage right.
   - `utils/orientation.py`'s table had `hanging` and `standing` right,
     but **all four `wall_*` presets were 90 degrees off** (its
     `wall_back` aimed stage right rather than at the audience).

**The fix:** exactly ONE table,
`utils/orientation.py::MOUNTING_PRESET_ANGLES`. The dialog imports it.
Never write a second copy.

```python
MOUNTING_PRESET_ANGLES = {           # absolute (yaw, pitch, roll)
    'hanging':    (0.0, 0.0, -90.0),   # beam DOWN
    'standing':   (0.0, 0.0,  90.0),   # beam UP
    'wall_left':  (0.0, 0.0,   0.0),   # beam stage RIGHT
    'wall_right': (180.0, 0.0, 0.0),   # beam stage LEFT
    'wall_back':  (90.0, 0.0,  0.0),   # beam at the AUDIENCE
    'wall_front': (-90.0, 0.0, 0.0),   # beam UPSTAGE
}
```

**Rules that keep this fixed:**

- `mounting` is a **label**. The angles carry the truth.
- Assert presets by **where the beam actually points in stage
  coordinates** (`beam_direction_stage`), never by the angle numbers.
  The angle numbers are exactly what nobody could sanity-check by eye,
  which is how they stayed wrong.
- Config load migrates zeroed and legacy-dialog angles onto the table
  (`migrate_orientation_angles`, idempotent). Hand-dialled custom
  orientations are left alone.
- A dead third rotation API (`get_rotation_matrix` and friends: a Z-up
  ZYX convention that added a hidden base rotation, called by nothing
  but its own tests) was deleted. It is the reason nobody noticed the
  presets were wrong: it *looked* like the authority and was never used.

**Consequence you must know:** because fixtures are now oriented
correctly, the pan/tilt written to the rig and to exported `.qxw`
workspaces **changes for any rig containing moving heads**. This is
intended: the old values were computed from mis-oriented fixtures. The
delta is provably confined to pan/tilt: of the five demo rigs, only
`theatre_static` (the one with zero movers) still exports
byte-identically.

**Pinned by:** `tests/unit/test_orientation.py`
(`TestMountingPresetBeams`, `TestMigration`, `TestAimingEndToEnd`).

---

## 4. OPEN: does the yoke model describe a real moving head?

**This is the one that needs the hardware. It is not fixed.**

### The claim

Both the solver and the renderer model *every* fixture the same way:

- the beam leaves along fixture-local **+X**
- **pan** rotates about local **Z**
- **tilt** rotates about local **Y**

In that model the beam at `tilt = 0` is always **perpendicular to the
pan axis**. Combine this with the canonical `hanging` preset (roll -90,
beam down at home) and the pan axis comes out **horizontal**.

A real hanging moving head pans about a **vertical** axis, and at
mid-tilt its beam points roughly **horizontally**, not straight down.

### Worked example (the discriminating prediction)

Hanging mover 5 m up at stage `(0, 0, 5)`. Target on the floor 2 m to
stage right, `(2, 0, 0)`.

- **What we currently emit:** pan `21.8 deg`, tilt `0 deg`
  (DMX pan ~137, tilt 127 on a 540/270 fixture).
- **What our visualizer draws:** the beam hits the target. Self-consistent.
- **What a real mover would most likely do:** at tilt centre it points
  straight down (or straight ahead, depending on its convention) and pan
  rotates it about the vertical without moving it off that direction. So
  it would **stay pointing straight down** and miss the target by 2 m.

If that is what the hardware does, the model is wrong for movers.

### Why it is not a sign flip

The beam's local axis is hard-coded to `+X` for every fixture. But:

- a **PAR** emits along its body: a hanging PAR must point **down**;
- a **mover** emits off an articulated head: a hanging mover must pan
  about the **vertical**, and its beam at home is perpendicular to that.

One set of Euler angles cannot satisfy both, because the model rigidly
ties "beam = local +X" and "pan axis = local Z" to the same body frame.
The beam axis and the base/pan axis need to come from the **fixture
definition**, not be hard-coded. GDTF's geometry tree already carries
exactly this (`utils/gdtf_mesh.py`,
`visualizer/renderer/gdtf_draw_plan.py` already parse the Axis nodes for
the mesh kinematics), so the data is largely in hand.

**Do not "fix" this by flipping signs until the hardware has spoken.**
Sign flips will make one test rig look right and silently break another
mounting.

---

## 5. Hardware verification protocol

For the session where the two real moving heads are on the bench. Each
test is designed so the *outcome discriminates between hypotheses*, not
merely "looks right".

**Setup**

- Patch the two movers, note make / model / mode, and their DMX
  addresses.
- In the Stage tab, place them at known coordinates and set mounting to
  match how they are physically rigged (hang them if at all possible,
  even from a short truss or a stand upside down: `hanging` is the case
  that matters).
- Record the fixture definition's `PanMax` / `TiltMax` (the app now
  reads these from `<Physical><Focus>`; a wrong range will confound
  every result below).
- Have the visualizer open beside the rig for every test.

**Test A: where is home?** (the single most informative observation)

Send pan = 127, tilt = 127 (centre) with the shutter open.

- Beam points **straight down** -> our current model matches the fixture.
- Beam points **horizontally** -> the real tilt-centre is horizontal,
  and the yoke model is wrong as predicted. Record which horizontal
  direction it faces relative to the fixture body.

**Test B: what does pan do?**

Hold tilt at 127, sweep pan slowly from 0 to 255.

- The beam traces a **horizontal circle / cone** about the vertical
  (azimuth sweep) -> real yoke, pan axis vertical.
- The beam swings in a **vertical plane** (up and over, left to right)
  -> matches our current model's horizontal pan axis.

**Test C: what does tilt do?**

Hold pan at 127, sweep tilt from 0 to 255. Record the beam's travel:
which plane it sweeps, and where the extremes point (this pins the
tilt-centre convention and the true tilt range).

**Test D: end to end, the thing the user actually does**

Drop a spike mark at a measured point on the floor. Select the mover
group in the Live tab and touch that position palette.

- Measure where the beam lands. Record the error vector in metres.
- Screenshot the visualizer for the same moment.
- If the visualizer says "on the mark" and the rig says otherwise, that
  is the yoke bug, quantified.

Repeat Test D with the mover at a **different mounting** (for instance
standing on the floor pointing up, or on its side) if time allows. A
model that is right for one mounting and wrong for another is the
signature of the hard-coded beam axis.

**Data to bring back**

| Field | Why |
|---|---|
| Make / model / mode / PanMax / TiltMax | fixes the ranges, rules out a range bug |
| Test A: home direction | discriminates the whole model in one shot |
| Test B: pan sweep shape | identifies the true pan axis |
| Test C: tilt sweep plane and extremes | identifies the tilt axis and centre convention |
| Test D: target vs landing point, per mounting | quantifies the error, proves the fix later |
| Whether pan or tilt is inverted on the fixture | `pan_tilt_to_dmx` already supports inversion flags, unused so far |

**If the hardware confirms the yoke bug**, the fix is: take the beam
axis and the pan/tilt axes from the fixture definition (GDTF geometry
tree, with a sensible fallback for `.qxf`), and make `mounting` orient
the fixture **body** rather than the beam. Then `calculate_pan_tilt`
solves in the fixture's real kinematic chain. Test D becomes the
acceptance test, and the visualizer must be re-verified against it since
it currently shares the same wrong model (and therefore currently agrees
with the solver for the wrong reason).

---

## 6. Where things live

| Thing | File |
|---|---|
| The one mounting table, migration, solver | `utils/orientation.py` |
| Display correction (`DISPLAY_FLIP`), camera | `visualizer/renderer/camera.py` |
| AUDIENCE marker (regression witness) | `visualizer/renderer/stage.py` |
| Beam chain the renderer uses | `visualizer/renderer/composable_fixtures.py::_compute_beam_dir_world` |
| Orientation migration on load | `config/models.py::Configuration.load` |
| Preset editing UI (imports the table) | `gui/dialogs/orientation_dialog.py` |
| Frame handedness tests | `tests/unit/test_display_frame.py` |
| Preset beam-direction + migration + aiming tests | `tests/unit/test_orientation.py` |
| The reflection trap, short form | `docs/gl-gotchas.md` #4 |
| Open yoke item | `todo.md`, ROADMAP v1.5a |
