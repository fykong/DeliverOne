import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentAuditRecord,
  AgentConversationState,
  AgentConversationSummary,
  AgentOrchestratorBundle,
  AgentTurnResult,
  ApprovalGrant,
  AutopilotSummary,
  CheckpointManifest,
  DeliveryPreview,
  DeliveryReport,
  ManagedProcess,
  MCPConfigValidation,
  MCPServerManifest,
  MCPToolHistoryEntry,
  MCPToolManifest,
  MemoryPatchCandidate,
  MemoryPatchDraft,
  MemorySnapshot,
  ModelSettings,
  PreflightResult,
  PreviewSmokeReport,
  RepositoryStatus,
  RuntimeEvent,
  RuntimeMetricsResponse,
  RuntimeSnapshot,
  SandboxRuntimeSnapshot,
  SandboxDiffFile,
  SandboxDiffResponse,
  SandboxFileContent,
  SandboxTreeItem,
  SandboxStatus,
  SkillSummary,
  ToolCallPlan
} from "@workbench/shared";
import {
  cloneGitHubSandbox,
  connectLocalSandbox,
  deleteConversation,
  denyApproval,
  discoverMCPTools,
  editToolCallPlan,
  editTaskStateMachine,
  applyDeliveryToSource,
  generateDeliveryPackage,
  getDeliveryPreview,
  getApprovals,
  getCheckpointDiff,
  getConversation,
  getCurrentDiff,
  getEvents,
  getFileDiff,
  generateMemoryPatchDraft,
  getMCPConfig,
  getMCPHistory,
  getMCPServers,
  getMCPTools,
  getMemory,
  getModelSettings,
  getRuntimeMetrics,
  getRuntimeSnapshot,
  getSandboxRuntime,
  getSkills,
  forgetMemory,
  grantApproval,
  listConversations,
  pinMemory,
  revokeApproval,
  rollbackCheckpoint,
  rollbackCheckpointFile,
  rollbackCheckpointHunk,
  rollbackOriginal,
  readSandboxFile,
  replayMCPHistory,
  rewriteToolCallPlan,
  runAutopilot,
  runPreviewSmokeTest,
  runOrchestratorAction,
  saveModelSettings,
  saveMCPConfig,
  startPreview,
  stopPreview,
  applyMemoryPatchCandidate,
  upsertManualMemory,
  validateMCPConfig
} from "../../shared/api";
import type { ConversationMessage } from "../chat/types";

const conduitRepoUrl = "https://github.com/TonyMckes/conduit-realworld-example-app";
const defaultPreviewCommand = "npm run dev -- --host 127.0.0.1 --port 3000";

function createConversationId() {
  return `conv_${Date.now()}`;
}

function inferPreviewPorts(command: string) {
  const explicit = command.match(/(?:--port|PORT=)\s*=?\s*(\d{2,5})/i)?.[1];
  if (explicit) return [Number(explicit)];
  if (command.includes("5173") || command.toLowerCase().includes("vite")) return [5173];
  if (command.includes("4173") || command.toLowerCase().includes("preview")) return [4173];
  return [3000];
}

function summarizeRepository(repository: RepositoryStatus) {
  const scripts = Object.keys(repository.scripts);
  return `${repository.sourceType === "github" ? "GitHub" : "本地"}仓库已接入沙盒。分支：${repository.branch ?? "未识别"}；脚本：${scripts.length ? scripts.join(", ") : "未识别"}`;
}

function resolvePhaseLabel(agentTurn: AgentTurnResult | null, toolPlan: ToolCallPlan | null) {
  if (toolPlan?.status === "completed") return "交付完成";
  if (toolPlan?.status === "running") return "执行中";
  if (toolPlan?.status === "approved") return "待执行";
  if (toolPlan?.status === "waiting_confirmation") return "待确认工具";
  if (agentTurn?.phase === "waiting_plan_confirmation") return "待确认方案";
  if (agentTurn) return "计划模式";
  return "待开始";
}

function latestAudit(audits: AgentAuditRecord[] | undefined, source: string) {
  return [...(audits ?? [])].reverse().find((audit) => audit.source === source) ?? null;
}

function formatAuditMessage(audit: AgentAuditRecord | null, label: string) {
  if (!audit) return null;
  const findings = audit.findings.length
    ? audit.findings.slice(0, 3).map((finding) => `${finding.title}：${finding.detail}`).join("\n")
    : "没有阻断项。";
  const recommendation = audit.recommendation ? `\n建议：${audit.recommendation}` : "";
  return `${label}：${audit.summary || audit.verdict}\n${findings}${recommendation}`;
}

function verifierVerdictLabel(audit: AgentAuditRecord | null, plan: ToolCallPlan) {
  const hasFailedStep = plan.status === "failed" || plan.steps.some((step) => step.status === "failed");
  if (hasFailedStep) return "未通过，需要修复";
  if (audit?.verdict === "pass") return "通过";
  if (audit?.verdict === "warning") return "有风险，需审查";
  if (audit?.verdict === "blocked") return "未通过，需要处理";
  return "未验证";
}

function formatVerifierMessage(plan: ToolCallPlan, audit: AgentAuditRecord | null) {
  if (!audit) return null;
  const failedSteps = plan.steps.filter((step) => step.status === "failed");
  const failedText = failedSteps
    .slice(0, 4)
    .map((step) => `${String(step.order).padStart(2, "0")}. ${step.title}：${step.summary || "工具步骤失败。"}`)
    .join("\n");
  const policy = audit.repairPolicy ?? plan.repairPolicy;
  const policyText = policy ? `\n失败类型：${policy.failureClass}；修复策略：${policy.reason}` : "";
  const recommendation = audit.recommendation ? `\n下一步：${audit.recommendation}` : "";
  return [
    `Verifier：${verifierVerdictLabel(audit, plan)}`,
    audit.summary || "执行证据已审查。",
    failedText ? `失败步骤：\n${failedText}` : "",
    `${policyText}${recommendation}`.trim()
  ]
    .filter(Boolean)
    .join("\n");
}

