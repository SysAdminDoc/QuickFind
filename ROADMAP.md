# QuickFind Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Actionable Items

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
