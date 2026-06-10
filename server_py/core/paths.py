from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
CONFIG_ROOT = PROJECT_ROOT / "config"
MODEL_PROVIDERS_PATH = CONFIG_ROOT / "model-providers.json"
MODEL_SETTINGS_PATH = CONFIG_ROOT / "model-settings.json"
AGENT_POLICY_PATH = CONFIG_ROOT / "agent-policy.json"
AGENT_SKILLS_PATH = CONFIG_ROOT / "agent-skills.json"


def safe_conversation_id(conversation_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", conversation_id)[:80]
    return safe or "conversation"


def conversation_root(conversation_id: str) -> Path:
    return WORKSPACE_ROOT / "conversations" / safe_conversation_id(conversation_id)
