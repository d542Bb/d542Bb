"""Run every widget's build script (widgets/*/build.py)."""

import subprocess
import sys
from pathlib import Path

WIDGETS = Path(__file__).resolve().parent


def main():
    scripts = sorted(WIDGETS.glob("*/build.py"))
    if not scripts:
        sys.exit("No widget build scripts found under widgets/*/.")
    for script in scripts:
        print(f"== {script.parent.name} ==")
        subprocess.run([sys.executable, str(script)], check=True)

    bust = WIDGETS / "bust_cache.py"
    if bust.exists():
        subprocess.run([sys.executable, str(bust)], check=True)


if __name__ == "__main__":
    main()
