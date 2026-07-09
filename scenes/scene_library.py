# scenes/scene_library.py
"""SceneLibrary - manages the collection of available whole-rig scenes.

Parallel to :class:`riffs.riff_library.RiffLibrary` but for scenes. A
:class:`config.models.Scene` is a static full-rig look that spans several
fixture groups; the library loads them from category subdirectories of
JSON files. Predefined scenes are authored later, so a missing directory
yields an empty library rather than a crash.
"""

import os
import json
from typing import Dict, List, Optional

from config.models import Scene


class SceneLibrary:
    """Manages the collection of available scenes."""

    def __init__(self, scenes_directory: str = None):
        """Initialize the scene library.

        Args:
            scenes_directory: Path to scenes directory. If None, uses the
                default 'scenes' folder at the project root.
        """
        if scenes_directory is None:
            # Default to 'scenes' folder relative to project root.
            scenes_directory = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'scenes'
            )
        self.scenes_dir = scenes_directory
        self.scenes: Dict[str, Scene] = {}  # "category/name" -> Scene
        self._load_all_scenes()

    def _load_all_scenes(self):
        """Scan the scenes directory and load all JSON files."""
        self.scenes.clear()

        if not os.path.exists(self.scenes_dir):
            # No scenes authored yet - stay empty, do not crash.
            return

        for category_name in os.listdir(self.scenes_dir):
            category_path = os.path.join(self.scenes_dir, category_name)

            # Skip non-directories and special files.
            if not os.path.isdir(category_path):
                continue
            if category_name.startswith('_') or category_name.startswith('.'):
                continue

            for filename in os.listdir(category_path):
                if not filename.endswith('.json'):
                    continue

                filepath = os.path.join(category_path, filename)
                scene = self.load_scene(filepath)
                if scene:
                    # Use category from directory, not from file.
                    scene.category = category_name
                    key = f"{category_name}/{scene.name}"
                    self.scenes[key] = scene

    def load_scene(self, filepath: str) -> Optional[Scene]:
        """Load a single scene from a JSON file.

        Returns the Scene, or None if loading failed.
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Scene.from_dict(data)
        except json.JSONDecodeError as e:
            print(f"Error parsing scene file {filepath}: {e}")
            return None
        except Exception as e:
            print(f"Error loading scene file {filepath}: {e}")
            return None

    def add_scene(self, scene: Scene, category: str = "general") -> None:
        """Register a scene under a category (in-memory, no file write)."""
        scene.category = category
        key = f"{category}/{scene.name}"
        self.scenes[key] = scene

    def get_scene(self, key: str) -> Optional[Scene]:
        """Get a scene by its "category/name" key, or None."""
        return self.scenes.get(key)

    def get_all_scenes(self) -> List[Scene]:
        """All scenes, sorted by (category, name)."""
        return sorted(self.scenes.values(), key=lambda s: (s.category, s.name))

    def scene_count(self) -> int:
        """Number of scenes in the library."""
        return len(self.scenes)

    def has_scene(self, key: str) -> bool:
        """Whether a scene exists for the given key."""
        return key in self.scenes

    def __len__(self) -> int:
        return len(self.scenes)

    def __contains__(self, key: str) -> bool:
        return key in self.scenes
