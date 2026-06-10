from __future__ import annotations

import time
from pathlib import Path

import server_py.skills.registry as registry_module
from server_py.skills.registry import SkillRegistry

SKILL_TEMPLATE = """---
id: {skill_id}
name: 测试技能
kind: requirement-pattern
triggers: [{trigger}]
clarifyChecklist:
  - "问题一？"
---

# 正文

## 硬限制

- 限制一。
"""


def _write_skill(catalog: Path, skill_id: str, trigger: str) -> Path:
    folder = catalog / skill_id
    folder.mkdir(parents=True)
    path = folder / "SKILL.md"
    path.write_text(SKILL_TEMPLATE.format(skill_id=skill_id, trigger=trigger), encoding="utf-8")
    return path


def _make_registry(tmp_path: Path, monkeypatch) -> SkillRegistry:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    legacy = tmp_path / "agent-skills.json"
    legacy.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(registry_module, "SKILLS_CATALOG_ROOT", catalog)
    monkeypatch.setattr(registry_module, "AGENT_SKILLS_PATH", legacy)
    monkeypatch.setattr(registry_module, "PROJECT_ROOT", tmp_path)
    return SkillRegistry()


def test_frontmatter_skill_discovered(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    _write_skill(catalog, "pattern-demo", "点赞")
    legacy = tmp_path / "agent-skills.json"
    legacy.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(registry_module, "SKILLS_CATALOG_ROOT", catalog)
    monkeypatch.setattr(registry_module, "AGENT_SKILLS_PATH", legacy)
    monkeypatch.setattr(registry_module, "PROJECT_ROOT", tmp_path)

    registry = SkillRegistry()
    skills = registry.list()
    assert [skill["id"] for skill in skills] == ["pattern-demo"]
    assert skills[0]["kind"] == "requirement-pattern"

    matched = registry.match("评论支持点赞")
    assert [skill["id"] for skill in matched] == ["pattern-demo"]
    assert matched[0]["clarifyChecklist"] == ["问题一？"]
    # 正文注入时去掉 frontmatter
    assert matched[0]["content"].lstrip().startswith("# 正文")


def test_hot_reload_new_skill_file(tmp_path, monkeypatch):
    registry = _make_registry(tmp_path, monkeypatch)
    assert registry.list() == []

    # 模拟比赛现场:运行中新增一个 SKILL.md,不重启即生效
    time.sleep(0.01)
    _write_skill(registry_module.SKILLS_CATALOG_ROOT, "pattern-live", "现场")
    matched = registry.match("现场加一个新模式")
    assert [skill["id"] for skill in matched] == ["pattern-live"]


def test_repository_context_matching(tmp_path, monkeypatch):
    registry = _make_registry(tmp_path, monkeypatch)
    _write_skill(registry_module.SKILLS_CATALOG_ROOT, "repo-profile-demo", "conduit")
    assert registry.match("加个字段") == []
    matched = registry.match("加个字段", context_text="conduit-realworld-example-app")
    assert [skill["id"] for skill in matched] == ["repo-profile-demo"]


def test_real_catalog_loads_pattern_skills():
    registry = SkillRegistry()
    ids = {skill["id"] for skill in registry.list()}
    assert {"agent-delivery-flow", "repo-context", "conduit-repo-profile", "pattern-add-field-fullstack"} <= ids
    field_skill = registry.get("pattern-add-field-fullstack")
    assert field_skill is not None
    assert field_skill["kind"] == "requirement-pattern"
    assert field_skill["clarifyChecklist"]
    assert set(field_skill["locateStrategy"].keys()) == {"backend", "frontend"}
