"""Tests for core.index — .quickfindignore pattern matching."""

import sys
import os
import tempfile
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.cache as cache_mod
import core.index as index_mod
from core.index import FileEntry, FileIndex, NTFS_ROOT_FRN
from core.network_shares import network_source_key
from core.platform_engines import LinuxPlatformEngine, PlatformRoot
from core.ntfs import (
    DRIVE_FIXED, FILE_ATTRIBUTE_ARCHIVE, FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_REPARSE_POINT, DriveInfo,
    USN_REASON_CLOSE, USN_REASON_FILE_CREATE, USNRecord,
)


def test_usn_resume_decision_catchup_and_reindex():
    from core.index import _usn_resume_decision
    # Same journal, valid checkpoint above FirstUsn -> catch up.
    assert _usn_resume_decision(100, 5000, 100, 1000) == "catchup"
    # No FirstUsn known (0) -> catch up (can't prove a wrap).
    assert _usn_resume_decision(100, 5000, 100, 0) == "catchup"
    # Journal recreated (id changed) -> reindex.
    assert _usn_resume_decision(100, 5000, 999, 1000) == "reindex"
    # No saved checkpoint -> reindex.
    assert _usn_resume_decision(100, 0, 100, 1000) == "reindex"
    # Journal wrapped past our saved position (saved < FirstUsn) -> reindex.
    assert _usn_resume_decision(100, 500, 100, 1000) == "reindex"


def test_ntfs_volume_wrap_flags_default_clear():
    import core.ntfs as ntfs
    vol = ntfs.NTFSVolume("C")
    assert vol.journal_wrapped is False
    assert vol.first_usn == 0


def test_invalidate_subtree_paths_clears_descendants_only():
    # Tree: dir(10) -> sub(11) -> file(12); plus unrelated file(20).
    entries = {
        10: FileEntry(frn=10, parent_frn=5, name="Projects", drive="C",
                      attributes=FILE_ATTRIBUTE_DIRECTORY),
        11: FileEntry(frn=11, parent_frn=10, name="sub", drive="C",
                      attributes=FILE_ATTRIBUTE_DIRECTORY),
        12: FileEntry(frn=12, parent_frn=11, name="a.txt", drive="C",
                      attributes=FILE_ATTRIBUTE_ARCHIVE),
        20: FileEntry(frn=20, parent_frn=5, name="other.txt", drive="C",
                      attributes=FILE_ATTRIBUTE_ARCHIVE),
    }
    for e in entries.values():
        e._path = r"C:\stale\path"

    FileIndex._invalidate_subtree_paths(entries, 10)

    # Descendants of the renamed dir are cleared; the dir itself and unrelated
    # entries are untouched (the dir clears its own path separately).
    assert entries[11]._path is None
    assert entries[12]._path is None
    assert entries[10]._path == r"C:\stale\path"
    assert entries[20]._path == r"C:\stale\path"


class FakeStat:
    def __init__(self, attrs: int, dev: int = 1, ino: int = 1, size: int = 0):
        self.st_file_attributes = attrs
        self.st_dev = dev
        self.st_ino = ino
        self.st_size = size
        self.st_mtime = 1
        self.st_ctime = 1


class FakeDirEntry:
    def __init__(self, name: str, path: str, attrs: int,
                 entry_is_dir: bool, target_is_dir: bool, size: int = 0):
        self.name = name
        self.path = path
        self._attrs = attrs
        self._entry_is_dir = entry_is_dir
        self._target_is_dir = target_is_dir
        self._size = size

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self._target_is_dir if follow_symlinks else self._entry_is_dir

    def is_symlink(self) -> bool:
        return bool(self._attrs & FILE_ATTRIBUTE_REPARSE_POINT)

    def stat(self, follow_symlinks: bool = True) -> FakeStat:
        return FakeStat(self._attrs, size=self._size)


