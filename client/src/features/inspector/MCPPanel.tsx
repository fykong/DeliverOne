import { AlertTriangle, CheckCircle2, FileJson2, KeyRound, ListChecks, PlugZap, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  ApprovalGrant,
  MCPConfigValidation,
  MCPPayloadPreview,
  MCPSchemaSummary,
  MCPServerManifest,
  MCPToolHistoryEntry,
  MCPToolManifest
} from "@workbench/shared";

interface MCPPanelProps {
  config: Record<string, unknown> | null;
  configValidation: MCPConfigValidation | null;
  servers: MCPServerManifest[];
  tools: MCPToolManifest[];
  history: MCPToolHistoryEntry[];
  approvals: ApprovalGrant[];
  isRunning: boolean;
  onDiscover: () => void;
  onSaveConfig: (config: Record<string, unknown>) => Promise<boolean>;
  onValidateConfig: (config: Record<string, unknown>) => void;
  onReplayHistory: (historyEntryId: string) => void;
  onGrant: (toolId: string, scope: ApprovalGrant["scope"]) => void;
  onRevoke: (grantId: string) => void;
}

function statusText(status: MCPServerManifest["status"]) {
  if (status === "configured") return "已配置";
  if (status === "misconfigured") return "配置异常";
  return "未启用";
}

function scopeText(scope: ApprovalGrant["scope"]) {
  if (scope === "once") return "一次";
  if (scope === "turn") return "本轮";
  return "会话";
}

function historyStatusText(status: MCPToolHistoryEntry["status"]) {
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "needs_approval") return "待授权";
  if (status === "running") return "运行中";
  return "未知";
}

function endpointText(server: MCPServerManifest) {
  const value = server.endpoint ?? server.details?.url ?? server.details?.command;
  return typeof value === "string" && value.trim() ? value : null;
}

function prettyJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseConfig(text: string) {
  return JSON.parse(text) as Record<string, unknown>;
}

function formatBytes(value?: number) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}

function shortText(value: string | undefined, fallback = "暂无") {
  const text = (value ?? "").trim();
  return text ? text : fallback;
}

function previewFallback(value: unknown): MCPPayloadPreview | null {
  if (value === undefined || value === null) return null;
  const text = prettyJson(value);
  return {
    text: text.length > 2200 ? `${text.slice(0, 2200)}...[已截断]` : text,
    truncated: text.length > 2200,
    bytes: new TextEncoder().encode(text).length,
    kind: Array.isArray(value) ? "array" : typeof value
  };
}

