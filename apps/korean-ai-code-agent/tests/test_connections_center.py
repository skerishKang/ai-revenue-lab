from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.connections_center import (
    CAPABILITY_ESCALATION_SILENT,
    REAL_CONNECTIONS_CENTER_BACKEND_WIRED,
    REVOCATION_ONE_PLACE,
    SECRET_VALUE_VISIBLE,
    UI_ACTION_AUTHORITY,
    AccountExposure,
    CapabilityEscalationReview,
    ConnectionStatus,
    ConnectionsCenterActivity,
    ConnectionsDevicesCenterSnapshot,
    ConnectorAccessClass,
    ConnectorAccountCard,
    DeviceCompatibility,
    EscalationSensitivity,
    EscalationTargetKind,
    LocalAgentDeviceCard,
    derive_connector_access_class,
)
from kagent.connector_trust import (
    ConnectorBindingProjection,
    ConnectorHealthProjection,
    ConnectorHealthState,
)
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_management import LocalAgentActivitySummary, LocalAgentManagementSnapshot
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from kagent.local_agent_permissions import default_device_permission_profile

NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


class ConnectionsCenterFixture(unittest.TestCase):
    def connector_binding(
        self,
        *,
        binding_ref: str = "binding_drive_1",
        connector_id: str = "google-drive",
        capabilities: tuple[str, ...] = ("files.read",),
        expires_at: datetime | None = None,
    ) -> ConnectorBindingProjection:
        return ConnectorBindingProjection(
            binding_ref=binding_ref,
            connector_id=connector_id,
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
            granted_scopes=("drive.file.read",),
            granted_capabilities=capabilities,
            issued_at=NOW - timedelta(days=1),
            updated_at=NOW - timedelta(hours=1),
            expires_at=expires_at,
        )

    def connector_health(
        self,
        binding_ref: str = "binding_drive_1",
        *,
        state: ConnectorHealthState = ConnectorHealthState.HEALTHY,
        observed_at: datetime | None = None,
    ) -> ConnectorHealthProjection:
        return ConnectorHealthProjection(
            binding_ref=binding_ref,
            state=state,
            observed_at=observed_at or NOW - timedelta(seconds=20),
            freshness_seconds=120,
            health_ref="health_1",
        )

    def activity(
        self,
        *,
        request_id: str = "request_1",
        run_id: str = "run_1",
        ended_at: datetime | None = None,
    ) -> LocalAgentActivitySummary:
        ended = ended_at or NOW - timedelta(minutes=4)
        return LocalAgentActivitySummary(
            request_id=request_id,
            run_id=run_id,
            root_ref="root_padiem",
            executable_profile_ref="python_profile",
            termination="exited",
            started_at=ended - timedelta(minutes=1),
            ended_at=ended,
            exit_code=0,
            dirty_worktree_before=False,
            dirty_worktree_after=False,
        )

    def local_snapshot(
        self,
        *,
        state: DeviceLifecycle = DeviceLifecycle.ONLINE,
        recent_activity: tuple[LocalAgentActivitySummary, ...] | None = None,
    ) -> LocalAgentManagementSnapshot:
        device = LocalAgentDeviceProfile(
            device_id="device_1",
            workspace_ref="workspace_1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(
                LocalRoot(root_ref="root_padiem", windows_path=r"E:\padiem-claw"),
                LocalRoot(root_ref="root_work", windows_path=r"G:\Ddrive\BatangD\task"),
            ),
        )
        binding = DeviceBinding(
            device_id=device.device_id,
            binding_ref="device_binding_1",
            account_ref="account_1",
            workspace_ref=device.workspace_ref,
            credential_ref="credential_ref_hidden",
            credential_generation=2,
            issued_at=NOW - timedelta(days=1),
            credential_expires_at=NOW + timedelta(days=29),
            state=state,
        )
        permissions = default_device_permission_profile(device=device)
        activities = recent_activity if recent_activity is not None else (self.activity(),)
        return LocalAgentManagementSnapshot(
            device_name="Office Windows",
            device=device,
            binding=binding,
            permissions=permissions,
            recent_activity=activities,
        )

    def connector_card(self, *, now: datetime = NOW) -> ConnectorAccountCard:
        return ConnectorAccountCard(
            service_label="Google Drive",
            binding=self.connector_binding(),
            health=self.connector_health(),
            now=now,
            last_successful_probe_at=NOW - timedelta(seconds=20),
        )

    def device_card(
        self,
        *,
        snapshot: LocalAgentManagementSnapshot | None = None,
        last_seen_at: datetime | None = None,
    ) -> LocalAgentDeviceCard:
        return LocalAgentDeviceCard(
            snapshot=snapshot or self.local_snapshot(),
            arch="x86_64",
            client_version="1.0.0",
            compatibility=DeviceCompatibility.CURRENT,
            last_seen_at=last_seen_at if last_seen_at is not None else NOW - timedelta(seconds=15),
        )


