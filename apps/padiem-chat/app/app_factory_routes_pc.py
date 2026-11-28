from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .pc_device_pairing_routes import (
    PC_PAIRING_CLAIM_PATH,
    PC_PAIRING_ADOPT_PATH,
    PC_PAIRING_HANDOFF_PATH,
    PC_PAIRING_INSTALL_FILE_PATH,
    PC_PAIRING_INSTALL_EXE_PATH,
    PC_PAIRING_LABEL_PATH,
    PC_PAIRING_LINK_PATH,
    PC_PAIRING_MANAGED_PATH,
    PC_PAIRING_PAUSE_PATH,
    PC_PAIRING_RESUME_PATH,
    PC_PAIRING_PATH,
    PC_PAIRING_ROOT_PATH,
    PC_PAIRING_ROOTS_PATH,
    PC_PAIRING_TOKEN_REISSUE_PATH,
    PC_PAIRING_TOKEN_REVOKE_PATH,
    pc_pairing_approve_root,
    pc_pairing_adopt,
    pc_pairing_claim,
    pc_pairing_handoff,
    pc_pairing_install_file,
    pc_pairing_install_exe,
    pc_pairing_issue,
    pc_pairing_label,
    pc_pairing_managed,
    pc_pairing_managed_state,
    pc_pairing_list,
    pc_pairing_pause,
    pc_pairing_resume,
    pc_pairing_revoke,
    pc_pairing_revoke_root,
    pc_pairing_token_reissue,
    pc_pairing_token_revoke,
)

from .pc_file_exchange_routes import (
    PC_BROWSE_PATH,
    PC_CANCEL_PATH,
    PC_DELETE_PATH,
    PC_FETCH_PATH,
    PC_FILE_PATH,
    PC_FIND_PATH,
    PC_MOVE_PATH,
    PC_REFERENCE_PATH,
    PC_RESULT_PATH,
    PC_SAVE_PATH,
    pc_file_exchange_browse,
    pc_file_exchange_cancel,
    pc_file_exchange_delete,
    pc_file_exchange_fetch,
    pc_file_exchange_file,
    pc_file_exchange_find,
    pc_file_exchange_move,
    pc_file_exchange_reference,
    pc_file_exchange_result,
    pc_file_exchange_save,
)

def register_pc_routes(routes: list) -> None:
    routes.extend([
        # #5573 PC pairing: an owner links their own PC to their own account.
        # Every route refuses 503 while the pairing store is uncomposed, so
        # mounting is not an activation — a deployment without the store behaves
        # exactly as it did before.
        Route(PC_PAIRING_PATH, pc_pairing_issue, methods=["POST"]),
        Route(PC_PAIRING_PATH, pc_pairing_list, methods=["GET"]),
        Route(PC_PAIRING_CLAIM_PATH, pc_pairing_claim, methods=["POST"]),
        Route(PC_PAIRING_HANDOFF_PATH, pc_pairing_handoff, methods=["POST"]),
        Route(PC_PAIRING_INSTALL_FILE_PATH, pc_pairing_install_file, methods=["POST"]),
        Route(PC_PAIRING_INSTALL_EXE_PATH, pc_pairing_install_exe, methods=["POST"]),
        Route(PC_PAIRING_ADOPT_PATH, pc_pairing_adopt, methods=["POST"]),
        Route(PC_PAIRING_MANAGED_PATH, pc_pairing_managed, methods=["POST"]),
        Route(PC_PAIRING_MANAGED_PATH, pc_pairing_managed_state, methods=["GET"]),
        Route(PC_PAIRING_LINK_PATH, pc_pairing_revoke, methods=["DELETE"]),
        Route(PC_PAIRING_LABEL_PATH, pc_pairing_label, methods=["POST"]),
        Route(PC_PAIRING_PAUSE_PATH, pc_pairing_pause, methods=["POST"]),
        Route(PC_PAIRING_RESUME_PATH, pc_pairing_resume, methods=["POST"]),
        # #6695 PR-4: the owner cancels an install, or replaces it with a fresh
        # code and token. Both are owner-scoped and refuse 503 without a store.
        Route(PC_PAIRING_TOKEN_REVOKE_PATH, pc_pairing_token_revoke, methods=["POST"]),
        Route(PC_PAIRING_TOKEN_REISSUE_PATH, pc_pairing_token_reissue, methods=["POST"]),
        Route(PC_PAIRING_ROOTS_PATH, pc_pairing_approve_root, methods=["POST"]),
        Route(PC_PAIRING_ROOT_PATH, pc_pairing_revoke_root, methods=["DELETE"]),
        # #5895: the shared "from my PC / to my PC" part the menus will use. The
        # owner session and this account's own PC links are the only authority, and
        # no model turn is involved. The pairing store refuses 503 when it is not
        # composed, exactly as the pairing routes above do.
        Route(PC_BROWSE_PATH, pc_file_exchange_browse, methods=["POST"]),
        Route(PC_FIND_PATH, pc_file_exchange_find, methods=["POST"]),
        Route(PC_FETCH_PATH, pc_file_exchange_fetch, methods=["POST"]),
        Route(PC_SAVE_PATH, pc_file_exchange_save, methods=["POST"]),
        Route(PC_MOVE_PATH, pc_file_exchange_move, methods=["POST"]),
        Route(PC_DELETE_PATH, pc_file_exchange_delete, methods=["POST"]),
        Route(PC_CANCEL_PATH, pc_file_exchange_cancel, methods=["POST"]),
        Route(PC_REFERENCE_PATH, pc_file_exchange_reference, methods=["POST"]),
        Route(PC_RESULT_PATH, pc_file_exchange_result, methods=["GET"]),
        Route(PC_FILE_PATH, pc_file_exchange_file, methods=["GET"]),
    ])