function SchemaSummaryView({ summary, rawSchema }: { summary?: MCPSchemaSummary | null; rawSchema?: Record<string, unknown> }) {
  if (!summary && rawSchema) {
    return (
      <details>
        <summary>输入 Schema</summary>
        <pre>{prettyJson(rawSchema)}</pre>
      </details>
    );
  }
  if (!summary) {
    return <p className="mutedText">这个工具暂时没有提供输入 schema。</p>;
  }

  return (
    <div className="mcpSchemaSummary">
      <div className="mcpSchemaMeta">
        <span>类型：{summary.type}</span>
        <span>字段：{summary.propertyCount}</span>
        <span>必填：{summary.required.length ? summary.required.join(" / ") : "无"}</span>
      </div>
      {summary.properties.length > 0 ? (
        <div className="mcpSchemaRows">
          {summary.properties.map((property) => (
            <div className="mcpSchemaRow" key={property.name}>
              <strong>
                {property.name}
                {property.required ? <em>必填</em> : null}
              </strong>
              <span>{property.type}</span>
              <p>{shortText(property.description, property.enum?.length ? `可选：${property.enum.join(" / ")}` : "无字段说明")}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mutedText">这个 schema 没有声明 properties。</p>
      )}
      {rawSchema ? (
        <details>
          <summary>原始 JSON Schema</summary>
          <pre>{prettyJson(rawSchema)}</pre>
        </details>
      ) : null}
    </div>
  );
}

function PreviewBlock({ title, preview }: { title: string; preview?: MCPPayloadPreview | null }) {
  return (
    <section className="drawerBlock">
      <header>
        <strong>{title}</strong>
        {preview ? <span>{preview.kind} · {formatBytes(preview.bytes)}{preview.truncated ? " · 已截断" : ""}</span> : <span>无数据</span>}
      </header>
      {preview ? <pre>{preview.text}</pre> : <p className="mutedText">这条事件没有保存对应内容。</p>}
    </section>
  );
}

export function MCPPanel({
  config,
  configValidation,
  servers,
  tools,
  history,
  approvals,
  isRunning,
  onDiscover,
  onSaveConfig,
  onValidateConfig,
  onReplayHistory,
  onGrant,
  onRevoke
}: MCPPanelProps) {
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [isEditingConfig, setIsEditingConfig] = useState(false);
  const [configText, setConfigText] = useState(prettyJson(config ?? { version: 1, servers: [] }));
  const [configError, setConfigError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const configUnavailable = config === null;

  const externalTools = tools.filter((tool) => tool.source === "external");
  const activeApprovals = approvals.filter((approval) => approval.active);
  const recommendedTools = useMemo(() => {
    const top = tools.filter((tool) => (tool.recommendationScore ?? 0) >= 0.78).slice(0, 5);
    return top.length ? top : tools.slice(0, 5);
  }, [tools]);
  const selectedTool = tools.find((tool) => tool.id === selectedToolId) ?? recommendedTools[0] ?? tools[0] ?? null;
  const toolHistory = useMemo(
    () => history.filter((entry) => !selectedTool || entry.toolId === selectedTool.id).slice(-10).reverse(),
    [history, selectedTool]
  );
  const selectedEvent = history.find((event) => event.id === selectedEventId) ?? null;
  const selectedEventCanReplay = Boolean(selectedEvent?.payload && Object.prototype.hasOwnProperty.call(selectedEvent.payload, "input"));

  useEffect(() => {
    setConfigText(prettyJson(config ?? { version: 1, servers: [] }));
  }, [config]);

  function readConfig() {
    try {
      const parsed = parseConfig(configText);
      setConfigError(null);
      return parsed;
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : String(error));
      return null;
    }
  }

  async function saveConfig() {
    if (configUnavailable) {
      setConfigError("配置加载失败，已禁止保存以防覆盖真实配置文件。");
      return;
    }
    const parsed = readConfig();
    if (!parsed) return;
    const ok = await onSaveConfig(parsed);
    if (ok) {
      setIsEditingConfig(false);
    }
  }

  function validateConfig() {
    const parsed = readConfig();
    if (parsed) {
      onValidateConfig(parsed);
    }
  }

  return (
    <section className="panel">
      <h3>
        <PlugZap size={16} />
        MCP 工具
        <small>{externalTools.length ? `${externalTools.length} 个外部工具` : `${tools.length} 个可用工具`}</small>
      </h3>

      <div className="mcpSummary">
        <div>
          <strong>{servers.length}</strong>
          <span>Server</span>
        </div>
        <div>
          <strong>{externalTools.length}</strong>
          <span>外部工具</span>
        </div>
        <div>
          <strong>{activeApprovals.length}</strong>
          <span>授权中</span>
        </div>
      </div>

      <div className="mcpActions">
        <button className="inspectorButton secondary" type="button" disabled={isRunning} onClick={onDiscover}>
          <RefreshCw size={16} />
          发现工具
        </button>
        <button className="inspectorButton secondary" type="button" disabled={isRunning} onClick={() => setIsEditingConfig((value) => !value)}>
          <FileJson2 size={16} />
          编辑配置
        </button>
      </div>

      {configUnavailable && (
        <p className="mcpConfigWarning">
          <AlertTriangle size={13} />
          MCP 配置加载失败，已禁止保存以防空模板覆盖真实配置文件；请确认后端已重启，再点右上角「刷新证据」重新加载。
        </p>
      )}

      {isEditingConfig && (
        <div className="mcpConfigEditor">
          <textarea value={configText} onChange={(event) => setConfigText(event.target.value)} spellCheck={false} />
          {configError && <p>{configError}</p>}
          {configValidation && (
            <div className={`mcpValidation ${configValidation.ok ? "valid" : "invalid"}`}>
              <strong>{configValidation.ok ? "配置校验通过" : "配置校验失败"}</strong>
              {[...configValidation.errors, ...configValidation.warnings].slice(0, 4).map((issue) => (
                <span key={`${issue.path}-${issue.message}`}>
                  {issue.path}：{issue.message}
                </span>
              ))}
            </div>
          )}
          <div className="miniActions">
            <button type="button" disabled={isRunning} onClick={validateConfig}>
              校验配置
            </button>
            <button type="button" disabled={isRunning || configUnavailable} onClick={saveConfig} title={configUnavailable ? "配置加载失败时禁止保存，避免覆盖真实配置。" : undefined}>
              保存配置
            </button>
            <button type="button" disabled={isRunning} onClick={() => setIsEditingConfig(false)}>
              取消
            </button>
          </div>
        </div>
      )}

      <div className="mcpList">
        {servers.map((server) => (
          <div className={`mcpServer ${server.status}`} key={server.id ?? server.name}>
            <div>
              <strong>{server.name ?? server.id ?? "未命名 Server"}</strong>
              <span>
                {server.transport ?? "unknown"} · {statusText(server.status)} · {server.toolDiscovery ?? "pending"}
              </span>
            </div>
            {endpointText(server) && <p>入口：{endpointText(server)}</p>}
            {server.toolCount !== undefined && <p>已发现工具：{server.toolCount}</p>}
            {server.discoveryError ? <p>发现失败：{server.discoveryError}</p> : null}
            {server.problems?.length ? <p>{server.problems.join("；")}</p> : null}
          </div>
        ))}
        {servers.length === 0 && <p>当前还没有配置外部 MCP server，内置工具仍可通过统一工具入口调用。</p>}
      </div>

      <div className="mcpToolDetails">
        <div>
          <strong>推荐工具</strong>
          <span>后端按当前需求、风险和交付阶段排序</span>
        </div>
        <div className="mcpRecommendationList">
          {recommendedTools.map((tool) => (
            <button className={`mcpRecommendation ${selectedTool?.id === tool.id ? "active" : ""}`} key={tool.id} type="button" onClick={() => setSelectedToolId(tool.id)}>
              <span>
                <ListChecks size={13} />
                {tool.name}
              </span>
              <strong>{Math.round((tool.recommendationScore ?? 0) * 100)}</strong>
              <small>{tool.recommendationReason ?? "可通过统一工具运行时调用。"}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="mcpToolDetails">
        {selectedTool ? (
          <>
            <div>
              <strong>{selectedTool.name}</strong>
              <span>
                {selectedTool.source === "external" ? "外部 MCP" : "内置工具"} · {selectedTool.transport ?? "internal"} · {selectedTool.riskLevel}
              </span>
            </div>
            <p>{selectedTool.description || "暂无描述。"}</p>
            {selectedTool.serverId && <p>Server：{selectedTool.serverId}</p>}
            {selectedTool.endpoint && <p>入口：{selectedTool.endpoint}</p>}
            {selectedTool.recommendationSignals?.length ? <p>信号：{selectedTool.recommendationSignals.join(" / ")}</p> : null}
            <SchemaSummaryView summary={selectedTool.schemaSummary} rawSchema={selectedTool.inputSchema} />
            <details open>
              <summary>调用历史</summary>
              <div className="mcpHistory">
                {toolHistory.map((entry) => (
                  <button className={`mcpHistoryRow ${entry.status}`} key={entry.id} type="button" onClick={() => setSelectedEventId(entry.id)}>
                    <strong>{historyStatusText(entry.status)}</strong>
                    <span>{new Date(entry.createdAt).toLocaleTimeString()}</span>
                    {entry.planId && <span>{entry.stepId ? `${entry.planId} / ${entry.stepId}` : entry.planId}</span>}
                    <code>{entry.summary}</code>
                    {entry.resultPreview ? <small>{entry.resultPreview.kind} · {formatBytes(entry.resultPreview.bytes)}</small> : null}
                  </button>
                ))}
                {toolHistory.length === 0 && <p>当前工具还没有调用历史。</p>}
              </div>
            </details>
            {selectedTool.source === "external" && (
              <div className="miniActions">
                <button type="button" disabled={isRunning} onClick={() => onGrant(selectedTool.id, "once")}>
                  <KeyRound size={13} />
                  授权一次
                </button>
                <button type="button" disabled={isRunning} onClick={() => onGrant(selectedTool.id, "session")}>
                  会话授权
                </button>
              </div>
            )}
          </>
        ) : (
          <p>发现 MCP 工具后，这里会显示 schema 和调用历史。</p>
        )}
      </div>

      {activeApprovals.length > 0 && (
        <div className="approvalList">
          {activeApprovals.map((approval) => (
            <div className="approvalRow" key={approval.id}>
              <div>
                <strong>{approval.toolId}</strong>
                <span>
                  {scopeText(approval.scope)}授权 · {approval.riskLevel}
                </span>
              </div>
              <button type="button" disabled={isRunning} onClick={() => onRevoke(approval.id)} title="撤销授权">
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {selectedEvent && (
        <div className="sideDrawer" role="dialog" aria-modal="true" aria-label="MCP 调用结果">
          <header>
            <div>
              <span>调用结果</span>
              <strong>{selectedEvent.type}</strong>
            </div>
            <button className="iconButton" type="button" onClick={() => setSelectedEventId(null)} title="关闭">
              <X size={16} />
            </button>
          </header>
          <div className={`drawerStatus ${selectedEvent.status}`}>
            {selectedEvent.status === "completed" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {historyStatusText(selectedEvent.status)}
          </div>
          <div className="drawerMetaGrid">
            <span>工具</span>
            <code>{selectedEvent.toolId}</code>
            <span>事件</span>
            <code>{selectedEvent.type}</code>
            <span>来源</span>
            <code>{selectedEvent.source}</code>
            <span>计划</span>
            <code>{selectedEvent.planId ? `${selectedEvent.planId}${selectedEvent.stepId ? ` / ${selectedEvent.stepId}` : ""}` : "未绑定"}</code>
          </div>
          {selectedEvent.approval ? (
            <div className="drawerNotice">
              <strong>{selectedEvent.approval.needsApproval ? "需要审批" : "审批信息"}</strong>
              <span>
                {selectedEvent.approval.allowed === true ? "已允许" : selectedEvent.approval.allowed === false ? "未允许" : "未记录结果"}
                {selectedEvent.approval.riskLevel ? ` · ${selectedEvent.approval.riskLevel}` : ""}
              </span>
              {selectedEvent.approval.reason ? <p>{selectedEvent.approval.reason}</p> : null}
            </div>
          ) : null}
          {selectedEventCanReplay && (
            <div className="miniActions">
              <button type="button" disabled={isRunning} onClick={() => onReplayHistory(selectedEvent.id)}>
                <RefreshCw size={13} />
                重放调用
              </button>
            </div>
          )}
          <div className="drawerScroll">
            <section className="drawerBlock">
              <header>
                <strong>工具输入 Schema</strong>
                <span>用于审查参数是否合理</span>
              </header>
              <SchemaSummaryView summary={selectedEvent.schemaSummary} />
            </section>
            <PreviewBlock title="本次输入" preview={selectedEvent.inputPreview ?? previewFallback(selectedEvent.payload?.input)} />
            <PreviewBlock title="本次输出" preview={selectedEvent.resultPreview ?? previewFallback(selectedEvent.result)} />
            <details className="drawerRaw">
              <summary>完整事件 JSON</summary>
              <pre>{prettyJson(selectedEvent)}</pre>
            </details>
          </div>
        </div>
      )}
    </section>
  );
}
