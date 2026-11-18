"""#7978 — a registered network share keeps its UNC spelling end to end.

The owner could already approve ``\\\\server\\share``, but the normalizer folded
its doubled leading slash into ``/server/share`` — a drive-relative path no PC
command can address — so every pc_* call on that grant answered
``pc_path_not_found``. The store now keeps ``//server/share`` as the one UNC
spelling the scope checks read, and the Windows folder builder spells the
PowerShell command in the share's own ``\\\\server\\share\\...`` form.

Drive grants are untouched: every drive case below pins the old answer too.
"""
from __future__ import annotations

import base64
import re

import pytest

from app.mcp_gateway_execution import (
    _pc_normalize_path,
    _pc_relative_inside_roots,
)
from app.oracle_mesh_read_return_routes import (
    _pc_files_command,
    _pc_files_pick_root,
    _pc_files_windows_folder,
)
from app.pc_device_pairing_store import normalize_root_path

from test_261105_mcp_registered_folders import _call  # noqa: F401

UNC_ROOTS = [{"name": "share", "path": "//server/share"}]
#: The Engine's signed context carries the store's own shape: label-keyed.
UNC_LABEL_ROOTS = [{"label": "share", "path": "//server/share"}]


def _utf8_values(command: str) -> list[str]:
    """Every value the command carries as base64 UTF-8, decoded back."""
    return [
        base64.b64decode(match, validate=True).decode("utf-8")
        for match in re.findall(r"FromBase64String\('([^']+)'\)", command)
    ]


# -- the store keeps the share's doubled leading slash ------------------------


@pytest.mark.parametrize("value,expected", [
    ("\\\\server\\share", "//server/share"),
    ("//server/share", "//server/share"),
    ("\\\\server\\share\\", "//server/share"),
    ("\\\\\\server\\share", "//server/share"),
    ("\\\\server\\share\\문서", "//server/share/문서"),
    ("\\\\server\\share\\a\\b", "//server/share/a/b"),
    ("\\\\SERVER\\Share", "//SERVER/Share"),
])
def test_unc_registration_keeps_the_doubled_leading_slash(value, expected):
    assert normalize_root_path(value) == expected


@pytest.mark.parametrize("value", [
    "\\\\server",               # a server alone is not a share
    "/",                        # a bare slash was never a grant
    "//",                       # the marker without a share names nothing
    "\\\\server\\share\\..\\x",  # traversal above the share
    "//server/share/./x",       # a dot segment
    "\\\\server\\sha*re",       # wildcards never reach a grant
    "\\\\server\\share:c",      # an ADS-style tail
])
def test_unc_shapes_that_stay_refused(value):
    assert normalize_root_path(value) is None


# -- drive grants keep their old spelling exactly -----------------------------


@pytest.mark.parametrize("value,expected", [
    ("C:", "C:"), ("c:/", "C:"), ("c:\\", "C:"),
    ("C:/Users/me/견적", "C:/Users/me/견적"),
    ("C:\\Users\\me\\a\\b", "C:/Users/me/a/b"),
    ("D:/./CGI", None),  # a dot segment stays refused, as it always was
])
def test_drive_registration_is_unchanged(value, expected):
    assert normalize_root_path(value) == expected


# -- the gateway's one path spelling ------------------------------------------


@pytest.mark.parametrize("value,expected", [
    ("\\\\server\\share\\a.txt", "//server/share/a.txt"),
    ("\\\\server\\share", "//server/share"),
    ("//server/share/a.txt", "//server/share/a.txt"),
    ("\\\\server\\share\\..\\other", "//server/share/../other"),
    ("C:/x/./y", "C:/x/y"),
    ("C:\\x", "C:/x"),
    ("/tmp/./x", "/tmp/x"),
])
def test_gateway_normalization_preserves_the_unc_marker(value, expected):
    assert _pc_normalize_path(value) == expected


def test_drive_normalization_is_unchanged():
    assert _pc_normalize_path("D:/.") == "D:"
    assert _pc_normalize_path("docs/../x") == "docs/../x"


