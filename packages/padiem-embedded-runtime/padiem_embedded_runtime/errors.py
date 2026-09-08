"""IP-SIDECAR shared error type.

Every contract violation fails closed by raising :class:`SidecarContractError`.
No secret, credential, or provider material ever flows through this package.
"""

from __future__ import annotations


class SidecarContractError(ValueError):
    """Raised when any IP-SIDECAR boundary contract is violated."""
