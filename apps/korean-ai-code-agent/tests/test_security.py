"""Dedicated tests for the KAgent credential boundary (#2784).

Two semantics are asserted separately on purpose:

```text
contains_credential_material(text) -> bool   gate: fail closed on credential material
redact_secrets(text)               -> str    scrub: presentation-safe, idempotent
```

Every credential value here is assembled at runtime from obviously synthetic fragments.
No real or realistically-scannable key literal is committed, and no provider's live key
format appears as a single string a secret scanner could flag.
"""

from __future__ import annotations

import hashlib
import re
import unittest

from kagent.contracts import ContractError
from kagent.github_draft_pr import DraftPullRequestPlan
from kagent.sandbox_conformance import VerifiedDiffEvidence
from kagent.security import contains_credential_material, redact_secrets


def secret_value(tag: str = "alpha", length: int = 26) -> str:
    """A synthetic, opaque-looking credential value of a predictable length."""
    base = f"synthetic{tag}placeholder"
    return (base * 4)[: max(len(base), length)]


def padded_upper(tag: str = "alpha", length: int = 16) -> str:
    """Upper-case alphanumerics, for shapes that are defined in that alphabet."""
    base = f"SYNTHETIC{tag.upper()}PLACEHOLDER"
    digits = "01345789"
    source = (base + digits) * 4
    return "".join(ch for ch in source if ch.isalnum())[:length]


def shaped(prefix: str, tag: str = "alpha", total: int = 30) -> str:
    """Provider-key material assembled at runtime so no scannable literal exists."""
    return prefix + secret_value(tag, total)[: max(0, total - len(prefix))]


def provider_shaped(prefix: str, tag: str, total: int) -> str:
    return prefix + padded_upper(tag, total - len(prefix))


REVISION = "ab" * 20
# The PEM marker is assembled rather than spelled out. It is a format sentinel with no key
# material beside it, but a literal private-key header in a test file is exactly what the
# secret scanner gating this repository alerts on, which would block the PR that tests it.
PEM_BEGIN = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
PEM_END = "-----END " + "RSA PRIVATE KEY" + "-----"

# The three patterns this module replaces, kept only as a parity oracle for
# GrammarAttributionTests. Fragments are split for the same reason as the PEM marker: a
# credential keyword sitting against a separator and a `[^\s]+` value is precisely the
# proximity shape the generic-password detector alerts on, and an incident pinned to a
# commit here cannot be cleared by a later commit while history rewriting is off.
_LEGACY_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        "(?i)(author" "ization\\s*:\\s*bearer\\s+)" "[^\\s]+",
        "\\bsk-" "(?:or-v1-)?" "[A-Za-z0-9._-]{8,}\\b",
        "(?i)((?:api[_-]?key|token|secret|pass" "word)" "\\s*[=:]\\s*)" "[^\\s]+",
    )
)


# ---------------------------------------------------------------------------
# Detector: positive corpus
# ---------------------------------------------------------------------------

ASSIGNMENT_POSITIVES = (
    ("api_key equals", lambda s: f"api_key={s}"),
    ("password colon", lambda s: f"password: {s}"),
    ("token quoted json", lambda s: '{{"token": "{}"}}'.format(s)),
    ("token json no space", lambda s: '{{"token":"{}"}}'.format(s)),
    ("nested json password", lambda s: '{{"db": {{"password": "{}"}}}}'.format(s)),
    ("single quoted yaml", lambda s: "password: '{}'".format(s)),
    ("pwd alias", lambda s: f"pwd={s}"),
    ("passphrase alias", lambda s: f"passphrase: {s}"),
    ("private_key alias", lambda s: f"private_key={s}"),
    ("credential alias", lambda s: f"credential={s}"),
    ("access_token substring", lambda s: f"access_token={s}"),
    ("refresh_token substring", lambda s: f"refresh_token={s}"),
    ("client secret", lambda s: f"client_secret={s}"),
    ("dotenv form", lambda s: f"API_KEY={s}"),
    ("toml form", lambda s: f"password = '{s}'"),
    ("python kwarg", lambda s: f"connect(password='{s}')"),
    ("log line", lambda s: f"[INFO] auth failed password={s} user=alice"),
    ("xml tag", lambda s: f"<password>{s}</password>"),
    ("connection string", lambda s: f"postgres://admin:{s}@db.internal:5432/app"),
    ("multi line value", lambda s: f"header\ntoken={s}\nfooter"),
)