# -- the scope check reads one shape for drives and shares --------------------


def test_a_path_on_the_registered_share_is_inside():
    where = _pc_relative_inside_roots("\\\\server\\share\\reports\\q3.xlsx", UNC_ROOTS)
    assert where == ("share/reports/q3.xlsx", "inside")


def test_the_share_spelled_in_windows_form_is_the_same_grant():
    where = _pc_relative_inside_roots("//server/share/reports", UNC_ROOTS)
    assert where == ("share/reports", "inside")


def test_uppercase_share_spelling_is_the_same_grant():
    where = _pc_relative_inside_roots("\\\\SERVER\\SHARE\\a", UNC_ROOTS)
    assert where == ("share/a", "inside")


def test_the_share_root_itself_is_the_grant_not_an_outside_path():
    assert _pc_relative_inside_roots("//server/share", UNC_ROOTS) == (None, "root")
    assert _pc_relative_inside_roots("\\\\server\\share\\", UNC_ROOTS) == (None, "root")


@pytest.mark.parametrize("value", [
    "\\\\other\\share\\x",          # another server's share
    "\\\\server\\other\\x",         # another share on the same server
    "//server/share/../outside",    # a walk above the share
])
def test_paths_off_the_registered_share_stay_outside(value):
    assert _pc_relative_inside_roots(value, UNC_ROOTS) == (None, "outside")


def test_drive_and_share_grants_are_judged_by_one_rule():
    roots = [*UNC_ROOTS, {"name": "PADIEM", "path": "D:/PADIEM"}]
    assert _pc_relative_inside_roots("\\\\server\\share\\a", roots) == ("share/a", "inside")
    assert _pc_relative_inside_roots("D:\\PADIEM\\a", roots) == ("PADIEM/a", "inside")
    assert _pc_relative_inside_roots("E:\\x", roots) == (None, "outside")


# -- the PowerShell command carries the share's Windows spelling --------------


def test_the_list_command_spells_the_share_in_windows_form():
    command = _pc_files_command(op="list", root="//server/share", relative="reports")
    values = _utf8_values(command)
    assert "\\\\server\\share\\reports" in values
    assert "\\\\server\\share\\" in values


def test_the_share_root_lists_the_share_itself():
    command = _pc_files_command(op="list", root="//server/share", relative="")
    values = _utf8_values(command)
    assert "\\\\server\\share" in values
    assert "\\\\server\\share\\" in values


def test_the_drive_command_keeps_its_old_spelling():
    command = _pc_files_command(op="list", root="C:", relative="docs")
    values = _utf8_values(command)
    assert "C:/docs" in values
    assert "C:\\" in values
    assert not any(value.startswith("\\\\") for value in values)


# -- the label-relative path the model names resolves to the share ------------


def test_the_label_relative_path_resolves_to_the_unc_root():
    picked = _pc_files_pick_root(UNC_LABEL_ROOTS, "share/reports")
    assert picked == ("//server/share", "reports")


def test_the_read_file_path_keeps_the_unc_marker():
    # The read lane joins root + "/" + relative and signs that string; the
    # preserved marker is what makes the PC resolve it as the share.
    root, relative = _pc_files_pick_root(UNC_LABEL_ROOTS, "share/a/b.txt")
    assert root + "/" + relative == "//server/share/a/b.txt"


# -- the gateway: a share call is rewritten, an unknown share is refused ------


def test_a_share_path_is_sent_as_a_label_relative_path(monkeypatch):
    result, recorder = _call(
        monkeypatch, "pc_list", {"path": "\\\\server\\share\\reports"}, roots=UNC_ROOTS,
    )
    assert result["status"] == "completed"
    sent = __import__("json").loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "share/reports"


def test_an_unregistered_share_is_refused_with_the_registered_list(monkeypatch):
    result, recorder = _call(
        monkeypatch, "pc_list", {"path": "\\\\server\\other\\x"}, roots=UNC_ROOTS,
    )
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert result["folders"] == UNC_ROOTS
    assert recorder.calls == []
