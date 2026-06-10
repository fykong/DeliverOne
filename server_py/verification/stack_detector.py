from __future__ import annotations

from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json


class StackDetector:
    def recommend_for_path(self, repo_path: str) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        package = read_json(repo / "package.json", {})
        scripts = package.get("scripts", {}) if isinstance(package, dict) and isinstance(package.get("scripts"), dict) else {}
        dependencies = self._dependencies(package)
        verification = self._verification_recommendations(scripts, repo)
        preview = self._preview_recommendations(scripts, dependencies)
        return {
            "verification": {
                "primary": verification[0] if verification else None,
                "all": verification,
                "commands": {item["phase"]: item["command"] for item in verification},
            },
            "preview": {
                "primary": preview[0] if preview else None,
                "all": preview,
            },
            "source": {
                "packageJson": str(repo / "package.json") if (repo / "package.json").exists() else None,
                "pyproject": str(repo / "pyproject.toml") if (repo / "pyproject.toml").exists() else None,
                "generatedAt": now_iso(),
            },
        }

    def select_commands(self, repository: dict[str, Any]) -> dict[str, str]:
        scripts = repository.get("scripts", {})
        return {item["phase"]: item["command"] for item in self._verification_recommendations(scripts, None)}

    def select_commands_for_path(self, repo_path: str) -> dict[str, str]:
        repo = Path(repo_path).resolve()
        recommendations = self.recommend_for_path(str(repo))
        commands = recommendations["verification"]["commands"]

        if not commands and (repo / "pyproject.toml").exists():
            if (repo / "tests").exists():
                commands["tests"] = "pytest"
            commands["lint"] = "ruff check ."
        return commands

    def _verification_recommendations(self, scripts: dict[str, Any], repo: Path | None) -> list[dict[str, Any]]:
        if not isinstance(scripts, dict):
            scripts = {}
        recommendations: list[dict[str, Any]] = []
        for phase, script_name, command, reason, confidence in [
            ("typecheck", "typecheck", "npm run typecheck", "发现 typecheck 脚本，优先验证类型边界。", 0.95),
            ("lint", "lint", "npm run lint", "发现 lint 脚本，用于检查代码风格和静态错误。", 0.88),
            ("tests", "test", self._test_command(scripts), "发现 test 脚本，用于验证行为是否回归。", 0.84),
            ("build", "build", "npm run build", "发现 build 脚本，用于确认前端或全栈产物可构建。", 0.8),
        ]:
            if script_name in scripts:
                recommendations.append(
                    self._recommendation(
                        kind="verification",
                        phase=phase,
                        command=command,
                        source=f"package.json scripts.{script_name}",
                        reason=reason,
                        confidence=confidence,
                        script_name=script_name,
                    )
                )
        if not recommendations and repo and (repo / "pyproject.toml").exists():
            if (repo / "tests").exists():
                recommendations.append(
                    self._recommendation("verification", "tests", "pytest", "pyproject.toml + tests/", "发现 Python 测试目录，推荐运行 pytest。", 0.78)
                )
            recommendations.append(
                self._recommendation("verification", "lint", "ruff check .", "pyproject.toml", "发现 Python 项目，推荐运行 ruff 做静态检查。", 0.65)
            )
        return recommendations

    def _test_command(self, scripts: dict[str, Any]) -> str:
        # vitest 默认进入 watch 模式,在非交互沙盒里会挂死直到超时;强制单次运行。
        script = str(scripts.get("test") or "").lower()
        if "vitest" in script and "--run" not in script and "vitest run" not in script:
            return "npm test -- --run"
        return "npm test"

    def _preview_recommendations(self, scripts: dict[str, Any], dependencies: set[str]) -> list[dict[str, Any]]:
        if not isinstance(scripts, dict):
            scripts = {}
        candidates: list[dict[str, Any]] = []
        if "dev" in scripts:
            script = str(scripts.get("dev") or "").lower()
            if "vite" in script or "vite" in dependencies:
                candidates.append(
                    self._recommendation(
                        "preview",
                        "dev",
                        "npm run dev -- --host 127.0.0.1 --port 5173",
                        "package.json scripts.dev",
                        "发现 Vite dev 脚本，推荐绑定本机地址和固定端口，便于 smoke test 与 iframe 预览。",
                        0.94,
                        script_name="dev",
                        ports=[5173],
                    )
                )
            elif "next" in script or "next" in dependencies:
                candidates.append(
                    self._recommendation(
                        "preview",
                        "dev",
                        "npm run dev -- --hostname 127.0.0.1 --port 3000",
                        "package.json scripts.dev",
                        "发现 Next.js dev 脚本，推荐绑定本机地址和固定端口。",
                        0.9,
                        script_name="dev",
                        ports=[3000],
                    )
                )
            else:
                candidates.append(
                    self._recommendation(
                        "preview",
                        "dev",
                        "npm run dev",
                        "package.json scripts.dev",
                        "发现 dev 脚本，适合作为第一预览命令。",
                        0.78,
                        script_name="dev",
                        ports=[3000],
                    )
                )
        if "start" in scripts:
            candidates.append(
                self._recommendation(
                    "preview",
                    "start",
                    "npm start",
                    "package.json scripts.start",
                    "发现 start 脚本，可作为构建后或传统项目预览命令。",
                    0.62,
                    script_name="start",
                    ports=[3000],
                )
            )
        if "preview" in scripts:
            candidates.append(
                self._recommendation(
                    "preview",
                    "preview",
                    "npm run preview -- --host 127.0.0.1",
                    "package.json scripts.preview",
                    "发现 preview 脚本，适合构建后预览，但通常需要先完成 build。",
                    0.58,
                    script_name="preview",
                    ports=[4173],
                )
            )
        return sorted(candidates, key=lambda item: item["confidence"], reverse=True)

    def _dependencies(self, package: dict[str, Any]) -> set[str]:
        names: set[str] = set()
        if not isinstance(package, dict):
            return names
        for key in ["dependencies", "devDependencies", "peerDependencies"]:
            values = package.get(key)
            if isinstance(values, dict):
                names.update(str(name).lower() for name in values)
        return names

    def _recommendation(
        self,
        kind: str,
        phase: str,
        command: str,
        source: str,
        reason: str,
        confidence: float,
        script_name: str | None = None,
        ports: list[int] | None = None,
    ) -> dict[str, Any]:
        item = {
            "kind": kind,
            "phase": phase,
            "command": command,
            "source": source,
            "reason": reason,
            "confidence": round(confidence, 3),
        }
        if script_name:
            item["scriptName"] = script_name
        if ports:
            item["ports"] = ports
        return item

    def empty_report(self) -> dict[str, Any]:
        return {
            "build": "skipped",
            "typecheck": "skipped",
            "lint": "skipped",
            "tests": "skipped",
            "preview": "skipped",
            "changedFiles": 0,
            "rollbackAvailable": False,
            "generatedAt": now_iso(),
        }
