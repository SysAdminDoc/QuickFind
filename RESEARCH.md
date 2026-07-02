# Research — QuickFind
Date: 2026-07-01 — replaces all prior research.

## Executive Summary
QuickFind (v0.8.57) is a local-first Windows file search tool: NTFS MFT/USN instant filename indexing, SQLite FTS5 content search over TXT/PDF/DOCX/PPTX/EML/source with sandboxed per-file worker adapters + optional Tesseract OCR + a Windows IFilter bridge, opt-in archive-metadata search, a scriptable CLI (`es.py`), a read-only HTTP/HTTPS server with a PWA web UI + OpenAPI, bookmarks/filters/EFU import-export, Catppuccin theme packs, a Windows service, and a custom-modifier plugin API. It is already ahead of the field on the axis that matters most: an **owned, on-disk FTS5 content index** that sidesteps Everything's in-RAM content ceiling (users report OOM at 11–60 GB), and it ships free everything Listary paywalls (dark theme, network drives, advanced syntax). The highest-value direction now is **trust/legal hardening + CLI parity + metadata breadth**, not new subsystems.

Top opportunities in priority order:
1. Resolve the PyQt6 (GPLv3) vs MIT-`LICENSE` inconsistency for the distributed binary (Verified conflict).
2. Explicitly pin `pdfminer.six>=20251230` so fresh installs can't drift into the CVE-2025-64512 RCE (Verified — current env is patched, but the pin is only transitive via pdfplumber).
3. `es.py` CLI parity with `fd`/`es.exe`: `-x/-X` exec, smart-case default, `-get-result-count/-get-total-size`, `--format`/`--hyperlink`, TSV/EFU export.
4. Launcher popup: inline preview + frecency ranking + scope prefixes (fzf / PowerToys Run patterns).
5. Property/metadata indexing (image dimensions/EXIF, audio tags) + folder-size + natural sort — Everything 1.5's headline gaps.
6. Content search inside archive members (rga-style) + `**` include/exclude glob semantics.
7. Packaging hardening: version resource in the spec, disable UPX for signed builds, OSS code signing (SignPath), pip-audit release gate.
8. Recoll-style "show compiled query" debug panel + query-time synonyms (cheap differentiators).
9. Opt-in local semantic search (FTS5 + sqlite-vec + local embeddings) as a longer-term leapfrog.

## Product Map
- **Core workflows:** index local/UNC/EFU/POSIX roots → search filename/path/content/archive → preview/open/recycle/export → CLI or read-only HTTP search → diagnose cache/service/index health.
- **Personas:** Windows power users replacing Windows Search/Everything; sysadmins over large local/network sets; developers using regex/git/CLI filters; users with offline drives and document archives.
- **Platforms/distribution:** Python 3.10+, Windows 10/11 primary (MFT/USN); Linux/macOS index configured roots via `os.scandir` + Watchdog; PyInstaller exe, MSIX/App Installer, winget manifests.
- **Integrations/data flows:** NTFS MFT/USN (`core/ntfs.py`) → SQLite cache + content/archive tables (`core/cache.py`) → PyQt6 GUI; Windows Credential Manager for SMB; Windows service IPC; HTTP/OpenAPI server; Everything EFU/filter/bookmark import.

