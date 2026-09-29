# text2audiobook (production)

Fire-and-forget CLI for converting text sources (EPUB, PDF, Markdown, HTML, URL) to M4B audiobooks.

Tool root: `src/tools/text2audiobook/`

## Quick start

```bash
uv sync --group text-audiobook
text2audiobook
# or
text2audiobook --url https://retrochronic.com
```

Drop `.epub`, `.pdf`, `.md`, `.html`, or `.url` files into `data/input/`. A `.url` file is a single http(s) URL on the first line (optional title on line 2). Fetched pages are split on `h1`/`h2` headings after stripping site chrome.

## Resilience (OOM + offline hub)

- **Speak WAV resume:** completed chunk WAVs under `data/staging/<slug>/speak/` are kept; re-runs skip them when fingerprints match.
- **In-batch CUDA OOM:** TTS reloads the model to defrag VRAM, then retries with half-split batches.
- **Book-level retry:** after a book still fails with CUDA OOM or a Hugging Face connection error, the pipeline clears the GPU and re-enters the same book (default `pipeline.book_retries: 3`). Earlier stages reuse current stems; speak continues from existing WAVs.
- **Local-first model load:** LLM/TTS resolve through the HF cache (`snapshot_download(..., local_files_only=True)` first) so mid-run reloads do not need the network. Set `pipeline.hub_offline: true` to never contact the hub (requires a warm cache or a local `model_id` path).

```json
"pipeline": {
  "book_retries": 3,
  "hub_prefer_local": true,
  "hub_offline": false
}
```

## Base voice-clone artifacts

Qwen3-TTS Base ICL (`x_vector_only: false`) can prepend a short “and”/“eNd” syllable at chunk onsets (chat-template `<|im_end|>` / ref-tail bleed). Mitigations:

- Speak text is whitespace-normalized (newlines → spaces) before synthesis.
- Default is `tts.x_vector_only: true` (speaker embedding only). Use CLI `--icl` when you want full ICL ref_text conditioning; `--x-vector-only` forces the safe default.
