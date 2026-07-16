# utils/templates.py
"""Project templates (starter rigs), backed by the bundled demo content.

The demo rigs under ``demos/rigs/`` and their ready-to-play show variants
under ``demos/shows/`` double as project templates: `File -> New from
Template` copies one to a user-chosen location (never opens it in place,
so Ctrl+S can't overwrite the template or write into a read-only install
dir) and the app opens the copy.

Path resolution works in both a dev checkout and a PyInstaller bundle:
``__file__`` lives under the project root in dev and under the bundle
directory when frozen, and the spec ships ``demos/rigs`` + ``demos/shows``
at the same relative location.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

import yaml

# Display metadata per rig file stem. Anything on disk that isn't listed
# here still shows up, with a generic description.
_TEMPLATE_INFO = {
    'club_band': (
        "Club band",
        "4 front PARs, 2 rear washes, 2 movers, 1 blinder — the smallest viable rig",
    ),
    'band_midsize': (
        "Mid-size band",
        "PARs front + back, spots, moving wash, LED bars, blinders, matrix",
    ),
    'festival_mainstage': (
        "Festival mainstage",
        "Truss rows of washes / spots / beams, floor beams, side towers (3 universes)",
    ),
    'dj_edm': (
        "DJ / EDM",
        "Beam array, moving wash, pixel bars, matrix, strobes",
    ),
    'theatre_static': (
        "Static theatre",
        "Front PAR wash, rear cyc wash, side booms — no moving fixtures",
    ),
}


@dataclass
class ProjectTemplate:
    key: str                    # file stem, e.g. "club_band"
    name: str                   # display name
    description: str
    fixture_count: int
    rig_path: str               # rig-only config
    show_path: Optional[str]    # rig + demo show + audio ("" variant absent)


def templates_root() -> str:
    """The demos/ directory, in a dev checkout or a frozen bundle."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'demos'
    )


def _count_fixtures(config_path: str) -> int:
    try:
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f) or {}
        return len(data.get('fixtures', []))
    except Exception:
        return 0


def list_templates() -> List[ProjectTemplate]:
    """Every starter rig found under the templates root, display-sorted."""
    rigs_dir = os.path.join(templates_root(), 'rigs')
    shows_dir = os.path.join(templates_root(), 'shows')
    if not os.path.isdir(rigs_dir):
        return []

    templates = []
    for filename in sorted(os.listdir(rigs_dir)):
        # Bundled templates ship as .lms since 2026-07-16; .yaml stays
        # accepted so a user-provided legacy rig dropped in still lists.
        if not filename.endswith(('.lms', '.yaml')):
            continue
        key = os.path.splitext(filename)[0]
        rig_path = os.path.join(rigs_dir, filename)
        show_path = os.path.join(shows_dir, filename)
        name, description = _TEMPLATE_INFO.get(
            key, (key.replace('_', ' ').title(), "Starter rig")
        )
        templates.append(ProjectTemplate(
            key=key,
            name=name,
            description=description,
            fixture_count=_count_fixtures(rig_path),
            rig_path=rig_path,
            show_path=show_path if os.path.exists(show_path) else None,
        ))
    templates.sort(key=lambda t: t.fixture_count)
    return templates


def instantiate_template(template: ProjectTemplate, dest_config_path: str,
                         include_show: bool = True) -> str:
    """Copy the template to ``dest_config_path`` and return that path.

    include_show=True uses the demo-show variant (when the template has
    one) and copies its audio files into ``<dest_dir>/audiofiles/`` so
    the show's audio resolves via the new config's bundle dir. Existing
    audio files at the destination are left alone.

    Refuses to write inside the templates root — that would be editing
    the template itself, the exact thing this flow exists to prevent.
    """
    root = os.path.abspath(templates_root())
    dest_abs = os.path.abspath(dest_config_path)
    if dest_abs.startswith(root + os.sep):
        raise ValueError(
            "Choose a location outside the bundled templates directory."
        )

    use_show = include_show and template.show_path is not None
    source = template.show_path if use_show else template.rig_path
    os.makedirs(os.path.dirname(dest_abs) or '.', exist_ok=True)
    shutil.copyfile(source, dest_abs)

    if use_show:
        src_audio = os.path.join(os.path.dirname(template.show_path), 'audiofiles')
        if os.path.isdir(src_audio):
            dest_audio = os.path.join(os.path.dirname(dest_abs), 'audiofiles')
            os.makedirs(dest_audio, exist_ok=True)
            for audio_file in os.listdir(src_audio):
                dst = os.path.join(dest_audio, audio_file)
                if not os.path.exists(dst):
                    shutil.copy2(os.path.join(src_audio, audio_file), dst)

    return dest_abs