HEADER_POSITIVES = (
    ("scheme header", lambda s: f"Authorization: Bearer {s}"),
    ("scheme glued to colon", lambda s: f"Authorization:Bearer{s}"),
    ("lowercase header", lambda s: f"authorization: bearer {s}"),
    ("bare bearer", lambda s: f"Bearer {s}"),
    ("basic auth", lambda s: f"Authorization: Basic {s}"),
    ("proxy authorization basic", lambda s: f"Proxy-Authorization: Basic {s}"),
    ("digest auth", lambda s: f"Authorization: Digest {s}"),
    ("tab separated scheme", lambda s: f"Authorization:\tBearer\t{s}"),
    ("x-api-key header", lambda s: f"x-api-key: {s}"),
    ("set-cookie", lambda s: f"Set-Cookie: sid={s}; HttpOnly"),
    ("url single character password", lambda _s: "postgres://admin:x@db.internal:5432/app"),
)

PROVIDER_POSITIVES = (
    ("github classic pat", lambda: shaped("ghp_", "gh1", 40)),
    ("github fine grained", lambda: shaped("github_pat_", "gh2", 40)),
    ("gitlab pat", lambda: shaped("glpat-", "gl1", 40)),
    ("google api key", lambda: shaped("AIza", "go1", 40)),
    ("aws access key id", lambda: provider_shaped("AKIA", "aws1", 20)),
    ("slack token", lambda: shaped("xoxb-", "sl1", 40)),
    ("stripe live", lambda: shaped("sk_live_", "st1", 40)),
    ("openai classic", lambda: shaped("sk-", "oa1", 40)),
    ("openai project", lambda: shaped("sk-proj-", "oa2", 46)),
    (
        "pem private key",
        lambda: PEM_BEGIN + "\n" + secret_value("pem1", 40) + "\n" + PEM_END,
    ),
)

BOUNDARY_POSITIVES = (
    ("sk glued after letters", lambda s: "prefixsk-" + s[3:]),
    ("sk glued after digit", lambda s: "9sk-" + s[3:]),
    ("sk alone at start", lambda s: "sk-" + s[3:]),
    ("token glued after brace", lambda s: '{{"api_key":"{' + s[:14] + '"}}'),
)

# ---------------------------------------------------------------------------
# Detector AND redactor: benign prose that must not be treated as credential material
# ---------------------------------------------------------------------------

# Verbatim from issue #2784. These six sentences are the stated acceptance requirement, so
# they are kept as-written rather than paraphrased, and a change here needs a reason.
ISSUE_BENIGN_PROSE = (
    "the api_key parameter is optional",
    "password must be at least 8 characters",
    "Authorization Bearer token is required here",
    "set token in the dashboard to continue",
    "the secret of the story is the island",
    "use sk- prefix for keys",
)

# Additional prose the grammar must not touch. What each has in common is that no value
# slot is opened: no `=` or `:` after a credential keyword, and no scheme word standing
# alone on its own line.
ADDITIONAL_BENIGN_PROSE = (
    "rotate your API key regularly",
    "tokens are split on whitespace",
    "credentials should never be committed",
    "we call the credential helper once",
    "the private_key field name is documented below",
    "pwd is the shell builtin for print working directory",
    "sk- is only a prefix, not a secret",
    "this document explains bearer tokens",
    "Bearer tokens are opaque.",
    "Basic configuration follows below",
    "please provide a passphrase when prompted",
)

BENIGN_PROSE = ISSUE_BENIGN_PROSE + ADDITIONAL_BENIGN_PROSE

