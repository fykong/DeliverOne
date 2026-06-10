export interface ParsedDiffFile {
  path: string;
  additions: number;
  deletions: number;
  lines: string[];
}

export function parseUnifiedDiffByFile(diff: string): ParsedDiffFile[] {
  const lines = diff.split("\n");
  const files: ParsedDiffFile[] = [];
  let current: ParsedDiffFile | null = null;

  for (const line of lines) {
    if (line.startsWith("diff --git ")) {
      current = {
        path: diffPathFromHeader(line) || `文件 ${files.length + 1}`,
        additions: 0,
        deletions: 0,
        lines: [line]
      };
      files.push(current);
      continue;
    }

    if (!current) {
      current = {
        path: "变更",
        additions: 0,
        deletions: 0,
        lines: []
      };
      files.push(current);
    }

    current.lines.push(line);
    if (line.startsWith("+") && !line.startsWith("+++")) {
      current.additions += 1;
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      current.deletions += 1;
    } else if (line.startsWith("+++ ")) {
      const path = diffPathFromFileMarker(line);
      if (path) current.path = path;
    }
  }

  return files.filter((file) => file.lines.some((line) => line.trim()));
}

export function diffLineClass(line: string) {
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+") && !line.startsWith("+++")) return "added";
  if (line.startsWith("-") && !line.startsWith("---")) return "deleted";
  if (line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("+++") || line.startsWith("---")) return "meta";
  return "";
}

function diffPathFromHeader(line: string) {
  const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
  return match?.[2] || match?.[1] || null;
}

function diffPathFromFileMarker(line: string) {
  const value = line.replace(/^\+\+\+\s+/, "").trim();
  if (!value || value === "/dev/null") return null;
  return value.replace(/^b\//, "");
}
