# text2audiobook

v2 fire-and-forget CLI: extract → format → speak, then an M4B audiobook.

```
src/tools/text2audiobook/
├── src/text2audiobook/   # Python package
├── config.json           # CLI default config
├── data/                 # production input / staging / output / runs
└── __main__.py
```

Package version in `pyproject.toml` stays `0.1.0`; this README describes the **tool** v2 pipeline.

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

### Stages

A full run is the default. Re-run a layer without repeating the others:

```bash
text2audiobook --stage extract
text2audiobook --stage format
text2audiobook --stage speak
text2audiobook --stage speak --voice bf_emma
text2audiobook --force
```

`--stage speak` loads Kokoro only (no Qwen). `--force` invalidates skip for the requested stages, and on extract also refetches cached `.url` HTML. There is no v1 migrator: delete `data/staging/<book_slug>/` to rebuild.

### Voices

```bash
text2audiobook --list-voices
text2audiobook --voice af_bella
text2audiobook --voice random
```

Default voice is `af_bella` (American, lang `a`). `--voice random` picks from official grades A / A- / B- without replacement until the pool wraps. Language follows the voice prefix (`bf_emma` → British `b`).

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

Stems live under `data/staging/<book_slug>/`:

| Path | Purpose |
|------|---------|
| `extract/` | Selected chapters + extract manifest |
| `format/` | LLM windows (`chunks.jsonl`), merged chapter scripts, format manifest |
| `speak/` | Phoneme units, WAVs, speak manifest (voice, speed, bitrate, loudnorm, silences) |
| `data/staging/_url_cache/` | Fetched HTML cache (keyed by URL hash) |
| `data/output/<book_slug>.m4b` | Finished audiobooks |
| `data/runs/` | Run manifests, logs, `ledger.jsonl` |

`data/**` is gitignored; only `.gitkeep` files are tracked. Ignore leftover v1 `wav/cleaned.jsonl` if it is still on disk.

## Cleanup / formatting

Format windows (~1000 words) are rewritten for spoken English, then merged into a chapter script. Speak packing uses a phoneme budget (target 160, cap 400) so Kokoro does not waterfall-split mid-sentence.

Deterministic rules (also in the LLM prompt):

- Dates such as `03/09/2026` become `the third of September, twenty twenty-six` (29 February only in leap years)
- `i.e.` / `e.i.` become `in other words`; `e.g.` becomes `for example`
- References / bibliography / works-cited sections are dropped
- Inline citations such as `Mark Fisher (2012). Title in Book, Publisher, p. 342.` become `Wrote Mark Fisher in twenty twelve.`
- Tables and figures become a short pointer: ebook *See the table Title in this chapter of the ebook.*; HTML/URL *…on the original page.*
- Section marks `§0.21` become `section 0.21`; title lists like `(Cyberpunk, Elysium)` become `for example Cyberpunk, Elysium`
- `#Accelerate` drops the hash; `&` → `and`; `35%` → `35 percent`

Format chapter scripts are written as `format/chapters/NNNN_<slug>.txt` so directory order matches narration order.

GPU default is sequential: unload Qwen before Kokoro. `pipeline.concurrent_models` is ignored.

## Adding a format

1. Implement `SourceReader` in `src/text2audiobook/formats/your_format.py` (see `io.py` for the protocol).
2. Register it in `formats/__init__.py`.
