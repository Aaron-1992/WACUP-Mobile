#!/usr/bin/env python3
"""Entry point for the packaged executable and for `python chip8bit.py`.

    chip8bit.exe                        open the app window (the normal way)
    chip8bit.exe song.mid               open the window with that file queued
    chip8bit.exe song.mid --extensions all
                                        command line, for scripts and batches
    chip8bit.exe --cli --list-extensions
                                        command line, explicitly
    chip8bit.exe --selftest             headless check of the window and pipeline
"""

import os
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--selftest":
        from nescore import app
        screenshot = None
        if "--screenshot" in argv:
            index = argv.index("--screenshot")
            if index + 1 < len(argv):
                screenshot = argv[index + 1]
        return app.selftest(screenshot)

    if argv and argv[0] == "--window":
        from nescore.app import run
        return run([item for item in argv[1:] if os.path.isfile(item)])

    if argv and argv[0] == "--cli":
        from nescore.cli import main as cli
        return cli(argv[1:])

    if not argv:
        from nescore.app import run
        return run()

    # A file dropped onto the executable shows up as a bare path: open the window
    # with it queued. Anything that looks like an option means the command line.
    looks_like_options = any(item.startswith("-") for item in argv)
    if not looks_like_options and all(os.path.isfile(item) for item in argv):
        from nescore.app import run
        return run(argv)

    from nescore.cli import main as cli
    return cli(argv)


if __name__ == "__main__":
    sys.exit(main())
