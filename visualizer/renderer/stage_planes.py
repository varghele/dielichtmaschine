# visualizer/renderer/stage_planes.py
# Translucent highlight for one face of the stage bounding cuboid.
#
# The Stage tab's plane picker drives this: hovering/selecting a plane
# (Floor / Ceiling / Front / Back / Left / Right) draws that face as a
# translucent quad + outline in the 3D view so the operator can see which
# Z-plane / wall they are about to work with. Display-only — plane
# *targeting* from movement blocks is v1.5a.

from typing import List, Optional, Tuple

import numpy as np
import moderngl
import glm

from .gl_state import set_depth_mask

PLANE_NAMES = ("Floor", "Ceiling", "Front", "Back", "Left", "Right")

# Cyan-ish accent; distinct from beam colors and both grid axis colors.
FILL_COLOR = (0.25, 0.75, 1.0, 0.22)
OUTLINE_COLOR = (0.25, 0.75, 1.0, 0.9)

# Lift the floor quad slightly above the stage floor + grid + axes
# (which stack up to y=0.003) so it never z-fights them.
_FLOOR_LIFT = 0.01


def plane_corners(name: str, width: float, depth: float,
                  height: float) -> List[Tuple[float, float, float]]:
    """The 4 world-space corners of a stage cuboid face.

    World frame is the renderer's Y-up convention: stage X -> world X
    (centered), stage height -> world Y (0 = floor), stage Y -> world Z
    (centered, negative = front / audience side). Corner order is fan
    order: (0,1,2) + (0,2,3) triangulates the quad.
    """
    hw, hd = width / 2.0, depth / 2.0
    if name == "Floor":
        y = _FLOOR_LIFT
        return [(-hw, y, -hd), (hw, y, -hd), (hw, y, hd), (-hw, y, hd)]
    if name == "Ceiling":
        return [(-hw, height, -hd), (hw, height, -hd),
                (hw, height, hd), (-hw, height, hd)]
    if name == "Front":
        return [(-hw, 0.0, -hd), (hw, 0.0, -hd),
                (hw, height, -hd), (-hw, height, -hd)]
    if name == "Back":
        return [(-hw, 0.0, hd), (hw, 0.0, hd),
                (hw, height, hd), (-hw, height, hd)]
    if name == "Left":
        return [(-hw, 0.0, -hd), (-hw, 0.0, hd),
                (-hw, height, hd), (-hw, height, -hd)]
    if name == "Right":
        return [(hw, 0.0, -hd), (hw, 0.0, hd),
                (hw, height, hd), (hw, height, -hd)]
    raise ValueError(f"Unknown stage plane: {name!r}")


class StagePlaneHighlight:
    """Owns the GL resources for the highlighted-plane overlay.

    State setters are GL-free (safe to call from any pre/post-init path);
    the vertex buffer is (re)written lazily inside :meth:`render` where a
    context is guaranteed current.
    """

    VERTEX_SHADER = """
    #version 330

    in vec3 in_position;

    uniform mat4 mvp;

    void main() {
        gl_Position = mvp * vec4(in_position, 1.0);
    }
    """

    FRAGMENT_SHADER = """
    #version 330

    out vec4 fragColor;

    uniform vec4 color;

    void main() {
        fragColor = color;
    }
    """

    def __init__(self, ctx: moderngl.Context,
                 width: float = 10.0, depth: float = 6.0):
        self.ctx = ctx
        self.stage_width = width
        self.stage_depth = depth
        self.rig_height = 3.0
        self.highlighted: Optional[str] = None
        self._dirty = True

        self.program = ctx.program(
            vertex_shader=self.VERTEX_SHADER,
            fragment_shader=self.FRAGMENT_SHADER,
        )
        # 6 fill vertices (2 triangles) + 4 outline vertices, 3 floats each.
        self._vbo = ctx.buffer(reserve=(6 + 4) * 3 * 4, dynamic=True)
        self._vao = ctx.vertex_array(
            self.program, [(self._vbo, '3f', 'in_position')]
        )

    # ── GL-free state setters ─────────────────────────────────────────

    def set_stage_size(self, width: float, depth: float) -> None:
        if (width, depth) != (self.stage_width, self.stage_depth):
            self.stage_width = width
            self.stage_depth = depth
            self._dirty = True

    def set_rig_height(self, height: float) -> None:
        height = max(height, 0.1)
        if height != self.rig_height:
            self.rig_height = height
            self._dirty = True

    def set_highlight(self, name: Optional[str]) -> None:
        if name is not None and name not in PLANE_NAMES:
            raise ValueError(f"Unknown stage plane: {name!r}")
        if name != self.highlighted:
            self.highlighted = name
            self._dirty = True

    # ── Rendering ─────────────────────────────────────────────────────

    def _rebuild_vbo(self) -> None:
        corners = plane_corners(
            self.highlighted, self.stage_width, self.stage_depth,
            self.rig_height,
        )
        fill = [corners[0], corners[1], corners[2],
                corners[0], corners[2], corners[3]]
        vertices = np.array(fill + corners, dtype='f4')
        self._vbo.write(vertices.tobytes())
        self._dirty = False

    def render(self, mvp: glm.mat4) -> None:
        if self.highlighted is None:
            return
        if self._dirty:
            self._rebuild_vbo()

        mvp_flat = []
        for col in mvp.to_list():
            mvp_flat.extend(col)
        self.program['mvp'].write(np.array(mvp_flat, dtype='f4').tobytes())

        # Standard alpha blend (this is a UI highlight, not light), depth
        # test on so chassis in front still occludes, depth WRITE off so
        # the translucent quad never stamps depth over later fragments —
        # and never through ctx.depth_mask (see docs/gl-gotchas.md #1).
        # Same state discipline as FloorProjectionComponent: enable + set
        # what we need, disable in finally; ctx.blend_func is write-only.
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        set_depth_mask(False)
        try:
            self.program['color'].value = FILL_COLOR
            self._vao.render(moderngl.TRIANGLES, vertices=6)
            self.program['color'].value = OUTLINE_COLOR
            self._vao.render(moderngl.LINE_LOOP, vertices=4, first=6)
        finally:
            set_depth_mask(True)
            self.ctx.disable(moderngl.BLEND)

    def release(self) -> None:
        self._vao.release()
        self._vbo.release()
        self.program.release()
