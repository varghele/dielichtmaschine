# riffs/riff_library.py
"""RiffLibrary - manages the collection of available riffs."""

import os
import json
from typing import Dict, List, Optional
from config.models import Riff, FixtureGroup


def parse_tags(text: str) -> List[str]:
    """Comma-separated user input -> a clean tag list.

    Strips whitespace and leading '#', drops empties, deduplicates
    case-insensitively while keeping the first spelling and the input
    order ('Chorus, punchy, #chorus' -> ['Chorus', 'punchy'])."""
    tags: List[str] = []
    for part in (text or "").split(","):
        tag = part.strip().lstrip("#").strip()
        if tag and tag.lower() not in (t.lower() for t in tags):
            tags.append(tag)
    return tags


class RiffLibrary:
    """Manages the collection of available riffs."""

    def __init__(self, riffs_directory: str = None):
        """Initialize the riff library.

        Args:
            riffs_directory: Path to riffs directory. If None, uses default 'riffs' folder.
        """
        if riffs_directory is None:
            # Default to 'riffs' folder relative to project root
            riffs_directory = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'riffs'
            )
        self.riffs_dir = riffs_directory
        self.riffs: Dict[str, Riff] = {}  # "category/name" -> Riff
        self.by_category: Dict[str, List[Riff]] = {}
        self._load_all_riffs()

    def _load_all_riffs(self):
        """Scan riffs directory and load all JSON files."""
        self.riffs.clear()
        self.by_category.clear()

        if not os.path.exists(self.riffs_dir):
            print(f"Riffs directory not found: {self.riffs_dir}")
            return

        # Scan each category directory
        for category_name in os.listdir(self.riffs_dir):
            category_path = os.path.join(self.riffs_dir, category_name)

            # Skip non-directories and special files
            if not os.path.isdir(category_path):
                continue
            if category_name.startswith('_') or category_name.startswith('.'):
                continue

            # Initialize category
            if category_name not in self.by_category:
                self.by_category[category_name] = []

            # Load all JSON files in category
            for filename in os.listdir(category_path):
                if not filename.endswith('.json'):
                    continue

                filepath = os.path.join(category_path, filename)
                riff = self.load_riff(filepath)
                if riff:
                    # Use category from directory, not from file
                    riff.category = category_name
                    key = f"{category_name}/{riff.name}"
                    self.riffs[key] = riff
                    self.by_category[category_name].append(riff)

        # Sort riffs by name within each category
        for category in self.by_category:
            self.by_category[category].sort(key=lambda r: r.name)

    def load_riff(self, filepath: str) -> Optional[Riff]:
        """Load single riff from JSON file.

        Args:
            filepath: Path to JSON file

        Returns:
            Riff object or None if loading failed
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Riff.from_dict(data)
        except json.JSONDecodeError as e:
            print(f"Error parsing riff file {filepath}: {e}")
            return None
        except Exception as e:
            print(f"Error loading riff file {filepath}: {e}")
            return None

    def save_riff(self, riff: Riff, category: str = None) -> str:
        """Save riff to JSON file.

        Args:
            riff: Riff object to save
            category: Category to save under (defaults to riff.category)

        Returns:
            Filepath where riff was saved
        """
        if category is None:
            category = riff.category or "custom"

        # Ensure category directory exists
        category_path = os.path.join(self.riffs_dir, category)
        os.makedirs(category_path, exist_ok=True)

        # Generate filename from riff name
        safe_name = riff.name.replace(' ', '_').replace('/', '_')
        filename = f"{safe_name}.json"
        filepath = os.path.join(category_path, filename)

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(riff.to_dict(), f, indent=2)

        # Update internal registry
        riff.category = category
        key = f"{category}/{riff.name}"
        self.riffs[key] = riff

        if category not in self.by_category:
            self.by_category[category] = []
        if riff not in self.by_category[category]:
            self.by_category[category].append(riff)
            self.by_category[category].sort(key=lambda r: r.name)

        return filepath

    def get_riff(self, riff_path: str) -> Optional[Riff]:
        """Get a riff by its path.

        Args:
            riff_path: Path like "category/name"

        Returns:
            Riff object or None if not found
        """
        return self.riffs.get(riff_path)

    def get_compatible_riffs(self, fixture_group: FixtureGroup) -> List[Riff]:
        """Get all riffs compatible with fixture group's capabilities.

        Args:
            fixture_group: The fixture group to check compatibility for

        Returns:
            List of compatible Riff objects
        """
        compatible = []
        for riff in self.riffs.values():
            is_compatible, _ = riff.is_compatible_with(fixture_group)
            if is_compatible:
                compatible.append(riff)
        return sorted(compatible, key=lambda r: (r.category, r.name))

    def get_categories(self) -> List[str]:
        """Get list of category names.

        Returns:
            Sorted list of category names
        """
        return sorted(self.by_category.keys())

    def get_riffs_in_category(self, category: str) -> List[Riff]:
        """Get all riffs in a category.

        Args:
            category: Category name

        Returns:
            List of Riff objects in the category
        """
        return self.by_category.get(category, [])

    def search(self, query: str, fixture_group: FixtureGroup = None) -> List[Riff]:
        """Search riffs by name, description, or tags.

        Args:
            query: Search query string
            fixture_group: Optional fixture group to filter by compatibility

        Returns:
            List of matching Riff objects
        """
        query_lower = query.lower()
        # A leading '#' scopes the query to TAGS ONLY ('#chorus' finds
        # riffs tagged chorus without dragging in every riff whose name
        # happens to contain the word).
        tags_only = query_lower.startswith("#")
        if tags_only:
            query_lower = query_lower[1:].strip()
        results = []

        for riff in self.riffs.values():
            # Check compatibility filter
            if fixture_group:
                is_compatible, _ = riff.is_compatible_with(fixture_group)
                if not is_compatible:
                    continue

            tag_hit = any(query_lower in tag.lower() for tag in riff.tags)
            if tags_only:
                if query_lower and tag_hit:
                    results.append(riff)
                continue

            # Search in name, description, and tags
            if query_lower in riff.name.lower():
                results.append(riff)
            elif query_lower in riff.description.lower():
                results.append(riff)
            elif tag_hit:
                results.append(riff)

        return sorted(results, key=lambda r: (r.category, r.name))

    def refresh(self):
        """Reload all riffs from disk."""
        self._load_all_riffs()

    def delete_riff(self, riff_path: str) -> bool:
        """Delete a riff from the library.

        Args:
            riff_path: Path like "category/name"

        Returns:
            True if deleted, False if not found
        """
        if riff_path not in self.riffs:
            return False

        riff = self.riffs[riff_path]
        category = riff.category

        # Build file path
        safe_name = riff.name.replace(' ', '_').replace('/', '_')
        filename = f"{safe_name}.json"
        filepath = os.path.join(self.riffs_dir, category, filename)

        # Delete file if exists
        if os.path.exists(filepath):
            os.remove(filepath)

        # Remove from registry
        del self.riffs[riff_path]
        if category in self.by_category:
            self.by_category[category] = [
                r for r in self.by_category[category] if r.name != riff.name
            ]

        return True

    def get_all_riffs(self) -> List[Riff]:
        """Get all riffs in the library.

        Returns:
            List of all Riff objects
        """
        return sorted(self.riffs.values(), key=lambda r: (r.category, r.name))

    def __len__(self) -> int:
        """Return number of riffs in library."""
        return len(self.riffs)

    def __contains__(self, riff_path: str) -> bool:
        """Check if riff exists in library."""
        return riff_path in self.riffs
