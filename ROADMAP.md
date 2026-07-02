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

### P3 — Larger Features

- [ ] P3 — Settings/Diagnostics/Help dialog titles and buttons ignore the Spanish catalog
  Why: `settings.*`, `diagnostics.*`, and `help.*` keys exist but the dialogs hardcode English, so `language = "es"` leaves these dialogs untranslated.
  Where: gui/settings_dialog.py, gui/diagnostics_dialog.py, gui/help_docs.py.

### 2026-07-01 External competitive research

#### P2 — CLI parity, workflow, packaging (quick wins first)
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

