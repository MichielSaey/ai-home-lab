"""Allow `python -m epub2audiobook`."""

import sys

from epub2audiobook.cli import main

if __name__ == "__main__":
    sys.exit(main())
