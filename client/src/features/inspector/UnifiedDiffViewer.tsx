import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { diffLineClass, parseUnifiedDiffByFile } from "./diffParsing";
import { SplitDiffView } from "./SplitDiffView";
import { HighlightedText } from "./TextHighlight";

interface UnifiedDiffViewerProps {
  diff?: string | null;
  emptyText: string;
  fallbackText?: string;
  leftLabel?: string;
  maxFiles?: number;
  rightLabel?: string;
}

export function UnifiedDiffViewer({ diff, emptyText, fallbackText, leftLabel = "原始", maxFiles = 24, rightLabel = "当前" }: UnifiedDiffViewerProps) {
  const files = useMemo(() => (diff ? parseUnifiedDiffByFile(diff) : []), [diff]);
  const [selectedPath, setSelectedPath] = useState<string>("__all__");
  const [mode, setMode] = useState<"split" | "unified">("split");
  const [collapseContext, setCollapseContext] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const normalizedSearch = searchQuery.trim().toLocaleLowerCase();
  useEffect(() => {
    if (selectedPath !== "__all__" && !files.some((file) => file.path === selectedPath)) {
      setSelectedPath("__all__");
    }
  }, [files, selectedPath]);
  const pathFilteredFiles = selectedPath === "__all__" ? files : files.filter((file) => file.path === selectedPath);
  const visibleFiles = normalizedSearch ? pathFilteredFiles.filter((file) => fileMatchesSearch(file, normalizedSearch)) : pathFilteredFiles;
  const displayedFiles = visibleFiles.slice(0, maxFiles);
  const hiddenCount = Math.max(0, visibleFiles.length - displayedFiles.length);

  if (!files.length) {
    return (
      <div className="unifiedDiffViewer">
        {fallbackText ? <pre>{fallbackText}</pre> : <p>{emptyText}</p>}
      </div>
    );
  }

  return (
    <div className="unifiedDiffViewer">
      {files.length > 1 && (
        <div className="unifiedDiffFileFilter" aria-label="Diff 文件筛选">
          <button className={selectedPath === "__all__" ? "active" : ""} type="button" onClick={() => setSelectedPath("__all__")}>
            全部文件
            <small>{files.length}</small>
          </button>
          {files.slice(0, maxFiles).map((file) => (
            <button className={selectedPath === file.path ? "active" : ""} type="button" key={file.path} onClick={() => setSelectedPath(file.path)} title={file.path}>
              {file.path}
              <small>
                +{file.additions} / -{file.deletions}
              </small>
            </button>
          ))}
        </div>
      )}
      <div className="unifiedDiffToolbar">
        <label className="unifiedDiffSearch">
          <Search size={13} />
          <input type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索当前 diff" />
          {normalizedSearch && <small>{visibleFiles.length} 个文件命中</small>}
        </label>
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
      </div>
      {!displayedFiles.length && <p>没有找到匹配的 diff 内容。</p>}
      {displayedFiles.map((file, index) => (
        <details open={index === 0} key={`${file.path}-${index}`}>
          <summary>
            <strong>{file.path}</strong>
            <span>
              +{file.additions} / -{file.deletions}
            </span>
          </summary>
          {mode === "split" ? (
            <SplitDiffView diff={file.lines.join("\n")} collapseContext={collapseContext} leftLabel={leftLabel} rightLabel={rightLabel} searchQuery={searchQuery} />
          ) : (
            <pre>
              {file.lines.map((line, lineIndex) => (
                <span className={`diffLine ${diffLineClass(line)}`} key={`${lineIndex}-${line}`}>
                  <b>{lineIndex + 1}</b>
                  <code>{normalizedSearch ? <HighlightedText text={line || " "} query={searchQuery} /> : line || " "}</code>
                </span>
              ))}
            </pre>
          )}
        </details>
      ))}
      {hiddenCount > 0 && <p>还有 {hiddenCount} 个文件未展开显示，请查看完整 patch 文件。</p>}
    </div>
  );
}

function fileMatchesSearch(file: { path: string; lines: string[] }, query: string) {
  if (file.path.toLocaleLowerCase().includes(query)) {
    return true;
  }
  return file.lines.some((line) => line.toLocaleLowerCase().includes(query));
}
