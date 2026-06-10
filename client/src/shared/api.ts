import type {
  AgentConversationState,
  AgentConversationSummary,
  AgentOrchestratorBundle,
  AgentTurnResult,
  ApprovalGrant,
  ApprovalMatrixRow,
  CheckpointManifest,
  DeliveryApplyResult,
  DeliveryPreview,
  DeliveryReport,
  DeliverySubmission,
  DeliverySubmissionStatus,
  ManagedProcess,
  MCPConfigValidation,
  MCPDiscoveryResult,
  MCPManifest,
  MCPServerManifest,
  MCPToolHistoryEntry,
  MCPToolManifest,
  MemoryPatchCandidate,
  MemoryPatchDraft,
  MemoryRecallItem,
  MemorySnapshot,
  ModelSettings,
  PreflightResult,
  PreviewSmokeReport,
  RepositoryStatus,
  RollbackReportDetail,
  RollbackReportSummary,
  RuntimeEvent,
  RuntimeMetricsResponse,
  SandboxRuntimeSnapshot,
  RollbackConfirmationSummary,
  RuntimeSnapshot,
  SandboxDiffResponse,
  SandboxFileContent,
  SandboxFileTree,
  SandboxStatus,
  SkillSummary,
  TaskStateMachineSummary,
  ToolCallPlan,
  VerificationRunReport
} from "@workbench/shared";

// 前端统一走 Node 网关(:4000);网关将 /api/* 转发给 Agent 运行时。
const apiBase = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:4000";

export type { CheckpointManifest } from "@workbench/shared";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export interface SandboxConnectResult {
  sandbox: SandboxStatus;
  repository: RepositoryStatus;
}

export interface RollbackResult {
  ok: boolean;
  summary: string;
  checkpointId?: string;
  relativePath?: string;
  hunkIndex?: number;
  restoredFiles?: string[];
  removedFiles?: string[];
  rollbackReport?: {
    id?: string;
    operation?: string;
    summary?: string;
    affectedFiles?: string[];
    beforeFileCount?: number | null;
    afterFileCount?: number | null;
    confirmation?: RollbackConfirmationSummary | null;
    reportPath?: string;
    createdAt?: string;
  };
}

export function getModelSettings() {
  return requestJson<ModelSettings>("/api/models");
}

