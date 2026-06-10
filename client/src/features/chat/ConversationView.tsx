import { useEffect, useRef } from "react";
import { Loader2, Play } from "lucide-react";
import type { SearchIntentSnapshot, TaskLedgerSnapshot } from "@workbench/shared";
import type { ConversationMessage } from "./types";

interface ConversationViewProps {
  messages: ConversationMessage[];
  requirement: string;
  searchIntent: SearchIntentSnapshot | null;
  taskLedger: TaskLedgerSnapshot | null;
  isRunning: boolean;
  executionStatus: string | null;
  canSend: boolean;
  autopilotEnabled: boolean;
  onAutopilotChange: (value: boolean) => void;
  onRequirementChange: (value: string) => void;
  onRunAgent: () => void;
}

export function ConversationView({
  messages,
  requirement,
  searchIntent,
  taskLedger,
  isRunning,
  executionStatus,
  canSend,
  autopilotEnabled,
  onAutopilotChange,
  onRequirementChange,
  onRunAgent,
}: ConversationViewProps) {
  const visibleMessages = messages.filter((message) => !isModelSwitchNotice(message.text));
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLElement>(null);

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
            <div className="messageText">{message.text}</div>
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
          aria-label="输入需求"
          placeholder="描述你希望 Agent 在当前沙盒仓库里完成的需求..."
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
          <span>
            {canSend
              ? autopilotEnabled
                ? "托管模式：自动确认并持续执行，直达提测"
                : "计划模式：先生成方案，再由你确认工具调用"
              : "先在左侧接入一个仓库"}
          </span>
          <button onClick={onRunAgent} className="primary" type="button" disabled={isRunning || !canSend || !requirement.trim()}>
            <Play size={18} />
            {isRunning ? "Agent 处理中" : "发送给 Agent"}
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
  if (!taskLedger && !searchIntent) {
    return null;
  }

  const intent = taskLedger?.searchIntent;
  const queries = firstValues(intent?.searchQueries, searchIntent?.searchQueries, 3);
  const files = firstValues(intent?.fileHints, searchIntent?.fileHints, 3);
  const nextSteps = firstValues(taskLedger?.nextSteps, undefined, 3);
  const phases = (taskLedger?.phases ?? []).slice(0, 7);
  const source = intent?.source || searchIntent?.source || "rules";
  const confidence = intent?.confidence ?? searchIntent?.confidence;

  return (
    <aside className="taskLedgerStrip" aria-label="任务账本">
      <div>
        <span>当前理解</span>
        <strong>{taskLedger?.currentUnderstanding || searchIntent?.summary || "等待 Agent 形成任务理解。"}</strong>
      </div>
      <dl>
        <div>
          <dt>来源</dt>
          <dd>
            {source}
            {typeof confidence === "number" ? ` · ${Math.round(confidence * 100)}%` : ""}
          </dd>
        </div>
        <div>
          <dt>检索</dt>
          <dd>{queries.length ? queries.join("；") : "等待生成"}</dd>
        </div>
        <div>
          <dt>文件</dt>
          <dd>{files.length ? files.join("；") : "暂无明确文件"}</dd>
        </div>
        <div>
          <dt>下一步</dt>
          <dd>{nextSteps.length ? nextSteps.join("；") : "等待用户发送需求"}</dd>
        </div>
      </dl>
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
