from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .claw_web_xlsx_source_routes import (
    WEB_SOURCES_PATH, WEB_SOURCE_DOWNLOAD_PATH,
    WEB_SOURCE_UPLOAD_TICKET_PATH, WEB_SOURCE_REGISTER_PATH,
    web_xlsx_sources, web_xlsx_download,
    web_xlsx_upload_ticket, web_xlsx_register,
)

from .tus_web_xlsx_upload import (
    WEB_XLSX_TUS_COLLECTION_PATH, WEB_XLSX_TUS_ITEM_PATH,
    web_xlsx_tus_collection, web_xlsx_tus_item,
)

from .claw_web_xlsx_selection_routes import (
    WEB_SELECTIONS_PATH, WEB_SELECTION_PATH,
    web_xlsx_selections, web_xlsx_selection_detail,
)

from .claw_web_xlsx_p01_owner_decision_routes import (
    WEB_XLSX_P01_OWNER_DECISION_PATH, web_xlsx_p01_owner_decision,
    WEB_XLSX_P01_OWNER_STATUS_PATH, web_xlsx_p01_owner_status,
    WEB_XLSX_P01_WORKCOPY_DOWNLOAD_PATH, web_xlsx_p01_workcopy_download,
)

from .claw_web_xlsx_quote_pdf import (
    PATH as WRITE_PDF_DOWNLOAD_PATH, web_xlsx_quote_pdf_download,
)

from .claw_web_xlsx_quote_approval_routes import (
    REQUEST as WRITE_REQUEST_PATH, DECISION as WRITE_DECISION_PATH,
    DECISION_STATUS as WRITE_APPROVAL_STATUS_PATH,
    request_quote_write, decide_quote_write, quote_write_approval_status,
)

from .claw_web_xlsx_quote_write_routes import (
    WRITE_PATH, WRITE_STATUS_PATH, WRITE_DOWNLOAD_PATH,
    web_xlsx_quote_edit_commit, web_xlsx_quote_edit_status,
    web_xlsx_quote_edit_download,
)

from .claw_web_xlsx_quote_preview_routes import (
    WEB_XLSX_QUOTE_PREVIEW_PATH, web_xlsx_quote_edit_preview,
)

from .claw_web_xlsx_p01_request_routes import (
    WEB_XLSX_REQUEST_P01_PATH, web_xlsx_request_p01,
)

from .claw_web_xlsx_p01_start_routes import (
    WEB_XLSX_START_P01_PATH, web_xlsx_start_p01,
)

def register_web_xlsx_routes(routes: list) -> None:
    routes.extend([
        Route(WEB_SOURCES_PATH, web_xlsx_sources, methods=["GET", "POST"]),
        Route(WEB_SOURCE_UPLOAD_TICKET_PATH, web_xlsx_upload_ticket, methods=["POST"]),
        Route(WEB_SOURCE_REGISTER_PATH, web_xlsx_register, methods=["POST"]),
        Route(WEB_SOURCE_DOWNLOAD_PATH, web_xlsx_download, methods=["GET"]),
        # #6579 step 2: a 1 GiB original arrives as <=90 MiB tus chunks.
        Route(WEB_XLSX_TUS_COLLECTION_PATH, web_xlsx_tus_collection, methods=["POST", "OPTIONS"]),
        Route(WEB_XLSX_TUS_ITEM_PATH, web_xlsx_tus_item, methods=["HEAD", "PATCH", "GET"]),
        Route(WEB_SELECTIONS_PATH, web_xlsx_selections, methods=["GET", "POST"]),
        Route(WEB_SELECTION_PATH, web_xlsx_selection_detail, methods=["GET"]),
        Route(WEB_XLSX_REQUEST_P01_PATH, web_xlsx_request_p01, methods=["POST"]),
        Route(WEB_XLSX_START_P01_PATH, web_xlsx_start_p01, methods=["POST"]),
        Route(WEB_XLSX_P01_OWNER_DECISION_PATH, web_xlsx_p01_owner_decision, methods=["POST"]),
        Route(WEB_XLSX_P01_OWNER_STATUS_PATH, web_xlsx_p01_owner_status, methods=["GET"]),
        Route(WEB_XLSX_P01_WORKCOPY_DOWNLOAD_PATH, web_xlsx_p01_workcopy_download, methods=["GET"]),
        Route(WEB_XLSX_QUOTE_PREVIEW_PATH, web_xlsx_quote_edit_preview, methods=["POST"]),
        Route(WRITE_PATH, web_xlsx_quote_edit_commit, methods=["POST"]),
        Route(WRITE_REQUEST_PATH, request_quote_write, methods=["POST"]),
        Route(WRITE_DECISION_PATH, decide_quote_write, methods=["POST"]),
        Route(WRITE_APPROVAL_STATUS_PATH, quote_write_approval_status, methods=["GET"]),
        Route(WRITE_STATUS_PATH, web_xlsx_quote_edit_status, methods=["GET"]),
        Route(WRITE_DOWNLOAD_PATH, web_xlsx_quote_edit_download, methods=["GET"]),
        Route(WRITE_PDF_DOWNLOAD_PATH, web_xlsx_quote_pdf_download, methods=["GET"]),
    ])
