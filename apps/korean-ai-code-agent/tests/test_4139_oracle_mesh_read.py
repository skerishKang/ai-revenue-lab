"""#4139 — Oracle management-host MeshCentral read executor (product path).

No broker, no MeshCentral server, no resident: ownership matching, package
gates and the injected-port execution boundary only.
"""
from __future__ import annotations

import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_meshcentral_private_reader import MeshCentralReadRefused
from kagent.local_agent_oracle_mesh_read import (
    MAX_ORACLE_MESH_READ_BYTES,
    OracleMeshReadCommand,
    OracleMeshReadTarget,
    build_oracle_mesh_result_package,
    execute_oracle_mesh_read,
    verify_oracle_mesh_ownership,
    verify_oracle_mesh_result_package,
)

ACCOUNT = "owner.account.1"
DEVICE = "22c584bb802864540dc897a6cab4e934"
BINDING = "bind.oracle.trial.1"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
ROOT = "meshcentral_private_trial"
RELATIVE = "meshcentral-padiem-trial.txt"
FINGERPRINT = hashlib.sha256(b"oracle-trial-request").hexdigest()

LIVE_TEXT = (
    b"PADIEM MESHCENTRAL SINGLE-PC TXT TEST\n"
    b"DATE=2026-10-16\n"
    b"HOST=COM1\n"
    b"TEST_CASE=mesh-agent-read-and-return\n"
    b"END_OF_FILE\n"
)


def _target(**overrides):
    fields = {
        "account_ref": ACCOUNT, "device_id": DEVICE, "binding_ref": BINDING,
        "node_ref": NODE, "root_ref": ROOT, "path_relative": RELATIVE,
    }
    fields.update(overrides)
    return OracleMeshReadTarget(**fields)


def _command(**overrides):
    fields = {
        "command_id": "cmd.oracle.1", "run_id": "run.oracle.1",
        "tool_request_ref": "tool.oracle.1", "request_id": "req.oracle.1",
        "revision_ref": "rev.oracle.1", "evidence_ref": "ev.oracle.1",
        "request_fingerprint": FINGERPRINT,
    }
    fields.update(overrides)
    return OracleMeshReadCommand(**fields)


class OwnershipTests(unittest.TestCase):
    def test_exact_quadruple_matches_one_target(self):
        matched = verify_oracle_mesh_ownership(
            targets=[_target()], account_ref=ACCOUNT, device_id=DEVICE,
            binding_ref=BINDING, node_ref=NODE, root_ref=ROOT,
            path_relative=RELATIVE,
        )
        self.assertEqual(matched.node_ref, NODE)

    def test_partial_matches_fail_closed(self):
        targets = [_target()]
        for field, wrong in (
            ("account_ref", "intruder.account.9"),
            ("device_id", "deadbeefdeadbeefdeadbeefdeadbeef"),
            ("binding_ref", "bind.other.2"),
            ("node_ref", "othernode@otherserver"),
            ("root_ref", "other_root"),
            ("path_relative", "other.txt"),
        ):
            kwargs = {
                "targets": targets, "account_ref": ACCOUNT, "device_id": DEVICE,
                "binding_ref": BINDING, "node_ref": NODE, "root_ref": ROOT,
                "path_relative": RELATIVE,
            }
            kwargs[field] = wrong
            with self.assertRaises(ContractError, msg=field):
                verify_oracle_mesh_ownership(**kwargs)

    def test_no_targets_or_two_matches_refused(self):
        kwargs = {
            "account_ref": ACCOUNT, "device_id": DEVICE, "binding_ref": BINDING,
            "node_ref": NODE, "root_ref": ROOT, "path_relative": RELATIVE,
        }
        with self.assertRaises(ContractError):
            verify_oracle_mesh_ownership(targets=[], **kwargs)
        with self.assertRaises(ContractError):
            verify_oracle_mesh_ownership(targets=[_target(), _target()], **kwargs)


class ExecutionBoundaryTests(unittest.TestCase):
    def test_executor_uses_the_injected_port_only(self):
        seen = {}

        class _Port:
            def read_bytes(self, *, node_ref, file_path, timeout_seconds):
                seen.update(
                    node_ref=node_ref, file_path=file_path,
                    timeout_seconds=timeout_seconds,
                )
                return LIVE_TEXT

        body = execute_oracle_mesh_read(
            port=_Port(), node_ref=NODE,
            file_path="C:\\Trial\\meshcentral-padiem-trial.txt",
            timeout_seconds=120,
        )
        self.assertEqual(body, LIVE_TEXT)
        self.assertEqual(seen["node_ref"], NODE)
        self.assertEqual(seen["timeout_seconds"], 120)

    def test_executor_requires_a_read_port(self):
        with self.assertRaises(ContractError):
            execute_oracle_mesh_read(
                port=object(), node_ref=NODE, file_path="C:\\x.txt",
            )


class ResultPackageTests(unittest.TestCase):
    def test_live_bytes_become_a_verifiable_package(self):
        package = build_oracle_mesh_result_package(
            command=_command(), content=bytes(LIVE_TEXT),
        )
        self.assertEqual(package["content_bytes"], 113)
        self.assertEqual(
            package["content_sha256"],
            "a8c2ead9ce5bb71a8e2625a482dd16be0196ef92df2af4e83156db45622b473c",
        )
        self.assertEqual(
            verify_oracle_mesh_result_package(package=package, command=_command()),
            LIVE_TEXT.decode("utf-8"),
        )

    def test_only_clean_executions_become_packages(self):
        for termination, exit_code in (
            ("cancelled", 0), ("timed_out", 0), ("exited", 1),
        ):
            with self.assertRaises(MeshCentralReadRefused):
                build_oracle_mesh_result_package(
                    command=_command(), content=b"ok\n",
                    termination=termination, exit_code=exit_code,
                )

    def test_oversize_is_refused_never_truncated(self):
        with self.assertRaises(MeshCentralReadRefused):
            build_oracle_mesh_result_package(
                command=_command(),
                content=b"x" * (MAX_ORACLE_MESH_READ_BYTES + 1),
            )

    def test_cross_command_packages_refused(self):
        package = build_oracle_mesh_result_package(
            command=_command(), content=b"ok\n",
        )
        with self.assertRaises(ContractError):
            verify_oracle_mesh_result_package(
                package=package, command=_command(command_id="cmd.other.9"),
            )
        tampered = dict(package)
        tampered["content_utf8"] = "tampered\n"
        with self.assertRaises(ContractError):
            verify_oracle_mesh_result_package(package=tampered, command=_command())


if __name__ == "__main__":
    unittest.main()
