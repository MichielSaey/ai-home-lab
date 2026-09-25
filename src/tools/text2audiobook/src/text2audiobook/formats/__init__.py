"""Built-in source format readers."""

from text2audiobook.formats.epub import EpubReader
from text2audiobook.formats.markdown import MarkdownReader
from text2audiobook.formats.pdf import PdfReader
from text2audiobook.formats.url import HtmlReader, UrlReader
from text2audiobook.io import register_reader

register_reader(EpubReader())
register_reader(MarkdownReader())
register_reader(PdfReader())
register_reader(HtmlReader())
register_reader(UrlReader())
