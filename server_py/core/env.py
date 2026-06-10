from __future__ import annotations

import os
from pathlib import Path

from server_py.core.paths import PROJECT_ROOT

_loaded = False


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """加载项目根目录 .env 到进程环境变量。

    .env 的值优先于继承的系统环境变量——演示机上曾有残留的旧
    ARK_API_KEY 用户级变量覆盖了比赛下发的 key，导致"API 不可用"。
    项目内 .env 必须是唯一事实来源。重复调用是幂等的。
    """
    global _loaded
    target = path or (PROJECT_ROOT / ".env")
    loaded: dict[str, str] = {}
    if _loaded and path is None:
        return loaded
    _loaded = True
    if not target.exists():
        return loaded
    try:
        raw = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return loaded
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded
