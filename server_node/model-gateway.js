import https from "node:https";
import { URL } from "node:url";

/**
 * 模型网关：API Key 只存在于 Node 进程，Agent 运行时（Python）通过本网关
 * 调用火山方舟。职责：密钥托管、滑动窗口限流、用量/延迟计量、错误归一。
 */
export class ModelGateway {
  constructor({ arkEndpoint, apiKey, metrics, rateLimitPerMinute = 60 }) {
    this.arkEndpoint = new URL(arkEndpoint);
    this.apiKey = apiKey;
    this.metrics = metrics;
    this.rateLimitPerMinute = rateLimitPerMinute;
    this.callTimestamps = [];
  }

  isConfigured() {
    return Boolean(this.apiKey);
  }

  _rateLimited() {
    const now = Date.now();
    this.callTimestamps = this.callTimestamps.filter((ts) => now - ts < 60_000);
    if (this.callTimestamps.length >= this.rateLimitPerMinute) {
      return true;
    }
    this.callTimestamps.push(now);
    return false;
  }

  async handle(req, res, bodyBuffer) {
    if (!this.isConfigured()) {
      this._json(res, 503, {
        error: { message: "网关未配置 ARK_API_KEY，请在项目根目录 .env 配置后重启 Node 网关。" },
      });
      return;
    }
    if (this._rateLimited()) {
      this._json(res, 429, {
        error: { message: `网关限流：每分钟最多 ${this.rateLimitPerMinute} 次模型调用，请稍后重试。` },
      });
      return;
    }

    const started = Date.now();
    let parsedBody = {};
    try {
      parsedBody = JSON.parse(bodyBuffer.toString("utf-8"));
    } catch {
      this._json(res, 400, { error: { message: "请求体不是合法 JSON。" } });
      return;
    }

    try {
      const { status, payload } = await this._forwardToArk(bodyBuffer);
      const usage = payload?.usage || {};
      await this.metrics.recordModelCall({
        at: new Date().toISOString(),
        ok: status === 200,
        status,
        model: parsedBody.model || null,
        promptTokens: usage.prompt_tokens || 0,
        completionTokens: usage.completion_tokens || 0,
        totalTokens: usage.total_tokens || 0,
        latencyMs: Date.now() - started,
        caller: req.headers["x-workbench-caller"] || "python-runtime",
      });
      this._json(res, status, payload);
    } catch (error) {
      await this.metrics.recordModelCall({
        at: new Date().toISOString(),
        ok: false,
        status: 0,
        model: parsedBody.model || null,
        promptTokens: 0,
        completionTokens: 0,
        totalTokens: 0,
        latencyMs: Date.now() - started,
        error: String(error?.message || error),
        caller: req.headers["x-workbench-caller"] || "python-runtime",
      });
      this._json(res, 502, { error: { message: `模型网关转发失败：${error?.message || error}` } });
    }
  }

  _forwardToArk(bodyBuffer) {
    return new Promise((resolve, reject) => {
      const request = https.request(
        {
          hostname: this.arkEndpoint.hostname,
          path: this.arkEndpoint.pathname,
          method: "POST",
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            "Content-Type": "application/json",
            "Content-Length": bodyBuffer.length,
          },
          timeout: 120_000,
        },
        (response) => {
          const chunks = [];
          response.on("data", (chunk) => chunks.push(chunk));
          response.on("end", () => {
            const text = Buffer.concat(chunks).toString("utf-8");
            try {
              resolve({ status: response.statusCode || 502, payload: JSON.parse(text) });
            } catch {
              resolve({
                status: response.statusCode || 502,
                payload: { error: { message: `上游返回非 JSON：${text.slice(0, 300)}` } },
              });
            }
          });
        },
      );
      request.on("timeout", () => {
        request.destroy(new Error("上游调用超过 120s 超时"));
      });
      request.on("error", reject);
      request.write(bodyBuffer);
      request.end();
    });
  }

  _json(res, status, payload) {
    const body = JSON.stringify(payload);
    res.writeHead(status, {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Length": Buffer.byteLength(body),
    });
    res.end(body);
  }
}