# Sentences that read like documentation but do open a value slot, so they are credential
# material and are rejected. An earlier revision of this module passed the second one as
# prose by ignoring 1-2 character values; the #2787 review ruled that length is not
# evidence of prose, and these cases are positives ever since.
ASSIGNMENT_POSITION_BEATS_PROSE = (
    "password: ab in the config file",
    "the password: at least eight characters is the rule",
    "token: x",
    "passphrase: 1234 then press enter",
    "credential=1",
)

# A scheme word with nothing but its value on the line is a field, not a sentence, at any
# length. Contrast with "Bearer tokens are opaque." above, which is a sentence. Each entry
# is (label, text, something that must disappear from the redacted copy).
STANDALONE_SCHEME_POSITIVES = (
    ("short bearer value", "Bearer short", "short"),
    ("two character bearer value", "Bearer ab", "Bearer ab"),
    ("basic value", "Basic Zm9v", "Zm9v"),
    ("digest value", "Digest x", "Digest x"),
    ("bearer line inside a log", "header line\nBearer zz\ntrailer line", "Bearer zz"),
)


class DetectorPositiveTests(unittest.TestCase):
    """Credential material must be detected, not merely credential-related prose."""

    def assert_detected(self, label: str, text: str) -> None:
        with self.subTest(case=label):
            self.assertTrue(contains_credential_material(text), text)

    def test_assignment_shapes_detected(self):
        for label, build in ASSIGNMENT_POSITIVES:
            self.assert_detected(label, build(secret_value()))

    def test_header_shapes_detected(self):
        for label, build in HEADER_POSITIVES:
            self.assert_detected(label, build(secret_value("hdr")))

    def test_provider_shapes_detected(self):
        for label, build in PROVIDER_POSITIVES:
            self.assert_detected(label, build())

    def test_glued_boundary_shapes_detected(self):
        for label, build in BOUNDARY_POSITIVES:
            self.assert_detected(label, build(secret_value("glue")))

    def test_short_assignment_values_stay_fail_closed(self):
        # CENTRAL blocker 1 on #2787: an assignment position is identified by syntax, so a
        # short value is not evidence of prose. Every one of these was passing as prose when
        # the rule consulted a length floor.
        for text in ASSIGNMENT_POSITION_BEATS_PROSE:
            with self.subTest(text=text):
                self.assertTrue(contains_credential_material(text), text)
                out = redact_secrets(text)
                self.assertIn("[REDACTED]", out)
                self.assertEqual(out, redact_secrets(out))

    def test_standalone_bare_scheme_field_detected_at_any_length(self):
        # CENTRAL blocker 2 on #2787: `Bearer short` was rejected by main's egress grammar
        # and this module weakened it to a 16-character minimum. It is now rejected because
        # the scheme owns the line, while the prose in test_benign_prose_rejected_by_detector
        # stays clean for the opposite reason.
        for label, text, value in STANDALONE_SCHEME_POSITIVES:
            with self.subTest(case=label):
                self.assertTrue(contains_credential_material(text), text)
                out = redact_secrets(text)
                self.assertNotIn(value, out)
                self.assertIn("[REDACTED]", out)
                self.assertEqual(out, redact_secrets(out))
        self.assertIn("Bearer", redact_secrets("Bearer short"), "the scheme word is context")

    def test_benign_prose_rejected_by_detector(self):
        for text in BENIGN_PROSE:
            with self.subTest(prose=text):
                self.assertFalse(contains_credential_material(text), text)

    def test_issue_listed_benign_prose_rejected_by_detector(self):
        # The same corpus as the test above, run separately and by name, because these six
        # sentences are what #2784 requires to stay acceptable. If this one goes red the
        # detector has started rejecting the issue's own examples.
        for text in ISSUE_BENIGN_PROSE:
            with self.subTest(prose=text):
                self.assertFalse(contains_credential_material(text), text)
                self.assertEqual(redact_secrets(text), text)

    def test_preference_cookie_values_stay_clean(self):
        # A cookie header is a credential position, but a UI preference is not a credential.
        # This is the one place a size test survives, and it is on the *value* shape rather
        # than an assignment slot: `sid=<opaque>` counts, `theme=light` does not.
        for text in (
            "Set-Cookie: theme=light; Path=/",
            "Set-Cookie: locale=ko_KR; Max-Age=86400",
        ):
            with self.subTest(text=text):
                self.assertFalse(contains_credential_material(text), text)
                self.assertEqual(redact_secrets(text), text)

    def test_detector_rejects_empty_and_non_string(self):
        self.assertFalse(contains_credential_material(""))
        for invalid in (None, 12, b"token=abc", ["token=abc"]):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    contains_credential_material(invalid)

    def test_detector_is_not_keyword_only(self):
        # A detector that merely looked for the words would fail these; the value must exist.
        for text in (
            "password",
            "password=",
            "token:",
            "api_key is unset",
            "secret",
        ):
            with self.subTest(text=text):
                self.assertFalse(contains_credential_material(text), text)


