"""Tests for HTML / URL source readers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from text2audiobook import formats  # noqa: F401
from text2audiobook.formats.html_extract import extract_html_chapters, html_to_markdownish
from text2audiobook.formats.url import parse_url_file, read_url
from text2audiobook.io import find_sources, parse_source

_LONG = " ".join(f"word{i}" for i in range(40))


def _anthology_html() -> str:
    """Fixture shaped like retrochronic.com: TOC nav + h1 + essay h2 sections."""
    return f"""<!DOCTYPE html>
<html>
<head><title>Nick Land Anthology</title></head>
<body>
<nav>
  <ul>
    <li><a href="#cover">Cover</a></li>
    <li><a href="#circuitries">Circuitries</a></li>
    <li><a href="#machinic">Machinic Desire</a></li>
  </ul>
</nav>
<header><p>Site chrome should not be narrated.</p></header>
<main>
  <h1>retrochronic</h1>
  <p>{_LONG}</p>
  <h2 id="circuitries">Circuitries</h2>
  <p>{_LONG}</p>
  <h3>A subsection</h3>
  <p>{_LONG}</p>
  <h2 id="machinic">Machinic Desire</h2>
  <p>{_LONG}</p>
</main>
<footer>Subscribe Contact</footer>
</body>
</html>
"""


def test_html_to_markdownish_strips_nav_and_keeps_headings() -> None:
    md = html_to_markdownish(_anthology_html())
    assert "Cover" not in md
    assert "Subscribe Contact" not in md
    assert "# retrochronic" in md
    assert "## Circuitries" in md
    assert "## Machinic Desire" in md
    assert "A subsection" in md


def test_extract_html_chapters_orders_essays() -> None:
    chapters = extract_html_chapters(_anthology_html(), preamble_title="Book")
    titles = [chapter.title for chapter in chapters]
    assert titles == ["retrochronic", "Circuitries", "Machinic Desire"]
    # Subsection text stays inside Circuitries, not its own chapter
    circuitries = next(chapter for chapter in chapters if chapter.title == "Circuitries")
    assert "subsection" in circuitries.text.lower() or "word" in circuitries.text


def test_parse_html_source_file(tmp_path: Path) -> None:
    html_path = tmp_path / "anthology.html"
    html_path.write_text(_anthology_html(), encoding="utf-8")
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    metadata, chapters = parse_source(html_path, staging_root=staging, output_root=output)
    assert metadata.title == "Nick Land Anthology"
    assert [chapter.title for chapter in chapters] == [
        "retrochronic",
        "Circuitries",
        "Machinic Desire",
    ]
    assert (metadata.staging_dir / "source.html").exists()


def test_parse_url_file(tmp_path: Path) -> None:
    path = tmp_path / "site.url"
    path.write_text("https://retrochronic.com\nCustom Title\n", encoding="utf-8")
    url, title = parse_url_file(path)
    assert url == "https://retrochronic.com"
    assert title == "Custom Title"


def test_parse_url_file_rejects_non_http(tmp_path: Path) -> None:
    path = tmp_path / "bad.url"
    path.write_text("ftp://example.com\n", encoding="utf-8")
    with pytest.raises(ValueError, match="http"):
        parse_url_file(path)


def test_url_reader_uses_httpx_and_cache(tmp_path: Path) -> None:
    url_path = tmp_path / "retrochronic.url"
    url_path.write_text("https://retrochronic.com\n", encoding="utf-8")
    staging = tmp_path / "staging"
    output = tmp_path / "output"

    mock_response = MagicMock()
    mock_response.content = _anthology_html().encode("utf-8")
    mock_response.raise_for_status = MagicMock()

    with patch("text2audiobook.formats.url.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = mock_response
        metadata, chapters = parse_source(url_path, staging_root=staging, output_root=output)
        assert client.get.call_count == 1
        assert metadata.title == "Nick Land Anthology"
        assert len(chapters) == 3

        # Second parse should hit cache, not network
        metadata2, chapters2 = parse_source(url_path, staging_root=staging, output_root=output)
        assert client.get.call_count == 1
        assert [c.title for c in chapters2] == [c.title for c in chapters]
        assert metadata2.slug == metadata.slug


def test_url_file_title_override_wins_over_page_title(tmp_path: Path) -> None:
    url_path = tmp_path / "site.url"
    url_path.write_text("https://retrochronic.com\nMy Custom Book\n", encoding="utf-8")
    staging = tmp_path / "staging"
    output = tmp_path / "output"

    mock_response = MagicMock()
    mock_response.content = _anthology_html().encode("utf-8")
    mock_response.raise_for_status = MagicMock()

    with patch("text2audiobook.formats.url.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = mock_response
        metadata, _chapters = parse_source(url_path, staging_root=staging, output_root=output)

    assert metadata.title == "My Custom Book"
    assert metadata.slug == "my_custom_book"
    assert metadata.m4b_path.name == "my_custom_book.m4b"


def test_read_url_direct(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    mock_response = MagicMock()
    mock_response.content = _anthology_html().encode("utf-8")
    mock_response.raise_for_status = MagicMock()

    with patch("text2audiobook.formats.url.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = mock_response
        metadata, chapters = read_url(
            "https://retrochronic.com",
            staging_root=staging,
            output_root=output,
        )
    assert metadata.title == "Nick Land Anthology"
    assert chapters[0].title == "retrochronic"


def test_find_sources_includes_url_and_html(tmp_path: Path) -> None:
    (tmp_path / "a.epub").write_bytes(b"epub")
    (tmp_path / "b.md").write_text("# Hi\n", encoding="utf-8")
    (tmp_path / "c.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "d.url").write_text("https://example.com\n", encoding="utf-8")
    names = {path.name for path in find_sources(tmp_path)}
    assert names == {"a.epub", "b.md", "c.html", "d.url"}
