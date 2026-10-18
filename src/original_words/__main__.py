"""应用入口：python -m original_words"""

from __future__ import annotations

import sys


def main() -> int:
    from original_words.application.app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
