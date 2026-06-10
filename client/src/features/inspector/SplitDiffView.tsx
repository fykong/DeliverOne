import { useState } from "react";
import { X } from "lucide-react";
import { HighlightedText } from "./TextHighlight";

export interface SplitRow {
  type: "meta" | "context" | "changed" | "added" | "deleted" | "collapsed";
  left?: string;
  right?: string;
  leftNo?: number | null;
  rightNo?: number | null;
  hunkIndex?: number;
  count?: number;
}

interface SplitDiffViewProps {
  diff: string;
  collapseContext: boolean;
  leftLabel: string;
  rightLabel: string;
  onRollbackHunk?: (hunkIndex: number) => void;
  searchQuery?: string;
}

export function SplitDiffView({ diff, collapseContext, leftLabel, rightLabel, onRollbackHunk, searchQuery }: SplitDiffViewProps) {
  const allRows = buildSplitRows(diff);
  const rows = collapseContext ? compactContextRows(allRows) : allRows;
  const [pendingHunk, setPendingHunk] = useState<{ index: number; preview: string } | null>(null);

  function openHunkConfirm(hunkIndex: number) {
    setPendingHunk({ index: hunkIndex, preview: hunkPreview(allRows, hunkIndex) });
  }

  function confirmHunkRollback() {
    if (!pendingHunk || !onRollbackHunk) return;
    onRollbackHunk(pendingHunk.index);
    setPendingHunk(null);
  }

  return (
    <div className="splitDiff">
      <div className="splitColumnHeader">
        <span>{leftLabel}</span>
        <span>{rightLabel}</span>
      </div>
      {rows.map((row, index) => (
        <div className={`splitDiffRow ${row.type}`} key={`${index}-${row.left ?? ""}-${row.right ?? ""}`}>
          {row.type === "meta" ? (
            <div className="splitMeta">
              <span>{row.left ?? row.right}</span>
              {onRollbackHunk && typeof row.hunkIndex === "number" && (
                <button type="button" onClick={() => openHunkConfirm(row.hunkIndex!)}>
                  回退此段
                </button>
              )}
            </div>
          ) : row.type === "collapsed" ? (
            <div className="splitCollapsed">已折叠 {row.count ?? 0} 行未变更上下文</div>
          ) : (
            <>
              <DiffCell lineNo={row.leftNo} text={row.left} type={row.type} peer={row.right} searchQuery={searchQuery} side="left" />
              <DiffCell lineNo={row.rightNo} text={row.right} type={row.type} peer={row.left} searchQuery={searchQuery} side="right" />
            </>
          )}
        </div>
      ))}
      {pendingHunk && (
        <div className="modalBackdrop" role="presentation">
          <div className="reviewModal" role="dialog" aria-modal="true" aria-label="确认回退变更块">
            <header>
              <div>
                <span>回退确认</span>
                <strong>变更块 #{pendingHunk.index + 1}</strong>
              </div>
              <button className="iconButton" type="button" onClick={() => setPendingHunk(null)} title="关闭">
                <X size={16} />
              </button>
            </header>
            <label className="modalField">
              <span>即将回退的 Diff 片段</span>
              <pre>{pendingHunk.preview}</pre>
            </label>
            <footer>
              <button className="dangerButton" type="button" onClick={confirmHunkRollback}>
                确认回退此段
              </button>
              <button type="button" onClick={() => setPendingHunk(null)}>
                取消
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}

function DiffCell({
  lineNo,
  text,
  type,
  peer,
  searchQuery,
  side
}: {
  lineNo?: number | null;
  text?: string;
  type: SplitRow["type"];
  peer?: string;
  searchQuery?: string;
  side: "left" | "right";
}) {
  const shouldHighlight = type === "changed" && text !== undefined && peer !== undefined;
  return (
    <div className={`splitCell ${side}`}>
      <b className="splitNo">{lineNo ?? ""}</b>
      <code className="splitCode">
        {searchQuery ? <HighlightedText text={text || " "} query={searchQuery} /> : shouldHighlight ? <InlineDiffText text={text} peer={peer} /> : text || " "}
      </code>
    </div>
  );
}

function InlineDiffText({ text, peer }: { text: string; peer: string }) {
  const { prefix, middle, suffix } = changedSegment(text, peer);
  if (!middle) {
    return <>{text || " "}</>;
  }
  return (
    <>
      {prefix}
      <mark>{middle}</mark>
      {suffix}
    </>
  );
}

function changedSegment(text: string, peer: string) {
  let prefixLength = 0;
  while (prefixLength < text.length && prefixLength < peer.length && text[prefixLength] === peer[prefixLength]) {
    prefixLength += 1;
  }

  let suffixLength = 0;
  while (
    suffixLength < text.length - prefixLength &&
    suffixLength < peer.length - prefixLength &&
    text[text.length - 1 - suffixLength] === peer[peer.length - 1 - suffixLength]
  ) {
    suffixLength += 1;
  }

  return {
    prefix: text.slice(0, prefixLength),
    middle: text.slice(prefixLength, suffixLength ? text.length - suffixLength : text.length),
    suffix: suffixLength ? text.slice(text.length - suffixLength) : ""
  };
}

function buildSplitRows(diff: string) {
  const rows: SplitRow[] = [];
  const lines = diff.split("\n");
  let oldLine = 0;
  let newLine = 0;
  let hunkIndex = -1;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      hunkIndex += 1;
      rows.push({ type: "meta", left: line, right: line, hunkIndex });
      continue;
    }
    if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("diff --git") || line.startsWith("index ")) {
      rows.push({ type: "meta", left: line, right: line });
      continue;
    }
    if (line.startsWith("\\ No newline")) {
      rows.push({ type: "meta", left: line, right: line });
      continue;
    }
    if (line.startsWith("-")) {
      const next = lines[index + 1];
      if (next?.startsWith("+") && !next.startsWith("+++")) {
        rows.push({ type: "changed", left: line.slice(1), right: next.slice(1), leftNo: oldLine, rightNo: newLine });
        oldLine += 1;
        newLine += 1;
        index += 1;
      } else {
        rows.push({ type: "deleted", left: line.slice(1), leftNo: oldLine, rightNo: null });
        oldLine += 1;
      }
      continue;
    }
    if (line.startsWith("+")) {
      rows.push({ type: "added", right: line.slice(1), leftNo: null, rightNo: newLine });
      newLine += 1;
      continue;
    }

    const text = line.startsWith(" ") ? line.slice(1) : line;
    rows.push({ type: "context", left: text, right: text, leftNo: oldLine || null, rightNo: newLine || null });
    if (oldLine) oldLine += 1;
    if (newLine) newLine += 1;
  }

  return rows;
}

