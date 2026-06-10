import http from "node:http";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { GatewayMetrics } from "./metrics.js";
import { ModelGateway } from "./model-gateway.js";
import { RuntimeProxy } from "./proxy.js";

/**
 * DeliverOne 的 Node 后端网关：
 *   前端(5173) -> Node 网关(4000) -> Python Agent 运行时(4317)
 *
 * 真实职责：
 *   1. 统一 API 入口与请求日志(前端只与本服务通信)
 *   2. 模型网关 /v1/model/chat/completions:ARK_API_KEY 只在本进程,
 *      Agent 运行时不持有真实密钥;含限流与用量计量
 *   3. 网关可观测性 /api/node/metrics(模型 tokens/延迟 + 路由统计)
 */

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function loadEnvFile(filePath) {
  try {
    const raw = readFileSync(filePath, "utf-8");
    for (const rawLine of raw.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const index = line.indexOf("=");
      const key = line.slice(0, index).trim();
      const value = line
        .slice(index + 1)
        .trim()
        .replace(/^['"]|['"]$/g, "");
      // .env 优先于继承的系统环境变量:演示机上残留的旧 key 曾覆盖比赛 key
      if (key) process.env[key] = value;
    }
  } catch {
    // .env 不存在时静默,由各组件自行报缺配置
  }
}

loadEnvFile(path.join(PROJECT_ROOT, ".env"));

const PORT = Number(process.env.GATEWAY_PORT || 4000);
const RUNTIME_HOST = process.env.PY_RUNTIME_HOST || "127.0.0.1";
const RUNTIME_PORT = Number(process.env.PY_RUNTIME_PORT || 4317);
const ARK_ENDPOINT = process.env.ARK_ENDPOINT || "https://ark.cn-beijing.volces.com/api/v3/chat/completions";
const RATE_LIMIT = Number(process.env.MODEL_RATE_LIMIT_PER_MIN || 60);

function log(message) {
  process.stdout.write(`[gateway ${new Date().toISOString()}] ${message}\n`);
}

const metrics = new GatewayMetrics(path.join(PROJECT_ROOT, "workspace"));
const modelGateway = new ModelGateway({
  arkEndpoint: ARK_ENDPOINT,
  apiKey: process.env.ARK_API_KEY || "",
  metrics,
  rateLimitPerMinute: RATE_LIMIT,
});
const proxy = new RuntimeProxy({ runtimeHost: RUNTIME_HOST, runtimePort: RUNTIME_PORT, metrics, log });

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function checkRuntimeHealth() {
  return new Promise((resolve) => {
    const request = http.request(
      { host: RUNTIME_HOST, port: RUNTIME_PORT, path: "/api/health", method: "GET", timeout: 3000 },
      (response) => {
        resolve(response.statusCode === 200);
        response.resume();
      },
    );
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
    request.end();
  });
}

const server = http.createServer(async (req, res) => {
  const url = req.url || "/";

  // 网关自有端点(带 CORS);其余 /api/* 透传 Python(CORS 由运行时返回)
  if (req.method === "OPTIONS" && (url.startsWith("/api/node/") || url === "/healthz")) {
    sendJson(res, 204, {});
    return;
  }

  if (url === "/healthz") {
    const runtimeOk = await checkRuntimeHealth();
    sendJson(res, 200, {
      ok: true,
      service: "workbench-node-gateway",
      port: PORT,
      runtime: { host: RUNTIME_HOST, port: RUNTIME_PORT, healthy: runtimeOk },
      modelGatewayConfigured: modelGateway.isConfigured(),
      time: new Date().toISOString(),
    });
    return;
  }

  if (url === "/api/node/metrics") {
    sendJson(res, 200, metrics.summary());
    return;
  }

  if (url === "/v1/model/chat/completions" && req.method === "POST") {
    const body = await readBody(req);
    await modelGateway.handle(req, res, body);
    return;
  }

  if (url.startsWith("/api/")) {
    proxy.handle(req, res);
    return;
  }

  sendJson(res, 404, { detail: `未知路径：${url}` });
});

server.listen(PORT, "127.0.0.1", () => {
  log(`Node 网关已启动 http://127.0.0.1:${PORT}`);
  log(`Agent 运行时上游 http://${RUNTIME_HOST}:${RUNTIME_PORT}`);
  log(`模型网关${modelGateway.isConfigured() ? "已配置(密钥仅驻留本进程)" : "未配置 ARK_API_KEY"}，限流 ${RATE_LIMIT}/min`);
});
