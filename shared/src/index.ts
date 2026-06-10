export type RiskLevel = "read" | "write" | "command" | "apply" | "dangerous" | "external";

export type AgentPhase =
  | "idle"
  | "repository_required"
  | "sandbox_creating"
  | "sandbox_ready"
  | "preflight"
  | "clarification"
  | "planning"
  | "waiting_plan_confirmation"
  | "waiting_tool_plan_confirmation"
  | "waiting_sandbox"
  | "locating_code"
  | "ready_to_edit"
  | "checkpoint_before_write"
  | "editing"
  | "verifying"
  | "reviewing"
  | "delivery_ready"
  | "execution_blocked"
  | "execution_ready"
  | "tool_plan_approved"
  | "tool_plan_running"
  | "tool_plan_completed"
  | "tool_plan_failed"
  | "tool_plan_waiting_approval"
  | "completed"
  | "failed";

export interface ModelProviderConfig {
  id: string;
  displayName: string;
  provider: "ark" | "local" | "mock";
  endpoint?: string;
  model: string;
  apiKeyEnv?: string;
  modelEnv?: string;
  enabled: boolean;
  unavailableReason?: string;
  maxContextTokens?: number;
}

export interface ModelSettings {
  defaultModelId: string;
  models: ModelProviderConfig[];
  updatedAt: string;
}

export interface SkillSummary {
  id: string;
  name: string;
  description: string;
  riskLevel: "low" | "medium" | "high";
  requiresConfirmation: boolean;
  tools: string[];
  runtime?: {
    selectedReason: string;
    contentChars: number;
    truncated: boolean;
    constraints: string[];
    references: string[];
    scripts: string[];
  };
}

export interface RepositoryStatus {
  id: string;
  sourceType: "local" | "github";
  source: string;
  branch?: string;
  head?: string;
  packageManager?: "npm" | "pnpm" | "yarn" | "unknown";
  scripts: Record<string, string>;
  dirtyFileCount: number;
}

export interface SandboxStatus {
  id: string;
  conversationId: string;
  rootPath: string;
  repoPath: string;
  createdAt: string;
}

export interface PreflightResult {
  conversationId: string;
  repository?: RepositoryStatus;
  sandbox?: SandboxStatus;
  model: ModelProviderConfig;
  matchedSkills: SkillSummary[];
  memory: MemorySnapshot;
  searchIntent?: SearchIntentSnapshot;
  requiredConfirmations: string[];
  availableCommands: Record<string, string>;
}

export interface ContextPackSection {
  id: string;
  title: string;
  content: string;
  sourcePath?: string;
}

export interface ContextPack {
  conversationId: string;
  summary: string;
  sections: ContextPackSection[];
  generatedAt: string;
}

export interface RepoMemorySnapshot {
  profilePath: string;
  routeMapPath: string;
  packageScriptsPath: string;
  projectInstructionsPath?: string;
  summary: string[];
}

export interface ConversationMemorySnapshot {
  requirementPath: string;
  decisionsPath: string;
  failuresPath?: string;
  agentTurnsPath: string;
  memoryEntriesPath?: string;
  recallItemsPath?: string;
  recallDiagnosticsPath?: string;
  searchIntentPath?: string;
  taskLedgerPath?: string;
  summary: string[];
}

export interface DeliveryMemorySnapshot {
  checkpointsPath: string;
  verificationReportPath: string;
  changedFiles: number;
  rollbackPointCount: number;
}

export interface SkillMemorySnapshot {
  matchedSkillIds: string[];
  successPatternsPath: string;
  rejectedPatternsPath: string;
}

export interface SearchIntentSnapshot {
  source?: "model" | "rules" | string;
  summary?: string;
  businessEntities?: string[];
  fileHints?: string[];
  memoryQueries?: string[];
  riskHints?: string[];
  verificationHints?: string[];
  searchQueries?: string[];
  confidence?: number;
  fallbackReason?: string | null;
  rawResponse?: string;
  generatedAt?: string;
}

export interface TaskLedgerSnapshot {
  conversationId: string;
  status?: string;
  activePhase?: string;
  currentUnderstanding: string;
  repository?: {
    source?: string;
    branch?: string;
    head?: string;
    sandboxPath?: string;
  };
  searchIntent?: {
    source?: string;
    confidence?: number;
    searchQueries?: string[];
    fileHints?: string[];
    memoryQueries?: string[];
    riskHints?: string[];
    verificationHints?: string[];
    fallbackReason?: string | null;
  };
  contextUsed?: Array<{
    id?: string;
    kind?: string;
    title?: string;
    reason?: string;
    score?: number;
    sourcePath?: string;
  }>;
  matchedSkills?: Array<{
    id?: string;
    name?: string;
    reason?: string;
  }>;
  phases?: Array<{
    id: string;
    title: string;
    status: "done" | "current" | "pending" | "blocked" | string;
    description?: string;
  }>;
  gates?: Array<{
    id: string;
    title: string;
    status: "pass" | "pending" | "blocked" | "warning" | string;
    detail?: string;
  }>;
  risks?: string[];
  blockers?: string[];
  nextSteps?: string[];
  editable?: boolean;
  editNote?: string;
  updatedAt: string;
  path?: string;
}