function compactContextRows(rows: SplitRow[], radius = 2) {
  const keep = new Set<number>();
  rows.forEach((row, index) => {
    if (row.type === "meta" || row.type === "changed" || row.type === "added" || row.type === "deleted") {
      for (let offset = -radius; offset <= radius; offset += 1) {
        const keepIndex = index + offset;
        if (keepIndex >= 0 && keepIndex < rows.length) {
          keep.add(keepIndex);
        }
      }
    }
  });

  const compacted: SplitRow[] = [];
  let hiddenCount = 0;
  rows.forEach((row, index) => {
    if (keep.has(index) || row.type !== "context") {
      if (hiddenCount) {
        compacted.push({ type: "collapsed", count: hiddenCount });
        hiddenCount = 0;
      }
      compacted.push(row);
      return;
    }
    hiddenCount += 1;
  });
  if (hiddenCount) {
    compacted.push({ type: "collapsed", count: hiddenCount });
  }
  return compacted;
}

function hunkPreview(rows: SplitRow[], hunkIndex: number) {
  const start = rows.findIndex((row) => row.type === "meta" && row.hunkIndex === hunkIndex);
  if (start < 0) return "未找到对应变更块。";
  const selected: string[] = [];

  for (let index = start; index < rows.length; index += 1) {
    const row = rows[index];
    if (index > start && row.type === "meta" && typeof row.hunkIndex === "number") break;
    if (row.type === "meta") {
      selected.push(row.left ?? row.right ?? "");
    } else if (row.type === "changed") {
      selected.push(`- ${row.left ?? ""}`);
      selected.push(`+ ${row.right ?? ""}`);
    } else if (row.type === "deleted") {
      selected.push(`- ${row.left ?? ""}`);
    } else if (row.type === "added") {
      selected.push(`+ ${row.right ?? ""}`);
    } else if (row.type === "context") {
      selected.push(`  ${row.left ?? row.right ?? ""}`);
    }
  }

  return selected.join("\n");
}
