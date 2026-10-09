import os
import sys


def resource(*parts):
    """Bundled file: next to the code when run from source, inside the .exe bundle when frozen."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)
