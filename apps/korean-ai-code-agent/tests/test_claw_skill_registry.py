"""#2822: Claw Skill Registry + capability manifest contract tests.

Deterministic, provider-free and network-free. No filesystem path, credential
or provider payload is required to prove the contract.
"""

from __future__ import annotations

import unittest

from kagent.claw_skill_registry import (
    ACCEPTANCE,
    CAPABILITY_FILE_INSPECT,
    CAPABILITY_HWP_CONVERT_TO_HWPX,
    CAPABILITY_HWP_READ,
    CAPABILITY_HWPX_CREATE,
    CAPABILITY_HWPX_EDIT,
    CAPABILITY_HWPX_READ,
    CAPABILITY_HWPX_TEMPLATE_FILL,
    CAPABILITY_HWPX_VALIDATE,
    CAPABILITY_IMAGE_INSPECT,
    CAPABILITY_IMAGE_OCR,
    CAPABILITY_IMAGE_TRANSFORM,
    CAPABILITY_PDF_CREATE,
    CAPABILITY_PDF_INSPECT,
    CAPABILITY_PDF_OCR,
    CAPABILITY_PDF_READ,
    CAPABILITY_PDF_TRANSFORM,
    MAX_INPUT_BYTES_LIMIT,
    MAX_PAGES_OR_ARCHIVE_EXPANSION_LIMIT,
    REQUIRED_MANIFEST_FIELD_NAMES,
    REQUIRED_MANIFEST_FIELDS,
    RESERVED_CAPABILITY_IDS,
    FilesystemScope,
    SideEffectClass,
    SkillInvocationRequest,
    SkillManifest,
    SkillRegistryContractError,
    authorize_composed_member,
    authorize_invocation,
    build_claw_skill_registry,
    compose_skills,
    is_reserved_capability,
)

PDF_MIME = "application/pdf"
HWPX_MIME = "application/hwp+zip"
IMAGE_MIME = "image/png"
HWP_MIME = "application/x-ole-storage"
ANY_MIME = "application/octet-stream"


def request(
    *,
    skill_id: str = "skill:claw:pdf-reader@1",
    actual_input_mime: str = PDF_MIME,
    wants_network: bool = False,
    wants_provider: bool = False,
    wants_sandbox: bool = False,
    wants_filesystem_scope: FilesystemScope = FilesystemScope.NONE,
) -> SkillInvocationRequest:
    return SkillInvocationRequest(
        skill_id=skill_id,
        actual_input_mime=actual_input_mime,
        wants_network=wants_network,
        wants_provider=wants_provider,
        wants_sandbox=wants_sandbox,
        wants_filesystem_scope=wants_filesystem_scope,
    )


def manifest(
    *,
    skill_id: str = "skill:claw:pdf-reader@1",
    version: str = "1.0.0",
    capability_id: str = CAPABILITY_PDF_READ,
    input_mime: tuple[str, ...] = (PDF_MIME,),
    output_mime: tuple[str, ...] = (PDF_MIME,),
    filesystem_scope: FilesystemScope = FilesystemScope.SCOPED_READ,
    network_required: bool = False,
    provider_required: bool = False,
    sandbox_required: bool = False,
    side_effect_class: SideEffectClass = SideEffectClass.NONE,
    approval_required: bool = False,
    max_input_bytes: int = 2 * 1024 * 1024,
    max_pages_or_archive_expansion: int = 64,
    provenance: str = "padiem-claw:builtin",
    license: str = "LicenseRef-Padiem-Internal",
) -> SkillManifest:
    return SkillManifest(
        skill_id=skill_id,
        version=version,
        capability_id=capability_id,
        input_mime=input_mime,
        output_mime=output_mime,
        filesystem_scope=filesystem_scope,
        network_required=network_required,
        provider_required=provider_required,
        sandbox_required=sandbox_required,
        side_effect_class=side_effect_class,
        approval_required=approval_required,
        max_input_bytes=max_input_bytes,
        max_pages_or_archive_expansion=max_pages_or_archive_expansion,
        provenance=provenance,
        license=license,
    )


class ReservedCapabilityTests(unittest.TestCase):
    def test_initial_capability_names_are_reserved(self) -> None:
        expected = {
            "pdf.inspect",
            "pdf.read",
            "pdf.ocr",
            "pdf.create",
            "pdf.transform",
            "image.inspect",
            "image.ocr",
            "image.transform",
            "hwpx.read",
            "hwpx.create",
            "hwpx.edit",
            "hwpx.template_fill",
            "hwpx.validate",
            "hwp.read",
            "hwp.convert_to_hwpx",
            "file.inspect",
        }
        self.assertEqual(RESERVED_CAPABILITY_IDS, expected)
        for capability_id in expected:
            self.assertTrue(is_reserved_capability(capability_id))
        self.assertFalse(is_reserved_capability("shell.exec"))
        self.assertFalse(is_reserved_capability(""))