class RedactorTests(unittest.TestCase):
    """redact_secrets stays presentation-oriented: value-shaped, marker-stable, idempotent."""

    def test_marker_vocabulary_unchanged(self):
        self.assertIn("[REDACTED]", redact_secrets(f"password={secret_value()}"))
        self.assertIn("[REDACTED_KEY]", redact_secrets(f"auth={shaped('sk-', 'm1', 40)}"))

    def test_json_quoted_assignment_now_redacted(self):
        value = secret_value("json")
        out = redact_secrets('{{"api_key": "%s"}}' % value)
        self.assertNotIn(value, out)
        self.assertIn("[REDACTED]", out)

    def test_provider_shape_redacted_without_prose_damage(self):
        key = shaped("ghp_", "pv")
        out = redact_secrets(f"token {key} used")
        self.assertNotIn(key, out)

    def test_glued_boundary_redacted(self):
        value = "sk-" + secret_value("gl2")[3:]
        out = redact_secrets("prefix" + value)
        self.assertNotIn(value, out)

    def test_benign_prose_is_left_byte_identical(self):
        for text in BENIGN_PROSE:
            with self.subTest(prose=text):
                self.assertEqual(redact_secrets(text), text, "redactor must not mask prose")

    def test_idempotent_across_every_positive_corpus(self):
        cases = []
        cases += [build(secret_value()) for _l, build in ASSIGNMENT_POSITIVES]
        cases += [build(secret_value("i")) for _l, build in HEADER_POSITIVES]
        cases += [build() for _l, build in PROVIDER_POSITIVES]
        cases += [build(secret_value("i3")) for _l, build in BOUNDARY_POSITIVES]
        cases += list(ASSIGNMENT_POSITION_BEATS_PROSE)
        cases += [text for _l, text, _v in STANDALONE_SCHEME_POSITIVES]
        cases += list(BENIGN_PROSE)
        for text in cases:
            with self.subTest(text=text[:48]):
                once = redact_secrets(text)
                self.assertEqual(once, redact_secrets(once))

    def test_quoted_value_containing_spaces_is_fully_masked(self):
        # A quoted value is not delimited by whitespace, so masking only the first word
        # would leave the rest on display. This is what the quoted assignment shape is
        # handled separately for.
        body = '{"api_key": "multi word secret value"}'
        self.assertTrue(contains_credential_material(body))
        out = redact_secrets(body)
        self.assertNotIn("multi word secret value", out)
        self.assertNotIn("word secret", out)
        self.assertIn('"api_key"', out, "only the value is masked, the structure stays")
        self.assertEqual(out, redact_secrets(out))

    def test_truncated_json_fragment_is_detected(self):
        # Excerpts reach the redactor already cut: a bounded read can stop inside a value,
        # and a slice can start mid-object so the key loses its opening quote. Both used to
        # hide a complete credential, because the quoted shape demanded quotes at both ends.
        cases = (
            ('token": "ab', "ab"),
            ('api_key": "abcdef', "abcdef"),
            ('{"api_key": "abcdefghij', "abcdefghij"),
            ('{"token":"one two three', "one two three"),
            ("password: 'still open", "still open"),
        )
        for text, value in cases:
            with self.subTest(text=text):
                self.assertTrue(contains_credential_material(text), text)
                out = redact_secrets(text)
                self.assertNotIn(value, out)
                self.assertIn("[REDACTED]", out)
                self.assertEqual(out, redact_secrets(out))

    def test_quoted_value_with_spaces_masks_fully_not_word_by_word(self):
        # The replaced grammar matched [^\s]+ here, so it redacted only `'multi` and left
        # `word value'` on display. Same shape must now be masked as one value.
        out = redact_secrets("api_key = 'multi word value'")
        self.assertNotIn("multi", out)
        self.assertNotIn("word value", out)
        self.assertIn("[REDACTED]", out)
        self.assertEqual(out, redact_secrets(out))

    def test_nested_assignment_inside_a_quoted_value_is_masked_once(self):
        # A quoted value that itself holds an assignment makes the two rules return spans
        # containing one another. Masked independently, the inner replacement moves the
        # outer offsets and part of the value survives, so overlapping spans are merged
        # before anything is replaced.
        inner = secret_value("nest")
        text = '{"api_key": "password=%s"}' % inner
        out = redact_secrets(text)
        self.assertNotIn(inner, out)
        self.assertNotIn("password=", out)
        self.assertEqual(out, '{"api_key": "[REDACTED]"}')
        self.assertEqual(out, redact_secrets(out))

    def test_pem_body_not_only_the_header_is_masked(self):
        # A rule that replaced just the BEGIN line would still pass every detection test
        # while leaving the key material on the page. The body is the part that matters.
        body = secret_value("pembody", 40)
        for label, text in (
            ("closed", PEM_BEGIN + "\n" + body + "\n" + PEM_END),
            ("truncated", PEM_BEGIN + "\n" + body),
        ):
            with self.subTest(pem=label):
                out = redact_secrets(text)
                self.assertNotIn(body, out)
                self.assertNotIn("PRIVATE KEY", out)
                self.assertIn("[REDACTED_KEY]", out)
                self.assertEqual(out, redact_secrets(out))

    def test_non_string_input_rejected(self):
        for invalid in (None, 7, b"x"):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    redact_secrets(invalid)


