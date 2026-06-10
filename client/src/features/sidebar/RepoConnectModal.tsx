import { FolderGit2, Github, X } from "lucide-react";
import type { RepositoryStatus, SandboxStatus } from "@workbench/shared";

interface RepoConnectModalProps {
  open: boolean;
  localPath: string;
  githubUrl: string;
  repository: RepositoryStatus | null;
  sandbox: SandboxStatus | null;
  isRunning: boolean;
  onLocalPathChange: (value: string) => void;
  onGithubUrlChange: (value: string) => void;
  onConnectLocal: () => void;
  onConnectGithub: () => void;
  onClose: () => void;
}

/**
 * 新建对话时弹出的仓库接入选择。
 * 接入仓库是开发交付的前置条件,放在对话起点而不是侧栏角落;
 * 用户也可以「稍后再说」——提问不需要仓库。
 */
export function RepoConnectModal({
  open,
  localPath,
  githubUrl,
  repository,
  sandbox,
  isRunning,
  onLocalPathChange,
  onGithubUrlChange,
  onConnectLocal,
  onConnectGithub,
  onClose,
}: RepoConnectModalProps) {
  if (!open) return null;

  return (
    <div className="confirmOverlay" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="repoDialog" onClick={(event) => event.stopPropagation()}>
        <div className="repoDialogHeader">
          <strong>接入要修改的项目</strong>
          <button type="button" className="iconButton" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        <p className="repoDialogIntro">
          系统会把项目<strong>复制一份</strong>到本次对话的隔离沙盒里修改，你的原始项目不会被改动。
        </p>

        <div className="repoOption">
          <div className="repoOptionTitle">
            <Github size={16} />
            从 GitHub 拉取
          </div>
          <div className="repoOptionRow">
            <input
              value={githubUrl}
              onChange={(event) => onGithubUrlChange(event.target.value)}
              placeholder="https://github.com/用户名/仓库名"
              aria-label="GitHub 仓库地址"
            />
            <button type="button" disabled={isRunning || !githubUrl.trim()} onClick={onConnectGithub}>
              {isRunning ? "拉取中..." : "拉取"}
            </button>
          </div>
        </div>

        <div className="repoOption">
          <div className="repoOptionTitle">
            <FolderGit2 size={16} />
            用电脑上的本地项目
          </div>
          <div className="repoOptionRow">
            <input
              value={localPath}
              onChange={(event) => onLocalPathChange(event.target.value)}
              placeholder="C:\path\to\项目文件夹"
              aria-label="本地项目路径"
            />
            <button type="button" disabled={isRunning || !localPath.trim()} onClick={onConnectLocal}>
              {isRunning ? "接入中..." : "接入"}
            </button>
          </div>
        </div>

        {repository && sandbox && (
          <p className="repoDialogCurrent">
            当前已接入：{repository.source.split(/[\\/]/).pop()}（分支 {repository.branch ?? "未知"}）。再次接入会替换当前沙盒。
          </p>
        )}

        <div className="repoDialogFooter">
          <button type="button" className="linkLikeButton" onClick={onClose}>
            稍后再说（提问不需要仓库）
          </button>
        </div>
      </div>
    </div>
  );
}
