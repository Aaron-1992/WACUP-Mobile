"""Kept for older scripts; the generator now lives in nescore/demo.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nescore.demo import build, write          # noqa: F401


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "test-song.mid"
    print("wrote %s" % write(target))
