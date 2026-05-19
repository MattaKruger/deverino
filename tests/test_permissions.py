from __future__ import annotations

from harness_poc.core.permissions import SkillPermissions


def test_default_permissions_are_none() -> None:
    p = SkillPermissions()
    assert p.blackboard == "none"
    assert p.workspace == "none"
    assert not p.can_read_blackboard
    assert not p.can_write_blackboard
    assert not p.can_read_workspace
    assert not p.can_write_workspace


def test_from_yaml_reads_valid_values() -> None:
    p = SkillPermissions.from_yaml({"blackboard": "read", "workspace": "read_write"})
    assert p.blackboard == "read"
    assert p.workspace == "read_write"
    assert p.can_read_blackboard
    assert not p.can_write_blackboard
    assert p.can_read_workspace
    assert p.can_write_workspace


def test_from_yaml_rejects_invalid_values() -> None:
    p = SkillPermissions.from_yaml({"blackboard": "admin", "workspace": "full"})
    assert p.blackboard == "none"
    assert p.workspace == "none"


def test_from_yaml_handles_none() -> None:
    p = SkillPermissions.from_yaml(None)
    assert p.blackboard == "none"
    assert p.workspace == "none"


def test_read_write_implies_read() -> None:
    p = SkillPermissions(blackboard="read_write", workspace="read_write")
    assert p.can_read_blackboard
    assert p.can_write_blackboard
    assert p.can_read_workspace
    assert p.can_write_workspace


def test_read_permission_allows_read_but_not_write() -> None:
    p = SkillPermissions(blackboard="read", workspace="read")
    assert p.can_read_blackboard
    assert not p.can_write_blackboard
    assert p.can_read_workspace
    assert not p.can_write_workspace
