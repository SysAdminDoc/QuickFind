# Research - QuickFind

## Executive Summary

QuickFind is a Windows-first Python/PyQt6 file search app that combines direct NTFS MFT reads, USN monitoring, non-admin `os.scandir` fallback, SQLite FTS5 cache, content adapters, archive filename search, CLI, remote web search, and optional Windows service mode. Verified: v0.8.1 has already shipped many items from the prior stale research file, including tests, content cache, HTTPS, rate limiting, service IPC, duplicate filename search, smart case, fuzzy search, `.quickfindignore`, and launcher mode. Highest-value direction: harden the new trust surfaces before adding broad features. Priority opportunities: remove runtime dependency installation from `quickfind.py`; gate or upgrade SQLite/FTS5 because the local Python runtime reports SQLite 3.49.1; harden remote token/CORS behavior; add content-index quotas, jobs, and adapter diagnostics; make Everything import saves atomic; pin dependencies and document the supported build/runtime matrix; add diagnostics for cache/service/index health; persist archive member metadata; add removable/offline drive state; defer large platform bets until the Windows engine is safer.

## Product Map

- Core workflows: elevate or fall back to non-admin indexing; load/save SQLite cache; search with modifiers; browse/open/delete/copy results; use launcher, CLI, HTTP/HTTPS, or service mode.
- User personas: Windows power users replacing Everything/Listary; sysadmins searching large local and removable drives; developers wanting scriptable search; privacy-minded users wanting local indexing.
- Platforms and distribution: Windows 10/11, Python 3.10+, PyInstaller source build; planned MSIX/winget work remains in `ROADMAP.md`.
- Key integrations and data flows: NTFS MFT/USN through `core/ntfs.py`; non-NTFS walks through `core/index.py`; SQLite entries/content/usage cache in `core/cache.py`; content extraction in `core/content/adapters.py`; remote browser UI in `server/http_server.py`; Windows service status via `service/`.

## Competitive Landscape

- Voidtools Everything: best-in-class Windows file search with mature duplicate/property/content work and SDK/IPC. Learn from its scoped content-index includes and hash-backed duplicate search; avoid copying closed-source/Windows-only integration assumptions without a clear open interface.
- Listary: strong commercial UX around fuzzy ranking, Quick Switch for file dialogs, network drive indexing, and habit-based result ordering. Learn from dialog/workflow integration; avoid paywall-style fragmentation in core search.
- WizFile: fast Windows search with global include/exclude filters, delayed startup for virtual drives, allocated-size filtering, and Seer/QuickLook preview integration. Learn from scan-time global excludes and startup delay controls; avoid relying on third-party preview tools as the only preview path.
- FSearch: open-source Everything-like Linux search with filters, bookmarks, regex/wildcards, and fast sortable indexed metadata. Learn from explicit include/exclude database configuration and offline/removable drive behavior; avoid pursuing Linux parity before isolating QuickFind's Win32 engine boundary.
- Recoll: mature content indexing across desktop and web interfaces with helper detection, OCR options, stemming, and format conversion layers. Learn from adapter diagnostics and opt-in indexing configuration; avoid heavy Xapian/JVM-style dependencies for QuickFind's lightweight Windows app.
- DocFetcher/DocFetcher Pro: document search with archive, PST/OST, and server-client/web access patterns. Learn from indexing archive names/content and enterprise-style recovery; avoid making content search automatic for all files without quotas.
- ripgrep-all/fd/ripgrep: fast CLI search patterns, smart case, ignore-file behavior, and adapter-based content extraction. QuickFind has adopted smart case and `.quickfindignore`; next useful lesson is transparent dependency/adapter reporting.
- Flow Launcher/PowerToys Run/EverythingToolbar: launcher ecosystems emphasize plugins, contextual actions, and taskbar/command-palette integration. Learn from contextual action APIs and plugin settings; avoid turning QuickFind into a general launcher before file-search reliability is finished.

## Security, Privacy, and Reliability

- Verified risk: `quickfind.py:22-36` installs `PyQt6` at runtime with `sys.executable -m pip`; this violates the repo's normal package-manager model and is unsafe for frozen apps because `sys.executable` becomes the packaged executable.
- Verified risk: local `py -3` reports SQLite 3.49.1 while QuickFind relies on FTS5 in `core/cache.py`; public advisories flag SQLite before 3.50.3 for an FTS5 integer overflow. Add a runtime/build gate or bundle a patched SQLite.
- Verified risk: `server/http_server.py:134-141` carries auth tokens in query parameters and `server/http_server.py:263` sends `Access-Control-Allow-Origin: *` for API responses. That is unnecessary for a local/remote file-path API and increases token/path exposure.
- Verified gap: `server/http_server.py:212` allows inline script/style in CSP. It is understandable for the embedded template, but extracting static JS/CSS would permit a stricter policy.
- Verified gap: `core/everything_import.py:150-194` writes imported filters/bookmarks directly, unlike the atomic saves in `gui/bookmarks.py`, `gui/filters.py`, and `gui/settings_dialog.py`.
- Verified gap: `core/content/adapters.py:12-120` supports TXT/PDF/DOCX/PPTX with fixed caps, but there is no visible queue, pause/resume, per-root opt-in, disk quota, failure summary, or missing-adapter diagnostics.
- Verified gap: `core/cache.py:437-499` loads all content freshness and returns paths only; no snippet/rank metadata is exposed for content results despite the FTS table storing text.
- Verified gap: `build.py:22-37` auto-installs PyInstaller during build and dependencies are unpinned in `requirements.txt`; reproducible releases and vulnerability audits need pinned application dependencies.

