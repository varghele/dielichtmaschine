# 3D Visualizer

The Visualizer is a separate PyQt6/ModernGL application that provides real-time 3D preview of lighting effects. It receives configuration via TCP and DMX data via ArtNet from Die Lichtmaschine (or from QLC+ directly).

## Running

```bash
# From the Show Creator Stage tab, click "Launch Visualizer"
# Or run directly:
python visualizer/main.py
```

The Show Creator's TCP server starts automatically when the Visualizer is launched from the Stage tab.

## Architecture

```
visualizer/
├── main.py                 # Entry point, main window
├── tcp/
│   └── client.py           # TCP client for config sync
├── artnet/
│   └── listener.py         # ArtNet UDP listener for DMX
└── renderer/
    ├── engine.py            # ModernGL render loop (QOpenGLWidget)
    ├── camera.py            # Orbiting camera (spherical coordinates)
    ├── stage.py             # Floor grid rendering
    ├── gizmo.py             # XYZ coordinate axes indicator
    └── fixtures.py          # All fixture renderers + beam shaders
```

## Camera Controls

| Input | Action |
|-------|--------|
| Left mouse drag | Orbit around stage center |
| Right mouse drag | Pan view |
| Middle mouse drag | Pan view |
| Scroll wheel | Zoom in/out |
| Home key or R | Reset view |

## Fixture Rendering

Each fixture type has a dedicated renderer:

| Type | Visualization |
|------|---------------|
| **PAR** | Cylindrical body with lens, color glow |
| **LED Bar** | Dark body with individually-lit RGBW segments |
| **Moving Head** | Base + yoke + rotating head with beam |
| **Sunstrip** | Dark body with warm white lamp bulbs |

DMX values drive fixture appearance:
- Dimmer channel controls brightness
- RGB/color wheel channels set color
- Pan/tilt channels rotate moving heads in real-time

## Beam Rendering

Moving heads project volumetric cone beams:
- Beam color and intensity from DMX values
- Follows pan/tilt orientation in real-time
- Additive blending for overlapping beams
- GLSL fragment shaders for volumetric appearance

### Floor Projection

Where a beam hits the floor, a soft gradient spotlight ellipse is rendered:
- Ray-floor intersection calculates position
- Ellipse shape varies with beam angle of incidence
- Intensity falls off with distance (30% reduction at 5m)
- Rendered as a decal on top of the floor

## Special Effects

### Prism (3-facet)

When prism is active (DMX value > 20):
- Beam splits into 3 cones at 120-degree intervals
- Each cone tilted 10 degrees outward from center
- Individual beams at 40% intensity
- 3 separate floor projections

### Gobo Patterns

7 procedural GLSL patterns, inferred from QXF fixture definitions:

| Pattern | Keywords matched from QXF |
|---------|--------------------------|
| Open | "open", "no gobo" |
| Dots | "dot", "circle", "spot" |
| Star | "star" |
| Lines | "line", "bar", "stripe" |
| Triangle | "triangle" |
| Cross | "cross", "plus" |
| Breakup | Default for unrecognized names |

Gobo patterns are visible in both the volumetric beam and the floor projection. Gobo rotation is driven by the rotation DMX channel.

### Focus

Focus simulates optical distance-based sharpness:
- DMX 0 = near focus (sharp at 1m), DMX 255 = far focus (sharp at 10m)
- When projection distance matches focus distance: maximum sharpness
- Affects beam edge softness, gobo pattern clarity, and floor projection spread
- Works with prism (all 3 beams affected equally)

### Combined Effects

Prism, gobo, and focus all work together: 3 patterned, focused beams with 3 patterned floor projections.

## Rendering Details

- **OpenGL**: 3.3 Core Profile via ModernGL
- **Anti-aliasing**: MSAA 4x
- **Target framerate**: 60 FPS
- **Stage grid**: Configurable spacing, synced from Show Creator via TCP
- **Coordinate axes**: X = red (width), Y = blue (depth), Z = green (height)
- **Coordinate gizmo**: XYZ indicator in top-right corner

## Communication

The Visualizer connects to two data sources:

1. **TCP** (port 9000) - Stage layout, fixture positions/types/groups, orientation. Received once on connect and again on changes. See [tcp-protocol.md](tcp-protocol.md).

2. **ArtNet** (UDP 6454) - Live DMX channel values at up to 44Hz. Can come from Show Creator during playback or from QLC+ for live use. See [artnet.md](artnet.md).
