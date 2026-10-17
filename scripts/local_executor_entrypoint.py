"""PyInstaller entrypoint; keeps package-relative imports out of the script boundary."""

import sys

from local_executor.__main__ import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        message = (
            "Topstep Local Executor could not start.\n\n"
            f"Error: {type(exc).__name__}: {exc}\n\n"
            "Please share this message with the person who provided the installer."
        )
        print(message, file=sys.stderr)
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(
                    None,
                    message,
                    "Topstep Local Executor",
                    0x10 | 0x1000,
                )
            except Exception:
                pass
        raise SystemExit(1) from None
