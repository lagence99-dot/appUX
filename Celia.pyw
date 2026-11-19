"""Lanceur de Celia (double-clic sous Windows : s'ouvre sans fenêtre de console)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from celia.app import main  # noqa: E402

main()
