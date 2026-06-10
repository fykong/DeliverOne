import { Activity } from "lucide-react";
import type { RuntimeMetricsResponse } from "@workbench/shared";

interface MetricsPanelProps {
  metrics: RuntimeMetricsResponse | null;
}

function formatCost(value: number) {
  if (!value) return "$0";
  return `$${value.toFixed(value < 0.01 ? 6 : 4)}`;
}

function formatMs(value?: number) {
  if (!value) return "0s";
  if (value < 1000) return `${value}ms`;
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`;
}

function formatTokens(value?: number) {
  if (!value) return "0";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

export function MetricsPanel({ metrics }: MetricsPanelProps) {
  const summary = metrics?.summary;

  return (
    <section className="panel">
      <h3>
        <Activity size={16} />
        运行指标
        <small>{summary ? `${summary.modelCallCount} 次模型 · ${summary.toolCallCount} 次工具` : "暂无数据"}</small>
      </h3>
      <div className="metricGrid">
        <div>
          <strong>{formatTokens(summary?.totalTokens)}</strong>
          <span>Token 总量</span>
        </div>
        <div>
          <strong>{formatMs(summary?.avgModelLatencyMs)}</strong>
          <span>平均延迟/次</span>
        </div>
        <div>
          <strong>{formatMs(summary?.modelDurationMs)}</strong>
          <span>模型总耗时</span>
        </div>
        <div>
          <strong>{formatCost(summary?.totalEstimatedCost ?? 0)}</strong>
          <span>估算成本</span>
        </div>
      </div>
      {summary && (
        <p className="metricDetail">
          输入 {formatTokens(summary.promptTokens)} / 输出 {formatTokens(summary.completionTokens)} token
          {summary.avgPromptTokens ? ` · 平均输入 ${formatTokens(summary.avgPromptTokens)}/次` : ""}
          {summary.maxModelLatencyMs ? ` · 最慢 ${formatMs(summary.maxModelLatencyMs)}` : ""}
          {summary.pricingConfigured === false ? " · 成本待配价（仅记 token/延迟）" : ""}
        </p>
      )}
      {summary && summary.failedToolCalls > 0 && <p>{summary.failedToolCalls} 次工具调用失败，需要进入审查或修复。</p>}
      {!summary && <p>Agent 调用模型或工具后，这里会显示 token、延迟、成本和失败次数。</p>}
    </section>
  );
}
