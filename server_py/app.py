from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server_py.core.json_io import now_iso
from server_py.services import services
from server_py.tools.types import ToolContext

app = FastAPI(title="DeliverOne Agent Runtime")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RepoGithubBody(BaseModel):
    conversationId: str
    repoUrl: str


class RepoLocalBody(BaseModel):
    conversationId: str
    sourcePath: str


class RequirementBody(BaseModel):
    conversationId: str
    requirement: str | None = None


class SkillSelectBody(BaseModel):
    conversationId: str
    requirement: str


class ConfirmPlanBody(BaseModel):
    conversationId: str


class ExecuteBody(BaseModel):
    conversationId: str
    requirement: str | None = None


class ToolPlanBody(BaseModel):
    conversationId: str
    requirement: str | None = None
    steps: list[dict[str, Any]] | None = None


class ToolPlanDecisionBody(BaseModel):
    conversationId: str
    planId: str | None = None


class ToolPlanEditBody(BaseModel):
    conversationId: str
    operation: str
    planId: str | None = None
    stepId: str | None = None
    reason: str | None = None
    title: str | None = None
    purpose: str | None = None
    input: dict[str, Any] | None = None
    targetOrder: int | None = None


class ToolPlanRewriteBody(BaseModel):
    conversationId: str
    planId: str | None = None
    instruction: str


class TaskStateEditBody(BaseModel):
    conversationId: str
    operation: str
    stageId: str | None = None
    note: str | None = None
    actionIds: list[str] | None = None


class OrchestratorBody(BaseModel):
    conversationId: str
    action: str
    requirement: str | None = None
    planId: str | None = None


class PreviewStartBody(BaseModel):
    command: str
    conversationId: str | None = None
    ports: list[int] | None = None


class PreviewStopBody(BaseModel):
    conversationId: str | None = None
    processId: str


class PreviewSmokeBody(BaseModel):
    conversationId: str
    port: int
    path: str = "/"
    timeoutSeconds: int = 30
    expectedTexts: list[str] = []
    requiredSelectors: list[str] = []


class VerificationRunBody(BaseModel):
    conversationId: str
    commands: dict[str, str] | None = None
    timeoutSeconds: int = 180


class ApprovalGrantBody(BaseModel):
    conversationId: str
    toolId: str
    riskLevel: str = "command"
    scope: str = "session"
    command: str | None = None
    note: str | None = None
    requestEventId: str | None = None


class ApprovalRevokeBody(BaseModel):
    conversationId: str
    grantId: str


class ApprovalDenyBody(BaseModel):
    conversationId: str
    toolId: str
    riskLevel: str = "command"
    reason: str
    requestEventId: str | None = None
    command: str | None = None


class ToolRunBody(BaseModel):
    conversationId: str
    toolId: str
    input: Any = {}
    approved: bool = False
    userInitiated: bool = False


class MCPRunBody(BaseModel):
    conversationId: str
    toolId: str
    input: Any = {}
    approved: bool = False
    userInitiated: bool = False


class MCPDiscoverBody(BaseModel):
    timeoutSeconds: int = 8


class MCPReplayBody(BaseModel):
    conversationId: str
    historyEntryId: str


class RollbackCheckpointBody(BaseModel):
    conversationId: str
    checkpointId: str


class RollbackCheckpointFileBody(BaseModel):
    conversationId: str
    checkpointId: str
    relativePath: str


class RollbackCheckpointHunkBody(BaseModel):
    conversationId: str
    checkpointId: str
    relativePath: str
    hunkIndex: int


class RollbackOriginalBody(BaseModel):
    conversationId: str
    confirmed: bool = False


class DeliveryPackageBody(BaseModel):
    conversationId: str


class DeliveryApplyBody(BaseModel):
    conversationId: str
    confirmed: bool = False


class DeliverySubmitBody(BaseModel):
    conversationId: str
    confirmed: bool = False
    title: str | None = None
    baseBranch: str | None = None


class MemoryFlagBody(BaseModel):
    itemId: str
    value: bool = True


class MemoryManualBody(BaseModel):
    conversationId: str
    itemId: str | None = None
    title: str
    content: str
    kind: str = "decision"
    tags: list[str] = []
    pinned: bool = False
    importance: float = 2.8


class MemoryPatchDraftBody(BaseModel):
    conversationId: str
    instruction: str = ""
    maxItems: int = 4


class MemoryPatchApplyBody(BaseModel):
    conversationId: str
    draftId: str | None = None
    candidate: dict[str, Any]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "name": "DeliverOne", "runtime": "python-agent", "time": now_iso()}


@app.get("/api/models")
def get_models() -> dict[str, Any]:
    return services.models.get_settings()


