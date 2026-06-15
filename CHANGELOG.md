# Changelog

All notable changes to QuickFind will be documented in this file.

## [v0.7.2] - 2026-06-15

- Fixed: `recycle_file` import crash — Delete key handler referenced wrong function name
- Fixed: Startup crash on non-admin — `Path` used before import, bogus `setWindowIcon` on Win32 HWND
- Fixed: `requirements.txt` now pip-installable (removed internal module names)
- Security: HTTP server uses `html.escape()` for all user-derived content, adds CSP + X-Content-Type-Options headers
- Fixed: Log rotation — `RotatingFileHandler` with 5MB max and 3 backups replaces unbounded `FileHandler`
- Added: HTTP server per-IP rate limiting (60 req/min, 429 on excess)
- Fixed: ctypes Win32 safety — `WinDLL(use_last_error=True)`, complete `argtypes` for all functions, `ctypes.get_last_error()` everywhere

## [v0.7.1]

- Fixed: Fix memory leaks during large drive scans
- Changed: Update README.md
- v0.7.1: Reorder menu bar, add filter/bookmark import/export
- Fixed: Fix launch crashes: _result_count_label init order, column visibility key mapping
- QuickFind v0.7.0 — bug fixes, dark title bar, regex validation, tray progress
- QuickFind v0.6.0 — 20 improvements: ReFS/Dev Drive, USN V3/V4, batch DB writes, non-admin fallback, search history, result highlighting, column filters, keyboard nav, token auth, build script
- Initial commit — QuickFind v0.1.0
