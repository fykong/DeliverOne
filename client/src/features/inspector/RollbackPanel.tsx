import { FileText, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import type { CheckpointManifest } from "../../shared/api";
import { getRollbackReport, getRollbackReports } from "../../shared/api";
import type { SandboxRuntimeSnapshot } from "@workbench/shared";
import type { RollbackDiffSnapshot, RollbackReportDetail, RollbackReportSummary } from "@workbench/shared";
import { RollbackConfirmationView } from "./RollbackConfirmationView";
import { UnifiedDiffViewer } from "./UnifiedDiffViewer";

interface RollbackPanelProps {
  conversationId: string;
  checkpoints: CheckpointManifest[];
  sandboxRuntime: SandboxRuntimeSnapshot | null;
  isRunning: boolean;
  onRollbackCheckpoint: (checkpointId: string) => void;
  onRollbackOriginal: () => void;
}

export function RollbackPanel({ conversationId, checkpoints, sandboxRuntime, isRunning, onRollbackCheckpoint, onRollbackOriginal }: RollbackPanelProps) {
  const report = sandboxRuntime?.rollback.report ?? null;
  const [reports, setReports] = useState<RollbackReportSummary[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedReport, setSelectedReport] = useState<RollbackReportDetail | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const latestReportId = report?.id ?? null;

  useEffect(() => {
    let cancelled = false;
    setReportError(null);
    getRollbackReports(conversationId)
      .then((items) => {
        if (cancelled) return;
        setReports(items);
        const nextId = latestReportId || selectedReportId || items[0]?.id || null;
        setSelectedReportId(nextId);
      })
      .catch((error) => {
        if (cancelled) return;
        setReports([]);
        setReportError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, latestReportId]);

  useEffect(() => {
    let cancelled = false;
    setSelectedReport(null);
    if (!selectedReportId) return () => {
      cancelled = true;
    };
    getRollbackReport(conversationId, selectedReportId)
      .then((item) => {
        if (!cancelled) setSelectedReport(item);
      })
      .catch((error) => {
        if (!cancelled) setReportError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, selectedReportId]);

  return (
    <section className="panel">
      <h3>
        <RotateCcw size={16} />
        回退
      </h3>
      <div className="checkpointList">
        {checkpoints.slice(0, 4).map((checkpoint) => (
          <div className="checkpointRow" key={checkpoint.id}>
            <div>
              <strong>{checkpoint.label}</strong>
              <span>{checkpoint.files.length} 个文件</span>
            </div>
            <button
              type="button"
              disabled={isRunning}
              onClick={() => {
                if (window.confirm(`确认回退到检查点「${checkpoint.label}」？这会把沙盒文件还原到该检查点时的状态，无法直接撤销。`)) {
                  onRollbackCheckpoint(checkpoint.id);
                }
              }}
            >
              回退
            </button>
          </div>
        ))}
        {checkpoints.length === 0 && <p>还没有 checkpoint。首次写代码前会自动创建。</p>}
      </div>
      {report && (
        <div className="rollbackEvidence">
          <strong>最近回退证据</strong>
          <span>{report.summary ?? "已记录回退操作。"}</span>
          <div>
            <small>回退前 {report.beforeFileCount ?? 0} 个变更</small>
            <small>回退后 {report.afterFileCount ?? 0} 个变更</small>
          </div>
          {report.confirmation && <RollbackConfirmationView confirmation={report.confirmation} compact />}
          {report.affectedFiles?.length ? <em>{report.affectedFiles.slice(0, 3).join(" / ")}</em> : null}
          {report.reportPath && <code>{report.reportPath}</code>}
        </div>
      )}
      <div className="rollbackReportViewer">
        <div className="rollbackReportHeader">
          <strong>
            <FileText size={14} />
            回退报告
          </strong>
          <span>{reports.length ? `${reports.length} 条` : "暂无"}</span>
        </div>
        {reportError && <p className="panelWarning">{reportError}</p>}
        {reports.length > 0 ? (
          <div className="rollbackReportList">
            {reports.slice(0, 6).map((item) => (
              <button
                className={item.id === selectedReportId ? "active" : ""}
                type="button"
                key={item.id ?? item.reportPath}
                onClick={() => item.id && setSelectedReportId(item.id)}
              >
                <span>{operationLabel(item.operation)}</span>
                <small>
                  {item.beforeFileCount ?? 0}
                  {" -> "}
                  {item.afterFileCount ?? 0} 个变更
                </small>
              </button>
            ))}
          </div>
        ) : (
          <p>还没有可展开的回退报告。</p>
        )}
        {selectedReport && (
          <div className="rollbackReportDetail">
            <strong>{selectedReport.summary || "回退报告详情"}</strong>
            <span>{selectedReport.createdAt ?? "未知时间"}</span>
            {selectedReport.confirmation && <RollbackConfirmationView confirmation={selectedReport.confirmation} />}
            {selectedReport.affectedFiles?.length ? <em>影响文件：{selectedReport.affectedFiles.join(" / ")}</em> : null}
            {selectedReport.reportPath && <code>{selectedReport.reportPath}</code>}
            <details open>
              <summary>回退前 diff / status</summary>
              <RollbackSnapshotView snapshot={selectedReport.before} rightLabel="回退前" />
            </details>
            <details>
              <summary>回退后 diff / status</summary>
              <RollbackSnapshotView snapshot={selectedReport.after} rightLabel="回退后" />
            </details>
          </div>
        )}
      </div>
      <button className="dangerButton" type="button" disabled={isRunning} onClick={onRollbackOriginal}>
        一键回到沙盒原始 HEAD
      </button>
    </section>
  );
}

function operationLabel(operation?: string) {
  if (operation === "checkpoint") return "检查点回退";
  if (operation === "checkpoint_file") return "文件回退";
  if (operation === "checkpoint_hunk") return "变更块回退";
  if (operation === "original") return "一键回退";
  return operation || "回退";
}

function RollbackSnapshotView({ snapshot, rightLabel }: { snapshot?: RollbackDiffSnapshot; rightLabel: string }) {
  if (!snapshot) {
    return <p>暂无快照。</p>;
  }
  const fallback = snapshot.statusShort || "无变更。";
  return (
    <div className="rollbackSnapshot">
      <div className="rollbackSnapshotMeta">
        <span>变更文件：{snapshot.fileCount}</span>
        <span>{snapshot.capturedAt}</span>
      </div>
      <UnifiedDiffViewer diff={snapshot.diff} emptyText="暂无 diff。" fallbackText={fallback} leftLabel="原始 HEAD" rightLabel={rightLabel} />
    </div>
  );
}
