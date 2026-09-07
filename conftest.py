import sys
from pathlib import Path

# Ensure root workspace is on sys.path for test discovery
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