export interface MemorySnapshot {
  conversationId: string;
  rootPath: string;
  repo: RepoMemorySnapshot;
  conversation: ConversationMemorySnapshot;
  delivery: DeliveryMemorySnapshot;
  skill: SkillMemorySnapshot;
  contextPack: ContextPack;
  recall?: {
    query: string;
    entryCount: number;
    candidateCount?: number;
    longTermCount?: number;
    patternCount?: number;
    curatedCount?: number;
    strategy?: string;
    path: string;
    diagnosticsPath?: string;
    longTermPath?: string;
    items: MemoryRecallItem[];
  };
  longTerm?: {
    namespace: string;
    path: string;
    count: number;
    items: MemoryRecallItem[];
  };
  patterns?: {
    count: number;
    path: string;
    items: MemoryPatternItem[];
  };
  searchIntent?: SearchIntentSnapshot;
  taskLedger?: TaskLedgerSnapshot;
  taskState?: TaskStateMachineSummary;
  curatedMemory?: CuratedMemorySnapshot;
  updatedAt: string;
}

export interface MemoryRecallItem {
  id: string;
  kind: "repo" | "requirement" | "decision" | "failure" | "agent" | "delivery" | "preview" | "skill" | string;
  title: string;
  content: string;
  score: number;
  sourcePath: string;
  tags: string[];
  createdAt?: string;
  scope?: "conversation" | "repository" | "workspace" | string;
  importance?: number;
  pinned?: boolean;
  reason?: string;
  matchSignals?: Record<string, number>;
  namespace?: string;
  manual?: boolean;
  updatedAt?: string;
  sourcePhase?: string;
  sourceConversationId?: string;
  sourceEntryId?: string;
  lastPatch?: MemoryPatchSummary | null;
  patchHistory?: MemoryPatchSummary[];
}

export interface MemoryPatchSummary {
  operation: "create" | "update" | string;
  summary: string;
  changedFields: string[];
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  conflicts: Array<{
    type: string;
    severity: "info" | "warning" | "error" | string;
    summary: string;
    evidence?: Record<string, unknown>;
  }>;
  createdAt: string;
}

export interface MemoryPatchReview {
  itemId: string;
  namespace: string;
  patch: MemoryPatchSummary;
}

export interface MemoryPatchCandidate {
  id: string;
  itemId?: string;
  title: string;
  content: string;
  kind: string;
  tags: string[];
  pinned: boolean;
  importance: number;
  reason?: string;
  source?: string;
  review?: MemoryPatchReview;
}

export interface MemoryPatchDraft {
  id: string;
  conversationId: string;
  source: "model" | "rules" | "model-fallback" | string;
  namespace: string;
  summary: string;
  instruction?: string;
  rawResponse?: string;
  fallbackReason?: string | null;
  candidates: MemoryPatchCandidate[];
  createdAt: string;
}

export interface MemoryPatternItem {
  id: string;
  kind: "pattern" | string;
  namespace?: string;
  repoSource?: string;
  conversationId?: string;
  outcome: "failure" | "success" | "evidence" | string;
  category: string;
  title: string;
  content: string;
  recommendedAction?: string;
  sourcePath?: string;
  sourceEntryId?: string;
  tags: string[];
  scope?: "repository" | "workspace" | string;
  importance?: number;
  pinned?: boolean;
  hitCount?: number;
  firstSeenAt?: string;
  lastSeenAt?: string;
  examples?: string[];
}

export interface CuratedMemorySnapshot {
  namespace: string;
  repoSource?: string;
  repoMemoryPath: string;
  repoMemoryMarkdownPath: string;
  repairRecipesPath: string;
  verificationRecipesPath: string;
  globalPreferencesPath: string;
  eventLogPath: string;
  counts: {
    constraints?: number;
    decisions?: number;
    knownFailures?: number;
    repairRecipes?: number;
    verificationRecipes?: number;
    uiPreferences?: number;
    doNotRepeat?: number;
    globalPreferences?: number;
    total: number;
  };
  items: CuratedMemoryItem[];
  updatedAt: string;
}

export interface CuratedMemoryItem {
  id: string;
  kind: "curated" | string;
  title: string;
  content: string;
  sourcePath: string;
  tags: string[];
  scope?: "repository" | "workspace" | string;
  importance?: number;
  pinned?: boolean;
  createdAt?: string;
}

export interface AgentChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface AgentRunStep {
  id: string;
  title: string;
  detail: string;
  status: "done" | "running" | "blocked" | "failed";
}

