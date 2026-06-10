import { useCallback, useEffect, useRef, useState } from "react";
import { ConversationView } from "../features/chat/ConversationView";
import { Inspector } from "../features/inspector/Inspector";
import { RepoConnectModal } from "../features/sidebar/RepoConnectModal";
import { Sidebar } from "../features/sidebar/Sidebar";
import { Topbar } from "../features/topbar/Topbar";
import { useWorkbench } from "../features/workbench/useWorkbench";
import { ErrorBoundary } from "../shared/ErrorBoundary";

const INSPECTOR_MIN = 300;
const INSPECTOR_MAX = 640;

function readStoredNumber(key: string, fallback: number) {
  const raw = window.localStorage.getItem(key);
  const value = raw ? Number(raw) : NaN;
  return Number.isFinite(value) ? Math.min(INSPECTOR_MAX, Math.max(INSPECTOR_MIN, value)) : fallback;
}

export function App() {
  const workbench = useWorkbench();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem("sidebarCollapsed") === "1");
  const [inspectorWidth, setInspectorWidth] = useState(() => readStoredNumber("inspectorWidth", 340));
  const [showRepoModal, setShowRepoModal] = useState(false);
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);

  // updater 必须保持纯函数:StrictMode 会双调用 updater,
  // 带副作用的 toggle 会被双重应用变成无操作。持久化放 useEffect。
  function toggleSidebar() {
    setSidebarCollapsed((value) => !value);
  }

  useEffect(() => {
    window.localStorage.setItem("sidebarCollapsed", sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  useEffect(() => {
    window.localStorage.setItem("inspectorWidth", String(inspectorWidth));
  }, [inspectorWidth]);

  function handleNewConversation() {
    workbench.resetConversation();
    // 接入仓库是开发交付的第一步,新对话直接给选择;提问的用户可以关掉。
    setShowRepoModal(true);
  }

  const onDragMove = useCallback((event: MouseEvent) => {
    if (!dragState.current) return;
    const delta = dragState.current.startX - event.clientX;
    const next = Math.min(INSPECTOR_MAX, Math.max(INSPECTOR_MIN, dragState.current.startWidth + delta));
    setInspectorWidth(next);
  }, []);

  const onDragEnd = useCallback(() => {
    dragState.current = null;
    window.removeEventListener("mousemove", onDragMove);
    window.removeEventListener("mouseup", onDragEnd);
    document.body.classList.remove("isResizing");
  }, [onDragMove]);

  function startInspectorDrag(event: React.MouseEvent) {
    event.preventDefault();
    dragState.current = { startX: event.clientX, startWidth: inspectorWidth };
    window.addEventListener("mousemove", onDragMove);
    window.addEventListener("mouseup", onDragEnd);
    document.body.classList.add("isResizing");
  }

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", onDragMove);
      window.removeEventListener("mouseup", onDragEnd);
    };
  }, [onDragMove, onDragEnd]);

  return (
    <div
      className="shell"
      style={{ gridTemplateColumns: `${sidebarCollapsed ? "52px" : "232px"} minmax(420px, 1fr) ${inspectorWidth}px` }}
    >
      <Sidebar
        conversations={workbench.conversations}
        activeConversationId={workbench.conversationId}
        isRunning={workbench.isRunning}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={toggleSidebar}
        onNewConversation={handleNewConversation}
        onSelectConversation={(conversationId) => void workbench.selectConversation(conversationId)}
        onDeleteConversation={(conversationId) => void workbench.removeConversation(conversationId)}
        onCleanup={() => void workbench.cleanupConversations()}
      />

      <main className="conversation">
        <Topbar
          models={workbench.models}
          modelName={workbench.activeModelName}
          phaseLabel={workbench.phaseLabel}
          onModelChange={(modelId) => void workbench.handleModelChange(modelId)}
        />
        <ErrorBoundary label="对话区">
        <ConversationView
          messages={workbench.messages}
          requirement={workbench.requirement}
          searchIntent={workbench.memory?.searchIntent ?? workbench.preflight?.searchIntent ?? null}
          taskLedger={workbench.memory?.taskLedger ?? null}
          isRunning={workbench.isRunning}
          executionStatus={workbench.executionStatus}
          repository={workbench.repository}
          sandbox={workbench.sandbox}
          autopilotEnabled={workbench.autopilotEnabled}
          onAutopilotChange={workbench.setAutopilotEnabled}
          onRequirementChange={workbench.setRequirement}
          onRunAgent={() => void workbench.handleRunAgent()}
          onOpenRepoModal={() => setShowRepoModal(true)}
        />
        </ErrorBoundary>
      </main>

      <div className="inspectorWrap">
        <div
          className="inspectorResizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整面板宽度"
          title="拖拽调整面板宽度"
          onMouseDown={startInspectorDrag}
        />
        <ErrorBoundary label="证据面板">
        <Inspector
          conversationId={workbench.conversationId}
          preflight={workbench.preflight}
          repository={workbench.repository}
          sandbox={workbench.sandbox}
          agentTurn={workbench.agentTurn}
          toolPlan={workbench.toolPlan}
          checkpoints={workbench.checkpoints}
          processes={workbench.processes}
          events={workbench.events}
          mcpConfig={workbench.mcpConfig}
          mcpConfigValidation={workbench.mcpConfigValidation}
          mcpServers={workbench.mcpServers}
          mcpTools={workbench.mcpTools}
          mcpHistory={workbench.mcpHistory}
          approvals={workbench.approvals}
          metrics={workbench.metrics}
          runtimeSnapshot={workbench.runtimeSnapshot}
          sandboxRuntime={workbench.sandboxRuntime}
          memory={workbench.memory}
          memoryPatchDraft={workbench.memoryPatchDraft}
          deliveryReport={workbench.deliveryReport}
          deliveryPreview={workbench.deliveryPreview}
          previewSmokeReport={workbench.previewSmokeReport}
          sandboxFiles={workbench.sandboxFiles}
          selectedFile={workbench.selectedFile}
          selectedFilePath={workbench.selectedFilePath}
          currentDiff={workbench.currentDiff}
          selectedDiff={workbench.selectedDiff}
          checkpointDiff={workbench.checkpointDiff}
          selectedCheckpointId={workbench.selectedCheckpointId}
          skills={workbench.skills}
          isRunning={workbench.isRunning}
          isExecutingToolPlan={workbench.isExecutingToolPlan}
          previewCommand={workbench.previewCommand}
          onPreviewCommandChange={workbench.setPreviewCommand}
          onConfirmPlan={() => void workbench.handleConfirmPlan()}
          onConfirmAndExecuteToolPlan={() => void workbench.handleConfirmAndExecuteToolPlan()}
          onCreateRepairPlan={() => void workbench.handleCreateRepairPlan()}
          onContinuePlan={() => void workbench.handleContinuePlan()}
          onEditToolPlanStep={(operation, stepId, options) => workbench.handleEditToolPlanStep(operation, stepId, options)}
          onRewriteToolPlan={(instruction) => void workbench.handleRewriteToolPlan(instruction)}
          onRollbackCheckpoint={(checkpointId) => void workbench.handleRollbackCheckpoint(checkpointId)}
          onRollbackCheckpointFile={(checkpointId, relativePath) => void workbench.handleRollbackCheckpointFile(checkpointId, relativePath)}
          onRollbackCheckpointHunk={(checkpointId, relativePath, hunkIndex) =>
            void workbench.handleRollbackCheckpointHunk(checkpointId, relativePath, hunkIndex)
          }
          onRollbackOriginal={() => void workbench.handleRollbackOriginal()}
          onStartPreview={() => void workbench.handleStartPreview()}
          onStopPreview={(processId) => void workbench.handleStopPreview(processId)}
          onRunPreviewSmokeTest={(port) => void workbench.handleRunPreviewSmokeTest(port)}
          onGenerateDeliveryPackage={() => void workbench.handleGenerateDeliveryPackage()}
          onApplyDeliveryToSource={() => void workbench.handleApplyDeliveryToSource()}
          onDiscoverMCPTools={() => void workbench.handleDiscoverMCPTools()}
          onSaveMCPConfig={(config) => workbench.handleSaveMCPConfig(config)}
          onValidateMCPConfig={(config) => void workbench.handleValidateMCPConfig(config)}
          onReplayMCPHistory={(historyEntryId) => void workbench.handleReplayMCPHistory(historyEntryId)}
          onGrantToolApproval={(toolId, scope, riskLevel, command, requestEventId) =>
            void workbench.handleGrantToolApproval(toolId, scope, riskLevel, command, requestEventId)
          }
          onDenyToolApproval={(toolId, riskLevel, reason, requestEventId, command) =>
            void workbench.handleDenyToolApproval(toolId, riskLevel, reason, requestEventId, command)
          }
          onRevokeApproval={(grantId) => void workbench.handleRevokeApproval(grantId)}
          onPinMemory={(itemId, pinned) => void workbench.handlePinMemory(itemId, pinned)}
          onForgetMemory={(itemId) => void workbench.handleForgetMemory(itemId)}
          onUpsertManualMemory={(input) => workbench.handleUpsertManualMemory(input)}
          onGenerateMemoryPatchDraft={() => void workbench.handleGenerateMemoryPatchDraft()}
          onApplyMemoryPatchCandidate={(candidate) => void workbench.handleApplyMemoryPatchCandidate(candidate)}
          onRefreshEvidence={() => void workbench.refreshEvidence()}
          onEditTaskState={(operation, options) => void workbench.handleEditTaskState(operation, options)}
          onOpenSandboxFile={(path) => void workbench.openSandboxFile(path)}
          onOpenDiffFile={(path) => void workbench.openDiffFile(path)}
          onOpenCheckpointDiff={(checkpointId) => void workbench.openCheckpointDiff(checkpointId)}
        />
        </ErrorBoundary>
      </div>

      <RepoConnectModal
        open={showRepoModal}
        localPath={workbench.localPath}
        githubUrl={workbench.githubUrl}
        repository={workbench.repository}
        sandbox={workbench.sandbox}
        isRunning={workbench.isRunning}
        onLocalPathChange={workbench.setLocalPath}
        onGithubUrlChange={workbench.setGithubUrl}
        onConnectLocal={() => {
          void workbench.connectLocal().then((ok) => {
            if (ok) setShowRepoModal(false);
          });
        }}
        onConnectGithub={() => {
          void workbench.connectGithub().then((ok) => {
            if (ok) setShowRepoModal(false);
          });
        }}
        onClose={() => setShowRepoModal(false)}
      />
    </div>
  );
}
