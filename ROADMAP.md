# QuickFind Roadmap

NTFS-MFT-backed instant file search (PyQt6 + SQLite FTS5). Voidtools Everything alternative with CLI, HTTP server, and Catppuccin theme. Roadmap strengthens content search, network share indexing, and cross-platform reach.

## Planned Features

### Indexing

### Content Search

### Search Syntax

### UX

### Remote

### Cross-platform

### Packaging

## Competitive Research
- **Voidtools Everything** — gold standard; closed source, Windows only, no content search. Lesson: content + remote + Linux are the deficits QuickFind should own.
- **fd + ripgrep** — CLI stars. Lesson: keep CLI fast, ensure `es.py` behaves predictably in scripts.
- **Recoll / DocFetcher** — content indexers. Lesson: don't rebuild Tika; borrow it.
- **Windows Search** — built-in, slow on big MFT. Lesson: explicit "beats Windows Search" metric in README (already present in feeling, make it a benchmark).

## Nice-to-Haves

## Research-Driven Additions

### P0 - Security and Release Blockers

- [ ] P0 — Sandbox content and archive extraction workers
  Why: PDF/DOCX/PPTX/EML and archive probing currently run in-process, so hostile or hanging parsers can still stall or crash indexing despite quotas.
  Evidence: `core/content/adapters.py`, `core/content/indexer.py`, `core/archives.py`, py7zr advisory/release discussion, Recoll/DocFetcher extractor models.
  Touches: `core/content/adapters.py`, `core/content/indexer.py`, `core/archives.py`, `core/cache.py`, `gui/diagnostics_dialog.py`, `tests/test_content_search.py`, `tests/test_archive_search.py`
  Acceptance: Extraction/probing runs through cancellable worker isolation with per-file timeout, byte caps, adapter failure/quarantine diagnostics, and tests proving a hanging adapter cannot block the GUI/index job.
  Complexity: L

- [ ] P0 — Verify release artifacts, update feeds, and locked clean paths
  Why: MSIX/App Installer/winget metadata points at GitHub release assets, but the build script does not verify release URLs, signatures, hashes, or locked stale artifacts before publishing.
  Evidence: `build.py:95`, `build.py:115`, `packaging/winget/`, Microsoft App Installer and winget manifest docs.
  Touches: `build.py`, `packaging/winget/`, `tests/test_version.py`, `README.md`
  Acceptance: A local release-check command validates version consistency, MSIX signature/hash, appinstaller and winget URLs, GitHub release asset presence, and cleanly reports/remediates locked build outputs.
  Complexity: M

### P1 - Trust, Reliability, and Observability

- [ ] P1 — Persist live USN journal checkpoints after monitor batches
  Why: File-row changes are batch-synced during live monitoring, but `drives.next_usn` is only refreshed on full cache saves, creating crash windows with stale journal replay positions.
  Evidence: `core/cache.py:1030`, `core/index.py:1732`, `core/index.py:1945`, Everything/FSearch live-update expectations.
  Touches: `core/index.py`, `core/cache.py`, `tests/test_index.py`, `tests/test_cache.py`
  Acceptance: After successful live USN batches, each affected drive's journal ID and next USN are durably flushed; restart tests prove no duplicate replay storm and proper full reindex on journal recycle.
  Complexity: M

- [ ] P1 — Harden remote session cookies and auth POST origin checks
  Why: Remote search is read-only and token-gated, but HTTPS cookies lack `Secure`, `/auth` has no Origin/Referer guard, and inline CSP should be intentionally documented or reduced.
  Evidence: `server/http_server.py:598`, `server/http_server.py:601`, `server/http_server.py:660`, OWASP-style session expectations, commercial remote-search surfaces.
  Touches: `server/http_server.py`, `tests/test_http_server.py`, `gui/settings_validation.py`
  Acceptance: HTTPS sessions set `Secure; HttpOnly; SameSite=Strict`, auth POST rejects cross-origin form submissions when an Origin/Referer is present, docs/tests cover HTTP vs HTTPS behavior, and no query token path is reintroduced.
  Complexity: S

- [ ] P1 — Add redacted diagnostics support bundle export
  Why: The diagnostics UI shows cache, drive, service, and content state but there is no single redacted artifact for troubleshooting stale indexes, parser failures, HTTP config, or release runtime drift.
  Evidence: `gui/diagnostics_dialog.py`, `gui/status_indicators.py`, `core/cache.py:665`, `build.py:66`, FileLocator/Copernic enterprise support patterns.
  Touches: `gui/diagnostics_dialog.py`, `gui/main_window.py`, `core/cache.py`, `build.py`, `tests/test_cache.py`, `tests/test_main_window.py`
  Acceptance: Tools > Index Diagnostics can export a JSON/ZIP bundle with runtime matrix, cache integrity, drive states, content adapter failures, settings summary with secrets redacted, recent log tail, and a test proving tokens/passwords are absent.
  Complexity: M

