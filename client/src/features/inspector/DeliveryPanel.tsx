import { Archive, GitPullRequest, Image as ImageIcon, PackageCheck } from "lucide-react";
import type { DeliveryPreview, DeliveryReport } from "@workbench/shared";
import { getPreviewScreenshotUrl } from "../../shared/api";
import { MarkdownPreview } from "./MarkdownPreview";
import { RollbackConfirmationView } from "./RollbackConfirmationView";
import { UnifiedDiffViewer } from "./UnifiedDiffViewer";

interface DeliveryPanelProps {
  conversationId: string;
  deliveryReport: DeliveryReport | null;
  deliveryPreview: DeliveryPreview | null;
  isRunning: boolean;
  onGenerateDeliveryPackage: () => void;
  onApplyDeliveryToSource: () => void;
}

export function DeliveryPanel({ conversationId, deliveryReport, deliveryPreview, isRunning, onGenerateDeliveryPackage, onApplyDeliveryToSource }: DeliveryPanelProps) {
  const markdown = deliveryPreview?.markdown;
  const patch = deliveryPreview?.patch;
  return (
    <section className="panel">
      <h3>
        <PackageCheck size={16} />
        交付包
        <small>{deliveryReport ? deliveryReport.statusShort : "未生成"}</small>
      </h3>

      <div className="buttonRow">
        <button type="button" disabled={isRunning} onClick={onGenerateDeliveryPackage}>
          <Archive size={16} />
          生成交付包
        </button>
        <button type="button" disabled={isRunning || !deliveryReport} onClick={onApplyDeliveryToSource}>
          <GitPullRequest size={16} />
          应用到原仓库
        </button>
      </div>

      {deliveryReport ? (
        <div className="deliverySummary">
          <div>
            <strong>{deliveryReport.changedFiles.length}</strong>
            <span>变更文件</span>
          </div>
          <div>
            <strong>{deliveryReport.checkpointCount}</strong>
            <span>回退点</span>
          </div>
          <div>
            <strong>{deliveryReport.verificationGate.status}</strong>
            <span>验证门禁</span>
          </div>
          <div>
            <strong>{deliveryReport.previewGate?.status ?? "missing"}</strong>
            <span>预览门禁</span>
          </div>
          <div>
            <strong>{deliveryReport.rollbackGate?.status ?? "missing"}</strong>
            <span>回退门禁</span>
          </div>
          <p>{deliveryReport.verificationGate.summary}</p>
          {deliveryReport.previewGate && <p>{deliveryReport.previewGate.summary}</p>}
          {deliveryReport.rollbackGate && <p>{deliveryReport.rollbackGate.summary}</p>}
          {deliveryReport.rollbackGate?.latest && (
            <p>
              最近回退：{deliveryReport.rollbackGate.latest.beforeFileCount ?? 0}
              {" -> "}
              {deliveryReport.rollbackGate.latest.afterFileCount ?? 0} 个变更
              {deliveryReport.rollbackGate.latest.reportPath ? `；报告：${deliveryReport.rollbackGate.latest.reportPath}` : ""}
            </p>
          )}
          {deliveryReport.rollbackGate?.latest?.confirmation && <RollbackConfirmationView confirmation={deliveryReport.rollbackGate.latest.confirmation} />}
          {deliveryReport.previewGate?.screenshotPath && <p>截图：{deliveryReport.previewGate.screenshotPath}</p>}
          {deliveryReport.previewGate && (
            <p>
              运行后 DOM：{deliveryReport.previewGate.runtimeDomOk ? "已读取" : "缺失"} · {deliveryReport.previewGate.runtimeDomBytes ?? 0} bytes ·
              控制台错误 {deliveryReport.previewGate.consoleErrorCount ?? 0} · {deliveryReport.previewGate.consoleReliable ? "CDP" : "降级"}
            </p>
          )}
          {deliveryReport.previewGate?.consoleErrors?.length ? (
            <div className="consoleSummary fail">
              {deliveryReport.previewGate.consoleErrors.slice(0, 3).map((item, index) => (
                <code key={`${item.message}-${index}`}>{item.message}</code>
              ))}
            </div>
          ) : null}
          {deliveryReport.previewGate?.assertions?.enabled ? (
            <div className={`assertionSummary ${deliveryReport.previewGate.assertions.ok ? "pass" : "fail"}`}>
              <span>{deliveryReport.previewGate.assertions.summary}</span>
              {[...deliveryReport.previewGate.assertions.textResults, ...deliveryReport.previewGate.assertions.selectorResults]
                .filter((item) => !item.ok)
                .slice(0, 4)
                .map((item, index) => (
                  <code key={`${"text" in item ? item.text : item.selector}-${index}`}>
                    {"text" in item ? item.text : item.selector}：{item.detail}
                  </code>
                ))}
            </div>
          ) : null}
          {deliveryReport.previewGate?.quality?.checks?.length ? (
            <div className="qualityList">
              {deliveryReport.previewGate.quality.checks.map((check) => (
                <span className={check.ok ? "pass" : "fail"} key={check.id}>
                  {check.title}：{check.ok ? "通过" : check.detail}
                </span>
              ))}
            </div>
          ) : null}
          {deliveryReport.previewGate?.screenshotPath && (
            <figure className="screenshotPreview">
              <img src={getPreviewScreenshotUrl(conversationId, deliveryReport.previewGate.generatedAt)} alt="交付预览截图" />
              <figcaption>
                <ImageIcon size={13} />
                {deliveryReport.previewGate.htmlTitle || "预览截图"} · {deliveryReport.previewGate.htmlBytes} bytes HTML
              </figcaption>
            </figure>
          )}
          <code>{deliveryReport.diffStat || "暂无 diff 统计"}</code>
          <p>{deliveryReport.artifacts.markdownPath}</p>
          {(markdown || patch) && (
            <div className="deliveryPreview">
              {markdown && (
                <details open>
                  <summary>交付报告 Markdown {markdown.truncated ? "（已截断）" : ""}</summary>
                  <MarkdownPreview content={markdown.content} truncated={markdown.truncated} />
                </details>
              )}
              {patch && (
                <details>
                  <summary>Patch Diff {patch.truncated ? "（已截断）" : ""}</summary>
                  <UnifiedDiffViewer
                    diff={patch.content}
                    emptyText="暂无 diff 内容。"
                    fallbackText={patch.content || "暂无 diff 内容。"}
                    leftLabel="原始 HEAD"
                    rightLabel="交付结果"
                  />
                </details>
              )}
            </div>
          )}
        </div>
      ) : (
        <p>执行完成后可生成交付包，包含 diff、报告、回退点和事件尾部。</p>
      )}
    </section>
  );
}
