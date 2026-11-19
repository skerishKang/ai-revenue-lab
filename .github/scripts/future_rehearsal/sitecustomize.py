"""CI-only companion for the +14d rehearsal clock (no test/product code touched).

libfaketime shifts the process wall clock here, but this runner's Python reads
file timestamps through a path its stat interception does not cover. A freshly
written file therefore looks 14 days old, which trips mtime-based expiry in the
tus and pc-output stores. Shifting reported file times by the same offset keeps
the rehearsal internally consistent; only this job's Python process is affected.
"""
import os

_OFFSET = float(os.environ.get("REHEARSAL_FILE_TIME_OFFSET_SECONDS", "1209600"))
_real_stat = os.stat
_real_lstat = os.lstat


def _shifted(result):
    values = list(result)
    for index in (7, 8, 9):
        if index < len(values):
            values[index] += _OFFSET
    if len(values) >= 13:
        for index in (10, 11, 12):
            values[index] += int(_OFFSET * 1_000_000_000)
    return os.stat_result(values)


def _stat(path, *args, **kwargs):
    return _shifted(_real_stat(path, *args, **kwargs))


def _lstat(path, *args, **kwargs):
    return _shifted(_real_lstat(path, *args, **kwargs))


os.stat = _stat
os.lstat = _lstat
os.path.getmtime = lambda path: _stat(path).st_mtime
os.path.getatime = lambda path: _stat(path).st_atime
os.path.getctime = lambda path: _stat(path).st_ctime
