"""Deterministic TTS-oriented rewriting for the cleanup / formatting step."""

from __future__ import annotations

import re
from dataclasses import replace

from text2audiobook.io import Chapter

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
    rf"(?:"
    rf"(?P<author>{_AUTHOR}|[A-Z][A-Za-z'.-]+\s+et\s+al\.?)"
    rf",?\s+(?P<year>(?:18|19|20)\d{{2}})[a-z]?"
    rf"(?:,\s*[Pp]p?\.\s*\d+[a-z]?(?:\s*[-–—]\s*\d+[a-z]?)?)?"
    rf"|"
    rf"(?P<last>[A-Z][A-Za-z'.-]+),\s+(?P<year2>(?:18|19|20)\d{{2}})[a-z]?"
    rf",\s*[Pp]p?\.\s*\d+[a-z]?(?:\s*[-–—]\s*\d+[a-z]?)?"
    rf")"
    rf"\)"
)

_NUMERIC_REF_RE = re.compile(r"\s*\[\d+(?:\s*[-–,;]\s*\d+)*\]")

_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\be\.i\.(?=\s|,|:|;|\)|$)", re.IGNORECASE), "in other words"),
    (re.compile(r"\bi\.e\.(?=\s|,|:|;|\)|$)", re.IGNORECASE), "in other words"),
    (re.compile(r"\be\.g\.(?=\s|,|:|;|\)|$)", re.IGNORECASE), "for example"),
)

_RESUME_AFTER_REFERENCES_RE = re.compile(
    r"""
    ^
    (?:\#{1,6}\s+)?
    (
        appendi(?:x|ces)(?:\s+[A-Z0-9]+)?
        | acknowledgements?
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


def _replace_date(match: re.Match[str]) -> str:
    day = int(match.group("day"))
    month = int(match.group("month"))
    year = int(match.group("year"))
    if not 1 <= month <= 12:
        return match.group(0)
    if not 1 <= day <= _DAYS_IN_MONTH[month - 1]:
        return match.group(0)
    if year < 1000:
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


def _replace_full_citation(match: re.Match[str]) -> str:
    body = match.group("body").strip()
    first = body.split()[0].lower().rstrip(",;:") if body.split() else ""
    if first in _CITE_SUBJECT_PRONOUNS or "," not in body:
        return match.group(0)
    author = match.group("author")
    year = year_to_words(int(match.group("year")))
    return f"Wrote {author} in {year}."


def _replace_paren_citation(match: re.Match[str]) -> str:
    author = match.group("author") or match.group("last")
    year_raw = match.group("year") or match.group("year2")
    year = year_to_words(int(year_raw))
    return f", wrote {author} in {year}"


def simplify_inline_citations(text: str) -> str:
    text = _FULL_CITE_PAGES_RE.sub(_replace_full_citation, text)
    text = _PAREN_CITE_RE.sub(_replace_paren_citation, text)
    text = _NUMERIC_REF_RE.sub("", text)
    return text


def _collapse_whitespace(text: str) -> str:
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def format_for_tts(text: str) -> str:
    """Rewrite a chunk so Kokoro hears spoken forms instead of print conventions."""
    text = strip_reference_sections(text)
    text = simplify_inline_citations(text)
    text = expand_dates(text)
    text = expand_abbreviations(text)
    return _collapse_whitespace(text)


def prepare_chapters_for_tts(chapters: list[Chapter]) -> list[Chapter]:
    """Drop reference-only chapters and trailing bibliography blocks before chunking."""
    prepared: list[Chapter] = []
    for chapter in chapters:
        if is_references_heading(chapter.title):
            continue
        text = strip_reference_sections(chapter.text)
        if not text.strip():
            continue
        prepared.append(replace(chapter, text=text))
    return prepared
