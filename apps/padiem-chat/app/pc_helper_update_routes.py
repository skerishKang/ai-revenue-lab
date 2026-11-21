"""Owner-only controls for the installed, fixed Windows helper update task."""
from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth_routes import current_user_id
from .pc_device_pairing_routes import _body, _now
from .pc_helper_update_policy import load_update_view, version_parts

PATH = "/api/pc/helper-updates"
_LINK = PATH + "/{link_id}"
_NO_STORE = {"Cache-Control": "no-store"}
# The helper runs this as its normal Windows user. No paths, arguments or shell
# text are accepted from the HTTP client; the installed task alone has SYSTEM.
_PREFIX = (
    "$ErrorActionPreference='Stop';"
    "$p='HKCU:\\Software\\PADIEM\\PCConnect';"
    "New-Item -Path $p -Force|Out-Null;"
)
_RUN = "schtasks.exe /Run /TN '\\Padiem\\PadiemUserHelperUpdater';if($LASTEXITCODE -ne 0){throw 'update_task_start_failed'}"


def control_command(*, auto=None, version=None):
    if type(auto) is bool and version is None:
        return _PREFIX + "Remove-ItemProperty -Path $p -Name ManualVersion -ErrorAction SilentlyContinue;" + f"New-ItemProperty -Path $p -Name AutoUpdate -Value {int(auto)} -PropertyType DWord -Force|Out-Null;" + _RUN
    if auto is None and version_parts(version) is not None:
        return _PREFIX + f"New-ItemProperty -Path $p -Name ManualVersion -Value '{version}' -PropertyType String -Force|Out-Null;" + _RUN
    raise ValueError("invalid helper update control")


def is_control_command(command):
    if command in (control_command(auto=True), control_command(auto=False)):
        return True
    prefix = _PREFIX + "New-ItemProperty -Path $p -Name ManualVersion -Value '"
    suffix = "' -PropertyType String -Force|Out-Null;" + _RUN
    return (isinstance(command, str) and command.startswith(prefix) and command.endswith(suffix)
            and version_parts(command[len(prefix):-len(suffix)]) is not None)


async def command_update_denial(state, *, device_id, command, user_mode, helper_update_control, now):
    """The only exemption is the exact fixed owner update control, in user mode."""
    if helper_update_control:
        return None if user_mode and is_control_command(command) else (403, "oracle_mesh_command_unverified", None)
    view = await load_update_view(state, device_id=device_id, now=now)
    if view["update_required"]:
        return 409, "pc_helper_update_required", "업데이트 후 사용할 수 있어요"
    return None


def response(body, status=200):
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def failure(code, status):
    return response({"ok": False, "error": {"code": code}}, status)


async def _rows(request, uid):
    store = request.app.state.pc_device_pairing_store
    return await store.list_helper_update_preferences(user_id=uid)


async def _view(request, row):
    from .pc_device_pairing_routes import _presence_view

    state = request.app.state
    now = _now()
    device = row["mesh_node_id"]
    presence = await _presence_view(getattr(state, "mesh_device_presence_store", None), device_id=device, now=now)
    update = await load_update_view(state, device_id=device, now=now)
    auto = row["auto_helper_update"] == 1
    return {"link_id": row["link_id"], "label": row.get("label"), "online": presence["online"],
            "auto_update": auto, **update,
            "dismissed": row.get("helper_update_dismissed_version") == update["latest_version"],
            "notice": presence["online"] and not auto and update["update_available"]
                       and row.get("helper_update_dismissed_version") != update["latest_version"]}


async def list_updates(request):
    uid = current_user_id(request)
    if not uid:
        return failure("unauthorized", 401)
    try:
        return response({"ok": True, "devices": [await _view(request, row) for row in await _rows(request, uid)]})
    except Exception:
        return failure("pc_update_unavailable", 503)


async def change_update(request):
    from .pc_file_exchange_routes import _owner, _dispatch_target, _stage_run, _staged
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent

    uid = current_user_id(request)
    if not uid:
        return failure("unauthorized", 401)
    body = await _body(request)
    if not isinstance(body, dict):
        return failure("pc_update_invalid", 400)
    action = body.get("action")
    if action not in ("auto", "update", "dismiss") or set(body) != (
        {"action", "enabled"} if action == "auto" else {"action", "version"} if action == "dismiss" else {"action"}
    ) or (action == "auto" and type(body["enabled"]) is not bool):
        return failure("pc_update_invalid", 400)
    try:
        rows = await _rows(request, uid)
        row = next((row for row in rows if row["link_id"] == request.path_params["link_id"]), None)
        if row is None:
            return failure("pc_link_not_found", 404)
        state = request.app.state
        store = state.pc_device_pairing_store
        view = await _view(request, row)
        if action == "dismiss":
            if not view["update_available"] or body["version"] != view["latest_version"]:
                return failure("pc_update_not_available", 409)
            if not await store.set_helper_update_preference(user_id=uid, link_id=row["link_id"],
                                                           dismissed_version=view["latest_version"]):
                return failure("pc_link_not_found", 404)
            return response({"ok": True})
        if not view["online"]:
            return failure("pc_update_offline", 409)
        if action == "update" and not view["update_available"]:
            return failure("pc_update_not_available", 409)
        # A shared node cannot have two competing updater preferences. It is
        # managed only by the single current owner of the local helper.
        scope = await store.device_scope(device_id=row["mesh_node_id"])
        if not isinstance(scope, dict) or scope.get("account_refs") != [uid]:
            return failure("pc_update_owner_required", 403)
        owner = await _owner(request)
        if isinstance(owner, JSONResponse):
            return owner
        session, owner_id, workspace = owner
        if owner_id != uid:
            return failure("pc_update_owner_required", 403)
        target, denial = await _dispatch_target(request, session=session, uid=uid, link=row)
        if denial is not None:
            return denial
        command = control_command(auto=body["enabled"]) if action == "auto" else control_command(version=view["latest_version"])
        run = await _stage_run(request, uid=uid, workspace_id=workspace, note="PC 연결 업데이트 설정")
        if isinstance(run, JSONResponse):
            return run
        result = await dispatch_oracle_mesh_command_intent(
            request, command=command, wire={"run_id": run[0], "device_id": row["mesh_node_id"], "confirmed": True},
            trusted_owner=owner, files_target=target, user_mode=True, helper_update_control=True,
        )
        if result.status_code == 200 and action == "auto":
            if not await store.set_helper_update_preference(user_id=uid, link_id=row["link_id"], auto=body["enabled"]):
                return failure("pc_link_not_found", 404)
        return await _staged(result, run=run)
    except Exception:
        return failure("pc_update_unavailable", 503)


def register_helper_update_routes(routes):
    routes.extend([Route(PATH, list_updates, methods=["GET"]), Route(_LINK, change_update, methods=["POST"])])
