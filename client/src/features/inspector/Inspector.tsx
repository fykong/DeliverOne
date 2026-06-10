import { RefreshCw } from "lucide-react";
import { ApprovalPanel } from "./ApprovalPanel";
import { CurrentContextPanel } from "./CurrentContextPanel";
import { DeliveryPanel } from "./DeliveryPanel";
import { EventStreamPanel } from "./EventStreamPanel";
import { EvidencePanel } from "./EvidencePanel";
import { MCPPanel } from "./MCPPanel";
import { MemoryPanel } from "./MemoryPanel";
import { MetricsPanel } from "./MetricsPanel";
import { PreviewPanel } from "./PreviewPanel";
import { RollbackPanel } from "./RollbackPanel";
import { RuntimePanel } from "./RuntimePanel";
import { SandboxRuntimePanel } from "./SandboxRuntimePanel";
import { SandboxFilePanel } from "./SandboxFilePanel";
import { ToolPlanPanel } from "./ToolPlanPanel";
import { phaseLabels } from "./constants";
import type { InspectorProps } from "./types";

export function Inspector({
  conversationId,
  preflight,
  agentTurn,
  toolPlan,
  checkpoints,
  processes,
  events,
  mcpConfig,
  mcpConfigValidation,
  mcpServers,
  mcpTools,
  mcpHistory,
  approvals,
  metrics,
  runtimeSnapshot,
  sandboxRuntime,
  memory,
  memoryPatchDraft,
  deliveryReport,
  deliveryPreview,
  previewSmokeReport,
  sandboxFiles,
  selectedFile,
  selectedFilePath,
  currentDiff,
  selectedDiff,
  checkpointDiff,
  selectedCheckpointId,
  skills,
  isRunning,
  previewCommand,
  onPreviewCommandChange,
  onConfirmPlan,
  onConfirmAndExecuteToolPlan,
  onCreateRepairPlan,
  onEditToolPlanStep,
  onRewriteToolPlan,
  onRollbackCheckpoint,
  onRollbackCheckpointFile,
  onRollbackCheckpointHunk,
  onRollbackOriginal,
  onStartPreview,
  onStopPreview,
  onRunPreviewSmokeTest,
  onGenerateDeliveryPackage,
  onApplyDeliveryToSource,
  onDiscoverMCPTools,
  onSaveMCPConfig,
  onValidateMCPConfig,
  onReplayMCPHistory,
  onGrantToolApproval,
  onDenyToolApproval,
  onRevokeApproval,
  onPinMemory,
  onForgetMemory,
  onUpsertManualMemory,
  onGenerateMemoryPatchDraft,
  onApplyMemoryPatchCandidate,
  onRefreshEvidence,
  onEditTaskState,
  onOpenSandboxFile,
  onOpenDiffFile,
  onOpenCheckpointDiff
}: InspectorProps) {
  const currentPhase = agentTurn ? phaseLabels[agentTurn.phase] : preflight ? "仓库已接入" : "等待仓库";

  return (
    <aside className="inspector">
      <div className="inspectorHeader">
        <div>
          <h2>交付面板</h2>
          <p>{currentPhase}</p>
        </div>
        <button className="iconButton" type="button" onClick={onRefreshEvidence} disabled={isRunning} title="刷新证据">
          <RefreshCw size={16} />
        </button>
      </div>

      <CurrentContextPanel preflight={preflight} agentTurn={agentTurn} skills={skills} isRunning={isRunning} onConfirmPlan={onConfirmPlan} />
      <RuntimePanel snapshot={runtimeSnapshot} isRunning={isRunning} onEditTaskState={onEditTaskState} />
      <SandboxRuntimePanel snapshot={sandboxRuntime} />
      <ToolPlanPanel
        toolPlan={toolPlan}
        isRunning={isRunning}
        onConfirmAndExecuteToolPlan={onConfirmAndExecuteToolPlan}
        onCreateRepairPlan={onCreateRepairPlan}
        onEditToolPlanStep={onEditToolPlanStep}
        onRewriteToolPlan={onRewriteToolPlan}
        onOpenDiffFile={onOpenDiffFile}
        onOpenCheckpointDiff={onOpenCheckpointDiff}
        onRollbackCheckpoint={onRollbackCheckpoint}
      />
      <ApprovalPanel events={events} approvals={approvals} isRunning={isRunning} onGrant={onGrantToolApproval} onDeny={onDenyToolApproval} />
      <PreviewPanel
        conversationId={conversationId}
        processes={processes}
        previewSmokeReport={previewSmokeReport}
        previewCommand={previewCommand}
        recommendedPreview={sandboxRuntime?.commandRecommendations?.preview.primary ?? null}
        isRunning={isRunning}
        onPreviewCommandChange={onPreviewCommandChange}
        onStartPreview={onStartPreview}
        onStopPreview={onStopPreview}
        onRunPreviewSmokeTest={onRunPreviewSmokeTest}
      />
      <MCPPanel
        config={mcpConfig}
        configValidation={mcpConfigValidation}
        servers={mcpServers}
        tools={mcpTools}
        history={mcpHistory}
        approvals={approvals}
        isRunning={isRunning}
        onDiscover={onDiscoverMCPTools}
        onSaveConfig={onSaveMCPConfig}
        onValidateConfig={onValidateMCPConfig}
        onReplayHistory={onReplayMCPHistory}
        onGrant={onGrantToolApproval}
        onRevoke={onRevokeApproval}
      />
      <EvidencePanel toolPlan={toolPlan} checkpoints={checkpoints} />
      <MemoryPanel
        memory={memory}
        memoryPatchDraft={memoryPatchDraft}
        isRunning={isRunning}
        onPinMemory={onPinMemory}
        onForgetMemory={onForgetMemory}
        onUpsertManualMemory={onUpsertManualMemory}
        onGenerateMemoryPatchDraft={onGenerateMemoryPatchDraft}
        onApplyMemoryPatchCandidate={onApplyMemoryPatchCandidate}
      />
      <MetricsPanel metrics={metrics} />
      <DeliveryPanel
        conversationId={conversationId}
        deliveryReport={deliveryReport}
        deliveryPreview={deliveryPreview}
        isRunning={isRunning}
        onGenerateDeliveryPackage={onGenerateDeliveryPackage}
        onApplyDeliveryToSource={onApplyDeliveryToSource}
      />
      <SandboxFilePanel
        sandboxFiles={sandboxFiles}
        selectedFile={selectedFile}
        selectedFilePath={selectedFilePath}
        currentDiff={currentDiff}
        selectedDiff={selectedDiff}
        checkpointDiff={checkpointDiff}
        selectedCheckpointId={selectedCheckpointId}
        checkpoints={checkpoints}
        isRunning={isRunning}
        onOpenSandboxFile={onOpenSandboxFile}
        onOpenDiffFile={onOpenDiffFile}
        onOpenCheckpointDiff={onOpenCheckpointDiff}
        onRollbackCheckpoint={onRollbackCheckpoint}
        onRollbackCheckpointFile={onRollbackCheckpointFile}
        onRollbackCheckpointHunk={onRollbackCheckpointHunk}
      />
      <EventStreamPanel events={events} />
      <RollbackPanel
        conversationId={conversationId}
        checkpoints={checkpoints}
        sandboxRuntime={sandboxRuntime}
        isRunning={isRunning}
        onRollbackCheckpoint={onRollbackCheckpoint}
        onRollbackOriginal={onRollbackOriginal}
      />
    </aside>
  );
}