- [ ] P1 — Version settings/profile migrations with backup and rollback
  Why: Settings import/export exists, but persisted settings have no schema version or pre-migration backup as options grow across remote, content, i18n, plugins, and packaging features.
  Evidence: `gui/settings_dialog.py:145`, `gui/settings_dialog.py:197`, `gui/settings_validation.py`, Listary/Flow portable/profile expectations.
  Touches: `gui/settings_dialog.py`, `gui/settings_validation.py`, `tests/test_settings_validation.py`, `README.md`
  Acceptance: Settings JSON includes schema version, migrations run through validated steps, old files are backed up before replacement, invalid imports can roll back to the previous profile, and tests cover forward/unknown versions.
  Complexity: M

- [ ] P1 — Add rendered UI accessibility smoke tests
  Why: Current accessibility tests validate helper metadata, but they do not exercise rendered settings/results/preview/diagnostics focus order or accessible names.
  Evidence: `gui/accessibility.py`, `tests/test_accessibility.py`, `tests/test_main_window.py`, README accessibility claim, WCAG/UIA expectations for desktop tools.
  Touches: `gui/accessibility.py`, `gui/main_window.py`, `gui/settings_dialog.py`, `gui/results_view.py`, `gui/diagnostics_dialog.py`, `tests/`
  Acceptance: A headless/offscreen PyQt smoke test opens core windows, verifies accessible names/descriptions for primary controls, confirms keyboard focus traversal reaches search/filter/results/actions, and fails on missing critical labels.
  Complexity: M

- [ ] P1 — Add Windows IFilter and property-handler content adapter
  Why: Current content search covers selected Python parsers only; Windows IFilter/property handlers unlock installed Office/PDF/email/metadata formats without making Windows Search the filename engine.
  Evidence: `core/content/adapters.py`, Microsoft IFilter docs, Windows Search AQS/property model, FileLocator/UltraSearch/Copernic content-search feature sets.
  Touches: `core/content/adapters.py`, `core/content/indexer.py`, `core/cache.py`, `gui/settings_dialog.py`, `tests/test_content_search.py`
  Acceptance: On Windows, an optional adapter extracts text/properties through installed IFilters/property handlers with timeout/fallback diagnostics, surfaces extractor name in content cache stats, and gracefully disables when COM/filter APIs are unavailable.
  Complexity: L

- [ ] P1 — Add recoverable delete action feedback
  Why: Delete-to-Recycle is intentionally no-confirm, but current context-menu deletion is silent and does not report success/failure or recovery details.
  Evidence: `gui/context_menu.py:104`, `gui/main_window.py`, commercial search tools' result action feedback.
  Touches: `gui/context_menu.py`, `gui/main_window.py`, `gui/results_view.py`, `tests/test_main_window.py`
  Acceptance: Recycle actions emit status/toast/log feedback with count/path summary, report SHFileOperation errors visibly, refresh affected result rows, and expose a non-modal recovery hint without adding confirmation dialogs.
  Complexity: S

### P2 - Search Depth and Workflow Expansion

- [ ] P2 — Package and discover modifier plugins safely
  Why: The modifier plugin API is programmatic only, so third-party plugins cannot be installed, disabled, or quarantined without code edits.
  Evidence: `core/search.py:182`, `tests/test_search.py:337`, Flow Launcher plugin store/docs, PowerToys Run plugin model.
  Touches: `core/search.py`, `gui/settings_dialog.py`, `gui/help_docs.py`, `README.md`, `tests/test_search.py`
  Acceptance: QuickFind discovers plugin manifests or Python entry points from a configured plugin directory, validates names/permissions, disables failed plugins without breaking search, lists plugin status in settings/help, and tests conflict/quarantine behavior.
  Complexity: L

- [ ] P2 — Incrementally reindex content from file-change events
  Why: Content indexing is a manual/background pass over all entries; changed files should enqueue targeted content refreshes from USN/watchdog updates.
  Evidence: `gui/main_window.py:137`, `core/content/indexer.py`, `core/index.py:1732`, Recoll/FSearch update workflows.
  Touches: `core/index.py`, `core/content/indexer.py`, `gui/main_window.py`, `core/cache.py`, `tests/test_content_search.py`, `tests/test_index.py`
  Acceptance: Creates/renames/modifies/deletes enqueue bounded content-cache refresh/removal work for supported files, diagnostics show queue status/failures, and tests prove stale snippets disappear after file changes.
  Complexity: L

