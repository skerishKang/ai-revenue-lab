"""A direct os.environ write must not reach the next test (#7042)."""
from __future__ import annotations

import os


def test_a_direct_write_is_visible_to_the_test_that_makes_it() -> None:
    os.environ["X_LEAK"] = "1"
    assert os.environ["X_LEAK"] == "1"


def test_b_receives_the_environment_the_first_test_found() -> None:
    assert "X_LEAK" not in os.environ
