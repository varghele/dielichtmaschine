# ArtNet DMX Output

The ArtNet module enables real-time DMX output during playback, allowing preview in the Visualizer or any ArtNet-compatible software without requiring QLC+.

## Components

### ArtNet Sender (`utils/artnet/sender.py`)

Low-level packet generator:
- ArtNet OpDmx packet format (Art-Net 4 specification)
- UDP broadcast or unicast to port 6454
- 44Hz rate limiting (22.7ms minimum interval)
- Sequence counter (0-255, wrapping)
- Automatic 512-byte padding

### DMX Manager (`utils/artnet/dmx_manager.py`)

Manages DMX state for all universes:
- 512 channels per universe
- Fixture-to-channel mapping from `.qxf` definitions
- Real-time block-to-DMX conversion
- LTP (Latest Takes Priority) for overlapping blocks
- BPM-aware timing via `SongStructure.get_bpm_at_time()`

### Shows ArtNet Controller (`utils/artnet/shows_artnet_controller.py`)

Integrates with the Shows tab playback:
- Tracks active blocks per fixture group per sublane type
- Granular block ending (dimmer can fade while color holds)
- Driven by the ShowsTab playback timer (no separate playback engine)

## Real-time Effects

### Dimmer Effects

| Effect | Behaviour |
|--------|-----------|
| Static | Constant intensity |
| Strobe | Alternates intensity/off based on speed multiplier |
| Twinkle | Random variation (70-100%) around base intensity |

### Movement Shapes

All shapes are BPM-synced and use parametric equations:

| Shape | Description |
|-------|-------------|
| Static | Fixed pan/tilt position |
| Circle | `cos(t)` / `sin(t)` |
| Figure-8 | `sin(t)` / `sin(2t)` |
| Lissajous | Configurable frequency ratio (e.g., 1:2, 3:4) |
| Diamond | 4 corners with linear interpolation |
| Square | 4 corners with linear interpolation |
| Triangle | 3 corners with linear interpolation |
| Random | Multiple sine waves for smooth pseudo-random motion |
| Bounce | Triangle waves, back and forth |

Speed multiplier and amplitude are configurable per block.

## GUI Integration

The Shows tab toolbar includes an **ArtNet Output** checkbox:
- Checked by default
- Green styling when active
- Tooltip: "Enable/disable real-time DMX output via ArtNet"

During playback:
1. ShowsTab updates position every frame (60 FPS)
2. Controller finds active blocks at current time
3. DMX Manager calculates channel values (effects evaluated in real-time)
4. ArtNet Sender transmits at 44Hz (rate-limited internally)

## Usage

```python
from utils.artnet import ShowsArtNetController

controller = ShowsArtNetController(
    config=config,
    fixture_definitions=fixture_defs,
    target_ip="255.255.255.255"  # broadcast
)
controller.set_song_structure(song_structure)
controller.set_light_lanes(lanes)
controller.start_playback()

# Each frame:
controller.update_position(current_time_seconds)

# Cleanup:
controller.stop_playback()
controller.cleanup()
```

## Network

- **Protocol**: ArtNet (Art-Net 4) over UDP
- **Port**: 6454 (standard)
- **Default target**: `255.255.255.255` (broadcast)
- **Send rate**: 44Hz max
- **Bandwidth**: ~28 KB/s per universe (512 bytes x 44Hz)

### Firewall

```bash
# Windows
netsh advfirewall firewall add rule name="Show Creator ArtNet" dir=out action=allow protocol=UDP localport=6454

# Linux
sudo ufw allow out 6454/udp
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No DMX output | Check ArtNet checkbox is enabled, playback is running |
| Visualizer not receiving | Verify same network, try unicast IP instead of broadcast |
| Wrong DMX values | Check fixture `.qxf` definitions and current mode |
| No movement | Verify fixtures have pan/tilt channels, amplitude > 0 |