function repairStopMessage(plan: ToolCallPlan) {
  const policy = plan.repairPolicy;
  if (policy?.requiresUserConfirmation && !policy.autoAllowed) {
    return `修复链路需要人工处理：${policy.reason}`;
  }
  if ((plan.repairSequence ?? 0) >= (policy?.maxTotalRepairSteps ?? 8)) {
    return "自动修复已达到总步数上限。请查看右侧失败证据、Diff 和日志后继续。";
  }
  if (policy?.countsTowardCodeRepairLimit && (plan.repairAttempt ?? 0) >= (policy.maxCodeRepairAttempts ?? 3)) {
    return "代码修复次数已达到上限。请人工审查当前方向后再继续。";
  }
  return "当前失败不适合继续自动生成修复计划，请先查看右侧证据。";
}

function formatRollbackMessage(result: { summary: string; rollbackReport?: { reportPath?: string } }) {
  if (!result.rollbackReport?.reportPath) {
    return result.summary;
  }
  return `${result.summary}\n证据报告：${result.rollbackReport.reportPath}`;
}

function formatToolStepTrace(plan: ToolCallPlan) {
  const lines = plan.steps.slice(0, 8).map((step) => {
    const status = step.status === "completed" ? "完成" : step.status === "failed" ? "失败" : step.status === "waiting_approval" ? "等待授权" : step.status;
    const summary = step.summary || step.purpose;
    return `${String(step.order).padStart(2, "0")}. ${step.title}（${step.toolId}）${status}：${summary}`;
  });
  const hidden = plan.steps.length > lines.length ? `\n还有 ${plan.steps.length - lines.length} 个步骤在右侧工具计划中。` : "";
  return `执行轨迹：\n${lines.join("\n")}${hidden}`;
}

function formatExecutionResult(plan: ToolCallPlan) {
  if (plan.status === "completed") {
    return `工具计划执行完成。变更文件：${plan.evidence.diffFiles.length} 个；验证命令：${plan.evidence.verificationResults.length} 条。`;
  }
  if (plan.status === "failed" || plan.steps.some((step) => step.status === "failed")) {
    return `工具计划未通过。失败步骤：${plan.steps.filter((step) => step.status === "failed").length} 个；变更文件：${plan.evidence.diffFiles.length} 个；验证命令：${plan.evidence.verificationResults.length} 条。`;
  }
  if (plan.status === "waiting_approval") {
    return "工具计划已暂停，存在步骤等待授权。";
  }
  return `工具计划已暂停在 ${plan.status} 状态。`;
}

function formatRepairPlanTrace(plan: ToolCallPlan) {
  const steps = plan.steps.slice(0, 6).map((step) => `${String(step.order).padStart(2, "0")}. ${step.title}（${step.toolId}）`).join("\n");
  const policy = plan.repairPolicy;
  const source = plan.repairSource;
  return [
    `修复计划 #${plan.repairSequence ?? 1}`,
    source?.summary ? `来源失败：${source.summary}` : undefined,
    `失败类型：${policy?.failureClass ?? "unknown"}`,
    `策略：${policy?.reason ?? "继续读取证据并复验。"}`,
    `代码修复次数：${plan.repairAttempt ?? 0}/${policy?.maxCodeRepairAttempts ?? 3}`,
    "待执行步骤：",
    steps || "暂无步骤"
  ]
    .filter(Boolean)
    .join("\n");
}

function formatAutopilotSummary(summary: AutopilotSummary | null | undefined) {
  if (!summary) return null;
  const lines: string[] = [];
  if (summary.finished) {
    const submission = summary.submission;
    if (submission?.branch) {
      const commit = submission.commitSha ? submission.commitSha.slice(0, 8) : "未知";
      lines.push(`托管完成：${summary.rounds} 轮，提测分支 ${submission.branch}（commit ${commit}）。`);
    } else {
      lines.push(`托管完成：${summary.rounds} 轮。${summary.reason}`.trim());
    }
    if (submission?.prUrl) {
      lines.push(`PR 链接：${submission.prUrl}`);
    }
  } else if (summary.needsHuman) {
    lines.push(`托管暂停于 ${summary.stage}：${summary.reason || "需要人工处理。"}`);
  } else {
    lines.push(`托管结束于 ${summary.stage}：${summary.reason || "未提供原因。"}`);
  }
  if (summary.delivery) {
    lines.push(`交付门禁：${summary.delivery.verificationGate ?? "unknown"}；变更文件 ${summary.delivery.changedFiles} 个。`);
  }
  return lines.join("\n");
}