class FakeScandir:
    def __init__(self, entries: list[FakeDirEntry]):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def install_fake_walk(monkeypatch, tree: dict[str, list[FakeDirEntry]],
                      identities: dict[str, tuple[int, int]]):
    original_stat = os.stat
    monkeypatch.setattr(index_mod, "get_all_drives", lambda: [])
    monkeypatch.setattr(
        index_mod.FileIndex,
        "_load_ignore_patterns",
        staticmethod(lambda _path: []),
    )
    monkeypatch.setattr(index_mod.os.path, "exists", lambda path: path in tree)
    monkeypatch.setattr(
        index_mod.os,
        "scandir",
        lambda path: FakeScandir(tree.get(path, [])),
    )

    def fake_stat(path: str, *args, **kwargs):
        if path not in identities:
            return original_stat(path, *args, **kwargs)
        dev, ino = identities[path]
        return FakeStat(FILE_ATTRIBUTE_DIRECTORY, dev=dev, ino=ino)

    monkeypatch.setattr(index_mod.os, "stat", fake_stat)


class TestIgnorePatterns:
    def test_load_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            patterns = FileIndex._load_ignore_patterns(d)
            assert patterns == []

    def test_load_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            ignore = os.path.join(d, '.quickfindignore')
            with open(ignore, 'w') as f:
                f.write("node_modules\n*.pyc\n# comment\n\n.git\n")
            patterns = FileIndex._load_ignore_patterns(d)
            assert patterns == ["node_modules", "*.pyc", ".git"]

    def test_matches_exact(self):
        assert FileIndex._matches_ignore("node_modules", ["node_modules"]) is True
        assert FileIndex._matches_ignore("src", ["node_modules"]) is False

    def test_matches_glob(self):
        assert FileIndex._matches_ignore("test.pyc", ["*.pyc"]) is True
        assert FileIndex._matches_ignore("test.py", ["*.pyc"]) is False

    def test_matches_case_insensitive(self):
        assert FileIndex._matches_ignore("Thumbs.db", ["thumbs.db"]) is True
        assert FileIndex._matches_ignore("DESKTOP.INI", ["desktop.ini"]) is True

    def test_matches_question_mark(self):
        assert FileIndex._matches_ignore("test1.log", ["test?.log"]) is True
        assert FileIndex._matches_ignore("test12.log", ["test?.log"]) is False

    def test_no_patterns(self):
        assert FileIndex._matches_ignore("anything", []) is False


