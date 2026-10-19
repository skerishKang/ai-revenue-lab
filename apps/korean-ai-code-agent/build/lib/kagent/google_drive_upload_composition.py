"""#3580 composition root for the existing trusted Google Drive WRITE port.

``google_drive_multipart_transport.py`` already owns the concrete Drive
``files.create`` multipart port (``StdlibGoogleDriveMultipartCreatePort``) and
``google_drive_artifact_upload.py`` already owns the canonical upload adapter
(``GoogleDriveArtifactUploadAdapter``). What no file owned was the one place
that assembles them, which is why the canonical flag
``PRODUCTION_DRIVE_WRITE_PORT_COMPOSED`` still reads ``False`` and the only
callers of the real port were its own hermetic tests.

This module is that place, and it is deliberately powerless:

```text
WHAT THIS FILE IS
  One composition root that wires the existing Drive WRITE port from
  server-owned config and hands the assembled uploader to an authorized
  Control Plane host.

WHAT IT IS NOT
  Not a Drive WRITE grant, not an OAuth authority and not a token store.
  Assembling the objects changes nothing about whether an upload may be made:
  #2010 keeps Google Drive at READ-only, the CP lease port reports
  ``DRIVE_WRITE = False`` and no live canary has been run. Every one of those
  stays closed after this module runs, so a composed uploader still refuses
  before any socket is opened.
```
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import google_drive_multipart_transport as _transport
from .connector_trust import (
    ConnectorBindingProjection, InMemoryWriteIdempotencyRegistry,
)
from .contracts import ContractError
from .google_drive_artifact_upload import GoogleDriveArtifactUploadAdapter
from .google_drive_multipart_transport import (
    DriveAuthorizedWriteTokenPort, GOOGLE_UPLOAD_ORIGIN,
    StdlibGoogleDriveMultipartCreatePort,
    UnconfiguredDriveAuthorizedWriteTokenPort,
)
from .google_drive_scope import DriveScopeProjection
from .google_oauth_authority import (
    GoogleProviderNetworkPort, StdlibGoogleProviderNetwork,
)

DRIVE_UPLOAD_COMPOSITION_CONTRACT_VERSION = "claw-drive-upload-composition.v1"

#: The composition root now exists. This records source wiring only; the grant,
#: the production host and the live canary below are still closed.
GOOGLE_DRIVE_UPLOAD_COMPOSITION_ROOT_WIRED = True

#: #2010 keeps Google Drive at READ-only. No authority is created here.
DRIVE_WRITE_GRANT_AUTHORIZED = False
LIVE_DRIVE_UPLOAD_CANARY = False
PRODUCTION_ACTIVATION = "BLOCKED"
NEW_DRIVE_AUTHORITY = False
NEW_TOKEN_STORE = False
AUTO_RETRY = False

#: The composition root's entire caller surface, pinned as data. Neither entry
#: can carry an endpoint, a path, a folder id, a scope or a credential value.
DRIVE_UPLOAD_COMPOSITION_PARAMETERS = ("authorization", "network")

#: Construction-time I/O counters, kept as data a reviewer can assert against
#: instead of trusting the prose above.
DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS = 0
DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS = 0


class DriveUploadCompositionError(ContractError):
    """Fail-closed composition error; no provider or credential detail leaks."""


@dataclass(frozen=True, slots=True)
class GoogleDriveUploadComposition:
    """The assembled Drive WRITE stack, in the order the upload port consumes it.

    Holding the objects is not permission to use them: ``armed`` stays ``False``
    for every instance that can exist in this build, because the WRITE grant and
    the live canary are both closed and the production host has not composed one.
    """

    authorization: DriveAuthorizedWriteTokenPort
    network: GoogleProviderNetworkPort
    upload_port: StdlibGoogleDriveMultipartCreatePort

    def __post_init__(self) -> None:
        # Structural defence against a second stack: a composition that held a
        # look-alike upload port would be a new authority wearing a canonical
        # name. The token and network seams stay duck-typed on purpose so an
        # authorized CP host can bind its own implementation, but neither may be
        # inert.
        if not callable(getattr(self.authorization, "resolve_write_access_token", None)):
            raise DriveUploadCompositionError("Drive WRITE token authority is unusable")
        if not callable(getattr(self.network, "request", None)):
            raise DriveUploadCompositionError("Drive provider network port is unusable")
        if not isinstance(self.upload_port, StdlibGoogleDriveMultipartCreatePort):
            raise DriveUploadCompositionError(
                "the composition root wires the canonical Drive multipart create port only"
            )

    @property
    def token_authority_unconfigured(self) -> bool:
        return isinstance(self.authorization, UnconfiguredDriveAuthorizedWriteTokenPort)

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.token_authority_unconfigured:
            reasons.append("no CP Drive WRITE token authority was supplied")
        if _transport.PRODUCTION_DRIVE_WRITE_PORT_COMPOSED is not True:
            reasons.append("no production host composes the Google Drive WRITE port")
        if DRIVE_WRITE_GRANT_AUTHORIZED is not True:
            reasons.append("the Google Drive WRITE grant is not authorized (#2010 is READ-only)")
        if LIVE_DRIVE_UPLOAD_CANARY is not True:
            reasons.append("no live Drive upload canary has been run")
        return tuple(reasons)

    @property
    def armed(self) -> bool:
        return False

    def uploader(
        self, *,
        binding: ConnectorBindingProjection, scope: DriveScopeProjection,
        artifacts: Any, folders: Any, approval: Any,
        attempts: InMemoryWriteIdempotencyRegistry | None = None,
    ) -> GoogleDriveArtifactUploadAdapter:
        """Assemble the canonical adapter around the composed real upload port.

        The adapter independently re-checks binding, scope, folder proof, exact
        artifact bytes, WRITE approval and one-shot replay. This method cannot
        relax any of them: it only guarantees the adapter receives the canonical
        composed port instead of a caller-supplied substitute.
        """
        return GoogleDriveArtifactUploadAdapter(
            binding=binding, scope=scope, artifacts=artifacts,
            folders=folders, approval=approval, upload=self.upload_port,
            **({} if attempts is None else {"attempts": attempts}),
        )

    def safe_dict(self) -> dict[str, Any]:
        """Projection safe to log: no token, no folder id, no artifact bytes."""
        return {
            "contract_version": DRIVE_UPLOAD_COMPOSITION_CONTRACT_VERSION,
            "composition_root_wired": GOOGLE_DRIVE_UPLOAD_COMPOSITION_ROOT_WIRED,
            # Read through the transport module, not copied: one flag, one authority.
            "production_drive_write_port_composed": (
                _transport.PRODUCTION_DRIVE_WRITE_PORT_COMPOSED
            ),
            "drive_write_grant_authorized": DRIVE_WRITE_GRANT_AUTHORIZED,
            "live_drive_upload_canary": LIVE_DRIVE_UPLOAD_CANARY,
            "production_activation": PRODUCTION_ACTIVATION,
            "new_drive_authority": NEW_DRIVE_AUTHORITY,
            "new_token_store": NEW_TOKEN_STORE,
            "token_authority_unconfigured": self.token_authority_unconfigured,
            "upload_endpoint_origin": GOOGLE_UPLOAD_ORIGIN,
            "upload_port": StdlibGoogleDriveMultipartCreatePort.__name__,
            "network": type(self.network).__name__,
            "authorization": type(self.authorization).__name__,
            "blocked_reasons": list(self.blocked_reasons),
            "armed": self.armed,
            "construction_provider_requests": (
                DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS
            ),
            "construction_token_resolutions": (
                DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS
            ),
            "production_claim": False,
        }


def build_google_drive_upload_composition(
    *,
    authorization: DriveAuthorizedWriteTokenPort | None = None,
    network: GoogleProviderNetworkPort | None = None,
) -> GoogleDriveUploadComposition:
    """Wire the canonical Drive WRITE stack from server-owned config.

    ``authorization`` is the existing CP connector secret/WRITE-lease authority
    and ``network`` is the existing pinned Google provider transport; everything
    else — upload origin, path, query, timeout and response bound — comes from
    source. Supplying neither is the normal state and also the safest one: the
    token port then refuses before any socket is opened, and ``armed`` is still
    ``False`` because the WRITE grant and the live canary are closed.

    Construction performs no provider request and resolves no token.
    """
    if authorization is not None and not callable(
        getattr(authorization, "resolve_write_access_token", None)
    ):
        raise DriveUploadCompositionError(
            "Drive WRITE token authority must resolve an access token"
        )
    if network is not None and not callable(getattr(network, "request", None)):
        raise DriveUploadCompositionError("Drive provider network port must request")

    token_port = authorization if authorization is not None else (
        UnconfiguredDriveAuthorizedWriteTokenPort()
    )
    provider_network = network if network is not None else StdlibGoogleProviderNetwork()
    upload_port = StdlibGoogleDriveMultipartCreatePort(
        authorization=token_port, network=provider_network,
    )
    return GoogleDriveUploadComposition(
        authorization=token_port, network=provider_network, upload_port=upload_port,
    )


__all__ = [
    "DRIVE_UPLOAD_COMPOSITION_CONTRACT_VERSION",
    "DRIVE_UPLOAD_COMPOSITION_PARAMETERS",
    "DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS",
    "DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS",
    "DRIVE_WRITE_GRANT_AUTHORIZED",
    "GOOGLE_DRIVE_UPLOAD_COMPOSITION_ROOT_WIRED",
    "LIVE_DRIVE_UPLOAD_CANARY",
    "PRODUCTION_ACTIVATION",
    "DriveUploadCompositionError",
    "GoogleDriveUploadComposition",
    "build_google_drive_upload_composition",
]