## Architecture Assessment

- Boundary improvement: split bootstrap/elevation/service dispatch from GUI launch in `quickfind.py` so source runs, frozen runs, and service commands have different dependency/error paths.
- Boundary improvement: make remote search a separate API layer with auth middleware, CORS policy, response schemas, and tests rather than embedding API and HTML concerns in one `BaseHTTPRequestHandler`.
- Refactor candidate: add a content-index job controller around `core/content/adapters.py` and `core/cache.py` so extraction is scheduled, cancellable, quota-aware, and observable instead of being driven opportunistically by searches.
- Refactor candidate: persist archive member metadata from `core/archives.py` into SQLite so `archive:` searches do not enumerate large archives on every query and can later support content-in-archive search.
- Test gaps: add tests for runtime bootstrap behavior, frozen-build guard paths, SQLite version/FTS5 gating, no-token-in-query remote flow, CORS denial, atomic Everything import saves, content quota cancellation, and archive member cache invalidation.
- Documentation gaps: README is comprehensive, but supported dependency versions, SQLite/FTS5 requirements, service security model, remote deployment model, and packaging/release verification are not explicit.
- Coverage note: accessibility, localization, plugin APIs, mobile-friendly remote UI, MSIX/winget distribution, OpenAPI docs, cross-platform engines, hash dedupe, migration/import paths, and upgrade strategy already have roadmap coverage or are addressed by the targeted additions here, so this pass avoids duplicating broad backlog items.

## Rejected Ideas

- Full Linux/macOS parity now: rejected for this pass because `core/ntfs.py`, service mode, and elevation are still central; isolate the engine first, then implement platform engines.
- Elasticsearch/OpenSearch backend: rejected because local SQLite FTS5 already fits the single-machine workload and keeps install size/ops low.
- Apache Tika as the primary extractor: rejected because a JVM dependency conflicts with the lightweight Windows utility shape; adapter plugins can support it later if users opt in.
- Automatic OCR for every PDF/image: rejected because Recoll-style OCR is valuable but CPU/disk expensive; make OCR opt-in per root or filter.
- Replacing PyQt6 with Electron/web UI: rejected because the current native GUI is already featureful and Electron would increase package size without fixing core reliability.
- General app launcher expansion: rejected until file-specific reliability, remote security, and packaging are stronger; launcher ecosystems show useful patterns, not a reason to broaden the core product.

## Sources

### Competitors and Adjacent Tools
- https://www.voidtools.com/everything-1.5/
- https://www.voidtools.com/forum/viewtopic.php?t=9996
- https://www.voidtools.com/forum/viewtopic.php?t=12795
- https://www.listary.com/
- https://help.listary.com/search-file
- https://help.listary.com/quick-switch
- https://antibody-software.com/wizfile/whats-new
- https://antibody-software.com/wizfile/download
- https://github.com/cboxdoerfer/fsearch
- https://github.com/cboxdoerfer/fsearch/wiki/Search-syntax
- https://www.recoll.org/pages/features.html
- https://www.recoll.org/usermanual/usermanual.html
- https://docfetcher.sourceforge.io/
- https://docfetcherpro.com/features/
- https://github.com/phiresky/ripgrep-all
- https://github.com/sharkdp/fd
- https://learn.microsoft.com/en-us/windows/powertoys/run
- https://github.com/microsoft/PowerToys/blob/main/doc/thirdPartyRunPlugins.md
- https://github.com/srwi/EverythingToolbar
- https://github.com/githubrobbi/UltraFastFileSearch

### Standards, Dependencies, Security
- https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ns-winioctl-usn_record_v4
- https://learn.microsoft.com/en-us/windows/dev-drive/
- https://learn.microsoft.com/en-us/windows/msix/app-installer/app-installer-file-overview
- https://learn.microsoft.com/en-us/windows/package-manager/package/manifest
- https://pyinstaller.org/en/v6.14.2/CHANGES.html
- https://sqlite.org/chronology.html
- https://www.tenable.com/plugins/nessus/265372
- https://github.com/jsvine/pdfplumber

### Community Signal
- https://news.ycombinator.com/item?id=41567262
- https://www.reddit.com/r/DataHoarder/comments/1brse4l/recoll_search_and_large_datasets/

## Open Questions

- Needs live validation: which Python runtime will release artifacts bundle, and can it provide SQLite 3.50.3+ or a patched `pysqlite3` wheel?
- Needs product decision: should remote search ever be exposed beyond localhost by default, or should LAN/WAN access require an explicit secure profile?
