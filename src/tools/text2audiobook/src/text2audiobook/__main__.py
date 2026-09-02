"""Allow `python -m text2audiobook`."""

import sys

from text2audiobook.cli import main

if __name__ == "__main__":
    sys.exit(main())
