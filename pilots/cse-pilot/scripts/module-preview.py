#!/usr/bin/env python3
"""Run the same module preview helper shipped in generated workspaces."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "templates/scripts/module-preview.py"),
                   run_name="__main__")