export type AuditVerdict = "pass" | "warning" | "blocked";
export type FailureClass = "environment" | "code" | "plan" | "requirement" | "external" | "unknown";

export interface AgentAuditFinding {
  id: string;
  title: string;
  detail: string;
  severity: "info" | "warning" | "error";
}

export interface AgentAuditRecord {
  id: string;
  stage: "clarification" | "planning" | "plan_confirmation" | "pre_write" | "post_verify";
  source: string;
  verdict: AuditVerdict;
  findings: AgentAuditFinding[];
  summary?: string;
  recommendation?: string;
  questions?: string[];
  failureClass?: FailureClass;
  repairScope?: string;
  repairPolicy?: {
    failureClass: FailureClass;
    severity: "minor" | "major" | "blocked";
    autoAllowed: boolean;
    countsTowardCodeRepairLimit: boolean;
    requiresUserConfirmation: boolean;
    maxCodeRepairAttempts: number;
    maxTotalRepairSteps: number;
    reason: string;
  };
  modelSource?: "model" | "rules";
  model?: {
    id?: string;
    displayName?: string;
    provider?: string;
  };
  fallbackReason?: string;
  rawResponse?: string;
  reusedFrom: string[];
  createdAt: string;
}

export interface AgentTurnResult {
  conversationId: string;
  phase: AgentPhase;
  preflight: PreflightResult;
  model: ModelProviderConfig;
  reply: string;
  steps: AgentRunStep[];
  audits: AgentAuditRecord[];
  blockedReason?: string;
  toolResults?: Record<string, unknown>;
  createdAt: string;
}

export interface AgentConversationMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  createdAt: string;
}

export interface RuntimeStateTransition {
  id: string;
  from: AgentPhase;
  to: AgentPhase;
  event: string;
  actor: "user" | "agent" | "runtime" | "system";
  allowed: boolean;
  reason?: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
}

export interface ToolResultEvidence {
  stepId: string;
  toolId: string;
  ok: boolean;
  summary: string;
}

export interface ToolCheckpointEvidence {
  stepId: string;
  checkpointId?: string;
  label?: string;
}

export interface ToolVerificationEvidence {
  stepId: string;
  phase?: string | null;
  command?: string;
  exitCode?: number | null;
  ok: boolean;
  summary: string;
  durationMs?: number | null;
  timedOut?: boolean;
  stdoutTail?: string | null;
  stderrTail?: string | null;
  reportPath?: string | null;
  source?: string;
  generatedAt?: string | null;
}

export interface ToolPreviewEvidence {
  stepId: string;
  url?: string;
  ok: boolean;
  summary: string;
  failureClass?: string | null;
  httpStatus?: number | null;
  htmlTitle?: string | null;
  htmlBytes?: number;
  runtimeDomOk?: boolean;
  runtimeDomPath?: string | null;
  runtimeDomBytes?: number;
  runtimeDomVisibleTextLength?: number;
  consoleErrorCount?: number;
  consoleReliable?: boolean;
  consoleErrors?: Array<{ message?: string }>;
  assertions?: PreviewAssertionReport | null;
  screenshotOk?: boolean;
  screenshotPath?: string | null;
  reportPath?: string | null;
  source?: string;
  generatedAt?: string | null;
  quality?: PreviewQualityReport | null;
}

export interface ToolPlanEvidence {
  checkpoints: ToolCheckpointEvidence[];
  diffFiles: string[];
  verificationResults: ToolVerificationEvidence[];
  previewResults?: ToolPreviewEvidence[];
  toolResults: ToolResultEvidence[];
}

export interface ToolPlanGeneration {
  source: "model" | "fallback" | "heuristic" | "repair-loop" | "rewrite";
  rawResponse?: string;
  fallbackReason?: string | null;
  summary?: string | null;
}

export interface ToolCallPlanStep {
  id: string;
  order: number;
  kind: "tool";
  toolId: string;
  title: string;
  purpose: string;
  input: Record<string, unknown>;
  riskLevel: RiskLevel | "unknown";
  requiresApproval: boolean;
  requiresCheckpoint: boolean;
  status: "pending" | "running" | "completed" | "failed" | "waiting_approval" | "skipped";
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  updatedAt?: string;
  summary?: string;
  result?: Record<string, unknown>;
  checkpointId?: string;
  diffFiles?: string[];
  disabled?: boolean;
  disabledReason?: string;
}

export interface ToolPlanEditRecord {
  operation: "skip_step" | "restore_step" | "update_step" | "move_step" | "rewrite_plan" | string;
  stepId?: string;
  reason?: string | null;
  before?: Partial<ToolCallPlanStep>;
  after?: Partial<ToolCallPlanStep>;
  createdAt: string;
}