@app.put("/api/models")
def save_models(payload: dict[str, Any]) -> dict[str, Any]:
    return services.models.save_settings(payload)


@app.get("/api/skills")
def get_skills() -> list[dict[str, Any]]:
    return services.skills.list()


@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: str) -> dict[str, Any]:
    skill = services.skills.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    return skill


@app.post("/api/skills/select")
def select_skills(body: SkillSelectBody) -> list[dict[str, Any]]:
    return services.skill_runtime.select(body.conversationId, body.requirement)


@app.get("/api/tools")
def get_tools() -> list[dict[str, Any]]:
    return services.tool_runtime.list()


@app.get("/api/mcp/manifest")
def get_mcp_manifest() -> dict[str, Any]:
    return services.mcp.manifest()


@app.get("/api/mcp/tools")
def get_mcp_tools(query: str | None = None) -> list[dict[str, Any]]:
    return services.mcp.list_tools(query)


@app.get("/api/mcp/servers")
def get_mcp_servers() -> list[dict[str, Any]]:
    return services.mcp.server_statuses()


@app.get("/api/mcp/config")
def get_mcp_config() -> dict[str, Any]:
    return services.mcp.config()


@app.put("/api/mcp/config")
def save_mcp_config(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return services.mcp.save_config(payload)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/mcp/config/validate")
def validate_mcp_config(payload: dict[str, Any]) -> dict[str, Any]:
    return services.mcp.validate_config(payload)


@app.post("/api/mcp/discover")
def discover_mcp_tools(body: MCPDiscoverBody) -> dict[str, Any]:
    try:
        return services.mcp.discover_external_tools(body.timeoutSeconds)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/mcp/history/{conversation_id}")
def get_mcp_history(conversation_id: str, toolId: str | None = None, limit: int = Query(80, ge=1, le=200)) -> list[dict[str, Any]]:
    return services.mcp.history(conversation_id, toolId, limit)


@app.get("/api/policy")
def get_policy() -> dict[str, Any]:
    return services.policy.describe()


@app.get("/api/policy/matrix")
def get_policy_matrix() -> list[dict[str, Any]]:
    return services.policy.matrix()


@app.get("/api/approvals/{conversation_id}")
def get_approvals(conversation_id: str) -> list[dict[str, Any]]:
    return services.approvals.list(conversation_id)


@app.post("/api/approvals/grant")
def grant_approval(body: ApprovalGrantBody) -> dict[str, Any]:
    try:
        return services.approvals.grant(
            body.conversationId,
            body.toolId,
            body.riskLevel,
            body.scope,
            body.command,
            body.note,
            body.requestEventId,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/approvals/deny")
def deny_approval(body: ApprovalDenyBody) -> dict[str, Any]:
    try:
        return services.approvals.deny(body.conversationId, body.toolId, body.riskLevel, body.reason, body.requestEventId, body.command)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/approvals/revoke")
def revoke_approval(body: ApprovalRevokeBody) -> dict[str, Any]:
    try:
        return services.approvals.revoke(body.conversationId, body.grantId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/runtime/state-machine")
def get_state_machine() -> dict[str, Any]:
    return services.state_machine.describe()


@app.post("/api/agent/orchestrator")
def agent_orchestrator(body: OrchestratorBody) -> dict[str, Any]:
    repository, sandbox = _context_for(body.conversationId)
    try:
        return services.orchestrator.run(
            conversation_id=body.conversationId,
            action=body.action,
            repository=repository,
            sandbox=sandbox,
            requirement=body.requirement,
            plan_id=body.planId,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class AutopilotBody(BaseModel):
    conversationId: str
    requirement: str
    maxRounds: int = 12


@app.post("/api/agent/autopilot")
def agent_autopilot(body: AutopilotBody) -> dict[str, Any]:
    if not body.requirement.strip():
        raise HTTPException(status_code=400, detail="需求不能为空。")
    repository, sandbox = _context_for(body.conversationId)
    try:
        return services.orchestrator.autopilot(
            conversation_id=body.conversationId,
            requirement=body.requirement,
            repository=repository,
            sandbox=sandbox,
            max_rounds=max(1, min(body.maxRounds, 20)),
            delivery=services.delivery,
            submission=services.git_submission,
            verification_runner=services.verification_runner,
            preview_smoke=services.preview_smoke,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/sandboxes/github")
def create_github_sandbox(body: RepoGithubBody) -> dict[str, Any]:
    try:
        sandbox = services.sandboxes.create_from_github(body.conversationId, body.repoUrl)
        repository = services.profiler.profile("repo_current", "github", body.repoUrl, sandbox["repoPath"])
        services.conversations.record_context(body.conversationId, repository, sandbox)
        return {"sandbox": sandbox, "repository": repository}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/sandboxes/local")
def create_local_sandbox(body: RepoLocalBody) -> dict[str, Any]:
    try:
        sandbox = services.sandboxes.create_from_local_path(body.conversationId, body.sourcePath)
        repository = services.profiler.profile("repo_current", "local", body.sourcePath, sandbox["repoPath"])
        services.conversations.record_context(body.conversationId, repository, sandbox)
        return {"sandbox": sandbox, "repository": repository}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/preflight")
def preflight(body: RequirementBody) -> dict[str, Any]:
    repository, sandbox = _context_for(body.conversationId)
    return services.preflight.run(body.conversationId, body.requirement, repository, sandbox)


@app.post("/api/agent/planning")
def agent_planning(body: RequirementBody) -> dict[str, Any]:
    if not body.requirement:
        raise HTTPException(status_code=400, detail="需求不能为空。")
    repository, sandbox = _context_for(body.conversationId)
    return services.agent_workflow.plan(body.conversationId, body.requirement, repository, sandbox)


@app.post("/api/agent/confirm-plan")
def confirm_plan(body: ConfirmPlanBody) -> dict[str, Any]:
    try:
        return services.agent_workflow.confirm_plan(body.conversationId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agent/execute")
def prepare_execution(body: ExecuteBody) -> dict[str, Any]:
    repository, sandbox = _context_for(body.conversationId)
    state = services.conversations.get(body.conversationId)
    requirement = body.requirement or state.get("lastRequirement")
    if not requirement:
        raise HTTPException(status_code=400, detail="执行阶段缺少需求。")

    try:
        services.events.append(body.conversationId, "turn.started", {"phase": "execution"})
        turn = services.executor_agent.prepare(body.conversationId, requirement, repository, sandbox, services.tool_runtime.list())
        services.conversations.record_turn(body.conversationId, turn, turn["phase"], turn["reply"])
        services.memory.record_agent_turn(body.conversationId, turn)
        services.events.append(body.conversationId, "agent.message", {"content": turn["reply"], "phase": turn["phase"]}, actor="agent")
        services.events.append(body.conversationId, "turn.completed", {"phase": turn["phase"]})
        return turn
    except Exception as error:
        services.events.append(body.conversationId, "turn.failed", {"phase": "execution", "error": str(error)})
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agent/tool-plan")
def create_tool_plan(body: ToolPlanBody) -> dict[str, Any]:
    repository, sandbox = _context_for(body.conversationId)
    state = services.conversations.get(body.conversationId)
    requirement = body.requirement or state.get("lastRequirement")
    if not requirement:
        raise HTTPException(status_code=400, detail="生成工具调用计划需要需求。")
    try:
        return services.tool_call_plans.create_plan(
            conversation_id=body.conversationId,
            requirement=requirement,
            repository=repository,
            sandbox=sandbox,
            tools=services.tool_runtime.list(),
            requested_steps=body.steps,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/agent/tool-plan/{conversation_id}")
def get_tool_plan(conversation_id: str) -> dict[str, Any]:
    plan = services.tool_call_plans.get_plan(conversation_id)
    if not plan:
        raise HTTPException(status_code=404, detail="当前对话还没有工具调用计划。")
    return plan


@app.post("/api/agent/tool-plan/approve")
def approve_tool_plan(body: ToolPlanDecisionBody) -> dict[str, Any]:
    try:
        return services.tool_call_plans.approve_plan(body.conversationId, body.planId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agent/tool-plan/execute")
def execute_tool_plan(body: ToolPlanDecisionBody) -> dict[str, Any]:
    repository, sandbox = _context_for(body.conversationId)
    try:
        return services.orchestrator.run(
            conversation_id=body.conversationId,
            action="execute_tool_plan",
            repository=repository,
            sandbox=sandbox,
            plan_id=body.planId,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agent/tool-plan/edit")
def edit_tool_plan(body: ToolPlanEditBody) -> dict[str, Any]:
    try:
        plan = services.tool_call_plans.edit_plan(
            conversation_id=body.conversationId,
            operation=body.operation,
            plan_id=body.planId,
            step_id=body.stepId,
            reason=body.reason,
            title=body.title,
            purpose=body.purpose,
            input_payload=body.input,
            target_order=body.targetOrder,
        )
        memory = services.memory.snapshot(
            body.conversationId,
            repository=plan.get("repository"),
            requirement=plan.get("requirement"),
        )
        review = services.roles.review_tool_plan(plan, body.conversationId, memory_snapshot=memory)
        plan = services.tool_call_plans.append_audit(body.conversationId, review, plan["id"])
        latest_edit = plan.get("editHistory", [])[-1] if isinstance(plan.get("editHistory"), list) and plan.get("editHistory") else None
        task_state = services.task_state_machine.record_tool_plan_edit(body.conversationId, latest_edit or {}, review)
        if task_state:
            services.events.append(
                body.conversationId,
                "task_state.edited",
                {
                    "operation": "tool_plan_edit",
                    "stageId": "tool-plan",
                    "latestEdit": latest_edit,
                    "reviewVerdict": review.get("verdict"),
                    "taskState": task_state,
                },
                actor="user",
            )
        services.events.append(
            body.conversationId,
            "agent.role.reviewer",
            {
                "verdict": review["verdict"],
                "summary": review.get("summary"),
                "recommendation": review.get("recommendation"),
                "findings": review["findings"],
                "planId": plan["id"],
                "afterEdit": True,
                "latestEdit": latest_edit,
            },
            actor="agent",
        )
        return plan
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agent/tool-plan/rewrite")
def rewrite_tool_plan(body: ToolPlanRewriteBody) -> dict[str, Any]:
    try:
        current_plan = services.tool_call_plans.get_plan(body.conversationId)
        if not current_plan:
            raise RuntimeError("当前对话还没有工具调用计划。")
        if body.planId and current_plan.get("id") != body.planId:
            raise RuntimeError("工具计划 id 不匹配。")
        memory = services.memory.snapshot(
            body.conversationId,
            repository=current_plan.get("repository"),
            requirement=current_plan.get("requirement"),
        )
        tools = services.tool_runtime.list()
        draft = services.tool_plan_drafter.rewrite(
            conversation_id=body.conversationId,
            current_plan=current_plan,
            instruction=body.instruction,
            tools=tools,
            memory_snapshot=memory,
        )
        if not draft.get("steps"):
            raise RuntimeError(draft.get("fallbackReason") or "模型没有返回可执行的重写计划。")
        plan = services.tool_call_plans.rewrite_plan(
            conversation_id=body.conversationId,
            plan_id=body.planId,
            tools=tools,
            requested_steps=draft["steps"],
            instruction=body.instruction,
            generation={
                "source": "rewrite",
                "rawResponse": draft.get("rawResponse", ""),
                "fallbackReason": draft.get("fallbackReason"),
                "summary": draft.get("summary") or body.instruction,
            },
            audits=[draft["audit"]] if isinstance(draft.get("audit"), dict) else [],
        )
        review_memory = services.memory.snapshot(
            body.conversationId,
            repository=plan.get("repository"),
            requirement=plan.get("requirement"),
        )
        review = services.roles.review_tool_plan(plan, body.conversationId, memory_snapshot=review_memory)
        plan = services.tool_call_plans.append_audit(body.conversationId, review, plan["id"])
        latest_edit = plan.get("editHistory", [])[-1] if isinstance(plan.get("editHistory"), list) and plan.get("editHistory") else None
        task_state = services.task_state_machine.record_tool_plan_edit(body.conversationId, latest_edit or {}, review)
        if task_state:
            services.events.append(
                body.conversationId,
                "task_state.edited",
                {
                    "operation": "tool_plan_rewrite",
                    "stageId": "tool-plan",
                    "latestEdit": latest_edit,
                    "reviewVerdict": review.get("verdict"),
                    "taskState": task_state,
                },
                actor="user",
            )
        services.events.append(
            body.conversationId,
            "agent.role.reviewer",
            {
                "verdict": review["verdict"],
                "summary": review.get("summary"),
                "recommendation": review.get("recommendation"),
                "findings": review["findings"],
                "planId": plan["id"],
                "afterRewrite": True,
                "latestEdit": latest_edit,
            },
            actor="agent",
        )
        return plan
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    return services.agent_workflow.get_conversation(conversation_id)


@app.get("/api/conversations/{conversation_id}/state")
def get_conversation_state(conversation_id: str) -> dict[str, Any]:
    state = services.conversations.get(conversation_id)
    return {
        "conversationId": conversation_id,
        "phase": state.get("phase"),
        "lastTransition": state.get("lastTransition"),
        "stateTransitions": state.get("stateTransitions", []),
        "stateWarnings": state.get("stateWarnings", []),
    }


@app.get("/api/conversations")
def list_conversations() -> list[dict[str, Any]]:
    return services.conversations.list()


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, Any]:
    try:
        # 删除前先停掉该会话的预览进程,否则进程占用文件会导致 rmtree 失败。
        for process in services.processes.list():
            if process.get("conversationId") == conversation_id and process.get("status") == "running":
                try:
                    services.processes.stop(process.get("id"), conversation_id)
                except Exception:
                    pass
        return services.conversations.delete(conversation_id)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/conversations/cleanup")
def cleanup_conversations() -> dict[str, Any]:
    try:
        return services.conversations.cleanup_orphans()
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/conversations/{conversation_id}/memory")
def get_memory(conversation_id: str) -> dict[str, Any]:
    repository, _sandbox = _context_for(conversation_id)
    return services.memory.snapshot(conversation_id, repository=repository)


@app.get("/api/runtime/snapshot/{conversation_id}")
def get_runtime_snapshot(conversation_id: str) -> dict[str, Any]:
    state = services.conversations.get(conversation_id)
    plan = services.tool_call_plans.get_plan(conversation_id)
    checkpoints = services.checkpoints.list(conversation_id)
    events = services.events.list(conversation_id, 200)
    processes = [process for process in services.processes.list() if process.get("conversationId") == conversation_id]
    repository, sandbox = _context_for(conversation_id)
    diff = None
    if sandbox:
        try:
            diff = services.diff.current(conversation_id, sandbox["repoPath"])
        except Exception as error:
            diff = {"conversationId": conversation_id, "kind": "current", "summary": str(error), "fileCount": 0, "files": []}
    try:
        memory = services.memory.snapshot(conversation_id, repository=repository, requirement=state.get("lastRequirement"))
    except Exception:
        memory = None
    return services.runtime_snapshot.build(
        state=state,
        tool_plan=plan,
        checkpoints=checkpoints,
        events=events,
        processes=processes,
        diff=diff,
        memory=memory,
    )


@app.get("/api/runtime/task-state/{conversation_id}")
def get_task_state_machine(conversation_id: str) -> dict[str, Any]:
    return get_runtime_snapshot(conversation_id).get("stateMachine", {})


@app.post("/api/runtime/task-state/edit")
def edit_task_state_machine(body: TaskStateEditBody) -> dict[str, Any]:
    try:
        result = services.task_state_machine.edit(
            conversation_id=body.conversationId,
            operation=body.operation,
            stage_id=body.stageId,
            note=body.note,
            action_ids=body.actionIds,
            actor="user",
        )
        services.events.append(
            body.conversationId,
            "task_state.edited",
            {
                "operation": body.operation,
                "stageId": body.stageId,
                "note": body.note,
                "actionIds": body.actionIds or [],
                "path": result.get("path"),
            },
            actor="user",
        )
        return get_runtime_snapshot(body.conversationId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/runtime/sandbox/{conversation_id}")
def get_sandbox_runtime(conversation_id: str) -> dict[str, Any]:
    state = services.conversations.get(conversation_id)
    checkpoints = services.checkpoints.list(conversation_id)
    events = services.events.list(conversation_id, 200)
    processes = [process for process in services.processes.list() if process.get("conversationId") == conversation_id]
    _repository, sandbox = _context_for(conversation_id)
    files = None
    diff = None
    if sandbox:
        try:
            files = services.file_browser.list_tree(sandbox["repoPath"])
        except Exception as error:
            files = {"rootPath": sandbox.get("repoPath"), "items": [], "truncated": False, "error": str(error)}
        try:
            diff = services.diff.current(conversation_id, sandbox["repoPath"])
        except Exception as error:
            diff = {"conversationId": conversation_id, "kind": "current", "summary": str(error), "fileCount": 0, "files": []}
    return services.sandbox_runtime.build(
        state=state,
        processes=processes,
        checkpoints=checkpoints,
        events=events,
        diff=diff,
        files=files,
    )


@app.post("/api/memory/pin")
def pin_memory(body: MemoryFlagBody) -> dict[str, Any]:
    item = services.memory.long_term_store.pin(body.itemId, body.value)
    if not item:
        raise HTTPException(status_code=404, detail="长期记忆不存在。")
    return {"ok": True, "item": item}


@app.post("/api/memory/forget")
def forget_memory(body: MemoryFlagBody) -> dict[str, Any]:
    item = services.memory.long_term_store.forget(body.itemId, body.value)
    if not item:
        raise HTTPException(status_code=404, detail="长期记忆不存在。")
    return {"ok": True, "item": item}


@app.post("/api/memory/manual")
def upsert_manual_memory(body: MemoryManualBody) -> dict[str, Any]:
    repository, _sandbox = _context_for(body.conversationId)
    try:
        item = services.memory.long_term_store.upsert_manual(
            conversation_id=body.conversationId,
            repository=repository,
            item_id=body.itemId,
            title=body.title,
            content=body.content,
            kind=body.kind,
            tags=body.tags,
            pinned=body.pinned,
            importance=body.importance,
        )
        services.events.append(
            body.conversationId,
            "memory.manual.upserted",
            {
                "itemId": item.get("id"),
                "title": item.get("title"),
                "kind": item.get("kind"),
                "namespace": item.get("namespace"),
                "manual": True,
            },
            actor="user",
        )
        return {"ok": True, "item": item}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/memory/patch/draft")
def draft_memory_patch(body: MemoryPatchDraftBody) -> dict[str, Any]:
    repository, _sandbox = _context_for(body.conversationId)
    try:
        draft = services.memory_patches.draft(
            conversation_id=body.conversationId,
            repository=repository,
            instruction=body.instruction,
            max_items=max(1, min(body.maxItems, 8)),
        )
        services.events.append(
            body.conversationId,
            "memory.patch.drafted",
            {
                "draftId": draft.get("id"),
                "source": draft.get("source"),
                "candidateCount": len(draft.get("candidates", [])),
                "summary": draft.get("summary"),
            },
            actor="agent",
        )
        return draft
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/memory/patch/apply")
def apply_memory_patch(body: MemoryPatchApplyBody) -> dict[str, Any]:
    repository, _sandbox = _context_for(body.conversationId)
    candidate = body.candidate
    try:
        item = services.memory.long_term_store.upsert_manual(
            conversation_id=body.conversationId,
            repository=repository,
            item_id=candidate.get("itemId"),
            title=str(candidate.get("title") or ""),
            content=str(candidate.get("content") or ""),
            kind=str(candidate.get("kind") or "decision"),
            tags=candidate.get("tags") if isinstance(candidate.get("tags"), list) else [],
            pinned=bool(candidate.get("pinned", False)),
            importance=float(candidate.get("importance") or 2.8),
        )
        services.events.append(
            body.conversationId,
            "memory.patch.applied",
            {
                "draftId": body.draftId,
                "candidateId": candidate.get("id"),
                "itemId": item.get("id"),
                "title": item.get("title"),
                "kind": item.get("kind"),
                "namespace": item.get("namespace"),
                "patchSummary": (item.get("lastPatch") or {}).get("summary"),
            },
            actor="user",
        )
        return {"ok": True, "item": item}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/events/{conversation_id}")
def get_events(conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return services.events.list(conversation_id, limit)


@app.get("/api/metrics/{conversation_id}")
def get_metrics(conversation_id: str, limit: int = 500) -> dict[str, Any]:
    return {
        "summary": services.metrics.summary(conversation_id),
        "items": services.metrics.list(conversation_id, limit),
    }


@app.get("/api/checkpoints/{conversation_id}")
def get_checkpoints(conversation_id: str) -> list[dict[str, Any]]:
    return services.checkpoints.list(conversation_id)


@app.get("/api/sandbox/files/{conversation_id}")
def get_sandbox_files(conversation_id: str) -> dict[str, Any]:
    _repository, sandbox = _context_for(conversation_id)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    try:
        result = services.file_browser.list_tree(sandbox["repoPath"])
        services.events.append(conversation_id, "sandbox.file_tree.read", {"itemCount": len(result["items"])}, actor="runtime")
        return result
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/sandbox/file/{conversation_id}")
def read_sandbox_file(conversation_id: str, path: str = Query(...)) -> dict[str, Any]:
    _repository, sandbox = _context_for(conversation_id)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    try:
        result = services.file_browser.read_file(sandbox["repoPath"], path)
        services.events.append(conversation_id, "sandbox.file.read", {"path": result["path"], "size": result["size"]}, actor="runtime")
        return result
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/diff/current/{conversation_id}")
def get_current_diff(conversation_id: str) -> dict[str, Any]:
    _repository, sandbox = _context_for(conversation_id)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    try:
        result = services.diff.current(conversation_id, sandbox["repoPath"])
        services.events.append(conversation_id, "sandbox.diff.current.read", {"fileCount": result["fileCount"]}, actor="runtime")
        return result
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/diff/file/{conversation_id}")
def get_file_diff(conversation_id: str, path: str = Query(...)) -> dict[str, Any]:
    _repository, sandbox = _context_for(conversation_id)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    try:
        result = services.diff.file(conversation_id, sandbox["repoPath"], path)
        services.events.append(conversation_id, "sandbox.diff.file.read", {"path": path, "fileCount": result["fileCount"]}, actor="runtime")
        return result
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/diff/checkpoint/{conversation_id}")
def get_checkpoint_diff(conversation_id: str, checkpointId: str = Query(...)) -> dict[str, Any]:
    try:
        result = services.diff.checkpoint(conversation_id, checkpointId)
        services.events.append(conversation_id, "sandbox.diff.checkpoint.read", {"checkpointId": checkpointId, "fileCount": result["fileCount"]}, actor="runtime")
        return result
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/tools/run")
def run_tool(body: ToolRunBody) -> dict[str, Any]:
    _repository, sandbox = _context_for(body.conversationId)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    payload = body.input if isinstance(body.input, dict) else {"value": body.input}
    if body.approved:
        payload = {**payload, "approved": True}
    context = ToolContext(
        conversation_id=body.conversationId,
        sandbox_id=sandbox["id"],
        repo_path=sandbox["repoPath"],
        user_initiated=body.userInitiated,
    )
    return services.tool_runtime.run(body.toolId, payload, context)


@app.post("/api/mcp/run")
def run_mcp_tool(body: MCPRunBody) -> dict[str, Any]:
    _repository, sandbox = _context_for(body.conversationId)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    payload = body.input if isinstance(body.input, dict) else {"value": body.input}
    if body.approved:
        payload = {**payload, "approved": True}
    context = ToolContext(
        conversation_id=body.conversationId,
        sandbox_id=sandbox["id"],
        repo_path=sandbox["repoPath"],
        user_initiated=body.userInitiated,
    )
    return services.mcp.run_tool(body.toolId, payload, context)


@app.post("/api/mcp/replay")
def replay_mcp_tool(body: MCPReplayBody) -> dict[str, Any]:
    _repository, sandbox = _context_for(body.conversationId)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    context = ToolContext(
        conversation_id=body.conversationId,
        sandbox_id=sandbox["id"],
        repo_path=sandbox["repoPath"],
        user_initiated=True,
    )
    try:
        return services.mcp.replay_history_entry(body.conversationId, body.historyEntryId, context)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/rollback/checkpoint")
def rollback_checkpoint(body: RollbackCheckpointBody) -> dict[str, Any]:
    try:
        return services.rollback.restore_checkpoint(body.conversationId, body.checkpointId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/rollback/checkpoint-file")
def rollback_checkpoint_file(body: RollbackCheckpointFileBody) -> dict[str, Any]:
    try:
        return services.rollback.restore_checkpoint_file(body.conversationId, body.checkpointId, body.relativePath)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/rollback/checkpoint-hunk")
def rollback_checkpoint_hunk(body: RollbackCheckpointHunkBody) -> dict[str, Any]:
    try:
        return services.rollback.restore_checkpoint_hunk(body.conversationId, body.checkpointId, body.relativePath, body.hunkIndex)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/rollback/original")
def rollback_original(body: RollbackOriginalBody) -> dict[str, Any]:
    _repository, sandbox = _context_for(body.conversationId)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    try:
        return services.rollback.hard_reset(body.conversationId, sandbox["repoPath"], body.confirmed)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/rollback/reports/{conversation_id}")
def rollback_reports(conversation_id: str) -> list[dict[str, Any]]:
    try:
        return services.rollback.list_reports(conversation_id)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/rollback/report/{conversation_id}/{report_id}")
def rollback_report(conversation_id: str, report_id: str) -> dict[str, Any]:
    try:
        return services.rollback.get_report(conversation_id, report_id)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/delivery/package")
def delivery_package(body: DeliveryPackageBody) -> dict[str, Any]:
    try:
        state = services.conversations.get(body.conversationId)
        plan = services.tool_call_plans.sync_latest_reports(body.conversationId) or services.tool_call_plans.get_plan(body.conversationId)
        checkpoints = services.checkpoints.list(body.conversationId)
        events = services.events.list(body.conversationId, 300)
        report = services.delivery.package(body.conversationId, state, plan, checkpoints, events)
        services.memory.record_delivery_report(body.conversationId, report)
        return report
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/delivery/preview/{conversation_id}")
def delivery_preview(conversation_id: str) -> dict[str, Any]:
    try:
        return services.delivery.preview(conversation_id)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/delivery/apply-to-source")
def delivery_apply_to_source(body: DeliveryApplyBody) -> dict[str, Any]:
    try:
        state = services.conversations.get(body.conversationId)
        result = services.delivery.apply_to_source(body.conversationId, state, body.confirmed)
        services.memory.record_decision(body.conversationId, "已应用回本地原仓库", result.get("summary", ""))
        return result
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/delivery/submit")
def delivery_submit(body: DeliverySubmitBody) -> dict[str, Any]:
    try:
        state = services.conversations.get(body.conversationId)
        plan = services.tool_call_plans.get_plan(body.conversationId)
        record = services.git_submission.submit(
            body.conversationId,
            state,
            plan,
            body.confirmed,
            title=body.title,
            base_branch=body.baseBranch,
        )
        services.memory.record_decision(
            body.conversationId,
            "已生成提测分支",
            f"分支 {record.get('branch')}，模式 {record.get('mode')}，PR：{record.get('pullRequest', {}).get('url') or '未创建'}",
        )
        services.memory.record_solution(
            body.conversationId,
            state.get("repository"),
            str(record.get("requirement") or state.get("lastRequirement") or ""),
            [str(item) for item in ((plan or {}).get("evidence", {}) or {}).get("diffFiles", [])][:12],
            "提测时验证门禁已通过",
            branch=record.get("branch"),
            commit_sha=record.get("commitSha"),
        )
        return record
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/delivery/submission/{conversation_id}")
def delivery_submission(conversation_id: str) -> dict[str, Any]:
    record = services.git_submission.latest(conversation_id)
    return {"conversationId": conversation_id, "exists": bool(record), "submission": record}


@app.post("/api/preview/start")
def preview_start(body: PreviewStartBody) -> dict[str, Any]:
    conversation_id = body.conversationId
    if not conversation_id:
        raise HTTPException(status_code=400, detail="启动预览需要 conversationId。")
    _repository, sandbox = _context_for(conversation_id)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    command = body.command
    repo_root = Path(sandbox["repoPath"])
    # 沙盒首次预览大概率没装依赖,npm run dev 会立刻失败、页面空白。
    # 检测到缺 node_modules 时自动先安装(命令链式拼接,日志可见)。
    needs_install = (repo_root / "package.json").exists() and not (repo_root / "node_modules").exists()
    if needs_install and command.strip().startswith("npm"):
        command = f"npm install --no-audit --no-fund && {command}"
    result = services.processes.start(
        conversation_id=conversation_id,
        sandbox_id=sandbox["id"],
        command=command,
        cwd=sandbox["repoPath"],
        ports=body.ports,
    )
    if needs_install:
        result["note"] = "检测到沙盒未安装依赖，已自动先执行 npm install（首次需 1-3 分钟），完成后预览会自动出现。"
    return result


@app.post("/api/preview/stop")
def preview_stop(body: PreviewStopBody) -> dict[str, Any]:
    try:
        return services.processes.stop(body.processId, body.conversationId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/preview/smoke-test")
def preview_smoke_test(body: PreviewSmokeBody) -> dict[str, Any]:
    try:
        report = services.preview_smoke.run(
            conversation_id=body.conversationId,
            port=body.port,
            path=body.path,
            timeout_seconds=body.timeoutSeconds,
            expected_texts=body.expectedTexts,
            required_selectors=body.requiredSelectors,
        )
        services.memory.record_preview_smoke(body.conversationId, report)
        services.tool_call_plans.sync_latest_reports(body.conversationId)
        if not report.get("ok"):
            services.memory.record_failure(body.conversationId, "预览 smoke test 未通过", report.get("summary", "预览验证失败。"), "preview")
        return report
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/preview/screenshot/{conversation_id}")
def preview_screenshot(conversation_id: str) -> FileResponse:
    path = services.preview_smoke.screenshot_path(conversation_id)
    if not path:
        raise HTTPException(status_code=404, detail="当前对话还没有可查看的预览截图。")
    return FileResponse(path, media_type="image/png", filename=f"{conversation_id}-preview.png")


@app.get("/api/processes")
def get_processes() -> list[dict[str, Any]]:
    return services.processes.list()


@app.get("/api/verification/plan")
def verification_plan(conversationId: str | None = None) -> dict[str, Any]:
    repository, _sandbox = _context_for(conversationId or "")
    if not repository:
        raise HTTPException(status_code=400, detail="当前还没有仓库。")
    return {"commands": services.stack_detector.select_commands(repository), "report": services.stack_detector.empty_report()}


@app.post("/api/verification/run")
def verification_run(body: VerificationRunBody) -> dict[str, Any]:
    _repository, sandbox = _context_for(body.conversationId)
    if not sandbox:
        raise HTTPException(status_code=400, detail="当前对话还没有沙盒。")
    try:
        report = services.verification_runner.run(
            conversation_id=body.conversationId,
            sandbox=sandbox,
            commands=body.commands,
            timeout_seconds=body.timeoutSeconds,
        )
        services.tool_call_plans.sync_latest_reports(body.conversationId)
        if report.get("status") == "fail":
            services.memory.record_failure(body.conversationId, "验证未通过", report.get("summary", ""), "verification")
        return report
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _context_for(conversation_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    state = services.conversations.get(conversation_id) if conversation_id else {}
    return state.get("repository"), state.get("sandbox")
