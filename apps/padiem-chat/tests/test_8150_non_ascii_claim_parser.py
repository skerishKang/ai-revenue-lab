"""#8150: the claim parsers read a tag beside non-ASCII device text."""
from __future__ import annotations

from app.pc_device_pairing_store import (
    drives_from_agent_name,
    pc_name_from_agent_name,
    shares_from_agent_name,
    tag_from_agent_name,
)

TAGGED = "pd-7a3f9c21 [C D] {Z:=//NAS/공유} 파디엠써피스"


def test_the_tag_is_found_next_to_korean_text():
    assert tag_from_agent_name(TAGGED) == "pd-7a3f9c21"


def test_drives_and_a_korean_share_are_read_from_the_same_name():
    assert drives_from_agent_name(TAGGED) == ["C:", "D:"]
    shares = shares_from_agent_name(TAGGED)
    assert len(shares) == 1
    assert shares[0]["path"] == "//NAS/공유"
    assert shares[0]["label"] == "공유"


def test_the_korean_machine_name_survives_decoration_removal():
    assert pc_name_from_agent_name(TAGGED) == "파디엠써피스"


def test_an_untagged_korean_name_is_not_a_claim():
    assert tag_from_agent_name("파디엠써피스") is None
    assert pc_name_from_agent_name("파디엠써피스") == "파디엠써피스"
