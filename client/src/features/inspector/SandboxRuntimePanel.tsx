import { Box, CheckCircle2, CircleDot, TriangleAlert } from "lucide-react";
import type { SandboxRuntimeSnapshot } from "@workbench/shared";

interface SandboxRuntimePanelProps {
  snapshot: SandboxRuntimeSnapshot | null;
}

function statusText(status: string) {
  if (status === "done") return "完成";
  if (status === "current" || status === "running") return "运行中";
  if (status === "blocked" || status === "fail") return "阻断";
  if (status === "pass") return "通过";
  return "待处理";
}

function confidenceText(value?: number) {
  if (typeof value !== "number") return "";
  return `${Math.round(value * 100)}%`;
}

function statusIcon(status: string) {
  if (status === "done" || status === "pass") return <CheckCircle2 size={13} />;
  if (status === "blocked" || status === "fail") return <TriangleAlert size={13} />;
  return <CircleDot size={13} />;
}

function evidenceText(evidence: Record<string, number>) {
  const items = Object.entries(evidence).filter(([, value]) => value > 0);
  if (!items.length) return "暂无证据";
  return items.map(([key, value]) => `${key} ${value}`).join(" · ");
}

export function SandboxRuntimePanel({ snapshot }: SandboxRuntimePanelProps) {
  return (
    <section className="panel sandboxRuntimePanel">
      <h3>
        <Box size={16} />
        沙盒 Runtime
        {snapshot && <small>{statusText(snapshot.status)}</small>}
      </h3>
      {!snapshot && <p>接入仓库后，这里会显示当前对话沙盒的运行生命周期。</p>}
      {snapshot && (
        <>
          <div className="sandboxRuntimeSummary">
            <span>进程 {snapshot.processes.running}/{snapshot.processes.total}</span>
            <span>文件 {snapshot.files.textFiles}</span>
            <span>变更 {snapshot.files.changedFiles}</span>
            <span>检查点 {snapshot.checkpoints.count}</span>
          </div>
          <div className="sandboxRuntimeFacts">
            <span>{snapshot.preview.summary}</span>
            <span>{snapshot.verification.summary}</span>
            {snapshot.commandRecommendations?.verification.primary && (
              <span>
                推荐验证：<code>{snapshot.commandRecommendations.verification.primary.command}</code>
                {` · ${confidenceText(snapshot.commandRecommendations.verification.primary.confidence)}`}
              </span>
            )}
            {snapshot.commandRecommendations?.preview.primary && (
              <span>
                推荐预览：<code>{snapshot.commandRecommendations.preview.primary.command}</code>
                {` · ${confidenceText(snapshot.commandRecommendations.preview.primary.confidence)}`}
              </span>
            )}
            {snapshot.rollback.report && (
              <span>
                最近回退：{snapshot.rollback.report.beforeFileCount ?? 0} → {snapshot.rollback.report.afterFileCount ?? 0} 个变更
              </span>
            )}
            {snapshot.delivery.reportPath && <span>{snapshot.delivery.reportPath}</span>}
          </div>
          {(snapshot.commandRecommendations?.verification.primary || snapshot.commandRecommendations?.preview.primary) && (
            <div className="commandRecommendationList">
              {snapshot.commandRecommendations.verification.all.slice(0, 4).map((item) => (
                <span key={`verification-${item.phase}`}>
                  验证 {item.phase}：<code>{item.command}</code>
                </span>
              ))}
              {snapshot.commandRecommendations.preview.all.slice(0, 3).map((item) => (
                <span key={`preview-${item.phase}`}>
                  预览 {item.phase}：<code>{item.command}</code>
                </span>
              ))}
            </div>
          )}
          <ol className="sandboxLifecycle">
            {snapshot.lifecycle.map((stage) => (
              <li className={stage.status} key={stage.id}>
                <span>{statusIcon(stage.status)}</span>
                <div>
                  <strong>{stage.title}</strong>
                  <small>{evidenceText(stage.evidence)}</small>
                </div>
                <em>{statusText(stage.status)}</em>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