export interface ToolCallPlan {
  id: string;
  conversationId: string;
  requirement: string;
  status: "waiting_confirmation" | "approved" | "running" | "completed" | "failed" | "waiting_approval";
  repairOfPlanId?: string;
  repairAttempt?: number;
  repairSequence?: number;
  repairPolicy?: AgentAuditRecord["repairPolicy"];
  repairSource?: {
    planId?: string;
    status?: ToolCallPlan["status"] | string;
    summary?: string;
    failureClass?: string;
    verifierVerdict?: string | null;
    verifierSummary?: string | null;
    failedSteps?: Array<{
      id?: string;
      order?: number;
      title?: string;
      toolId?: string;
      summary?: string;
    }>;
  };
  repository?: RepositoryStatus;
  sandbox?: SandboxStatus;
  steps: ToolCallPlanStep[];
  evidence: ToolPlanEvidence;
  generation?: ToolPlanGeneration;
  audits?: AgentAuditRecord[];
  editHistory?: ToolPlanEditRecord[];
  reusedCodexMechanisms: string[];
  createdAt: string;
  updatedAt: string;
  approvedAt?: string;
  startedAt?: string;
  completedAt?: string;
}

export interface ToolCallPlanSummary {
  id?: string;
  status?: ToolCallPlan["status"];
  stepCount: number;
  updatedAt?: string;
  evidence?: ToolPlanEvidence;
}

export interface AgentPendingConfirmation {
  id: "plan" | "tool-call-plan";
  title: string;
  description: string;
  createdAt: string;
}

export interface AgentConversationState {
  conversationId: string;
  phase: AgentPhase;
  messages: AgentConversationMessage[];
  turns: AgentTurnResult[];
  audits: AgentAuditRecord[];
  pendingConfirmation?: AgentPendingConfirmation;
  lastRequirement?: string;
  repository?: RepositoryStatus;
  sandbox?: SandboxStatus;
  toolCallPlan?: ToolCallPlanSummary;
  lastTransition?: RuntimeStateTransition;
  stateTransitions?: RuntimeStateTransition[];
  stateWarnings?: string[];
  createdAt: string;
  updatedAt: string;
}

export interface AgentConversationSummary {
  conversationId: string;
  title: string;
  phase: AgentPhase;
  updatedAt?: string;
  createdAt?: string;
  repository?: RepositoryStatus;
  sandbox?: SandboxStatus;
  toolCallPlan?: ToolCallPlanSummary;
  lastTransition?: RuntimeStateTransition;
  stateWarningCount?: number;
}

