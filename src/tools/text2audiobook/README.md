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
text2audiobook --extract
text2audiobook --clean
text2audiobook --format
text2audiobook --speak
text2audiobook --format --speak
text2audiobook --speak --voice Aiden
text2audiobook --force
text2audiobook --footnote-cues
text2audiobook --no-footnote-cues
```

Stage flags are combinable (`--format --speak`). With none set, all four stages run. `--speak` alone loads Qwen3-TTS only (no LLM). `--force` invalidates skip for the requested stages, and on extract also refetches cached `.url` HTML. There is no v1 migrator: delete `data/staging/<book_slug>/` to rebuild.

Spoken `Footnote.` / `End of footnote.` cues are **off** by default (`output.speak_footnote_cues`). Enable per book in `config.books/<slug>.json` or with `--footnote-cues`.

### Voices

```bash
text2audiobook --list-voices
text2audiobook --voice Serena
text2audiobook --voice Aiden
text2audiobook --voice random
```

**Shipped default is Base 0.6B voice clone** (`Qwen/Qwen3-TTS-12Hz-0.6B-Base`) with `voice: cloned`, `tts.ref_audio` (reference WAV), and `tts.ref_text` (exact transcript of that clip). The Base model does **not** support `instruct` style control; keep `tts.instruct` / direction for CustomVoice 1.7B or VoiceDesign if you switch.

For a fixed catalog speaker instead, set `tts.model_id` to `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` and `voice` to e.g. `Serena` (faster; no instruct on 0.6B). Serena/Vivian are Chinese-native; Mandarin accent can slip on English. English-native CustomVoice speakers are male only (`Ryan`, `Aiden`). For a designed native-English female persona without a reference clip, set `tts.model_id` to `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` and `voice` to `designed` (slower). `--voice random` picks from the nine CustomVoice speakers without replacement until the pool wraps.

`tts.lang` is the book/content language (default `English`). When the active model supports instruct, global `tts.instruct` is composed with optional per-chunk direction (base + direction). CustomVoice has no `speed` knob. Base cloning uses `tts.x_vector_only` (default `false`; ICL mode needs `ref_text`).

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
| `speak/` | Character-budget units, WAVs, speak manifest (model_id, voice, lang, instruct, bitrate, loudnorm, silences) |
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

**Format** further-splits clean sections by word budget (~1000), then optionally runs **two LLM passes** while the model is still loaded: (1) cleanup rewrites each window for spoken English; (2) direction writes a short Qwen3-TTS `instruct` string per window (passage-level pace/emotion/emphasis only — **not** bracket tags like `[excited]` inside the narration text, and **not** a new accent/persona). Direction can run even when cleanup is off (`llm.direction`). Per-chunk `instruct` is stored in `format/chunks.jsonl` and inherited by speak units; speak **composes** global `tts.instruct` + chunk direction (never replaces the baseline). Joined chapter scripts are written for inspection/M4B titles. The default LLM cleanup prompt (and a deterministic post-pass) shrink bibliographic dumps to a short author/work credit, drop page numbers / publishers / stacked “see also” lists, and remove `[...]` ellipses. **Speak** further-splits those format windows by character budget (target 800, cap 1200) for Qwen3-TTS (0.6B Base voice clone by default), then packs consecutive speak units into GPU batches up to `tts.batch_max_chars` / `tts.batch_max_items` (still one WAV per unit).

After changing TTS model/voice/instruct, re-run `--speak` so the speak stem picks up the new fingerprint. Speak reuses existing format files even when the format fingerprint is stale (for example after a direction prompt hash change); re-run `--format` only when you want regenerated format text.

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

GPU default is sequential: unload the Qwen LLM before Qwen3-TTS loads. `pipeline.concurrent_models` is ignored. Dependencies: `qwen-tts` requires `transformers==4.57.3` (and `accelerate==1.12.0`), so the text-audiobook group pins those instead of transformers 5.x.

## Adding a format

1. Implement `SourceReader` in `src/text2audiobook/formats/your_format.py` (see `io.py` for the protocol).
2. Register it in `formats/__init__.py`.
