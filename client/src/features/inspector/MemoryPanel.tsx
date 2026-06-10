import { Brain, Edit3, Pin, PinOff, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { MemoryPatchCandidate, MemoryPatchDraft, MemoryPatternItem, MemoryRecallItem, MemorySnapshot } from "@workbench/shared";

interface MemoryPanelProps {
  memory: MemorySnapshot | null;
  memoryPatchDraft: MemoryPatchDraft | null;
  isRunning: boolean;
  onPinMemory: (itemId: string, pinned: boolean) => void;
  onForgetMemory: (itemId: string) => void;
  onUpsertManualMemory: (input: {
    itemId?: string;
    title: string;
    content: string;
    kind?: string;
    tags?: string[];
    pinned?: boolean;
    importance?: number;
  }) => Promise<boolean>;
  onGenerateMemoryPatchDraft: () => void;
  onApplyMemoryPatchCandidate: (candidate: MemoryPatchCandidate) => void;
}

interface MemoryFormState {
  itemId?: string;
  title: string;
  content: string;
  kind: string;
  tags: string;
  pinned: boolean;
  importance: number;
}

const emptyForm: MemoryFormState = {
  title: "",
  content: "",
  kind: "decision",
  tags: "manual, decision",
  pinned: true,
  importance: 3
};

function canEditMemory(item: MemoryRecallItem) {
  return item.id.startsWith("lt_");
}

export function MemoryPanel({
  memory,
  memoryPatchDraft,
  isRunning,
  onPinMemory,
  onForgetMemory,
  onUpsertManualMemory,
  onGenerateMemoryPatchDraft,
  onApplyMemoryPatchCandidate
}: MemoryPanelProps) {
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState("all");
  const [form, setForm] = useState<MemoryFormState | null>(null);
  const recallItems = memory?.recall?.items ?? [];
  const longTermItems = memory?.longTerm?.items ?? [];
  const sections = memory?.contextPack.sections ?? [];
  const patterns = memory?.patterns?.items ?? [];
  const curatedMemory = memory?.curatedMemory;
  const curatedItems = curatedMemory?.items ?? [];
  const taskLedger = memory?.taskLedger;
  const strategy = memory?.recall?.strategy ?? "尚未生成";
  const visibleRecallItems = useMemo(() => filterMemoryItems(recallItems, query, kindFilter), [recallItems, query, kindFilter]);
  const visibleLongTermItems = useMemo(() => filterMemoryItems(longTermItems, query, kindFilter), [longTermItems, query, kindFilter]);
  const visiblePatterns = useMemo(() => filterPatterns(patterns, query), [patterns, query]);

  function openNewForm() {
    setForm(emptyForm);
  }

  function openEditForm(item: MemoryRecallItem) {
    setForm({
      itemId: item.id,
      title: item.title,
      content: item.content,
      kind: item.kind,
      tags: item.tags.join(", "),
      pinned: Boolean(item.pinned),
      importance: item.importance ?? 3
    });
  }

  async function submitForm() {
    if (!form) return;
    // 数字输入清空或填非法值时 importance 会是 NaN，序列化成 null 会触发后端 422；此时直接不传该字段。
    const safeImportance = Number.isFinite(form.importance) ? form.importance : undefined;
    const ok = await onUpsertManualMemory({
      itemId: form.itemId,
      title: form.title,
      content: form.content,
      kind: form.kind,
      tags: form.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      pinned: form.pinned,
      importance: safeImportance
    });
    if (ok) {
      setForm(null);
    }
  }

  return (
    <section className="panel">
      <h3>
        <Brain size={16} />
        记忆
        {memory && <small>{memory.recall?.entryCount ?? 0} 条</small>}
      </h3>
      {!memory && <p>发送需求或刷新证据后，这里会显示当前对话记忆。</p>}
      <MemoryToolbar
        query={query}
        kindFilter={kindFilter}
        isRunning={isRunning}
        onQueryChange={setQuery}
        onKindFilterChange={setKindFilter}
        onNew={openNewForm}
        onGenerateDraft={onGenerateMemoryPatchDraft}
      />
      {form && <MemoryEditor form={form} isRunning={isRunning} onChange={setForm} onClose={() => setForm(null)} onSubmit={submitForm} />}
      {memoryPatchDraft && <MemoryPatchDraftView draft={memoryPatchDraft} isRunning={isRunning} onApply={onApplyMemoryPatchCandidate} />}
      {memory && (
        <>
          <div className="metricGrid">
            <Metric value={sections.length} label="上下文片段" />
            <Metric value={recallItems.length} label="召回记忆" />
            <Metric value={memory.longTerm?.count ?? memory.recall?.longTermCount ?? 0} label="长期记忆" />
            <Metric value={memory.patterns?.count ?? 0} label="复用策略" />
            <Metric value={curatedMemory?.counts.total ?? 0} label="结构化记忆" />
          </div>

          <div className="memoryMeta">
            <span>{strategy}</span>
            <span>候选 {memory.recall?.candidateCount ?? memory.recall?.entryCount ?? 0}</span>
            <span>命名空间 {memory.longTerm?.namespace ?? "workspace"}</span>
            <span>Curator {memory.recall?.curatedCount ?? curatedMemory?.counts.total ?? 0}</span>
          </div>

          {taskLedger && <TaskLedgerBlock taskLedger={taskLedger} />}

          <MemoryGroup title="本轮召回" items={visibleRecallItems} isRunning={isRunning} onPinMemory={onPinMemory} onForgetMemory={onForgetMemory} onEdit={openEditForm} />

          <MemoryGroup
            title="长期记忆库"
            items={visibleLongTermItems}
            emptyText="当前仓库命名空间还没有长期记忆。"
            isRunning={isRunning}
            onPinMemory={onPinMemory}
            onForgetMemory={onForgetMemory}
            onEdit={openEditForm}
          />

          {!!visiblePatterns.length && <PatternGroup patterns={visiblePatterns} />}

          {!!curatedItems.length && (
            <details className="memoryDetails">
              <summary>结构化记忆文件</summary>
              <div>
                <strong>{curatedMemory?.namespace}</strong>
                <p>{curatedMemory?.repoMemoryMarkdownPath}</p>
              </div>
              {curatedItems.slice(0, 8).map((item) => (
                <div key={item.id}>
                  <strong>{item.title}</strong>
                  <p>{item.content}</p>
                </div>
              ))}
            </details>
          )}

          <details className="memoryDetails">
            <summary>上下文包</summary>
            {sections.map((section) => (
              <div key={section.id}>
                <strong>{section.title}</strong>
                <p>{section.content}</p>
              </div>
            ))}
          </details>
        </>
      )}
    </section>
  );
}

function Metric({ value, label }: { value: number; label: string }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function MemoryToolbar({
  query,
  kindFilter,
  isRunning,
  onQueryChange,
  onKindFilterChange,
  onNew,
  onGenerateDraft
}: {
  query: string;
  kindFilter: string;
  isRunning: boolean;
  onQueryChange: (value: string) => void;
  onKindFilterChange: (value: string) => void;
  onNew: () => void;
  onGenerateDraft: () => void;
}) {
  return (
    <div className="memoryToolbar">
      <label>
        <Search size={14} />
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="搜索标题、内容、标签或来源" />
      </label>
      <select value={kindFilter} onChange={(event) => onKindFilterChange(event.target.value)} aria-label="筛选记忆类型">
        <option value="all">全部类型</option>
        <option value="repo">仓库</option>
        <option value="decision">决策</option>
        <option value="failure">失败</option>
        <option value="delivery">交付</option>
        <option value="preview">预览</option>
        <option value="skill">Skill</option>
      </select>
      <button type="button" disabled={isRunning} onClick={onNew}>
        <Plus size={14} />
        新增
      </button>
      <button type="button" disabled={isRunning} onClick={onGenerateDraft}>
        <Sparkles size={14} />
        模型整理
      </button>
    </div>
  );
}

function MemoryEditor({
  form,
  isRunning,
  onChange,
  onClose,
  onSubmit
}: {
  form: MemoryFormState;
  isRunning: boolean;
  onChange: (form: MemoryFormState) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="memoryEditor">
      <header>
        <strong>{form.itemId ? "编辑长期记忆" : "新增长期记忆"}</strong>
        <button className="iconButton" type="button" onClick={onClose} title="关闭">
          <X size={14} />
        </button>
      </header>
      <label>
        <span>标题</span>
        <input value={form.title} onChange={(event) => onChange({ ...form, title: event.target.value })} />
      </label>
      <label>
        <span>内容</span>
        <textarea value={form.content} onChange={(event) => onChange({ ...form, content: event.target.value })} />
      </label>
      <div className="memoryEditorGrid">
        <label>
          <span>类型</span>
          <input value={form.kind} onChange={(event) => onChange({ ...form, kind: event.target.value })} />
        </label>
        <label>
          <span>重要性</span>
          <input
            type="number"
            min={0.1}
            max={5}
            step={0.1}
            value={form.importance}
            onChange={(event) => onChange({ ...form, importance: Number(event.target.value) })}
          />
        </label>
      </div>
      <label>
        <span>标签，逗号分隔</span>
        <input value={form.tags} onChange={(event) => onChange({ ...form, tags: event.target.value })} />
      </label>
      <label className="memoryCheckbox">
        <input type="checkbox" checked={form.pinned} onChange={(event) => onChange({ ...form, pinned: event.target.checked })} />
        <span>置顶并优先进入后续上下文</span>
      </label>
      <button type="button" disabled={isRunning || !form.title.trim() || !form.content.trim()} onClick={onSubmit}>
        保存记忆
      </button>
    </div>
  );
}

function MemoryPatchDraftView({
  draft,
  isRunning,
  onApply
}: {
  draft: MemoryPatchDraft;
  isRunning: boolean;
  onApply: (candidate: MemoryPatchCandidate) => void;
}) {
  return (
    <details className="memoryDraft" open>
      <summary>
        <span>模型记忆草案</span>
        <small>
          {draft.source} · {draft.candidates.length} 条
        </small>
      </summary>
      <p>{draft.summary}</p>
      <em>命名空间：{draft.namespace}</em>
      <div className="memoryDraftList">
        {draft.candidates.map((candidate) => (
          <article className="memoryDraftItem" key={candidate.id}>
            <header>
              <div>
                <strong>{candidate.title}</strong>
                <small>
                  {candidate.kind} · 重要性 {formatNumber(candidate.importance)}
                  {candidate.pinned ? " · 置顶" : ""}
                </small>
              </div>
              <button type="button" disabled={isRunning} onClick={() => onApply(candidate)}>
                写入
              </button>
            </header>
            {candidate.reason && <em>{candidate.reason}</em>}
            {candidate.review?.patch && <MemoryPatchView patch={candidate.review.patch} />}
            <p>{candidate.content}</p>
          </article>
        ))}
        {!draft.candidates.length && <p>当前没有可写入的长期记忆草案。</p>}
      </div>
    </details>
  );
}

function MemoryGroup({
  title,
  items,
  emptyText = "当前需求还没有召回到相关历史记忆。",
  isRunning,
  onPinMemory,
  onForgetMemory,
  onEdit
}: {
  title: string;
  items: MemoryRecallItem[];
  emptyText?: string;
  isRunning: boolean;
  onPinMemory: (itemId: string, pinned: boolean) => void;
  onForgetMemory: (itemId: string) => void;
  onEdit: (item: MemoryRecallItem) => void;
}) {
  return (
    <details className="memoryDetails" open={title === "本轮召回"}>
      <summary>
        {title}
        <small>{items.length} 条</small>
      </summary>
      <div className="memoryList">
        {items.map((item) => (
          <article className="memoryItem" key={item.id}>
            <header>
              <div>
                <strong>{item.title}</strong>
                <small>
                  {item.sourcePhase ?? "来源未标注"} · {item.scope ?? "conversation"} · {item.kind} · 分数 {formatNumber(item.score)} · 重要性 {formatNumber(item.importance)}
                  {item.pinned ? " · 已置顶" : ""}
                  {item.manual ? " · 手动" : ""}
                </small>
              </div>
              {canEditMemory(item) && (
                <div className="memoryActions">
                  <button type="button" disabled={isRunning} title="编辑" onClick={() => onEdit(item)}>
                    <Edit3 size={14} />
                  </button>
                  <button type="button" disabled={isRunning} title={item.pinned ? "取消置顶" : "置顶"} onClick={() => onPinMemory(item.id, !item.pinned)}>
                    {item.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                  </button>
                  <button type="button" disabled={isRunning} title="遗忘" onClick={() => onForgetMemory(item.id)}>
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </header>
            {item.reason && <em>{item.reason}</em>}
            {item.lastPatch && <MemoryPatchView patch={item.lastPatch} />}
            {item.patchHistory && item.patchHistory.length > 1 && <MemoryPatchHistoryView patches={item.patchHistory} />}
            <p>{item.content}</p>
            <em>{item.sourcePath}</em>
          </article>
        ))}
        {!items.length && <p>{emptyText}</p>}
      </div>
    </details>
  );
}

function MemoryPatchView({ patch }: { patch: NonNullable<MemoryRecallItem["lastPatch"]> }) {
  return (
    <details className={`memoryPatch ${patch.conflicts?.length ? "hasConflict" : ""}`}>
      <summary>
        最近变更：{patch.summary}
        {!!patch.conflicts?.length && <span>{patch.conflicts.length} 个提示</span>}
      </summary>
      <div>
        <strong>变更字段</strong>
        <p>{patch.changedFields?.length ? patch.changedFields.join("、") : "无字段变化"}</p>
      </div>
      {!!patch.conflicts?.length && (
        <div>
          <strong>冲突提示</strong>
          {patch.conflicts.map((conflict, index) => (
            <p key={`${conflict.type}-${index}`}>
              {conflict.severity} · {conflict.summary}
            </p>
          ))}
        </div>
      )}
    </details>
  );
}

function MemoryPatchHistoryView({ patches }: { patches: NonNullable<MemoryRecallItem["patchHistory"]> }) {
  const ordered = [...patches].reverse();
  return (
    <details className="memoryPatchHistory">
      <summary>变更历史 · {patches.length} 次</summary>
      <div>
        {ordered.map((patch, index) => (
          <article key={`${patch.createdAt}-${index}`}>
            <strong>
              {patch.operation} · {patch.createdAt}
            </strong>
            <p>{patch.summary}</p>
            <em>{patch.changedFields?.length ? patch.changedFields.join("、") : "无字段变化"}</em>
          </article>
        ))}
      </div>
    </details>
  );
}

function TaskLedgerBlock({ taskLedger }: { taskLedger: NonNullable<MemorySnapshot["taskLedger"]> }) {
  return (
    <details className="memoryDetails taskLedgerDetails" open>
      <summary>任务账本</summary>
      <div>
        <strong>{taskLedger.currentUnderstanding}</strong>
        <p>{taskLedger.editNote ?? "当前任务状态会随 Agent 执行更新。"}</p>
      </div>
      {!!taskLedger.gates?.length && (
        <div className="ledgerGrid">
          {taskLedger.gates.map((gate) => (
            <span className={gate.status} key={gate.id} title={gate.detail}>
              {gate.title}
            </span>
          ))}
        </div>
      )}
      {!!taskLedger.blockers?.length && (
        <div>
          <strong>阻塞点</strong>
          <p>{taskLedger.blockers.join("；")}</p>
        </div>
      )}
      {!!taskLedger.nextSteps?.length && (
        <div>
          <strong>下一步</strong>
          <p>{taskLedger.nextSteps.join("；")}</p>
        </div>
      )}
    </details>
  );
}

function PatternGroup({ patterns }: { patterns: MemoryPatternItem[] }) {
  return (
    <details className="memoryDetails">
      <summary>可复用修复策略</summary>
      {patterns.slice(0, 8).map((pattern) => (
        <div key={pattern.id}>
          <strong>{pattern.title}</strong>
          <p>{pattern.recommendedAction ?? pattern.content}</p>
        </div>
      ))}
    </details>
  );
}

function filterMemoryItems(items: MemoryRecallItem[], query: string, kind: string) {
  const cleanedQuery = query.trim().toLowerCase();
  return items.filter((item) => {
    const kindOk = kind === "all" || item.kind === kind;
    if (!kindOk) return false;
    if (!cleanedQuery) return true;
    const haystack = [item.title, item.content, item.kind, item.scope, item.sourcePath, ...(item.tags ?? [])].join("\n").toLowerCase();
    return haystack.includes(cleanedQuery);
  });
}

function filterPatterns(patterns: MemoryPatternItem[], query: string) {
  const cleanedQuery = query.trim().toLowerCase();
  if (!cleanedQuery) return patterns;
  return patterns.filter((pattern) => [pattern.title, pattern.content, pattern.recommendedAction, pattern.category, ...(pattern.tags ?? [])].join("\n").toLowerCase().includes(cleanedQuery));
}

function formatNumber(value?: number) {
  if (typeof value !== "number") return "-";
  return value.toFixed(2).replace(/\.?0+$/, "");
}
