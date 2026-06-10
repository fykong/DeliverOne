from __future__ import annotations

import os
import subprocess
import sys
from typing import Any


def run_sandbox_command(command: str, cwd: str, timeout_seconds: int) -> dict[str, Any]:
    """非交互地在沙盒里运行 shell 命令,超时杀整棵进程树。

    - CI=true:vitest/jest 等测试器的 watch 模式会改为单次运行;
      否则 `npm test` 在沙盒里永远不退出,整条执行链挂死。
    - shell=True 下超时直接 kill 只杀外层 shell;Windows 上孙进程
      (vite/vitest)拿着 stdout/stderr 管道不放,communicate() 会
      永远阻塞,所以必须用 taskkill /T(POSIX 用 killpg)杀整棵树。
    """
    env = {**os.environ, "CI": "true", "FORCE_COLOR": "0", "NO_COLOR": "1"}
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=(sys.platform != "win32"),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=max(1, timeout_seconds))
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except Exception:
            stdout, stderr = "", ""
    exit_code = proc.returncode if proc.returncode is not None else 124
    return {
        "exitCode": None if timed_out else exit_code,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "timedOut": timed_out,
    }


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
