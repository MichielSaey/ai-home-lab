# text2audiobook (production)

Fire-and-forget CLI for converting text sources (EPUB, Markdown, HTML, URL) to M4B audiobooks.

Primary documentation: [src/tools/text2audiobook/README.md](../src/tools/text2audiobook/README.md)

## Quick start

```bash
uv sync --group text-audiobook
text2audiobook
# or
text2audiobook --url https://retrochronic.com
```

Tool root: `src/tools/text2audiobook/`

Drop `.epub`, `.md`, `.html`, or `.url` files into `data/input/`. A `.url` file is a single http(s) URL on the first line (optional title on line 2). Fetched pages are split on `h1`/`h2` headings after stripping site chrome.

## Base voice-clone artifacts

Qwen3-TTS Base ICL (`x_vector_only: false`) can prepend a short “and”/“eNd” syllable at chunk onsets (chat-template `<|im_end|>` / ref-tail bleed). Mitigations:

- Speak text is whitespace-normalized (newlines → spaces) before synthesis.
- Default is `tts.x_vector_only: true` (speaker embedding only). Use CLI `--icl` when you want full ICL ref_text conditioning; `--x-vector-only` forces the safe default.
