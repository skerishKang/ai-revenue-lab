"""CI-only companion for the +14d rehearsal clock (no test/product code touched).

libfaketime shifts the process wall clock here, but this runner's Python reads
file timestamps through a path its stat interception does not cover. A freshly
written file therefore looks 14 days old, which trips mtime-based expiry in the
tus and pc-output stores. Shift only the timestamp read paths those stores use
so file times agree with the fake wall clock. os.stat itself is left alone, so
build backends keep seeing real metadata.
"""
import os
import pathlib

_OFFSET = float(os.environ.get("REHEARSAL_FILE_TIME_OFFSET_SECONDS", "1209600"))
_real_getmtime = os.path.getmtime
_real_getatime = os.path.getatime
_real_getctime = os.path.getctime
_real_path_stat = pathlib.Path.stat
_real_utime = os.utime


class _ShiftedStat:
    """Attribute-only view with the rehearsal offset added to file times."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if name in ("st_atime", "st_mtime", "st_ctime") and value is not None:
            return value + _OFFSET
        if name in ("st_atime_ns", "st_mtime_ns", "st_ctime_ns") and value is not None:
            return value + int(_OFFSET * 1_000_000_000)
        return value


def _path_stat(self, *args, **kwargs):
    return _ShiftedStat(_real_path_stat(self, *args, **kwargs))


def _utime(path, *args, **kwargs):
    # Tests that deliberately age a file compute the timestamp from the fake
    # clock. Store the real-clock equivalent so the read shift restores it.
    if args and args[0] is not None:
        args = (tuple(value - _OFFSET for value in args[0]),) + args[1:]
    if kwargs.get("ns") is not None:
        kwargs["ns"] = tuple(
            value - int(_OFFSET * 1_000_000_000) for value in kwargs["ns"]
        )
    return _real_utime(path, *args, **kwargs)


os.path.getmtime = lambda path: _real_getmtime(path) + _OFFSET
os.path.getatime = lambda path: _real_getatime(path) + _OFFSET
os.path.getctime = lambda path: _real_getctime(path) + _OFFSET
os.utime = _utime
pathlib.Path.stat = _path_stat
