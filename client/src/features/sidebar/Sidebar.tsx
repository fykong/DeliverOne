import { useState } from "react";
import { Bot, PanelLeftClose, PanelLeftOpen, Plus, Trash2 } from "lucide-react";
import type { AgentConversationSummary } from "@workbench/shared";
import { phaseLabels } from "../inspector/constants";

interface SidebarProps {
  conversations: AgentConversationSummary[];
  activeConversationId: string;
  isRunning: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
  onCleanup?: () => void;
}

export function Sidebar({
  conversations,
  activeConversationId,
  isRunning,
  collapsed,
  onToggleCollapsed,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
  onCleanup
}: SidebarProps) {
  const [showHidden, setShowHidden] = useState(false);
  const visibleConversations = conversations.filter(
    (item) => showHidden || item.conversationId === activeConversationId || !isInternalConversation(item)
  );
  const hiddenCount = conversations.length - visibleConversations.length;

  if (collapsed) {
    return (
      <aside className="sidebar collapsed">
        <button className="iconRailButton" type="button" onClick={onToggleCollapsed} title="展开侧栏" aria-label="展开侧栏">
          <PanelLeftOpen size={18} />
        </button>
        <button className="iconRailButton" type="button" onClick={onNewConversation} disabled={isRunning} title="新建对话" aria-label="新建对话">
          <Plus size={18} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <Bot size={18} />
        <span>DeliverOne</span>
        <button className="iconRailButton brandCollapse" type="button" onClick={onToggleCollapsed} title="收起侧栏" aria-label="收起侧栏">
          <PanelLeftClose size={16} />
        </button>
      </div>

      <button className="newButton" type="button" onClick={onNewConversation} disabled={isRunning}>
        <Plus size={16} />
        新建对话
      </button>

      <section className="sideSection historySection">
        <div className="sideTitle">
          <span>历史对话</span>
          {hiddenCount > 0 && (
            <button type="button" className="linkButton" onClick={() => setShowHidden((value) => !value)}>
              {showHidden ? "收起开发记录" : `+${hiddenCount} 条开发记录`}
            </button>
          )}
          {onCleanup && (
            <button type="button" className="linkButton" onClick={onCleanup} disabled={isRunning} title="删除残留的空会话目录,释放磁盘">
              <Trash2 size={12} />
              清理
            </button>
          )}
        </div>
        {visibleConversations.map((item) => (
          <div className={`threadRow ${item.conversationId === activeConversationId ? "active" : ""}`} key={item.conversationId}>
            <button className="threadItem" type="button" onClick={() => onSelectConversation(item.conversationId)}>
              <span>{item.title}</span>
              <small>{phaseLabels[item.phase] ?? item.phase}</small>
            </button>
            <button className="threadDelete" type="button" onClick={() => onDeleteConversation(item.conversationId)} disabled={isRunning} aria-label="删除对话">
              ×
            </button>
          </div>
        ))}
        {visibleConversations.length === 0 && <p className="sideEmpty">还没有对话。</p>}
      </section>
    </aside>
  );
}

function isInternalConversation(item: AgentConversationSummary) {
  // 后端显式标记优先;旧会话回退到关键词启发式(仅作兼容,不再扩大)。
  if (item.internal) return true;
  const title = item.title.trim().toLowerCase();
  const value = `${item.conversationId} ${title}`.toLowerCase();
  return (
    value.includes("smoke") ||
    value.includes("tool-plan") ||
    value.includes("state-machine") ||
    value.includes("file-browser") ||
    value.includes("patch-smoke") ||
    value.includes("ai-delivery-") ||
    title === "repo" ||
    title === "source" ||
    /\?{3,}/.test(value)
  );
}