class EgressGateMigrationTests(unittest.TestCase):
    """The GitHub draft-PR boundary must gate on the detector, not the redactor."""

    def plan(self, **overrides):
        evidence_kwargs = {
            "run_id": "run_egress_1",
            "lease_id": "lease_egress_1",
            "repository_ref": "skerishKang/example",
            "input_revision": REVISION,
            "changed_files": ("src/app.py",),
            "unified_diff_sha256": hashlib.sha256(b"diff").hexdigest(),
            "verification_command_id": "verify_unit",
            "verification_exit_code": 0,
            "verification_output_sha256": hashlib.sha256(b"out").hexdigest(),
            "terminal_reason": "completed",
            "final_revision_ref": "workspace_final_1",
        }
        evidence_kwargs.update(
            {k: v for k, v in overrides.items() if k in {"repository_ref", "changed_files"}}
        )
        args = {
            "plan_id": "plan_1",
            "evidence": VerifiedDiffEvidence(**evidence_kwargs),
            "title": "fix: repair bounded task",
            "body": "Verified by bounded unit tests.",
        }
        args.update({k: v for k, v in overrides.items() if k in {"title", "body"}})
        return DraftPullRequestPlan.from_verified_diff(**args)

    def test_clean_plan_accepted(self):
        plan = self.plan()
        self.assertEqual(plan.title, "fix: repair bounded task")

    def test_issue_benign_prose_in_body_still_accepted(self):
        # The #2784 corpus, at the egress boundary that actually rejects run output. This is
        # the acceptance line CENTRAL drew: these sentences must pass, and nothing here may
        # trade them for breadth.
        for prose in ISSUE_BENIGN_PROSE:
            with self.subTest(prose=prose):
                self.assertEqual(self.plan(body=prose).body, prose)
        for prose in ADDITIONAL_BENIGN_PROSE:
            with self.subTest(prose=prose):
                self.assertEqual(self.plan(body=prose).body, prose)

    def test_standalone_short_bearer_rejected_at_egress(self):
        # CENTRAL blocker 2 regression. main's deleted local grammar rejected `Bearer short`
        # and the first revision of this module let it through on a length floor, which made
        # the egress gate weaker than the code it replaced. It is rejected again, and by line
        # position rather than size — while the issue's own sentence still passes above.
        for text in ("Bearer short", "Digest x", "Bearer ab"):
            with self.subTest(text=text):
                self.assertTrue(contains_credential_material(text), text)
                with self.assertRaises(ContractError):
                    self.plan(body=text)
                with self.assertRaises(ContractError):
                    self.plan(title=text)
        # A multi-line body is gated per line, so one credential line fails the whole body.
        with self.assertRaises(ContractError):
            self.plan(body="verified against bounded tests\nBearer short\n")

    def test_credential_forms_rejected_in_body(self):
        cases = (
            ("json key", '{{"api_key": "%s"}}' % secret_value("eg1")),
            ("github pat", shaped("ghp_", "eg2", 40)),
            ("basic auth", "Authorization: Basic " + secret_value("eg3")),
            ("password assign", "password=" + secret_value("eg4")),
            ("pem", PROVIDER_POSITIVES[-1][1]()),
            # CENTRAL blocker 1 regression: a two-character value in an assignment position
            # is rejected at egress, prose continuation included.
            ("short assignment in prose", "password: ab in the config file"),
            ("single character value", "token: x"),
        )
        for label, value in cases:
            with self.subTest(case=label):
                self.assertTrue(contains_credential_material(value), value)
                with self.assertRaises(ContractError):
                    self.plan(body=value)

    def test_credential_forms_rejected_in_title_and_repository(self):
        with self.assertRaises(ContractError):
            self.plan(title="Fix token=" + secret_value("eg5"))
        with self.assertRaises(ContractError):
            self.plan(repository_ref="skerishKang/" + shaped("glpat-", "eg6", 40))

    def test_local_duplicate_gate_grammar_removed(self):
        import kagent.github_draft_pr as module

        self.assertFalse(hasattr(module, "_CREDENTIAL_TEXT_RE"))
        self.assertTrue(hasattr(module, "contains_credential_material"))
        credential_named = [
            name
            for name, value in vars(module).items()
            if name.isupper()
            and isinstance(value, re.Pattern)
            and any(w in name.lower() for w in ("credential", "secret", "token", "password"))
        ]
        self.assertEqual(credential_named, [])