class ManifestContractTests(unittest.TestCase):
    def test_manifest_is_typed_and_acceptance_tokens_are_pinned(self) -> None:
        entry = manifest()
        self.assertIsInstance(entry.filesystem_scope, FilesystemScope)
        self.assertIsInstance(entry.side_effect_class, SideEffectClass)
        self.assertEqual(
            ACCEPTANCE,
            {
                "SKILL_REGISTRY_CANONICAL": "YES",
                "CAPABILITY_MANIFEST_TYPED": "YES",
                "REQUIRED_MANIFEST_FIELDS": "14",
                "UNKNOWN_SKILL_FAIL_CLOSED": "YES",
                "DUPLICATE_ID_VERSION_REJECTED": "YES",
                "MIME_MISMATCH_REJECTED": "YES",
                "UNDECLARED_NETWORK_AUTHORITY_REJECTED": "YES",
                "UNDECLARED_PROVIDER_AUTHORITY_REJECTED": "YES",
                "UNDECLARED_SANDBOX_AUTHORITY_REJECTED": "YES",
                "FILESYSTEM_SCOPE_WIDENING_REJECTED": "YES",
                "SILENT_AUTHORITY_ESCALATION": "NO",
                "AUTHORITY_INHERITANCE": "NO",
                "COMPOSITION_AUTHORITY_WIDENING": "NO",
                "READONLY_PROVIDER_SIDE_EFFECT_NONE": "YES",
                "ARBITRARY_SHELL_FROM_SKILL_ID": "NO",
                "SAFE_PROJECTION": "PASS",
                "PARSER_IMPLEMENTATION": "0",
                "OSS_ADOPTION": "0",
                "PROVIDER_CALLS": "0",
                "PRODUCTION_MUTATION": "0",
            },
        )

    def test_required_manifest_fields_are_exactly_the_issue_fourteen(self) -> None:
        self.assertEqual(REQUIRED_MANIFEST_FIELDS, 14)
        self.assertEqual(len(REQUIRED_MANIFEST_FIELD_NAMES), 14)
        self.assertEqual(
            set(REQUIRED_MANIFEST_FIELD_NAMES),
            {
                "skill_id",
                "version",
                "input_mime",
                "output_mime",
                "filesystem_scope",
                "network_required",
                "provider_required",
                "sandbox_required",
                "side_effect_class",
                "approval_required",
                "max_input_bytes",
                "max_pages_or_archive_expansion",
                "provenance",
                "license",
            },
        )
        dataclass_fields = {field.name for field in SkillManifest.__dataclass_fields__.values()}
        self.assertTrue(set(REQUIRED_MANIFEST_FIELD_NAMES) <= dataclass_fields)
        # capability_id is the additional typed discovery key.
        self.assertIn("capability_id", dataclass_fields)

    def test_manifest_required_fields_present_on_instance(self) -> None:
        entry = manifest()
        for name in REQUIRED_MANIFEST_FIELD_NAMES:
            self.assertTrue(hasattr(entry, name), msg=name)

    def test_contract_behaviour_tokens_are_individually_enforced(self) -> None:
        """Each behaviour token has a dedicated fail-closed enforcement path."""

        # DUPLICATE_ID_VERSION_REJECTED
        with self.assertRaises(SkillRegistryContractError) as ctx:
            build_claw_skill_registry([manifest(), manifest(max_input_bytes=4096)])
        self.assertEqual(ctx.exception.code, "duplicate_skill_id_version")

        # MIME_MISMATCH_REJECTED
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.require_input_mime("skill:claw:pdf-reader@1", IMAGE_MIME)
        self.assertEqual(ctx.exception.code, "mime_mismatch")

        # UNDECLARED_NETWORK_AUTHORITY_REJECTED
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_network=True,
                    wants_filesystem_scope=FilesystemScope.SCOPED_READ,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_network_request")

        # UNDECLARED_PROVIDER_AUTHORITY_REJECTED
        network_only = build_claw_skill_registry(
            [
                manifest(
                    network_required=True,
                    provider_required=False,
                    side_effect_class=SideEffectClass.NONE,
                    filesystem_scope=FilesystemScope.NONE,
                )
            ]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                network_only,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_network=True,
                    wants_provider=True,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_provider_request")

        # UNDECLARED_SANDBOX_AUTHORITY_REJECTED
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_sandbox=True,
                    wants_filesystem_scope=FilesystemScope.SCOPED_READ,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_sandbox_request")

        # FILESYSTEM_SCOPE_WIDENING_REJECTED
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_filesystem_scope=FilesystemScope.SCOPED_WRITE,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_filesystem_request")

        # SILENT_AUTHORITY_ESCALATION = NO (narrower request fails closed)
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            )
        self.assertEqual(ctx.exception.code, "missing_filesystem_authority_request")

        # READONLY_PROVIDER_SIDE_EFFECT_NONE = YES
        ro_registry = build_claw_skill_registry(
            [
                manifest(
                    skill_id="skill:claw:pdf-ocr-ro@1",
                    capability_id=CAPABILITY_PDF_OCR,
                    network_required=True,
                    provider_required=True,
                    side_effect_class=SideEffectClass.NONE,
                    approval_required=False,
                    filesystem_scope=FilesystemScope.NONE,
                )
            ]
        )
        ro_grant = authorize_invocation(
            ro_registry,
            SkillInvocationRequest(
                skill_id="skill:claw:pdf-ocr-ro@1",
                actual_input_mime=PDF_MIME,
                wants_network=True,
                wants_provider=True,
                wants_filesystem_scope=FilesystemScope.NONE,
            ),
        )
        self.assertTrue(ro_grant.provider_required)
        self.assertIs(ro_grant.side_effect_class, SideEffectClass.NONE)

        # COMPOSITION_AUTHORITY_WIDENING
        wide = build_claw_skill_registry(
            [
                manifest(filesystem_scope=FilesystemScope.NONE),
                manifest(
                    skill_id="skill:claw:ocr-worker@1",
                    capability_id=CAPABILITY_PDF_OCR,
                    network_required=True,
                    filesystem_scope=FilesystemScope.NONE,
                ),
            ]
        )
        composition = compose_skills(
            wide,
            ["skill:claw:pdf-reader@1", "skill:claw:ocr-worker@1"],
        )
        self.assertTrue(composition.network_required)
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_composed_member(
                wide,
                composition,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_network=True,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_network_request")

        # UNKNOWN_SKILL_FAIL_CLOSED
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.get("skill:claw:ghost@1")
        self.assertEqual(ctx.exception.code, "unknown_skill")

    def test_invalid_skill_id_rejected(self) -> None:
        for bad in (
            "pdf.read",
            "skill:Claw:PDF@1",
            "skill:claw:pdf reader@1",
            "skill:claw:pdf-reader@0",
            "; rm -rf /",
            "$(whoami)",
            "skill:claw:../../etc/passwd@1",
        ):
            with self.subTest(skill_id=bad):
                with self.assertRaises(SkillRegistryContractError) as ctx:
                    manifest(skill_id=bad)
                self.assertEqual(ctx.exception.code, "invalid_capability_manifest")

    def test_invalid_version_rejected(self) -> None:
        for bad in ("1.0", "v1.0.0", "01.0.0", "1.0.0-beta", ""):
            with self.subTest(version=bad), self.assertRaises(SkillRegistryContractError):
                manifest(version=bad)

    def test_provider_requires_network(self) -> None:
        with self.assertRaises(SkillRegistryContractError) as ctx:
            manifest(network_required=False, provider_required=True)
        self.assertEqual(ctx.exception.code, "invalid_capability_manifest")

    def test_external_side_effect_requires_approval(self) -> None:
        with self.assertRaises(SkillRegistryContractError) as ctx:
            manifest(
                side_effect_class=SideEffectClass.EXTERNAL_SIDE_EFFECT,
                approval_required=False,
            )
        self.assertEqual(ctx.exception.code, "invalid_capability_manifest")

    def test_scoped_write_requires_side_effect_class(self) -> None:
        with self.assertRaises(SkillRegistryContractError) as ctx:
            manifest(
                filesystem_scope=FilesystemScope.SCOPED_WRITE,
                side_effect_class=SideEffectClass.NONE,
            )
        self.assertEqual(ctx.exception.code, "invalid_capability_manifest")

    def test_bounds_are_enforced(self) -> None:
        with self.assertRaises(SkillRegistryContractError):
            manifest(max_input_bytes=0)
        with self.assertRaises(SkillRegistryContractError):
            manifest(max_input_bytes=MAX_INPUT_BYTES_LIMIT + 1)
        with self.assertRaises(SkillRegistryContractError):
            manifest(max_pages_or_archive_expansion=0)
        with self.assertRaises(SkillRegistryContractError):
            manifest(max_pages_or_archive_expansion=MAX_PAGES_OR_ARCHIVE_EXPANSION_LIMIT + 1)

    def test_provenance_must_not_be_a_host_path(self) -> None:
        for bad in ("/etc/passwd", "C:\\Windows\\System32", "../secrets", "file:///tmp/x"):
            with self.subTest(provenance=bad), self.assertRaises(SkillRegistryContractError):
                manifest(provenance=bad)

    def test_empty_input_mime_rejected(self) -> None:
        with self.assertRaises(SkillRegistryContractError):
            manifest(input_mime=())


class RegistryDiscoveryTests(unittest.TestCase):
    def test_duplicate_skill_id_version_rejected(self) -> None:
        first = manifest()
        second = manifest(max_input_bytes=4096)
        with self.assertRaises(SkillRegistryContractError) as ctx:
            build_claw_skill_registry([first, second])
        self.assertEqual(ctx.exception.code, "duplicate_skill_id_version")

    def test_duplicate_identity_with_different_content_rejected(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.with_manifest(manifest(max_input_bytes=4096))
        self.assertEqual(ctx.exception.code, "duplicate_skill_id_version")

    def test_same_skill_id_different_version_rejected(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.with_manifest(manifest(version="2.0.0"))
        self.assertEqual(ctx.exception.code, "duplicate_skill_id_version")

    def test_unknown_skill_fails_closed(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.get("skill:claw:not-registered@1")
        self.assertEqual(ctx.exception.code, "unknown_skill")

    def test_unknown_capability_discovery_is_empty_and_require_fails_closed(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        self.assertEqual(registry.discover("shell.exec"), ())
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.require_capability("shell.exec")
        self.assertEqual(ctx.exception.code, "unknown_capability")

    def test_capability_discovery_is_deterministic(self) -> None:
        pdf_inspect = manifest(
            skill_id="skill:claw:pdf-inspector@1",
            capability_id=CAPABILITY_PDF_INSPECT,
        )
        pdf_read = manifest()
        registry = build_claw_skill_registry([pdf_read, pdf_inspect])
        discovered = registry.discover(CAPABILITY_PDF_READ)
        self.assertEqual([item.skill_id for item in discovered], ["skill:claw:pdf-reader@1"])
        self.assertEqual(registry.skill_ids, ("skill:claw:pdf-inspector@1", "skill:claw:pdf-reader@1"))

    def test_ambiguous_capability_fails_closed(self) -> None:
        registry = build_claw_skill_registry(
            [
                manifest(),
                manifest(skill_id="skill:claw:pdf-reader-b@1"),
            ]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.require_capability(CAPABILITY_PDF_READ)
        self.assertEqual(ctx.exception.code, "ambiguous_capability")

    def test_reserved_capability_catalogue_covers_issue_list(self) -> None:
        for capability_id in (
            CAPABILITY_PDF_INSPECT,
            CAPABILITY_PDF_READ,
            CAPABILITY_PDF_OCR,
            CAPABILITY_PDF_CREATE,
            CAPABILITY_PDF_TRANSFORM,
            CAPABILITY_IMAGE_INSPECT,
            CAPABILITY_IMAGE_OCR,
            CAPABILITY_IMAGE_TRANSFORM,
            CAPABILITY_HWPX_READ,
            CAPABILITY_HWPX_CREATE,
            CAPABILITY_HWPX_EDIT,
            CAPABILITY_HWPX_TEMPLATE_FILL,
            CAPABILITY_HWPX_VALIDATE,
            CAPABILITY_HWP_READ,
            CAPABILITY_HWP_CONVERT_TO_HWPX,
            CAPABILITY_FILE_INSPECT,
        ):
            self.assertTrue(is_reserved_capability(capability_id))


class MimeCompatibilityTests(unittest.TestCase):
    def test_mime_mismatch_rejected(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.require_input_mime("skill:claw:pdf-reader@1", IMAGE_MIME)
        self.assertEqual(ctx.exception.code, "mime_mismatch")

    def test_declared_input_mime_accepted(self) -> None:
        registry = build_claw_skill_registry(
            [manifest(input_mime=(PDF_MIME, ANY_MIME))]
        )
        resolved = registry.require_input_mime("skill:claw:pdf-reader@1", ANY_MIME)
        self.assertEqual(resolved.skill_id, "skill:claw:pdf-reader@1")

    def test_unbounded_mime_value_rejected(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            registry.require_input_mime("skill:claw:pdf-reader@1", "not-a-mime")
        self.assertEqual(ctx.exception.code, "mime_mismatch")


class AuthorityTests(unittest.TestCase):
    def test_unauthorized_network_request_rejected(self) -> None:
        registry = build_claw_skill_registry(
            [manifest(network_required=False, filesystem_scope=FilesystemScope.NONE)]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(wants_network=True, wants_filesystem_scope=FilesystemScope.NONE),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_network_request")

    def test_unauthorized_provider_request_rejected(self) -> None:
        registry = build_claw_skill_registry(
            [
                manifest(
                    network_required=True,
                    provider_required=False,
                    side_effect_class=SideEffectClass.NONE,
                    filesystem_scope=FilesystemScope.NONE,
                )
            ]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(
                    wants_network=True,
                    wants_provider=True,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_provider_request")

    def test_unknown_skill_invocation_fails_closed(self) -> None:
        registry = build_claw_skill_registry(
            [manifest(filesystem_scope=FilesystemScope.NONE)]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(skill_id="skill:claw:ghost@1"),
            )
        self.assertEqual(ctx.exception.code, "unknown_skill")

    def test_narrower_request_than_manifest_fails_closed(self) -> None:
        """A request below required manifest authority must not be escalated."""

        registry = build_claw_skill_registry(
            [
                manifest(
                    network_required=True,
                    filesystem_scope=FilesystemScope.SCOPED_READ,
                )
            ]
        )
        # network required but not requested
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(wants_network=False, wants_filesystem_scope=FilesystemScope.SCOPED_READ),
            )
        self.assertEqual(ctx.exception.code, "missing_network_authority_request")

        # filesystem required but not requested
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(wants_network=True, wants_filesystem_scope=FilesystemScope.NONE),
            )
        self.assertEqual(ctx.exception.code, "missing_filesystem_authority_request")

    def test_matching_request_grant_equals_required_manifest_authority(self) -> None:
        registry = build_claw_skill_registry(
            [
                manifest(
                    network_required=True,
                    filesystem_scope=FilesystemScope.SCOPED_READ,
                )
            ]
        )
        matched = request(
            wants_network=True,
            wants_filesystem_scope=FilesystemScope.SCOPED_READ,
        )
        grant = authorize_invocation(registry, matched)
        self.assertEqual(grant.network_required, matched.wants_network)
        self.assertEqual(grant.provider_required, matched.wants_provider)
        self.assertEqual(grant.sandbox_required, matched.wants_sandbox)
        self.assertEqual(grant.filesystem_scope, matched.wants_filesystem_scope)
        self.assertFalse(hasattr(grant, "caller_authority"))

    def test_filesystem_scope_widening_rejected(self) -> None:
        registry = build_claw_skill_registry(
            [manifest(filesystem_scope=FilesystemScope.SCOPED_READ)]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(wants_filesystem_scope=FilesystemScope.SCOPED_WRITE),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_filesystem_request")

    def test_sandbox_request_without_declaration_rejected(self) -> None:
        registry = build_claw_skill_registry(
            [manifest(sandbox_required=False, filesystem_scope=FilesystemScope.NONE)]
        )
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_invocation(
                registry,
                request(wants_sandbox=True, wants_filesystem_scope=FilesystemScope.NONE),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_sandbox_request")

    def test_readonly_provider_skill_is_authorizable(self) -> None:
        """provider_required + side_effect NONE is a valid read-only Skill."""

        readonly_provider = manifest(
            skill_id="skill:claw:pdf-ocr-ro@1",
            capability_id=CAPABILITY_PDF_OCR,
            network_required=True,
            provider_required=True,
            side_effect_class=SideEffectClass.NONE,
            approval_required=False,
            filesystem_scope=FilesystemScope.NONE,
        )
        registry = build_claw_skill_registry([readonly_provider])
        grant = authorize_invocation(
            registry,
            request(
                skill_id="skill:claw:pdf-ocr-ro@1",
                wants_network=True,
                wants_provider=True,
                wants_filesystem_scope=FilesystemScope.NONE,
            ),
        )
        self.assertTrue(grant.provider_required)
        self.assertIs(grant.side_effect_class, SideEffectClass.NONE)
        self.assertFalse(grant.approval_required)

    def test_provider_without_network_manifest_fails_construction(self) -> None:
        with self.assertRaises(SkillRegistryContractError) as ctx:
            manifest(network_required=False, provider_required=True)
        self.assertEqual(ctx.exception.code, "invalid_capability_manifest")

    def test_authority_truth_table(self) -> None:
        """Required truth table for request vs manifest authority."""

        def auth(entry: SkillManifest, req: SkillInvocationRequest) -> str:
            registry = build_claw_skill_registry([entry])
            try:
                authorize_invocation(registry, req)
            except SkillRegistryContractError as exc:
                return f"FAIL:{exc.code}"
            return "PASS"

        # NETWORK
        net = manifest(network_required=True, filesystem_scope=FilesystemScope.NONE)
        self.assertEqual(
            auth(net, request(wants_network=False, wants_filesystem_scope=FilesystemScope.NONE)),
            "FAIL:missing_network_authority_request",
        )
        self.assertEqual(
            auth(net, request(wants_network=True, wants_filesystem_scope=FilesystemScope.NONE)),
            "PASS",
        )
        offline = manifest(network_required=False, filesystem_scope=FilesystemScope.NONE)
        self.assertEqual(
            auth(offline, request(wants_network=True, wants_filesystem_scope=FilesystemScope.NONE)),
            "FAIL:unauthorized_network_request",
        )

        # PROVIDER
        prov = manifest(
            network_required=True,
            provider_required=True,
            side_effect_class=SideEffectClass.NONE,
            filesystem_scope=FilesystemScope.NONE,
        )
        self.assertEqual(
            auth(
                prov,
                request(
                    wants_network=True,
                    wants_provider=False,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            ),
            "FAIL:missing_provider_authority_request",
        )
        self.assertEqual(
            auth(
                prov,
                request(
                    wants_network=True,
                    wants_provider=True,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            ),
            "PASS",
        )

        # SANDBOX
        box = manifest(sandbox_required=True, filesystem_scope=FilesystemScope.NONE)
        self.assertEqual(
            auth(box, request(wants_sandbox=False, wants_filesystem_scope=FilesystemScope.NONE)),
            "FAIL:missing_sandbox_authority_request",
        )
        self.assertEqual(
            auth(box, request(wants_sandbox=True, wants_filesystem_scope=FilesystemScope.NONE)),
            "PASS",
        )
        unboxed = manifest(sandbox_required=False, filesystem_scope=FilesystemScope.NONE)
        self.assertEqual(
            auth(unboxed, request(wants_sandbox=True, wants_filesystem_scope=FilesystemScope.NONE)),
            "FAIL:unauthorized_sandbox_request",
        )

        # FILESYSTEM
        fs_read = manifest(filesystem_scope=FilesystemScope.SCOPED_READ)
        self.assertEqual(
            auth(fs_read, request(wants_filesystem_scope=FilesystemScope.NONE)),
            "FAIL:missing_filesystem_authority_request",
        )
        self.assertEqual(
            auth(fs_read, request(wants_filesystem_scope=FilesystemScope.SCOPED_READ)),
            "PASS",
        )
        self.assertEqual(
            auth(fs_read, request(wants_filesystem_scope=FilesystemScope.SCOPED_WRITE)),
            "FAIL:unauthorized_filesystem_request",
        )


class CompositionTests(unittest.TestCase):
    def test_composition_unions_member_authority(self) -> None:
        narrow = manifest()
        wide = manifest(
            skill_id="skill:claw:ocr-worker@1",
            capability_id=CAPABILITY_PDF_OCR,
            network_required=True,
            filesystem_scope=FilesystemScope.SCOPED_WRITE,
            side_effect_class=SideEffectClass.LOCAL_WRITE,
        )
        registry = build_claw_skill_registry([narrow, wide])
        composition = compose_skills(
            registry,
            ["skill:claw:pdf-reader@1", "skill:claw:ocr-worker@1"],
        )
        self.assertTrue(composition.network_required)
        self.assertEqual(composition.filesystem_scope, FilesystemScope.SCOPED_WRITE)
        self.assertEqual(
            composition.side_effect_class,
            SideEffectClass.LOCAL_WRITE,
        )

    def test_composition_unknown_member_fails_closed(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            compose_skills(registry, ["skill:claw:pdf-reader@1", "skill:claw:ghost@1"])
        self.assertEqual(ctx.exception.code, "unknown_skill")

    def test_composition_authority_widening_rejected_for_member(self) -> None:
        """A wide composition must not widen a narrow member's authority."""

        narrow = manifest(network_required=False, filesystem_scope=FilesystemScope.NONE)
        wide = manifest(
            skill_id="skill:claw:ocr-worker@1",
            capability_id=CAPABILITY_PDF_OCR,
            network_required=True,
            filesystem_scope=FilesystemScope.NONE,
        )
        registry = build_claw_skill_registry([narrow, wide])
        composition = compose_skills(
            registry,
            ["skill:claw:pdf-reader@1", "skill:claw:ocr-worker@1"],
        )
        self.assertTrue(composition.network_required)

        # The composition has network authority, but the narrow member does not.
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_composed_member(
                registry,
                composition,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-reader@1",
                    actual_input_mime=PDF_MIME,
                    wants_network=True,
                    wants_filesystem_scope=FilesystemScope.NONE,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_network_request")

        # The wide member remains authorized for its own declared authority.
        grant = authorize_composed_member(
            registry,
            composition,
            SkillInvocationRequest(
                skill_id="skill:claw:ocr-worker@1",
                actual_input_mime=PDF_MIME,
                wants_network=True,
                wants_filesystem_scope=FilesystemScope.NONE,
            ),
        )
        self.assertTrue(grant.network_required)
        self.assertEqual(grant.filesystem_scope, FilesystemScope.NONE)

    def test_composition_rejects_non_member_invocation(self) -> None:
        registry = build_claw_skill_registry(
            [
                manifest(),
                manifest(skill_id="skill:claw:ocr-worker@1", capability_id=CAPABILITY_PDF_OCR),
            ]
        )
        composition = compose_skills(registry, ["skill:claw:pdf-reader@1"])
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_composed_member(
                registry,
                composition,
                SkillInvocationRequest(
                    skill_id="skill:claw:ocr-worker@1",
                    actual_input_mime=PDF_MIME,
                ),
            )
        self.assertEqual(ctx.exception.code, "unknown_skill")


class SafeProjectionTests(unittest.TestCase):
    def test_manifest_projection_contains_only_bounded_metadata(self) -> None:
        entry = manifest()
        projected = entry.to_public_dict()
        self.assertEqual(
            set(projected),
            {
                "skill_id",
                "version",
                "capability_id",
                "input_mime",
                "output_mime",
                "filesystem_scope",
                "network_required",
                "provider_required",
                "sandbox_required",
                "side_effect_class",
                "approval_required",
                "max_input_bytes",
                "max_pages_or_archive_expansion",
                "provenance",
                "license",
            },
        )
        for key, value in projected.items():
            self.assertNotIn("credential", str(key).casefold())
            self.assertNotIn("token", str(key).casefold())
            self.assertNotIn("password", str(key).casefold())
            self.assertNotIn("C:\\", str(value))
            self.assertNotIn("/home/", str(value))
            self.assertNotIn("/etc/", str(value))

    def test_registry_projection_is_bounded(self) -> None:
        registry = build_claw_skill_registry(
            [
                manifest(),
                manifest(
                    skill_id="skill:claw:hwpx-reader@1",
                    capability_id=CAPABILITY_HWPX_READ,
                    input_mime=(HWPX_MIME,),
                ),
            ]
        )
        rows = registry.to_public_dicts()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(
                set(row),
                {
                    "skill_id",
                    "version",
                    "capability_id",
                    "input_mime",
                    "output_mime",
                    "filesystem_scope",
                    "network_required",
                    "provider_required",
                    "sandbox_required",
                    "side_effect_class",
                    "approval_required",
                    "max_input_bytes",
                    "max_pages_or_archive_expansion",
                    "provenance",
                    "license",
                },
            )

    def test_grant_projection_excludes_input_bytes_payload_fields(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        grant = authorize_invocation(
            registry,
            SkillInvocationRequest(
                skill_id="skill:claw:pdf-reader@1",
                actual_input_mime=PDF_MIME,
                wants_filesystem_scope=FilesystemScope.SCOPED_READ,
            ),
        )
        projected = grant.to_public_dict()
        self.assertNotIn("input_mime", projected)
        self.assertNotIn("output_mime", projected)
        self.assertNotIn("provenance", projected)
        self.assertNotIn("license", projected)
        self.assertEqual(projected["skill_id"], "skill:claw:pdf-reader@1")


class NoArbitraryExecutionTests(unittest.TestCase):
    def test_skill_id_is_rejected_before_any_lookup_for_shell_shapes(self) -> None:
        registry = build_claw_skill_registry([manifest()])
        for bad in (
            "skill:claw:x;id@1",
            "skill:claw:x|id@1",
            "skill:claw:x`id`@1",
            "skill:claw:x$(id)@1",
            "skill:claw:x&&id@1",
            "skill:claw:x\nid@1",
        ):
            with self.subTest(skill_id=bad):
                with self.assertRaises(SkillRegistryContractError) as ctx:
                    registry.get(bad)
                self.assertEqual(ctx.exception.code, "unknown_skill")

    def test_module_exposes_no_execution_entrypoints(self) -> None:
        import ast

        import kagent.claw_skill_registry as module

        with open(module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported: set[str] = set()
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

        for banned_module in ("subprocess", "importlib", "os", "runpy", "pty", "shlex"):
            self.assertNotIn(banned_module, imported)
        for banned_call in ("eval", "exec", "system", "popen", "Popen", "check_call", "check_output", "run"):
            self.assertNotIn(banned_call, called)


class FullCatalogueSmokeTests(unittest.TestCase):
    def test_each_reserved_capability_can_own_exactly_one_builtin_manifest(self) -> None:
        builders = {
            CAPABILITY_FILE_INSPECT: {"skill_id": "skill:claw:file-inspect@1", "input_mime": (ANY_MIME,)},
            CAPABILITY_PDF_INSPECT: {"skill_id": "skill:claw:pdf-inspect@1", "input_mime": (PDF_MIME,)},
            CAPABILITY_PDF_READ: {"skill_id": "skill:claw:pdf-read@1", "input_mime": (PDF_MIME,)},
            CAPABILITY_PDF_OCR: {"skill_id": "skill:claw:pdf-ocr@1", "input_mime": (PDF_MIME,)},
            CAPABILITY_PDF_CREATE: {
                "skill_id": "skill:claw:pdf-create@1",
                "input_mime": (ANY_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
            CAPABILITY_PDF_TRANSFORM: {
                "skill_id": "skill:claw:pdf-transform@1",
                "input_mime": (PDF_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
            CAPABILITY_IMAGE_INSPECT: {
                "skill_id": "skill:claw:image-inspect@1",
                "input_mime": (IMAGE_MIME,),
            },
            CAPABILITY_IMAGE_OCR: {"skill_id": "skill:claw:image-ocr@1", "input_mime": (IMAGE_MIME,)},
            CAPABILITY_IMAGE_TRANSFORM: {
                "skill_id": "skill:claw:image-transform@1",
                "input_mime": (IMAGE_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
            CAPABILITY_HWPX_READ: {"skill_id": "skill:claw:hwpx-read@1", "input_mime": (HWPX_MIME,)},
            CAPABILITY_HWPX_CREATE: {
                "skill_id": "skill:claw:hwpx-create@1",
                "input_mime": (ANY_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
            CAPABILITY_HWPX_EDIT: {
                "skill_id": "skill:claw:hwpx-edit@1",
                "input_mime": (HWPX_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
            CAPABILITY_HWPX_TEMPLATE_FILL: {
                "skill_id": "skill:claw:hwpx-template-fill@1",
                "input_mime": (HWPX_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
            CAPABILITY_HWPX_VALIDATE: {
                "skill_id": "skill:claw:hwpx-validate@1",
                "input_mime": (HWPX_MIME,),
            },
            CAPABILITY_HWP_READ: {"skill_id": "skill:claw:hwp-read@1", "input_mime": (HWP_MIME,)},
            CAPABILITY_HWP_CONVERT_TO_HWPX: {
                "skill_id": "skill:claw:hwp-convert@1",
                "input_mime": (HWP_MIME,),
                "side_effect_class": SideEffectClass.LOCAL_WRITE,
                "filesystem_scope": FilesystemScope.SCOPED_WRITE,
            },
        }
        self.assertEqual(set(builders), set(RESERVED_CAPABILITY_IDS))
        manifests = tuple(
            manifest(capability_id=capability_id, **fields)
            for capability_id, fields in sorted(builders.items())
        )
        registry = build_claw_skill_registry(manifests)
        self.assertEqual(len(registry.entries), len(RESERVED_CAPABILITY_IDS))
        for capability_id in RESERVED_CAPABILITY_IDS:
            self.assertEqual(registry.require_capability(capability_id).capability_id, capability_id)

        # Composition of the full catalogue stays fail-closed for undeclared network use.
        composition = compose_skills(registry, registry.skill_ids)
        self.assertFalse(composition.provider_required)
        with self.assertRaises(SkillRegistryContractError) as ctx:
            authorize_composed_member(
                registry,
                composition,
                SkillInvocationRequest(
                    skill_id="skill:claw:pdf-read@1",
                    actual_input_mime=PDF_MIME,
                    wants_network=True,
                    wants_filesystem_scope=FilesystemScope.SCOPED_READ,
                ),
            )
        self.assertEqual(ctx.exception.code, "unauthorized_network_request")

        # Read-only provider Skill (side_effect NONE) authorizes when requested exactly.
        ro = manifest(
            skill_id="skill:claw:pdf-ocr-ro@1",
            capability_id=CAPABILITY_PDF_OCR,
            input_mime=(PDF_MIME,),
            network_required=True,
            provider_required=True,
            side_effect_class=SideEffectClass.NONE,
            approval_required=False,
            filesystem_scope=FilesystemScope.NONE,
        )
        ro_registry = build_claw_skill_registry([ro])
        ro_grant = authorize_invocation(
            ro_registry,
            SkillInvocationRequest(
                skill_id="skill:claw:pdf-ocr-ro@1",
                actual_input_mime=PDF_MIME,
                wants_network=True,
                wants_provider=True,
                wants_filesystem_scope=FilesystemScope.NONE,
            ),
        )
        self.assertTrue(ro_grant.provider_required)
        self.assertIs(ro_grant.side_effect_class, SideEffectClass.NONE)


if __name__ == "__main__":
    unittest.main()
