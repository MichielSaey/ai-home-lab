# EPUB → Audiobook (production)

Fire-and-forget CLI for converting EPUBs to M4B audiobooks.

```
src/tools/epub2audiobook/
├── src/epub2audiobook/   # Python package
├── config.json           # CLI default config
├── data/                 # production input / staging / output / runs
└── __main__.py           # optional: python -m from package path
```

## Usage

From the repo root (devenv active):

```bash
uv sync --group epub-audiobook
epub2audiobook
```

`epub2audiobook` loads `config.json` in the tool directory by default. Paths in the config are relative to that folder.

## Data layout

| Path | Purpose |
|------|---------|
| `data/epub/` | Canonical EPUB storage |
| `data/input/` | Symlinks into `data/epub/` (what the CLI scans) |
| `data/staging/<book_slug>/` | Per-book scratch (`wav/`, `decisions.json`) |
| `data/output/<book_slug>.m4b` | Finished audiobooks |
| `data/runs/` | Run manifests, logs, `ledger.jsonl` |

Drop new EPUBs into `data/epub/` and add a symlink under `data/input/`, or place files directly in `data/input/`.

`data/**` is gitignored; only `.gitkeep` files are tracked.

## Jellyfin publish

After a book is assembled (and on skip-if-exists re-runs), the pipeline can copy or rsync the M4B into a Jellyfin Books library and ask Jellyfin to scan just that file.

Publish is **off** until you set a destination in the environment (devenv loads repo-root `.env`):

| Variable | Purpose |
|----------|---------|
| `JELLYFIN_URL` | Server URL. Default: `http://192.168.0.10:8096` |
| `JELLYFIN_API_KEY` | Dashboard → API Keys. Without it, files are still transferred; the scan is skipped |
| `JELLYFIN_RSYNC_TARGET` | `user@192.168.0.10:/host/path/to/audiobooks` (typical: other host, SSH + rsync) |
| `JELLYFIN_LIBRARY_ROOT` | Local/mounted library root for `copy` mode |
| `JELLYFIN_CONTAINER_PATH` | Same folder as the Jellyfin **container** sees it. Required for a scan; host/rsync paths are never guessed |
| `JELLYFIN_PUBLISH_MODE` | `auto` (default), `rsync`, or `copy` |
| `JELLYFIN_PUBLISH` | `1` to force on, `0` to force off |

Layout written under the library root (Jellyfin Books / Bookshelf):

```text
Author Name/Book Title/Book Title.m4b
Author Name/Book Title/cover.jpg
```

A failed publish is logged and recorded on the run; the local M4B is still a success.

SSH to the Jellyfin host must work non-interactively for rsync (`ssh user@192.168.0.10` with a key). Create the API key and point a Books library at the audiobooks folder in Jellyfin yourself.

## Experimentation

For step-by-step work and smoke tests, use `src/epub-to-audiobook/` (notebook + separate `data/` tree) if present.
