# ArtNet DMX Output Module

Real-time ArtNet DMX output for Die Lichtmaschine.

## Overview

This module enables the app to send DMX data via ArtNet during playback, driving a real rig live and allowing real-time preview in the Visualizer or other ArtNet-compatible software.

## Components

### 1. `ArtNetSender`
Low-level ArtNet packet generator and UDP sender.

- Generates ArtNet OpDmx packets according to specification
- Rate-limited to 44Hz max to avoid overloading receivers
- Supports broadcast or unicast transmission

### 2. `DMXManager`
Manages DMX state for all universes.

- Tracks 512 channels per universe
- Maps fixtures to DMX channels using `.qxf` definitions
- Converts sublane blocks to DMX values in real-time
- Handles overlapping blocks with LTP (Latest Takes Priority)
- Supports real-time effect calculations (strobe, twinkle, movement shapes)

### 3. `ArtNetOutputController`
High-level controller that integrates with the playback engine.

- Connects to PlaybackEngine signals
- Updates DMX state based on active blocks
- Sends DMX via ArtNet at 44Hz during playback
- Can be enabled/disabled independently of playback

## Integration Example

```python
from utils.artnet import ArtNetOutputController
from config.models import Configuration
from timeline.playback_engine import PlaybackEngine

# Load configuration with fixtures
config = Configuration.load("config.yaml")

# Load fixture definitions
fixture_definitions = Configuration._scan_fixture_definitions()

# Create playback engine
playback_engine = PlaybackEngine()

# Create ArtNet output controller
artnet_controller = ArtNetOutputController(
    config=config,
    fixture_definitions=fixture_definitions,
    playback_engine=playback_engine,
    target_ip="255.255.255.255"  # Broadcast (or specific IP like "192.168.1.100")
)

# Enable ArtNet output
artnet_controller.enable_output()

# Now when playback starts, DMX will be sent via ArtNet
playback_engine.play()

# To disable output
artnet_controller.disable_output()

# Cleanup when done
artnet_controller.cleanup()
```

## Integration with Main GUI

In `gui/gui.py` or the Shows tab:

```python
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ... existing initialization ...

        # Create ArtNet controller (after config and playback engine are created)
        self.artnet_controller = None
        self._init_artnet_output()

    def _init_artnet_output(self):
        """Initialize ArtNet output controller."""
        if self.config and self.playback_engine:
            # Load fixture definitions
            fixture_defs = Configuration._scan_fixture_definitions()

            # Create controller
            self.artnet_controller = ArtNetOutputController(
                config=self.config,
                fixture_definitions=fixture_defs,
                playback_engine=self.playback_engine,
                target_ip="255.255.255.255"
            )

            # Add a checkbox or button to enable/disable output
            # For now, enable by default
            self.artnet_controller.enable_output()

    def closeEvent(self, event):
        """Clean up on window close."""
        if self.artnet_controller:
            self.artnet_controller.cleanup()
        super().closeEvent(event)
```

## How It Works

### 1. Block Triggering
When a `LightBlock` starts during playback:
- `PlaybackEngine` emits `block_triggered(lane, block)` signal
- `ArtNetOutputController` receives the signal
- For each sublane block in the light block:
  - Registers the block with `DMXManager` if it's currently active
  - DMXManager stores the block for the fixture group

### 2. Real-time DMX Update (44Hz)
Every ~23ms (44Hz):
- `ArtNetOutputController` timer triggers `_update_and_send_dmx()`
- `DMXManager.update_dmx(current_time)` calculates DMX values:
  - For each fixture group with active blocks:
    - For each fixture in the group:
      - Apply dimmer block → calculate intensity (with effects like strobe)
      - Apply colour block → set RGB/color wheel channels
      - Apply movement block → calculate pan/tilt position (shapes calculated in real-time)
      - Apply special block → set gobo, prism, focus, zoom
- `ArtNetSender.send_dmx()` sends packets for each universe

### 3. Block Ending
When a `LightBlock` ends:
- `PlaybackEngine` emits `block_ended(lane, block)` signal
- `ArtNetOutputController` removes the block from `DMXManager`

## Real-time Effect Calculations

### Dimmer Effects
- **Static**: Constant intensity
- **Strobe**: Alternates between intensity and 0 based on speed
- **Twinkle**: Random variation around intensity

### Movement Shapes
Calculated using parametric equations based on `current_time`:

- **Circle**: `pan = center + amplitude * cos(t)`, `tilt = center + amplitude * sin(t)`
- **Figure-8**: `pan = center + amplitude * sin(t)`, `tilt = center + amplitude * sin(2t)`
- **Lissajous**: Frequency ratio determines pattern (e.g., 1:2, 3:4)

Where `t = 2π * cycles * progress` and progress is calculated from current playback time.

## Configuration

### Universe Settings
The module reads universe configuration from `config.universes`:
- Universe ID
- Output type (E1.31, ArtNet, etc.)
- IP address and port

### Target IP
Default: `255.255.255.255` (broadcast)

To send to specific IP:
```python
artnet_controller.set_target_ip("192.168.1.100")
```

## Network Ports

- **ArtNet**: UDP port 6454 (standard)
- Packets are sent to the configured target IP on port 6454

## Rate Limiting

- Maximum send rate: **44Hz** (22.7ms interval)
- Prevents overloading receivers
- Matches standard DMX refresh rate
- Can be forced with `send_dmx(force=True)` if needed

## Troubleshooting

### No DMX output
1. Check that output is enabled: `artnet_controller.enable_output()`
2. Verify playback is running
3. Check firewall settings (UDP port 6454)
4. Verify fixture definitions are loaded correctly

### Visualizer not receiving
1. Ensure Visualizer is listening on the same network
2. Check IP address (use broadcast for testing)
3. Verify universe numbers match
4. Check that blocks have valid start/end times

### DMX values incorrect
1. Verify fixture definitions (`.qxf` files) are correct
2. Check fixture current_mode matches available modes
3. Review channel mappings in DMXManager
4. Enable debug logging to see DMX values

## Future Enhancements

- [ ] Add UI toggle for ArtNet output
- [ ] Add universe activity indicators
- [ ] Add DMX value monitoring/debugging view
- [ ] Support for multiple output interfaces
- [ ] Configurable send rate (currently fixed at 44Hz)
- [ ] BPM-aware timing from SongStructure (currently uses default 120 BPM)
