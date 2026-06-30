# Research — QuickFind

## Executive Summary
QuickFind is a verified v0.8.42 Windows-first desktop search tool built around NTFS MFT/USN indexing, PyQt6, SQLite cache/FTS5 fallback, CLI search, read-only HTTP search, content/archive indexing, diagnostics, localization, accessibility metadata, and MSIX/winget packaging. Its strongest current shape is a local-first Everything alternative that already covers most old roadmap gaps; the highest-value direction is to harden trust boundaries and release/update reliability before adding more search surface. Top opportunities: sandbox untrusted content/archive parsing, verify release/update artifacts, persist live USN checkpoints durably, harden remote sessions, add redacted support bundles, version settings/cache migrations, test rendered accessibility, expose Windows IFilter/property extraction, package modifier plugins, and add benchmark evidence.

## Product Map
- Core workflows: index local/UNC/EFU/POSIX roots, search filename/path/content/archive metadata, preview/open/recycle results, run CLI or read-only HTTP search, diagnose cache/service/index health.
- User personas: Windows power users replacing Windows Search/Everything, sysadmins searching large local/network file sets, developers using CLI/regex/git filters, users with offline drives and document archives.
- Platforms and distribution: Python 3.10+, Windows 10/11 primary, Linux/macOS configured roots via `os.scandir` + Watchdog, PyInstaller exe, MSIX/App Installer, winget manifests.
- Key integrations and data flows: NTFS MFT/USN via `core/ntfs.py`, SQLite cache and content/archive tables in `core/cache.py`, PyQt6 GUI, Windows Credential Manager for SMB, Windows service IPC, HTTP/OpenAPI server, Everything EFU/filter/bookmark imports.

## Competitive Landscape
- Voidtools Everything: sets the speed/live-index bar and has filters, bookmarks, EFU, HTTP/SDK, and 1.5 content/property indexing. Learn from its durable service/index reliability and advanced metadata functions; avoid its closed-source model and filename-only default ceiling.
- FSearch: proves fast open-source filename search with database update concerns and users asking for content/metadata. Learn from selective update UX; avoid Linux-only GTK assumptions.
- Recoll and DocFetcher: strongest open content-indexing references with web UI, Python API, external indexers, rich file filters, OCR, email/archive support. Learn from pluggable extractors and shared-index web patterns; avoid heavy always-on or Java/Tika defaults unless isolated.
- Flow Launcher, EverythingToolbar, PowerToys Command Palette: win on plugin ecosystems, launcher ergonomics, and taskbar/command-palette workflows. Learn plugin manifest/discovery, preview/action UX, and extension isolation; avoid turning QuickFind into a general app launcher.
- FileLocator Pro, UltraSearch, WizFile, Listary, Copernic, Fluent Search: commercial tools paywall content indexing, enterprise/network/cloud/email search, quick switch, signed updates, duplicate tools, previews, and plugins. Learn what users pay for; avoid cloud/web/AI features that weaken QuickFind's local-first privacy position.
- Windows Search and IFilter: platform-native content/property extraction and AQS/property model remain the broadest file-type bridge. Learn from IFilter/property handlers; avoid delegating core filename speed to Windows Search.

## Security, Privacy, and Reliability
- Verified: `core/content/adapters.py` extracts PDF/DOCX/PPTX/EML/source text in-process; parser crashes are caught, but CPU hangs, hostile parser behavior, and per-file wall-clock isolation are not enforced. py7zr 1.1.3 fixed decompression-bomb issues, which makes worker-level archive/content quotas still roadmap-worthy.
- Verified: `build.py:95` deletes `dist/` and `build/` with plain `shutil.rmtree`; recent local verification hit locked `dist\QuickFind.exe`, and `build.py:115` emits GitHub release URLs without a release-asset verification command.
- Verified: `core/cache.py:1030` defines `db_update_usn_position()`, but `core/index.py:1945` `USNMonitorThread` only emits changes and `_apply_usn_changes()` batch-syncs file rows; durable `drives.next_usn` is refreshed on full cache saves, leaving crash windows with stale journal checkpoints.
- Verified: `server/http_server.py` correctly rejects query-string tokens and uses Bearer/Basic/session-cookie auth, but `_session_cookie_header()` lacks `Secure` when HTTPS is enabled and `/auth` has no Origin/Referer guard. CSP still permits inline script/style because the server renders inline HTML.
- Verified: `gui/context_menu.py:104` sends delete actions straight to Recycle Bin with silent/no-confirm flags; this matches the no-confirmation product style but needs success/failure feedback and recovery affordance.
- Missing guardrails: no redacted support bundle export, no rendered UIA/accessibility smoke run, no schema-versioned settings migration/rollback, no plugin discovery/quarantine boundary, no content-index incremental queue tied to file-change events.
- Recovery and rollback needs: versioned settings/profile backups, durable USN checkpoint flushing, release asset/signature/feed verification, and cache rebuild/reporting paths that include enough evidence for users to trust stale/offline results.

