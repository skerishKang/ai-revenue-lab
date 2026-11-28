from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

def register_connector_enrollment_routes(routes: list, connector_owner_enrollment) -> None:
    # #4139: append the owner-only consent/challenge routes before the catch-all
    # StaticFiles Mount, solely when the server provided canonical private
    # Identity+Broker ports. The default public app has no such route.
    if connector_owner_enrollment is not None:
        from .connector_owner_runtime_mount import reviewed_owner_enrollment_routes
        from .connector_txt_read_routes import (
            CONNECTOR_TXT_READ_REQUEST_PATH,
            connector_txt_read_request,
        )
        from .connector_android_read_routes import (
            CONNECTOR_ANDROID_FOLDERS_PATH,
            CONNECTOR_ANDROID_READ_REQUEST_PATH,
            connector_android_folders,
            connector_android_read_request,
        )
        from .android_device_enrollment_routes import (
            ANDROID_ENROLLMENT_CHALLENGE_PATH,
            android_enrollment_challenge,
        )
        routes[-1:-1] = list(reviewed_owner_enrollment_routes(connector_owner_enrollment))
        routes[-1:-1] = [
            Route(CONNECTOR_TXT_READ_REQUEST_PATH, connector_txt_read_request, methods=["POST"]),
            # #5080: the Android device enrollment challenge. Same canonical
            # enrollment, Identity consent and Broker challenge as the browser
            # issue route; the one-time pairing code is released to the DEVICE
            # so the device can redeem the credential on the broker pairing
            # surface. It never releases a credential or a browser reference.
            Route(
                ANDROID_ENROLLMENT_CHALLENGE_PATH,
                android_enrollment_challenge,
                methods=["POST"],
            ),
            # #5080: Android adapter over the same approval/enqueue/result
            # pipeline. Folders are the phone's declared SAF set; the browser
            # never supplies an account, workspace, credential or SAF URI.
            Route(CONNECTOR_ANDROID_FOLDERS_PATH, connector_android_folders, methods=["GET"]),
            Route(
                CONNECTOR_ANDROID_READ_REQUEST_PATH,
                connector_android_read_request,
                methods=["POST"],
            ),
        ]