class ConnectorCardTests(ConnectionsCenterFixture):
    def test_connected_card_exposes_scope_health_access_and_no_secrets(self):
        binding = self.connector_binding(capabilities=("files.read", "files.update"))
        card = ConnectorAccountCard(
            service_label="Google Drive",
            binding=binding,
            health=self.connector_health(),
            now=NOW,
            last_successful_probe_at=NOW - timedelta(seconds=20),
            last_material_action=ConnectionsCenterActivity(
                action_ref="action_1",
                action_name="files.update",
                target_ref="file_1",
                occurred_at=NOW - timedelta(minutes=10),
                evidence_ref="evidence_1",
                material=True,
            ),
        )
        rendered = card.safe_dict()
        self.assertEqual(rendered["status"], ConnectionStatus.CONNECTED.value)
        self.assertEqual(rendered["access_class"], ConnectorAccessClass.READ_WRITE.value)
        self.assertTrue(rendered["write_capability_visible"])
        self.assertEqual(rendered["last_material_action"]["evidence_ref"], "evidence_1")
        self.assertFalse(rendered["ui_action_authority"])
        self.assertFalse(rendered["raw_access_token"])
        self.assertFalse(rendered["raw_refresh_token"])
        self.assertFalse(rendered["raw_client_secret"])
        self.assertFalse(rendered["raw_api_key"])

    def test_expired_stale_degraded_and_unavailable_are_visible_action_states(self):
        expired = ConnectorAccountCard(
            service_label="Drive",
            binding=self.connector_binding(expires_at=NOW - timedelta(seconds=1)),
            health=self.connector_health(),
            now=NOW,
        )
        self.assertEqual(expired.status, ConnectionStatus.EXPIRED)
        self.assertTrue(expired.safe_dict()["action_required_visible"])
        self.assertIn("reconnect", expired.safe_dict()["management_actions"])

        stale = ConnectorAccountCard(
            service_label="Drive",
            binding=self.connector_binding(),
            health=self.connector_health(observed_at=NOW - timedelta(minutes=10)),
            now=NOW,
        )
        self.assertEqual(stale.status, ConnectionStatus.ACTION_REQUIRED)

        degraded = ConnectorAccountCard(
            service_label="Drive",
            binding=self.connector_binding(),
            health=self.connector_health(state=ConnectorHealthState.DEGRADED),
            now=NOW,
        )
        self.assertEqual(degraded.status, ConnectionStatus.ACTION_REQUIRED)

        unavailable = ConnectorAccountCard(
            service_label="Drive",
            binding=self.connector_binding(),
            health=self.connector_health(state=ConnectorHealthState.UNAVAILABLE),
            now=NOW,
        )
        self.assertEqual(unavailable.status, ConnectionStatus.UNAVAILABLE)

    def test_shared_and_public_accounts_carry_explicit_warning(self):
        shared = ConnectorAccountCard(
            service_label="Slack",
            binding=self.connector_binding(connector_id="slack"),
            health=self.connector_health(),
            now=NOW,
            account_exposure=AccountExposure.SHARED,
        ).safe_dict()
        public = ConnectorAccountCard(
            service_label="Public Service",
            binding=self.connector_binding(binding_ref="binding_public", connector_id="public-service"),
            health=self.connector_health("binding_public"),
            now=NOW,
            account_exposure=AccountExposure.PUBLIC,
        ).safe_dict()
        self.assertEqual(shared["account_warning"], "shared_account_scope_review_required")
        self.assertEqual(public["account_warning"], "public_account_high_risk_scope_review_required")

    def test_access_class_is_conservative_for_material_capabilities(self):
        self.assertEqual(derive_connector_access_class(("files.read",)), ConnectorAccessClass.READ_ONLY)
        self.assertEqual(derive_connector_access_class(("files.update",)), ConnectorAccessClass.READ_WRITE)
        self.assertEqual(derive_connector_access_class(("production.deploy",)), ConnectorAccessClass.MATERIAL_WRITE)
        self.assertEqual(derive_connector_access_class(("records.delete",)), ConnectorAccessClass.MATERIAL_WRITE)


