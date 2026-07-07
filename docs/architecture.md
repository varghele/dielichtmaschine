# Architecture

Die Lichtmaschine is a PyQt6 desktop application for designing DMX light shows. It provides real-time playback and preview via ArtNet and a 3D Visualizer, and exports QLC+ workspace files (.qxw) for interop.

## Directory Structure

```
QLCplusShowCreator/
├── main.py                    # Application entry point
├── config/
│   ├── models.py              # Core dataclasses (shared with Visualizer)
│   └── compact_serializer.py  # YAML serialization with deduplication
├── gui/
│   ├── gui.py                 # MainWindow orchestration
│   ├── Ui_MainWindow.py       # Qt Designer-generated UI
│   ├── StageView.py           # 2D stage canvas widget
│   ├── stage_items.py         # Fixture icons for stage plot
│   ├── tabs/
│   │   ├── base_tab.py        # Base class with lifecycle methods
│   │   ├── configuration_tab.py  # DMX universe setup
│   │   ├── fixtures_tab.py    # Fixture import and groups
│   │   ├── stage_tab.py       # Visual fixture placement
│   │   ├── structure_tab.py   # Show structure editor
│   │   └── shows_tab.py       # Timeline editor + playback
│   └── dialogs/
│       └── orientation_dialog.py  # 3D fixture orientation popup
├── timeline/
│   ├── playback_engine.py     # BPM-aware playback timing
│   ├── song_structure.py      # Song part management
│   └── light_lane.py          # Light effect lanes
├── timeline_ui/
│   ├── timeline_widget.py     # Master timeline container
│   ├── light_block_widget.py  # Effect block editor
│   ├── light_lane_widget.py   # Lane management
│   ├── colour_block_dialog.py # Color effect editor
│   ├── dimmer_block_dialog.py # Intensity/strobe editor
│   ├── movement_block_dialog.py  # Pan/tilt/shape editor
│   ├── special_block_dialog.py   # Gobo/focus/zoom editor
│   ├── riff_browser_widget.py # Reusable effect library panel
│   ├── undo_commands.py       # Undo/redo support
│   └── selection_manager.py   # Multi-selection handling
├── utils/
│   ├── effects_utils.py       # Color matching, channel helpers
│   ├── fixture_utils.py       # QLC+ fixture definition parsing
│   ├── orientation.py         # 3D rotation matrix utilities
│   ├── target_resolver.py     # Multi-target lane resolution
│   ├── artnet/                # Real-time DMX output (see artnet.md)
│   ├── tcp/                   # Visualizer config sync (see tcp-protocol.md)
│   └── to_xml/                # QLC+ workspace export
│       ├── shows_to_xml.py    # Main export engine
│       └── unified_sequence.py  # Sequence generation
├── audio/
│   ├── simple_audio_player.py # pygame-based playback
│   ├── waveform_analyzer.py   # Waveform peak detection
│   └── audio_waveform_widget.py  # Visual waveform display
├── effects/                   # Effect computation module (extracted from dmx_manager)
│   ├── types.py               # DimmerContext/Result, MovementContext/Result
│   ├── timing.py              # parse_speed(), get_bpm()
│   ├── dimmer_effects.py      # 15 dimmer effects + DIMMER_REGISTRY
│   └── movement_effects.py    # 11 movement shapes + MOVEMENT_REGISTRY
├── rudiments/                 # Rudiment system (Phase 16)
│   ├── rudiment.py            # Rudiment, FluxEnvelope, enums
│   ├── registry.py            # 15 intensity + 11 movement rudiments
│   └── block_converter.py     # rudiment → DimmerBlock/MovementBlock
├── autogen/                   # Automatic show generation (Phase 24)
│   ├── generator.py           # Main orchestrator
│   ├── matcher.py             # Rudiment matching engine
│   ├── spatial.py             # Fixture group classification, activation rules
│   └── color_generator.py     # Song-level color palette system
├── riffs/                     # Reusable effect library (see riffs.md)
│   ├── riff_library.py
│   ├── builds/, drops/, fills/, loops/, movement/, custom/
├── custom_fixtures/           # User QLC+ fixture definitions (.qxf)
├── shows/                     # Show data (CSV + audio)
├── visualizer/                # 3D preview app (see visualizer.md)
└── tests/
```