## Competitive Landscape
- **voidtools Everything (closed, Windows):** sets the filename-speed/live-index bar; 1.5 adds property indexing (EXIF/audio/dimensions), folder-size indexing, fast sort, custom columns, natural sort, FAT/mapped-drive indexing, ETP federation. Learn: metadata breadth, `**` content include/exclude globs, es.exe flag surface. Avoid: in-RAM content index (hard OOM ceiling — QuickFind's on-disk FTS5 is the win), FTP transport, closed source.
- **fd + ripgrep (CLI stars):** smart-case default, `-x/-X` parallel exec, human-duration `--changed-within`, `--type` aliases, `--json` event stream, OSC-8 hyperlinks. Learn: make `es.py` feel like a first-class modern CLI. Avoid: nothing — pure parity target.
- **ripgrep-all (rga):** modular content adapters (Poppler/Pandoc/FFmpeg), recursive archive descent, bounded ZSTD extraction cache. Learn: search text *inside* archive members; document user-defined adapters via `plugin_loader`. Validates QuickFind's cached-extraction design.
- **Recoll (Xapian):** field query language, "show compiled query" debug, query-time synonyms/stemming decoupled from index, inotify monitor. Learn: the debug panel + synonym table are cheap, distinctive. Avoid: swapping FTS5 for Xapian (FTS5 already has bm25).
- **DocFetcher / Pro:** portable index repository (USB/cloud-syncable), media-metadata search, preview highlighting. Learn: relocatable self-contained index; QuickFind's `core/portable.py` is a partial head-start. Avoid: Java/Lucene weight.
- **Listary (commercial, $19.95):** paywalls dark theme, network-drive indexing, advanced syntax, custom actions — all of which QuickFind ships free/MIT. Its dialog Quick-Switch is the most-praised feature; QuickFind mirrors it in `core/dialog_switch.py`. Learn: match Quick-Switch reliability; market the free-vs-paywall contrast.
- **PowerToys Run / Flow Launcher / Wox:** bottleneck on external indexers (Windows Search / Everything); Flow's content search crashes. Learn: scope prefixes (`>` `=` `?`), frecency ranking, recent-selection recall. Avoid: dependence on someone else's index — QuickFind's owned index is the differentiator.

## Security, Privacy, and Reliability
- **pdfminer.six CVE-2025-64512 (RCE via crafted PDF, Windows high-risk).** Current env has the fixed 20251230, but `requirements.txt` pins only `pdfplumber==0.11.10` and lets pdfminer.six float transitively — a fresh install could regress. Add explicit `pdfminer.six>=20251230`. (Verified; `requirements.txt`.)
- **PyQt6 is GPLv3-or-commercial; `LICENSE` is MIT.** The distributed exe/MSIX bundles PyQt6, making the shipped work effectively GPLv3 — inconsistent with an MIT badge. The user accepts copyleft, so the low-effort resolution is to relicense the *distributed app* GPLv3 (with Qt/PyQt notices) or add a clear bundled-dependency-license note; a PySide6 (LGPL) migration is the alternative if MIT must hold. (Verified conflict; `LICENSE`, `README.md`.)
- **Untrusted-doc parsing** already runs in spawned worker isolation with per-file timeouts (`core/worker_isolation.py`, `core/content/sandbox.py`) and py7zr is pinned ≥1.1.3 (past the symlink/zip-slip CVEs) — good posture. Residual: worker blocks the full timeout on an instant crash (existing ROADMAP item); verify lxml entity resolution is disabled for docx/pptx XML.
- **Regression found and fixed this pass:** `es.py`'s newly-added `-r/--reverse` collided with `-r/--regex`, crashing the CLI at parser build; fixed to `-R` with regression tests (`tests/test_es_cli.py`). Root cause: no test exercised `parse_args`.
- **Remote/ACL guardrails** already tracked in ROADMAP (per-token ACL not enforced on served responses; single global session token; single-threaded server). No new remote risks surfaced.

## Architecture Assessment
- **CLI (`cli/es.py`)** is the weakest surface relative to peers: no exec, no smart-case, no aggregate output, no format template. Highest-ROI, lowest-risk area to close parity.
- **Content adapters (`core/content/adapters.py`, `core/archives.py`)** are well-factored for extension; archive *content* descent and user-documented custom adapters are natural next steps that reuse the existing worker model.
- **Metadata schema (`core/cache.py`)** currently stores name/path/size/dates/attrs/reparse/EA + FTS text. Property indexing (EXIF/ID3/dimensions/folder-size) needs new columns + adapters + results-view columns — the largest but highest-visibility gap vs Everything 1.5.
- **Packaging (`QuickFind.spec`, `build.py`)** lacks a `VSVersionInfo` resource and uses `upx=True` (both worsen AV/SmartScreen heuristics). `build.py` already scaffolds `--dep-audit`/`--sbom`; wire pip-audit to fail the build and attach a CycloneDX SBOM to releases.
- **Test gaps:** no test built the `es.py` parser (caused the shipped crash); property/metadata and content-archive-descent are unbuilt so untested. FTS5 branch is under-exercised locally because the dev SQLite (3.49.1) is below the patched minimum and falls back to LIKE — CI should run against a patched SQLite to cover the FTS path.

## Rejected Ideas
- **Apache Tika as a content backend** — JVM + REST-server dependency contradicts the lightweight sandboxed-Python-worker model; keep only as an optional exotic-format adapter. (Source: tika-python/tika-client.)
- **Everything-style in-RAM content index** — the exact design that causes Everything's OOM complaints; QuickFind's on-disk FTS5 is already superior. (Source: voidtools forum OOM threads.)
- **FTP/ETP transport** — QuickFind's REST/OpenAPI + PWA is a more modern remote surface than FTP; ETP *federation* (multi-host search) is interesting but deferred. (Source: voidtools ETP docs.)
- **FastCDC content-defined chunking** — real wins only for very large append-heavy files; mtime+hash delta re-index covers ~90% at a fraction of the effort. (Source: FastCDC USENIX ATC16.)
- **New fuzzy-search subsystem** — QuickFind already ships a `fuzzy:` modifier (`core/search.py`); no gap. (Source: repo.)
- **FAT/exFAT/ReFS and SMB-network "gaps" from Everything analysis** — already implemented (README: FAT32/exFAT/ReFS via `os.scandir`; SMB via `core/network_shares.py`). Not gaps.
- **Xapian backend swap** — FTS5 already provides bm25; migration cost unjustified. (Source: recoll.org.)

## Sources
Competitors (OSS/commercial):
- https://www.voidtools.com/support/everything/searching/
- https://www.voidtools.com/forum/viewtopic.php?p=35389
- https://www.voidtools.com/support/everything/etp/
- https://github.com/voidtools/ES
- https://www.voidtools.com/support/everything/http/
- https://www.voidtools.com/forum/viewtopic.php?t=11543
- https://github.com/sharkdp/fd
- https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
- https://github.com/phiresky/ripgrep-all
- https://phiresky.github.io/blog/2019/rga--ripgrep-for-zip-targz-docx-odt-epub-jpg/
- https://github.com/junegunn/fzf
- https://learn.microsoft.com/en-us/windows/powertoys/run
- https://github.com/Flow-Launcher/Flow.Launcher/issues/4328
- https://www.listary.com/pro
- https://www.recoll.org/usermanual/webhelp/docs/RCL.SEARCH.LANG.html
- https://docfetcherpro.com/features/

Platform / techniques:
- https://learn.microsoft.com/en-us/windows/win32/properties/property-system-overview
- https://learn.microsoft.com/en-us/uwp/api/windows.storage.search
- https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html
- https://github.com/asg017/sqlite-vec/issues/25
- https://tika.apache.org/2.0.0/formats.html

Security / packaging / deps:
- https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-wf5f-4jwr-ppcp
- https://github.com/advisories/GHSA-m8xw-9x5x-6vh3
- https://www.pythonguis.com/faq/licensing-differences-between-pyqt6-and-pyside6/
- https://github.com/pyinstaller/pyinstaller/issues/6754
- https://learn.microsoft.com/en-us/windows/msix/package/signing-package-overview
- https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
- https://github.com/pypa/pip-audit
- https://doc.qt.io/qt-6/whatsnew611.html

## Open Questions
- License intent: is the distributed binary meant to be MIT (forcing a PySide6 migration) or is GPLv3 for the shipped app acceptable (keep PyQt6, add notices)? Blocks the license fix's direction.
- Is there appetite for an optional heavyweight dependency (local embedding model, ~hundreds of MB) to enable semantic search, or must QuickFind stay dependency-light by default? Blocks prioritizing the sqlite-vec leapfrog.
- Target scale for property indexing — is folder-size/EXIF indexing expected on multi-million-file volumes (needs incremental, bounded computation) or only on user-selected roots? Affects the design's complexity tier.
