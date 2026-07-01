# Research - QuickFind

## Executive Summary
QuickFind is a verified v0.8.42 local-first desktop search tool built around NTFS MFT/USN indexing, PyQt6, SQLite cache/FTS5 fallback, CLI search, read-only HTTP search, content/archive indexing, diagnostics, localization, accessibility metadata, and MSIX/winget packaging. Its strongest current shape is an open Everything-style search surface that already covers filename speed, content search, remote read-only access, previews, service mode, and packaging; the highest-value direction remains trust hardening and reproducible release quality before broader workflow expansion. Top opportunities: sandbox untrusted content/archive parsing, verify release/update artifacts, persist live USN checkpoints durably, harden remote sessions and browser cache headers, add privacy-preserving remote audit logs, add dependency/SBOM/advisory gates, add content-cache privacy and purge controls, export redacted support bundles, version settings/cache migrations, test rendered accessibility, expose Windows IFilter/property extraction, package modifier plugins, and add benchmark evidence.

## Product Map
- Core workflows: index local/UNC/EFU/POSIX roots, search filename/path/content/archive metadata, preview/open/recycle results, export EFU file lists, run CLI or read-only HTTP search, diagnose cache/service/index health.
- User personas: Windows power users replacing Windows Search/Everything, sysadmins searching large local/network file sets, developers using CLI/regex/git filters, users with offline drives and document archives.
- Platforms and distribution: Python 3.10+, Windows 10/11 primary, Linux/macOS configured roots via `os.scandir` + Watchdog, PyInstaller exe, MSIX/App Installer, winget manifests.
- Key integrations and data flows: NTFS MFT/USN via `core/ntfs.py`, SQLite cache and content/archive tables in `core/cache.py`, PyQt6 GUI, Windows Credential Manager for SMB, Windows service IPC, HTTP/OpenAPI server, Everything EFU/filter/bookmark imports.

## Competitive Landscape
- Voidtools Everything: sets the speed/live-index bar and has filters, EFU, service mode, HTTP/SDK, property indexing, content-index include rules, and content-size statistics. Learn durable service/index reliability, content-scope controls, and metadata functions; avoid its closed-source model and filename-first content ceiling.
- FSearch: proves fast open-source filename search and recurring demand for Everything-like live updates. Learn selective update UX; avoid Linux-only GTK assumptions and manual refresh expectations.
- Recoll and DocFetcher: strongest open content-indexing references with web UI, Python API, external indexers, rich file filters, OCR, email/archive support, and recovery/index-failure docs. Learn pluggable extractors and shared-index web patterns; avoid heavy always-on or Java/Tika defaults unless isolated.
- Flow Launcher, EverythingToolbar, PowerToys Command Palette: win on plugin ecosystems, launcher ergonomics, taskbar/command-palette access, and extension marketplaces. Learn plugin manifests/discovery, preview/action UX, and failed-plugin quarantine; avoid turning QuickFind into a general app launcher.
- FileLocator Pro, UltraSearch, WizFile, Listary, Copernic, Fluent Search: commercial tools paywall content indexing, network/cloud/email search, quick switch, signed updates, duplicate tools, previews, report/export workflows, and plugins. Learn what users pay for; avoid cloud/web/AI features that weaken QuickFind's local-first privacy position.
- Windows Search and IFilter: platform-native content/property extraction remains the broadest file-type bridge, and Microsoft documents property handlers running out-of-process for robustness. Learn from IFilter/property handlers; avoid delegating core filename speed to Windows Search.

## Security, Privacy, and Reliability
- Verified: `core/content/adapters.py` extracts PDF/DOCX/PPTX/EML/source text in-process; parser crashes are caught, but CPU hangs, hostile parser behavior, and per-file wall-clock isolation are not enforced. py7zr 1.1.3 fixed multiple 7z vulnerabilities, which keeps worker-level archive/content quotas roadmap-worthy.
- Verified: `core/archives.py` enumerates ZIP/7z members in-process and caches metadata in `core/cache.py`; it does not extract members, but archive metadata parsing still needs timeout/quarantine protection.
- Verified: `core/cache.py` persists extracted full text in `content_cache.text` and mirrors it into `content_fts`; settings expose roots, extensions, size caps, and diagnostics expose cache size, but there is no purge, retention, per-root removal, or privacy warning for cached sensitive document text.
- Verified: `build.py` prints pinned runtime versions from `requirements.txt`, but there is no local dependency advisory, license inventory, or SBOM gate for the PyQt/PyInstaller/pdfplumber/py7zr/watchdog stack.
- Verified: `build.py` deletes `dist/` and `build/` with plain `shutil.rmtree`, and release URLs are rendered without a release-asset verification command.
- Verified: `core/cache.py:1030` defines `db_update_usn_position()`, but `core/index.py:1945` `USNMonitorThread` only emits changes and `_apply_usn_changes()` batch-syncs file rows; durable `drives.next_usn` is refreshed on full cache saves, leaving crash windows with stale journal checkpoints.
- Verified: `server/http_server.py` correctly rejects query-string tokens and uses Bearer/Basic/session-cookie auth, but `_session_cookie_header()` lacks `Secure` when HTTPS is enabled, `/auth` has no Origin/Referer guard, and `_send_security_headers()` does not send `Cache-Control: no-store` or `Referrer-Policy` for pages containing search results or auth fields.
- Verified: `server/http_server.py` logs generic request messages at debug level but has no privacy-preserving audit trail for auth failures, rate limits, denied shared-mode paths, or remote query volume.
- Verified: `gui/context_menu.py` sends delete actions straight to Recycle Bin with silent/no-confirm flags; this matches the no-confirmation product style but needs success/failure feedback and recovery affordance.
- Missing guardrails: no redacted support bundle export, no rendered UIA/accessibility smoke run, no schema-versioned settings migration/rollback, no plugin discovery/quarantine boundary, no content-index incremental queue tied to file-change events, no report-grade GUI export with match snippets.

