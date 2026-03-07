"""
NTFS MFT Enumeration and USN Journal Monitor via ctypes.

Reads the NTFS Master File Table to enumerate all files/folders on a volume,
then monitors the USN Change Journal for real-time filesystem updates.
Requires admin privileges for raw volume access.
"""

import ctypes
import ctypes.wintypes as wintypes
import struct
import string
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable

logger = logging.getLogger('QuickFind.NTFS')

# ── Win32 Constants ─────────────────────────────────────────────────
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# FSCTL codes
FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064
FSCTL_ENUM_USN_DATA = 0x000900B3
FSCTL_QUERY_USN_JOURNAL = 0x000900F4
FSCTL_READ_USN_JOURNAL = 0x000900BB
FSCTL_CREATE_USN_JOURNAL = 0x000900E7

# File attributes
FILE_ATTRIBUTE_READONLY = 0x00000001
FILE_ATTRIBUTE_HIDDEN = 0x00000002
FILE_ATTRIBUTE_SYSTEM = 0x00000004
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_ARCHIVE = 0x00000020
FILE_ATTRIBUTE_DEVICE = 0x00000040
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_TEMPORARY = 0x00000100
FILE_ATTRIBUTE_SPARSE_FILE = 0x00000200
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_COMPRESSED = 0x00000800
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 0x00002000
FILE_ATTRIBUTE_ENCRYPTED = 0x00004000

# USN reason flags
USN_REASON_DATA_OVERWRITE = 0x00000001
USN_REASON_DATA_EXTEND = 0x00000002
USN_REASON_DATA_TRUNCATION = 0x00000004
USN_REASON_NAMED_DATA_OVERWRITE = 0x00000010
USN_REASON_NAMED_DATA_EXTEND = 0x00000020
USN_REASON_NAMED_DATA_TRUNCATION = 0x00000040
USN_REASON_FILE_CREATE = 0x00000100
USN_REASON_FILE_DELETE = 0x00000200
USN_REASON_EA_CHANGE = 0x00000400
USN_REASON_SECURITY_CHANGE = 0x00000800
USN_REASON_RENAME_OLD_NAME = 0x00001000
USN_REASON_RENAME_NEW_NAME = 0x00002000
USN_REASON_INDEXABLE_CHANGE = 0x00004000
USN_REASON_BASIC_INFO_CHANGE = 0x00008000
USN_REASON_HARD_LINK_CHANGE = 0x00010000
USN_REASON_COMPRESSION_CHANGE = 0x00020000
USN_REASON_ENCRYPTION_CHANGE = 0x00040000
USN_REASON_OBJECT_ID_CHANGE = 0x00080000
USN_REASON_REPARSE_POINT_CHANGE = 0x00100000
USN_REASON_STREAM_CHANGE = 0x00200000
USN_REASON_CLOSE = 0x80000000

# ── Win32 API setup ─────────────────────────────────────────────────
kernel32 = ctypes.windll.kernel32
CreateFileW = kernel32.CreateFileW
CreateFileW.restype = wintypes.HANDLE
CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
]

DeviceIoControl = kernel32.DeviceIoControl
DeviceIoControl.restype = wintypes.BOOL
DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p
]

CloseHandle = kernel32.CloseHandle
CloseHandle.restype = wintypes.BOOL
CloseHandle.argtypes = [wintypes.HANDLE]

# Privilege management for $MFT access
advapi32 = ctypes.windll.advapi32

OpenProcessToken = advapi32.OpenProcessToken
OpenProcessToken.restype = wintypes.BOOL
OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]

LookupPrivilegeValueW = advapi32.LookupPrivilegeValueW
LookupPrivilegeValueW.restype = wintypes.BOOL
LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]

AdjustTokenPrivileges = advapi32.AdjustTokenPrivileges
AdjustTokenPrivileges.restype = wintypes.BOOL
AdjustTokenPrivileges.argtypes = [
    wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p,
    wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p
]

GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.restype = wintypes.HANDLE

TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002

_backup_privilege_enabled = False