class TestExcludeRules:
    def test_should_exclude_by_attribute_mask(self):
        index = FileIndex()
        index.set_exclude_rules(attribute_mask=FILE_ATTRIBUTE_REPARSE_POINT)
        entry = FileEntry(
            10,
            NTFS_ROOT_FRN,
            "Link",
            "C",
            FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
        )

        assert index._should_exclude(entry) is True

    def test_should_exclude_by_glob_name_or_path(self):
        index = FileIndex()
        index.set_exclude_rules(globs=["*.tmp", "*\\build\\*"])

        temp_entry = FileEntry(10, NTFS_ROOT_FRN, "scratch.tmp", "C")
        path_entry = FileEntry(11, NTFS_ROOT_FRN, "main.py", "C")
        path_entry._path = "C:\\repo\\build\\main.py"
        keep_entry = FileEntry(12, NTFS_ROOT_FRN, "main.py", "C")
        keep_entry._path = "C:\\repo\\src\\main.py"

        assert index._should_exclude(temp_entry) is True
        assert index._should_exclude(path_entry) is True
        assert index._should_exclude(keep_entry) is False

    def test_should_exclude_by_regex_name_or_path(self):
        index = FileIndex()
        index.set_exclude_rules(regexes=[r"cache\d+", r"\\Generated\\"])
        cache_entry = FileEntry(10, NTFS_ROOT_FRN, "cache12.db", "C")
        generated_entry = FileEntry(11, NTFS_ROOT_FRN, "model.cs", "C")
        generated_entry._path = "C:\\repo\\Generated\\model.cs"

        assert index._should_exclude(cache_entry) is True
        assert index._should_exclude(generated_entry) is True

    def test_rebuild_flat_list_removes_excluded_entries(self):
        index = FileIndex()
        hidden_entry = FileEntry(10, NTFS_ROOT_FRN, "secret.txt", "C", FILE_ATTRIBUTE_HIDDEN)
        keep_entry = FileEntry(11, NTFS_ROOT_FRN, "visible.txt", "C", FILE_ATTRIBUTE_ARCHIVE)
        index._entries = {
            "C": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "C", FILE_ATTRIBUTE_DIRECTORY),
                10: hidden_entry,
                11: keep_entry,
            }
        }
        index.set_exclude_rules(attribute_mask=FILE_ATTRIBUTE_HIDDEN)

        index._rebuild_flat_list()

        assert index._all_entries == [keep_entry]

    def test_walk_drive_does_not_descend_excluded_directories(self, monkeypatch):
        root = "E:\\"
        build = "E:\\build"
        child = "E:\\build\\child.txt"
        tree = {
            root: [FakeDirEntry("build", build, FILE_ATTRIBUTE_DIRECTORY, True, True)],
            build: [FakeDirEntry("child.txt", child, FILE_ATTRIBUTE_ARCHIVE, False, False, size=4)],
        }
        install_fake_walk(monkeypatch, tree, {root: (1, 1)})

        index = FileIndex()
        index.set_exclude_rules(globs=["build"])
        count = index._walk_drive("E")
        names = {entry.name for entry in index._entries["E"].values()}

        assert count == 0
        assert "build" not in names
        assert "child.txt" not in names

    def test_index_network_roots_walks_unc_source(self, monkeypatch):
        root = "\\\\server\\share"
        folder = "\\\\server\\share\\Folder"
        child = "\\\\server\\share\\Folder\\child.txt"
        tree = {
            root: [FakeDirEntry("Folder", folder, FILE_ATTRIBUTE_DIRECTORY, True, True)],
            folder: [FakeDirEntry("child.txt", child, FILE_ATTRIBUTE_ARCHIVE, False, False, size=4)],
        }
        install_fake_walk(monkeypatch, tree, {root: (2, 1), folder: (2, 2)})
        monkeypatch.setattr(index_mod, "connect_network_share", lambda _root: False)

        index = FileIndex()
        indexed = index.index_network_roots([root])
        source = network_source_key(root)
        paths = {
            entry._path
            for entry in index._entries[source].values()
            if entry.name
        }

        assert indexed == [source]
        assert source not in index._walked_drives
        assert child in paths


