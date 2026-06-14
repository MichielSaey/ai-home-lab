# EPUB → Audiobook (production)

Fire-and-forget CLI for converting EPUBs to M4B audiobooks.

```
src/epub2audiobook/
├── src/epub2audiobook/   # Python package
├── config.json           # CLI default config
├── data/                 # production input / staging / output / runs
└── __main__.py           # optional: python src/epub2audiobook
```

## Usage

From the repo root (devenv active):

```bash
uv sync --group epub-audiobook
epub2audiobook
```

`epub2audiobook` loads `config.json` in this directory by default. Paths in the config are relative to this folder.

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

## Experimentation

For step-by-step work and smoke tests, use `src/epub-to-audiobook/` (notebook + separate `data/` tree).
