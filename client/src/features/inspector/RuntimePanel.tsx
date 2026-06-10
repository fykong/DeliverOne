import { Activity, AlertTriangle, CheckCircle2, CircleDot } from "lucide-react";
import type { RuntimeSnapshot } from "@workbench/shared";

interface RuntimePanelProps {
  snapshot: RuntimeSnapshot | null;
  isRunning: boolean;
  onEditTaskState: (
    operation: "annotate_stage" | "pause_stage" | "resume_stage" | "set_next_actions" | "clear_next_actions",
    options?: { stageId?: string; note?: string; actionIds?: string[] }
  ) => void;
}

function statusLabel(status: string) {
  if (status === "done") return "完成";
  if (status === "current") return "当前";
  if (status === "blocked") return "阻断";
  return "待处理";
}

function statusIcon(status: string) {
  if (status === "done") return <CheckCircle2 size={13} />;
  if (status === "blocked") return <AlertTriangle size={13} />;
  return <CircleDot size={13} />;
}

function evidenceText(evidence: Record<string, number>) {
  const entries = Object.entries(evidence).filter(([, value]) => value > 0);
  if (!entries.length) return "暂无证据";
  return entries.map(([key, value]) => `${key} ${value}`).join(" · ");
}

export function RuntimePanel({ snapshot, isRunning, onEditTaskState }: RuntimePanelProps) {
  const activeStage = snapshot?.stages.find((stage) => stage.id === snapshot.activeStage) ?? null;
  const isPaused = Boolean(activeStage?.control?.paused);

  function annotateActiveStage() {
    if (!activeStage) return;
    const note = window.prompt("给当前阶段写一条审查意见：", activeStage.userNote ?? "");
    if (note === null) return;
    onEditTaskState("annotate_stage", { stageId: activeStage.id, note });
  }

  function pauseActiveStage() {
    if (!activeStage) return;
    const note = window.prompt("暂停当前阶段的原因：", activeStage.userNote ?? "等待人工审查。");
    if (note === null) return;
    onEditTaskState("pause_stage", { stageId: activeStage.id, note });
  }

  function resumeActiveStage() {
    if (!activeStage) return;
    onEditTaskState("resume_stage", { stageId: activeStage.id, note: "用户恢复此阶段。" });
  }

  function overrideNextActions() {
    const current = snapshot?.stateMachine?.control?.manualNextActionIds.join(", ") ?? "";
    const value = window.prompt("输入下一步动作 ID，用逗号分隔：", current);
    if (value === null) return;
    const actionIds = value.split(",").map((item) => item.trim()).filter(Boolean);
    if (!actionIds.length) {
      onEditTaskState("clear_next_actions");
      return;
    }
    onEditTaskState("set_next_actions", { actionIds, note: "用户手动覆盖下一步动作。" });
  }

  return (
    <section className="panel runtimePanel">
      <h3>
        <Activity size={16} />
        任务状态机
        {snapshot && <small>{statusLabel(snapshot.stages.find((stage) => stage.id === snapshot.activeStage)?.status ?? "pending")}</small>}
      </h3>
      {!snapshot && <p>接入仓库并发送需求后，这里会显示完整交付链路。</p>}
      {snapshot && (
        <>
          <p>{snapshot.summary}</p>
          <div className="runtimeEvidence">
            <span>工具 {snapshot.evidence.toolResults ?? 0}</span>
            <span>Diff {snapshot.evidence.diffFiles ?? 0}</span>
            <span>检查点 {snapshot.evidence.checkpoints ?? 0}</span>
            <span>验证 {snapshot.evidence.verificationResults ?? 0}</span>
          </div>
          {snapshot.stateMachine && (
            <div className="stateMachineMeta">
              <strong>状态机已持久化</strong>
              <span>{snapshot.stateMachine.stageCount} 个阶段 · {snapshot.stateMachine.transitionCount} 次转移</span>
              {!!snapshot.stateMachine.control?.editCount && (
                <span>
                  人工控制 {snapshot.stateMachine.control.editCount} 次
                  {snapshot.stateMachine.control.pausedStageIds.length ? ` · 暂停 ${snapshot.stateMachine.control.pausedStageIds.join(", ")}` : ""}
                </span>
              )}
              {!!snapshot.stateMachine.control?.manualNextActionIds.length && (
                <span>下一步覆盖：{snapshot.stateMachine.control.manualNextActionIds.join(" / ")}</span>
              )}
              <code>{snapshot.stateMachine.path}</code>
              {activeStage && (
                <div className="stateMachineActions">
                  <button type="button" disabled={isRunning} onClick={annotateActiveStage}>
                    备注
                  </button>
                  {isPaused ? (
                    <button type="button" disabled={isRunning} onClick={resumeActiveStage}>
                      恢复
                    </button>
                  ) : (
                    <button type="button" disabled={isRunning} onClick={pauseActiveStage}>
                      暂停
                    </button>
                  )}
                  <button type="button" disabled={isRunning} onClick={overrideNextActions}>
                    下一步
                  </button>
                </div>
              )}
            </div>
          )}
          <ol className="runtimeStages">
            {snapshot.stages.map((stage) => (
              <li className={stage.status} key={stage.id}>
                <span>{statusIcon(stage.status)}</span>
                <div>
                  <strong>{stage.title}</strong>
                  <small>{stage.owner} · {evidenceText(stage.evidence)}</small>
                  {stage.userNote && <small>备注：{stage.userNote}</small>}
                </div>
                <em>{statusLabel(stage.status)}</em>
              </li>
            ))}
          </ol>
          {snapshot.blockers.length > 0 && <p className="runtimeBlocker">{snapshot.blockers[0]}</p>}
        </>
      )}
    </section>
  );
}
