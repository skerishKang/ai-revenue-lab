"""Keep one-time credentials out of the access log.

The access line's request target is the path with its query string, and a login
callback's query is exactly the code that must never be persisted.
"""
from __future__ import annotations

import copy
import logging


class QueryStrippingFilter(logging.Filter):
    """Rewrite uvicorn's access arguments to the path alone."""

    def filter(self, record):
        args = getattr(record, 'args', None)
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2].partition('?')[0]
            if path != args[2]:
                record.args = (args[0], args[1], path, args[3], args[4])
        return True


def uvicorn_log_config(base):
    """Return uvicorn's logging config with access lines reduced to the path."""
    config = copy.deepcopy(base)
    config.setdefault('filters', {})['padiem_path_only'] = {'()': QueryStrippingFilter}
    access = config.get('handlers', {}).get('access')
    if isinstance(access, dict):
        access['filters'] = ['padiem_path_only']
    return config
