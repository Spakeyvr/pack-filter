"""PyInstaller entry point."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] in ("scan", "export", "apply", "restore"):
        from packfilter.cli import main as cli_main
        sys.exit(cli_main(sys.argv[1:]))
    from packfilter.gui.app import main
    sys.exit(main())
