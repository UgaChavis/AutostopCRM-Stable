# ruff: noqa: E402
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from minimal_kanban.telegram_ai.worker import run

if __name__ == "__main__":
    raise SystemExit(run())
