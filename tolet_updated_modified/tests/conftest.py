import os
import sys

# The app's own modules import each other as `from services.xxx import yyy`
# (relative to app/ being the import root), not `from app.services.xxx import
# yyy` — mirroring how run.py/main.py are actually launched. Tests need the
# same sys.path setup, or every `from services...` import inside app/ fails.
_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
