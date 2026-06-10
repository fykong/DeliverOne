from __future__ import annotations

from server_py.core.env import load_env_file

# 在任何服务实例化之前加载 .env，保证 ARK_API_KEY 等配置可见。
load_env_file()

from server_py.agent.planning_agent import PlanningAgent
from server_py.agent.role_agents import AgentRoleSuite
from server_py.agent.executor_agent import ExecutorAgent
from server_py.agent.orchestrator import AgentOrchestrator
from server_py.agent.tool_call_plan import ToolCallPlanService
from server_py.agent.tool_plan_drafter import ToolPlanDrafter
from server_py.agent.workflow import AgentWorkflow
from server_py.audit.plan_auditor import PlanAuditor
from server_py.conversations.store import ConversationStore
from server_py.delivery.git_submission import GitSubmissionService
from server_py.delivery.service import DeliveryService
from server_py.memory.memory_service import MemoryService
from server_py.memory.patch_service import MemoryPatchService
from server_py.memory.preflight_service import PreflightService
from server_py.memory.search_intent import SearchIntentService
from server_py.mcp.adapter import MCPAdapter
from server_py.models.ark_client import ArkClient
from server_py.models.model_config import ModelConfigService
from server_py.observability.metrics import MetricStore
from server_py.preview.process_registry import ProcessRegistry
from server_py.preview.smoke_test import PreviewSmokeTester
from server_py.repository.profiler import RepoProfiler
from server_py.runtime.approval_store import ApprovalStore
from server_py.runtime.events import EventStore
from server_py.runtime.permissions import PermissionPolicy
from server_py.runtime.sandbox_runtime import SandboxRuntimeService
from server_py.runtime.snapshot import RuntimeSnapshotService
from server_py.runtime.state_machine import RuntimeStateMachine
from server_py.runtime.task_state_machine import TaskStateMachineService
from server_py.sandbox.checkpoint_manager import CheckpointManager
from server_py.sandbox.diff_service import SandboxDiffService
from server_py.sandbox.file_browser import SandboxFileBrowser
from server_py.sandbox.manager import SandboxManager
from server_py.sandbox.rollback_service import RollbackService
from server_py.skills.registry import SkillRegistry
from server_py.skills.runtime import SkillRuntime
from server_py.tools import create_tool_registry
from server_py.tools.unified_runtime import UnifiedToolRuntime
from server_py.verification.runner import VerificationRunner
from server_py.verification.stack_detector import StackDetector


class Services:
    def __init__(self) -> None:
        self.events = EventStore()
        self.metrics = MetricStore()
        self.state_machine = RuntimeStateMachine()
        self.task_state_machine = TaskStateMachineService()
        self.runtime_snapshot = RuntimeSnapshotService(self.task_state_machine)
        self.stack_detector = StackDetector()
        self.sandbox_runtime = SandboxRuntimeService(self.stack_detector)
        self.policy = PermissionPolicy()
        self.approvals = ApprovalStore(self.events)
        self.checkpoints = CheckpointManager()
        self.delivery = DeliveryService(self.events)
        self.git_submission = GitSubmissionService(self.events)
        self.rollback = RollbackService(self.checkpoints, self.events)
        self.models = ModelConfigService()
        self.client = ArkClient()
        self.skills = SkillRegistry()
        self.skill_runtime = SkillRuntime(self.skills, self.events)
        self.memory = MemoryService()
        self.memory_patches = MemoryPatchService(self.client, self.models, self.memory, self.metrics)
        self.search_intent = SearchIntentService(self.client, self.metrics)
        self.preflight = PreflightService(self.models, self.skill_runtime, self.memory, self.search_intent)
        self.auditor = PlanAuditor()
        self.planning_agent = PlanningAgent(self.preflight, self.client, self.auditor, self.metrics)
        self.executor_agent = ExecutorAgent(self.preflight, self.client, self.metrics)
        self.tool_plan_drafter = ToolPlanDrafter(self.client, self.auditor, self.metrics, self.models)
        self.roles = AgentRoleSuite(self.client, self.metrics, self.models, self.skill_runtime)
        self.conversations = ConversationStore(self.state_machine)
        self.verification_runner = VerificationRunner(self.events, self.stack_detector)
        self.preview_smoke = PreviewSmokeTester(self.events)
        self.tools = create_tool_registry(
            self.events,
            self.policy,
            self.checkpoints,
            self.metrics,
            self.verification_runner,
            self.approvals,
            self.preview_smoke,
        )
        self.mcp = MCPAdapter(self.tools, self.events, self.approvals, self.metrics)
        self.tool_runtime = UnifiedToolRuntime(self.tools, self.mcp)
        self.tool_call_plans = ToolCallPlanService(self.events, self.conversations, self.memory)
        self.agent_workflow = AgentWorkflow(
            self.planning_agent,
            self.conversations,
            self.auditor,
            self.memory,
            self.tools,
            self.events,
            self.checkpoints,
        )
        self.sandboxes = SandboxManager(self.events)
        self.file_browser = SandboxFileBrowser()
        self.diff = SandboxDiffService()
        self.profiler = RepoProfiler()
        self.processes = ProcessRegistry(self.events)
        self.orchestrator = AgentOrchestrator(
            workflow=self.agent_workflow,
            conversations=self.conversations,
            memory=self.memory,
            tool_call_plans=self.tool_call_plans,
            tool_plan_drafter=self.tool_plan_drafter,
            tools=self.tool_runtime,
            roles=self.roles,
            events=self.events,
            checkpoints=self.checkpoints,
            processes=self.processes,
            file_browser=self.file_browser,
            runtime_snapshot=self.runtime_snapshot,
            sandbox_runtime=self.sandbox_runtime,
            diff=self.diff,
            task_state_machine=self.task_state_machine,
            skills=self.skill_runtime,
        )


services = Services()