class LocalAgentCardTests(ConnectionsCenterFixture):
    def test_device_card_composes_existing_management_snapshot(self):
        rendered = self.device_card().safe_dict()
        self.assertEqual(rendered["device_name"], "Office Windows")
        self.assertEqual(rendered["paired_account_ref"], "account_1")
        self.assertEqual(rendered["status"], DeviceLifecycle.ONLINE.value)
        self.assertEqual(len(rendered["roots"]), 2)
        self.assertTrue(rendered["roots"][0]["capabilities"])
        self.assertIsNotNone(rendered["last_local_action"])
        self.assertIn("disable", rendered["management_actions"])
        self.assertIn("revoke", rendered["management_actions"])
        self.assertIn("delete", rendered["management_actions"])
        self.assertFalse(rendered["ui_action_authority"])
        self.assertFalse(rendered["raw_device_credential"])

    def test_device_card_chooses_latest_activity_by_timestamp(self):
        older = self.activity(
            request_id="request_old",
            run_id="run_old",
            ended_at=NOW - timedelta(minutes=20),
        )
        newer = self.activity(
            request_id="request_new",
            run_id="run_new",
            ended_at=NOW - timedelta(minutes=2),
        )
        snapshot = self.local_snapshot(recent_activity=(older, newer))
        rendered = self.device_card(snapshot=snapshot).safe_dict()
        self.assertEqual(rendered["last_local_action"]["request_id"], "request_new")
        self.assertEqual(rendered["last_local_action"]["run_id"], "run_new")

    def test_update_required_lifecycle_cannot_be_hidden(self):
        snapshot = self.local_snapshot(state=DeviceLifecycle.UPDATE_REQUIRED)
        with self.assertRaises(ContractError):
            LocalAgentDeviceCard(
                snapshot=snapshot,
                arch="x86_64",
                client_version="0.9.0",
                compatibility=DeviceCompatibility.CURRENT,
                last_seen_at=NOW,
            )
        card = LocalAgentDeviceCard(
            snapshot=snapshot,
            arch="x86_64",
            client_version="0.9.0",
            compatibility=DeviceCompatibility.UPDATE_REQUIRED,
            last_seen_at=NOW,
        )
        self.assertIn("update", card.safe_dict()["management_actions"])


class CapabilityEscalationTests(unittest.TestCase):
    def test_pending_widening_is_visible_but_cannot_authorize_itself(self):
        review = CapabilityEscalationReview(
            review_ref="review_1",
            target_kind=EscalationTargetKind.CONNECTOR,
            target_ref="binding_drive_1",
            current_scope=("files.read",),
            requested_scope=("files.read", "files.update"),
            reason="Allow reviewed document updates for this workspace.",
            sensitivity=EscalationSensitivity.SENSITIVE,
            requested_at=NOW,
        )
        rendered = review.safe_dict()
        self.assertEqual(rendered["additions"], ["files.update"])
        self.assertTrue(rendered["widens_capability"])
        self.assertTrue(rendered["approval_required"])
        self.assertFalse(rendered["trusted_approval_present"])
        self.assertFalse(rendered["ui_may_apply_without_trusted_authority"])
        with self.assertRaises(ContractError):
            review.require_authorized_widening()

    def test_trusted_approval_ref_satisfies_apply_guard_but_ui_remains_non_authoritative(self):
        review = CapabilityEscalationReview(
            review_ref="review_2",
            target_kind=EscalationTargetKind.LOCAL_AGENT,
            target_ref="device_1",
            current_scope=("filesystem.read",),
            requested_scope=("filesystem.read", "filesystem.write"),
            reason="Enable writes only inside the selected project root.",
            sensitivity=EscalationSensitivity.HIGH,
            requested_at=NOW,
            trusted_approval_ref="approval_1",
        )
        review.require_authorized_widening()
        rendered = review.safe_dict()
        self.assertTrue(rendered["trusted_approval_present"])
        self.assertFalse(rendered["ui_may_apply_without_trusted_authority"])

    def test_narrowing_needs_no_widening_approval(self):
        review = CapabilityEscalationReview(
            review_ref="review_3",
            target_kind=EscalationTargetKind.CONNECTOR,
            target_ref="binding_drive_1",
            current_scope=("files.read", "files.update"),
            requested_scope=("files.read",),
            reason="Reduce the connector to read-only access.",
            sensitivity=EscalationSensitivity.STANDARD,
            requested_at=NOW,
        )
        review.require_authorized_widening()
        self.assertFalse(review.widens_capability)
        self.assertEqual(review.removals, ("files.update",))