- [ ] P2 — Expand localization coverage with extraction and pseudo-locale checks
  Why: English/Spanish localization currently covers a small shell catalog while help, settings, diagnostics, and result text still contain many literals.
  Evidence: `core/localization.py`, `gui/help_docs.py`, `gui/settings_dialog.py`, `tests/test_localization.py`
  Touches: `core/localization.py`, `gui/help_docs.py`, `gui/settings_dialog.py`, `gui/main_window.py`, `tests/test_localization.py`
  Acceptance: Adds a string-key extraction/lint command, pseudo-locale test coverage, Spanish coverage for help/settings/diagnostics primary text, and fallback tests for missing keys.
  Complexity: M

- [ ] P2 — Add repeatable benchmark harness and README metrics
  Why: README claims sub-second/millions-file performance, but there is no reproducible benchmark for cold cache, warm cache, content search, USN catchup, or Windows Search comparison.
  Evidence: `README.md`, `core/index.py`, `core/search.py`, Voidtools Everything and Windows Search performance positioning.
  Touches: `tools/` or `tests/benchmarks/`, `core/index.py`, `core/search.py`, `README.md`
  Acceptance: A local benchmark command builds synthetic trees, records cold/warm/index/search/content timings and memory, exports JSON/CSV, and README badges/text cite the latest measured run.
  Complexity: M

- [ ] P2 — Add visual query builder and filter chips for advanced modifiers
  Why: QuickFind has rich boolean/modifier syntax, but complex queries are discoverable mainly through offline docs rather than editable UI state.
  Evidence: `core/search.py`, `gui/help_docs.py`, Everything/FSearch filters, Recoll query workflow, FileLocator Pro query UX.
  Touches: `gui/main_window.py`, `gui/filters.py`, `gui/help_docs.py`, `core/search.py`, `tests/test_search.py`, `tests/test_main_window.py`
  Acceptance: Users can compose/edit modifiers as removable chips, chips round-trip to the raw query string, invalid modifiers show inline status, and parser tests cover UI-generated queries.
  Complexity: M

- [ ] P2 — Add duplicate review workflow with safe remediation
  Why: `dupe:` and `dupe:hash` identify duplicates, but there is no grouped review surface, keep-rule preview, or safe batch action.
  Evidence: `core/search.py:1142`, `gui/results_view.py`, UltraSearch/WizFile duplicate and hardlink features.
  Touches: `core/search.py`, `gui/main_window.py`, `gui/results_view.py`, `gui/context_menu.py`, `tests/test_search.py`, `tests/test_main_window.py`
  Acceptance: Duplicate results can be grouped by duplicate set/hash, users can preview keep/delete candidates, safe actions move only selected duplicates to Recycle Bin with feedback, and tests cover folders, hardlinks, and missing files.
  Complexity: L

### P3 — Larger Features

- [ ] P3 — Add portable/cloud-profile mode with machine-scoped caches
  Why: Users sync launcher/search profiles through OneDrive/Dropbox, but cache and plugin state need machine-specific identity to avoid stale paths and conflicts.
  Evidence: `gui/settings_dialog.py`, `core/cache.py`, Flow Launcher portable-mode issue signal, Listary portable/profile workflows.
  Touches: `gui/settings_dialog.py`, `core/cache.py`, `core/version.py`, `README.md`, `tests/test_settings_validation.py`
  Acceptance: A portable mode stores settings beside the executable or a chosen root, caches include a machine/source identity, synced profiles do not reuse incompatible cache DBs, and diagnostics report portable/profile paths.
  Complexity: L

- [ ] P3 — Make the remote web UI installable and mobile-tested
  Why: Remote search has cards and OpenAPI, but there is no PWA manifest, offline shell, or mobile viewport verification for phone/tablet lookup flows.
  Evidence: `server/http_server.py`, `tests/test_http_server.py`, Fluent/Copernic remote/search-app expectations.
  Touches: `server/http_server.py`, `tests/test_http_server.py`, `README.md`
  Acceptance: Remote UI includes responsive mobile layout tests, PWA manifest/icons, offline/error shell for disconnected API calls, and no weakening of read-only auth behavior.
  Complexity: M

- [ ] P3 — Prototype shared read-only search server with explicit ACL boundary
  Why: Commercial and Recoll-style web deployments show demand for shared indexes, but exposing personal filesystem results requires an explicit access-control model before multi-user use.
  Evidence: `server/http_server.py`, `service/windows_service.py`, Recoll web/Python API docs, FileLocator/Copernic enterprise search patterns.
  Touches: `server/http_server.py`, `service/windows_service.py`, `core/index.py`, `gui/settings_dialog.py`, `README.md`, `tests/test_http_server.py`
  Acceptance: A prototype supports named read-only indexes and per-token allowed roots, denies paths outside token roots, logs denied requests, and documents that shared mode is disabled by default.
  Complexity: XL
