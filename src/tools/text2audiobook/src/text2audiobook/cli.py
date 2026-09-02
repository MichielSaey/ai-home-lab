"""Command-line entry point: fire-and-forget folder scan or --url one-shot."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from text2audiobook.config import DEFAULT_CONFIG_PATH


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="text2audiobook",
        description=(
            "Convert supported text sources (EPUB, Markdown, HTML, .url) "
            "to M4B audiobooks."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Path to a config JSON file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help=(
            "Fetch and convert a web page (repeatable). "
            "When set, the input folder is not scanned."
        ),
    )
    args = parser.parse_args(argv)

    from text2audiobook.gpu import prepare_gpu_env

    prepare_gpu_env()

    from text2audiobook.config import load_config
    from text2audiobook.formats.url import write_url_source
    from text2audiobook.logging_setup import setup_logging
    from text2audiobook.pipeline import run

    setup_logging()
    config = load_config(args.config)

    source_paths: list[Path] | None = None
    if args.url:
        url_dir = config.paths.staging_dir / "_cli_urls"
        source_paths = [
            write_url_source(url_dir, url, stem=f"cli_{index}")
            for index, url in enumerate(args.url, start=1)
        ]

    return run(config, source_paths=source_paths)


if __name__ == "__main__":
    sys.exit(main())
