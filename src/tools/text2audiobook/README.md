# text2audiobook

Fire-and-forget CLI for converting text sources (EPUB, Markdown, HTML, URL) to M4B audiobooks.

```
src/tools/text2audiobook/
├── src/text2audiobook/   # Python package
├── config.json           # CLI default config
├── data/                 # production input / staging / output / runs
└── __main__.py
```

## Usage

From the repo root (devenv active):

```bash
uv sync --group text-audiobook
text2audiobook
```

Or fetch a page directly:

```bash
text2audiobook --url https://retrochronic.com
```

`text2audiobook` loads `config.json` in the tool directory by default. Paths in the config are relative to that folder.

## Supported inputs

| Source | How |
|--------|-----|
| EPUB (`.epub`) | Drop under `data/input/` |
| Markdown (`.md`, `.markdown`) | Drop under `data/input/` |
| HTML (`.html`, `.htm`) | Drop under `data/input/` |
| URL (`.url`) | File with one `http(s)` URL on line 1; optional title on line 2 |
| CLI `--url` | One-shot fetch; skips the input-folder scan |

HTML/URL pages are chapterized on `h1`/`h2` (nav/header/footer stripped). Large anthologies still go through LLM chapter selection; set `selection.max_chapters` for a smoke run.

Example `.url` file:

```
https://retrochronic.com
```

## Data layout

| Path | Purpose |
|------|---------|
| `data/input/` | Sources the CLI scans (EPUB, Markdown, HTML, `.url`) |
| `data/staging/<book_slug>/` | Per-book scratch (`wav/`, `decisions.json`, `source.html`) |
| `data/staging/_url_cache/` | Fetched HTML cache (keyed by URL hash) |
| `data/output/<book_slug>.m4b` | Finished audiobooks |
| `data/runs/` | Run manifests, logs, `ledger.jsonl` |

`data/**` is gitignored; only `.gitkeep` files are tracked.

## Adding a format

1. Implement `SourceReader` in `src/text2audiobook/formats/your_format.py` (see `io.py` for the protocol).
2. Register it in `formats/__init__.py`.