export function saveModelSettings(input: Pick<ModelSettings, "defaultModelId">) {
  return requestJson<ModelSettings>("/api/models", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
}

export function getSkills() {
  return requestJson<SkillSummary[]>("/api/skills");
}

export function selectSkills(input: { conversationId: string; requirement: string }) {
  return postJson<SkillSummary[]>("/api/skills/select", input);
}

export function getMCPManifest() {
  return requestJson<MCPManifest>("/api/mcp/manifest");
}

export function getMCPTools(query?: string) {
  const suffix = query ? `?query=${encodeURIComponent(query)}` : "";
  return requestJson<MCPToolManifest[]>(`/api/mcp/tools${suffix}`);
}

export function getMCPServers() {
  return requestJson<MCPServerManifest[]>("/api/mcp/servers");
}

export function getMCPConfig() {
  return requestJson<Record<string, unknown>>("/api/mcp/config");
}

export function saveMCPConfig(input: Record<string, unknown>) {
  return requestJson<Record<string, unknown>>("/api/mcp/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
}

export function validateMCPConfig(input: Record<string, unknown>) {
  return postJson<MCPConfigValidation>("/api/mcp/config/validate", input);
}

export function discoverMCPTools(input: { timeoutSeconds?: number } = {}) {
  return postJson<MCPDiscoveryResult>("/api/mcp/discover", input);
}

export function runMCPTool(input: { conversationId: string; toolId: string; input?: unknown; approved?: boolean; userInitiated?: boolean }) {
  return postJson<Record<string, unknown>>("/api/mcp/run", input);
}

export function replayMCPHistory(input: { conversationId: string; historyEntryId: string }) {
  return postJson<Record<string, unknown>>("/api/mcp/replay", input);
}

export function getMCPHistory(conversationId: string, toolId?: string, limit = 80) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (toolId) params.set("toolId", toolId);
  return requestJson<MCPToolHistoryEntry[]>(`/api/mcp/history/${conversationId}?${params.toString()}`);
}

export function getApprovalMatrix() {
  return requestJson<ApprovalMatrixRow[]>("/api/policy/matrix");
}

export function getApprovals(conversationId: string) {
  return requestJson<ApprovalGrant[]>(`/api/approvals/${conversationId}`);
}

export function grantApproval(input: {
  conversationId: string;
  toolId: string;
  riskLevel?: string;
  scope?: "once" | "turn" | "session";
  command?: string;
  note?: string;
  requestEventId?: string;
}) {
  return postJson<ApprovalGrant>("/api/approvals/grant", input);
}

export function denyApproval(input: {
  conversationId: string;
  toolId: string;
  riskLevel?: string;
  reason: string;
  requestEventId?: string;
  command?: string;
}) {
  return postJson<ApprovalGrant>("/api/approvals/deny", input);
}

export function revokeApproval(input: { conversationId: string; grantId: string }) {
  return postJson<ApprovalGrant>("/api/approvals/revoke", input);
}

export function getRuntimeMetrics(conversationId: string) {
  return requestJson<RuntimeMetricsResponse>(`/api/metrics/${conversationId}`);
}

export function getRuntimeSnapshot(conversationId: string) {
  return requestJson<RuntimeSnapshot>(`/api/runtime/snapshot/${conversationId}`);
}

export function getTaskStateMachine(conversationId: string) {
  return requestJson<TaskStateMachineSummary>(`/api/runtime/task-state/${conversationId}`);
}

export function editTaskStateMachine(input: {
  conversationId: string;
  operation: "annotate_stage" | "pause_stage" | "resume_stage" | "set_next_actions" | "clear_next_actions";
  stageId?: string;
  note?: string;
  actionIds?: string[];
}) {
  return postJson<RuntimeSnapshot>("/api/runtime/task-state/edit", input);
}

export function getSandboxRuntime(conversationId: string) {
  return requestJson<SandboxRuntimeSnapshot>(`/api/runtime/sandbox/${conversationId}`);
}

export function getMemory(conversationId: string) {
  return requestJson<MemorySnapshot>(`/api/conversations/${conversationId}/memory`);
}

export function pinMemory(input: { itemId: string; value?: boolean }) {
  return postJson<{ ok: boolean; item: MemoryRecallItem }>("/api/memory/pin", input);
}

export function forgetMemory(input: { itemId: string; value?: boolean }) {
  return postJson<{ ok: boolean; item: MemoryRecallItem }>("/api/memory/forget", input);
}

export function upsertManualMemory(input: {
  conversationId: string;
  itemId?: string;
  title: string;
  content: string;
  kind?: string;
  tags?: string[];
  pinned?: boolean;
  importance?: number;
}) {
  return postJson<{ ok: boolean; item: MemoryRecallItem }>("/api/memory/manual", input);
}

export function generateMemoryPatchDraft(input: { conversationId: string; instruction?: string; maxItems?: number }) {
  return postJson<MemoryPatchDraft>("/api/memory/patch/draft", input);
}

export function applyMemoryPatchCandidate(input: { conversationId: string; draftId?: string; candidate: MemoryPatchCandidate }) {
  return postJson<{ ok: boolean; item: MemoryRecallItem }>("/api/memory/patch/apply", input);
}

export function generateDeliveryPackage(input: { conversationId: string }) {
  return postJson<DeliveryReport>("/api/delivery/package", input);
}

export function getDeliveryPreview(conversationId: string) {
  return requestJson<DeliveryPreview>(`/api/delivery/preview/${conversationId}`);
}

export function applyDeliveryToSource(input: { conversationId: string; confirmed: boolean }) {
  return postJson<DeliveryApplyResult>("/api/delivery/apply-to-source", input);
}

export function submitDelivery(input: { conversationId: string; confirmed: boolean; title?: string; baseBranch?: string }) {
  return postJson<DeliverySubmission>("/api/delivery/submit", input);
}

export function getDeliverySubmission(conversationId: string) {
  return requestJson<DeliverySubmissionStatus>(`/api/delivery/submission/${conversationId}`);
}

export function getConversation(conversationId: string) {
  return requestJson<AgentConversationState>(`/api/conversations/${conversationId}`);
}

export function listConversations() {
  return requestJson<AgentConversationSummary[]>("/api/conversations");
}

export function deleteConversation(conversationId: string) {
  return requestJson<{ ok: boolean; conversationId: string; summary: string }>(`/api/conversations/${conversationId}`, {
    method: "DELETE"
  });
}

export function getEvents(conversationId: string) {
  return requestJson<RuntimeEvent[]>(`/api/events/${conversationId}?limit=120`);
}

export function runPreflight(input: { conversationId: string; requirement: string }) {
  return postJson<PreflightResult>("/api/preflight", input);
}

export function runAgentPlanning(input: { conversationId: string; requirement: string }) {
  return postJson<AgentTurnResult>("/api/agent/planning", input);
}

export function confirmAgentPlan(input: { conversationId: string }) {
  return postJson<AgentTurnResult>("/api/agent/confirm-plan", input);
}

export function createToolCallPlan(input: { conversationId: string; requirement?: string; steps?: Array<Record<string, unknown>> }) {
  return postJson<ToolCallPlan>("/api/agent/tool-plan", input);
}

export function getToolCallPlan(conversationId: string) {
  return requestJson<ToolCallPlan>(`/api/agent/tool-plan/${conversationId}`);
}

export function approveToolCallPlan(input: { conversationId: string; planId?: string }) {
  return postJson<ToolCallPlan>("/api/agent/tool-plan/approve", input);
}

export function executeToolCallPlan(input: { conversationId: string; planId?: string }) {
  return postJson<AgentOrchestratorBundle>("/api/agent/tool-plan/execute", input);
}

export function editToolCallPlan(input: {
  conversationId: string;
  planId?: string;
  operation: "skip_step" | "restore_step" | "update_step" | "move_step";
  stepId: string;
  reason?: string;
  title?: string;
  purpose?: string;
  input?: Record<string, unknown>;
  targetOrder?: number;
}) {
  return postJson<ToolCallPlan>("/api/agent/tool-plan/edit", input);
}

export function rewriteToolCallPlan(input: { conversationId: string; planId?: string; instruction: string }) {
  return postJson<ToolCallPlan>("/api/agent/tool-plan/rewrite", input);
}

export function runOrchestratorAction(input: {
  conversationId: string;
  action: "submit_requirement" | "approve_plan" | "approve_tool_plan" | "execute_tool_plan" | "repair_failed_plan" | "refresh";
  requirement?: string;
  planId?: string;
}) {
  return postJson<AgentOrchestratorBundle>("/api/agent/orchestrator", input);
}

export function cloneGitHubSandbox(input: { conversationId: string; repoUrl: string }) {
  return postJson<SandboxConnectResult>("/api/sandboxes/github", input);
}

export function connectLocalSandbox(input: { conversationId: string; sourcePath: string }) {
  return postJson<SandboxConnectResult>("/api/sandboxes/local", input);
}

export function getCheckpoints(conversationId: string) {
  return requestJson<CheckpointManifest[]>(`/api/checkpoints/${conversationId}`);
}

export function getSandboxFiles(conversationId: string) {
  return requestJson<SandboxFileTree>(`/api/sandbox/files/${conversationId}`);
}

export function readSandboxFile(conversationId: string, path: string) {
  return requestJson<SandboxFileContent>(`/api/sandbox/file/${conversationId}?path=${encodeURIComponent(path)}`);
}

export function getCurrentDiff(conversationId: string) {
  return requestJson<SandboxDiffResponse>(`/api/diff/current/${conversationId}`);
}

export function getFileDiff(conversationId: string, path: string) {
  return requestJson<SandboxDiffResponse>(`/api/diff/file/${conversationId}?path=${encodeURIComponent(path)}`);
}

export function getCheckpointDiff(conversationId: string, checkpointId: string) {
  return requestJson<SandboxDiffResponse>(`/api/diff/checkpoint/${conversationId}?checkpointId=${encodeURIComponent(checkpointId)}`);
}

export function rollbackCheckpoint(input: { conversationId: string; checkpointId: string }) {
  return postJson<RollbackResult>("/api/rollback/checkpoint", input);
}

export function rollbackCheckpointFile(input: { conversationId: string; checkpointId: string; relativePath: string }) {
  return postJson<RollbackResult>("/api/rollback/checkpoint-file", input);
}

export function rollbackCheckpointHunk(input: { conversationId: string; checkpointId: string; relativePath: string; hunkIndex: number }) {
  return postJson<RollbackResult>("/api/rollback/checkpoint-hunk", input);
}

export function rollbackOriginal(input: { conversationId: string; confirmed: boolean }) {
  return postJson<RollbackResult>("/api/rollback/original", input);
}

export function getRollbackReports(conversationId: string) {
  return requestJson<RollbackReportSummary[]>(`/api/rollback/reports/${conversationId}`);
}

export function getRollbackReport(conversationId: string, reportId: string) {
  return requestJson<RollbackReportDetail>(`/api/rollback/report/${conversationId}/${reportId}`);
}

export function startPreview(input: { conversationId: string; command: string; ports?: number[] }) {
  return postJson<ManagedProcess>("/api/preview/start", input);
}

export function stopPreview(input: { conversationId: string; processId: string }) {
  return postJson<ManagedProcess>("/api/preview/stop", input);
}

export function runPreviewSmokeTest(input: {
  conversationId: string;
  port: number;
  path?: string;
  timeoutSeconds?: number;
  expectedTexts?: string[];
  requiredSelectors?: string[];
}) {
  return postJson<PreviewSmokeReport>("/api/preview/smoke-test", input);
}

export function getPreviewScreenshotUrl(conversationId: string, version?: string | number | null) {
  const suffix = version ? `?v=${encodeURIComponent(String(version))}` : "";
  return `${apiBase}/api/preview/screenshot/${conversationId}${suffix}`;
}

export function runVerification(input: { conversationId: string; commands?: Record<string, string>; timeoutSeconds?: number }) {
  return postJson<VerificationRunReport>("/api/verification/run", input);
}

export function getProcesses() {
  return requestJson<ManagedProcess[]>("/api/processes");
}
