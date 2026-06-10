from __future__ import annotations

import os
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import MODEL_PROVIDERS_PATH, MODEL_SETTINGS_PATH


class ModelConfigService:
    def get_settings(self) -> dict[str, Any]:
        catalog = read_json(MODEL_PROVIDERS_PATH, {"defaultModelId": "doubao-seed-2-lite", "models": []})
        settings = read_json(
            MODEL_SETTINGS_PATH,
            {"defaultModelId": catalog.get("defaultModelId", "doubao-seed-2-lite"), "updatedAt": now_iso()},
        )
        models = [self._with_availability(model) for model in catalog.get("models", [])]
        known_ids = {model.get("id") for model in models}
        requested_default_id = settings.get("defaultModelId") or catalog.get("defaultModelId")
        default_model_id = requested_default_id if requested_default_id in known_ids else catalog.get("defaultModelId")
        if default_model_id not in known_ids and models:
            default_model_id = models[0]["id"]
        return {"defaultModelId": default_model_id, "models": models, "updatedAt": settings.get("updatedAt", now_iso())}

    def save_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        catalog = read_json(MODEL_PROVIDERS_PATH, {"defaultModelId": "doubao-seed-2-lite", "models": []})
        known_ids = {model.get("id") for model in catalog.get("models", [])}
        default_model_id = value.get("defaultModelId")
        if default_model_id not in known_ids:
            default_model_id = catalog.get("defaultModelId")
        payload = {"defaultModelId": default_model_id, "updatedAt": now_iso()}
        write_json(MODEL_SETTINGS_PATH, payload)
        return self.get_settings()

    def get_default_model(self) -> dict[str, Any]:
        settings = self.get_settings()
        default_model_id = settings["defaultModelId"]
        for model in settings["models"]:
            if model["id"] == default_model_id:
                return model
        return settings["models"][0] if settings["models"] else self._fallback_model()

    def _with_availability(self, model: dict[str, Any]) -> dict[str, Any]:
        result = dict(model)
        provider = result.get("provider")
        api_key_env = result.get("apiKeyEnv")
        if provider == "ark" and api_key_env and not os.environ.get(api_key_env):
            result["enabled"] = False
            result["unavailableReason"] = f"缺少环境变量 {api_key_env}"
        else:
            result["enabled"] = True
            result.pop("unavailableReason", None)
        return result

    def _fallback_model(self) -> dict[str, Any]:
        return {
            "id": "doubao-seed-2-lite",
            "displayName": "Doubao Seed 2.0 Lite",
            "provider": "ark",
            "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            "model": "EP_ID_REDACTED",
            "apiKeyEnv": "ARK_API_KEY",
            "modelEnv": "ARK_MODEL",
            "enabled": bool(os.environ.get("ARK_API_KEY")),
            "unavailableReason": None if os.environ.get("ARK_API_KEY") else "缺少环境变量 ARK_API_KEY",
        }
