"""Deterministic TTS-oriented rewriting for the cleanup / formatting step."""

from __future__ import annotations

import calendar
import re
from dataclasses import replace

from text2audiobook.io import Chapter

FORMATTER_VERSION = "6"

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)

_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)

_ORDINALS_UNDER_20 = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
}

_ORDINAL_TENS = {
    20: "twentieth",
    30: "thirtieth",
}

_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# Standalone bibliography / works-cited headings (chapter title or in-body).
_REFERENCES_HEADING_RE = re.compile(
    r"""
    ^
    (?:\#{1,6}\s+)?
    [\*"'_]*
    (
        references?
        | bibliography
        | works\s+cited
        | works\s+consulted
        | literature\s+cited
        | notes\s+and\s+references
        | notes\s+and\s+bibliography
        | endnotes
        | citations
        | further\s+reading
        | sources
    )
    [\*"'_]*
    \s*[:.]?
    \s*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DATE_RE = re.compile(
    r"(?<![\w/])(?P<day>\d{1,2})(?P<sep>[./-])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{4})(?![\d/])"
)

_AUTHOR = (
    r"(?:[A-Z][A-Za-z'.-]+(?:\s+(?:van|von|de|der|da|di|del|bin|al|[A-Z][A-Za-z'.-]+))+)"
    r"(?:\s+et\s+al\.)?"
)

# Bibliographic inline cite: Author (Year). Title…, p. 342.
# Body cannot cross a sentence period, so narrative like
# "Name (2012). He later appeared in The Guardian." is left alone.
_FULL_CITE_PAGES_RE = re.compile(
    rf"(?P<author>{_AUTHOR})\s+\((?P<year>(?:18|19|20)\d{{2}})\)\.\s+"
    rf"(?P<body>[^.\n]{{8,240}}?)"
    rf"[Pp]p?\.\s*\d+[a-z]?(?:\s*[-–—]\s*\d+[a-z]?)?\.?"
)

_PAREN_CITE_RE = re.compile(
    rf"\s*\("
    rf"(?P<author>{_AUTHOR}|[A-Z][A-Za-z'.-]+(?:\s+et\s+al\.?)?)"
    rf",?\s+(?P<year>(?:18|19|20)\d{{2}})[a-z]?"
    rf",\s*[Pp]p?\.\s*\d+[a-z]?(?:\s*[-–—]\s*\d+[a-z]?)?"
    rf"\)"
)

_NUMERIC_REF_RE = re.compile(r"\s*\[\d+(?:\s*[-–,;]\s*\d+)*\]")

# Mid-body footnote callouts broken onto their own line (Urbanomic EPUB style).
_FOOTNOTE_CALLOUT_LINE_RE = re.compile(r"(?m)^\d{1,3}\s*$")
_SEE_NOTE_RE = re.compile(
    r"\[?\s*see\s+notes?\s+\d+[a-z]?(?:\s*[-–,]\s*\d+[a-z]?)?\s*\]?",
    re.IGNORECASE,
)

# Chapter-end note apparatus we keep for discursive content, but scrub cites from.
_NOTES_APPARATUS_HEADING_RE = re.compile(
    r"""
    ^
    (?:\#{1,6}\s+)?
    [\*"'_]*
    (?:notes|footnotes)
    [\*"'_]*
    \s*[:.]?
    \s*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ENDNOTE_ENTRY_START_RE = re.compile(r"(?m)^(?P<num>\d{1,3})\s*(?:\n\.\s*|\.\s+)")
_PAGE_CITE_RE = re.compile(
    r"(?:,\s*\d+[a-z]?(?:\s*[-–—]\s*\d+[a-z]?)?\s*\.?$|\bpp?\.\s*\d+)",
    re.IGNORECASE | re.MULTILINE,
)
_PUBLISHER_CITE_RE = re.compile(
    r"\([^)]*(?:Press|University|Verlag|Macmillan|Urbanomic|Publisher|Editionen|Madra|Tuttle)",
    re.IGNORECASE,
)
_URL_CITE_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_SEE_WORK_RE = re.compile(r"^See\s+[A-Z]", re.MULTILINE)
_AUTHOR_START_RE = re.compile(
    r"^(?:[A-Z]\.\s*)+[A-Z][A-Za-z'’.-]+|^[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+)?,",
)

# Spoken cue when a discursive endnote is inlined after its callout.
FOOTNOTE_SPOKEN_MARKER = "Footnote."
_SEE_NOTE_NUM_RE = re.compile(
    r"\[?\(?\s*see\s+notes?\s+(?P<nums>\d+[a-z]?(?:\s*[-–,;—]\s*\d+[a-z]?)*)"
    r"(?:\s+below)?\s*\)?\]?",
    re.IGNORECASE,
)

_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\be\.i\.(?=\s|,|:|;|\)|$)", re.IGNORECASE), "in other words"),
    (re.compile(r"\bi\.e\.(?=\s|,|:|;|\)|$)", re.IGNORECASE), "in other words"),
    (re.compile(r"\be\.g\.(?=\s|,|:|;|\)|$)", re.IGNORECASE), "for example"),
)

# §0.21 / §3.741 → "section 0.21" so Kokoro does not say "section sign".
_SECTION_MARK_RE = re.compile(r"§\s*(?P<label>[0-9]+(?:\.[0-9]+)*)")

# Title-like media lists in parentheses, rewritten only with a nearby cue
# (e.g. / for example / tandem / films) so (Marx, Engels) stays intact.
_TITLE_TOKEN = r"[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)*"
_EXAMPLE_PAREN_LIST_RE = re.compile(
    rf"\(\s*(?P<body>{_TITLE_TOKEN}(?:\s*,\s*{_TITLE_TOKEN})+)\s*\)"
)
_EXAMPLE_LEAD_RE = re.compile(
    r"(?:for example|such as)\s+$",
    re.IGNORECASE,
)
_EXAMPLE_SOFT_CUE_RE = re.compile(
    r"\btandem\s+$",
    re.IGNORECASE,
)

_HASHTAG_RE = re.compile(r"#(?P<tag>[A-Za-z][\w-]*)")
_AMPERSAND_RE = re.compile(r"\s&\s")
_PERCENT_RE = re.compile(r"(?P<num>\d+)\s*%")

_RESUME_AFTER_REFERENCES_RE = re.compile(
    r"""
    ^
    (?:\#{1,6}\s+)?
    (
        appendi(?:x|ces)(?:\s+[A-Z0-9]+)?
        | acknowledge?ments?
        | about\s+the\s+author
        | conclusion
        | afterword
        | epilogue
        | glossary
        | index
    )
    \s*[:.]?
    \s*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)

_CITE_SUBJECT_PRONOUNS = frozenset(
    {"he", "she", "they", "it", "we", "i", "this", "that", "his", "her", "their"}
)

_WHITESPACE_RE = re.compile(r"[ \t]{2,}")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _two_digit_words(value: int, *, hyphen: bool = True) -> str:
    if value < 20:
        return _ONES[value]
    tens, ones = divmod(value, 10)
    if ones == 0:
        return _TENS[tens]
    joiner = "-" if hyphen else " "
    return f"{_TENS[tens]}{joiner}{_ONES[ones]}"


def day_to_ordinal_words(day: int) -> str:
    if day in _ORDINALS_UNDER_20:
        return _ORDINALS_UNDER_20[day]
    if day in _ORDINAL_TENS:
        return _ORDINAL_TENS[day]
    tens, ones = divmod(day, 10)
    return f"{_TENS[tens]}-{_ORDINALS_UNDER_20[ones]}"


def year_to_words(year: int) -> str:
    """Spell a calendar year the way a narrator would say it."""
    if year == 2000:
        return "two thousand"
    if 2001 <= year <= 2009:
        return f"two thousand {_ONES[year - 2000]}"
    if 2010 <= year <= 2099:
        return f"twenty {_two_digit_words(year - 2000)}"

    century, rest = divmod(year, 100)
    if century < 20:
        century_words = _ONES[century]
    else:
        century_words = _two_digit_words(century)

    if rest == 0:
        return f"{century_words} hundred"
    if rest < 10:
        return f"{century_words} oh {_ONES[rest]}"
    return f"{century_words} {_two_digit_words(rest)}"


def is_references_heading(title: str) -> bool:
    cleaned = title.strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    cleaned = cleaned.strip("*_\"'")
    return bool(_REFERENCES_HEADING_RE.match(cleaned))


def _heading_text(line: str) -> str:
    cleaned = re.sub(r"^#{1,6}\s+", "", line.strip())
    return cleaned.strip("*_\"'")


def _is_resume_heading(line: str) -> bool:
    """True for a later section heading after a references block (markdown or plain)."""
    heading = _heading_text(line)
    if not heading or is_references_heading(heading):
        return False
    return bool(_RESUME_AFTER_REFERENCES_RE.match(heading))


def strip_reference_sections(text: str) -> str:
    """Drop bibliography / works-cited blocks, typically trailing sections."""
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        heading = _heading_text(line)
        if is_references_heading(heading):
            skipping = True
            continue
        if skipping:
            if _is_resume_heading(line):
                skipping = False
                kept.append(line)
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _days_in_month(month: int, year: int) -> int:
    if month == 2:
        return 29 if calendar.isleap(year) else 28
    return _DAYS_IN_MONTH[month - 1]


def _replace_date(match: re.Match[str]) -> str:
    day = int(match.group("day"))
    month = int(match.group("month"))
    year = int(match.group("year"))
    if not 1 <= month <= 12:
        return match.group(0)
    if year < 1000:
        return match.group(0)
    if not 1 <= day <= _days_in_month(month, year):
        return match.group(0)
    spoken = (
        f"the {day_to_ordinal_words(day)} of {_MONTHS[month - 1]}, {year_to_words(year)}"
    )
    return spoken


def expand_dates(text: str) -> str:
    return _DATE_RE.sub(_replace_date, text)


def expand_abbreviations(text: str) -> str:
    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    return text


def expand_section_marks(text: str) -> str:
    """Speak section marks: §0.21 → section 0.21."""
    return _SECTION_MARK_RE.sub(lambda match: f"section {match.group('label')}", text)


def expand_example_parentheticals(text: str) -> str:
    """Rewrite cued title lists in parentheses as spoken examples.

    Only matches comma-separated Title Case tokens. Requires an immediate
    lead cue (``for example`` / ``such as``) or ``tandem`` right before the
    parenthesis, so author lists like ``(Marx, Engels)`` stay intact.
    """
    pieces: list[str] = []
    cursor = 0
    for match in _EXAMPLE_PAREN_LIST_RE.finditer(text):
        start, end = match.span()
        prefix = text[max(0, start - 24) : start]
        lead = _EXAMPLE_LEAD_RE.search(prefix)
        soft = _EXAMPLE_SOFT_CUE_RE.search(prefix)
        if not lead and not soft:
            continue
        body = match.group("body").strip()
        consume_from = lead.start() + max(0, start - 24) if lead else start
        pieces.append(text[cursor:consume_from])
        pieces.append(f"for example {body}")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def expand_symbols(text: str) -> str:
    """Strip hashtags and speak & / % in running text."""
    text = _HASHTAG_RE.sub(lambda match: match.group("tag"), text)
    text = _AMPERSAND_RE.sub(" and ", text)
    text = _PERCENT_RE.sub(lambda match: f"{match.group('num')} percent", text)
    return text


def _replace_full_citation(match: re.Match[str]) -> str:
    body = match.group("body").strip()
    first = body.split()[0].lower().rstrip(",;:") if body.split() else ""
    if first in _CITE_SUBJECT_PRONOUNS or "," not in body:
        return match.group(0)
    author = match.group("author")
    year = year_to_words(int(match.group("year")))
    return f"Wrote {author} in {year}."


def simplify_inline_citations(text: str) -> str:
    text = _FULL_CITE_PAGES_RE.sub(_replace_full_citation, text)
    text = _PAREN_CITE_RE.sub("", text)
    text = _NUMERIC_REF_RE.sub("", text)
    return text


def strip_footnote_callouts(text: str) -> str:
    """Remove bare footnote markers and 'see note N' pointers from running text."""
    text = _FOOTNOTE_CALLOUT_LINE_RE.sub("", text)
    text = _SEE_NOTE_RE.sub("", text)
    return text


def is_citation_only_note(text: str) -> bool:
    """True when an endnote is bibliographic rather than discursive prose."""
    stripped = text.strip()
    if not stripped:
        return True
    words = stripped.split()
    if len(words) > 80:
        return False
    has_page = bool(_PAGE_CITE_RE.search(stripped))
    has_pub = bool(_PUBLISHER_CITE_RE.search(stripped))
    has_url = bool(_URL_CITE_RE.search(stripped))
    has_see = bool(_SEE_WORK_RE.search(stripped))
    has_author = bool(_AUTHOR_START_RE.match(stripped))
    score = sum((has_page, has_pub, has_url, has_see, has_author))
    if score >= 2:
        return True
    # A lone "See …" opener is not enough — short discursive asides use it too.
    if len(words) <= 25 and (has_page or has_pub or has_url):
        return True
    return False


def _prefer_note_body(existing: str, incoming: str) -> str:
    """On duplicate note numbers, keep discursive text over a citation stub."""
    existing_cite = is_citation_only_note(existing)
    incoming_cite = is_citation_only_note(incoming)
    if existing_cite and not incoming_cite:
        return incoming
    if incoming_cite and not existing_cite:
        return existing
    return incoming if len(incoming) > len(existing) else existing


def _iter_endnote_entries(notes_body: str) -> tuple[str, dict[str, str]]:
    """Split a Notes section into leading preamble plus numbered entry bodies."""
    matches = list(_ENDNOTE_ENTRY_START_RE.finditer(notes_body))
    if not matches:
        return notes_body.strip(), {}
    preamble = notes_body[: matches[0].start()].strip()
    entries: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(notes_body)
        num = match.group("num")
        body = notes_body[start:end].strip()
        if num in entries:
            entries[num] = _prefer_note_body(entries[num], body)
        else:
            entries[num] = body
    return preamble, entries


def _format_footnote_block(body: str) -> str:
    return f"{FOOTNOTE_SPOKEN_MARKER}\n{body.strip()}"


def _extract_notes_apparatus(text: str) -> tuple[str, str, dict[str, str]]:
    """Return body without Notes sections, combined preamble, and numbered entries."""
    lines = text.splitlines()
    rebuilt: list[str] = []
    preambles: list[str] = []
    entries: dict[str, str] = {}
    index = 0
    while index < len(lines):
        if not _NOTES_APPARATUS_HEADING_RE.match(_heading_text(lines[index])):
            rebuilt.append(lines[index])
            index += 1
            continue
        index += 1
        block_lines: list[str] = []
        while index < len(lines):
            heading = _heading_text(lines[index])
            if is_references_heading(heading) or _is_resume_heading(lines[index]):
                break
            if _NOTES_APPARATUS_HEADING_RE.match(heading):
                break
            block_lines.append(lines[index])
            index += 1
        preamble, block_entries = _iter_endnote_entries("\n".join(block_lines))
        if preamble:
            preambles.append(preamble)
        for num, body in block_entries.items():
            if num in entries:
                entries[num] = _prefer_note_body(entries[num], body)
            else:
                entries[num] = body
    return "\n".join(rebuilt), "\n\n".join(preambles), entries


def _consume_footnote(
    num: str,
    entries: dict[str, str],
    used: set[str],
) -> str | None:
    """Return a spoken footnote block, or None when the note is dropped/already used."""
    body = entries.get(num)
    if body is None:
        return None
    if num in used:
        return None
    used.add(num)
    if is_citation_only_note(body):
        return None
    return _format_footnote_block(body)


def _note_numbers_from_spec(nums: str) -> list[str]:
    """Expand ``1-3``, ``1–3``, or ``1, 2`` into ordered note-number strings."""
    found: list[str] = []
    for match in re.finditer(r"(\d+)(?:\s*[-–—]\s*(\d+))?", nums):
        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
        if end < start:
            start, end = end, start
        found.extend(str(value) for value in range(start, end + 1))
    return found


def _replace_see_note_pointers(
    line: str,
    entries: dict[str, str],
    used: set[str],
) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _SEE_NOTE_NUM_RE.finditer(line):
        prefix = line[cursor : match.start()]
        blocks = [
            block
            for num in _note_numbers_from_spec(match.group("nums"))
            if (block := _consume_footnote(num, entries, used))
        ]
        rest_start = match.end()
        # Keep a following sentence period with the host clause, not after the note.
        trailing_period = ""
        if rest_start < len(line) and line[rest_start] == ".":
            trailing_period = "."
            rest_start += 1
            prefix = prefix.rstrip()
        pieces.append(prefix)
        pieces.append(trailing_period)
        if blocks:
            pieces.append("\n\n" + "\n\n".join(blocks) + "\n\n")
        cursor = rest_start
    pieces.append(line[cursor:])
    return "".join(pieces)


def relocate_footnotes(text: str) -> str:
    """Move discursive endnotes after their callouts; drop citation-only notes.

    Bare markers like ``34`` and ``see note 34`` are removed. Discursive note
    bodies are inserted immediately afterward, prefixed with
    :data:`FOOTNOTE_SPOKEN_MARKER`, so later word-window chunking keeps them
    next to the claim they annotate. Unreferenced discursive notes (and any
    Notes preamble) are appended at the end.
    """
    body, preamble, entries = _extract_notes_apparatus(text)
    if not entries and not preamble:
        # Already relocated, or no Notes apparatus. Clear orphan see-note
        # pointers only — never strip lone digit lines (format windows may
        # split a footnote body away from its Footnote. cue).
        return _SEE_NOTE_NUM_RE.sub("", body)

    used: set[str] = set()
    out_lines: list[str] = []
    for line in body.splitlines():
        if _FOOTNOTE_CALLOUT_LINE_RE.match(line):
            block = _consume_footnote(line.strip(), entries, used)
            if block:
                out_lines.append("")
                out_lines.extend(block.splitlines())
                out_lines.append("")
            continue
        out_lines.append(_replace_see_note_pointers(line, entries, used))

    trailing: list[str] = []
    if preamble:
        trailing.append(preamble)
    for num in sorted(entries, key=lambda value: int(re.sub(r"\D", "", value) or 0)):
        if num in used:
            continue
        body_text = entries[num]
        if is_citation_only_note(body_text):
            continue
        trailing.append(_format_footnote_block(body_text))
    if trailing:
        out_lines.append("")
        out_lines.extend(trailing)

    return "\n".join(out_lines).strip()


def scrub_citations_for_tts(text: str) -> str:
    """Relocate discursive footnotes and drop citation-only endnotes/callouts."""
    return relocate_footnotes(text)


def _collapse_whitespace(text: str) -> str:
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


_HTML_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_HTML_IMG_RE = re.compile(
    r"<img\b[^>]*\balt\s*=\s*[\"']([^\"']*)[\"'][^>]*>",
    re.IGNORECASE,
)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_PIPE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_PIPE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def visual_reference(
    kind: str,
    *,
    title: str | None,
    chapter_title: str,
    source_kind: str,
) -> str:
    """Spoken stand-in for a table or figure that should not be read cell-by-cell."""
    noun = "figure" if kind == "figure" else "table"
    label = f"the {noun} {title.strip()}" if title and title.strip() else f"the {noun}"
    where = "on the original page" if source_kind == "page" else "in this chapter of the ebook"
    return f"See {label} {where}."


def _caption_from_pipe_row(line: str) -> str | None:
    cells = [cell.strip().strip("*_") for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell]
    if not cells:
        return None
    caption = ", ".join(cells)
    return caption if caption else None


def replace_tables_and_figures(
    text: str,
    *,
    chapter_title: str = "",
    source_kind: str = "ebook",
) -> str:
    """Replace HTML/Markdown tables and images with a short ebook/page reference."""

    def html_table(match: re.Match[str]) -> str:
        block = match.group(0)
        header = re.search(r"<th\b[^>]*>(.*?)</th>", block, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"<[^>]+>", "", header.group(1)).strip() if header else None
        return visual_reference(
            "table", title=title, chapter_title=chapter_title, source_kind=source_kind
        )

    text = _HTML_TABLE_RE.sub(html_table, text)

    def html_img(match: re.Match[str]) -> str:
        return visual_reference(
            "figure",
            title=match.group(1) or None,
            chapter_title=chapter_title,
            source_kind=source_kind,
        )

    text = _HTML_IMG_RE.sub(html_img, text)

    def md_img(match: re.Match[str]) -> str:
        return visual_reference(
            "figure",
            title=match.group(1) or None,
            chapter_title=chapter_title,
            source_kind=source_kind,
        )

    text = _MD_IMAGE_RE.sub(md_img, text)

    lines = text.splitlines()
    rebuilt: list[str] = []
    index = 0
    while index < len(lines):
        if _PIPE_ROW_RE.match(lines[index]):
            start = index
            caption = _caption_from_pipe_row(lines[index])
            index += 1
            while index < len(lines) and (
                _PIPE_ROW_RE.match(lines[index]) or _PIPE_SEP_RE.match(lines[index])
            ):
                index += 1
            if index - start >= 2:
                rebuilt.append(
                    visual_reference(
                        "table",
                        title=caption,
                        chapter_title=chapter_title,
                        source_kind=source_kind,
                    )
                )
                continue
            rebuilt.extend(lines[start:index])
            continue
        rebuilt.append(lines[index])
        index += 1
    return "\n".join(rebuilt)


def format_for_tts(
    text: str,
    *,
    chapter_title: str = "",
    source_kind: str = "ebook",
) -> str:
    """Rewrite a chunk so Kokoro hears spoken forms instead of print conventions."""
    text = strip_reference_sections(text)
    text = scrub_citations_for_tts(text)
    text = replace_tables_and_figures(
        text, chapter_title=chapter_title, source_kind=source_kind
    )
    text = simplify_inline_citations(text)
    text = expand_section_marks(text)
    text = expand_dates(text)
    text = expand_abbreviations(text)
    text = expand_example_parentheticals(text)
    text = expand_symbols(text)
    return _collapse_whitespace(text)


def prepare_chapters_for_tts(chapters: list[Chapter]) -> list[Chapter]:
    """Drop reference-only chapters and relocate footnotes before chunking."""
    prepared: list[Chapter] = []
    for chapter in chapters:
        if is_references_heading(chapter.title):
            continue
        text = strip_reference_sections(chapter.text)
        text = scrub_citations_for_tts(text)
        if not text.strip():
            continue
        prepared.append(replace(chapter, text=text))
    return prepared
