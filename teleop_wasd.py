"""
Backward-compatibility wrapper for teleop_wasd.py.
Delegates to scripts/teleop_cli.py.
"""

from scripts.teleop_cli import main

if __name__ == "__main__":
    main()
