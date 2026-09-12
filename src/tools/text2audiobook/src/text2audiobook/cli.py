"""Command-line entry point: fire-and-forget folder scan or --url one-shot."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from text2audiobook.config import DEFAULT_CONFIG_PATH
from text2audiobook.stems import PIPELINE_STAGES


def _selected_stages(args: argparse.Namespace) -> list[str] | None:
    """Return requested stage names, or None for the full default pipeline."""
    selected = [name for name in PIPELINE_STAGES if getattr(args, name, False)]
    return selected or None


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
        "--extract",
        action="store_true",
        help="Run the extract stage (combinable with other stage flags).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run the clean stage (combinable; requires extract stem if extract is skipped).",
    )
    parser.add_argument(
        "--format",
        action="store_true",
        dest="format",
        help="Run the format stage (combinable; requires clean stem if clean is skipped).",
    )
    parser.add_argument(
        "--speak",
        action="store_true",
        help=(
            "Run the speak stage (combinable; requires format stem if format is skipped). "
            "Speak-only does not load the LLM."
        ),
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
            "CustomVoice speaker (e.g. Serena, Ryan, Aiden), 'random' for the "
            "CustomVoice pool, 'cloned' for Base voice clone (uses tts.ref_audio), "
            "or 'designed' for VoiceDesign. Content language stays from config "
            "tts.lang."
        ),
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help=(
            "Print CustomVoice speakers plus Base/VoiceDesign notes, then exit "
            "(no GPU / LLM load)."
        ),
    )
    cues = parser.add_mutually_exclusive_group()
    cues.add_argument(
        "--footnote-cues",
        action="store_true",
        dest="footnote_cues",
        help="Speak footnote start/end markers (overrides config).",
    )
    cues.add_argument(
        "--no-footnote-cues",
        action="store_false",
        dest="footnote_cues",
        help="Omit spoken footnote markers (overrides config).",
    )
    parser.set_defaults(footnote_cues=None)
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
        stages=_selected_stages(args),
        force=args.force,
        voice=args.voice,
        speak_footnote_cues=args.footnote_cues,
    )


if __name__ == "__main__":
    sys.exit(main())
