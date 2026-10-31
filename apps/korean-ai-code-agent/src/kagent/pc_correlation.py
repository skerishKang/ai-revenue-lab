"""Safe identifiers for PC lane operational correlation."""
import hashlib
import re

_RUN = re.compile(r"chat_pcq_[0-9a-f]{32}\Z")
_DISPATCH = re.compile(r"dsp_[0-9a-f]{32}\Z")
RUN_HASH_HEADER = "X-Padiem-PC-Run-Hash"
DISPATCH_ID_HEADER = "X-Padiem-PC-Dispatch-ID"


def run_hash(value):
    if not isinstance(value, str) or not _RUN.fullmatch(value):
        return None
    return hashlib.sha256(value.encode("ascii")).hexdigest()[:16]


def dispatch_id(value):
    return value if isinstance(value, str) and _DISPATCH.fullmatch(value) else None
