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

### P1 - Trust, Reliability, and Observability

- [ ] P1 — Directory rename/move leaves stale cached paths on descendants
  Why: renaming an indexed folder while running keeps `_path` on every child, so results show wrong paths, opens fail, and the stale paths persist to the DB across restarts until a full re-index.
  Where: core/index.py `_apply_usn_changes` (only the renamed entry calls `invalidate_path`); cache.py DB rows for children are never updated.
- [ ] P1 — USN journal overflow/wrap is silently treated as "no changes"
  Why: `read_usn_journal` returns `[]` on `ERROR_JOURNAL_ENTRY_DELETED`; catchup then marks the drive fresh and the live monitor polls a dead position forever, permanently missing changes since the purge. Journal `FirstUsn` is parsed but never compared to the resume position; the self-created journal is only 8 MB.
  Where: core/index.py `usn_catchup` / `USNMonitorThread.run`; core/ntfs.py `read_usn_journal`, journal size `0x800000`.

### P2 - Search Depth and Workflow Expansion

- [ ] P2 — Launcher popup search runs synchronously on the GUI thread
  Why: the launcher accepts full engine syntax, so a `content:`, `regex:`, or `dupe:hash` query freezes the whole UI per debounced keystroke and races the main window's search workers.
  Where: gui/launcher_popup.py (`self._engine.search` on the GUI thread).
- [ ] P2 — Per-token ACL is not enforced on the HTTP search surface
  Why: `filter_results_by_acl` has no callers outside tests; `_handle_api_search` returns unfiltered results, so shared-mode path restrictions are not applied to served responses.
  Where: server/acl.py, server/http_server.py `_handle_api_search`.
- [ ] P2 — Remote server is single-threaded and leaks its socket on stop
  Why: `HTTPServer` (not `ThreadingHTTPServer`) means one slow client (or the per-result stat loop) blocks all requests; `stop()` calls `shutdown()` but never `server_close()` or joins the thread.
  Where: server/http_server.py server construction and `stop()`.

### P3 — Larger Features

- [ ] P3 — Settings/Diagnostics/Help dialog titles and buttons ignore the Spanish catalog
  Why: `settings.*`, `diagnostics.*`, and `help.*` keys exist but the dialogs hardcode English, so `language = "es"` leaves these dialogs untranslated.
  Where: gui/settings_dialog.py, gui/diagnostics_dialog.py, gui/help_docs.py.
- [ ] P3 — Bare `dm:`/`dc:` date means "on or after" instead of that day's range
  Why: a bare date sets only the `_after` bound, unlike Everything which treats it as a full-day range.
  Where: core/search.py date-modifier parsing.
- [ ] P3 — Extraction worker blocks the full timeout on an instant crash
  Why: the parent only waits on `result_queue.get(timeout=...)`, so a worker that dies in milliseconds still costs the full 10 s; poll `process.sentinel` to detect early death.
  Where: core/worker_isolation.py.
- [ ] P3 — Remote UI uses one global session token with no expiry or logout
  Why: every authenticated client shares the same token; a leaked cookie grants all sessions until restart, and there is no `/logout` or `Max-Age`.
  Where: server/http_server.py session handling.
