"""Command-line entry point: zero-argument fire and forget."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from epub2audiobook.config import DEFAULT_CONFIG_PATH


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="epub2audiobook",
        description="Convert every EPUB in the configured folder to an M4B audiobook.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Path to a config JSON file (default: {DEFAULT_CONFIG_PATH})",
    )
    args = parser.parse_args(argv)

    from epub2audiobook.gpu import prepare_gpu_env

    prepare_gpu_env()

    from epub2audiobook.config import load_config
    from epub2audiobook.logging_setup import setup_logging
    from epub2audiobook.pipeline import run

    setup_logging()
    config = load_config(args.config)
    return run(config)


if __name__ == "__main__":
    sys.exit(main())
