import { ShieldCheck } from "lucide-react";
import type { ToolCallPlan } from "@workbench/shared";
import type { CheckpointManifest } from "../../shared/api";

interface EvidencePanelProps {
  toolPlan: ToolCallPlan | null;
  checkpoints: CheckpointManifest[];
}

export function EvidencePanel({ toolPlan, checkpoints }: EvidencePanelProps) {
  const diffFiles = toolPlan?.evidence.diffFiles ?? [];
  const verificationResults = toolPlan?.evidence.verificationResults ?? [];
  const previewResults = toolPlan?.evidence.previewResults ?? [];

  return (
    <section className="panel">
      <h3>
        <ShieldCheck size={16} />
        证据
      </h3>
      <div className="evidenceGrid">
        <div>
          <strong>{diffFiles.length}</strong>
          <span>变更文件</span>
        </div>
        <div>
          <strong>{checkpoints.length}</strong>
          <span>回退点</span>
        </div>
        <div>
          <strong>{verificationResults.length}</strong>
          <span>验证命令</span>
        </div>
        <div>
          <strong>{previewResults.length}</strong>
          <span>预览证据</span>
        </div>
      </div>
      {diffFiles.length > 0 && (
        <ul className="fileList">
          {diffFiles.map((file) => (
            <li key={file}>{file}</li>
          ))}
        </ul>
      )}
      {verificationResults.map((result) => (
        <div className="verifyRow" key={`${result.stepId}-${result.phase ?? ""}-${result.command ?? ""}-${result.reportPath ?? ""}`}>
          <span>{result.ok ? "通过" : "失败"}</span>
          <code>{result.command ?? "未记录命令"}</code>
          <small>
            {result.source === "verification-report" ? "验证报告" : "工具步骤"}{result.phase ? ` · ${result.phase}` : ""}
            {typeof result.durationMs === "number" ? ` · ${result.durationMs}ms` : ""}
          </small>
          {result.reportPath && <small>报告：{result.reportPath}</small>}
          {!result.ok && result.stderrTail && <small>{result.stderrTail.slice(0, 500)}</small>}
        </div>
      ))}
      {previewResults.map((result) => (
        <div className="verifyRow" key={`preview-${result.stepId}-${result.reportPath ?? result.generatedAt ?? result.url ?? ""}`}>
          <span>{result.ok ? "通过" : "失败"}</span>
          <code>{result.htmlTitle || result.url || "预览 smoke test"}</code>
          <small>{result.source === "preview-smoke-report" ? "预览 smoke 报告" : "工具步骤"}{result.generatedAt ? ` · ${result.generatedAt}` : ""}</small>
          <small>
            DOM {result.runtimeDomBytes ?? 0} bytes · 控制台错误 {result.consoleErrorCount ?? 0} · {result.consoleReliable ? "CDP" : "降级"}
          </small>
          {result.reportPath && <small>报告：{result.reportPath}</small>}
          {result.assertions?.enabled && <small>断言：{result.assertions.summary}</small>}
          {result.screenshotPath && <small>截图：{result.screenshotPath}</small>}
          {result.consoleErrors?.slice(0, 2).map((item, index) => (
            <small key={`${item.message}-${index}`}>{item.message}</small>
          ))}
        </div>
      ))}
    </section>
  );
}
