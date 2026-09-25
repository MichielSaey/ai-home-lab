"""Structured documents: paragraphs linked to footnotes, before any speech rewrite.

Extractors produce :class:`Block` lists. The clean stage scrubs them. The format
stage receives a paragraph together with the notes that hang from it.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import unquote

from bs4 import BeautifulSoup, NavigableString, Tag

from text2audiobook.formatting import (
    _SEE_NOTE_NUM_RE,
    _extract_notes_apparatus,
    _note_numbers_from_spec,
    is_citation_only_note,
    strip_reference_sections,
)
from text2audiobook.io import Block

_MARKER_RE = re.compile(r"^\d{1,3}[a-z]?$")
_CALLOUT_LINE_RE = re.compile(r"^\d{1,3}[a-z]?$")
_SECTION_HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")
_NOTES_HEADING_TEXT_RE = re.compile(r"^(?:notes|footnotes|endnotes)\s*[:.]?$", re.IGNORECASE)
_QXD_RE = re.compile(r"\.qxd\b", re.IGNORECASE)
_PAGE_WORD_RE = re.compile(r"^page\s+\d{1,4}$", re.IGNORECASE)
_TRAILING_PAGE_RE = re.compile(r"^(?P<body>.+?)\s+(?P<page>\d{1,4})$")
_GLUED_MARKER_RE = re.compile(
    r"(?P<word>[A-Za-z][A-Za-z'’-]{2,})(?P<q>['’\"”]?)"
    r"(?P<num>\d{1,2})(?!\d)(?!\.\d)"
)
_LEADING_MARKER_RE = re.compile(r"^\d{1,3}[a-z]?(?:\s*[.)])?\s+")

_BLOCK_TAGS = {
    "p",
    "div",
    "li",
    "aside",
    "blockquote",
    "section",
    "article",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "figcaption",
    "pre",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WALK_TAGS = _BLOCK_TAGS | {"ul", "ol", "body", "td", "th"}

_CALLOUT_CLASS_RE = re.compile(
    r"fn[_-]?ref|noteref|class_su1|(?:^|[^a-z])su1(?:[^a-z]|$)",
    re.IGNORECASE,
)
_NOTE_CLASS_RE = re.compile(
    r"footnote|endnote|_idfootnote",
    re.IGNORECASE,
)


def _tag_name(tag: Tag) -> str:
    name = tag.name or ""
    if "}" in name:
        name = name.rsplit("}", 1)[-1]
    return name.lower()


def _class_text(tag: Tag) -> str:
    raw = tag.get("class")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return " ".join(str(item) for item in raw)


def _fragment(href: str) -> str:
    if "#" not in href:
        return ""
    return unquote(href.split("#", 1)[1]).strip()


def _marker_text(tag: Tag) -> str | None:
    text = re.sub(r"\s+", "", tag.get_text())
    if _MARKER_RE.match(text):
        return text
    return None


def _nearest_block(tag: Tag) -> Tag | None:
    if _tag_name(tag) in _BLOCK_TAGS:
        return tag
    for parent in tag.parents:
        if isinstance(parent, Tag) and _tag_name(parent) in _BLOCK_TAGS:
            return parent
    return None


def _in_notes_region(tag: Tag) -> bool:
    for previous in tag.find_all_previous(_HEADING_TAGS):
        heading = re.sub(r"\s+", " ", previous.get_text(" ", strip=True))
        if _NOTES_HEADING_TEXT_RE.match(heading):
            return True
        if _tag_name(previous) in {"h1", "h2"}:
            return False
    return False


def _is_callout_anchor(anchor: Tag, target_block: Tag) -> bool:
    if any(_tag_name(parent) == "sup" for parent in anchor.parents):
        return True
    if _CALLOUT_CLASS_RE.search(_class_text(anchor)):
        return True
    if _NOTE_CLASS_RE.search(_class_text(target_block)):
        return True
    return _in_notes_region(target_block)


def _soup(content: bytes | str) -> BeautifulSoup:
    try:
        return BeautifulSoup(content, features="xml")
    except Exception:
        return BeautifulSoup(content, "lxml")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _inline_text(node: Tag, callout_ids: set[int], found: list[str], callout_frag: dict[int, str]) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        if id(child) in callout_ids:
            frag = callout_frag[id(child)]
            if frag not in found:
                found.append(frag)
            continue
        name = _tag_name(child)
        if name in {"script", "style"}:
            continue
        if name == "br":
            parts.append(" ")
            continue
        parts.append(_inline_text(child, callout_ids, found, callout_frag))
    return _collapse("".join(parts))


def _strip_leading_marker(text: str) -> str:
    return _LEADING_MARKER_RE.sub("", text, count=1).strip()


def parse_html_blocks(content: bytes | str) -> list[Block]:
    """Read an EPUB or HTML chapter into paragraphs linked to footnote bodies."""
    soup = _soup(content)
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for span in list(soup.find_all("span")):
        if re.fullmatch(r"page_\d+", str(span.get("id") or "")):
            span.unwrap()

    id_map: dict[str, Tag] = {}
    for tag in soup.find_all(True):
        raw_id = tag.get("id")
        if raw_id:
            id_map.setdefault(str(raw_id), tag)

    callout_frag: dict[int, str] = {}
    note_by_frag: dict[str, tuple[Tag, str]] = {}
    for anchor in soup.find_all("a"):
        marker = _marker_text(anchor)
        frag = _fragment(str(anchor.get("href") or ""))
        if marker is None or not frag or frag not in id_map:
            continue
        target = id_map[frag]
        target_block = target if _tag_name(target) in _BLOCK_TAGS else _nearest_block(target)
        source_block = _nearest_block(anchor)
        if target_block is None or source_block is None or target_block is source_block:
            continue
        if _tag_name(target_block) in _HEADING_TAGS:
            continue
        if not _is_callout_anchor(anchor, target_block):
            continue
        callout_frag[id(anchor)] = frag
        note_by_frag.setdefault(frag, (target_block, marker))

    callout_ids = set(callout_frag)
    note_block_ids = {id(block) for block, _marker in note_by_frag.values()}
    emitted: set[str] = set()
    blocks: list[Block] = []
    counter = 0

    def add_notes(parent_id: str, frags: list[str]) -> None:
        for frag in frags:
            if frag in emitted or frag not in note_by_frag:
                continue
            container, marker = note_by_frag[frag]
            text = _strip_leading_marker(
                _inline_text(container, callout_ids, [], callout_frag)
            )
            if not text:
                continue
            emitted.add(frag)
            blocks.append(
                Block(
                    id=f"fn:{frag}",
                    kind="footnote",
                    text=text,
                    note_number=marker,
                    parent_id=parent_id,
                    bibliographic_hint=is_citation_only_note(text),
                )
            )

    def emit_leaf(tag: Tag) -> None:
        nonlocal counter
        name = _tag_name(tag)
        refs: list[str] = []
        text = _inline_text(tag, callout_ids, refs, callout_frag)
        if name == "table":
            caption_tag = tag.find("caption")
            caption = _collapse(caption_tag.get_text(" ", strip=True)) if caption_tag else ""
            counter += 1
            blocks.append(
                Block(
                    id=f"t{counter}",
                    kind="table",
                    text=caption or "See the table in this chapter of the ebook.",
                )
            )
            return
        if name == "figure":
            caption_tag = tag.find("figcaption")
            image = tag.find("img")
            alt = ""
            if image is not None:
                alt = _collapse(str(image.get("alt") or ""))
            caption = _collapse(caption_tag.get_text(" ", strip=True)) if caption_tag else alt
            counter += 1
            blocks.append(
                Block(
                    id=f"f{counter}",
                    kind="figure",
                    text=caption or "See the figure in this chapter of the ebook.",
                )
            )
            return
        if not text and not refs:
            return
        if name in _HEADING_TAGS and _NOTES_HEADING_TEXT_RE.match(text):
            return
        counter += 1
        if name in _HEADING_TAGS:
            kind = "heading"
        elif name == "li":
            kind = "list_item"
        else:
            kind = "paragraph"
        block_id = f"b{counter}"
        note_ids = [f"fn:{frag}" for frag in refs if frag in note_by_frag]
        blocks.append(Block(id=block_id, kind=kind, text=text, note_refs=note_ids))
        add_notes(block_id, refs)

    def walk(node: Tag) -> None:
        for child in list(node.children):
            if not isinstance(child, Tag):
                continue
            if id(child) in note_block_ids:
                continue
            name = _tag_name(child)
            if name in {"script", "style"}:
                continue
            if name in {"table", "figure"} or name in {"p", "li", "pre", "figcaption"} | _HEADING_TAGS:
                emit_leaf(child)
                continue
            if name in _WALK_TAGS or name == "div":
                nested = child.find(["p", "li", "table", "figure", "h1", "h2", "h3", "h4", "h5", "h6"])
                if nested is None:
                    emit_leaf(child)
                else:
                    walk(child)
                continue
            walk(child)

    root = soup.body or soup
    walk(root)

    for frag, (container, marker) in note_by_frag.items():
        if frag in emitted:
            continue
        text = _strip_leading_marker(_inline_text(container, callout_ids, [], callout_frag))
        if not text:
            continue
        blocks.append(
            Block(
                id=f"fn:{frag}",
                kind="footnote",
                text=text,
                note_number=marker,
                bibliographic_hint=is_citation_only_note(text),
            )
        )
    return blocks


def render_blocks(blocks: list[Block]) -> str:
    """Plain text for inspection. Footnotes stay in a Notes section, still linked in ``blocks``."""
    body: list[str] = []
    notes: list[str] = []
    for block in blocks:
        if block.kind == "footnote":
            number = block.note_number or ""
            notes.append(f"{number}\n. {block.text}".strip() if number else block.text)
            continue
        if block.text.strip():
            body.append(block.text.strip())
    text = "\n\n".join(body)
    if notes:
        text = f"{text}\n\nNotes\n" + "\n".join(notes) if text else "Notes\n" + "\n".join(notes)
    return text.strip()


def strip_pdf_furniture(pages: list[str]) -> list[str]:
    """Drop printer slugs, ``Page N`` lines, and repeated running headers.

    A running header is a short, period-free line that ends in a page number and
    whose title stem shows up on more than one page. ``Chapter 1`` is kept:
    its stem is a single word. ``1.1 Section title`` is not a trailing page number.
    """
    stems: Counter[str] = Counter()
    parsed: list[list[str]] = []
    for page in pages:
        lines = page.splitlines()
        parsed.append(lines)
        for line in lines:
            stripped = line.strip()
            if not stripped or _QXD_RE.search(stripped) or _SECTION_HEADING_RE.match(stripped):
                continue
            match = _TRAILING_PAGE_RE.match(stripped)
            if match is None:
                continue
            body = match.group("body").strip()
            if "." in body or len(body.split()) < 3 or len(body) > 80:
                continue
            stems[body.casefold()] += 1
    repeated = {stem for stem, count in stems.items() if count >= 2}

    cleaned: list[str] = []
    for lines in parsed:
        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                kept.append(line)
                continue
            if _QXD_RE.search(stripped) or _PAGE_WORD_RE.match(stripped):
                continue
            match = _TRAILING_PAGE_RE.match(stripped)
            if (
                match is not None
                and match.group("body").strip().casefold() in repeated
            ):
                continue
            kept.append(line)
        cleaned.append("\n".join(kept))
    return cleaned


def _detach_glued_markers(text: str, note_numbers: set[str]) -> str:
    if not note_numbers:
        return text

    def repl(match: re.Match[str]) -> str:
        number = match.group("num")
        if number not in note_numbers:
            return match.group(0)
        word = match.group("word") + (match.group("q") or "")
        return f"{word}\n{number}\n"

    lines: list[str] = []
    for line in text.splitlines():
        if _SECTION_HEADING_RE.match(line.strip()):
            lines.append(line)
            continue
        lines.append(_GLUED_MARKER_RE.sub(repl, line))
    return "\n".join(lines)


def _pull_see_notes(text: str) -> tuple[str, list[str]]:
    numbers: list[str] = []

    def repl(match: re.Match[str]) -> str:
        numbers.extend(_note_numbers_from_spec(match.group("nums")))
        return ""

    cleaned = _SEE_NOTE_NUM_RE.sub(repl, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip(), numbers


def parse_plain_document(text: str) -> list[Block]:
    """Recover paragraphs and notes from already-flattened text.

    Lone digit lines are callouts. ``1.1 Title`` stays a heading. A callout
    followed by a lowercase line stays inside the paragraph; otherwise it ends
    the paragraph. Bibliographic notes are kept and only hinted.
    """
    text = strip_reference_sections(text)
    _body, preamble, entries = _extract_notes_apparatus(text)
    body = _detach_glued_markers(_body, set(entries))

    groups: list[tuple[str, str, list[str]]] = []
    current: list[str] = []
    current_notes: list[str] = []

    def flush() -> None:
        nonlocal current, current_notes
        joined = _collapse(" ".join(part.strip() for part in current if part.strip()))
        see_text, see_nums = _pull_see_notes(joined) if joined else ("", [])
        notes = current_notes + [num for num in see_nums if num not in current_notes]
        current = []
        current_notes = []
        if see_text or notes:
            groups.append(("paragraph", see_text, notes))

    lines = body.splitlines()

    def next_content(start: int) -> str:
        for later in lines[start + 1 :]:
            stripped = later.strip()
            if stripped and not _CALLOUT_LINE_RE.match(stripped):
                return stripped
        return ""

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if _CALLOUT_LINE_RE.match(stripped):
            current_notes.append(stripped)
            nxt = next_content(index)
            if not nxt or not nxt[:1].islower():
                flush()
            continue
        if _SECTION_HEADING_RE.match(stripped):
            flush()
            groups.append(("heading", stripped, []))
            continue
        current.append(stripped)
    flush()

    blocks: list[Block] = []
    used: set[str] = set()
    counter = 0

    def footnote_block(number: str, parent_id: str | None) -> Block | None:
        note = entries.get(number)
        if note is None or number in used:
            return None
        used.add(number)
        note_text = note.strip()
        if not note_text:
            return None
        return Block(
            id=f"fn:{number}",
            kind="footnote",
            text=note_text,
            note_number=number,
            parent_id=parent_id,
            bibliographic_hint=is_citation_only_note(note_text),
        )

    for kind, paragraph, numbers in groups:
        counter += 1
        block_id = f"b{counter}"
        refs = [f"fn:{number}" for number in numbers if number in entries and number not in used]
        blocks.append(
            Block(
                id=block_id,
                kind=kind,
                text=paragraph,
                note_refs=refs,
            )
        )
        for number in numbers:
            note = footnote_block(number, block_id)
            if note is not None:
                blocks.append(note)

    if preamble and preamble.strip():
        counter += 1
        blocks.append(
            Block(id=f"b{counter}", kind="paragraph", text=_collapse(preamble))
        )

    for number in sorted(entries, key=lambda value: int(re.sub(r"\D", "", value) or 0)):
        note = footnote_block(number, None)
        if note is not None:
            blocks.append(note)
    return blocks