- [ ] P3 — Remote `max` up to 10000 is silently capped at 1000 in the payload builder
  Why: `_coerce_remote_max_results`/OpenAPI advertise 10000 but `_build_result_payloads` slices results (fixed to honor search's max this pass; verify no other cap remains).
  Where: server/http_server.py.
- [ ] P3 — Dead code: `queue_path_resolve` machinery, `ColumnFilterRow`, hidden compat `FilterBar`
  Why: unused paths advertised in docstrings/menus that never run; remove to reduce confusion.
  Where: core/index.py deferred path-resolution; gui/results_view.py `ColumnFilterRow`; gui/main_window.py hidden `FilterBar`.
- [ ] P3 — `filters.json` written non-atomically in main window
  Why: `open('w')` + `json.dump` (unlike the atomic tmp+replace used elsewhere) can corrupt custom filters on a crash mid-write.
  Where: gui/main_window.py `_show_manage_filters`.

### 2026-07-01 External competitive research

#### P1 — Trust, legal, and security
- [ ] P1 — Resolve PyQt6 (GPLv3) vs MIT `LICENSE` inconsistency for the distributed binary
  Why: the shipped exe/MSIX bundles PyQt6, which is GPLv3-or-commercial, so the distributed work is effectively GPLv3 while the repo advertises MIT — a real license conflict. User accepts copyleft, so relicensing the distributed app is the low-effort path.
  Evidence: pythonguis PyQt6-vs-PySide6 licensing; `LICENSE`, `README.md`.
  Touches: LICENSE, README.md (badge + a NOTICE of bundled Qt/PyQt terms), or a PySide6 migration if MIT must hold.
  Acceptance: the distributed artifact's license is internally consistent — either GPLv3 with Qt/PyQt attribution and a written source offer, or the GUI runs on PySide6 (LGPL) and MIT is preserved.
  Complexity: S (relicense) / XL (PySide6 migration)
- [ ] P1 — Explicitly pin `pdfminer.six>=20251230` in requirements
  Why: pdfplumber pulls pdfminer.six transitively; versions <20251230 carry CVE-2025-64512 (arbitrary code execution from a crafted PDF CMap, Windows high-risk). QuickFind parses untrusted PDFs, and a fresh install could resolve an older pdfminer.six.
  Evidence: GHSA-wf5f-4jwr-ppcp; `requirements.txt` pins only pdfplumber.
  Touches: requirements.txt (add explicit pin), build dep-audit.
  Acceptance: a clean `pip install -r requirements.txt` installs pdfminer.six ≥20251230; `--dep-audit` reports no advisory for it.
  Complexity: S

#### P2 — CLI parity, workflow, packaging (quick wins first)
- [ ] P2 — `es.py` smart-case default (uppercase in query ⇒ case-sensitive)
  Why: fd and ripgrep both default to smart-case; QuickFind's `-i/--case` is opt-in only, so scripts and users get surprising case-insensitive behavior with mixed-case queries.
  Evidence: github.com/sharkdp/fd; mankier rg `-S`.
  Touches: cli/es.py, core/search.py (case-mode selection).
  Acceptance: `es Foo` is case-sensitive; `es foo` is insensitive; explicit `-i`/`nocase:` still override.
  Complexity: S
- [ ] P2 — `es.py` aggregate output: `--count` (result count) and `--total-size`
  Why: es.exe ships `-get-result-count`/`-get-total-size`; these are the two most-scripted-against outputs and QuickFind's CLI has neither.
  Evidence: github.com/voidtools/ES.
  Touches: cli/es.py.
  Acceptance: `es <q> --count` prints only the integer count; `--total-size` prints summed bytes; both suppress the result list and honor filters.
  Complexity: S
- [ ] P2 — `es.py` `--format` template and `--hyperlink` (OSC-8) output
  Why: fd/rg let scripts template output and emit clickable terminal paths; QuickFind only has fixed plain/CSV/JSON.
  Evidence: github.com/sharkdp/fd; mankier rg `--hyperlink-format`.
  Touches: cli/es.py.
  Acceptance: `--format "{path}\t{size}"` renders per-result placeholders; `--hyperlink` wraps paths in OSC-8 escapes in a TTY.
  Complexity: M
- [ ] P2 — `es.py` `-x/--exec` and `-X/--exec-batch`
  Why: running a command per result (parallel) or once over all results is the single biggest table-stakes miss vs fd; without it QuickFind's CLI can't drive pipelines.
  Evidence: github.com/sharkdp/fd.
  Touches: cli/es.py.
  Acceptance: `es <q> -x echo {}` runs per result with `{}`/`{/}`/`{.}` placeholders; `-X` runs one command with all results appended; non-zero child exit is surfaced.
  Complexity: M
- [ ] P2 — `es.py` TSV/EFU export and `--no-header`
  Why: es.exe exports CSV/TSV/TXT/EFU; QuickFind has CSV/JSON only and an EFU importer but no CLI EFU export.
  Evidence: github.com/voidtools/ES; core/file_list.py (EFU writer exists).
  Touches: cli/es.py, core/file_list.py.
  Acceptance: `--tsv`, `--export-efu <path>`, and `--no-header` all produce correct output reusing the existing EFU writer.
  Complexity: S
- [ ] P2 — Content search inside archive members (rga-style descent)
  Why: `archive:` currently searches member metadata only; rga searches extracted text inside zip/7z members, which is the natural next step and reuses the sandboxed worker model.
  Evidence: github.com/phiresky/ripgrep-all; core/archives.py, core/content/adapters.py.
  Touches: core/archives.py, core/content/indexer.py, core/content/adapters.py, core/cache.py (bound + compress the extraction cache).
  Acceptance: `content:` matches text inside supported archive members; extraction cache is size-capped; malformed members fail closed in the worker.
  Complexity: L
- [ ] P2 — Content include/exclude `**` glob semantics + explicit max-file-size default
  Why: Everything 1.5 scopes content indexing with `c:\docs\**.docx` (`**`=recursive, `*`=one level) and a size cap; aligning avoids surprising over/under-indexing.
  Evidence: voidtools content-index forum (t=9833), searching docs.
  Touches: core/content/indexer.py, gui/settings_dialog.py (content roots/extensions/size).
  Acceptance: content roots accept `**`/`*` glob semantics; a documented default max file size is enforced and shown in settings.
  Complexity: M
- [ ] P2 — PyInstaller spec hardening: embed VSVersionInfo, disable UPX for signed builds
  Why: `QuickFind.spec` has no version resource and uses `upx=True`; both worsen AV/SmartScreen heuristics and make the exe look untrusted in Explorer properties.
  Evidence: pyinstaller#6754 (UPX false positives); ahmedsyntax onefile guide (version resource).
  Touches: QuickFind.spec, build.py (generate VSVersionInfo from core/version.py).
  Acceptance: the built exe shows CompanyName/FileVersion/ProductVersion in Properties; release builds are produced without UPX.
  Complexity: S
- [ ] P2 — Make `--dep-audit` a build-failing pip-audit gate and attach the CycloneDX SBOM to releases
  Why: build.py already scaffolds `--dep-audit`/`--sbom`; wiring pip-audit to fail the build and publishing the SBOM turns it into a real supply-chain gate.
  Evidence: github.com/pypa/pip-audit; CycloneDX python.
  Touches: build.py (`--release-check`/`--dep-audit`), release process.
  Acceptance: a known-vulnerable pinned dep fails `--release-check`; a CycloneDX SBOM is emitted and attachable to the GitHub release.
  Complexity: M
- [ ] P2 — OSS code signing (SignPath Foundation) + document SmartScreen reputation ramp
  Why: unsigned PyInstaller exes trigger SmartScreen; SignPath offers free OV signing for qualifying OSS, and EV no longer instantly bypasses SmartScreen (reputation still ramps).
  Evidence: MS code-signing-options docs; MS smartscreen-reputation docs. Operator-gated (external enrollment).
  Touches: release/build process, README install notes.
  Acceptance: release exe/MSIX is OV-signed; README documents the expected SmartScreen ramp.
  Complexity: M
- [ ] P2 — Launcher popup: inline preview + frecency ranking + scope prefixes
  Why: fzf shows a preview beside results and PowerToys Run uses scope sigils + frecency; QuickFind's popup has none, and (per project rule) actions must be clickable buttons, not keyboard shortcuts.
  Evidence: github.com/junegunn/fzf; learn.microsoft.com PowerToys Run. Depends on the existing P2 item that moves launcher search off the GUI thread.
  Touches: gui/launcher_popup.py, gui/preview_pane.py, core/search.py (frecency), core/query_slots.py (prefixes).
  Acceptance: selecting a result shows a preview in the popup; recently/frequently opened files rank higher; `>` scopes to content and `=` to calculator, alongside the existing `@slot`.
  Complexity: M

#### P3 — Metadata breadth, search UX, larger bets
- [ ] P3 — Natural (human) sort order for name/path columns
  Why: Everything defaults to natural sort (file2 < file10); QuickFind's lexical sort orders file10 before file2, which power users notice immediately.
  Evidence: voidtools 1.5 thread (p=35389).
  Touches: core/search.py sort comparators, cache.py ORDER BY (or a natural-key collation), gui/results_view.py.
  Acceptance: sorting by name orders `file2` before `file10`; toggleable if lexical is needed.
  Complexity: S
- [ ] P3 — "Show compiled query" debug panel
  Why: Recoll exposes the parsed/compiled query so users can understand why a search matched; QuickFind's rich modifier parser is opaque when a query misbehaves.
  Evidence: recoll.org query-language docs.
  Touches: core/search.py (expose parsed structure), a read-only GUI panel + `es.py --explain`.
  Acceptance: a query can be inspected to show parsed modifiers, terms, and the resulting FTS5 MATCH / filter predicates.
  Complexity: S
- [ ] P3 — Query-time synonyms / expansion table
  Why: Recoll applies a synonyms file at query time for higher recall without reindexing; cheap and distinctive for document search.
  Evidence: recoll.org Python API (synonyms).
  Touches: core/search.py (query expansion), a user-editable synonyms store, settings.
  Acceptance: with a synonyms entry, a query for one term also matches its configured synonyms; disabled by default.
  Complexity: M
- [ ] P3 — Property/metadata indexing: image dimensions + EXIF, audio (ID3) tags
  Why: Everything 1.5's headline feature and DocFetcher indexes media metadata; QuickFind indexes no rich file properties, only name/size/dates/attrs + FTS text.
  Evidence: voidtools 1.5 properties thread (t=9788); docfetcher.sourceforge.io.
  Touches: core/content adapters (new EXIF/ID3 extractors in the worker model), core/cache.py (property columns), gui/results_view.py (custom columns), core/search.py (property modifiers).
  Acceptance: images expose width/height/EXIF and audio exposes tag fields as searchable/sortable columns for indexed roots.
  Complexity: L
- [ ] P3 — Folder-size indexing and sort
  Why: Everything 1.5 indexes child size/count for instant folder-size sort; QuickFind cannot sort folders by aggregate size.
  Evidence: voidtools 1.5 beta thread (t=9787).
  Touches: core/index.py (aggregate child size, incremental on USN changes), cache.py, gui/results_view.py.
  Acceptance: folders can be sorted by total size; the aggregate updates incrementally rather than requiring a full rescan.
  Complexity: L
- [ ] P3 — Opt-in local semantic search (FTS5 + sqlite-vec + local embeddings)
  Why: hybrid keyword+vector search over document content is a genuine leapfrog no filename-search competitor offers; sqlite-vec drops into the existing SQLite file and multiple OSS tools prove the pattern.
  Evidence: alexgarcia.xyz sqlite-vec stable release; sqlite-vec#25 (brute-force ceiling).
  Touches: core/cache.py (vec table), core/content/indexer.py (embed on index), core/search.py (hybrid merge), an optional local embedding backend (Ollama/GGUF).
  Acceptance: with the feature explicitly enabled, `semantic:` (or a hybrid mode) returns relevance-ranked content hits; disabled by default so no embedding dependency is required for normal use.
  Complexity: XL