def _enable_backup_privilege() -> bool:
    """Enable SeBackupPrivilege for the current process (required to open $MFT)."""
    global _backup_privilege_enabled
    if _backup_privilege_enabled:
        return True

    try:
        token = wintypes.HANDLE()
        if not OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
            logger.warning("Failed to open process token")
            return False

        # LUID for SeBackupPrivilege
        luid = ctypes.c_longlong(0)
        if not LookupPrivilegeValueW(None, "SeBackupPrivilege", ctypes.byref(luid)):
            CloseHandle(token)
            logger.warning("Failed to lookup SeBackupPrivilege")
            return False

        # TOKEN_PRIVILEGES: PrivilegeCount(4) + LUID(8) + Attributes(4) = 16 bytes
        tp = ctypes.create_string_buffer(16)
        struct.pack_into('<IqI', tp, 0, 1, luid.value, SE_PRIVILEGE_ENABLED)

        if not AdjustTokenPrivileges(token, False, tp, 0, None, None):
            CloseHandle(token)
            logger.warning("Failed to adjust token privileges")
            return False

        CloseHandle(token)
        _backup_privilege_enabled = True
        logger.info("SeBackupPrivilege enabled")
        return True

    except Exception as e:
        logger.warning(f"Failed to enable backup privilege: {e}")
        return False

ReadFile = kernel32.ReadFile
ReadFile.restype = wintypes.BOOL
ReadFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
]

GetDriveTypeW = kernel32.GetDriveTypeW
GetDriveTypeW.restype = ctypes.c_uint
GetDriveTypeW.argtypes = [wintypes.LPCWSTR]

GetVolumeInformationW = kernel32.GetVolumeInformationW
GetVolumeInformationW.restype = wintypes.BOOL

GetLogicalDriveStringsW = kernel32.GetLogicalDriveStringsW
GetLogicalDriveStringsW.restype = wintypes.DWORD
GetLogicalDriveStringsW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]

GetDiskFreeSpaceExW = kernel32.GetDiskFreeSpaceExW
GetDiskFreeSpaceExW.restype = wintypes.BOOL

DRIVE_FIXED = 3
DRIVE_REMOVABLE = 2
DRIVE_REMOTE = 4

FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

# MFT record parsing
MFT_SIGNATURE = b'FILE'
ATTR_STANDARD_INFORMATION = 0x10
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
ATTR_END_MARKER = 0xFFFFFFFF

# $FILE_NAME namespace values
FILENAME_POSIX = 0
FILENAME_WIN32 = 1
FILENAME_DOS = 2
FILENAME_WIN32_DOS = 3

