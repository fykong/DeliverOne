from __future__ import annotations

from server_py.agent.role_agents import AgentRoleSuite
from server_py.runtime.events import EventStore
from server_py.skills.registry import SkillRegistry
from server_py.skills.runtime import SkillRuntime


def _suite() -> AgentRoleSuite:
    runtime = SkillRuntime(SkillRegistry(), EventStore())
    return AgentRoleSuite(client=None, metrics=None, models=None, skills=runtime)


def test_vague_pattern_requirement_blocked_with_questions():
    suite = _suite()
    result = suite.clarify(
        "给文章加一个封面图字段",
        repository={"name": "conduit-realworld-example-app"},
        sandbox=None,
    )
    assert result["verdict"] == "blocked"  # 缺沙盒
    assert result["modelSource"] == "rules"
    # 模型不可用时,命中需求模式 Skill 的 clarifyChecklist 仍能产出具体追问
    assert result["questions"]
    assert any("字段" in question for question in result["questions"])


def test_contradictory_requirement_detected():
    suite = _suite()
    result = suite.clarify(
        "加一个阅读量字段保存到数据库，但是不要动后端",
        repository={"name": "conduit"},
        sandbox={"id": "sb", "repoPath": "x"},
    )
    assert result["verdict"] == "blocked"
    assert any(finding["id"] == "contradictory-scope" for finding in result["findings"])


def test_clear_requirement_passes_rules():
    suite = _suite()
    result = suite.clarify(
        "在文章详情页正文下方显示本文共 X 字预计阅读 Y 分钟，基于 body 前端计算，空文章显示 0 字",
        repository={"name": "conduit"},
        sandbox={"id": "sb", "repoPath": "x"},
    )
    assert result["verdict"] == "pass"


def test_reviewer_blocks_write_without_checkpoint():
    suite = _suite()
    plan = {
        "steps": [
            {"id": "s1", "toolId": "code.apply_patch", "riskLevel": "write", "requiresCheckpoint": False, "status": "pending"}
        ]
    }
    result = suite.review_tool_plan(plan)
    assert result["verdict"] == "blocked"
    assert any(finding["id"] == "write-without-checkpoint" for finding in result["findings"])