export interface RuntimeEvent {
  id: string;
  type: string;
  actor: "user" | "agent" | "runtime" | "system";
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface MCPServerManifest {
  id?: string;
  name?: string;
  transport?: string;
  endpoint?: string;
  enabled: boolean;
  status: "configured" | "disabled" | "misconfigured";
  problems?: string[];
  details?: Record<string, unknown>;
  toolDiscovery?: "pending" | "unavailable" | "ready" | "failed";
  toolCount?: number;
  discoveryError?: string | null;
}

export interface MCPToolManifest {
  id: string;
  mcpName: string;
  source: "internal" | "external";
  serverId?: string;
  transport?: string;
  endpoint?: string;
  name: string;
  description: string;
  riskLevel: RiskLevel | "unknown";
  requiresCheckpoint: boolean;
  inputSchema: Record<string, unknown>;
  schemaSummary?: MCPSchemaSummary;
  approvalAware: boolean;
  sandboxScoped: boolean;
  capabilityTags?: string[];
  recommendationScore?: number;
  recommendationReason?: string;
  recommendationSignals?: string[];
}

export interface MCPSchemaPropertySummary {
  name: string;
  type: string;
  required: boolean;
  description?: string;
  enum?: string[];
}

export interface MCPSchemaSummary {
  type: string;
  required: string[];
  propertyCount: number;
  properties: MCPSchemaPropertySummary[];
}

export interface MCPPayloadPreview {
  text: string;
  truncated: boolean;
  bytes: number;
  kind: string;
}

export interface MCPApprovalSummary {
  needsApproval: boolean;
  allowed?: boolean;
  grantId?: string | null;
  reason?: string;
  riskLevel?: string;
}

export interface MCPConfigValidationIssue {
  path: string;
  message: string;
}

export interface MCPConfigValidation {
  ok: boolean;
  errors: MCPConfigValidationIssue[];
  warnings: MCPConfigValidationIssue[];
  normalized: Record<string, unknown>;
}

export interface MCPToolHistoryEntry {
  id: string;
  eventId?: string;
  conversationId?: string;
  toolId: string;
  toolName?: string;
  serverId?: string;
  transport?: string;
  planId?: string;
  stepId?: string;
  type: string;
  source: "internal" | "external" | string;
  status: "running" | "completed" | "failed" | "needs_approval" | "unknown";
  summary: string;
  inputSummary?: string;
  schemaSummary?: MCPSchemaSummary | null;
  inputPreview?: MCPPayloadPreview | null;
  resultPreview?: MCPPayloadPreview | null;
  approval?: MCPApprovalSummary | null;
  result?: unknown;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface MCPDiscoveryResult {
  ok: boolean;
  serverCount: number;
  toolCount: number;
  results: Array<{
    ok: boolean;
    serverId?: string;
    transport?: string;
    tools: unknown[];
    error?: string | null;
    stderrTail?: string;
    httpStatus?: number | null;
  }>;
  tools: MCPToolManifest[];
}

export interface MCPManifest {
  version: 1;
  mode: "internal-first";
  adapter: string;
  capabilities: {
    internalTools: boolean;
    externalServers: boolean;
    dynamicExternalExecution: boolean;
    externalServerDiagnostics?: boolean;
    stdioToolDiscovery?: boolean;
    stdioToolCall?: boolean;
    httpToolDiscovery?: boolean;
    httpToolCall?: boolean;
    sseConfig?: boolean;
    wsConfig?: boolean;
    sseToolCall?: boolean;
    wsToolCall?: boolean;
    approvalAware: boolean;
    sandboxScoped: boolean;
  };
  servers: MCPServerManifest[];
  tools: MCPToolManifest[];
}

export interface ApprovalMatrixRow {
  riskLevel: RiskLevel | "external" | "dangerous";
  defaultDecision: string;
  approvalRequired: boolean | string;
  checkpointRequired: boolean | string;
  scope: string;
  reason: string;
}

export interface ApprovalGrant {
  id: string;
  conversationId: string;
  toolId: string;
  riskLevel: string;
  scope: "once" | "turn" | "session";
  command?: string | null;
  note?: string | null;
  requestEventId?: string | null;
  decision?: "granted" | "denied" | "revoked";
  active: boolean;
  createdAt: string;
  usedAt?: string | null;
  revokedAt?: string | null;
  deniedAt?: string | null;
}

export interface RuntimeMetric {
  id: string;
  conversationId: string;
  kind: "model" | "tool";
  createdAt: string;
  source?: string;
  modelId?: string;
  modelName?: string;
  provider?: string;
  latencyMs?: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  estimatedCost?: {
    amount: number;
    currency: string;
    estimated: boolean;
    pricingConfigured: boolean;
  };
  toolId?: string;
  durationMs?: number;
  ok?: boolean;
  riskLevel?: string;
}

export interface RuntimeMetricSummary {
  conversationId: string;
  modelCallCount: number;
  toolCallCount: number;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  totalEstimatedCost: number;
  toolDurationMs: number;
  failedToolCalls: number;
  updatedAt: string;
}

export interface RuntimeMetricsResponse {
  summary: RuntimeMetricSummary;
  items: RuntimeMetric[];
}

export interface CheckpointManifest {
  id: string;
  conversationId: string;
  repoPath: string;
  label: string;
  files: Array<{ relativePath: string; existed: boolean; snapshotPath?: string; size: number }>;
  createdAt: string;
}

export interface AgentOrchestratorNextAction {
  id: string;
  label: string;
  kind: "read" | "approval" | "write" | "command";
}

export type RuntimeStageStatus = "done" | "current" | "pending" | "blocked" | string;

export interface RuntimeSnapshotStage {
  id: string;
  title: string;
  owner: string;
  status: RuntimeStageStatus;
  summary: string;
  evidence: Record<string, number>;
  actions: string[];
  userNote?: string;
  control?: {
    note?: string;
    paused?: boolean;
    updatedAt?: string;
    actor?: string;
  };
}

export interface TaskStateMachineSummary {
  schemaVersion: number;
  status: "ready" | "running" | "blocked" | string;
  activeStage: string;
  primaryStageIds: string[];
  stageCount: number;
  transitionCount: number;
  recentTransitions: Array<{
    from?: string;
    to?: string;
    event?: string;
    actor?: string;
    allowed?: boolean;
    createdAt?: string;
  }>;
  control?: {
    annotatedStageIds: string[];
    pausedStageIds: string[];
    manualNextActionIds: string[];
    manualNextActionNote?: string | null;
    editCount: number;
    latestEdit?: {
      operation?: string;
      stageId?: string | null;
      note?: string;
      actionIds?: string[];
      actor?: string;
      createdAt?: string;
    } | null;
  };
  path: string;
  updatedAt: string;
}

export interface RuntimeSnapshot {
  conversationId: string;
  phase: AgentPhase;
  summary: string;
  activeStage: string;
  stages: RuntimeSnapshotStage[];
  evidence: Record<string, number>;
  blockers: string[];
  warnings: string[];
  nextActions: AgentOrchestratorNextAction[];
  reusedCodexMechanisms: string[];
  stateMachine?: TaskStateMachineSummary;
  updatedAt: string;
}

export interface SandboxRuntimeStage {
  id: string;
  title: string;
  status: "done" | "current" | "pending" | "blocked" | string;
  summary: string;
  evidence: Record<string, number>;
}

export interface RuntimeCommandRecommendation {
  kind: "verification" | "preview" | string;
  phase: string;
  command: string;
  source: string;
  reason: string;
  confidence: number;
  scriptName?: string;
  ports?: number[];
}

export interface SandboxRuntimeSnapshot {
  conversationId: string;
  status: "ready" | "running" | "blocked" | "unknown" | string;
  repository?: {
    sourceType?: string;
    source?: string;
    branch?: string | null;
    head?: string | null;
    packageManager?: string;
    scriptCount: number;
  } | null;
  sandbox?: {
    id?: string;
    rootPath?: string;
    repoPath?: string;
    createdAt?: string;
  } | null;
  lifecycle: SandboxRuntimeStage[];
  processes: {
    total: number;
    running: number;
    failed: number;
    ports: number[];
    latest?: {
      id?: string;
      status?: string;
      command?: string;
      ports?: number[];
      updatedAt?: string;
    } | null;
  };
  preview: {
    status: "not_started" | "running" | "stopped" | "pass" | "fail" | string;
    summary: string;
    url?: string | null;
    reportPath?: string | null;
    htmlPath?: string | null;
    htmlTitle?: string | null;
    htmlBytes: number;
    runtimeDomPath?: string | null;
    runtimeDomOk?: boolean;
    runtimeDomBytes?: number;
    runtimeDomVisibleTextLength?: number;
    consoleErrorCount?: number;
    consoleReliable?: boolean;
    consoleErrors?: Array<{ message?: string }>;
    assertions?: PreviewAssertionReport | null;
    screenshotPath?: string | null;
    screenshotOk: boolean;
    quality?: PreviewQualityReport | null;
    generatedAt?: string | null;
  };
  verification: {
    status: "pass" | "fail" | "skipped" | "missing" | "unknown" | string;
    summary: string;
    reportPath?: string | null;
    generatedAt?: string | null;
    commandCount: number;
  };
  commandRecommendations?: {
    verification: {
      primary?: RuntimeCommandRecommendation | null;
      all: RuntimeCommandRecommendation[];
      commands: Record<string, string>;
    };
    preview: {
      primary?: RuntimeCommandRecommendation | null;
      all: RuntimeCommandRecommendation[];
    };
    source?: {
      packageJson?: string | null;
      pyproject?: string | null;
      generatedAt?: string;
      error?: string;
    };
  };
  files: {
    treeItems: number;
    textFiles: number;
    changedFiles: number;
    truncated: boolean;
  };
  checkpoints: {
    count: number;
    latest?: {
      id?: string;
      label?: string;
      fileCount: number;
      createdAt?: string;
    } | null;
  };
  delivery: {
    status: "generated" | "applied" | "missing" | string;
    summary: string;
    reportPath?: string | null;
    generatedAt?: string | null;
  };
  rollback: {
    eventCount: number;
    summary: string;
    report?: {
      id?: string;
      operation?: string;
      summary?: string;
      affectedFiles?: string[];
      beforeFileCount?: number | null;
      afterFileCount?: number | null;
      confirmation?: RollbackConfirmationSummary | null;
      reportPath?: string;
      createdAt?: string;
    } | null;
    latest?: Record<string, unknown> | null;
  };
  updatedAt: string;
}

export interface AutopilotTraceItem {
  action: string;
  phase?: string | null;
  planId?: string | null;
  round?: number;
  executedPlanId?: string | null;
  executedStatus?: string | null;
  nextPlanId?: string | null;
  nextPlanSource?: string | null;
}

export interface AutopilotSummary {
  finished: boolean;
  needsHuman: boolean;
  stage: string;
  reason: string;
  rounds: number;
  trace: AutopilotTraceItem[];
  delivery: {
    verificationGate?: string | null;
    changedFiles: number;
  } | null;
  submission: {
    mode?: "github-pr" | "pr-ready-branch" | string;
    branch?: string;
    commitSha?: string;
    prUrl?: string | null;
  } | null;
}

export interface AgentOrchestratorBundle {
  conversation: AgentConversationState;
  turn?: AgentTurnResult;
  toolPlan?: ToolCallPlan | null;
  executedToolPlan?: ToolCallPlan | null;
  repairPlan?: ToolCallPlan | null;
  repairLoop?: {
    created: boolean;
    sourcePlanId?: string;
    repairPlanId?: string;
    repairAttempt?: number;
    repairSequence?: number;
    reason: string;
  } | null;
  checkpoints: CheckpointManifest[];
  events: RuntimeEvent[];
  processes: ManagedProcess[];
  files?: SandboxFileTree | null;
  runtimeSnapshot?: RuntimeSnapshot;
  sandboxRuntime?: SandboxRuntimeSnapshot;
  nextActions: AgentOrchestratorNextAction[];
  /** 托管模式（/api/agent/autopilot）返回时附带的执行摘要。 */
  autopilot?: AutopilotSummary | null;
}

export interface ManagedProcess {
  id: string;
  conversationId: string;
  sandboxId: string;
  command: string;
  cwd: string;
  status: "starting" | "running" | "exited" | "failed" | "stopped";
  pid?: number;
  startedAt: string;
  updatedAt: string;
  stdoutTail: string;
  stderrTail: string;
  exitCode?: number;
  ports: number[];
  stopRequested?: boolean;
}

export interface PreviewSmokeReport {
  ok: boolean;
  conversationId: string;
  url: string;
  portOpen: boolean;
  httpStatus?: number;
  summary: string;
  htmlPath: string;
  htmlTitle?: string | null;
  htmlBytes: number;
  runtimeDom?: {
    ok: boolean;
    path?: string | null;
    bytes?: number;
    title?: string | null;
    visibleTextLength?: number;
    visibleTextSample?: string;
    stdoutTail?: string;
    stderr?: string;
    error?: string | null;
  };
  browserConsole?: {
    ok: boolean;
    mode: string;
    reliable?: boolean;
    errorCount: number;
    errors: Array<{ message?: string }>;
    warningCount?: number;
    warnings?: Array<{ message?: string }>;
    eventCount?: number;
    note?: string;
  };
  assertions?: PreviewAssertionReport;
  screenshot: {
    ok: boolean;
    path?: string | null;
    bytes?: number;
    error?: string;
    stdout?: string;
    stderr?: string;
  };
  quality: PreviewQualityReport;
  generatedAt: string;
  reportPath: string;
}

export interface PreviewQualityCheck {
  id: string;
  title: string;
  ok: boolean;
  detail: string;
  failureClass?: string | null;
  evidence: Record<string, unknown>;
}

export interface PreviewQualityIssue {
  id: string;
  title: string;
  detail: string;
  severity: "info" | "warning" | "error" | string;
}

export interface PreviewQualityReport {
  status: "pass" | "fail" | "warning" | string;
  summary: string;
  failureClass?: string | null;
  checks: PreviewQualityCheck[];
  warnings: PreviewQualityIssue[];
}

export interface PreviewAssertionTextResult {
  text: string;
  ok: boolean;
  detail: string;
}

export interface PreviewAssertionSelectorResult {
  selector: string;
  ok: boolean;
  count: number;
  detail: string;
}

export interface PreviewAssertionReport {
  enabled: boolean;
  ok: boolean;
  summary: string;
  expectedTexts: string[];
  requiredSelectors: string[];
  textResults: PreviewAssertionTextResult[];
  selectorResults: PreviewAssertionSelectorResult[];
}

export interface VerificationCommandResult {
  phase: string;
  command: string;
  ok: boolean;
  exitCode?: number | null;
  timedOut: boolean;
  durationMs: number;
  startedAt: string;
  finishedAt: string;
  stdoutTail: string;
  stderrTail: string;
  summary: string;
}

export interface VerificationRunReport {
  id: string;
  conversationId: string;
  generatedAt: string;
  repoPath: string;
  status: "pass" | "fail" | "skipped";
  summary: string;
  commands: Record<string, string>;
  results: VerificationCommandResult[];
  reportPath: string;
}

export interface SandboxTreeItem {
  path: string;
  name: string;
  type: "directory" | "file";
  depth: number;
  size: number;
  isText: boolean;
}

export interface SandboxFileTree {
  rootPath: string;
  items: SandboxTreeItem[];
  truncated: boolean;
}

export interface SandboxFileContent {
  path: string;
  name: string;
  size: number;
  language: string;
  content: string;
  truncated: boolean;
}

export type SandboxDiffStatus = "modified" | "added" | "deleted" | "renamed" | "unchanged" | "unknown";

export interface SandboxDiffFile {
  path: string;
  status: SandboxDiffStatus;
  additions: number;
  deletions: number;
  diff: string;
}

export interface SandboxDiffResponse {
  conversationId: string;
  kind: "current" | "file" | "checkpoint";
  summary: string;
  fileCount: number;
  files: SandboxDiffFile[];
  generatedAt: string;
  checkpointId?: string;
  checkpointLabel?: string;
  checkpointCreatedAt?: string;
}

export interface VerificationReport {
  build: "pass" | "fail" | "skipped";
  typecheck: "pass" | "fail" | "skipped";
  lint: "pass" | "fail" | "skipped";
  tests: "pass" | "fail" | "skipped";
  preview: "pass" | "fail" | "skipped";
  changedFiles: number;
  rollbackAvailable: boolean;
  generatedAt: string;
}

export interface DeliveryChangedFile {
  path: string;
  status: string;
  action: "copy" | "delete";
}

export interface RollbackReportSummary {
  id?: string;
  operation?: string;
  summary?: string;
  affectedFiles?: string[];
  beforeFileCount?: number | null;
  afterFileCount?: number | null;
  confirmation?: RollbackConfirmationSummary | null;
  reportPath?: string;
  createdAt?: string;
}

export interface RollbackConfirmationSummary {
  status: "clean" | "improved" | "unchanged" | "expanded" | "failed" | "unknown" | string;
  ok: boolean;
  summary: string;
  beforeFileCount: number;
  afterFileCount: number;
  beforeDiffBytes: number;
  afterDiffBytes: number;
}

export interface RollbackDiffSnapshot {
  fileCount: number;
  statusShort: string;
  diff: string;
  diffBytes: number;
  capturedAt: string;
}

export interface RollbackReportDetail extends RollbackReportSummary {
  conversationId: string;
  target?: Record<string, unknown>;
  repoPath?: string;
  ok?: boolean;
  before: RollbackDiffSnapshot;
  after: RollbackDiffSnapshot;
}

export interface DeliveryReport {
  id: string;
  conversationId: string;
  generatedAt: string;
  repository?: RepositoryStatus;
  sandbox?: SandboxStatus;
  toolPlan?: Record<string, unknown> | null;
  changedFiles: DeliveryChangedFile[];
  statusShort: string;
  diffStat: string;
  verificationGate: {
    status: "pass" | "fail" | "skipped" | "missing" | "unknown" | string;
    source: "verification-report" | "tool-plan" | "none" | string;
    summary: string;
    reportPath?: string | null;
    generatedAt?: string | null;
    commandCount: number;
  };
  previewGate?: {
    status: "pass" | "fail" | "missing" | "unknown" | string;
    source: "preview-smoke-report" | "tool-plan" | "none" | string;
    summary: string;
    reportPath?: string | null;
    screenshotPath?: string | null;
    screenshotOk: boolean;
    htmlTitle?: string | null;
    htmlBytes: number;
    runtimeDomPath?: string | null;
    runtimeDomOk?: boolean;
    runtimeDomBytes?: number;
    runtimeDomVisibleTextLength?: number;
    consoleErrorCount?: number;
    consoleReliable?: boolean;
    consoleErrors?: Array<{ message?: string }>;
    assertions?: PreviewAssertionReport | null;
    quality?: PreviewQualityReport | null;
    generatedAt?: string | null;
  };
  rollbackGate?: {
    status: "ready" | "used" | "missing" | string;
    source: "checkpoints" | "rollback-report" | "none" | string;
    summary: string;
    checkpointCount: number;
    rollbackAvailable: boolean;
    latest?: {
      id?: string;
      operation?: string;
      affectedFiles?: string[];
      beforeFileCount?: number;
      afterFileCount?: number;
      confirmation?: RollbackConfirmationSummary | null;
      reportPath?: string;
      createdAt?: string;
    } | null;
  };
  checkpointCount: number;
  checkpoints: Array<{ id?: string; label?: string; createdAt?: string }>;
  eventTail: Array<{ type?: string; actor?: string; createdAt?: string }>;
  artifacts: {
    patchPath: string;
    jsonPath: string;
    markdownPath: string;
  };
  notes: string[];
}

export interface DeliveryPreviewFile {
  path: string;
  content: string;
  bytes: number;
  truncated: boolean;
}

export interface DeliveryPreview {
  conversationId: string;
  exists: boolean;
  summary: string;
  report?: DeliveryReport | null;
  markdown?: DeliveryPreviewFile | null;
  patch?: DeliveryPreviewFile | null;
  generatedAt?: string | null;
}

export interface DeliveryApplyResult {
  ok: boolean;
  summary: string;
  applied: Array<{ path: string; action: "copy" | "delete" }>;
  backupPath: string;
}

export interface DeliverySubmissionPushResult {
  attempted: boolean;
  ok: boolean;
  detail: string;
}

export interface DeliverySubmissionPullRequestResult {
  attempted: boolean;
  ok: boolean;
  url?: string | null;
  number?: number;
  detail: string;
}

export interface DeliverySubmission {
  id: string;
  conversationId: string;
  generatedAt: string;
  branch: string;
  baseBranch: string;
  commitSha: string;
  title: string;
  requirement: string;
  remoteUrl?: string | null;
  githubRepo?: string | null;
  push: DeliverySubmissionPushResult;
  pullRequest: DeliverySubmissionPullRequestResult;
  artifacts: {
    prDescriptionPath: string;
    patchPath: string;
  };
  mode: "github-pr" | "pr-ready-branch";
  notes: string[];
}

export interface DeliverySubmissionStatus {
  conversationId: string;
  exists: boolean;
  submission?: DeliverySubmission | null;
}