class AggregateCenterTests(ConnectionsCenterFixture):
    def test_center_places_connector_and_device_revocation_in_one_surface(self):
        center = ConnectionsDevicesCenterSnapshot(
            workspace_ref="workspace_1",
            generated_at=NOW,
            connectors=(self.connector_card(),),
            devices=(self.device_card(),),
        )
        rendered = center.safe_dict()
        self.assertEqual(len(rendered["connectors"]), 1)
        self.assertEqual(len(rendered["devices"]), 1)
        self.assertEqual(
            {item["kind"] for item in rendered["revocation_targets"]},
            {"connector", "local_agent"},
        )
        self.assertTrue(rendered["revocation_one_place"])
        self.assertFalse(rendered["secret_value_visible"])
        self.assertFalse(rendered["ui_action_authority"])
        self.assertFalse(rendered["real_backend_wired"])

    def test_workspace_mismatch_fails_closed(self):
        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_other",
                generated_at=NOW,
                connectors=(self.connector_card(),),
                devices=(),
            )

    def test_escalation_target_must_exist_in_center(self):
        unknown_connector = CapabilityEscalationReview(
            review_ref="review_unknown_connector",
            target_kind=EscalationTargetKind.CONNECTOR,
            target_ref="binding_missing",
            current_scope=("files.read",),
            requested_scope=("files.read", "files.update"),
            reason="Synthetic integrity check.",
            sensitivity=EscalationSensitivity.SENSITIVE,
            requested_at=NOW,
        )
        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_1",
                generated_at=NOW,
                connectors=(self.connector_card(),),
                devices=(self.device_card(),),
                escalation_reviews=(unknown_connector,),
            )

        unknown_device = CapabilityEscalationReview(
            review_ref="review_unknown_device",
            target_kind=EscalationTargetKind.LOCAL_AGENT,
            target_ref="device_missing",
            current_scope=("filesystem.read",),
            requested_scope=("filesystem.read", "filesystem.write"),
            reason="Synthetic integrity check.",
            sensitivity=EscalationSensitivity.HIGH,
            requested_at=NOW,
        )
        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_1",
                generated_at=NOW,
                connectors=(self.connector_card(),),
                devices=(self.device_card(),),
                escalation_reviews=(unknown_device,),
            )

    def test_future_observations_are_rejected_by_center(self):
        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_1",
                generated_at=NOW,
                connectors=(self.connector_card(now=NOW + timedelta(seconds=1)),),
                devices=(),
            )

        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_1",
                generated_at=NOW,
                connectors=(),
                devices=(self.device_card(last_seen_at=NOW + timedelta(seconds=1)),),
            )

        future_activity = self.activity(
            request_id="request_future",
            run_id="run_future",
            ended_at=NOW + timedelta(seconds=1),
        )
        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_1",
                generated_at=NOW,
                connectors=(),
                devices=(self.device_card(snapshot=self.local_snapshot(recent_activity=(future_activity,))),),
            )

        future_review = CapabilityEscalationReview(
            review_ref="review_future",
            target_kind=EscalationTargetKind.CONNECTOR,
            target_ref="binding_drive_1",
            current_scope=("files.read",),
            requested_scope=("files.read", "files.update"),
            reason="Synthetic future timestamp check.",
            sensitivity=EscalationSensitivity.SENSITIVE,
            requested_at=NOW + timedelta(seconds=1),
        )
        with self.assertRaises(ContractError):
            ConnectionsDevicesCenterSnapshot(
                workspace_ref="workspace_1",
                generated_at=NOW,
                connectors=(self.connector_card(),),
                devices=(),
                escalation_reviews=(future_review,),
            )

    def test_valid_escalation_target_is_accepted_and_remains_non_authoritative(self):
        review = CapabilityEscalationReview(
            review_ref="review_valid",
            target_kind=EscalationTargetKind.CONNECTOR,
            target_ref="binding_drive_1",
            current_scope=("files.read",),
            requested_scope=("files.read", "files.update"),
            reason="Synthetic visible pending review.",
            sensitivity=EscalationSensitivity.SENSITIVE,
            requested_at=NOW,
        )
        center = ConnectionsDevicesCenterSnapshot(
            workspace_ref="workspace_1",
            generated_at=NOW,
            connectors=(self.connector_card(),),
            devices=(),
            escalation_reviews=(review,),
        )
        rendered = center.safe_dict()["escalation_reviews"][0]
        self.assertTrue(rendered["approval_required"])
        self.assertFalse(rendered["ui_may_apply_without_trusted_authority"])

    def test_repository_nonclaims_are_explicit(self):
        self.assertFalse(REAL_CONNECTIONS_CENTER_BACKEND_WIRED)
        self.assertFalse(SECRET_VALUE_VISIBLE)
        self.assertFalse(UI_ACTION_AUTHORITY)
        self.assertFalse(CAPABILITY_ESCALATION_SILENT)
        self.assertTrue(REVOCATION_ONE_PLACE)


if __name__ == "__main__":
    unittest.main()
