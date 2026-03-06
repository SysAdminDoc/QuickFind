"""
Per-filter hidden paths manager.
Stores directories and files to exclude from search results, keyed by filter name.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger('QuickFind.HiddenPaths')

CONFIG_DIR = Path.home() / '.quickfind'
HIDDEN_PATHS_FILE = CONFIG_DIR / 'hidden_paths.json'


class HiddenPathsManager:
    """Manages hidden paths per filter category."""

    def __init__(self):
        self._data: dict[str, list[str]] = {}
        self._load()

    def _load(self):
        if not HIDDEN_PATHS_FILE.exists():
            self._data = {}
            return
        try:
            with open(HIDDEN_PATHS_FILE, 'r') as f:
                self._data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load hidden paths: {e}")
            self._data = {}

    def _save(self):
        CONFIG_DIR.mkdir(exist_ok=True)
        try:
            with open(HIDDEN_PATHS_FILE, 'w') as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save hidden paths: {e}")

    def get_paths(self, filter_name: str) -> list[str]:
        return list(self._data.get(filter_name, []))

    def get_all(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._data.items()}

    def add_path(self, filter_name: str, path: str):
        if filter_name not in self._data:
            self._data[filter_name] = []
        normalized = path.replace('/', '\\')
        if normalized not in self._data[filter_name]:
            self._data[filter_name].append(normalized)
            self._save()

    def remove_path(self, filter_name: str, path: str):
        if filter_name in self._data:
            normalized = path.replace('/', '\\')
            try:
                self._data[filter_name].remove(normalized)
            except ValueError:
                pass
            if not self._data[filter_name]:
                del self._data[filter_name]
            self._save()

    def set_paths(self, filter_name: str, paths: list[str]):
        if paths:
            self._data[filter_name] = [p.replace('/', '\\') for p in paths]
        elif filter_name in self._data:
            del self._data[filter_name]
        self._save()

    def clear_filter(self, filter_name: str):
        if filter_name in self._data:
            del self._data[filter_name]
            self._save()

    def filter_names(self) -> list[str]:
        return list(self._data.keys())
