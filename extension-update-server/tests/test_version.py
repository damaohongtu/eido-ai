import pytest

from extension_updater.version import ChromeVersion


def test_chrome_versions_compare_by_numeric_components() -> None:
    assert ChromeVersion.parse("1.2") == ChromeVersion.parse("1.2.0.0")
    assert ChromeVersion.parse("1.2.10") > ChromeVersion.parse("1.2.9.9999")


@pytest.mark.parametrize("value", ["", "1.2.3.4.5", "1.02", "65536", "1.a", "0"])
def test_invalid_release_versions_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        ChromeVersion.parse(value)


def test_zero_is_allowed_for_initial_client_update_check() -> None:
    assert ChromeVersion.parse("0", allow_zero=True).comparable == (0, 0, 0, 0)

