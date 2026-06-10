from __future__ import annotations

import socket
import subprocess
import time
import urllib.error
import urllib.request
import re
import json
import shutil
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.runtime.events import EventStore


class PreviewSmokeTester:
    def __init__(self, events: EventStore) -> None:
        self.events = events

    def run(
        self,
        conversation_id: str,
        port: int,
        path: str = "/",
        host: str = "127.0.0.1",
        timeout_seconds: int = 30,
        expected_texts: list[str] | None = None,
        required_selectors: list[str] | None = None,
    ) -> dict[str, Any]:
        safe_path = path if path.startswith("/") else f"/{path}"
        url = f"http://{host}:{port}{safe_path}"
        expected_texts = self._clean_string_list(expected_texts)
        required_selectors = self._clean_string_list(required_selectors)
        root = conversation_root(conversation_id) / "preview"
        root.mkdir(parents=True, exist_ok=True)
        self.events.append(
            conversation_id,
            "preview.smoke.begin",
            {
                "url": url,
                "timeoutSeconds": timeout_seconds,
                "expectedTextCount": len(expected_texts),
                "requiredSelectorCount": len(required_selectors),
            },
            actor="runtime",
        )

        port_open = self._wait_for_port(host, port, timeout_seconds)
        response = self._fetch(url) if port_open else {"ok": False, "status": 0, "error": "端口未在超时时间内打开。", "html": ""}
        html_path = root / "preview-response.html"
        html = str(response.get("html") or "")
        html_path.write_text(html, encoding="utf-8")
        diagnostics = self._browser_diagnostics(url, root, required_selectors) if port_open else {}
        runtime_dom = diagnostics.get("runtimeDom") if isinstance(diagnostics.get("runtimeDom"), dict) else None
        if not runtime_dom:
            runtime_dom = self._runtime_dom(url, root / "runtime-dom.html") if port_open else {"ok": False, "path": None, "error": "端口未打开，跳过运行后 DOM 检查。"}
        browser_console = diagnostics.get("browserConsole") if isinstance(diagnostics.get("browserConsole"), dict) else None
        screenshot = self._screenshot(url, root / "preview.png") if port_open else {"ok": False, "path": None, "error": "端口未打开，跳过截图。"}
        if not browser_console:
            browser_console = self._browser_console(runtime_dom, screenshot)
        assertions = self._assertions(expected_texts, required_selectors, runtime_dom, diagnostics)
        quality = self._quality_report(port_open, response, html, runtime_dom, screenshot, browser_console, assertions)

        ok = quality["status"] == "pass"
        report = {
            "ok": ok,
            "conversationId": conversation_id,
            "url": url,
            "portOpen": port_open,
            "httpStatus": response.get("status"),
            "summary": quality["summary"],
            "htmlPath": str(html_path),
            "htmlTitle": self._title(html),
            "htmlBytes": len(html.encode("utf-8")),
            "runtimeDom": runtime_dom,
            "browserConsole": browser_console,
            "diagnostics": diagnostics,
            "assertions": assertions,
            "screenshot": screenshot,
            "quality": quality,
            "generatedAt": now_iso(),
        }
        report_path = root / "smoke-report.json"
        report["reportPath"] = str(report_path)
        write_json(report_path, report)
        self.events.append(
            conversation_id,
            "preview.smoke.end",
            {
                "ok": ok,
                "url": url,
                "httpStatus": report["httpStatus"],
                "htmlTitle": report["htmlTitle"],
                "htmlBytes": report["htmlBytes"],
                "htmlPath": report["htmlPath"],
                "runtimeDomOk": bool(runtime_dom.get("ok")),
                "runtimeDomPath": runtime_dom.get("path"),
                "runtimeDomBytes": runtime_dom.get("bytes"),
                "consoleErrorCount": browser_console.get("errorCount", 0),
                "consoleReliable": browser_console.get("reliable", False),
                "assertionOk": assertions.get("ok"),
                "expectedTextCount": len(expected_texts),
                "requiredSelectorCount": len(required_selectors),
                "screenshotOk": bool(screenshot.get("ok")),
                "screenshotPath": screenshot.get("path"),
                "reportPath": str(report_path),
                "summary": report["summary"],
                "quality": quality,
            },
            actor="runtime",
        )
        return report

    def screenshot_path(self, conversation_id: str) -> Path | None:
        root = conversation_root(conversation_id) / "preview"
        report = read_json(root / "smoke-report.json", None)
        if not isinstance(report, dict):
            return None
        screenshot = report.get("screenshot") if isinstance(report.get("screenshot"), dict) else {}
        path = screenshot.get("path")
        if not path:
            return None
        candidate = Path(str(path)).resolve()
        preview_root = root.resolve()
        if candidate != preview_root and preview_root not in candidate.parents:
            return None
        if not candidate.exists() or not candidate.is_file():
            return None
        return candidate

    def _wait_for_port(self, host: str, port: int, timeout_seconds: int) -> bool:
        deadline = time.time() + max(1, timeout_seconds)
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.4)
        return False

    def _fetch(self, url: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                body = response.read().decode("utf-8", errors="replace")
                status = int(response.status)
                return {"ok": status < 400, "status": status, "html": body}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": error.code, "html": body, "error": str(error)}
        except Exception as error:
            return {"ok": False, "status": 0, "html": "", "error": str(error)}

    def _screenshot(self, url: str, output_path: Path) -> dict[str, Any]:
        browser = self._browser_executable()
        if not browser:
            return {"ok": False, "path": None, "error": "未找到 Edge 或 Chrome headless 可执行文件。"}
        result = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1280,720",
                "--virtual-time-budget=3000",
                f"--screenshot={output_path}",
                url,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        ok = result.returncode == 0 and output_path.exists()
        size = output_path.stat().st_size if output_path.exists() else 0
        return {
            "ok": ok,
            "path": str(output_path) if output_path.exists() else None,
            "bytes": size,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }

    def _runtime_dom(self, url: str, output_path: Path) -> dict[str, Any]:
        browser = self._browser_executable()
        if not browser:
            return {"ok": False, "path": None, "bytes": 0, "error": "未找到 Edge 或 Chrome headless 可执行文件。"}
        result = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1280,720",
                "--virtual-time-budget=3000",
                "--dump-dom",
                url,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        dom = result.stdout or ""
        output_path.write_text(dom, encoding="utf-8")
        visible_text = self._visible_text(dom)
        ok = result.returncode == 0 and len(dom.encode("utf-8")) > 0
        return {
            "ok": ok,
            "path": str(output_path),
            "bytes": len(dom.encode("utf-8")),
            "title": self._title(dom),
            "visibleTextLength": len(visible_text),
            "visibleTextSample": visible_text[:2000],
            "stdoutTail": dom[-2000:],
            "stderr": result.stderr[-4000:],
            "error": None if ok else (result.stderr[-1000:] or "浏览器未能输出运行后 DOM。"),
        }

    def _browser_diagnostics(self, url: str, root: Path, required_selectors: list[str] | None = None) -> dict[str, Any]:
        browser = self._browser_executable()
        if not browser:
            return {"ok": False, "error": "未找到 Edge 或 Chrome headless 可执行文件。"}
        try:
            import websocket  # type: ignore[import-not-found]
        except Exception as error:
            return {"ok": False, "error": f"缺少 websocket-client，无法使用 CDP 捕获浏览器事件：{error}"}

        port = self._free_port()
        user_data_dir = Path(tempfile.mkdtemp(prefix="preview-cdp-", dir=str(root)))
        process = subprocess.Popen(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-allow-origins=*",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "about:blank",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ws = None
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        event_count = 0
        try:
            target = self._create_cdp_target(port, url)
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError("CDP 未返回页面 websocket 地址。")
            ws = websocket.create_connection(str(ws_url), timeout=2)
            command_id = 0

            def send(method: str, params: dict[str, Any] | None = None) -> int:
                nonlocal command_id
                command_id += 1
                ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
                return command_id

            for method in ("Runtime.enable", "Log.enable", "Page.enable", "Network.enable"):
                send(method)
            navigate_id = send("Page.navigate", {"url": url})
            deadline = time.time() + 8
            loaded_at: float | None = None
            while time.time() < deadline:
                try:
                    message = json.loads(ws.recv())
                except TimeoutError:
                    continue
                except Exception:
                    break
                event_count += 1
                self._collect_cdp_event(message, errors, warnings)
                if message.get("id") == navigate_id and message.get("error"):
                    raise RuntimeError(str(message["error"]))
                if message.get("method") == "Page.loadEventFired":
                    loaded_at = time.time()
                if loaded_at and time.time() - loaded_at > 1:
                    break

            selectors_json = json.dumps(required_selectors or [], ensure_ascii=False)
            expression = """
(() => ({
  title: document.title || null,
  outerHTML: document.documentElement ? document.documentElement.outerHTML : "",
  visibleText: document.body ? document.body.innerText : "",
  selectorMatches: __SELECTORS__.map((selector) => {
    try {
      const count = document.querySelectorAll(selector).length;
      return { selector, ok: count > 0, count };
    } catch (error) {
      return { selector, ok: false, count: 0, error: String(error && error.message ? error.message : error) };
    }
  })
}))()
""".replace("__SELECTORS__", selectors_json)
            evaluate_id = send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
            dom_result: dict[str, Any] = {}
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    message = json.loads(ws.recv())
                except TimeoutError:
                    continue
                except Exception:
                    break
                event_count += 1
                self._collect_cdp_event(message, errors, warnings)
                if message.get("id") == evaluate_id:
                    value = (((message.get("result") or {}).get("result") or {}).get("value") or {})
                    if isinstance(value, dict):
                        dom_result = value
                    break

            dom = str(dom_result.get("outerHTML") or "")
            runtime_dom_path = root / "runtime-dom.html"
            runtime_dom_path.write_text(dom, encoding="utf-8")
            errors = self._dedupe_diagnostics(errors)
            warnings = self._dedupe_diagnostics(warnings)
            browser_console = {
                "ok": not errors,
                "mode": "cdp",
                "reliable": True,
                "errorCount": len(errors),
                "errors": errors[:20],
                "warningCount": len(warnings),
                "warnings": warnings[:20],
                "eventCount": event_count,
                "note": "通过 Chromium DevTools Protocol 捕获 Runtime.consoleAPICalled、Runtime.exceptionThrown 和 Log.entryAdded。",
            }
            return {
                "ok": True,
                "mode": "cdp",
                "runtimeDom": {
                    "ok": bool(dom),
                    "path": str(runtime_dom_path),
                    "bytes": len(dom.encode("utf-8")),
                    "title": dom_result.get("title"),
                    "visibleTextLength": len(str(dom_result.get("visibleText") or "").strip()),
                    "visibleTextSample": str(dom_result.get("visibleText") or "").strip()[:2000],
                    "stdoutTail": dom[-2000:],
                    "stderr": "",
                    "error": None if dom else "CDP 未能读取运行后 DOM。",
                },
                "browserConsole": browser_console,
                "selectorMatches": dom_result.get("selectorMatches") if isinstance(dom_result.get("selectorMatches"), list) else [],
            }
        except Exception as error:
            return {"ok": False, "mode": "cdp", "error": str(error)}
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            shutil.rmtree(user_data_dir, ignore_errors=True)

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _create_cdp_target(self, port: int, url: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(url, safe="")
        endpoint = f"http://127.0.0.1:{port}/json/new?{encoded}"
        deadline = time.time() + 6
        last_error: Exception | None = None
        while time.time() < deadline:
            for method in ("PUT", "GET"):
                try:
                    request = urllib.request.Request(endpoint, method=method)
                    with urllib.request.urlopen(request, timeout=1) as response:
                        data = json.loads(response.read().decode("utf-8", errors="replace"))
                        if isinstance(data, dict):
                            return data
                except Exception as error:
                    last_error = error
            time.sleep(0.2)
        raise RuntimeError(f"无法创建 CDP 页面目标：{last_error}")

    def _collect_cdp_event(self, message: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
        method = message.get("method")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "Runtime.consoleAPICalled":
            kind = str(params.get("type") or "")
            text = self._console_args_text(params.get("args"))
            if kind in {"error", "assert"}:
                errors.append({"message": text or kind, "source": "Runtime.consoleAPICalled"})
            elif kind == "warning":
                warnings.append({"message": text or kind, "source": "Runtime.consoleAPICalled"})
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") if isinstance(params.get("exceptionDetails"), dict) else {}
            text = str(details.get("text") or "")
            exception = details.get("exception") if isinstance(details.get("exception"), dict) else {}
            description = str(exception.get("description") or exception.get("value") or "")
            errors.append({"message": (description or text or "Runtime exception")[:500], "source": "Runtime.exceptionThrown"})
        elif method == "Log.entryAdded":
            entry = params.get("entry") if isinstance(params.get("entry"), dict) else {}
            level = str(entry.get("level") or "")
            text = str(entry.get("text") or "")
            url = str(entry.get("url") or "")
            message = f"{text} {url}".strip()
            if self._ignorable_browser_log(message):
                warnings.append({"message": message[:500], "source": "Log.entryAdded"})
                return
            if level == "error":
                errors.append({"message": message[:500], "source": "Log.entryAdded"})
            elif level == "warning":
                warnings.append({"message": message[:500], "source": "Log.entryAdded"})

    def _console_args_text(self, args: Any) -> str:
        if not isinstance(args, list):
            return ""
        parts: list[str] = []
        for item in args:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if value is None:
                value = item.get("description")
            if value is not None:
                parts.append(str(value))
        return " ".join(parts)[:500]

    def _dedupe_diagnostics(self, items: list[dict[str, str]]) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (str(item.get("source") or ""), str(item.get("message") or ""))
            if key in seen:
                continue
            deduped.append(item)
            seen.add(key)
        return deduped

    def _ignorable_browser_log(self, text: str) -> bool:
        normalized = text.lower()
        return "favicon.ico" in normalized and ("404" in normalized or "not found" in normalized)

    def _browser_executable(self) -> Path | None:
        candidates = [
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _title(self, html: str) -> str | None:
        lower = html.lower()
        start = lower.find("<title>")
        end = lower.find("</title>")
        if start < 0 or end <= start:
            return None
        return html[start + len("<title>") : end].strip()[:200]

    def _quality_report(
        self,
        port_open: bool,
        response: dict[str, Any],
        html: str,
        runtime_dom: dict[str, Any],
        screenshot: dict[str, Any],
        browser_console: dict[str, Any],
        assertions: dict[str, Any],
    ) -> dict[str, Any]:
        html_bytes = len(html.encode("utf-8"))
        visible_text_length = len(self._visible_text(html))
        runtime_dom_bytes = int(runtime_dom.get("bytes") or 0)
        runtime_visible_text_length = int(runtime_dom.get("visibleTextLength") or 0)
        screenshot_bytes = int(screenshot.get("bytes") or 0)
        console_error_count = int(browser_console.get("errorCount") or 0)
        checks = [
            self._quality_check("port", "端口可连接", port_open, "端口未在超时时间内打开。", "port"),
            self._quality_check(
                "http",
                "HTTP 响应可用",
                bool(response.get("ok")),
                f"HTTP 状态不可用：{response.get('status') or 0}。",
                "http",
                {"status": response.get("status")},
            ),
            self._quality_check(
                "html",
                "HTML 非空",
                html_bytes > 0,
                "页面 HTML 为空，可能是服务未正常返回页面。",
                "html",
                {"htmlBytes": html_bytes, "visibleTextLength": visible_text_length},
            ),
            self._quality_check(
                "runtime-dom",
                "运行后 DOM 可读取",
                bool(runtime_dom.get("ok")) and runtime_dom_bytes > 0,
                runtime_dom.get("error") or "浏览器未能读取运行后 DOM。",
                "dom",
                {
                    "runtimeDomBytes": runtime_dom_bytes,
                    "visibleTextLength": runtime_visible_text_length,
                    "runtimeDomPath": runtime_dom.get("path"),
                },
            ),
            self._quality_check(
                "browser-console",
                "浏览器错误为空",
                console_error_count == 0,
                f"浏览器运行时发现 {console_error_count} 条疑似错误。",
                "console",
                {"errorCount": console_error_count, "errors": browser_console.get("errors", []), "mode": browser_console.get("mode")},
            ),
            self._quality_check(
                "screenshot",
                "截图已生成",
                bool(screenshot.get("ok")) and screenshot_bytes > 1000,
                screenshot.get("error") or "截图文件缺失或过小，无法作为视觉证据。",
                "screenshot",
                {"screenshotBytes": screenshot_bytes, "screenshotPath": screenshot.get("path")},
            ),
        ]
        if assertions.get("enabled"):
            checks.insert(
                -1,
                self._quality_check(
                    "assertions",
                    "验收断言通过",
                    bool(assertions.get("ok")),
                    assertions.get("summary") or "页面未满足指定的文字或选择器断言。",
                    "assertion",
                    {
                        "expectedTexts": assertions.get("expectedTexts", []),
                        "requiredSelectors": assertions.get("requiredSelectors", []),
                        "textResults": assertions.get("textResults", []),
                        "selectorResults": assertions.get("selectorResults", []),
                    },
                ),
            )
        warnings: list[dict[str, Any]] = []
        if not self._title(html):
            warnings.append({"id": "html-title", "title": "缺少页面标题", "detail": "HTML 中没有 title，建议补充页面标题便于识别。", "severity": "warning"})
        if visible_text_length < 12 and html_bytes > 0:
            warnings.append(
                {
                    "id": "visible-text",
                    "title": "可见文本较少",
                    "detail": "原始 HTML 中可见文本较少；如果是 SPA，需要结合截图或浏览器 DOM 检查继续确认。",
                    "severity": "warning",
                }
            )
        if 0 < runtime_visible_text_length < 12:
            warnings.append(
                {
                    "id": "runtime-visible-text",
                    "title": "运行后可见文本较少",
                    "detail": "浏览器运行后的 DOM 中可见文本较少，需要结合截图继续确认页面是否为空白或被遮挡。",
                    "severity": "warning",
                }
            )
        if not browser_console.get("reliable"):
            warnings.append(
                {
                    "id": "console-capture-fallback",
                    "title": "控制台采集为降级模式",
                    "detail": "CDP 控制台事件不可用，当前只检查 headless stderr 中的疑似错误。",
                    "severity": "warning",
                }
            )

        failed = [check for check in checks if not check["ok"]]
        status = "fail" if failed else "pass"
        failure_class = failed[0]["failureClass"] if failed else None
        summary = "预览 smoke test 通过，已生成 HTML、运行后 DOM、控制台和截图证据。" if not failed else f"预览 smoke test 未通过：{failed[0]['detail']}"
        return {
            "status": status,
            "summary": summary,
            "failureClass": failure_class,
            "checks": checks,
            "warnings": warnings,
        }

    def _quality_check(
        self,
        check_id: str,
        title: str,
        ok: bool,
        detail: str,
        failure_class: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": check_id,
            "title": title,
            "ok": bool(ok),
            "detail": "通过。" if ok else detail,
            "failureClass": None if ok else failure_class,
            "evidence": evidence or {},
        }

    def _visible_text(self, html: str) -> str:
        without_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
        return " ".join(without_tags.split())

    def _assertions(
        self,
        expected_texts: list[str],
        required_selectors: list[str],
        runtime_dom: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        visible_text = str(runtime_dom.get("visibleTextSample") or "")
        dom_tail = str(runtime_dom.get("stdoutTail") or "")
        text_results = [
            {
                "text": text,
                "ok": text in visible_text or text in dom_tail,
                "detail": "已在运行后页面中找到。" if text in visible_text or text in dom_tail else "运行后页面中未找到该文字。",
            }
            for text in expected_texts
        ]

        selector_map: dict[str, dict[str, Any]] = {}
        for item in diagnostics.get("selectorMatches", []) if isinstance(diagnostics.get("selectorMatches"), list) else []:
            if isinstance(item, dict):
                selector_map[str(item.get("selector") or "")] = item

        selector_results = []
        for selector in required_selectors:
            match = selector_map.get(selector)
            if match:
                selector_results.append(
                    {
                        "selector": selector,
                        "ok": bool(match.get("ok")),
                        "count": int(match.get("count") or 0),
                        "detail": "已找到匹配元素。" if match.get("ok") else str(match.get("error") or "未找到匹配元素。"),
                    }
                )
            else:
                selector_results.append(
                    {
                        "selector": selector,
                        "ok": False,
                        "count": 0,
                        "detail": "当前浏览器诊断没有返回 selector 检查结果，可能是 CDP 不可用。",
                    }
                )

        enabled = bool(expected_texts or required_selectors)
        failed_count = sum(1 for item in [*text_results, *selector_results] if not item["ok"])
        ok = failed_count == 0
        summary = (
            "未配置页面验收断言。"
            if not enabled
            else ("页面验收断言全部通过。" if ok else f"页面验收断言未通过：{failed_count} 项失败。")
        )
        return {
            "enabled": enabled,
            "ok": ok,
            "summary": summary,
            "expectedTexts": expected_texts,
            "requiredSelectors": required_selectors,
            "textResults": text_results,
            "selectorResults": selector_results,
        }

    def _clean_string_list(self, values: list[str] | None, limit: int = 12) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            cleaned.append(text[:300])
            seen.add(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _browser_console(self, runtime_dom: dict[str, Any], screenshot: dict[str, Any]) -> dict[str, Any]:
        stderr = "\n".join(
            str(item.get("stderr") or "")
            for item in (runtime_dom, screenshot)
            if isinstance(item, dict)
        )
        errors: list[dict[str, str]] = []
        markers = ["uncaught", "typeerror", "referenceerror", "syntaxerror", "console.error", "severe", "failed to load resource"]
        for line in stderr.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            lower = normalized.lower()
            if any(marker in lower for marker in markers):
                errors.append({"message": normalized[:500]})
            if len(errors) >= 20:
                break
        return {
            "ok": not errors,
            "mode": "headless-stderr",
            "reliable": False,
            "errorCount": len(errors),
            "errors": errors,
            "note": "CDP 不可用时的降级采集：只检查 Chromium headless stderr 中的疑似错误。",
        }
