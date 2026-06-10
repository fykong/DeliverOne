import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { FileCode2, FolderTree, GitCompareArrows, RotateCcw } from "lucide-react";
import type { CheckpointManifest, SandboxDiffFile, SandboxDiffResponse, SandboxFileContent, SandboxTreeItem } from "@workbench/shared";
import { SplitDiffView } from "./SplitDiffView";

type FilePanelTab = "files" | "changes" | "rollback";

interface SandboxFilePanelProps {
  sandboxFiles: SandboxTreeItem[];
  selectedFile: SandboxFileContent | null;
  selectedFilePath: string | null;
  currentDiff: SandboxDiffResponse | null;
  selectedDiff: SandboxDiffFile | null;
  checkpointDiff: SandboxDiffResponse | null;
  selectedCheckpointId: string | null;
  checkpoints: CheckpointManifest[];
  isRunning: boolean;
  onOpenSandboxFile: (path: string) => void;
  onOpenDiffFile: (path: string) => void;
  onOpenCheckpointDiff: (checkpointId: string) => void;
  onRollbackCheckpoint: (checkpointId: string) => void;
  onRollbackCheckpointFile: (checkpointId: string, relativePath: string) => void;
  onRollbackCheckpointHunk: (checkpointId: string, relativePath: string, hunkIndex: number) => void;
}

const statusLabel: Record<string, string> = {
  added: "A",
  deleted: "D",
  modified: "M",
  renamed: "R",
  unchanged: "",
  unknown: "?"
};

const statusText: Record<string, string> = {
  added: "新增",
  deleted: "删除",
  modified: "修改",
  renamed: "重命名",
  unchanged: "无变化",
  unknown: "未知"
};

