"""Trusted server composition foundation for the Worker isolated parser (#2824).

Why this module exists
----------------------
``padiem_ai_core.isolated_parser_client`` already defines the bounded client
and transport port (#2936), and ``padiem_ai_core.document_parser_boundary``
is still the single Worker binary parser *authority* decision. Between those
two contracts this module provides only the missing **trusted composition
seam**: server-side code prepares a transport, builds the existing client,
and installs that client as the Worker-side authority — without any caller
supplying endpoint, host, command, credential, timeout or parser selection.

What this module deliberately does NOT do
-----------------------------------------
* No endpoint, host, base URL, credential, timeout, deadline or parser
  selection parameter exists. The only input is an already-prepared
  ``IsolatedParserTransport`` that trusted server composition owns.
* No network, process, thread, signal or subprocess primitive is imported.
  A real HTTP/service transport and any server-owned endpoint configuration
  remain a later, explicitly reviewed live-binding slice (#1405 gate).
* Importing this module installs nothing. Until
  ``compose_worker_isolated_parser_authority`` is called by trusted server
  composition, the production Worker continues to fail closed with
  ``document_parser_isolation_unavailable``.
* The local CPython authority path is unchanged; composition affects only
  the production-Worker branch of the single existing resolver.
"""

from __future__ import annotations

from .document_parser_boundary import (
    BinaryDocumentParserPort,
    clear_worker_isolated_parser_composition,
    install_worker_isolated_parser_composition,
)
from .isolated_parser_client import IsolatedParserClient, IsolatedParserTransport


def compose_worker_isolated_parser_authority(
    *,
    transport: IsolatedParserTransport,
) -> BinaryDocumentParserPort:
    """Build the existing isolated-parser client and install it as Worker authority.

    Trusted server composition only. The transport (and any endpoint,
    credential or deadline it closes over) is supplied exclusively here; the
    document parse entry points never see it. Returns the installed port so
    composition code can retain a reference for lifecycle management.
    """

    client = IsolatedParserClient(transport=transport)
    install_worker_isolated_parser_composition(client)
    return client


def reset_worker_isolated_parser_composition() -> None:
    """Clear any installed Worker composition and restore the fail-closed default."""

    clear_worker_isolated_parser_composition()


__all__ = [
    "compose_worker_isolated_parser_authority",
    "reset_worker_isolated_parser_composition",
]
