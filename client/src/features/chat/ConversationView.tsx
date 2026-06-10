import { useEffect, useRef } from "react";
import { FolderGit2, Loader2, Send } from "lucide-react";
import type { RepositoryStatus, SandboxStatus, SearchIntentSnapshot, TaskLedgerSnapshot } from "@workbench/shared";
import { MarkdownPreview } from "../inspector/MarkdownPreview";
import type { ConversationMessage } from "./types";

interface ConversationViewProps {
  messages: ConversationMessage[];
  requirement: string;
  searchIntent: SearchIntentSnapshot | null;
  taskLedger: TaskLedgerSnapshot | null;
  isRunning: boolean;
  executionStatus: string | null;
  repository: RepositoryStatus | null;
  sandbox: SandboxStatus | null;
  autopilotEnabled: boolean;
  onAutopilotChange: (value: boolean) => void;
  onRequirementChange: (value: string) => void;
  onRunAgent: () => void;
  onOpenRepoModal: () => void;
}

export function ConversationView({
  messages,
  requirement,
  searchIntent,
  taskLedger,
  isRunning,
  executionStatus,
  repository,
  sandbox,
  autopilotEnabled,
  onAutopilotChange,
  onRequirementChange,
  onRunAgent,
  onOpenRepoModal,
}: ConversationViewProps) {
  const visibleMessages = messages.filter((message) => !isModelSwitchNotice(message.text));
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLElement>(null);
  const repoName = repository?.source.split(/[\\/]/).pop() ?? null;

  // 新消息追加时自动滚到底,但用户已手动上滚查看历史时不打扰。
  useEffect(() => {
    const container = messagesRef.current;
    if (!container) return;
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 160;
    if (nearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages.length, executionStatus]);

  return (
    <>
      <section className="messages" ref={messagesRef}>
        <TaskLedgerStrip taskLedger={taskLedger} searchIntent={searchIntent} />
        {visibleMessages.map((message, index) => (
          <article className={`message ${message.role === "你" ? "user" : message.role === "系统" ? "system" : "agent"}`} key={`${message.role}-${index}`}>
            <div className="messageRole">{message.role}</div>
            {message.role === "你" ? (
              <div className="messageText">{message.text}</div>
            ) : (
              <div className="messageText messageMarkdown">
                <MarkdownPreview content={message.text} />
              </div>
            )}
            {message.questions?.length ? (
              <div className="clarifyBlock" aria-label="澄清问题">
                <strong>澄清问题</strong>
                <ol>
                  {message.questions.map((question, questionIndex) => (
                    <li key={`${questionIndex}-${question.slice(0, 12)}`}>{question}</li>
                  ))}
                </ol>
              </div>
            ) : null}
            {message.meta && <div className="messageMeta">{message.meta}</div>}
          </article>
        ))}
        <div ref={bottomRef} />
      </section>

      {executionStatus && (
        <div className="executionStatus" role="status" aria-live="polite">
          <Loader2 size={14} className="executionStatusIcon" />
          <span>{executionStatus}</span>
        </div>
      )}

      <footer className="composer">
        <textarea
          value={requirement}
          onChange={(event) => onRequirementChange(event.target.value)}
          onKeyDown={(event) => {
            // 中文输入法组词时的 Enter 是选字,绝不能触发发送。
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!isRunning && requirement.trim()) onRunAgent();
            }
          }}
          aria-label="输入需求或提问"
          placeholder={sandbox ? "描述需求或直接提问，我会自动判断…（Enter 发送，Shift+Enter 换行）" : "可以先提问；要改代码请先接入仓库…（Enter 发送）"}
        />
        <div className="composerToggle">
          <label>
            <input
              type="checkbox"
              checked={autopilotEnabled}
              disabled={isRunning}
              onChange={(event) => onAutopilotChange(event.target.checked)}
              aria-label="托管模式"
            />
            托管模式
          </label>
          <small>自动确认方案与工具计划，直达提测；澄清问题与高危操作仍会停下</small>
        </div>
        <div className="composerActions">
          <span className="repoLine">
            <FolderGit2 size={13} />
            {sandbox && repoName ? (
              <>
                沙盒就绪：{repoName}
                {repository?.branch ? ` · ${repository.branch}` : ""}
                <button type="button" className="linkLikeButton" onClick={onOpenRepoModal} disabled={isRunning}>
                  更换仓库
                </button>
              </>
            ) : (
              <>
                未接入仓库——提问可直接发，改代码请先
                <button type="button" className="linkLikeButton" onClick={onOpenRepoModal} disabled={isRunning}>
                  接入仓库
                </button>
              </>
            )}
          </span>
          <button onClick={onRunAgent} className="primary" type="button" disabled={isRunning || !requirement.trim()}>
            <Send size={16} />
            {isRunning ? "处理中" : "发送"}
          </button>
        </div>
      </footer>
    </>
  );
}

function TaskLedgerStrip({
  taskLedger,
  searchIntent,
}: {
  taskLedger: TaskLedgerSnapshot | null;
  searchIntent: SearchIntentSnapshot | null;
}) {
  const understanding = (taskLedger?.currentUnderstanding || searchIntent?.summary || "").trim();
  // 没有真实任务理解时整块隐藏——"尚未形成/等待"之类的占位文案对用户是噪音,
  // 还会带出"先接入仓库"等可能已过期的下一步提示。
  if (!understanding || understanding.startsWith("尚未") || understanding.startsWith("等待")) {
    return null;
  }

  const intent = taskLedger?.searchIntent;
  const queries = firstValues(intent?.searchQueries, searchIntent?.searchQueries, 3);
  const files = firstValues(intent?.fileHints, searchIntent?.fileHints, 3);
  const nextSteps = firstValues(taskLedger?.nextSteps, undefined, 3);
  const phases = (taskLedger?.phases ?? []).slice(0, 7);
  const rawSource = intent?.source || searchIntent?.source || "rules";
  const confidence = intent?.confidence ?? searchIntent?.confidence;
  // 只有模型分析才值得标注置信度;内部的规则回退对用户没有意义,不展示来源。
  const confidenceLabel =
    rawSource === "model" && typeof confidence === "number" ? `模型理解 · ${Math.round(confidence * 100)}%` : null;

  return (
    <aside className="taskLedgerStrip" aria-label="任务理解">
      <div>
        <span>当前理解{confidenceLabel ? <em className="ledgerConfidence">{confidenceLabel}</em> : null}</span>
        <strong>{understanding}</strong>
      </div>
      {(queries.length > 0 || files.length > 0 || nextSteps.length > 0) && (
        <dl>
          {queries.length > 0 && (
            <div>
              <dt>检索</dt>
              <dd>{queries.join("；")}</dd>
            </div>
          )}
          {files.length > 0 && (
            <div>
              <dt>文件</dt>
              <dd>{files.join("；")}</dd>
            </div>
          )}
          {nextSteps.length > 0 && (
            <div>
              <dt>下一步</dt>
              <dd>{nextSteps.join("；")}</dd>
            </div>
          )}
        </dl>
      )}
      {!!phases.length && (
        <ol className="taskLedgerPhases" aria-label="任务阶段">
          {phases.map((phase) => (
            <li className={phase.status} key={phase.id}>
              <span>{phase.title}</span>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}

function firstValues(primary: string[] | undefined, fallback: string[] | undefined, limit: number) {
  const values = primary?.length ? primary : fallback || [];
  return values.map((value) => value.trim()).filter(Boolean).slice(0, limit);
}

function isModelSwitchNotice(text: string) {
  return text.startsWith("默认模型已切换为 ");
}
