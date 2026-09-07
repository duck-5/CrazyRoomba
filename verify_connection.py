"""
Backward-compatibility wrapper for verify_connection.py.
Delegates to scripts/verify.py.
"""

from scripts.verify import main

if __name__ == "__main__":
    main()
