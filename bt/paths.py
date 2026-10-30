import ctypes
import functools
import os
import sys


def resource(*parts):
    """Bundled file: next to the code when run from source, inside the .exe bundle when frozen."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


@functools.lru_cache(maxsize=None)
def package_family():
    """The package's family name when BookTalker came from the Microsoft Store (an MSIX package),
    else None."""
    n = ctypes.c_uint32(0)
    try:        # unpackaged: 15700 (APPMODEL_ERROR_NO_PACKAGE); packaged: 122, the name won't fit
        if ctypes.windll.kernel32.GetCurrentPackageFamilyName(ctypes.byref(n), None) != 122:
            return None
        buf = ctypes.create_unicode_buffer(n.value)
        return None if ctypes.windll.kernel32.GetCurrentPackageFamilyName(ctypes.byref(n), buf) else buf.value
    except (AttributeError, OSError):
        return None
