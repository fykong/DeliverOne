import { AlertTriangle, ArrowDown, ArrowUp, Ban, CheckCircle2, FileCode2, GitCompareArrows, Pencil, Play, RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";
import type { ToolCallPlan, ToolCallPlanStep } from "@workbench/shared";
import { toolPlanStatusLabels } from "./constants";

type ToolStepEditOperation = "skip_step" | "restore_step" | "update_step" | "move_step";

interface ToolPlanPanelProps {
  toolPlan: ToolCallPlan | null;
  isRunning: boolean;
  onConfirmAndExecuteToolPlan: () => void;
  onCreateRepairPlan: () => void;
  onEditToolPlanStep: (
    operation: ToolStepEditOperation,
    stepId: string,
    options?: { reason?: string; title?: string; purpose?: string; input?: Record<string, unknown>; targetOrder?: number }
  ) => void;
  onRewriteToolPlan: (instruction: string) => void;
  onOpenDiffFile: (path: string) => void;
  onOpenCheckpointDiff: (checkpointId: string) => void;
  onRollbackCheckpoint: (checkpointId: string) => void;
}

export function ToolPlanPanel({
  toolPlan,
  isRunning,
  onConfirmAndExecuteToolPlan,
  onCreateRepairPlan,
  onEditToolPlanStep,
  onRewriteToolPlan,
  onOpenDiffFile,
  onOpenCheckpointDiff,
  onRollbackCheckpoint
}: ToolPlanPanelProps) {
  const reviewerAudit = [...(toolPlan?.audits ?? [])].reverse().find((audit) => audit.source === "Reviewer") ?? null;
  const verifierAudit = [...(toolPlan?.audits ?? [])].reverse().find((audit) => audit.source === "Verifier") ?? null;
  const reviewerBlocked = reviewerAudit?.verdict === "blocked";
  const hasFailedStep = Boolean(toolPlan?.status === "failed" || toolPlan?.steps.some((step) => step.status === "failed"));
  const planState = summarizeToolPlanState(toolPlan, verifierAudit?.verdict ?? null);
  const canConfirmAndExecute =
    Boolean(toolPlan) &&
    !reviewerBlocked &&
    (toolPlan?.status === "waiting_confirmation" || toolPlan?.status === "approved" || toolPlan?.status === "waiting_approval");
  const canCreateRepairPlan = Boolean(toolPlan && (toolPlan.status === "failed" || toolPlan.status === "waiting_approval" || toolPlan.steps.some((step) => step.status === "failed")));
  const failedFindings = verifierAudit?.findings.filter((finding) => finding.severity === "error") ?? [];
  const primaryLabel = toolPlan?.status === "waiting_approval" ? "继续执行" : toolPlan?.repairOfPlanId ? "确认修复并执行" : "确认并执行";
  const repairPolicy = toolPlan?.repairPolicy;
  const repairSource = toolPlan?.repairSource;
  const canEditPlan = Boolean(toolPlan && !isRunning && toolPlan.status !== "running" && toolPlan.status !== "completed");
  const latestEdit = toolPlan?.editHistory?.at(-1) ?? null;
  const reviewAfterLatestEdit =
    latestEdit && reviewerAudit ? new Date(reviewerAudit.createdAt).getTime() >= new Date(latestEdit.createdAt).getTime() : false;
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editPurpose, setEditPurpose] = useState("");
  const [editInputText, setEditInputText] = useState("");
  const [editReason, setEditReason] = useState("用户审查后修改工具步骤。");
  const [editError, setEditError] = useState<string | null>(null);
  const [rewriteInstruction, setRewriteInstruction] = useState("");
  const editingStep = toolPlan?.steps.find((step) => step.id === editingStepId) ?? null;

  function openStepEditor(step: ToolCallPlanStep) {
    setEditingStepId(step.id);
    setEditTitle(step.title);
    setEditPurpose(step.purpose);
    setEditInputText(JSON.stringify(step.input, null, 2));
    setEditReason("用户审查后修改工具步骤。");
    setEditError(null);
  }

  function closeStepEditor() {
    setEditingStepId(null);
    setEditError(null);
  }

  function submitStepEditor() {
    if (!editingStep) return;
    try {
      const parsed = JSON.parse(editInputText) as Record<string, unknown>;
      onEditToolPlanStep("update_step", editingStep.id, {
        title: editTitle,
        purpose: editPurpose,
        input: parsed,
        reason: editReason.trim() || "用户审查后修改工具步骤。"
      });
      closeStepEditor();
    } catch (error) {
      setEditError(`参数 JSON 格式不正确：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  function submitRewrite() {
    const cleaned = rewriteInstruction.trim();
    if (!cleaned) return;
    onRewriteToolPlan(cleaned);
    setRewriteInstruction("");
  }

  return (
    <section className="panel">
      <h3>
        <FileCode2 size={16} />
        工具计划
        {toolPlan && <small>{toolPlanStatusLabels[toolPlan.status]}</small>}
      </h3>
      {toolPlan && (
        <div className={`planStateSummary ${planState.kind}`}>
          <strong>{planState.title}</strong>
          <span>{planState.detail}</span>
        </div>
      )}
      {toolPlan?.repairOfPlanId && (
        <div className="repairMeta">
          <strong>修复计划 #{toolPlan.repairSequence ?? 1}</strong>
          <span>来源计划：{toolPlan.repairOfPlanId}</span>
          <span>失败类型：{repairSource?.failureClass ?? repairPolicy?.failureClass ?? "unknown"}</span>
          <span>代码修复：{toolPlan.repairAttempt ?? 0}/{repairPolicy?.maxCodeRepairAttempts ?? 3}</span>
          {repairSource?.verifierSummary && <span>Verifier：{repairSource.verifierSummary}</span>}
          {repairSource?.summary && <p>{repairSource.summary}</p>}
          {repairSource?.failedSteps?.length ? (
            <div className="repairSourceSteps">
              {repairSource.failedSteps.map((step) => (
                <span key={step.id ?? `${step.order}-${step.title}`}>
                  {String(step.order ?? "?").padStart(2, "0")} {step.title ?? step.toolId}：{step.summary || "失败步骤"}
                </span>
              ))}
            </div>
          ) : null}
          <span>状态：等待用户审查确认后才会执行写入。</span>
        </div>
      )}
      {(reviewerAudit || verifierAudit) && (
        <div className={`auditSummary ${reviewerBlocked || failedFindings.length || hasFailedStep ? "blocked" : ""}`}>
          <AlertTriangle size={14} />
          <div>
            {reviewerAudit && <strong>Reviewer：{reviewerAudit.summary || reviewerAudit.verdict}</strong>}
            {verifierAudit && <strong>Verifier：{hasFailedStep ? "未通过，需要修复" : verifierAudit.summary || verifierAudit.verdict}</strong>}
            {verifierAudit && hasFailedStep && verifierAudit.summary && <p>{verifierAudit.summary}</p>}
            {failedFindings.length > 0 && <p>{failedFindings.map((finding) => finding.detail).join("；")}</p>}
            {reviewerBlocked && <p>Reviewer 已阻断该计划，需要重新生成或调整后再确认。</p>}
          </div>
        </div>
      )}
      {latestEdit && (
        <div className={`editReviewSummary ${reviewAfterLatestEdit && !reviewerBlocked ? "passed" : reviewerBlocked ? "blocked" : ""}`}>
          <Pencil size={14} />
          <div>
            <strong>最近编辑：{editOperationLabel(latestEdit.operation)}</strong>
            <p>{latestEdit.reason || "用户调整了工具计划，系统会重新审查后再允许确认。"}</p>
            <small>{reviewAfterLatestEdit ? `已重审：${reviewerAudit?.verdict}` : "等待 Reviewer 重审结果"}</small>
          </div>
        </div>
      )}
      {toolPlan?.generation?.summary && <p>{toolPlan.generation.summary}</p>}
      {canEditPlan && (
        <div className="planRewriteBox">
          <label>
            <span>用一句话调整计划</span>
            <textarea
              value={rewriteInstruction}
              onChange={(event) => setRewriteInstruction(event.target.value)}
              placeholder="例如：删掉预览步骤，只保留读取文件、diff 检查和 npm run test；或把验证命令改成 npm run build。"
            />
          </label>
          <button type="button" disabled={isRunning || !rewriteInstruction.trim()} onClick={submitRewrite}>
            <RefreshCw size={14} />
            重写计划
          </button>
        </div>
      )}
      <div className="toolPlanList">
        {toolPlan?.steps.map((step) => (
          <div className={`toolStep ${step.status}`} key={step.id}>
            <div>
              <span>{String(step.order).padStart(2, "0")}</span>
              <strong>{step.title}</strong>
              <small>{step.toolId}</small>
            </div>
            <p>{step.summary || step.purpose}</p>
            {step.disabledReason && <p className="stepDisabledReason">{step.disabledReason}</p>}
            <em>{step.status}</em>
            <div className="stepEvidenceActions">
              {canEditPlan && step.status !== "running" && step.status !== "completed" && (
                <>
                  <button type="button" disabled={step.order <= 1} onClick={() => onEditToolPlanStep("move_step", step.id, { targetOrder: step.order - 1, reason: "用户上移工具步骤。" })}>
                    <ArrowUp size={13} />
                    上移
                  </button>
                  <button
                    type="button"
                    disabled={!toolPlan || step.order >= toolPlan.steps.length}
                    onClick={() => onEditToolPlanStep("move_step", step.id, { targetOrder: step.order + 1, reason: "用户下移工具步骤。" })}
                  >
                    <ArrowDown size={13} />
                    下移
                  </button>
                  <button type="button" onClick={() => openStepEditor(step)}>
                    <Pencil size={13} />
                    编辑
                  </button>
                  {step.status === "skipped" ? (
                    <button type="button" onClick={() => onEditToolPlanStep("restore_step", step.id, { reason: "用户恢复工具步骤。" })}>
                      <RotateCcw size={13} />
                      恢复
                    </button>
                  ) : (
                    <button type="button" onClick={() => onEditToolPlanStep("skip_step", step.id, { reason: "用户审查后禁用该工具步骤。" })}>
                      <Ban size={13} />
                      禁用
                    </button>
                  )}
                </>
              )}
              {step.diffFiles?.[0] && (
                <button type="button" onClick={() => onOpenDiffFile(step.diffFiles![0])}>
                  <GitCompareArrows size={13} />
                  Diff
                </button>
              )}
              {step.checkpointId && (
                <button type="button" onClick={() => onOpenCheckpointDiff(step.checkpointId!)}>
                  检查点
                </button>
              )}
              {step.checkpointId && (
                <button type="button" disabled={isRunning} onClick={() => onRollbackCheckpoint(step.checkpointId!)}>
                  <RotateCcw size={13} />
                  回退
                </button>
              )}
            </div>
          </div>
        ))}
        {!toolPlan && <p>Agent 方案确认后，这里会出现即将调用的真实工具。</p>}
      </div>
      {toolPlan && (
        <div className="buttonRow">
          <button type="button" disabled={isRunning || !canConfirmAndExecute} onClick={onConfirmAndExecuteToolPlan}>
            {toolPlan.status === "waiting_confirmation" ? <CheckCircle2 size={16} /> : <Play size={16} />}
            {primaryLabel}
          </button>
        </div>
      )}
      {toolPlan && canCreateRepairPlan && (
        <button className="inspectorButton secondary" type="button" disabled={isRunning} onClick={onCreateRepairPlan}>
          <RefreshCw size={16} />
          生成修复计划
        </button>
      )}
      {editingStep && (
        <div className="modalBackdrop" role="presentation">
          <div className="reviewModal toolStepEditor" role="dialog" aria-modal="true" aria-label="编辑工具步骤">
            <header>
              <div>
                <span>编辑工具步骤</span>
                <strong>{editingStep.toolId}</strong>
              </div>
              <button className="iconButton" type="button" onClick={closeStepEditor} title="关闭">
                ×
              </button>
            </header>
            <div className="modalMeta">
              <span>步骤</span>
              <code>{editingStep.order}</code>
              <span>风险</span>
              <code>{editingStep.riskLevel}</code>
            </div>
            <label className="modalField">
              <span>标题</span>
              <input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} />
            </label>
            <label className="modalField">
              <span>目的</span>
              <textarea value={editPurpose} onChange={(event) => setEditPurpose(event.target.value)} />
            </label>
            <label className="modalField">
              <span>输入参数 JSON</span>
              <textarea className="codeTextarea" value={editInputText} onChange={(event) => setEditInputText(event.target.value)} spellCheck={false} />
            </label>
            <label className="modalField">
              <span>修改原因</span>
              <textarea value={editReason} onChange={(event) => setEditReason(event.target.value)} />
            </label>
            {editError && <p className="formError">{editError}</p>}
            <footer>
              <button type="button" onClick={submitStepEditor} disabled={isRunning}>
                保存并重审
              </button>
              <button type="button" onClick={closeStepEditor}>
                取消
              </button>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
}

function editOperationLabel(operation: string) {
  const labels: Record<string, string> = {
    skip_step: "禁用步骤",
    restore_step: "恢复步骤",
    update_step: "修改参数",
    move_step: "调整顺序",
    rewrite_plan: "模型重写"
  };
  return labels[operation] ?? operation;
}

function summarizeToolPlanState(toolPlan: ToolCallPlan | null, verifierVerdict: string | null) {
  if (!toolPlan) {
    return { kind: "idle", title: "等待工具计划", detail: "Agent 方案确认后，这里会出现可审查的工具步骤。" };
  }
  const failedCount = toolPlan.steps.filter((step) => step.status === "failed").length;
  if (toolPlan.repairOfPlanId) {
    return {
      kind: "repair",
      title: `修复计划等待确认`,
      detail: `来源计划未通过，当前是第 ${toolPlan.repairSequence ?? 1} 轮修复；确认前不会执行写入或命令。`
    };
  }
  if (toolPlan.status === "failed" || failedCount > 0) {
    return {
      kind: "failed",
      title: "执行未通过",
      detail: `Verifier ${verifierVerdict === "pass" ? "仍需复核" : "已给出失败判断"}；${failedCount} 个步骤失败，可生成修复计划。`
    };
  }
  if (toolPlan.status === "waiting_approval") {
    return { kind: "blocked", title: "等待授权", detail: "有高风险命令或外部工具需要授权，授权后才能继续执行。" };
  }
  if (toolPlan.status === "completed") {
    return { kind: "passed", title: "执行完成", detail: "工具计划已完成，继续检查验证、diff、交付包和回退点。" };
  }
  if (toolPlan.status === "waiting_confirmation") {
    return { kind: "review", title: "等待审查确认", detail: "请先审查步骤、命令、diff/checkpoint 策略，再确认执行。" };
  }
  if (toolPlan.status === "approved") {
    return { kind: "review", title: "已确认，待执行", detail: "用户已确认计划，可以开始在当前沙盒中执行。" };
  }
  return { kind: "running", title: "执行中", detail: "Agent 正在按工具计划运行，右侧证据会持续更新。" };
}
