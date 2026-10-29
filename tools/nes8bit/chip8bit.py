#!/usr/bin/env python3
"""Entry point for the packaged executable and for `python chip8bit.py`.

    chip8bit.exe                        open the window (the normal, friendly way)
    chip8bit.exe song.mid               window opens with that file ready to convert
    chip8bit.exe song.mid --extensions all --stats
                                        command line (the console build, or python)
    chip8bit.exe --serve --port 8734    serve the window without opening a browser
    chip8bit.exe --selftest             headless check of the window and the pipeline
"""

import os
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in ("--gui", "--window"):
        from nescore.gui import run
        files = [item for item in argv[1:] if os.path.isfile(item)]
        return run(initial_files=files, open_browser="--no-browser" not in argv)

    if argv and argv[0] in ("--serve", "--selftest"):
        from nescore import gui
        host, port = "127.0.0.1", 8734
        rest = argv[1:]
        for index, item in enumerate(rest):
            if item == "--host" and index + 1 < len(rest):
                host = rest[index + 1]
            elif item == "--port" and index + 1 < len(rest):
                port = int(rest[index + 1])
        if argv[0] == "--selftest":
            return gui.selftest(host)
        return gui.run(host, port, open_browser=False)

    # A windowed executable has no console to print to: always show the window,
    # and queue up any files that were dropped onto it.
    if getattr(sys, "frozen", False) and sys.stdout is None:
        from nescore.gui import run
        return run(initial_files=[item for item in argv if os.path.isfile(item)])

    if not argv:
        from nescore.gui import run
        return run()

    from nescore.cli import main as cli
    return cli(argv)


if __name__ == "__main__":
    sys.exit(main())
