"""Tests of what a test build works out."""
import pytest

from test_build import next_patch


@pytest.mark.parametrize(("released", "following"), [("1.2.0", "1.2.1"), ("1.2.9", "1.2.10")])
def test_without_a_draft_a_test_build_is_of_the_patch_after_the_last_release(
    released: str, following: str, capsys: pytest.CaptureFixture[str]
) -> None:
    next_patch(released)
    assert capsys.readouterr().out == f"{following}\n"
