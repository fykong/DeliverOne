import { ConversationView } from "../features/chat/ConversationView";
import { Inspector } from "../features/inspector/Inspector";
import { Sidebar } from "../features/sidebar/Sidebar";
import { Topbar } from "../features/topbar/Topbar";
import { useWorkbench } from "../features/workbench/useWorkbench";

export function App() {
  const workbench = useWorkbench();

  return (
    <div className="shell">
      <Sidebar
        conversations={workbench.conversations}
        activeConversationId={workbench.conversationId}
        localPath={workbench.localPath}
        githubUrl={workbench.githubUrl}
        repository={workbench.repository}
        isRunning={workbench.isRunning}
        onLocalPathChange={workbench.setLocalPath}
        onGithubUrlChange={workbench.setGithubUrl}
        onConnectLocal={() => void workbench.connectLocal()}
        onConnectGithub={() => void workbench.connectGithub()}
        onNewConversation={workbench.resetConversation}
        onSelectConversation={(conversationId) => void workbench.selectConversation(conversationId)}
        onDeleteConversation={(conversationId) => void workbench.removeConversation(conversationId)}
      />

      <main className="conversation">
        <Topbar
          models={workbench.models}
          modelName={workbench.activeModelName}
          phaseLabel={workbench.phaseLabel}
          onModelChange={(modelId) => void workbench.handleModelChange(modelId)}
        />
        <ConversationView
          messages={workbench.messages}
          requirement={workbench.requirement}
          searchIntent={workbench.memory?.searchIntent ?? workbench.preflight?.searchIntent ?? null}
          taskLedger={workbench.memory?.taskLedger ?? null}
          isRunning={workbench.isRunning}
          canSend={Boolean(workbench.sandbox)}
          onRequirementChange={workbench.setRequirement}
          onRunAgent={() => void workbench.handleRunAgent()}
        />
      </main>

      <Inspector
        conversationId={workbench.conversationId}
        preflight={workbench.preflight}
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
        previewCommand={workbench.previewCommand}
        onPreviewCommandChange={workbench.setPreviewCommand}
        onConfirmPlan={() => void workbench.handleConfirmPlan()}
        onConfirmAndExecuteToolPlan={() => void workbench.handleConfirmAndExecuteToolPlan()}
        onCreateRepairPlan={() => void workbench.handleCreateRepairPlan()}
        onEditToolPlanStep={(operation, stepId, options) => void workbench.handleEditToolPlanStep(operation, stepId, options)}
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
        onSaveMCPConfig={(config) => void workbench.handleSaveMCPConfig(config)}
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
        onUpsertManualMemory={(input) => void workbench.handleUpsertManualMemory(input)}
        onGenerateMemoryPatchDraft={() => void workbench.handleGenerateMemoryPatchDraft()}
        onApplyMemoryPatchCandidate={(candidate) => void workbench.handleApplyMemoryPatchCandidate(candidate)}
        onRefreshEvidence={() => void workbench.refreshEvidence()}
        onEditTaskState={(operation, options) => void workbench.handleEditTaskState(operation, options)}
        onOpenSandboxFile={(path) => void workbench.openSandboxFile(path)}
        onOpenDiffFile={(path) => void workbench.openDiffFile(path)}
        onOpenCheckpointDiff={(checkpointId) => void workbench.openCheckpointDiff(checkpointId)}
      />
    </div>
  );
}
