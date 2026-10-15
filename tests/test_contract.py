"""The integration against what it is built on: its library, the Home Assistant it is tested
with, its translations, icons and manifest, and what the repository may hold."""

from __future__ import annotations

import hashlib
import importlib.metadata
import ipaddress
import json
import re
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from homeassistant.const import __version__ as HA_VERSION
from packaging.version import Version

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "powerview_connect"
REPOSITORY = INTEGRATION.parents[1]


def _json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _translations(language: str) -> dict[str, Any]:
    return _json(INTEGRATION / "translations" / f"{language}.json")


def _paths(tree: Mapping[str, Any], prefix: str = "") -> Iterator[str]:
    """Every leaf of a JSON tree, as its dotted path."""
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _paths(cast(dict[str, Any], value), path)
        else:
            yield path


def test_danish_translates_exactly_what_english_does() -> None:
    assert set(_paths(_translations("da"))) == set(_paths(_translations("en")))


def test_the_placeholders_of_each_text_are_the_same_in_danish() -> None:
    english, danish = _translations("en"), _translations("da")
    for path in _paths(english):
        texts: list[str] = []
        for tree in (english, danish):
            node: Any = tree
            for key in path.split("."):
                node = node[key]
            texts.append(str(node))
        assert set(re.findall(r"\{\w+\}", texts[0])) == set(re.findall(r"\{\w+\}", texts[1])), path


def test_every_icon_belongs_to_a_translated_entity_or_action() -> None:
    icons = _json(INTEGRATION / "icons.json")
    names = _translations("en")
    for platform, entities in icons["entity"].items():
        for key in entities:
            assert key in names["entity"][platform], f"{platform}.{key}"
    assert set(icons["services"]) == set(names["services"])


def test_every_action_and_its_fields_are_named() -> None:
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))
    names = _translations("en")["services"]
    assert set(services) == set(names)
    for service, described in services.items():
        assert set(described["fields"]) == set(names[service]["fields"]), service


def _manifest() -> dict[str, Any]:
    return _json(INTEGRATION / "manifest.json")


def _from_a_branch(distribution: str) -> bool:
    """Whether `distribution` was installed from a URL, as a library's branch is, rather than
    from an index, as a release is (PEP 610)."""
    return importlib.metadata.distribution(distribution).read_text("direct_url.json") is not None


def test_the_manifest_pins_the_library_version_the_tests_run() -> None:
    installed = importlib.metadata.version("powerview_connect")
    if _from_a_branch("powerview_connect") or Version(installed).local is not None:
        pytest.skip(f"powerview_connect {installed} is built from a branch, so no release pins it yet")
    assert _manifest()["requirements"] == [f"powerview_connect=={installed}"]


def test_the_tests_pin_the_library_the_manifest_requires() -> None:
    pins = [line for line in (REPOSITORY / "requirements-test.txt").read_text(
        encoding="utf-8").splitlines() if line.startswith("powerview_connect==")]
    assert pins == _manifest()["requirements"]


def test_hacs_requires_the_home_assistant_the_tests_run() -> None:
    assert _json(REPOSITORY / "hacs.json")["homeassistant"] == HA_VERSION


def test_the_library_is_imported_from_its_package_not_from_the_integration() -> None:
    import powerview_connect

    assert INTEGRATION not in Path(powerview_connect.__file__).parents


def test_the_domain_is_the_folder_the_zip_and_the_librarys_name() -> None:
    """Home Assistant finds an integration by its folder, and HACS unpacks the zip into it."""
    from custom_components.powerview_connect.const import DOMAIN

    assert _manifest()["domain"] == DOMAIN == INTEGRATION.name == "powerview_connect"
    assert _json(REPOSITORY / "hacs.json")["filename"] == f"{DOMAIN}.zip"


def test_the_gateway_is_discovered_by_its_mdns_service() -> None:
    assert _manifest()["zeroconf"] == ["_PowerView-G3._tcp.local."]