class TestIndexMode:
    def test_full_index_resets_admin_mode(self, monkeypatch):
        index = FileIndex()
        index._admin_mode = False
        monkeypatch.setattr(index_mod, "get_all_drives", lambda: [])

        index.index_all_drives(drives=[])

        assert index.is_admin_mode is True

    def test_force_walk_reports_non_admin_mode(self, monkeypatch):
        index = FileIndex()
        monkeypatch.setattr(index_mod, "get_all_drives", lambda: [])

        index.index_all_drives(drives=[], force_walk=True)

        assert index.is_admin_mode is False

    def test_index_diagnostics_reports_drive_modes_and_usn(self):
        index = FileIndex()
        file_entry = FileEntry(10, NTFS_ROOT_FRN, "file.txt", "C")
        folder_entry = FileEntry(20, NTFS_ROOT_FRN, "Docs", "E", FILE_ATTRIBUTE_DIRECTORY)
        index._entries = {
            "C": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "C", FILE_ATTRIBUTE_DIRECTORY),
                10: file_entry,
            },
            "E": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "E", FILE_ATTRIBUTE_DIRECTORY),
                20: folder_entry,
            },
        }
        index._all_entries = [file_entry, folder_entry]
        index._stats.total_files = 1
        index._stats.total_folders = 1
        index._volumes["C"] = type("Volume", (), {"journal_id": 7, "current_usn": 99})()
        index._walked_drives.add("E")
        index.set_external_source("EFU file list: sample.efu")

        diagnostics = index.index_diagnostics()
        drives = {row["drive"]: row for row in diagnostics["drives"]}

        assert diagnostics["source"] == "EFU file list: sample.efu"
        assert diagnostics["total_entries"] == 2
        assert drives["C"]["mode"] == "MFT + USN"
        assert drives["C"]["journal_id"] == 7
        assert drives["C"]["next_usn"] == 99
        assert drives["E"]["mode"] == "os.scandir"
        assert drives["E"]["folders"] == 1

    def test_apply_usn_changes_persists_checkpoint_after_successful_batch(self, monkeypatch, tmp_path):
        cache_mod._close_connection()
        monkeypatch.setattr(cache_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "DB_FILE", tmp_path / "index.db")
        monkeypatch.setattr(cache_mod, "OLD_CACHE_FILE", tmp_path / "index_cache.bin")
        conn = cache_mod._get_connection()
        cache_mod._init_schema(conn)
        conn.execute(
            "INSERT INTO drives (letter, flags, journal_id, next_usn) VALUES (?, ?, ?, ?)",
            ("C", 0, 1, 10),
        )
        conn.commit()

        index = FileIndex()
        index._entries = {
            "C": {
                NTFS_ROOT_FRN: FileEntry(
                    NTFS_ROOT_FRN,
                    0,
                    "",
                    "C",
                    FILE_ATTRIBUTE_DIRECTORY,
                )
            }
        }
        index._volumes["C"] = type("Volume", (), {"journal_id": 99, "current_usn": 250})()
        record = USNRecord(
            usn=200,
            frn=42,
            parent_frn=NTFS_ROOT_FRN,
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
            reason=USN_REASON_FILE_CREATE | USN_REASON_CLOSE,
            attributes=FILE_ATTRIBUTE_ARCHIVE,
            name="new.txt",
        )

        index._apply_usn_changes([("C", record)])

        row = conn.execute("SELECT journal_id, next_usn FROM drives WHERE letter='C'").fetchone()
        entry_row = conn.execute("SELECT name FROM entries WHERE drive='C' AND frn=42").fetchone()
        cache_mod._close_connection()
        assert tuple(row) == (99, 250)
        assert tuple(entry_row) == ("new.txt",)

    def test_apply_usn_changes_does_not_checkpoint_failed_batch(self, monkeypatch):
        index = FileIndex()
        index._entries = {
            "C": {
                NTFS_ROOT_FRN: FileEntry(
                    NTFS_ROOT_FRN,
                    0,
                    "",
                    "C",
                    FILE_ATTRIBUTE_DIRECTORY,
                )
            }
        }
        index._volumes["C"] = type("Volume", (), {"journal_id": 99, "current_usn": 250})()
        checkpoint_calls = []
        monkeypatch.setattr(cache_mod, "db_batch_apply", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(
            cache_mod,
            "db_update_usn_position",
            lambda *args: checkpoint_calls.append(args) or True,
        )
        record = USNRecord(
            usn=200,
            frn=42,
            parent_frn=NTFS_ROOT_FRN,
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
            reason=USN_REASON_FILE_CREATE | USN_REASON_CLOSE,
            attributes=FILE_ATTRIBUTE_ARCHIVE,
            name="new.txt",
        )

        index._apply_usn_changes([("C", record)])

        assert checkpoint_calls == []

    def test_cached_drive_states_mark_offline_drives_stale(self, monkeypatch):
        index = FileIndex()
        index._entries = {
            "C": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "C", FILE_ATTRIBUTE_DIRECTORY),
                10: FileEntry(10, NTFS_ROOT_FRN, "file.txt", "C"),
            },
            "E": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "E", FILE_ATTRIBUTE_DIRECTORY),
                20: FileEntry(20, NTFS_ROOT_FRN, "offline.txt", "E"),
            },
        }
        monkeypatch.setattr(
            index_mod,
            "get_all_drives",
            lambda: [DriveInfo("C", "NTFS", DRIVE_FIXED, "System")],
        )

        index._mark_cached_drive_states(["C", "E"])

        drives = {row["drive"]: row for row in index.drive_diagnostics()}
        assert drives["C"]["state"] == "stale"
        assert drives["C"]["online"] is True
        assert drives["E"]["state"] == "offline"
        assert drives["E"]["stale"] is True
        assert "cached results" in drives["E"]["stale_reason"]

    def test_walk_drive_preserves_cached_entries_when_drive_missing(self, monkeypatch):
        index = FileIndex()
        cached_entry = FileEntry(20, NTFS_ROOT_FRN, "offline.txt", "E")
        index._entries = {
            "E": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "E", FILE_ATTRIBUTE_DIRECTORY),
                20: cached_entry,
            }
        }
        index._all_entries = [cached_entry]
        monkeypatch.setattr(
            index_mod.os.path,
            "exists",
            lambda path: False if path == "E:\\" else True,
        )

        count = index._walk_drive("E")

        assert count == 2
        assert index._entries["E"][20] is cached_entry
        drive = index.drive_diagnostics()[0]
        assert drive["state"] == "offline"
        assert drive["stale"] is True

    def test_walk_drive_skips_reparse_descendants_by_default(self, monkeypatch):
        root = "E:\\"
        link = "E:\\Link"
        child = "E:\\Link\\child.txt"
        reparse_dir = FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT
        tree = {
            root: [FakeDirEntry("Link", link, reparse_dir, True, True)],
            link: [FakeDirEntry("child.txt", child, FILE_ATTRIBUTE_ARCHIVE, False, False, size=4)],
        }
        install_fake_walk(monkeypatch, tree, {root: (1, 1), link: (1, 2)})

        index = FileIndex()
        count = index._walk_drive("E")
        names = {entry.name for entry in index._entries["E"].values()}

        assert count == 1
        assert "Link" in names
        assert "child.txt" not in names

    def test_walk_drive_follows_reparse_dirs_when_enabled(self, monkeypatch):
        root = "E:\\"
        link = "E:\\Link"
        child = "E:\\Link\\child.txt"
        reparse_dir = FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT
        tree = {
            root: [FakeDirEntry("Link", link, reparse_dir, True, True)],
            link: [FakeDirEntry("child.txt", child, FILE_ATTRIBUTE_ARCHIVE, False, False, size=4)],
        }
        install_fake_walk(monkeypatch, tree, {root: (1, 1), link: (1, 2)})

        index = FileIndex()
        index._follow_reparse_points = True
        count = index._walk_drive("E")
        names = {entry.name for entry in index._entries["E"].values()}

        assert count == 2
        assert "Link" in names
        assert "child.txt" in names

    def test_walk_drive_does_not_follow_reparse_loops(self, monkeypatch):
        root = "E:\\"
        loop = "E:\\Loop"
        child = "E:\\Loop\\child.txt"
        reparse_dir = FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT
        tree = {
            root: [FakeDirEntry("Loop", loop, reparse_dir, True, True)],
            loop: [FakeDirEntry("child.txt", child, FILE_ATTRIBUTE_ARCHIVE, False, False, size=4)],
        }
        install_fake_walk(monkeypatch, tree, {root: (1, 1), loop: (1, 1)})

        index = FileIndex()
        index._follow_reparse_points = True
        count = index._walk_drive("E")
        names = {entry.name for entry in index._entries["E"].values()}

        assert count == 1
        assert "Loop" in names
        assert "child.txt" not in names

    def test_platform_root_walk_uses_posix_source_key_and_absolute_paths(self, monkeypatch):
        root = "/home/user"
        docs = "/home/user/docs"
        child = "/home/user/docs/readme.txt"
        tree = {
            root: [FakeDirEntry("docs", docs, 0, True, True)],
            docs: [FakeDirEntry("readme.txt", child, 0, False, False, size=4)],
        }
        install_fake_walk(monkeypatch, tree, {root: (3, 1), docs: (3, 2)})

        index = FileIndex()
        index._platform_engine = LinuxPlatformEngine()
        platform_root = PlatformRoot(
            key="POSIX:TEST",
            path=root,
            label="user",
            filesystem="Linux filesystem",
            watcher="inotify",
        )

        count = index._walk_platform_root(platform_root)
        paths = {entry.get_path(index) for entry in index._entries["POSIX:TEST"].values()}
        diagnostics = {row["drive"]: row for row in index.drive_diagnostics()}

        assert count == 2
        assert child in paths
        assert index.resolve_parent_path("POSIX:TEST", NTFS_ROOT_FRN) == root
        assert diagnostics["POSIX:TEST"]["mode"] == "inotify + os.scandir"
