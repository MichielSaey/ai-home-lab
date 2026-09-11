# text2audiobook

v2 fire-and-forget CLI: extract → clean → format → speak, then an M4B audiobook.

```
src/tools/text2audiobook/
├── src/text2audiobook/   # Python package
├── config.json           # default config for undefined books
├── config.books/         # optional per-book overlays (`<slug>.json`)
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

`text2audiobook` loads `config.json` in the tool directory by default. Paths in the config are relative to that folder. For each book slug, if `config.books/<slug>.json` exists it is deep-merged on top of the base (book wins; `paths` stay on the base).

### Stages

A full run is the default. Re-run a layer without repeating the others:

```bash
text2audiobook --stage extract
text2audiobook --clean
text2audiobook --stage clean
text2audiobook --stage format
text2audiobook --stage speak
text2audiobook --stage speak --voice bf_emma
text2audiobook --force
text2audiobook --footnote-cues
text2audiobook --no-footnote-cues
```

`--clean` is an alias for `--stage clean` (clean-only). `--stage speak` loads Kokoro only (no Qwen). `--force` invalidates skip for the requested stages, and on extract also refetches cached `.url` HTML. There is no v1 migrator: delete `data/staging/<book_slug>/` to rebuild.

Spoken `Footnote.` / `End of footnote.` cues are **off** by default (`output.speak_footnote_cues`). Enable per book in `config.books/<slug>.json` or with `--footnote-cues`.

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
| `clean/` | Deterministic sections (`sections.jsonl`: body/footnote in reading order) + clean manifest |
| `format/` | LLM windows (`chunks.jsonl`), joined chapter scripts, format manifest |
| `speak/` | Phoneme units, WAVs, speak manifest (voice, speed, bitrate, loudnorm, silences) |
| `data/staging/_url_cache/` | Fetched HTML cache (keyed by URL hash) |
| `data/output/<book_slug>.m4b` | Finished audiobooks |
| `data/runs/` | Run manifests, logs, `ledger.jsonl` |

`data/**` is gitignored; only `.gitkeep` files are tracked. Ignore leftover v1 `wav/cleaned.jsonl` if it is still on disk.

## Cleanup / formatting

Each stage starts from the previous stem’s units and **further-splits only when over budget** (never rematches body+footnote into one chapter blob then re-chunks).

**Clean** (after extract) splits each chapter into ordered sections and applies deterministic scrubbing—no LLM. Inspect `clean/sections.jsonl` before formatting:

1. Split on footnote callouts at unit boundaries (sentence end or newline before a new capital unit)
2. Drop citation-only notes; keep discursive notes as `kind=footnote` sections (optional spoken cues)
3. Scrub URLs, inline citations, dates, abbreviations, tables/figures, and other print conventions

**Format** further-splits clean sections by word budget (~1000), rewrites each window for spoken English (optional LLM), then joins windows per chapter for inspection/M4B titles. **Speak** further-splits those format windows by phoneme budget (target 160, cap 400).

Deterministic rules (also in the LLM prompt):

- Dates such as `03/09/2026` become `the third of September, twenty twenty-six` (29 February only in leap years)
- `i.e.` / `e.i.` become `in other words`; `e.g.` becomes `for example`
- References / bibliography / works-cited sections are dropped
- Citation-only endnotes are dropped; discursive footnotes are sections after their callout sentence
- Inline citations such as `Mark Fisher (2012). Title in Book, Publisher, p. 342.` become `Wrote Mark Fisher in twenty twelve.`
- Tables and figures become a short pointer: ebook *See the table Title in this chapter of the ebook.*; HTML/URL *…on the original page.*
- Section marks `§0.21` become `section 0.21`; title lists like `(Cyberpunk, Elysium)` become `for example Cyberpunk, Elysium`
- `#Accelerate` drops the hash; `&` → `and`; `35%` → `35 percent`
- URLs are removed

Format chapter scripts are written as `format/chapters/NNNN_<slug>.txt` so directory order matches narration order.

GPU default is sequential: unload Qwen before Kokoro. `pipeline.concurrent_models` is ignored.

## Adding a format

1. Implement `SourceReader` in `src/text2audiobook/formats/your_format.py` (see `io.py` for the protocol).
2. Register it in `formats/__init__.py`.