POWERVIEW_ICONS = {
    "icon.png": "c16934bf1c7d17657a3ac214381f2398fde2fe0d1f41253044d1e57f4914eb3a",
    "icon@2x.png": "a11788bb84f2372f5d299ccba52143ef1929c973b2fe9c5b6b2b74e741347d1f",
}
"""The PowerView icon, as Home Assistant's brands repository has it for its own PowerView
integration (core_integrations/hunterdouglas_powerview): a brand icon shows the brand or the
product."""


@pytest.mark.parametrize(("name", "digest"), POWERVIEW_ICONS.items())
def test_the_brand_icon_is_the_powerview_icon(name: str, digest: str) -> None:
    assert hashlib.sha256((INTEGRATION / "brand" / name).read_bytes()).hexdigest() == digest


QUALITY_SCALE_RULES = frozenset({
    # Bronze
    "action-setup", "appropriate-polling", "brands", "common-modules",
    "config-flow-test-coverage", "config-flow", "dependency-transparency", "docs-actions",
    "docs-conditions", "docs-high-level-description", "docs-installation-instructions",
    "docs-removal-instructions", "docs-triggers", "entity-event-setup", "entity-unique-id",
    "has-entity-name", "runtime-data", "test-before-configure", "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions", "config-entry-unloading", "docs-configuration-parameters",
    "docs-installation-parameters", "entity-unavailable", "integration-owner",
    "log-when-unavailable", "parallel-updates", "reauthentication-flow", "test-coverage",
    # Gold
    "devices", "diagnostics", "discovery-update-info", "discovery", "docs-data-update",
    "docs-examples", "docs-known-limitations", "docs-supported-devices",
    "docs-supported-functions", "docs-troubleshooting", "docs-use-cases", "dynamic-devices",
    "entity-category", "entity-device-class", "entity-disabled-by-default",
    "entity-translations", "exception-translations", "icon-translations",
    "reconfiguration-flow", "repair-issues", "stale-devices",
    # Platinum
    "async-dependency", "inject-websession", "strict-typing",
})
"""The rules of Home Assistant's Integration Quality Scale, as its developer documentation lists
them. hassfest does not check this file for a custom integration, so this test does."""


def test_the_quality_scale_states_every_rule_and_explains_every_exemption() -> None:
    text = (INTEGRATION / "quality_scale.yaml").read_text(encoding="utf-8")
    rules = cast(dict[str, Any], yaml.safe_load(text)["rules"])
    assert set(rules) == QUALITY_SCALE_RULES
    for rule, state in rules.items():
        if state == "done":
            continue
        assert isinstance(state, dict), rule
        entry = cast(dict[str, Any], state)
        assert entry["status"] in ("done", "exempt", "todo"), rule
        if entry["status"] != "done":
            assert entry.get("comment"), f"{rule} is {entry['status']} without a reason"


ALLOWED_NETWORKS = [ipaddress.ip_network(net) for net in (
    "127.0.0.0/8", "0.0.0.0/32", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
"""Loopback, and the ranges RFC 5737 sets aside for documentation."""

ALLOWED_EMAILS = {"41898282+github-actions[bot]@users.noreply.github.com"}


def _tracked() -> list[tuple[str, str]]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPOSITORY, capture_output=True,
                            check=True).stdout.decode().split("\0")
    found: list[tuple[str, str]] = []
    for name in filter(None, listed):
        try:
            found.append((name, (REPOSITORY / name).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return found


def test_no_real_ip_address_or_email_address_is_tracked() -> None:
    found: list[str] = []
    for name, text in _tracked():
        for match in re.finditer(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])", text):
            try:
                address = ipaddress.ip_address(match.group(1))
            except ValueError:
                continue
            if not any(address in network for network in ALLOWED_NETWORKS):
                found.append(f"{name}: {address}")
        found += [f"{name}: {email}" for email in
                  set(re.findall(r"[\w.+-]+@[A-Za-z][\w-]*(?:\.[\w-]+)*\.[A-Za-z]{2,}\b", text)) - ALLOWED_EMAILS]
    assert found == []
