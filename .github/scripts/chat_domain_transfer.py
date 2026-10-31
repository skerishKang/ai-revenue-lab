"""Shared custom-domain transfer and guarded recovery. No live calls at import."""
from __future__ import annotations
import re


class TransferError(Exception):
    def __init__(self, stage, owner):
        self.stage, self.owner = stage, owner
        super().__init__(stage)


def read_owner(read_rows, host, zone=None):
    """Return a safe owner name, ABSENT, or UNKNOWN; never expose raw errors."""
    try:
        rows = read_rows()
        if not isinstance(rows, list):
            return "UNKNOWN"
        matches = [row for row in rows if isinstance(row, dict) and row.get("hostname") == host]
        if not matches:
            return "ABSENT"
        if len(matches) != 1 or (zone is not None and matches[0].get("zone_id") != zone):
            return "UNKNOWN"
        service = matches[0].get("service")
        if not isinstance(service, str) or not re.fullmatch(r"[a-z0-9-]{1,100}", service):
            return "UNKNOWN"
        return service
    except Exception:
        return "UNKNOWN"


def transfer(*, host, before, target, read_rows, mutate, report):
    """A single DELETE then PUT; recovery only when absence is established."""
    source, zone = before["service"], before["zone_id"]

    def observe():
        return read_owner(read_rows, host, zone)

    def stop(stage):
        owner = observe()
        report(stage, owner)
        raise TransferError(stage, owner) from None

    domain_id = before.get("id", "")
    if not isinstance(domain_id, str) or not re.fullmatch(r"[0-9a-f]{32,64}", domain_id):
        stop("domain_id_invalid")
    try:
        mutate("DELETE", "/workers/domains/" + domain_id, None)
    except Exception:
        stop("delete_failed")
    if observe() != "ABSENT":
        stop("detach_unverified")

    payload = {"hostname": host, "service": target, "zone_id": zone,
               "enabled": True, "previews_enabled": False}
    def recover_if_absent(owner):
        if owner != "ABSENT":
            report("attach_failed", owner)
            raise TransferError("attach_failed", owner) from None
        recovery_payload = {**payload, "service": source}
        try:
            mutate("PUT", "/workers/domains", recovery_payload)
        except Exception:
            stop("recovery_failed")
        owner = observe()
        report("attach_failed_recovery", owner)
        raise TransferError("attach_failed_recovered" if owner == source
                            else "recovery_unverified", owner) from None

    try:
        mutate("PUT", "/workers/domains", payload)
    except Exception:
        # A failed response can still represent a successful attach.
        recover_if_absent(observe())
    owner = observe()
    if owner == "ABSENT":
        recover_if_absent(owner)
    if owner != target:
        report("target_unverified", owner)
        raise TransferError("target_unverified", owner)
    return owner
