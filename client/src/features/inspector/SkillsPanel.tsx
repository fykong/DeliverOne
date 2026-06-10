import { useState } from "react";
import { BookOpen } from "lucide-react";
import type { SkillSummary } from "@workbench/shared";

const kindLabels: Record<string, string> = {
  process: "流程",
  "requirement-pattern": "需求模式",
  "repo-profile": "仓库画像",
};

/**
 * 技能列表:按 Claude Code 的渐进披露惯例,常驻只看名称+一句话说明,
 * 点开才看细节。技能 = catalog/<id>/SKILL.md,放文件即生效(热加载)。
 */
export function SkillsPanel({ skills }: { skills: SkillSummary[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section className="panel">
      <h3>
        <BookOpen size={16} />
        技能（Skills）
        <small>{skills.length} 个</small>
      </h3>
      <p className="panelHint">
        技能是教 Agent 做某类事的方法论文件（澄清要问什么、去哪定位、改完怎么验收）。新建
        catalog/&lt;名字&gt;/SKILL.md 即自动生效，无需重启。
      </p>
      <div className="skillList">
        {skills.map((skill) => (
          <div className="skillRow" key={skill.id}>
            <button
              type="button"
              className="skillHeader"
              onClick={() => setOpenId(openId === skill.id ? null : skill.id)}
              aria-expanded={openId === skill.id}
            >
              <strong>{skill.name}</strong>
              <span className="skillBadges">
                {skill.alwaysOn ? <em className="skillBadge always">常驻</em> : null}
                <em className="skillBadge">{kindLabels[skill.kind ?? ""] ?? skill.kind ?? "技能"}</em>
              </span>
            </button>
            {openId === skill.id && (
              <div className="skillDetail">
                <p>{skill.description}</p>
                {skill.triggers?.length ? <small>触发词：{skill.triggers.slice(0, 10).join("、")}</small> : null}
              </div>
            )}
          </div>
        ))}
        {skills.length === 0 && <p>还没有加载任何技能。</p>}
      </div>
    </section>
  );
}
