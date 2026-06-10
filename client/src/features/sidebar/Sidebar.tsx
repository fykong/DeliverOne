import { Bot, FolderGit2, Github, Plus, RotateCcw } from "lucide-react";
import type { AgentConversationSummary, RepositoryStatus } from "@workbench/shared";

interface SidebarProps {
  conversations: AgentConversationSummary[];
  activeConversationId: string;
  localPath: string;
  githubUrl: string;
  repository: RepositoryStatus | null;
  isRunning: boolean;
  onLocalPathChange: (value: string) => void;
  onGithubUrlChange: (value: string) => void;
  onConnectLocal: () => void;
  onConnectGithub: () => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
}

export function Sidebar({
  conversations,
  activeConversationId,
  localPath,
  githubUrl,
  repository,
  isRunning,
  onLocalPathChange,
  onGithubUrlChange,
  onConnectLocal,
  onConnectGithub,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation
}: SidebarProps) {
  const visibleConversations = conversations.filter((item) => item.conversationId === activeConversationId || !isInternalConversation(item));
  const hiddenCount = conversations.length - visibleConversations.length;

  return (
    <aside className="sidebar">
      <div className="brand">
        <Bot size={22} />
        <span>Agent 工作台</span>
      </div>

      <button className="newButton" type="button" onClick={onNewConversation} disabled={isRunning}>
        <Plus size={18} />
        新建对话
      </button>

      <section className="sideSection">
        <div className="sideTitle">仓库</div>
        <label className="sideField">
          <span>本地路径</span>
          <input value={localPath} onChange={(event) => onLocalPathChange(event.target.value)} placeholder="C:\\path\\to\\repo" />
        </label>
        <button className="sideAction" type="button" onClick={onConnectLocal} disabled={isRunning || !localPath.trim()}>
          <FolderGit2 size={16} />
          接入本地仓库
        </button>

        <label className="sideField">
          <span>GitHub</span>
          <input value={githubUrl} onChange={(event) => onGithubUrlChange(event.target.value)} placeholder="https://github.com/..." />
        </label>
        <button className="sideAction" type="button" onClick={onConnectGithub} disabled={isRunning || !githubUrl.trim()}>
          <Github size={16} />
          拉取到沙盒
        </button>

        {repository && (
          <div className="repoStatus">
            <strong>{repository.sourceType === "github" ? "GitHub 仓库" : "本地仓库"}</strong>
            <span>{repository.branch ?? "未识别分支"}</span>
            <small>{Object.keys(repository.scripts).length} 个 scripts</small>
          </div>
        )}
      </section>

      <section className="sideSection historySection">
        <div className="sideTitle">
          <span>历史对话</span>
          {hiddenCount > 0 && <small>已隐藏 {hiddenCount} 条测试记录</small>}
        </div>
        {visibleConversations.map((item) => (
          <div className={`threadRow ${item.conversationId === activeConversationId ? "active" : ""}`} key={item.conversationId}>
            <button className="threadItem" type="button" onClick={() => onSelectConversation(item.conversationId)}>
              <span>{item.title}</span>
              <small>{item.phase}</small>
            </button>
            <button className="threadDelete" type="button" onClick={() => onDeleteConversation(item.conversationId)} disabled={isRunning} aria-label="删除对话">
              ×
            </button>
          </div>
        ))}
      </section>

      <div className="sideHint">
        <RotateCcw size={15} />
        所有写入先进入当前对话沙盒，确认后再交付。
      </div>
    </aside>
  );
}

function isInternalConversation(item: AgentConversationSummary) {
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
