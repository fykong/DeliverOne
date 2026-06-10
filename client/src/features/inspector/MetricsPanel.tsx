import { Activity } from "lucide-react";
import type { RuntimeMetricsResponse } from "@workbench/shared";

interface MetricsPanelProps {
  metrics: RuntimeMetricsResponse | null;
}

function formatCost(value: number) {
  if (!value) return "$0";
  return `$${value.toFixed(value < 0.01 ? 6 : 4)}`;
}

export function MetricsPanel({ metrics }: MetricsPanelProps) {
  const summary = metrics?.summary;

  return (
    <section className="panel">
      <h3>
        <Activity size={16} />
        运行指标
        <small>{summary ? `${summary.toolCallCount} 次工具` : "暂无数据"}</small>
      </h3>
      <div className="metricGrid">
        <div>
          <strong>{summary?.modelCallCount ?? 0}</strong>
          <span>模型调用</span>
        </div>
        <div>
          <strong>{summary?.toolCallCount ?? 0}</strong>
          <span>工具调用</span>
        </div>
        <div>
          <strong>{summary?.totalTokens ?? 0}</strong>
          <span>Token</span>
        </div>
        <div>
          <strong>{formatCost(summary?.totalEstimatedCost ?? 0)}</strong>
          <span>估算成本</span>
        </div>
      </div>
      {summary && summary.failedToolCalls > 0 && <p>{summary.failedToolCalls} 次工具调用失败，需要进入审查或修复。</p>}
      {!summary && <p>Agent 调用模型或工具后，这里会显示 token、耗时、成本和失败次数。</p>}
    </section>
  );
}