## Architecture Assessment
- `core/index.py` and `core/cache.py`: add a narrow journal-checkpoint write path after successful monitor batches; keep it per-drive and test journal recycle/idempotent replay.
- `core/content/adapters.py`, `core/content/indexer.py`, `core/archives.py`: move untrusted extraction/probing into cancellable workers with timeout, byte caps, adapter failure counters, and quarantine metadata.
- `build.py`, `packaging/winget/`: add release verification that proves version, MSIX signature/hash, appinstaller URL, winget manifest URL/hash, and GitHub release assets agree.
- `gui/settings_dialog.py`: settings import/export exists, but there is no explicit schema version or pre-migration backup. Add a migration boundary before future settings growth.
- `core/localization.py`, `gui/help_docs.py`, `gui/settings_dialog.py`: Spanish catalog is a small shell subset; many help/settings/result strings remain literal. Add extraction/linting and pseudo-locale coverage before adding languages.
- `core/search.py`: modifier plugin API is programmatic only. Add entry-point/manifest loading, disabled-on-error state, and docs/tests before encouraging third-party plugins.
- Tests: `python -m pytest -q` is verified green at 329 tests, but coverage is mostly unit-level. Add smoke harnesses for rendered UI state, accessibility names, MSIX/update metadata, and remote HTTPS auth headers.

## Rejected Ideas
- Replace SQLite with Xapian/Tantivy/Lucene now: Recoll/DocFetcher show their value, but QuickFind already has SQLite cache/FTS5 fallback and needs benchmarks before a storage-engine rewrite.
- Default Java/Tika server for all content search: DocFetcher-style broad extraction is useful, but a Java runtime would add distribution and attack-surface cost; keep it optional/plugin-gated.
- Cloud/AI semantic search as a core feature: Raycast/Fluent/Copernic show market interest, but it conflicts with QuickFind's local-first privacy and would add model/cloud dependencies before trust work is finished.
- Multi-user shared search without ACL enforcement: Recoll-webui community reports document-level security/RBAC as the hard problem; QuickFind should not expose shared indexes until ACL semantics are explicit.
- Web/Bing-style default search aggregation: community complaints about Windows Search point in the opposite direction; QuickFind should stay local and deterministic by default.

## Sources
Direct OSS and adjacent:
- https://www.voidtools.com/support/everything/using_everything/
- https://www.voidtools.com/support/everything/options/
- https://www.voidtools.com/support/everything/file_lists/
- https://github.com/cboxdoerfer/fsearch
- https://github.com/cboxdoerfer/fsearch/issues/45
- https://www.recoll.org/pages/features.html
- https://www.recoll.org/usermanual/webhelp/docs/RCL.PROGRAM.PYTHONAPI.INTRO.html
- https://docfetcher.sourceforge.io/
- https://github.com/srwi/EverythingToolbar
- https://www.flowlauncher.com/plugins/
- https://github.com/phiresky/ripgrep-all

Commercial:
- https://help.listary.com/quick-switch
- https://antibody-software.com/wizfile/about
- https://www.mythicsoft.com/filelocatorpro/information/
- https://www.jam-software.com/ultrasearch
- https://fluentsearch.net/
- https://copernic.com/en/desktop/release/

Standards and platform APIs:
- https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ns-winioctl-usn_record_v4
- https://learn.microsoft.com/en-us/windows/win32/search/-search-ifilter-about
- https://learn.microsoft.com/en-us/windows/win32/api/filter/nn-filter-ifilter
- https://learn.microsoft.com/en-us/windows/msix/app-installer/update-settings
- https://learn.microsoft.com/en-us/uwp/schemas/appinstallerschema/element-update-settings
- https://www.sqlite.org/fts5.html

Community, dependency, and advisory:
- https://news.ycombinator.com/item?id=41337268
- https://www.reddit.com/r/DataHoarder/comments/csdzxv/indexing_searching_across_your_data_fulltext/
- https://www.reddit.com/r/DataHoarder/comments/1b8wqyd/how_do_you_efficiently_search_through_your_data/
- https://burntsushi.net/ripgrep/
- https://pyinstaller.org/en/stable/CHANGES.html
- https://github.com/miurahr/py7zr/discussions/738
- https://docs.pytest.org/en/stable/changelog.html

## Open Questions
None.
