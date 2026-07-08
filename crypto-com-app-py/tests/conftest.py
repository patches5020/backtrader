import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.dirname(_THIS_DIR)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

os.environ.setdefault("CDC_API_KEY", "test-key")
os.environ.setdefault("CDC_API_SECRET", "test-secret")