export function useWorkbench() {
  const [conversationId, setConversationId] = useState(createConversationId);
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([]);
  const [models, setModels] = useState<ModelSettings | null>(null);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [localPath, setLocalPath] = useState("");
  const [githubUrl, setGithubUrl] = useState(conduitRepoUrl);
  const [repository, setRepository] = useState<RepositoryStatus | null>(null);
  const [sandbox, setSandbox] = useState<SandboxStatus | null>(null);
  const [requirement, setRequirement] = useState(
    "Build a team billing dashboard with subscription plans, invoice list, role permissions, usage alerts, and Stripe Webhook tests."
  );
  const [messages, setMessages] = useState<ConversationMessage[]>([
    {
      role: "Agent",
      text: "先在左侧接入仓库。你发送需求后，我会先返回模型生成的方案；你确认后，我再生成可审查的工具调用计划。"
    }
  ]);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [agentTurn, setAgentTurn] = useState<AgentTurnResult | null>(null);
  const [toolPlan, setToolPlan] = useState<ToolCallPlan | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointManifest[]>([]);
  const [processes, setProcesses] = useState<ManagedProcess[]>([]);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [mcpConfig, setMcpConfig] = useState<Record<string, unknown> | null>(null);
  const [mcpConfigValidation, setMcpConfigValidation] = useState<MCPConfigValidation | null>(null);
  const [mcpServers, setMcpServers] = useState<MCPServerManifest[]>([]);
  const [mcpTools, setMcpTools] = useState<MCPToolManifest[]>([]);
  const [mcpHistory, setMcpHistory] = useState<MCPToolHistoryEntry[]>([]);
  const [approvals, setApprovals] = useState<ApprovalGrant[]>([]);
  const [metrics, setMetrics] = useState<RuntimeMetricsResponse | null>(null);
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [sandboxRuntime, setSandboxRuntime] = useState<SandboxRuntimeSnapshot | null>(null);
  const [memory, setMemory] = useState<MemorySnapshot | null>(null);
  const [memoryPatchDraft, setMemoryPatchDraft] = useState<MemoryPatchDraft | null>(null);
  const [deliveryReport, setDeliveryReport] = useState<DeliveryReport | null>(null);
  const [deliveryPreview, setDeliveryPreview] = useState<DeliveryPreview | null>(null);
  const [previewSmokeReport, setPreviewSmokeReport] = useState<PreviewSmokeReport | null>(null);
  const [sandboxFiles, setSandboxFiles] = useState<SandboxTreeItem[]>([]);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<SandboxFileContent | null>(null);
  const [currentDiff, setCurrentDiff] = useState<SandboxDiffResponse | null>(null);
  const [selectedDiff, setSelectedDiff] = useState<SandboxDiffFile | null>(null);
  const [checkpointDiff, setCheckpointDiff] = useState<SandboxDiffResponse | null>(null);
  const [selectedCheckpointId, setSelectedCheckpointId] = useState<string | null>(null);
  const [previewCommand, setPreviewCommand] = useState(defaultPreviewCommand);
  const [isRunning, setIsRunning] = useState(false);
  const [isExecutingToolPlan, setIsExecutingToolPlan] = useState(false);
  const [executionStatus, setExecutionStatus] = useState<string | null>(null);
  const [autopilotEnabled, setAutopilotEnabled] = useState(false);

  // 写动作（含长执行）统一用这个标记禁用；只读动作只看短动作 isRunning。
  const isBusy = isRunning || isExecutingToolPlan;

  const conversationIdRef = useRef(conversationId);
  const executionPollTimerRef = useRef<number | null>(null);
  const executionPollTokenRef = useRef(0);

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    return () => {
      if (executionPollTimerRef.current !== null) {
        window.clearInterval(executionPollTimerRef.current);
        executionPollTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    void getModelSettings().then(setModels);
    void getSkills().then(setSkills);
    void refreshRuntimeState(conversationId);
    void refreshConversations();
  }, []);

  useEffect(() => {
    const recommended = sandboxRuntime?.commandRecommendations?.preview.primary?.command;
    if (recommended && previewCommand === defaultPreviewCommand) {
      setPreviewCommand(recommended);
    }
  }, [previewCommand, sandboxRuntime?.commandRecommendations?.preview.primary?.command]);

  const activeModelName = useMemo(() => {
    return models?.models.find((model) => model.id === models.defaultModelId)?.displayName ?? "模型加载中";
  }, [models]);

  const phaseLabel = useMemo(() => resolvePhaseLabel(agentTurn, toolPlan), [agentTurn, toolPlan]);
  const visibleConversations = useMemo(() => {
    if (conversations.some((item) => item.conversationId === conversationId)) {
      return conversations;
    }
    return [
      {
        conversationId,
        title: repository ? repository.source.split(/[\\/]/).pop() || "当前对话" : "当前对话",
        phase: agentTurn?.phase ?? "idle",
        repository: repository ?? undefined,
        sandbox: sandbox ?? undefined,
        toolCallPlan: toolPlan
          ? {
              id: toolPlan.id,
              status: toolPlan.status,
              stepCount: toolPlan.steps.length,
              updatedAt: toolPlan.updatedAt,
              evidence: toolPlan.evidence
            }
          : undefined
      },
      ...conversations
    ];
  }, [agentTurn?.phase, conversationId, conversations, repository, sandbox, toolPlan]);

  function pushMessage(message: ConversationMessage) {
    setMessages((items) => [...items, message]);
  }

  async function refreshConversations() {
    const summaries = await listConversations().catch(() => []);
    setConversations(summaries);
  }

  async function refreshRuntimeState(nextConversationId = conversationId) {
    const [
      nextConfig,
      nextServers,
      nextTools,
      nextHistory,
      nextApprovals,
      nextMetrics,
      nextRuntimeSnapshot,
      nextSandboxRuntime,
      nextMemory,
      nextDeliveryPreview
    ] = await Promise.all([
      getMCPConfig().catch(() => null),
      getMCPServers().catch(() => []),
      getMCPTools(requirement).catch(() => []),
      getMCPHistory(nextConversationId).catch(() => []),
      getApprovals(nextConversationId).catch(() => []),
      getRuntimeMetrics(nextConversationId).catch(() => null),
      getRuntimeSnapshot(nextConversationId).catch(() => null),
      getSandboxRuntime(nextConversationId).catch(() => null),
      getMemory(nextConversationId).catch(() => null),
      getDeliveryPreview(nextConversationId).catch(() => null)
    ]);
    setMcpConfig(nextConfig);
    setMcpServers(nextServers);
    setMcpTools(nextTools);
    setMcpHistory(nextHistory);
    setApprovals(nextApprovals);
    setMetrics(nextMetrics);
    setRuntimeSnapshot(nextRuntimeSnapshot);
    setSandboxRuntime(nextSandboxRuntime);
    setMemory(nextMemory);
    setDeliveryPreview(nextDeliveryPreview && nextDeliveryPreview.exists ? nextDeliveryPreview : null);
    if (nextDeliveryPreview?.report) {
      setDeliveryReport(nextDeliveryPreview.report);
    }
  }

  async function refreshCurrentDiff(nextConversationId = conversationId) {
    const diff = await getCurrentDiff(nextConversationId).catch(() => null);
    setCurrentDiff(diff);
    if (selectedDiff && diff && !diff.files.some((item) => item.path === selectedDiff.path)) {
      setSelectedDiff(null);
    }
  }

  function applyOrchestratorBundle(bundle: AgentOrchestratorBundle) {
    const state = bundle.conversation;
    const latestTurn = bundle.turn ?? state.turns.at(-1) ?? null;
    setRepository(state.repository ?? null);
    setSandbox(state.sandbox ?? null);
    setAgentTurn(latestTurn);
    setPreflight(latestTurn?.preflight ?? null);
    if (latestTurn?.preflight?.memory) {
      setMemory(latestTurn.preflight.memory);
    }
    setToolPlan(bundle.toolPlan ?? null);
    setCheckpoints(bundle.checkpoints);
    setProcesses(bundle.processes);
    setEvents(bundle.events);
    setRuntimeSnapshot(bundle.runtimeSnapshot ?? null);
    setSandboxRuntime(bundle.sandboxRuntime ?? null);

    const nextFiles = bundle.files?.items ?? [];
    setSandboxFiles(nextFiles);
    if (selectedFilePath && !nextFiles.some((item) => item.type === "file" && item.path === selectedFilePath)) {
      setSelectedFilePath(null);
      setSelectedFile(null);
    }
  }

  async function refreshEvidence(nextConversationId = conversationId) {
    const bundle = await runOrchestratorAction({ conversationId: nextConversationId, action: "refresh" }).catch(() => null);
    if (bundle) {
      applyOrchestratorBundle(bundle);
    }
    await refreshRuntimeState(nextConversationId);
    await refreshCurrentDiff(nextConversationId);
    await refreshConversations();
  }

  function resetConversation() {
    const nextId = createConversationId();
    setConversationId(nextId);
    setRepository(null);
    setSandbox(null);
    setPreflight(null);
    setAgentTurn(null);
    setToolPlan(null);
    setCheckpoints([]);
    setProcesses([]);
    setEvents([]);
    setMcpConfigValidation(null);
    setMcpHistory([]);
    setApprovals([]);
    setMetrics(null);
    setRuntimeSnapshot(null);
    setSandboxRuntime(null);
    setMemory(null);
    setMemoryPatchDraft(null);
    setDeliveryReport(null);
    setDeliveryPreview(null);
    setPreviewSmokeReport(null);
    setSandboxFiles([]);
    setSelectedFilePath(null);
    setSelectedFile(null);
    setCurrentDiff(null);
    setSelectedDiff(null);
    setCheckpointDiff(null);
    setSelectedCheckpointId(null);
    setMessages([{ role: "Agent", text: "已新建对话。请接入仓库后发送需求，我会按计划模式推进。" }]);
  }

  async function selectConversation(nextConversationId: string) {
    if (nextConversationId === conversationId || isRunning) return;
    setIsRunning(true);
    try {
      const state = await getConversation(nextConversationId);
      hydrateConversation(state);
      await refreshEvidence(nextConversationId);
    } catch (error) {
      pushMessage({ role: "Agent", text: `切换对话失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function removeConversation(targetConversationId: string) {
    if (isBusy) return;
    const confirmed = window.confirm("确认删除这个对话及其沙盒工作区？");
    if (!confirmed) return;
    setIsRunning(true);
    try {
      await deleteConversation(targetConversationId);
      await refreshConversations();
      if (targetConversationId === conversationId) {
        resetConversation();
      }
    } catch (error) {
      pushMessage({ role: "Agent", text: `删除对话失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  function hydrateConversation(state: AgentConversationState) {
    setConversationId(state.conversationId);
    setRepository(state.repository ?? null);
    setSandbox(state.sandbox ?? null);
    setPreflight(null);
    setMemory(null);
    setMemoryPatchDraft(null);
    setAgentTurn(state.turns.at(-1) ?? null);
    setToolPlan(null);
    setRuntimeSnapshot(null);
    setSandboxRuntime(null);
    setSelectedFilePath(null);
    setSelectedFile(null);
    setSelectedDiff(null);
    setCheckpointDiff(null);
    setSelectedCheckpointId(null);
    setMessages(
      state.messages.length
        ? state.messages.map((message) => ({
            role: message.role === "user" ? "你" : "Agent",
            text: message.content,
            meta: message.createdAt
          }))
        : [{ role: "Agent", text: "这个对话还没有消息。" }]
    );
  }

  async function handleModelChange(modelId: string) {
    if (!models) return;
    if (modelId === models.defaultModelId || models.models.length <= 1) return;
    const next = await saveModelSettings({ defaultModelId: modelId });
    setModels(next);
    pushMessage({ role: "系统", text: `默认模型已切换为 ${next.models.find((model) => model.id === next.defaultModelId)?.displayName ?? modelId}。新的对话会使用这个模型。` });
  }

  async function connectRepository(kind: "local" | "github") {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result =
        kind === "local"
          ? await connectLocalSandbox({ conversationId, sourcePath: localPath.trim() })
          : await cloneGitHubSandbox({ conversationId, repoUrl: githubUrl.trim() });
      setRepository(result.repository);
      setSandbox(result.sandbox);
      setPreflight(null);
      setAgentTurn(null);
      setToolPlan(null);
      setCheckpoints([]);
      setDeliveryReport(null);
      setDeliveryPreview(null);
      setPreviewSmokeReport(null);
      setMemory(null);
      setMemoryPatchDraft(null);
      setSandboxFiles([]);
      setSelectedFilePath(null);
      setSelectedFile(null);
      setCurrentDiff(null);
      setSelectedDiff(null);
      setCheckpointDiff(null);
      setSelectedCheckpointId(null);
      pushMessage({ role: "系统", text: summarizeRepository(result.repository), meta: result.sandbox.repoPath });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `仓库接入失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRunAgent() {
    const trimmedRequirement = requirement.trim();
    if (!trimmedRequirement || isBusy || !sandbox) return;

    if (autopilotEnabled) {
      await runAutopilotRequirement(trimmedRequirement);
      return;
    }

    setIsRunning(true);
    setToolPlan(null);
    pushMessage({ role: "你", text: trimmedRequirement });
    pushMessage({ role: "Agent", text: "我正在读取仓库画像、匹配 Skill，并调用当前模型生成方案。" });

    try {
      const bundle = await runOrchestratorAction({
        conversationId,
        action: "submit_requirement",
        requirement: trimmedRequirement
      });
      applyOrchestratorBundle(bundle);
      if (bundle.turn) {
        const clarification = latestAudit(bundle.turn.audits, "Clarifier");
        const message = formatAuditMessage(clarification, "Clarifier 结论");
        if (message) {
          pushMessage({ role: "Agent", text: message });
        }
        const clarifyingQuestions =
          bundle.turn.phase === "clarification" && clarification?.questions?.length ? clarification.questions : undefined;
        pushMessage({
          role: "Agent",
          text: bundle.turn.reply,
          meta: `模型：${bundle.turn.model.displayName}`,
          questions: clarifyingQuestions
        });
      }
      await refreshConversations();
    } catch (error) {
      pushMessage({ role: "Agent", text: `Agent 规划失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function runAutopilotRequirement(trimmedRequirement: string) {
    const targetConversationId = conversationId;
    // 复用工具计划执行的长任务标记与事件轮询：只禁用写动作，UI 不全局冻结。
    setIsExecutingToolPlan(true);
    setToolPlan(null);
    pushMessage({ role: "你", text: trimmedRequirement });
    pushMessage({ role: "Agent", text: "托管模式已开启：我会自动确认方案与工具计划并持续执行，遇到澄清问题或高危操作会停下来等你。" });
    startExecutionPolling(targetConversationId);
    try {
      const bundle = await runAutopilot({ conversationId: targetConversationId, requirement: trimmedRequirement });
      if (conversationIdRef.current !== targetConversationId) {
        // 托管期间用户切换了会话：不要把旧会话结果写入当前界面。
        await refreshConversations();
        return;
      }
      applyOrchestratorBundle(bundle);
      await refreshCurrentDiff(targetConversationId);
      if (bundle.turn) {
        pushMessage({ role: "Agent", text: bundle.turn.reply, meta: `模型：${bundle.turn.model.displayName}` });
      }
      const summaryText = formatAutopilotSummary(bundle.autopilot);
      if (summaryText) {
        pushMessage({ role: "Agent", text: summaryText });
      }
      await refreshConversations();
    } catch (error) {
      pushMessage({ role: "Agent", text: `托管模式失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      stopExecutionPolling();
      setIsExecutingToolPlan(false);
    }
  }

  async function handleConfirmPlan() {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const bundle = await runOrchestratorAction({ conversationId, action: "approve_plan", requirement });
      applyOrchestratorBundle(bundle);
      if (bundle.turn) {
        pushMessage({ role: "Agent", text: bundle.turn.reply });
      }
      if (bundle.toolPlan) {
        const review = latestAudit(bundle.toolPlan.audits, "Reviewer");
        const message = formatAuditMessage(review, "Reviewer 结论");
        if (message) {
          pushMessage({ role: "Agent", text: message });
        }
        pushMessage({ role: "Agent", text: `我已生成 ${bundle.toolPlan.steps.length} 步工具调用计划。请在右侧审查并确认后执行。` });
      }
      await refreshConversations();
    } catch (error) {
      pushMessage({ role: "Agent", text: `方案确认失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleApproveToolPlan() {
    if (!toolPlan || isBusy) return;
    setIsRunning(true);
    try {
      const bundle = await runOrchestratorAction({ conversationId, action: "approve_tool_plan", planId: toolPlan.id });
      applyOrchestratorBundle(bundle);
      pushMessage({ role: "系统", text: "工具计划已确认。现在可以执行，所有写入会先产生 checkpoint。" });
      await refreshConversations();
    } catch (error) {
      pushMessage({ role: "Agent", text: `工具计划确认失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleConfirmAndExecuteToolPlan() {
    if (!toolPlan || isBusy) return;
    setIsExecutingToolPlan(true);
    try {
      let planId = toolPlan.id;
      if (toolPlan.status === "waiting_confirmation") {
        const approveBundle = await runOrchestratorAction({ conversationId, action: "approve_tool_plan", planId });
        applyOrchestratorBundle(approveBundle);
        const approvedPlan = approveBundle.toolPlan;
        if (!approvedPlan) {
          throw new Error("工具计划确认后没有返回计划状态。");
        }
        planId = approvedPlan.id;
        pushMessage({
          role: "系统",
          text: approvedPlan.repairOfPlanId ? "修复计划已确认，开始在沙盒中执行。" : "工具计划已确认，开始在沙盒中执行。"
        });
      }
      await executeToolPlanById(planId);
    } catch (error) {
      pushMessage({ role: "Agent", text: `确认并执行失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsExecutingToolPlan(false);
    }
  }

  async function handleCreateRepairPlan() {
    if (!toolPlan || isBusy) return;
    setIsRunning(true);
    try {
      const bundle = await runOrchestratorAction({ conversationId, action: "repair_failed_plan", planId: toolPlan.id });
      applyOrchestratorBundle(bundle);
      if (bundle.toolPlan) {
        pushMessage({ role: "Agent", text: `${formatRepairPlanTrace(bundle.toolPlan)}\n请在右侧审查，确认后再执行。` });
      }
      await refreshConversations();
    } catch (error) {
      pushMessage({ role: "Agent", text: `生成修复计划失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleEditToolPlanStep(
    operation: "skip_step" | "restore_step" | "update_step" | "move_step",
    stepId: string,
    options: { reason?: string; title?: string; purpose?: string; input?: Record<string, unknown>; targetOrder?: number } = {}
  ) {
    if (!toolPlan || isBusy) return;
    setIsRunning(true);
    try {
      const nextPlan = await editToolCallPlan({
        conversationId,
        planId: toolPlan.id,
        operation,
        stepId,
        ...options
      });
      setToolPlan(nextPlan);
      pushMessage({ role: "系统", text: "工具计划已更新，执行前请重新审查右侧步骤。" });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `编辑工具计划失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRewriteToolPlan(instruction: string) {
    if (!toolPlan || isBusy) return;
    const cleaned = instruction.trim();
    if (!cleaned) {
      pushMessage({ role: "系统", text: "请先写清楚希望如何调整工具计划。" });
      return;
    }
    setIsRunning(true);
    try {
      const nextPlan = await rewriteToolCallPlan({
        conversationId,
        planId: toolPlan.id,
        instruction: cleaned
      });
      setToolPlan(nextPlan);
      const reviewer = latestAudit(nextPlan.audits, "Reviewer");
      const reviewerText = formatAuditMessage(reviewer, "Reviewer 结论");
      pushMessage({ role: "Agent", text: `已按你的意见重写工具计划：${nextPlan.generation?.summary ?? cleaned}\n当前共有 ${nextPlan.steps.length} 个步骤，仍需你在右侧确认后才会执行。` });
      if (reviewerText) pushMessage({ role: "Agent", text: reviewerText });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `重写工具计划失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleEditTaskState(
    operation: "annotate_stage" | "pause_stage" | "resume_stage" | "set_next_actions" | "clear_next_actions",
    options: { stageId?: string; note?: string; actionIds?: string[] } = {}
  ) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const nextRuntime = await editTaskStateMachine({
        conversationId,
        operation,
        ...options
      });
      setRuntimeSnapshot(nextRuntime);
      await refreshEvidence();
      const actionText =
        operation === "pause_stage"
          ? "任务阶段已暂停，Agent 会在继续前保留这条人工控制记录。"
          : operation === "resume_stage"
            ? "任务阶段已恢复。"
            : operation === "set_next_actions"
              ? "下一步动作已由用户覆盖。"
              : operation === "clear_next_actions"
                ? "下一步动作覆盖已清除。"
                : "任务阶段备注已记录。";
      pushMessage({ role: "系统", text: actionText });
    } catch (error) {
      pushMessage({ role: "Agent", text: `编辑任务状态机失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleExecuteToolPlan() {
    if (!toolPlan || isBusy) return;
    setIsExecutingToolPlan(true);
    try {
      await executeToolPlanById(toolPlan.id);
    } catch (error) {
      pushMessage({ role: "Agent", text: `执行失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsExecutingToolPlan(false);
    }
  }

  function startExecutionPolling(targetConversationId: string) {
    stopExecutionPolling();
    const token = ++executionPollTokenRef.current;
    setExecutionStatus("正在执行工具计划，等待 runtime 事件……");
    const tick = async () => {
      try {
        const polledEvents = await getEvents(targetConversationId);
        // 用 ref 标记当前轮询会话，过期响应直接丢弃，避免竞态。
        if (executionPollTokenRef.current !== token) return;
        if (conversationIdRef.current !== targetConversationId) {
          // 用户切换到了其它会话：先隐藏进度条，切回来后下一轮会恢复显示。
          setExecutionStatus(null);
          return;
        }
        setEvents(polledEvents);
        const last = polledEvents.at(-1);
        setExecutionStatus(`正在执行：${last ? last.type : "等待事件"} · 已记录 ${polledEvents.length} 条事件`);
      } catch {
        // 轮询失败不打断执行，下一轮继续。
      }
    };
    void tick();
    executionPollTimerRef.current = window.setInterval(() => {
      void tick();
    }, 2000);
  }

  function stopExecutionPolling() {
    executionPollTokenRef.current += 1;
    if (executionPollTimerRef.current !== null) {
      window.clearInterval(executionPollTimerRef.current);
      executionPollTimerRef.current = null;
    }
    setExecutionStatus(null);
  }

  async function executeToolPlanById(planId: string) {
    const targetConversationId = conversationId;
    pushMessage({ role: "Agent", text: "开始执行工具计划。右侧会更新 diff、checkpoint 和验证证据。" });
    startExecutionPolling(targetConversationId);
    let bundle: AgentOrchestratorBundle;
    try {
      bundle = await runOrchestratorAction({ conversationId: targetConversationId, action: "execute_tool_plan", planId });
    } finally {
      stopExecutionPolling();
    }
    if (conversationIdRef.current !== targetConversationId) {
      // 执行期间用户已切换会话：不要把旧会话结果写入当前界面。
      await refreshConversations();
      return;
    }
    applyOrchestratorBundle(bundle);
    await refreshCurrentDiff(targetConversationId);
    const plan = bundle.executedToolPlan ?? bundle.toolPlan;
    if (!plan) {
      throw new Error("工具计划执行后没有返回计划状态。");
    }
    pushMessage({
      role: "Agent",
      text: formatExecutionResult(plan)
    });
    pushMessage({ role: "Agent", text: formatToolStepTrace(plan) });
    const verifier = latestAudit(plan.audits, "Verifier");
    const verifierMessage = formatVerifierMessage(plan, verifier);
    if (verifierMessage) {
      pushMessage({ role: "Agent", text: verifierMessage });
    }
    if (bundle.repairPlan) {
      pushMessage({ role: "Agent", text: `${formatRepairPlanTrace(bundle.repairPlan)}\n后端 Orchestrator 已生成下一轮待确认修复计划，请审查右侧步骤后点击“确认并执行”。` });
    } else if (plan.status === "failed" || plan.steps.some((step) => step.status === "failed")) {
      pushMessage({ role: "Agent", text: bundle.repairLoop?.reason ?? repairStopMessage(plan) });
    }
    await refreshConversations();
  }

  async function handleRollbackCheckpoint(checkpointId: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await rollbackCheckpoint({ conversationId, checkpointId });
      pushMessage({ role: "系统", text: formatRollbackMessage(result) });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `回退失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRollbackCheckpointFile(checkpointId: string, relativePath: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await rollbackCheckpointFile({ conversationId, checkpointId, relativePath });
      pushMessage({ role: "系统", text: formatRollbackMessage(result) });
      await refreshEvidence();
      if (selectedCheckpointId === checkpointId) {
        const diff = await getCheckpointDiff(conversationId, checkpointId).catch(() => null);
        setCheckpointDiff(diff);
      }
    } catch (error) {
      pushMessage({ role: "Agent", text: `文件回退失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRollbackCheckpointHunk(checkpointId: string, relativePath: string, hunkIndex: number) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await rollbackCheckpointHunk({ conversationId, checkpointId, relativePath, hunkIndex });
      pushMessage({ role: "系统", text: formatRollbackMessage(result) });
      await refreshEvidence();
      if (selectedCheckpointId === checkpointId) {
        const diff = await getCheckpointDiff(conversationId, checkpointId).catch(() => null);
        setCheckpointDiff(diff);
      }
    } catch (error) {
      pushMessage({ role: "Agent", text: `变更块回退失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRollbackOriginal() {
    if (isBusy) return;
    const confirmed = window.confirm("确认把当前对话沙盒回到原始 HEAD？这会丢弃沙盒内所有未提交改动。");
    if (!confirmed) return;
    setIsRunning(true);
    try {
      const result = await rollbackOriginal({ conversationId, confirmed: true });
      pushMessage({ role: "系统", text: formatRollbackMessage(result) });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `一键回退失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleStartPreview() {
    if (isBusy || !previewCommand.trim()) return;
    setIsRunning(true);
    try {
      const recommended = sandboxRuntime?.commandRecommendations?.preview.primary;
      const ports = recommended?.command === previewCommand.trim() && recommended.ports?.length ? recommended.ports : inferPreviewPorts(previewCommand);
      const process = await startPreview({ conversationId, command: previewCommand.trim(), ports });
      setProcesses((items) => [process, ...items]);
      pushMessage({ role: "系统", text: `预览命令已在沙盒启动：${process.command}` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `预览启动失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleStopPreview(processId: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const process = await stopPreview({ conversationId, processId });
      setProcesses((items) => items.map((item) => (item.id === process.id ? process : item)));
      pushMessage({ role: "系统", text: `预览进程已停止：${process.command}` });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `预览停止失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRunPreviewSmokeTest(port: number) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const report = await runPreviewSmokeTest({ conversationId, port, path: "/", timeoutSeconds: 30 });
      setPreviewSmokeReport(report);
      pushMessage({ role: "系统", text: `预览验证${report.ok ? "通过" : "失败"}：${report.summary}` });
      await refreshRuntimeState();
    } catch (error) {
      pushMessage({ role: "Agent", text: `预览验证失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleGenerateDeliveryPackage() {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const report = await generateDeliveryPackage({ conversationId });
      setDeliveryReport(report);
      const preview = await getDeliveryPreview(conversationId).catch(() => null);
      setDeliveryPreview(preview && preview.exists ? preview : null);
      pushMessage({ role: "系统", text: `交付包已生成：${report.statusShort}，变更文件 ${report.changedFiles.length} 个。`, meta: report.artifacts.markdownPath });
      await refreshRuntimeState();
    } catch (error) {
      pushMessage({ role: "Agent", text: `生成交付包失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleApplyDeliveryToSource() {
    if (isBusy || !deliveryReport) return;
    const confirmed = window.confirm("确认把当前沙盒交付包应用回原始本地仓库？系统会先备份被覆盖文件。");
    if (!confirmed) return;
    setIsRunning(true);
    try {
      const result = await applyDeliveryToSource({ conversationId, confirmed: true });
      pushMessage({ role: "系统", text: result.summary, meta: result.backupPath });
      await refreshEvidence();
    } catch (error) {
      pushMessage({ role: "Agent", text: `应用交付包失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleDiscoverMCPTools() {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await discoverMCPTools({ timeoutSeconds: 8 });
      setMcpTools(result.tools);
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: `MCP 发现完成：${result.serverCount} 个 server，${result.toolCount} 个外部工具。` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `MCP 工具发现失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleSaveMCPConfig(config: Record<string, unknown>) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const validation = await validateMCPConfig(config);
      setMcpConfigValidation(validation);
      if (!validation.ok) {
        pushMessage({ role: "Agent", text: `MCP 配置校验未通过：${validation.errors.map((item) => item.message).join("；")}` });
        return;
      }
      const saved = await saveMCPConfig(config);
      setMcpConfig(saved);
      await refreshRuntimeState();
      const warningText = validation.warnings.length ? `\n提示：${validation.warnings.map((item) => item.message).join("；")}` : "";
      pushMessage({ role: "系统", text: `MCP 配置已保存。请按需点击“发现 MCP 工具”刷新外部工具。${warningText}` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `保存 MCP 配置失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleValidateMCPConfig(config: Record<string, unknown>) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const validation = await validateMCPConfig(config);
      setMcpConfigValidation(validation);
      const detail = validation.ok
        ? validation.warnings.length
          ? `通过，但有 ${validation.warnings.length} 条提示。`
          : "通过。"
        : `失败：${validation.errors.map((item) => item.message).join("；")}`;
      pushMessage({ role: "系统", text: `MCP 配置校验${detail}` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `校验 MCP 配置失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleReplayMCPHistory(historyEntryId: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await replayMCPHistory({ conversationId, historyEntryId });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: String(result.summary ?? "MCP 调用已重放。") });
    } catch (error) {
      pushMessage({ role: "Agent", text: `重放 MCP 调用失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleGrantToolApproval(toolId: string, scope: ApprovalGrant["scope"], riskLevel = "external", command?: string, requestEventId?: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const approval = await grantApproval({
        conversationId,
        toolId,
        riskLevel,
        scope,
        command,
        requestEventId,
        note: "用户从右侧面板授权工具调用。"
      });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: `已授权外部工具：${approval.toolId}（${approval.scope}）。` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `授权失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleDenyToolApproval(toolId: string, riskLevel: string, reason: string, requestEventId?: string, command?: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const decision = await denyApproval({ conversationId, toolId, riskLevel, reason, requestEventId, command });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: `已拒绝工具调用：${decision.toolId}。原因：${decision.note ?? reason}` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `拒绝审批失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleRevokeApproval(grantId: string) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const approval = await revokeApproval({ conversationId, grantId });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: `已撤销授权：${approval.toolId}。` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `撤销授权失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handlePinMemory(itemId: string, pinned: boolean) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      await pinMemory({ itemId, value: pinned });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: pinned ? "长期记忆已置顶。" : "长期记忆已取消置顶。" });
    } catch (error) {
      pushMessage({ role: "Agent", text: `更新长期记忆失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleForgetMemory(itemId: string) {
    if (isBusy) return;
    const confirmed = window.confirm("确认遗忘这条长期记忆？它不会再进入后续上下文召回。");
    if (!confirmed) return;
    setIsRunning(true);
    try {
      await forgetMemory({ itemId, value: true });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: "长期记忆已遗忘。" });
    } catch (error) {
      pushMessage({ role: "Agent", text: `遗忘长期记忆失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleUpsertManualMemory(input: {
    itemId?: string;
    title: string;
    content: string;
    kind?: string;
    tags?: string[];
    pinned?: boolean;
    importance?: number;
  }) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await upsertManualMemory({ conversationId, ...input });
      await refreshRuntimeState();
      pushMessage({ role: "系统", text: `长期记忆已保存：${result.item.title}` });
    } catch (error) {
      pushMessage({ role: "Agent", text: `保存长期记忆失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleGenerateMemoryPatchDraft() {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const draft = await generateMemoryPatchDraft({
        conversationId,
        instruction: requirement,
        maxItems: 4
      });
      setMemoryPatchDraft(draft);
      await refreshRuntimeState();
      pushMessage({
        role: "Agent",
        text: `Memory Curator 已生成 ${draft.candidates.length} 条长期记忆草案。\n${draft.summary}`
      });
    } catch (error) {
      pushMessage({ role: "Agent", text: `生成长期记忆草案失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function handleApplyMemoryPatchCandidate(candidate: MemoryPatchCandidate) {
    if (isBusy) return;
    setIsRunning(true);
    try {
      const result = await applyMemoryPatchCandidate({
        conversationId,
        draftId: memoryPatchDraft?.id,
        candidate
      });
      await refreshRuntimeState();
      pushMessage({
        role: "系统",
        text: `长期记忆草案已写入：${result.item.title}\n${result.item.lastPatch?.summary ?? ""}`
      });
      setMemoryPatchDraft((draft) =>
        draft ? { ...draft, candidates: draft.candidates.filter((item) => item.id !== candidate.id) } : draft
      );
    } catch (error) {
      pushMessage({ role: "Agent", text: `写入长期记忆草案失败：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      setIsRunning(false);
    }
  }

  async function openSandboxFile(path: string) {
    if (isRunning) return;
    setSelectedFilePath(path);
    try {
      const file = await readSandboxFile(conversationId, path);
      setSelectedFile(file);
    } catch (error) {
      setSelectedFile(null);
      pushMessage({ role: "Agent", text: `读取文件失败：${error instanceof Error ? error.message : String(error)}` });
    }
  }

  async function openDiffFile(path: string) {
    if (isRunning) return;
    try {
      const diff = await getFileDiff(conversationId, path);
      setSelectedDiff(diff.files[0] ?? { path, status: "unknown", additions: 0, deletions: 0, diff: "" });
    } catch (error) {
      setSelectedDiff(null);
      pushMessage({ role: "Agent", text: `读取 Diff 失败：${error instanceof Error ? error.message : String(error)}` });
    }
  }

  async function openCheckpointDiff(checkpointId: string) {
    if (isRunning) return;
    setSelectedCheckpointId(checkpointId);
    try {
      const diff = await getCheckpointDiff(conversationId, checkpointId);
      setCheckpointDiff(diff);
    } catch (error) {
      setCheckpointDiff(null);
      pushMessage({ role: "Agent", text: `读取 checkpoint Diff 失败：${error instanceof Error ? error.message : String(error)}` });
    }
  }

  return {
    activeModelName,
    agentTurn,
    checkpoints,
    checkpointDiff,
    conversations: visibleConversations,
    conversationId,
    currentDiff,
    events,
    mcpConfig,
    mcpConfigValidation,
    mcpServers,
    mcpTools,
    mcpHistory,
    approvals,
    autopilotEnabled,
    metrics,
    runtimeSnapshot,
    sandboxRuntime,
    memory,
    memoryPatchDraft,
    deliveryReport,
    deliveryPreview,
    previewSmokeReport,
    githubUrl,
    isRunning: isBusy,
    isExecutingToolPlan,
    executionStatus,
    localPath,
    messages,
    models,
    phaseLabel,
    preflight,
    previewCommand,
    processes,
    repository,
    requirement,
    sandbox,
    sandboxFiles,
    selectedFile,
    selectedFilePath,
    selectedCheckpointId,
    selectedDiff,
    skills,
    toolPlan,
    connectGithub: () => connectRepository("github"),
    connectLocal: () => connectRepository("local"),
    handleApproveToolPlan,
    handleConfirmAndExecuteToolPlan,
    handleConfirmPlan,
    handleCreateRepairPlan,
    handleEditTaskState,
    handleEditToolPlanStep,
    handleRewriteToolPlan,
    handleDenyToolApproval,
    handleExecuteToolPlan,
    handleDiscoverMCPTools,
    handleGenerateDeliveryPackage,
    handleApplyDeliveryToSource,
    handleGrantToolApproval,
    handleModelChange,
    handlePinMemory,
    handleForgetMemory,
    handleUpsertManualMemory,
    handleGenerateMemoryPatchDraft,
    handleApplyMemoryPatchCandidate,
    handleRevokeApproval,
    handleReplayMCPHistory,
    handleRollbackCheckpoint,
    handleRollbackCheckpointFile,
    handleRollbackCheckpointHunk,
    handleRollbackOriginal,
    handleRunAgent,
    handleRunPreviewSmokeTest,
    handleSaveMCPConfig,
    handleValidateMCPConfig,
    handleStartPreview,
    handleStopPreview,
    openSandboxFile,
    openDiffFile,
    openCheckpointDiff,
    refreshEvidence,
    resetConversation,
    removeConversation,
    selectConversation,
    setAutopilotEnabled,
    setGithubUrl,
    setLocalPath,
    setPreviewCommand,
    setRequirement
  };
}
