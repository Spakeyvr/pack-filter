import sys

if len(sys.argv) > 1 and sys.argv[1] in ("scan", "apply", "restore", "-h", "--help"):
    from .cli import main
else:
    from .gui.app import main

sys.exit(main())
