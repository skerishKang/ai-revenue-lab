from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .account_model_selection_routes import (
    MODEL_SELECTION_PATH,
    account_model_selection_get,
    account_model_selection_put,
)

from .pc_delegation_routes import PC_DELEGATION_PATH, pc_delegation_get, pc_delegation_put

from .mcp_gateway_account_routes import (
    MCP_TOKENS_PATH, MCP_TOKEN_PATH, MCP_APPROVALS_PATH, MCP_APPROVAL_PATH,
    MCP_OAUTH_CLIENTS_PATH, MCP_OAUTH_CLIENT_PATH,
    mcp_tokens_get, mcp_tokens_post, mcp_token_delete,
    mcp_approvals_get, mcp_approval_post,
    mcp_oauth_clients_get, mcp_oauth_client_delete,
)

from .mcp_gateway_transport import MCP_GATEWAY_PATH, mcp_gateway_endpoint

from .mcp_oauth import mcp_oauth_routes

from .chat_routes import api_chat, api_chat_stream

from .byok_routes import (
    byok_detect, byok_register,
    custom_credential_delete,
    custom_credential_save,
    custom_credential_status,
    custom_credential_test,
    custom_provider_models,
)

from .conversation_routes import (
    api_conversation_detail,
    api_conversation_search,
    api_conversation_update,
    api_conversations,
)

from .desktop_conversation_routes import (
    DESKTOP_CONVERSATION_DETAIL_PATH,
    DESKTOP_CONVERSATIONS_PATH,
    desktop_conversation_detail,
    desktop_conversations,
)

from .file_lane import BINARY_KINDS, KINDS, FileLaneClient, file_upload_ticket, file_capabilities

from .tus_chat_attachment import (
    CHAT_ATTACHMENT_TUS_COLLECTION_PATH,
    CHAT_ATTACHMENT_TUS_ITEM_PATH,
    chat_attachment_tus_collection,
    chat_attachment_tus_item,
)

def register_chat_routes(routes: list) -> None:
    routes.extend([
        Route("/api/conversations", api_conversations, methods=["GET"]),
        Route("/api/conversations/search", api_conversation_search, methods=["GET"]),
        Route("/api/conversations/{conversation_id}", api_conversation_detail, methods=["GET", "DELETE"]),
        # #7175: owner-scoped rename/pin. Same path, mutating method only.
        Route("/api/conversations/{conversation_id}", api_conversation_update, methods=["PATCH"]),
        # #3436 B2c: the GET-only canonical conversation surface for the paired
        # Desktop. Identity is the canonical broker device session, derived
        # server-side; it creates, deletes and writes nothing, and no browser
        # cookie path reaches it.
        Route(DESKTOP_CONVERSATIONS_PATH, desktop_conversations, methods=["GET"]),
        Route(
            DESKTOP_CONVERSATION_DETAIL_PATH,
            desktop_conversation_detail,
            methods=["GET"],
        ),
        Route("/api/chat/stream", api_chat_stream, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/byok/detect", byok_detect, methods=["POST"]),
        Route("/api/byok/register", byok_register, methods=["POST"]),
        Route("/api/files/ticket", file_upload_ticket, methods=["POST"]),
        Route("/api/files/capabilities", file_capabilities, methods=["GET"]),
        # #6579 3단계 — Chat 첨부는 base64 본문 대신 조각 업로드(tus 1.0.0)로 먼저
        # 올리고, 대화 요청에는 참조 ID만 싣는다. 대화 요청 문법
        # ({"type": "file", "file_id"})은 그대로다. See app/tus_chat_attachment.py.
        Route(CHAT_ATTACHMENT_TUS_COLLECTION_PATH, chat_attachment_tus_collection,
              methods=["POST", "OPTIONS"]),
        Route(CHAT_ATTACHMENT_TUS_ITEM_PATH, chat_attachment_tus_item,
              methods=["HEAD", "PATCH", "GET"]),
        Route("/api/chat/custom/credential", custom_credential_status, methods=["GET"]),
        Route("/api/chat/custom/credential", custom_credential_save, methods=["PUT"]),
        Route("/api/chat/custom/credential", custom_credential_delete, methods=["DELETE"]),
        # #5121 PADIEM Custom (BYOK) multi-provider routes: the customer key
        # lane, separate from the B14 managed model routes.
        Route("/api/chat/custom/credential/test", custom_credential_test, methods=["GET"]),
        Route("/api/chat/custom/models", custom_provider_models, methods=["GET"]),
        # #5222 account-scoped last selected AI tier. One signed-in account owns
        # one stored preference; the browser never names the account.
        Route(MODEL_SELECTION_PATH, account_model_selection_get, methods=["GET"]),
        Route(MODEL_SELECTION_PATH, account_model_selection_put, methods=["PUT"]),
        Route(PC_DELEGATION_PATH, pc_delegation_get, methods=["GET"]),
        Route(PC_DELEGATION_PATH, pc_delegation_put, methods=["PUT"]),
        Route(MCP_TOKENS_PATH, mcp_tokens_get, methods=["GET"]),
        Route(MCP_TOKENS_PATH, mcp_tokens_post, methods=["POST"]),
        Route(MCP_TOKEN_PATH, mcp_token_delete, methods=["DELETE"]),
        Route(MCP_OAUTH_CLIENTS_PATH, mcp_oauth_clients_get, methods=["GET"]),
        Route(MCP_OAUTH_CLIENT_PATH, mcp_oauth_client_delete, methods=["DELETE"]),
        Route(MCP_APPROVALS_PATH, mcp_approvals_get, methods=["GET"]),
        Route(MCP_APPROVAL_PATH, mcp_approval_post, methods=["POST"]),
        Route(MCP_GATEWAY_PATH, mcp_gateway_endpoint, methods=["POST", "GET", "DELETE", "OPTIONS"]),
        *mcp_oauth_routes(),
    ])
