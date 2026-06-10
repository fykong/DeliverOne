import http from "node:http";

// 不应原样转发的逐跳头
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

/**
 * Agent 运行时反向代理：把 /api/* 流式转发给 Python 运行时。
 * 长任务（工具计划执行）可能跑数分钟，因此不设响应超时，只设连接超时。
 */
export class RuntimeProxy {
  constructor({ runtimeHost, runtimePort, metrics, log }) {
    this.runtimeHost = runtimeHost;
    this.runtimePort = runtimePort;
    this.metrics = metrics;
    this.log = log;
  }

  handle(req, res) {
    const started = Date.now();
    const routeKey = `${req.method} ${this._normalizeRoute(req.url || "/")}`;

    const headers = {};
    for (const [name, value] of Object.entries(req.headers)) {
      if (!HOP_BY_HOP.has(name.toLowerCase())) headers[name] = value;
    }

    const upstream = http.request(
      {
        host: this.runtimeHost,
        port: this.runtimePort,
        path: req.url,
        method: req.method,
        headers,
      },
      (upstreamRes) => {
        const responseHeaders = {};
        for (const [name, value] of Object.entries(upstreamRes.headers)) {
          if (!HOP_BY_HOP.has(name.toLowerCase())) responseHeaders[name] = value;
        }
        res.writeHead(upstreamRes.statusCode || 502, responseHeaders);
        upstreamRes.pipe(res);
        upstreamRes.on("end", () => {
          const latency = Date.now() - started;
          const ok = (upstreamRes.statusCode || 500) < 500;
          this.metrics.recordProxy(routeKey, latency, ok);
          this.log(`${req.method} ${req.url} -> ${upstreamRes.statusCode} ${latency}ms`);
        });
      },
    );

    // 连接建立超时 10s;已建立的长响应不限时(工具计划执行可达数分钟)
    upstream.setTimeout(10_000, () => {
      if (!upstream.socket || upstream.socket.connecting) {
        upstream.destroy(new Error("连接 Agent 运行时超时"));
      }
    });

    upstream.on("error", (error) => {
      const latency = Date.now() - started;
      this.metrics.recordProxy(routeKey, latency, false);
      this.log(`${req.method} ${req.url} -> PROXY ERROR ${error.message}`);
      if (!res.headersSent) {
        const body = JSON.stringify({
          detail: `Node 网关无法连接 Agent 运行时(${this.runtimeHost}:${this.runtimePort})：${error.message}。请确认 npm run dev:server 已启动。`,
        });
        res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
        res.end(body);
      } else {
        res.destroy();
      }
    });

    req.pipe(upstream);
  }

  // 把 /api/events/conv_123 归一成 /api/events/:id,避免指标里路由爆炸
  _normalizeRoute(url) {
    const pathOnly = url.split("?")[0];
    return pathOnly
      .split("/")
      .map((segment) =>
        /^(conv|ckpt|plan|step|proc|sb|grant|delivery|rollback)_[A-Za-z0-9_-]+$/.test(segment) ||
        /^\d{6,}$/.test(segment)
          ? ":id"
          : segment,
      )
      .join("/");
  }
}