## Architecture Assessment
- `core/index.py` and `core/cache.py`: add a narrow journal-checkpoint write path after successful monitor batches; keep it per-drive and test journal recycle/idempotent replay.
- `core/content/adapters.py`, `core/content/indexer.py`, `core/archives.py`: move untrusted extraction/probing into cancellable workers with timeout, byte caps, adapter failure counters, and quarantine metadata.
- `core/cache.py`, `gui/settings_dialog.py`, `gui/diagnostics_dialog.py`: add content-cache purge/retention controls before expanding extraction depth; SQLite FTS5 supports explicit index deletion/rebuild flows that can make purge testable.
- `server/http_server.py`: separate operational debug logs from redacted security audit events; record auth/rate-limit/search counts without raw tokens, passwords, or full result paths, and add browser no-store/referrer/HSTS behavior to the existing remote hardening item.
- `build.py`, `requirements.txt`, `packaging/winget/`: add release verification that proves version, dependency/advisory state, SBOM/license inventory, MSIX signature/hash, appinstaller URL, winget URL/hash, and GitHub release assets agree.
- `gui/settings_dialog.py`: settings import/export exists, but there is no explicit schema version or pre-migration backup. Add a migration boundary before future settings growth.
- `core/localization.py`, `gui/help_docs.py`, `gui/settings_dialog.py`: Spanish catalog is a small shell subset; many help/settings/result strings remain literal. Add extraction/linting and pseudo-locale coverage before adding languages.
- `core/search.py`: modifier plugin API is programmatic only. Add entry-point/manifest loading, disabled-on-error state, and docs/tests before encouraging third-party plugins.
- `gui/main_window.py`, `gui/results_view.py`, `core/file_list.py`: EFU export exists for file-list interchange and CLI output supports CSV/JSON, but the GUI lacks FileLocator-style report exports with visible columns, content snippets, and reproducible search criteria.
- Tests: `python -m pytest -q` is verified green at 329 tests, but coverage is mostly unit-level. Add smoke harnesses for rendered UI state, accessibility names, MSIX/update metadata, dependency advisory gates, remote HTTPS/auth audit behavior, content-cache purge, and report export escaping.

## Rejected Ideas
- Replace SQLite with Xapian/Tantivy/Lucene now: Recoll/DocFetcher show their value, but QuickFind already has SQLite cache/FTS5 fallback and needs benchmarks before a storage-engine rewrite.
- Default Java/Tika server for all content search: DocFetcher-style broad extraction is useful, but a Java runtime would add distribution and attack-surface cost; keep it optional/plugin-gated.
- Cloud/AI semantic search as a core feature: Raycast/Fluent/Copernic show market interest, but it conflicts with QuickFind's local-first privacy and would add model/cloud dependencies before trust work is finished.
- Multi-user shared search without ACL enforcement: shared index products show demand, but QuickFind should not expose shared indexes until ACL semantics and audit logging are explicit.
- Web/Bing-style default search aggregation: community complaints about Windows Search point in the opposite direction; QuickFind should stay local and deterministic by default.
- Dependabot/Renovate automation: dependency freshness matters, but this repo's operating rules ban those services; use a local advisory/SBOM gate instead.
- Encrypted content-cache database as the first privacy step: useful for some users, but purge/retention/transparency controls are simpler, testable, and needed before key-management complexity.

## Sources
Direct OSS and adjacent:
- https://www.voidtools.com/support/everything/using_everything/
- https://www.voidtools.com/forum/viewtopic.php?t=9793
- https://github.com/cboxdoerfer/fsearch
- https://github.com/cboxdoerfer/fsearch/issues/115
- https://www.recoll.org/pages/features.html
- https://www.recoll.org/usermanual/webhelp/docs/RCL.PROGRAM.PYTHONAPI.INTRO.html
- https://www.recoll.org/usermanual/webhelp/docs/RCL.PROGRAM.PYTHONAPI.UPDATE.EXTINDEXER.html
- https://docfetcher.sourceforge.io/
- https://github.com/srwi/EverythingToolbar
- https://www.flowlauncher.com/plugins/
- https://github.com/microsoft/PowerToys/issues/32451
- https://github.com/phiresky/ripgrep-all

Commercial:
- https://help.listary.com/quick-switch
- https://www.listary.com/pro
- https://www.mythicsoft.com/filelocatorpro/information/
- https://mythicsoft.com/filelocatorpro/help/save_results.htm
- https://www.jam-software.com/ultrasearch
- https://antibody-software.com/wizfile/about
- https://copernic.com/en/desktop/pricing/

Standards and platform APIs:
- https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ns-winioctl-usn_record_v4
- https://learn.microsoft.com/en-us/windows/win32/search/-search-ifilter-about
- https://learn.microsoft.com/en-us/windows/win32/search/-search-3x-wds-extidx-propertyhandlers
- https://learn.microsoft.com/en-us/windows/msix/app-installer/update-settings
- https://learn.microsoft.com/en-us/windows/package-manager/package/manifest
- https://www.sqlite.org/fts5.html
- https://owasp.org/www-project-desktop-app-security-top-10/

Community, dependency, and advisory:
- https://pyinstaller.org/en/stable/CHANGES.html
- https://github.com/miurahr/py7zr/security/advisories/GHSA-gjrg-mpp7-g774
- https://github.com/pypa/pip-audit
- https://cyclonedx.org/

## Open Questions
None.