## Core Data Models

All models live in `config/models.py` and use Python dataclasses with `to_dict()`/`from_dict()` serialization.

### Configuration

The root container for all project data:

- `universes: Dict[int, Universe]` - DMX universe configurations
- `fixtures: Dict[str, Fixture]` - All fixtures by name
- `groups: Dict[str, FixtureGroup]` - Fixture groups
- `shows: Dict[str, Show]` - Shows with song structure
- `spots: Dict[str, Spot]` - Named stage positions
- `stage_width`, `stage_depth`, `stage_height`, `grid_size`

### Fixture

Individual lighting fixture with DMX addressing and 3D orientation:

- `universe`, `address` - DMX addressing
- `manufacturer`, `model`, `current_mode` - QLC+ fixture definition reference
- `type` - PAR, MH (Moving Head), WASH, BAR, SUNSTRIP
- `x, y, z` - Stage position in meters
- `mounting, yaw, pitch, roll` - 3D orientation (see [orientation.md](orientation.md))

### Effect Blocks (Sublanes)

Effects are organized into four sublane types, each stored as blocks on a timeline:

| Sublane | Model | Controls |
|---------|-------|----------|
| **Dimmer** | `DimmerBlock` | Intensity, strobe, iris, effect type/speed |
| **Colour** | `ColourBlock` | RGB/CMY/HSV colors, color wheel position |
| **Movement** | `MovementBlock` | Pan/tilt, shapes (circle, figure-8, lissajous, etc.) |
| **Special** | `SpecialBlock` | Gobo index, prism, focus, zoom |

These are contained within a `LightBlock` envelope on a `LightLane`, which targets one or more fixture groups.

### Timeline Structure

```
Show
 └── ShowPart (BPM, bars, time signature, transition)
      └── TimelineData
           └── LightLane (targets fixture groups/fixtures)
                └── LightBlock (time range envelope)
                     ├── dimmer_blocks: List[DimmerBlock]
                     ├── colour_blocks: List[ColourBlock]
                     ├── movement_blocks: List[MovementBlock]
                     └── special_blocks: List[SpecialBlock]
```

## GUI Tab System

The application uses a modular tab architecture. Each tab extends `BaseTab` with lifecycle methods:

1. **Configuration** - DMX universe setup (E1.31, ArtNet, DMX USB)
2. **Fixtures** - Import QLC+ fixture definitions, manage groups
3. **Stage** - 2D visual fixture placement with drag-and-drop
4. **Structure** - Create show parts with BPM, time signature, bars
5. **Shows** - Timeline editor with sublane blocks, audio sync, playback

Cross-tab communication happens through the parent `MainWindow` and the shared `Configuration` object.

## Communication Architecture

```
┌──────────────────────────────────────────────┐
│              Show Creator                     │
│                                              │
│  Configuration ──► TCP Server (port 9000)    │
│                    (stage, fixtures, groups)  │
│                                              │
│  Playback ──────► ArtNet Sender (UDP 6454)   │
│  Engine           (DMX values @ 44Hz)        │
└──────────┬────────────────────┬──────────────┘
           │ TCP                │ ArtNet
           ▼                   ▼
┌──────────────────────────────────────────────┐
│              Visualizer                       │
│                                              │
│  TCP Client ──► Scene Setup                  │
│  ArtNet Listener ──► DMX-driven Rendering    │
└──────────────────────────────────────────────┘
```

- **TCP** carries configuration data (one-time + on change)
- **ArtNet** carries live DMX values during playback (44Hz)
- The Visualizer can also receive ArtNet from QLC+ directly

## Serialization

Configurations are saved as YAML using `compact_serializer.py`, which provides two-level deduplication:
1. Identical sublane blocks are stored as templates
2. Identical light blocks reference shared definitions with position offsets

This keeps file sizes manageable for large shows.

## QLC+ Export

`utils/to_xml/shows_to_xml.py` generates QLC+ workspace XML files containing:
- Fixture definitions and universe mappings
- Scenes with DMX channel values
- Sequences built from sublane blocks (adaptive step density, max 24 steps/sec)
- Virtual console layout
- Show timeline structure
