import { Settings, ShieldCheck } from "lucide-react";
import type { ModelSettings } from "@workbench/shared";

interface TopbarProps {
  models: ModelSettings | null;
  modelName: string;
  phaseLabel: string;
  onModelChange: (modelId: string) => void;
}

export function Topbar({ models, modelName, phaseLabel, onModelChange }: TopbarProps) {
  const visibleModels = models?.models ?? [];
  const canSwitchModel = visibleModels.length > 1;

  return (
    <header className="topbar">
      <div>
        <div className="muted">当前任务</div>
        <h1>需求到代码交付</h1>
      </div>

      <div className="topActions">
        {canSwitchModel ? (
          <label className="modelSelect">
            <Settings size={16} />
            <select
              value={models?.defaultModelId ?? ""}
              onChange={(event) => onModelChange(event.target.value)}
              aria-label="选择模型"
              disabled={!models}
            >
              {visibleModels.map((model) => (
                <option key={model.id} value={model.id} disabled={!model.enabled}>
                  {model.displayName}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="modelSelect static" title={modelName}>
            <Settings size={16} />
            {modelName}
          </span>
        )}
        <span className="statePill" title={modelName}>
          <ShieldCheck size={16} />
          {phaseLabel}
        </span>
      </div>
    </header>
  );
}
