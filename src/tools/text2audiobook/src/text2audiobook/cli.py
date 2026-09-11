"""Command-line entry point: fire-and-forget folder scan or --url one-shot."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from text2audiobook.config import DEFAULT_CONFIG_PATH
from text2audiobook.stems import PIPELINE_STAGES


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
    parser.add_argument(
        "--stage",
        action="append",
        choices=PIPELINE_STAGES,
        dest="stages",
        help=(
            "Run only this stage (repeatable). Default: extract, clean, format, and speak. "
            "Speak-only does not load the LLM."
        ),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run only the clean stage (alias for --stage clean). Requires extract stem.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redo requested stages even when stems or the M4B already exist.",
    )
    parser.add_argument(
        "--voice",
        default=None,
        help=(
            "Kokoro voice id, or 'random' to pick A / A- / B- without replacement. "
            "Language code follows the voice prefix (af_* → a, bf_* → b)."
        ),
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="Print Kokoro voices and exit (no GPU / LLM load).",
    )
    args = parser.parse_args(argv)

    if args.list_voices:
        from text2audiobook.voices import format_voice_table

        print(format_voice_table())
        return 0

    from text2audiobook.gpu import prepare_gpu_env

    prepare_gpu_env()

    from text2audiobook.config import load_config
    from text2audiobook.formats.url import write_url_source
    from text2audiobook.logging_setup import setup_logging
    from text2audiobook.pipeline import run

    setup_logging()
    config = load_config(args.config)

    stages = list(args.stages or [])
    if args.clean and not args.stages:
        stages = ["clean"]
    elif args.clean:
        stages.append("clean")

    source_paths: list[Path] | None = None
    if args.url:
        url_dir = config.paths.staging_dir / "_cli_urls"
        source_paths = [
            write_url_source(url_dir, url, stem=f"cli_{index}")
            for index, url in enumerate(args.url, start=1)
        ]

    return run(
        config,
        source_paths=source_paths,
        stages=stages or None,
        force=args.force,
        voice=args.voice,
    )


if __name__ == "__main__":
    sys.exit(main())
