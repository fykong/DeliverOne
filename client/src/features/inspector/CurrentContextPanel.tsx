import { CheckCircle2, ShieldCheck } from "lucide-react";
import type { AgentTurnResult, PreflightResult, RepositoryStatus, SandboxStatus, SkillSummary } from "@workbench/shared";
import { phaseLabels } from "./constants";

interface CurrentContextPanelProps {
  preflight: PreflightResult | null;
  repository: RepositoryStatus | null;
  sandbox: SandboxStatus | null;
  agentTurn: AgentTurnResult | null;
  skills: SkillSummary[];
  isRunning: boolean;
  onConfirmPlan: () => void;
}

export function CurrentContextPanel({ preflight, repository, sandbox, agentTurn, skills, isRunning, onConfirmPlan }: CurrentContextPanelProps) {
  const canConfirmPlan = agentTurn?.phase === "waiting_plan_confirmation";
  const repo = preflight?.repository ?? repository;
  const box = preflight?.sandbox ?? sandbox;
  const currentPhase = agentTurn ? phaseLabels[agentTurn.phase] : repo ? "仓库已接入" : "等待仓库";

  return (
    <section className="panel">
      <h3>
        <ShieldCheck size={16} />
        当前上下文
      </h3>
      <dl className="factList">
        <div>
          <dt>阶段</dt>
          <dd>{currentPhase}</dd>
        </div>
        <div>
          <dt>仓库</dt>
          <dd>{repo?.sourceType === "github" ? "GitHub" : repo ? "本地" : "未接入"}</dd>
        </div>
        <div>
          <dt>沙盒</dt>
          <dd>{box?.id ?? "未创建"}</dd>
        </div>
        <div>
          <dt>Skill</dt>
          <dd>{preflight?.matchedSkills.length ?? skills.length} 个</dd>
        </div>
      </dl>
      {canConfirmPlan && (
        <button className="inspectorButton" type="button" disabled={isRunning} onClick={onConfirmPlan}>
          <CheckCircle2 size={16} />
          确认方案并生成工具计划
        </button>
      )}
    </section>
  );
}
