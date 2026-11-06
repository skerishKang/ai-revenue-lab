"""Process-local identity cache counters, without cache keys or identities."""
import asyncio
from collections import defaultdict

_counts = defaultdict(lambda: [0, 0])
_timer = None


def record(layer, method, hit):
    _counts[(layer, method)][0 if hit else 1] += 1


def flush():
    global _timer
    _timer = None
    rows = sorted(_counts.items())
    _counts.clear()
    detail = ' '.join(f'{layer}.{method}:hit={counts[0]},miss={counts[1]}'
                      for (layer, method), counts in rows)
    print('identity_cache_minute ' + (detail or 'empty'), flush=True)


def _tick():
    flush()
    arm()


def arm():
    global _timer
    if _timer is None:
        _timer = asyncio.get_running_loop().call_later(60, _tick)


def stop():
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
