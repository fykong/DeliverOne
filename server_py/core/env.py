from __future__ import annotations

import os
from pathlib import Path

from server_py.core.paths import PROJECT_ROOT

_loaded = False


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """加载项目根目录 .env 到进程环境变量（不覆盖已存在的变量）。

    让用户拿到 ARK_API_KEY 后只需要在 .env 写一行即可，
    不依赖系统级环境变量配置。重复调用是幂等的。
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
        if key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
