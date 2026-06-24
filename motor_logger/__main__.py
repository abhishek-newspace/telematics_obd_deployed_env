from __future__ import annotations

import sys
from pathlib import Path

from motor_logger.app import main

if __name__ == "__main__":
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(main(cfg))