export function SandboxFilePanel({
  sandboxFiles,
  selectedFile,
  selectedFilePath,
  currentDiff,
  selectedDiff,
  checkpointDiff,
  selectedCheckpointId,
  checkpoints,
  isRunning,
  onOpenSandboxFile,
  onOpenDiffFile,
  onOpenCheckpointDiff,
  onRollbackCheckpoint,
  onRollbackCheckpointFile,
  onRollbackCheckpointHunk
}: SandboxFilePanelProps) {
  const [tab, setTab] = useState<FilePanelTab>("files");
  const [checkpointFilePath, setCheckpointFilePath] = useState<string | null>(null);
  const changedByPath = useMemo(() => new Map((currentDiff?.files ?? []).map((item) => [item.path, item])), [currentDiff]);
  const displayedDiff = selectedDiff ?? currentDiff?.files[0] ?? null;
  const displayedCheckpointFile = checkpointDiff?.files.find((item) => item.path === checkpointFilePath) ?? checkpointDiff?.files[0] ?? null;

  useEffect(() => {
    setCheckpointFilePath(checkpointDiff?.files[0]?.path ?? null);
  }, [checkpointDiff?.checkpointId]);

  useEffect(() => {
    if (selectedDiff) {
      setTab("changes");
    }
  }, [selectedDiff]);

  useEffect(() => {
    if (selectedCheckpointId) {
      setTab("rollback");
    }
  }, [selectedCheckpointId]);

  return (
    <section className="panel fileWorkspacePanel">
      <h3>
        <FileCode2 size={16} />
        文件与变更
        {currentDiff && <small>{currentDiff.fileCount} 个变更</small>}
      </h3>

      <div className="fileTabs" role="tablist" aria-label="文件工作区">
        <button className={tab === "files" ? "active" : ""} type="button" onClick={() => setTab("files")}>
          <FolderTree size={14} />
          文件
        </button>
        <button className={tab === "changes" ? "active" : ""} type="button" onClick={() => setTab("changes")}>
          <GitCompareArrows size={14} />
          变更
        </button>
        <button className={tab === "rollback" ? "active" : ""} type="button" onClick={() => setTab("rollback")}>
          <RotateCcw size={14} />
          回退
        </button>
      </div>

      {tab === "files" && (
        <div className="fileBrowser">
          <div className="fileTree">
            {sandboxFiles.map((item) => {
              const change = changedByPath.get(item.path);
              return (
                <button
                  className={`fileNode ${item.type} ${selectedFilePath === item.path ? "active" : ""}`}
                  key={`${item.type}-${item.path}`}
                  style={{ paddingLeft: `${8 + item.depth * 14}px` }}
                  type="button"
                  disabled={item.type === "directory" || !item.isText}
                  onClick={() => onOpenSandboxFile(item.path)}
                  title={item.path}
                >
                  <span>{item.type === "directory" ? "目录" : item.isText ? "文件" : "二进制"}</span>
                  <strong>{item.name}</strong>
                  {change && <em className={`statusBadge ${change.status}`}>{statusLabel[change.status] ?? "?"}</em>}
                </button>
              );
            })}
            {sandboxFiles.length === 0 && <p>接入仓库后，这里会显示当前对话沙盒的文件树。</p>}
          </div>
          {selectedFile ? <FilePreview file={selectedFile} /> : <p>点开文件后，会在这里查看当前沙盒中的文件内容。</p>}
        </div>
      )}

      {tab === "changes" && (
        <div className="diffWorkspace">
          <ChangeList files={currentDiff?.files ?? []} selectedPath={displayedDiff?.path ?? null} onOpen={onOpenDiffFile} />
          <DiffViewer file={displayedDiff} emptyText="当前沙盒还没有可展示的变更。" leftLabel="原始 HEAD" rightLabel="当前沙盒" />
        </div>
      )}

      {tab === "rollback" && (
        <div className="rollbackWorkspace">
          <div className="checkpointList">
            {checkpoints.slice(0, 8).map((checkpoint) => (
              <div className={`checkpointRow ${selectedCheckpointId === checkpoint.id ? "active" : ""}`} key={checkpoint.id}>
                <div>
                  <strong>{checkpoint.label}</strong>
                  <span>{checkpoint.files.length} 个文件 · {checkpoint.createdAt}</span>
                </div>
                <div className="checkpointActions">
                  <button type="button" disabled={isRunning} onClick={() => onOpenCheckpointDiff(checkpoint.id)}>
                    Diff
                  </button>
                  <button
                    type="button"
                    disabled={isRunning}
                    onClick={() => {
                      if (window.confirm(`确认回退到检查点「${checkpoint.label}」？这会把沙盒文件还原到该检查点时的状态，无法直接撤销。`)) {
                        onRollbackCheckpoint(checkpoint.id);
                      }
                    }}
                  >
                    回退
                  </button>
                </div>
              </div>
            ))}
            {checkpoints.length === 0 && <p>还没有 checkpoint。首次写代码前会自动创建。</p>}
          </div>

          {checkpointDiff && (
            <div className="checkpointDiff">
              <div className="diffHeader">
                <strong>{checkpointDiff.checkpointLabel ?? checkpointDiff.checkpointId}</strong>
                <span>{checkpointDiff.fileCount} 个文件</span>
              </div>
              <ChangeList files={checkpointDiff.files} selectedPath={displayedCheckpointFile?.path ?? null} onOpen={setCheckpointFilePath} />
              <DiffViewer
                file={displayedCheckpointFile}
                emptyText="这个 checkpoint 当前没有可展示的差异。"
                rightAction={
                  selectedCheckpointId && displayedCheckpointFile ? (
                    <button
                      type="button"
                      disabled={isRunning}
                      onClick={() => {
                        if (window.confirm(`确认回退文件「${displayedCheckpointFile.path}」？这会把该沙盒文件还原到检查点时的状态，无法直接撤销。`)) {
                          onRollbackCheckpointFile(selectedCheckpointId, displayedCheckpointFile.path);
                        }
                      }}
                    >
                      回退此文件
                    </button>
                  ) : null
                }
                leftLabel="检查点"
                rightLabel="当前沙盒"
                onRollbackHunk={
                  selectedCheckpointId && displayedCheckpointFile
                    ? (hunkIndex) => onRollbackCheckpointHunk(selectedCheckpointId, displayedCheckpointFile.path, hunkIndex)
                    : undefined
                }
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function FilePreview({ file }: { file: SandboxFileContent }) {
  return (
    <div className="filePreview">
      <div>
        <strong>{file.path}</strong>
        <span>
          {file.language}
          {file.truncated ? "，已截断" : ""}
        </span>
      </div>
      <pre>{file.content}</pre>
    </div>
  );
}

function ChangeList({ files, selectedPath, onOpen }: { files: SandboxDiffFile[]; selectedPath: string | null; onOpen: (path: string) => void }) {
  if (files.length === 0) {
    return <p>暂无变更文件。</p>;
  }
  return (
    <div className="changeList">
      {files.map((file) => (
        <button className={selectedPath === file.path ? "active" : ""} key={file.path} type="button" onClick={() => onOpen(file.path)} title={file.path}>
          <em className={`statusBadge ${file.status}`}>{statusLabel[file.status] ?? "?"}</em>
          <strong>{file.path}</strong>
          <span>
            +{file.additions} / -{file.deletions}
          </span>
        </button>
      ))}
    </div>
  );
}

function DiffViewer({
  file,
  emptyText,
  rightAction,
  leftLabel = "原始",
  rightLabel = "当前",
  onRollbackHunk
}: {
  file: SandboxDiffFile | null;
  emptyText: string;
  rightAction?: ReactNode;
  leftLabel?: string;
  rightLabel?: string;
  onRollbackHunk?: (hunkIndex: number) => void;
}) {
  const [mode, setMode] = useState<"split" | "unified">("split");
  const [collapseContext, setCollapseContext] = useState(true);

  if (!file) {
    return <p>{emptyText}</p>;
  }
  const lines = file.diff ? file.diff.split("\n") : [];
  return (
    <div className="diffViewer">
      <div className="diffHeader">
        <strong>{file.path}</strong>
        <div className="diffHeaderActions">
          <span>
            {statusText[file.status] ?? file.status} · +{file.additions} / -{file.deletions}
          </span>
          <div className="diffModeToggle" aria-label="Diff 展示方式">
            <button className={mode === "split" ? "active" : ""} type="button" onClick={() => setMode("split")}>
              左右
            </button>
            <button className={mode === "unified" ? "active" : ""} type="button" onClick={() => setMode("unified")}>
              统一
            </button>
          </div>
          <button type="button" className={collapseContext ? "active" : ""} onClick={() => setCollapseContext((value) => !value)}>
            {collapseContext ? "展开上下文" : "折叠上下文"}
          </button>
          {rightAction}
        </div>
      </div>
      {lines.length > 0 && mode === "split" ? (
        <SplitDiffView
          diff={file.diff}
          collapseContext={collapseContext}
          leftLabel={leftLabel}
          rightLabel={rightLabel}
          onRollbackHunk={onRollbackHunk}
        />
      ) : lines.length > 0 ? (
        <pre>
          {lines.map((line, index) => (
            <span className={`diffLine ${lineClass(line)}`} key={`${index}-${line}`}>
              <b>{index + 1}</b>
              <code>{line || " "}</code>
            </span>
          ))}
        </pre>
      ) : (
        <p>这个文件没有文本 diff，可能是二进制文件或当前没有差异。</p>
      )}
    </div>
  );
}

function lineClass(line: string) {
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+") && !line.startsWith("+++")) return "added";
  if (line.startsWith("-") && !line.startsWith("---")) return "deleted";
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  return "context";
}
