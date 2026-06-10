import type {
  AgentTurnResult,
  ApprovalGrant,
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
  PreflightResult,
  PreviewSmokeReport,
  RuntimeMetricsResponse,
  RuntimeSnapshot,
  SandboxRuntimeSnapshot,
  RuntimeEvent,
  SandboxFileContent,
  SandboxDiffFile,
  SandboxDiffResponse,
  SandboxTreeItem,
  SkillSummary,
  ToolCallPlan
} from "@workbench/shared";
import type { CheckpointManifest } from "../../shared/api";

export interface InspectorProps {
  conversationId: string;
  preflight: PreflightResult | null;
  agentTurn: AgentTurnResult | null;
  toolPlan: ToolCallPlan | null;
  checkpoints: CheckpointManifest[];
  processes: ManagedProcess[];
  events: RuntimeEvent[];
  mcpConfig: Record<string, unknown> | null;
  mcpConfigValidation: MCPConfigValidation | null;
  mcpServers: MCPServerManifest[];
  mcpTools: MCPToolManifest[];
  mcpHistory: MCPToolHistoryEntry[];
  approvals: ApprovalGrant[];
  metrics: RuntimeMetricsResponse | null;
  runtimeSnapshot: RuntimeSnapshot | null;
  sandboxRuntime: SandboxRuntimeSnapshot | null;
  memory: MemorySnapshot | null;
  memoryPatchDraft: MemoryPatchDraft | null;
  deliveryReport: DeliveryReport | null;
  deliveryPreview: DeliveryPreview | null;
  previewSmokeReport: PreviewSmokeReport | null;
  sandboxFiles: SandboxTreeItem[];
  selectedFile: SandboxFileContent | null;
  selectedFilePath: string | null;
  currentDiff: SandboxDiffResponse | null;
  selectedDiff: SandboxDiffFile | null;
  checkpointDiff: SandboxDiffResponse | null;
  selectedCheckpointId: string | null;
  skills: SkillSummary[];
  isRunning: boolean;
  previewCommand: string;
  onPreviewCommandChange: (value: string) => void;
  onConfirmPlan: () => void;
  onConfirmAndExecuteToolPlan: () => void;
  onCreateRepairPlan: () => void;
  onEditToolPlanStep: (
    operation: "skip_step" | "restore_step" | "update_step" | "move_step",
    stepId: string,
    options?: { reason?: string; title?: string; purpose?: string; input?: Record<string, unknown>; targetOrder?: number }
  ) => void;
  onRewriteToolPlan: (instruction: string) => void;
  onRollbackCheckpoint: (checkpointId: string) => void;
  onRollbackCheckpointFile: (checkpointId: string, relativePath: string) => void;
  onRollbackCheckpointHunk: (checkpointId: string, relativePath: string, hunkIndex: number) => void;
  onRollbackOriginal: () => void;
  onStartPreview: () => void;
  onStopPreview: (processId: string) => void;
  onRunPreviewSmokeTest: (port: number) => void;
  onGenerateDeliveryPackage: () => void;
  onApplyDeliveryToSource: () => void;
  onDiscoverMCPTools: () => void;
  onSaveMCPConfig: (config: Record<string, unknown>) => void;
  onValidateMCPConfig: (config: Record<string, unknown>) => void;
  onReplayMCPHistory: (historyEntryId: string) => void;
  onGrantToolApproval: (toolId: string, scope: ApprovalGrant["scope"], riskLevel?: string, command?: string, requestEventId?: string) => void;
  onDenyToolApproval: (toolId: string, riskLevel: string, reason: string, requestEventId?: string, command?: string) => void;
  onRevokeApproval: (grantId: string) => void;
  onPinMemory: (itemId: string, pinned: boolean) => void;
  onForgetMemory: (itemId: string) => void;
  onUpsertManualMemory: (input: {
    itemId?: string;
    title: string;
    content: string;
    kind?: string;
    tags?: string[];
    pinned?: boolean;
    importance?: number;
  }) => void;
  onGenerateMemoryPatchDraft: () => void;
  onApplyMemoryPatchCandidate: (candidate: MemoryPatchCandidate) => void;
  onRefreshEvidence: () => void;
  onEditTaskState: (
    operation: "annotate_stage" | "pause_stage" | "resume_stage" | "set_next_actions" | "clear_next_actions",
    options?: { stageId?: string; note?: string; actionIds?: string[] }
  ) => void;
  onOpenSandboxFile: (path: string) => void;
  onOpenDiffFile: (path: string) => void;
  onOpenCheckpointDiff: (checkpointId: string) => void;
}
