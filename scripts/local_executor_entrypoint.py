"""PyInstaller entrypoint; keeps package-relative imports out of the script boundary."""

from local_executor.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
