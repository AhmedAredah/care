"""Frozen-build entry point (Phase 15.6).

Wraps the existing ``care.cli`` entry so that the frozen exe
- bootstraps user-data on first launch (copies seed config + templates),
- attaches the rotating-file logger,
- defaults to the desktop ``app`` subcommand when no argv is supplied
  (the typical "double-click the icon" path).

A double-clicked exe should land the operator in the GUI without them
having to type ``care.exe app``. Power-users can still
``care.exe serve --port 8080`` etc. — argv is honoured
verbatim when supplied.
"""
from __future__ import annotations

import sys


def _bootstrap() -> None:
    from care.core.logging import configure_logging_for_frozen
    from care.core.runtime_paths import bootstrap_user_data

    bootstrap_user_data()
    configure_logging_for_frozen()


def main() -> None:
    _bootstrap()

    from care.cli.main import main as cli_main

    if len(sys.argv) <= 1:
        # Double-click on the .exe → land in the desktop GUI.
        sys.argv = [sys.argv[0], "app"]

    cli_main()  # raises SystemExit


if __name__ == "__main__":
    main()