# Windows FILETIME epoch: Jan 1, 1601
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def filetime_to_datetime(ft: int) -> Optional[datetime]:
    """Convert Windows FILETIME (100ns intervals since 1601-01-01) to naive local datetime."""
    if ft <= 0:
        return None
    try:
        utc_dt = FILETIME_EPOCH + timedelta(microseconds=ft // 10)
        # Convert to naive local time (consistent with datetime.fromtimestamp from os.stat)
        local_dt = utc_dt.astimezone(tz=None)
        return local_dt.replace(tzinfo=None)
    except (OverflowError, OSError):
        return None


def _apply_usa_fixup(record_data: bytearray, bytes_per_sector: int) -> bool:
    """Apply the Update Sequence Array fixup to a raw MFT record.

    Each sector's last 2 bytes are replaced by a sequence number on disk.
    The original values are stored in the USA. We restore them here.
    """
    if len(record_data) < 48:
        return False

    if record_data[:4] != MFT_SIGNATURE:
        return False

    usa_offset = struct.unpack_from('<H', record_data, 4)[0]
    usa_size = struct.unpack_from('<H', record_data, 6)[0]  # entries including check value

    if usa_size < 2 or usa_offset + usa_size * 2 > len(record_data):
        return False

    # First 2 bytes of USA = expected value at end of each sector
    expected = record_data[usa_offset:usa_offset + 2]

    # Restore original sector-end bytes
    for i in range(1, usa_size):
        sector_end = i * bytes_per_sector - 2
        if sector_end + 2 > len(record_data):
            break
        # Verify sector end matches expected (detects torn writes)
        if record_data[sector_end:sector_end + 2] != expected:
            return False
        # Restore original value
        original = record_data[usa_offset + i * 2:usa_offset + i * 2 + 2]
        record_data[sector_end:sector_end + 2] = original

    return True


def _parse_mft_record(record_data: bytearray, record_number: int,
                      bytes_per_sector: int) -> Optional['FileRecord']:
    """Parse a raw MFT file record and extract metadata.

    Extracts from:
    - $STANDARD_INFORMATION (0x10): timestamps, file attributes
    - $FILE_NAME (0x30): parent FRN, filename
    - $DATA (0x80): file size (real size for non-resident)
    """
    if not _apply_usa_fixup(record_data, bytes_per_sector):
        return None

    # Check record is in use (flags at offset 0x16)
    flags = struct.unpack_from('<H', record_data, 0x16)[0]
    if not (flags & 0x01):
        return None

    is_dir = bool(flags & 0x02)

    # Skip extension records (base_record != 0 at offset 0x20)
    base_record = struct.unpack_from('<Q', record_data, 0x20)[0]
    if base_record != 0:
        return None

    # First attribute offset (at 0x14)
    first_attr = struct.unpack_from('<H', record_data, 0x14)[0]

    name = None
    parent_frn = 0
    date_created = None
    date_modified = None
    file_size = 0
    attributes = 0
    best_namespace = -1  # track best filename namespace

    offset = first_attr
    record_len = len(record_data)

    while offset + 8 <= record_len:
        attr_type = struct.unpack_from('<I', record_data, offset)[0]
        if attr_type == ATTR_END_MARKER or attr_type == 0:
            break

        attr_len = struct.unpack_from('<I', record_data, offset + 4)[0]
        if attr_len < 16 or offset + attr_len > record_len:
            break

        non_resident = record_data[offset + 8]

        if attr_type == ATTR_STANDARD_INFORMATION and not non_resident:
            # $STANDARD_INFORMATION is always resident
            content_offset = struct.unpack_from('<H', record_data, offset + 0x14)[0]
            content_start = offset + content_offset
            if content_start + 0x24 <= record_len:
                c_time = struct.unpack_from('<Q', record_data, content_start)[0]
                m_time = struct.unpack_from('<Q', record_data, content_start + 8)[0]
                attributes = struct.unpack_from('<I', record_data, content_start + 0x20)[0]
                date_created = filetime_to_datetime(c_time)
                date_modified = filetime_to_datetime(m_time)

        elif attr_type == ATTR_FILE_NAME and not non_resident:
            content_offset = struct.unpack_from('<H', record_data, offset + 0x14)[0]
            content_start = offset + content_offset
            if content_start + 0x42 <= record_len:
                fn_parent = struct.unpack_from('<Q', record_data, content_start)[0]
                fn_parent_index = fn_parent & 0x0000FFFFFFFFFFFF
                fn_name_len = record_data[content_start + 0x40]  # in characters
                fn_namespace = record_data[content_start + 0x41]
                fn_name_start = content_start + 0x42
                fn_name_end = fn_name_start + fn_name_len * 2

                if fn_name_end <= record_len and fn_name_len > 0:
                    try:
                        fn_name = record_data[fn_name_start:fn_name_end].decode('utf-16-le')
                    except UnicodeDecodeError:
                        fn_name = None

                    # Prefer Win32 (1) or Win32+DOS (3) namespace over DOS-only (2)
                    if fn_name and fn_namespace != FILENAME_DOS:
                        if name is None or fn_namespace in (FILENAME_WIN32, FILENAME_WIN32_DOS):
                            name = fn_name
                            parent_frn = fn_parent_index
                            best_namespace = fn_namespace

        elif attr_type == ATTR_DATA:
            # Only process unnamed (default) data stream
            attr_name_len = record_data[offset + 9]
            if attr_name_len == 0:
                if non_resident:
                    # Non-resident $DATA: real size at offset 0x30 from attr start
                    if offset + 0x38 <= record_len:
                        file_size = struct.unpack_from('<Q', record_data, offset + 0x30)[0]
                else:
                    # Resident $DATA: content length at offset 0x10 from attr start
                    if offset + 0x14 <= record_len:
                        file_size = struct.unpack_from('<I', record_data, offset + 0x10)[0]

        offset += attr_len

    if name is None or name in ('.', '..'):
        return None

    # Ensure directory flag in attributes matches MFT flags
    if is_dir:
        attributes |= FILE_ATTRIBUTE_DIRECTORY

    return FileRecord(
        frn=record_number,
        parent_frn=parent_frn,
        name=name,
        attributes=attributes,
        timestamp=date_modified,
        size=file_size,
        date_created=date_created,
        mft_metadata=True,
    )


@dataclass
class FileRecord:
    """Represents a single file or folder entry from the MFT."""
    frn: int  # File Reference Number
    parent_frn: int
    name: str
    attributes: int = 0
    timestamp: Optional[datetime] = None  # date_modified
    size: int = 0
    date_created: Optional[datetime] = None
    mft_metadata: bool = False  # True when populated from direct $MFT reading

    @property
    def is_dir(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_DIRECTORY)

    @property
    def is_hidden(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_HIDDEN)

    @property
    def is_system(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_SYSTEM)

    @property
    def is_readonly(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_READONLY)

    @property
    def is_compressed(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_COMPRESSED)

    @property
    def is_encrypted(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_ENCRYPTED)


@dataclass
class USNRecord:
    """Represents a single USN journal change record."""
    usn: int
    frn: int
    parent_frn: int
    timestamp: Optional[datetime]
    reason: int
    attributes: int
    name: str

    @property
    def is_create(self) -> bool:
        return bool(self.reason & USN_REASON_FILE_CREATE)

    @property
    def is_delete(self) -> bool:
        return bool(self.reason & USN_REASON_FILE_DELETE)

    @property
    def is_rename(self) -> bool:
        return bool(self.reason & (USN_REASON_RENAME_OLD_NAME | USN_REASON_RENAME_NEW_NAME))

    @property
    def is_close(self) -> bool:
        return bool(self.reason & USN_REASON_CLOSE)

    @property
    def is_modify(self) -> bool:
        return bool(self.reason & (
            USN_REASON_DATA_OVERWRITE | USN_REASON_DATA_EXTEND |
            USN_REASON_DATA_TRUNCATION | USN_REASON_BASIC_INFO_CHANGE
        ))


@dataclass
class VolumeInfo:
    """NTFS volume information."""
    drive_letter: str
    serial_number: int = 0
    mft_start_lcn: int = 0
    mft_zone_start: int = 0
    mft_zone_end: int = 0
    bytes_per_sector: int = 0
    bytes_per_cluster: int = 0
    bytes_per_file_record: int = 0
    clusters_per_file_record: int = 0
    mft_valid_data_length: int = 0
    total_clusters: int = 0
    free_clusters: int = 0
    total_reserved: int = 0
    volume_label: str = ""
    filesystem: str = ""


class NTFSVolume:
    """
    Provides low-level NTFS volume access for MFT enumeration
    and USN journal monitoring via Win32 DeviceIoControl.
    """

    def __init__(self, drive_letter: str):
        self.drive_letter = drive_letter.upper().rstrip(':').rstrip('\\')
        self._handle = None
        self._volume_info: Optional[VolumeInfo] = None
        self._journal_id: int = 0
        self._next_usn: int = 0

    def open(self) -> bool:
        """Open a handle to the NTFS volume."""
        volume_path = f"\\\\.\\{self.drive_letter}:"
        self._handle = CreateFileW(
            volume_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            0,
            None
        )
        if self._handle == INVALID_HANDLE_VALUE or self._handle is None:
            # Try read-only
            self._handle = CreateFileW(
                volume_path,
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                0,
                None
            )
            if self._handle == INVALID_HANDLE_VALUE or self._handle is None:
                err = ctypes.get_last_error()
                logger.error(f"Failed to open volume {self.drive_letter}: error {err}")
                return False

        logger.info(f"Opened volume {self.drive_letter}:")
        return True

    def close(self):
        """Close the volume handle."""
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            CloseHandle(self._handle)
            self._handle = None

    def get_volume_info(self) -> Optional[VolumeInfo]:
        """Query NTFS volume data."""
        if self._volume_info:
            return self._volume_info

        # Get volume label and filesystem type
        vol_name = ctypes.create_unicode_buffer(256)
        fs_name = ctypes.create_unicode_buffer(256)
        serial = wintypes.DWORD()
        max_comp = wintypes.DWORD()
        flags = wintypes.DWORD()

        root = f"{self.drive_letter}:\\"
        GetVolumeInformationW(
            root, vol_name, 256, ctypes.byref(serial),
            ctypes.byref(max_comp), ctypes.byref(flags),
            fs_name, 256
        )

        info = VolumeInfo(
            drive_letter=self.drive_letter,
            volume_label=vol_name.value or "",
            filesystem=fs_name.value or "",
            serial_number=serial.value
        )

        # Get NTFS volume data via DeviceIoControl
        buf_size = 128
        out_buf = ctypes.create_string_buffer(buf_size)
        bytes_returned = wintypes.DWORD(0)

        success = DeviceIoControl(
            self._handle,
            FSCTL_GET_NTFS_VOLUME_DATA,
            None, 0,
            out_buf, buf_size,
            ctypes.byref(bytes_returned),
            None
        )

        if success:
            # Parse NTFS_VOLUME_DATA_BUFFER
            # Layout: VolumeSerialNumber(8), NumberSectors(8), TotalClusters(8),
            #         FreeClusters(8), TotalReserved(8), BytesPerSector(4),
            #         BytesPerCluster(4), BytesPerFileRecordSegment(4),
            #         ClustersPerFileRecordSegment(4), MftValidDataLength(8),
            #         MftStartLcn(8), Mft2StartLcn(8), MftZoneStart(8), MftZoneEnd(8)
            data = out_buf.raw[:bytes_returned.value]
            if len(data) >= 96:
                vals = struct.unpack_from('<QQQQQIIIIQQQqq', data, 0)
                info.serial_number = vals[0]
                info.total_clusters = vals[2]
                info.free_clusters = vals[3]
                info.total_reserved = vals[4]
                info.bytes_per_sector = vals[5]
                info.bytes_per_cluster = vals[6]
                info.bytes_per_file_record = vals[7]
                info.clusters_per_file_record = vals[8]
                info.mft_valid_data_length = vals[9]
                info.mft_start_lcn = vals[10]
                info.mft_zone_start = vals[12]
                info.mft_zone_end = vals[13]

        self._volume_info = info
        return info

    def enumerate_mft(self, callback: Optional[Callable[[FileRecord, int], None]] = None,
                      cancel_check: Optional[Callable[[], bool]] = None) -> list[FileRecord]:
        """
        Enumerate all files and folders on the volume using FSCTL_ENUM_USN_DATA.
        This reads the MFT and returns FileRecord objects for every entry.

        Args:
            callback: Optional progress callback(record, total_so_far)
            cancel_check: Optional callable returning True to cancel

        Returns:
            List of all FileRecord entries on the volume.
        """
        records = []

        # MFT_ENUM_DATA_V0: StartFileReferenceNumber(8), LowUsn(8), HighUsn(8)
        # We use 0 for start, 0 for low USN, and max for high USN
        med_input = struct.pack('<QQQ', 0, 0, 0x7FFFFFFFFFFFFFFF)

        # Use a large output buffer for performance (64KB)
        OUT_BUF_SIZE = 65536
        out_buf = ctypes.create_string_buffer(OUT_BUF_SIZE)
        bytes_returned = wintypes.DWORD(0)

        total = 0
        callback_interval = 10000  # Report progress every 10k records

        while True:
            if cancel_check and cancel_check():
                logger.info("MFT enumeration cancelled")
                break

            success = DeviceIoControl(
                self._handle,
                FSCTL_ENUM_USN_DATA,
                med_input, len(med_input),
                out_buf, OUT_BUF_SIZE,
                ctypes.byref(bytes_returned),
                None
            )

            if not success:
                err = ctypes.GetLastError()
                if err == 38:  # ERROR_HANDLE_EOF - we've reached the end
                    break
                logger.debug(f"FSCTL_ENUM_USN_DATA ended with error {err}")
                break

            returned = bytes_returned.value
            if returned <= 8:
                break

            data = out_buf.raw[:returned]

            # First 8 bytes: next StartFileReferenceNumber for continuation
            next_frn = struct.unpack_from('<Q', data, 0)[0]

            # Parse USN_RECORD_V2 entries starting at offset 8
            offset = 8
            while offset < returned:
                if offset + 64 > returned:
                    break

                # USN_RECORD_V2 header
                record_len = struct.unpack_from('<I', data, offset)[0]
                if record_len == 0 or offset + record_len > returned:
                    break

                # Parse fields
                # Offset within record:
                # 0: RecordLength (4)
                # 4: MajorVersion (2), MinorVersion (2)
                # 8: FileReferenceNumber (8)
                # 16: ParentFileReferenceNumber (8)
                # 24: Usn (8)
                # 32: TimeStamp (8) - FILETIME
                # 40: Reason (4)
                # 44: SourceInfo (4)
                # 48: SecurityId (4)
                # 52: FileAttributes (4)
                # 56: FileNameLength (2)
                # 58: FileNameOffset (2)
                # 60: FileName (variable, UTF-16LE)

                frn, parent_frn = struct.unpack_from('<QQ', data, offset + 8)
                timestamp_raw = struct.unpack_from('<Q', data, offset + 32)[0]
                attributes = struct.unpack_from('<I', data, offset + 52)[0]
                name_len = struct.unpack_from('<H', data, offset + 56)[0]
                name_offset = struct.unpack_from('<H', data, offset + 58)[0]

                # Mask off sequence number from FRN (lower 48 bits = file index)
                frn_index = frn & 0x0000FFFFFFFFFFFF
                parent_index = parent_frn & 0x0000FFFFFFFFFFFF

                # Extract filename (UTF-16LE)
                name_start = offset + name_offset
                name_end = name_start + name_len
                if name_end <= returned and name_len > 0:
                    try:
                        name = data[name_start:name_end].decode('utf-16-le')
                    except UnicodeDecodeError:
                        name = ""
                else:
                    name = ""

                if name and name not in ('.', '..'):
                    record = FileRecord(
                        frn=frn_index,
                        parent_frn=parent_index,
                        name=name,
                        attributes=attributes,
                        timestamp=filetime_to_datetime(timestamp_raw),
                    )
                    records.append(record)
                    total += 1

                    if callback and total % callback_interval == 0:
                        callback(record, total)

                offset += record_len

            # Update input for next iteration
            med_input = struct.pack('<QQQ', next_frn, 0, 0x7FFFFFFFFFFFFFFF)

        logger.info(f"Enumerated {total} records from {self.drive_letter}:")
        return records

    def enumerate_mft_direct(self, callback: Optional[Callable[[FileRecord, int], None]] = None,
                             cancel_check: Optional[Callable[[], bool]] = None) -> list[FileRecord]:
        """
        Enumerate all files/folders by reading the $MFT file directly.
        Extracts full metadata (timestamps, file sizes) from MFT records
        in a single sequential pass — no per-file os.stat() needed.

        Falls back to FSCTL_ENUM_USN_DATA if $MFT cannot be opened.
        """
        vol_info = self.get_volume_info()
        if not vol_info:
            logger.warning(f"No volume info for {self.drive_letter}:, falling back to USN enum")
            return self.enumerate_mft(callback, cancel_check)

        record_size = vol_info.bytes_per_file_record
        if record_size <= 0:
            record_size = 1024
        bytes_per_sector = vol_info.bytes_per_sector
        if bytes_per_sector <= 0:
            bytes_per_sector = 512

        # Enable SeBackupPrivilege (required to open NTFS metafiles)
        _enable_backup_privilege()

        # Open $MFT file directly (requires admin + backup semantics)
        mft_path = f"{self.drive_letter}:\\$MFT"
        mft_handle = CreateFileW(
            mft_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None
        )

        if mft_handle == INVALID_HANDLE_VALUE or mft_handle is None:
            err = ctypes.GetLastError()
            logger.warning(f"Cannot open $MFT on {self.drive_letter}: (error {err}), falling back to USN enum")
            return self.enumerate_mft(callback, cancel_check)

        logger.info(f"Reading $MFT directly on {self.drive_letter}: (record_size={record_size})")

        try:
            records = []
            frn = 0
            records_per_chunk = 4096
            chunk_size = record_size * records_per_chunk
            callback_interval = 10000

            while True:
                if cancel_check and cancel_check():
                    logger.info("MFT direct read cancelled")
                    break

                buf = ctypes.create_string_buffer(chunk_size)
                bytes_read = wintypes.DWORD(0)
                ok = ReadFile(mft_handle, buf, chunk_size, ctypes.byref(bytes_read), None)

                if not ok or bytes_read.value == 0:
                    break

                data = buf.raw[:bytes_read.value]

                for pos in range(0, len(data), record_size):
                    if pos + record_size > len(data):
                        break

                    record_data = bytearray(data[pos:pos + record_size])
                    record = _parse_mft_record(record_data, frn, bytes_per_sector)
                    frn += 1

                    if record is not None:
                        records.append(record)

                        if callback and len(records) % callback_interval == 0:
                            callback(record, len(records))

                    # Check cancel every 4096 records for responsive cancellation
                    if cancel_check and frn % 4096 == 0 and cancel_check():
                        break

                if cancel_check and cancel_check():
                    break

            logger.info(
                f"Direct MFT read: {len(records)} records from {self.drive_letter}: "
                f"({frn} MFT entries scanned)"
            )
            return records

        except Exception as e:
            logger.error(f"Error reading $MFT on {self.drive_letter}: {e}, falling back to USN enum")
            return self.enumerate_mft(callback, cancel_check)

        finally:
            CloseHandle(mft_handle)

    def query_usn_journal(self) -> bool:
        """Query the USN journal to get the journal ID and current USN."""
        # USN_JOURNAL_DATA_V0 output: UsnJournalID(8), FirstUsn(8), NextUsn(8),
        #   LowestValidUsn(8), MaxUsn(8), MaximumSize(8), AllocationDelta(8)
        out_buf = ctypes.create_string_buffer(64)
        bytes_returned = wintypes.DWORD(0)

        success = DeviceIoControl(
            self._handle,
            FSCTL_QUERY_USN_JOURNAL,
            None, 0,
            out_buf, 64,
            ctypes.byref(bytes_returned),
            None
        )

        if not success:
            err = ctypes.GetLastError()
            logger.warning(f"Failed to query USN journal on {self.drive_letter}: error {err}")
            # Try to create the journal
            if err == 1179:  # ERROR_JOURNAL_NOT_ACTIVE
                return self._create_usn_journal()
            return False

        data = out_buf.raw[:bytes_returned.value]
        if len(data) >= 56:
            vals = struct.unpack_from('<QQQQQQQ', data, 0)
            self._journal_id = vals[0]
            first_usn = vals[1]
            self._next_usn = vals[2]
            logger.info(
                f"USN Journal on {self.drive_letter}: "
                f"ID={self._journal_id}, FirstUSN={first_usn}, NextUSN={self._next_usn}"
            )
            return True

        return False

    def _create_usn_journal(self) -> bool:
        """Create a USN journal on the volume if one doesn't exist."""
        # CREATE_USN_JOURNAL_DATA: MaximumSize(8), AllocationDelta(8)
        input_buf = struct.pack('<QQ', 0x800000, 0x100000)  # 8MB max, 1MB delta
        bytes_returned = wintypes.DWORD(0)

        success = DeviceIoControl(
            self._handle,
            FSCTL_CREATE_USN_JOURNAL,
            input_buf, len(input_buf),
            None, 0,
            ctypes.byref(bytes_returned),
            None
        )

        if success:
            logger.info(f"Created USN journal on {self.drive_letter}:")
            return self.query_usn_journal()

        logger.error(f"Failed to create USN journal on {self.drive_letter}:")
        return False

    def read_usn_journal(self, start_usn: Optional[int] = None) -> list[USNRecord]:
        """
        Read new USN journal records since start_usn (or the last read position).
        Supports USN_RECORD V2, V3, and V4 formats.

        Returns:
            List of USNRecord entries.
        """
        if start_usn is not None:
            self._next_usn = start_usn

        # READ_USN_JOURNAL_DATA_V0:
        # StartUsn(8), ReasonMask(4), ReturnOnlyOnClose(4),
        # Timeout(8), BytesToWaitFor(8), UsnJournalID(8)
        reason_mask = 0xFFFFFFFF  # All reasons
        input_buf = struct.pack(
            '<QIIQQQ',
            self._next_usn,
            reason_mask,
            0,  # ReturnOnlyOnClose = false
            0,  # Timeout = 0 (don't wait)
            0,  # BytesToWaitFor = 0
            self._journal_id
        )

        OUT_BUF_SIZE = 65536
        out_buf = ctypes.create_string_buffer(OUT_BUF_SIZE)
        bytes_returned = wintypes.DWORD(0)

        success = DeviceIoControl(
            self._handle,
            FSCTL_READ_USN_JOURNAL,
            input_buf, len(input_buf),
            out_buf, OUT_BUF_SIZE,
            ctypes.byref(bytes_returned),
            None
        )

        records = []
        if not success:
            return records

        returned = bytes_returned.value
        if returned <= 8:
            return records

        data = out_buf.raw[:returned]

        # First 8 bytes: next USN for continuation
        next_usn = struct.unpack_from('<Q', data, 0)[0]

        offset = 8
        while offset < returned:
            if offset + 4 > returned:
                break

            record_len = struct.unpack_from('<I', data, offset)[0]
            if record_len == 0 or offset + record_len > returned:
                break

            # Detect record version (MajorVersion at offset +4)
            if offset + 6 > returned:
                break
            major_ver = struct.unpack_from('<H', data, offset + 4)[0]

            if major_ver == 3 or major_ver == 4:
                # USN_RECORD_V3/V4: uses 128-bit file IDs (ReFS)
                # Layout: RecordLength(4), MajorVersion(2), MinorVersion(2),
                #   FileReferenceNumber(16), ParentFileReferenceNumber(16),
                #   Usn(8), TimeStamp(8), Reason(4), SourceInfo(4),
                #   SecurityId(4), FileAttributes(4), FileNameLength(2),
                #   FileNameOffset(2), FileName(variable)
                if offset + 76 > returned:
                    break

                # 128-bit file IDs — take lower 64 bits for our FRN
                frn_lo = struct.unpack_from('<Q', data, offset + 8)[0]
                parent_lo = struct.unpack_from('<Q', data, offset + 24)[0]
                usn = struct.unpack_from('<Q', data, offset + 40)[0]
                timestamp_raw = struct.unpack_from('<Q', data, offset + 48)[0]
                reason = struct.unpack_from('<I', data, offset + 56)[0]
                attributes = struct.unpack_from('<I', data, offset + 64)[0]
                name_len = struct.unpack_from('<H', data, offset + 68)[0]
                name_offset = struct.unpack_from('<H', data, offset + 70)[0]

                frn_index = frn_lo & 0x0000FFFFFFFFFFFF
                parent_index = parent_lo & 0x0000FFFFFFFFFFFF
            else:
                # USN_RECORD_V2 (standard NTFS)
                if offset + 64 > returned:
                    break

                frn, parent_frn = struct.unpack_from('<QQ', data, offset + 8)
                usn = struct.unpack_from('<Q', data, offset + 24)[0]
                timestamp_raw = struct.unpack_from('<Q', data, offset + 32)[0]
                reason = struct.unpack_from('<I', data, offset + 40)[0]
                attributes = struct.unpack_from('<I', data, offset + 52)[0]
                name_len = struct.unpack_from('<H', data, offset + 56)[0]
                name_offset = struct.unpack_from('<H', data, offset + 58)[0]

                frn_index = frn & 0x0000FFFFFFFFFFFF
                parent_index = parent_frn & 0x0000FFFFFFFFFFFF

            name_start = offset + name_offset
            name_end = name_start + name_len
            if name_end <= returned and name_len > 0:
                try:
                    name = data[name_start:name_end].decode('utf-16-le')
                except UnicodeDecodeError:
                    name = ""
            else:
                name = ""

            if name:
                records.append(USNRecord(
                    usn=usn,
                    frn=frn_index,
                    parent_frn=parent_index,
                    timestamp=filetime_to_datetime(timestamp_raw),
                    reason=reason,
                    attributes=attributes,
                    name=name
                ))

            offset += record_len

        self._next_usn = next_usn
        return records

    @property
    def journal_id(self) -> int:
        return self._journal_id

    @property
    def current_usn(self) -> int:
        return self._next_usn

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


@dataclass
class DriveInfo:
    """Information about a detected drive."""
    letter: str
    filesystem: str  # 'NTFS', 'FAT32', 'exFAT', etc.
    drive_type: int  # DRIVE_FIXED, DRIVE_REMOVABLE, etc.
    label: str = ""

    @property
    def is_ntfs(self) -> bool:
        return self.filesystem.upper() == 'NTFS'

    @property
    def is_refs(self) -> bool:
        return self.filesystem.upper() == 'REFS'

    @property
    def is_fat(self) -> bool:
        return self.filesystem.upper() in ('FAT', 'FAT32', 'EXFAT')

    @property
    def needs_walk(self) -> bool:
        """True if this drive requires os.scandir (no MFT/USN support)."""
        return self.is_fat or self.is_refs


# Supported filesystems for indexing
SUPPORTED_FILESYSTEMS = {'NTFS', 'FAT', 'FAT32', 'EXFAT', 'REFS'}


def get_all_drives() -> list[DriveInfo]:
    """Return info for all fixed/removable drives with supported filesystems."""
    buf = ctypes.create_unicode_buffer(512)
    length = GetLogicalDriveStringsW(512, buf)
    if length == 0:
        return []

    drives = []
    raw = ctypes.wstring_at(buf, length)
    for part in raw.split('\x00'):
        part = part.strip()
        if not part:
            continue
        letter = part[0].upper()
        dt = GetDriveTypeW(part)
        if dt not in (DRIVE_FIXED, DRIVE_REMOVABLE):
            continue

        vol_name = ctypes.create_unicode_buffer(256)
        fs_name = ctypes.create_unicode_buffer(32)
        ok = GetVolumeInformationW(
            part, vol_name, 256, None, None, None, fs_name, 32
        )
        if not ok:
            continue

        fs = fs_name.value.upper() if fs_name.value else ""
        if fs in SUPPORTED_FILESYSTEMS:
            drives.append(DriveInfo(
                letter=letter,
                filesystem=fs,
                drive_type=dt,
                label=vol_name.value or "",
            ))

    return sorted(drives, key=lambda d: d.letter)


def get_ntfs_drives() -> list[str]:
    """Return a list of drive letters for fixed NTFS volumes."""
    return [d.letter for d in get_all_drives() if d.is_ntfs]
