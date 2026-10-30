"""Give a store double the dispatch-authority seam the real store carries.

`D1HistoryStore` answers dispatch-row reads through `_dispatch`, which defaults to itself
(d1 mode). Tests that borrow the real methods onto a `SimpleNamespace` need the same parts or
they fail on a missing attribute rather than on behaviour.
"""
from __future__ import annotations

from app.history import D1HistoryStore

READS = ("get_oracle_mesh_run_correlation", "get_oracle_mesh_dispatch_pin",
         "get_oracle_mesh_run_command", "get_oracle_mesh_run_open_state")


def attach_dispatch_seam(store):
    store.dispatch_authority = None
    store._verified = D1HistoryStore._verified
    for name in READS:
        setattr(store, name, getattr(D1HistoryStore, name).__get__(store))
    store._dispatch = D1HistoryStore._dispatch.__get__(store)
    return store
