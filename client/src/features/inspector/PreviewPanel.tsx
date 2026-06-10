import { ExternalLink, Image as ImageIcon, RefreshCw, Square, Terminal } from "lucide-react";
import { useMemo, useState } from "react";
import type { ManagedProcess, PreviewSmokeReport, RuntimeCommandRecommendation } from "@workbench/shared";
import { getPreviewScreenshotUrl } from "../../shared/api";

interface PreviewPanelProps {
  conversationId: string;
  processes: ManagedProcess[];
  previewSmokeReport: PreviewSmokeReport | null;
  previewCommand: string;
  recommendedPreview?: RuntimeCommandRecommendation | null;
  isRunning: boolean;
  onPreviewCommandChange: (value: string) => void;
  onStartPreview: () => void;
  onStopPreview: (processId: string) => void;
  onRunPreviewSmokeTest: (port: number) => void;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    starting: "启动中",
    running: "运行中",
    stopped: "已停止",
    exited: "已退出",
    failed: "失败",
  };
  return labels[status] ?? status;
}

export function PreviewPanel({
  conversationId,
  processes,
  previewSmokeReport,
  previewCommand,
  recommendedPreview,
  isRunning,
  onPreviewCommandChange,
  onStartPreview,
  onStopPreview,
  onRunPreviewSmokeTest
}: PreviewPanelProps) {
  const [frameVersion, setFrameVersion] = useState(0);
  const activePreview = useMemo(() => {
    return processes.find((process) => process.status === "running" && process.ports.length > 0) ?? null;
  }, [processes]);
  const activePort = activePreview?.ports[0] ?? null;
  const activeUrl = activePort ? `http://127.0.0.1:${activePort}` : null;

  return (
    <section className="panel">
      <h3>
        <Terminal size={16} />
        实时预览
      </h3>
      <div className="previewControl">
        <input value={previewCommand} onChange={(event) => onPreviewCommandChange(event.target.value)} placeholder="npm run dev" />
        {recommendedPreview && (
          <button type="button" disabled={isRunning} onClick={() => onPreviewCommandChange(recommendedPreview.command)} title={recommendedPreview.reason}>
            用推荐
          </button>
        )}
        <button type="button" disabled={isRunning || !previewCommand.trim()} onClick={onStartPreview}>
          启动
        </button>
      </div>
      {recommendedPreview && (
        <p className="previewRecommendation">
          推荐：<code>{recommendedPreview.command}</code>
          <span>{recommendedPreview.reason}</span>
        </p>
      )}

      <div className="livePreviewSurface">
        <div className="livePreviewToolbar">
          <span>{activeUrl ? `沙盒页面 ${activePort}` : "沙盒页面未启动"}</span>
          <div>
            <button type="button" disabled={!activeUrl} onClick={() => setFrameVersion((value) => value + 1)} title="刷新预览">
              <RefreshCw size={13} />
              刷新
            </button>
            {activeUrl && (
              <a href={activeUrl} target="_blank" rel="noreferrer">
                <ExternalLink size={13} />
                打开
              </a>
            )}
            {activePort && (
              <button type="button" disabled={isRunning} onClick={() => onRunPreviewSmokeTest(activePort)} title="运行页面 smoke test">
                验证
              </button>
            )}
          </div>
        </div>
        {activeUrl ? (
          <iframe key={`${activeUrl}-${frameVersion}`} title="沙盒实时预览" src={activeUrl} />
        ) : (
          <div className="livePreviewEmpty">
            启动预览命令后这里会显示被修改项目的页面。首次启动会自动安装依赖（约 1-3 分钟），页面空白时点「刷新」或查看下方进程日志。
          </div>
        )}
      </div>

      {processes.map((process) => {
        const canStop = process.status === "running" || process.status === "starting";
        const logTail = [process.stderrTail, process.stdoutTail].filter(Boolean).join("\n").trim();
        const failed = process.status === "failed" || process.status === "exited";
        return (
          <div className="processRow" key={process.id}>
            <span>{statusLabel(process.status)}</span>
            <code>{process.command}</code>
            <div className="processActions">
              {process.ports.map((port) => (
                <span className="processPort" key={port}>
                  <a href={`http://127.0.0.1:${port}`} target="_blank" rel="noreferrer">
                    打开 {port}
                  </a>
                  <button type="button" disabled={isRunning} onClick={() => onRunPreviewSmokeTest(port)} title="运行页面 smoke test">
                    验证
                  </button>
                </span>
              ))}
              {canStop && (
                <button type="button" disabled={isRunning} onClick={() => onStopPreview(process.id)} title="停止预览进程">
                  <Square size={13} />
                  停止
                </button>
              )}
            </div>
            {logTail && (
              <details className="processLog" open={failed}>
                <summary>{failed ? "进程已退出——查看日志找原因" : "查看进程日志"}</summary>
                <pre>{logTail.slice(-2400)}</pre>
              </details>
            )}
          </div>
        );
      })}

      {previewSmokeReport && (
        <div className={`smokeResult ${previewSmokeReport.ok ? "pass" : "fail"}`}>
          <strong>{previewSmokeReport.ok ? "预览验证通过" : "预览验证失败"}</strong>
          <span>{previewSmokeReport.summary}</span>
          <code>{previewSmokeReport.url}</code>
          {previewSmokeReport.quality?.checks?.length > 0 && (
            <div className="qualityList">
              {previewSmokeReport.quality.checks.map((check) => (
                <span className={check.ok ? "pass" : "fail"} key={check.id}>
                  {check.title}：{check.ok ? "通过" : check.detail}
                </span>
              ))}
            </div>
          )}
          {previewSmokeReport.screenshot.path && <p>截图：{previewSmokeReport.screenshot.path}</p>}
          {previewSmokeReport.runtimeDom && (
            <p>
              运行后 DOM：{previewSmokeReport.runtimeDom.ok ? "已读取" : "失败"} · {previewSmokeReport.runtimeDom.bytes ?? 0} bytes · 可见文本{" "}
              {previewSmokeReport.runtimeDom.visibleTextLength ?? 0}
            </p>
          )}
          {previewSmokeReport.browserConsole && (
            <div className={`consoleSummary ${previewSmokeReport.browserConsole.errorCount > 0 ? "fail" : "pass"}`}>
              <span>
                控制台错误：{previewSmokeReport.browserConsole.errorCount} · {previewSmokeReport.browserConsole.reliable ? "CDP" : "降级"}
              </span>
              {previewSmokeReport.browserConsole.errors.slice(0, 3).map((item, index) => (
                <code key={`${item.message}-${index}`}>{item.message}</code>
              ))}
            </div>
          )}
          {previewSmokeReport.assertions?.enabled && (
            <div className={`assertionSummary ${previewSmokeReport.assertions.ok ? "pass" : "fail"}`}>
              <span>{previewSmokeReport.assertions.summary}</span>
              {[...previewSmokeReport.assertions.textResults, ...previewSmokeReport.assertions.selectorResults]
                .filter((item) => !item.ok)
                .slice(0, 4)
                .map((item, index) => (
                  <code key={`${"text" in item ? item.text : item.selector}-${index}`}>
                    {"text" in item ? item.text : item.selector}：{item.detail}
                  </code>
                ))}
            </div>
          )}
          {previewSmokeReport.screenshot.path && (
            <figure className="screenshotPreview">
              <img src={getPreviewScreenshotUrl(conversationId, previewSmokeReport.generatedAt)} alt="预览 smoke test 截图" />
              <figcaption>
                <ImageIcon size={13} />
                {previewSmokeReport.htmlTitle || "预览截图"} · {previewSmokeReport.screenshot.bytes ?? 0} bytes
              </figcaption>
            </figure>
          )}
        </div>
      )}
    </section>
  );
}
