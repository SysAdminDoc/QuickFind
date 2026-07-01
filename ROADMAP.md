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

