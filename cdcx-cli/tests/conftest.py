import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CDCX_DIR = os.path.dirname(_THIS_DIR)
_REPO_ROOT = os.path.dirname(_CDCX_DIR)
for path in (_CDCX_DIR, _REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
