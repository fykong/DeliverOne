import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";

/**
 * 网关侧可观测性：模型调用与 API 代理的计量。
 * 内存里保留汇总 + 最近调用环形缓冲；模型调用同时落盘 jsonl 便于审计。
 * 不记录消息正文（可能包含用户代码），只记录用量与延迟。
 */
export class GatewayMetrics {
  constructor(workspaceRoot) {
    this.modelCallsPath = path.join(workspaceRoot, "node-gateway", "model-calls.jsonl");
    this.model = { calls: 0, failures: 0, promptTokens: 0, completionTokens: 0, totalLatencyMs: 0 };
    this.proxy = { requests: 0, failures: 0, totalLatencyMs: 0, byRoute: new Map() };
    this.recentModelCalls = [];
    this.startedAt = new Date().toISOString();
  }

  async recordModelCall(entry) {
    this.model.calls += 1;
    if (!entry.ok) this.model.failures += 1;
    this.model.promptTokens += entry.promptTokens || 0;
    this.model.completionTokens += entry.completionTokens || 0;
    this.model.totalLatencyMs += entry.latencyMs || 0;
    this.recentModelCalls.push(entry);
    if (this.recentModelCalls.length > 50) this.recentModelCalls.shift();
    try {
      await mkdir(path.dirname(this.modelCallsPath), { recursive: true });
      await appendFile(this.modelCallsPath, JSON.stringify(entry) + "\n", "utf-8");
    } catch {
      // 落盘失败不阻断调用链路
    }
  }

  recordProxy(routeKey, latencyMs, ok) {
    this.proxy.requests += 1;
    if (!ok) this.proxy.failures += 1;
    this.proxy.totalLatencyMs += latencyMs;
    const existing = this.proxy.byRoute.get(routeKey) || { count: 0, totalLatencyMs: 0, failures: 0 };
    existing.count += 1;
    existing.totalLatencyMs += latencyMs;
    if (!ok) existing.failures += 1;
    this.proxy.byRoute.set(routeKey, existing);
  }

  summary() {
    const routes = [...this.proxy.byRoute.entries()]
      .map(([route, stats]) => ({
        route,
        count: stats.count,
        failures: stats.failures,
        avgLatencyMs: Math.round(stats.totalLatencyMs / Math.max(1, stats.count)),
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20);
    return {
      startedAt: this.startedAt,
      model: {
        ...this.model,
        avgLatencyMs: Math.round(this.model.totalLatencyMs / Math.max(1, this.model.calls)),
        totalTokens: this.model.promptTokens + this.model.completionTokens,
      },
      proxy: {
        requests: this.proxy.requests,
        failures: this.proxy.failures,
        avgLatencyMs: Math.round(this.proxy.totalLatencyMs / Math.max(1, this.proxy.requests)),
        topRoutes: routes,
      },
      recentModelCalls: this.recentModelCalls.slice(-20),
      modelCallsLogPath: this.modelCallsPath,
    };
  }
}