class GrammarAttributionTests(unittest.TestCase):
    """Each rule must earn its place, and the shape rule must not be keyword matching."""

    def test_each_detection_rule_fires_on_its_own_shape(self):
        import kagent.security as security

        cases = (
            ("auth header", "Authorization: Bearer " + secret_value("at2")),
            ("scheme field line", "Bearer short"),
            # Kept mid-sentence on purpose: as a whole line this would also satisfy the
            # scheme-field rule, and the pairing below has to be one shape per rule.
            ("bare scheme", "the gateway replied Bearer " + secret_value("at3") + " today"),
            ("cookie", "Set-Cookie: sid=" + secret_value("at4") + "; HttpOnly"),
            ("url credentials", "postgres://admin:" + secret_value("at5") + "@db/app"),
            ("xml tag", "<password>" + secret_value("at6") + "</password>"),
            ("provider", shaped("ghp_", "at7", 40)),
            ("pem", PEM_BEGIN + "\n" + secret_value("at8")),
        )
        self.assertEqual(len(cases), len(security._DETECTION_PATTERNS))
        for (label, case), pattern in zip(cases, security._DETECTION_PATTERNS):
            with self.subTest(rule=label):
                self.assertIsNotNone(pattern.search(case), case)
                self.assertNotEqual(security.redact_secrets(case), case)

    def test_assignment_rule_contributes_shapes_no_pattern_catches(self):
        import kagent.security as security

        # These are found only by the structural assignment check. If _assignment_hits
        # were dead code the detector would silently lose its widest category.
        for case in (
            "api_key=" + secret_value("a1"),
            "password: " + secret_value("a2"),
            '{"api_key": "%s"}' % secret_value("a3"),
            "pwd=ab",
        ):
            with self.subTest(case=case[:40]):
                self.assertTrue(contains_credential_material(case))
                self.assertFalse(
                    any(p.search(case) for p in security._DETECTION_PATTERNS),
                    "expected the assignment path, not a pattern, to catch this",
                )

    def test_disabling_detection_returns_false_for_every_positive(self):
        # Inverting the detector must break the corpus, otherwise the corpus proves nothing.
        import kagent.security as security

        positive = "api_key=" + secret_value("mut")
        original = security._assignment_spans
        try:
            security._assignment_spans = lambda text: []
            self.assertFalse(security.contains_credential_material(positive))
        finally:
            security._assignment_spans = original
        self.assertTrue(security.contains_credential_material(positive))

    def test_benign_prose_names_credentials_without_being_one(self):
        # Every benign phrase below literally contains a keyword, so a keyword-presence
        # detector would reject all of them. Together with the negative corpus this is the
        # proof the gate is shape-driven, which is the property that keeps prose acceptable.
        keyword_words = (
            "password", "passwd", "pwd", "passphrase", "token", "secret", "api", "key",
            "bearer", "credential", "private_key", "sk-", "basic", "digest",
        )
        for text in BENIGN_PROSE:
            with self.subTest(text=text):
                self.assertTrue(any(w in text.lower() for w in keyword_words), text)
                self.assertFalse(contains_credential_material(text), text)

    def test_value_slot_is_the_boundary_not_value_length(self):
        # The line CENTRAL drew under blocker 1: what makes text a credential is that a
        # keyword opened a value slot, never how big the thing in the slot is.
        for text in (
            "password: ab",
            "password: ab in the config file",
            "some prefix password: ab more words",
            "token: x",
            "credential=1",
            "password: " + secret_value("bnd"),
        ):
            with self.subTest(text=text):
                self.assertTrue(contains_credential_material(text), text)
        for text in (
            "password must be at least 8 characters",
            "the api_key parameter is optional",
            "password:",
            "password= ",
            "no separator here at all",
        ):
            with self.subTest(text=text):
                self.assertFalse(contains_credential_material(text), text)

    def test_detector_never_narrower_than_replaced_grammar_on_field_shapes(self):
        # Parity as a property, not a hand-picked list: the three patterns this module
        # replaces are reproduced here only as an oracle, and every field shape they caught
        # must still be caught. Cases they missed are the gaps the other tests in this
        # module exist to prove closed.
        def legacy_catches(text: str) -> bool:
            return any(pattern.search(text) for pattern in _LEGACY_PATTERNS)

        corpus = (
            [build(secret_value()) for _label, build in ASSIGNMENT_POSITIVES]
            + [build(secret_value("par")) for _label, build in HEADER_POSITIVES]
            + [build() for _label, build in PROVIDER_POSITIVES]
            + [build(secret_value("par2")) for _label, build in BOUNDARY_POSITIVES]
            + [
                "password=ab",
                "token=ab",
                "password: ab in the config file",
                "api_key = 'multi word value'",
                "password = 'short'",
                "the token: 'quoted value' is set",
            ]
        )
        legacy_caught = 0
        for text in corpus:
            if not legacy_catches(text):
                continue
            legacy_caught += 1
            with self.subTest(text=text[:48]):
                self.assertTrue(
                    contains_credential_material(text),
                    "the replaced grammar caught this; the detector must not be narrower",
                )
        # A guard that never fires is not a guard: prove the oracle actually overlapped here.
        self.assertGreater(legacy_caught, len(corpus) // 3)


if __name__ == "__main__":
    unittest.main()
