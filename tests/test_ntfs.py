"""Tests for core.ntfs — MFT record parsing, FILETIME conversion, USA fixup."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import struct
import pytest
import core.ntfs as ntfs
from datetime import datetime, timezone
from core.ntfs import (
    filetime_to_datetime, _apply_usa_fixup, _parse_mft_record,
    FileRecord, USNRecord, VolumeInfo, DriveInfo,
    MFT_SIGNATURE, ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME,
    ATTR_DATA, ATTR_END_MARKER,
    FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_REPARSE_POINT,
    FILENAME_WIN32, FILENAME_DOS, FILENAME_WIN32_DOS,
    USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_CLOSE, USN_REASON_DATA_OVERWRITE,
    FILETIME_EPOCH,
)


class TestFiletimeToDatetime:
    def test_zero(self):
        assert filetime_to_datetime(0) is None

    def test_negative(self):
        assert filetime_to_datetime(-1) is None

    def test_known_epoch(self):
        ft = 132514560000000000  # 2021-01-01 00:00:00 UTC
        result = filetime_to_datetime(ft)
        assert result is not None
        assert result.year == 2021 or result.year == 2020  # timezone shift possible

    def test_returns_naive_datetime(self):
        ft = 132514560000000000
        result = filetime_to_datetime(ft)
        assert result is not None
        assert result.tzinfo is None

    def test_very_large_value(self):
        result = filetime_to_datetime(0x7FFFFFFFFFFFFFFF)
        assert result is None  # overflow expected


class TestApplyUsaFixup:
    def _make_record(self, sector_size=512, record_size=1024):
        data = bytearray(record_size)
        data[0:4] = MFT_SIGNATURE
        usa_offset = 48
        usa_entries = record_size // sector_size + 1
        struct.pack_into('<H', data, 4, usa_offset)
        struct.pack_into('<H', data, 6, usa_entries)

        check_value = b'\xAA\xBB'
        data[usa_offset:usa_offset + 2] = check_value

        for i in range(1, usa_entries):
            sector_end = i * sector_size - 2
            data[sector_end:sector_end + 2] = check_value
            original = bytes([0x10 + i, 0x20 + i])
            data[usa_offset + i * 2:usa_offset + i * 2 + 2] = original

        return data

    def test_valid_fixup(self):
        data = self._make_record()
        assert _apply_usa_fixup(data, 512) is True
        assert data[510:512] == bytes([0x11, 0x21])

    def test_bad_signature(self):
        data = self._make_record()
        data[0:4] = b'BAAD'
        assert _apply_usa_fixup(data, 512) is False

    def test_too_short(self):
        data = bytearray(10)
        assert _apply_usa_fixup(data, 512) is False

    def test_torn_write_detection(self):
        data = self._make_record()
        data[510:512] = b'\xFF\xFF'  # corrupt sector end
        assert _apply_usa_fixup(data, 512) is False


class TestFileRecord:
    def test_is_dir(self):
        rec = FileRecord(frn=10, parent_frn=5, name="folder",
                         attributes=FILE_ATTRIBUTE_DIRECTORY)
        assert rec.is_dir is True

    def test_is_not_dir(self):
        rec = FileRecord(frn=10, parent_frn=5, name="file.txt",
                         attributes=FILE_ATTRIBUTE_ARCHIVE)
        assert rec.is_dir is False

    def test_is_hidden(self):
        rec = FileRecord(frn=10, parent_frn=5, name="hidden",
                         attributes=FILE_ATTRIBUTE_HIDDEN)
        assert rec.is_hidden is True

    def test_is_system(self):
        rec = FileRecord(frn=10, parent_frn=5, name="sys",
                         attributes=FILE_ATTRIBUTE_SYSTEM)
        assert rec.is_system is True

    def test_is_readonly(self):
        rec = FileRecord(frn=10, parent_frn=5, name="readonly",
                         attributes=0x01)
        assert rec.is_readonly is True

    def test_is_compressed(self):
        rec = FileRecord(frn=10, parent_frn=5, name="compressed",
                         attributes=0x800)
        assert rec.is_compressed is True

    def test_is_encrypted(self):
        rec = FileRecord(frn=10, parent_frn=5, name="encrypted",
                         attributes=0x4000)
        assert rec.is_encrypted is True

    def test_reparse_and_extended_attribute_metadata(self):
        rec = FileRecord(
            frn=10,
            parent_frn=5,
            name="link",
            attributes=FILE_ATTRIBUTE_REPARSE_POINT,
            reparse_tag=0xA000000C,
            has_extended_attributes=True,
        )

        assert rec.is_reparse_point is True
        assert rec.reparse_tag == 0xA000000C
        assert rec.has_extended_attributes is True


class TestUSNRecord:
    def _make(self, reason=0):
        return USNRecord(usn=100, frn=10, parent_frn=5,
                         timestamp=None, reason=reason,
                         attributes=0, name="test.txt")

    def test_is_create(self):
        assert self._make(USN_REASON_FILE_CREATE).is_create is True
        assert self._make(USN_REASON_CLOSE).is_create is False

    def test_is_delete(self):
        assert self._make(USN_REASON_FILE_DELETE).is_delete is True

    def test_is_rename(self):
        assert self._make(USN_REASON_RENAME_OLD_NAME).is_rename is True
        assert self._make(USN_REASON_RENAME_NEW_NAME).is_rename is True

    def test_is_close(self):
        assert self._make(USN_REASON_CLOSE).is_close is True

    def test_is_modify(self):
        assert self._make(USN_REASON_DATA_OVERWRITE).is_modify is True


class TestDriveInfo:
    def test_is_ntfs(self):
        d = DriveInfo(letter='C', filesystem='NTFS', drive_type=3)
        assert d.is_ntfs is True
        assert d.is_fat is False
        assert d.needs_walk is False

    def test_is_fat32(self):
        d = DriveInfo(letter='D', filesystem='FAT32', drive_type=2)
        assert d.is_fat is True
        assert d.is_ntfs is False
        assert d.needs_walk is True

    def test_is_refs(self):
        d = DriveInfo(letter='E', filesystem='ReFS', drive_type=3)
        assert d.is_refs is True
        assert d.needs_walk is True

    def test_is_exfat(self):
        d = DriveInfo(letter='F', filesystem='exFAT', drive_type=2)
        assert d.is_fat is True


class TestBackupPrivilegeScope:
    def test_reference_counts_parallel_mft_scans(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ntfs, "_backup_privilege_enabled", False)
        monkeypatch.setattr(ntfs, "_backup_privilege_users", 0)
        monkeypatch.setattr(ntfs, "_set_backup_privilege", lambda enabled: calls.append(enabled) or True)

        with ntfs._backup_privilege_scope() as outer_acquired:
            assert outer_acquired is True
            assert ntfs._backup_privilege_enabled is True
            assert ntfs._backup_privilege_users == 1
            assert calls == [True]

            with ntfs._backup_privilege_scope() as inner_acquired:
                assert inner_acquired is True
                assert ntfs._backup_privilege_users == 2
                assert calls == [True]

            assert ntfs._backup_privilege_enabled is True
            assert ntfs._backup_privilege_users == 1
            assert calls == [True]

        assert ntfs._backup_privilege_enabled is False
        assert ntfs._backup_privilege_users == 0
        assert calls == [True, False]

    def test_failed_enable_does_not_schedule_disable(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ntfs, "_backup_privilege_enabled", False)
        monkeypatch.setattr(ntfs, "_backup_privilege_users", 0)
        monkeypatch.setattr(ntfs, "_set_backup_privilege", lambda enabled: calls.append(enabled) or False)

        with ntfs._backup_privilege_scope() as acquired:
            assert acquired is False

        assert ntfs._backup_privilege_enabled is False
        assert ntfs._backup_privilege_users == 0
        assert calls == [True]

    def test_direct_mft_open_failure_releases_privilege_before_fallback(self, monkeypatch):
        calls = []
        volume = ntfs.NTFSVolume("C")

        monkeypatch.setattr(ntfs, "_backup_privilege_enabled", False)
        monkeypatch.setattr(ntfs, "_backup_privilege_users", 0)
        monkeypatch.setattr(ntfs, "_set_backup_privilege", lambda enabled: calls.append(enabled) or True)
        monkeypatch.setattr(ntfs.ctypes, "get_last_error", lambda: 5)
        monkeypatch.setattr(
            volume,
            "get_volume_info",
            lambda: VolumeInfo(drive_letter="C", bytes_per_file_record=1024, bytes_per_sector=512),
        )
        monkeypatch.setattr(ntfs, "CreateFileW", lambda *args: ntfs.INVALID_HANDLE_VALUE)

        def fallback_enumerate_mft(callback=None, cancel_check=None):
            assert ntfs._backup_privilege_enabled is False
            assert ntfs._backup_privilege_users == 0
            yield FileRecord(frn=1, parent_frn=0, name="fallback.txt")

        monkeypatch.setattr(volume, "enumerate_mft", fallback_enumerate_mft)

        records = list(volume.enumerate_mft_direct())

        assert [record.name for record in records] == ["fallback.txt"]
        assert calls == [True, False]
