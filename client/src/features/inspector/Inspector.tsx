import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { ApprovalPanel } from "./ApprovalPanel";
import { CurrentContextPanel } from "./CurrentContextPanel";
import { DeliveryPanel } from "./DeliveryPanel";
import { EvidencePanel } from "./EvidencePanel";
import { MCPPanel } from "./MCPPanel";
import { MemoryPanel } from "./MemoryPanel";
import { MetricsPanel } from "./MetricsPanel";
import { PreviewPanel } from "./PreviewPanel";
import { RollbackPanel } from "./RollbackPanel";
import { RuntimePanel } from "./RuntimePanel";
import { SandboxRuntimePanel } from "./SandboxRuntimePanel";
import { SandboxFilePanel } from "./SandboxFilePanel";
import { SkillsPanel } from "./SkillsPanel";
import { ToolPlanPanel } from "./ToolPlanPanel";
import { phaseLabels } from "./constants";
import type { InspectorProps } from "./types";

export function Inspector({
  conversationId,
  preflight,
  repository,
  sandbox,
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
  isExecutingToolPlan,
  previewCommand,
  onPreviewCommandChange,
  onConfirmPlan,
  onConfirmAndExecuteToolPlan,
  onCreateRepairPlan,
  onContinuePlan,
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
  const currentPhase = agentTurn ? phaseLabels[agentTurn.phase] : preflight || repository ? "仓库已接入" : "等待仓库";
  const [activeTab, setActiveTab] = useState<TabKey>("overview");

  const tabs: { key: TabKey; label: string; badge?: number | string }[] = [
    { key: "overview", label: "概览" },
    { key: "plan", label: "工具计划", badge: toolPlan?.steps?.length || undefined },
    { key: "code", label: "代码与回退", badge: currentDiff?.files?.length || undefined },
    { key: "preview", label: "验证预览" },
    { key: "delivery", label: "交付" },
    { key: "memory", label: "记忆指标", badge: memory?.recall?.entryCount || undefined },
    { key: "events", label: "扩展" }
  ];

  return (
    <aside className="inspector">
      <div className="inspectorHeader">
        <div>
          <h2>交付面板</h2>
          <p>{currentPhase}</p>
        </div>
        <button className="iconButton" type="button" onClick={onRefreshEvidence} disabled={isRunning && !isExecutingToolPlan} title="刷新证据">
          <RefreshCw size={16} />
        </button>
      </div>

      <div className="inspectorTabs" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`inspectorTab ${activeTab === tab.key ? "active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
            {tab.badge ? <span className="tabBadge">{tab.badge}</span> : null}
          </button>
        ))}
      </div>

      <div className="inspectorTabBody">
        {activeTab === "overview" && (
          <>
            <CurrentContextPanel preflight={preflight} repository={repository} sandbox={sandbox} agentTurn={agentTurn} skills={skills} isRunning={isRunning} onConfirmPlan={onConfirmPlan} />
            {/* 任务状态机/沙盒 Runtime 默认收起:状态快照只在动作后刷新,
                实时性有限,常驻展示反而误导;需要时点开看。 */}
            <details className="advancedPanels">
              <summary>高级状态（任务状态机 / 沙盒 Runtime）</summary>
              <RuntimePanel snapshot={runtimeSnapshot} isRunning={isRunning} onEditTaskState={onEditTaskState} />
              <SandboxRuntimePanel snapshot={sandboxRuntime} />
            </details>
          </>
        )}

        {activeTab === "plan" && (
          <>
            <ToolPlanPanel
              toolPlan={toolPlan}
              isRunning={isRunning}
              onConfirmAndExecuteToolPlan={onConfirmAndExecuteToolPlan}
              onCreateRepairPlan={onCreateRepairPlan}
              onContinuePlan={onContinuePlan}
              onEditToolPlanStep={onEditToolPlanStep}
              onRewriteToolPlan={onRewriteToolPlan}
              onOpenDiffFile={onOpenDiffFile}
              onOpenCheckpointDiff={onOpenCheckpointDiff}
              onRollbackCheckpoint={onRollbackCheckpoint}
            />
            <ApprovalPanel events={events} approvals={approvals} isRunning={isRunning} onGrant={onGrantToolApproval} onDeny={onDenyToolApproval} />
          </>
        )}

        {activeTab === "code" && (
          <>
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
            <RollbackPanel
              conversationId={conversationId}
              sandboxRuntime={sandboxRuntime}
              isRunning={isRunning}
              onRollbackOriginal={onRollbackOriginal}
            />
          </>
        )}

        {activeTab === "preview" && (
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
        )}

        {activeTab === "delivery" && (
          <>
            <DeliveryPanel
              conversationId={conversationId}
              deliveryReport={deliveryReport}
              deliveryPreview={deliveryPreview}
              isRunning={isRunning}
              onGenerateDeliveryPackage={onGenerateDeliveryPackage}
              onApplyDeliveryToSource={onApplyDeliveryToSource}
            />
            <EvidencePanel toolPlan={toolPlan} checkpoints={checkpoints} />
          </>
        )}

        {activeTab === "memory" && (
          <>
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
          </>
        )}

        {activeTab === "events" && (
          <>
            <SkillsPanel skills={skills} />
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
          </>
        )}
      </div>
    </aside>
  );
}

type TabKey = "overview" | "plan" | "code" | "preview" | "delivery" | "memory" | "events";
