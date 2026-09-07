"""
Backward-compatibility wrapper for web_server.py.
Delegates to scripts/run_server.py and roomba.web.app.
"""

from roomba.web.app import app, controller
from scripts.run_server import main

if __name__ == "__main__":
    main()
