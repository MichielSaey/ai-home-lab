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
