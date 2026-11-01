"""Forward authenticated Mesh drive observations into the existing COM2 queue.

The queue supplies the active paired targets before any PC is queried. A
snapshot changes metadata only: it does not add roots, grants or PC commands.
Failed delivery remains retryable, and a failed probe is never an empty disk
list. No credential or customer metadata is logged by this background loop.
"""
from __future__ import annotations

import json
import threading

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.pc_drive_inventory import validate_drive_inventory


DRIVES_PATH = "/api/claw/connector/mesh-reads/drives"
DRIVE_TARGETS_PATH = DRIVES_PATH + "/targets"
# The user explicitly selected a 30-second comparison fallback.
DRIVE_REFRESH_SECONDS = 30


class MeshDriveReporter:
    def __init__(self, *, post, source, may_report=None):
        self._post = post
        self._source = source
        self._may_report = may_report
        self._accepted = {}
        self._stop = threading.Event()
        self._thread = None

    def tick(self):
        """One comparison/report round, also used by the simulated end-to-end test."""
        reported = 0
        try:
            if self._may_report is not None and not self._may_report():
                return reported
            status, envelope = self._post(DRIVE_TARGETS_PATH, {})
            if status != 200 or not isinstance(envelope, dict) or envelope.get("ok") is not True:
                return reported
            targets = envelope.get("device_ids")
            if not isinstance(targets, list) or any(not is_pc_device_id(item) for item in targets):
                return reported
            allowed = set(targets)
            self._accepted = {key: value for key, value in self._accepted.items() if key in allowed}
            if not allowed:
                return reported
            rows = self._source(sorted(allowed))
            seen = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"device_id", "drives"}:
                    continue
                node = row["device_id"]
                if not isinstance(node, str) or node not in allowed or node in seen:
                    continue
                seen.add(node)
                try:
                    drives = validate_drive_inventory(row["drives"])
                except (TypeError, ValueError):
                    continue
                fingerprint = json.dumps(drives, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if self._accepted.get(node) == fingerprint:
                    continue
                try:
                    status, ack = self._post(DRIVES_PATH, {"device_id": node, "drives": drives})
                except Exception:
                    continue
                if status == 200 and isinstance(ack, dict) and ack.get("ok") is True:
                    self._accepted[node] = fingerprint
                    reported += 1
        except Exception:
            # A disconnected PC or a temporary inventory failure must not stop
            # the command lane or erase the last successfully observed disks.
            pass
        return reported

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def work():
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(DRIVE_REFRESH_SECONDS)

        self._thread = threading.Thread(target=work, name="mesh-drive-inventory", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
