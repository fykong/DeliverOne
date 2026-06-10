import { Fragment, type ReactNode } from "react";

interface MarkdownPreviewProps {
  content: string;
  truncated?: boolean;
}

type MarkdownBlock =
  | { kind: "heading"; level: number; text: string; key: string }
  | { kind: "paragraph"; lines: string[]; key: string }
  | { kind: "list"; ordered: boolean; items: string[]; key: string }
  | { kind: "code"; language?: string; lines: string[]; key: string }
  | { kind: "quote"; lines: string[]; key: string }
  | { kind: "table"; rows: string[][]; key: string }
  | { kind: "rule"; key: string };

export function MarkdownPreview({ content, truncated }: MarkdownPreviewProps) {
  const blocks = parseMarkdown(content);
  if (!content.trim()) {
    return <p className="markdownPreviewEmpty">暂无 Markdown 内容。</p>;
  }
  return (
    <div className="markdownPreview">
      {truncated && <p className="markdownPreviewWarning">内容较大，当前仅展示前半部分。</p>}
      {blocks.map((block) => renderBlock(block))}
    </div>
  );
}

function parseMarkdown(content: string): MarkdownBlock[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  function nextKey(kind: string) {
    return `${kind}-${blocks.length}-${index}`;
  }

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^```(\S*)\s*$/);
    if (fence) {
      const start = index;
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ kind: "code", language: fence[1] || undefined, lines: codeLines, key: `code-${start}` });
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim(), key: nextKey("heading") });
      index += 1;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ kind: "rule", key: nextKey("rule") });
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const rows: string[][] = [];
      rows.push(splitTableRow(lines[index]));
      index += 2;
      while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push({ kind: "table", rows, key: nextKey("table") });
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push({ kind: "quote", lines: quoteLines, key: nextKey("quote") });
      continue;
    }

    const unordered = /^\s*[-*]\s+/.test(line);
    const ordered = /^\s*\d+\.\s+/.test(line);
    if (unordered || ordered) {
      const items: string[] = [];
      const itemPattern = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/;
      while (index < lines.length && itemPattern.test(lines[index])) {
        items.push(lines[index].replace(itemPattern, "").trim());
        index += 1;
      }
      blocks.push({ kind: "list", ordered, items, key: nextKey("list") });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length && lines[index].trim()) {
      if (/^```/.test(lines[index]) || /^(#{1,4})\s+/.test(lines[index]) || /^\s*[-*]\s+/.test(lines[index]) || /^\s*\d+\.\s+/.test(lines[index])) {
        break;
      }
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ kind: "paragraph", lines: paragraphLines, key: nextKey("paragraph") });
  }

  return blocks;
}

function isTableStart(lines: string[], index: number) {
  if (!/^\s*\|.*\|\s*$/.test(lines[index] ?? "")) return false;
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1] ?? "");
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderBlock(block: MarkdownBlock) {
  if (block.kind === "heading") {
    const HeadingTag = `h${Math.min(block.level + 2, 6)}` as "h3" | "h4" | "h5" | "h6";
    return <HeadingTag key={block.key}>{renderInline(block.text)}</HeadingTag>;
  }
  if (block.kind === "paragraph") {
    return <p key={block.key}>{renderInline(block.lines.join(" "))}</p>;
  }
  if (block.kind === "list") {
    const ListTag = block.ordered ? "ol" : "ul";
    return (
      <ListTag key={block.key}>
        {block.items.map((item, index) => (
          <li key={`${block.key}-${index}`}>{renderInline(item)}</li>
        ))}
      </ListTag>
    );
  }
  if (block.kind === "code") {
    return (
      <figure className="markdownCodeBlock" key={block.key}>
        {block.language && <figcaption>{block.language}</figcaption>}
        <pre>
          <code>{block.lines.join("\n")}</code>
        </pre>
      </figure>
    );
  }
  if (block.kind === "quote") {
    return <blockquote key={block.key}>{renderLinesWithBreaks(block.lines)}</blockquote>;
  }
  if (block.kind === "table") {
    const [head, ...body] = block.rows;
    return (
      <div className="markdownTableWrap" key={block.key}>
        <table>
          <thead>
            <tr>
              {head.map((cell, index) => (
                <th key={`${block.key}-head-${index}`}>{renderInline(cell)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={`${block.key}-row-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${block.key}-${rowIndex}-${cellIndex}`}>{renderInline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <hr key={block.key} />;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // 裸 URL 也自动转链接(排除中英文标点结尾),聊天里的 PR 链接才点得动。
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s)）\]」》。，、;；!！?？]+)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={`code-${match.index}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`strong-${match.index}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("http")) {
      nodes.push(
        <a href={token} target="_blank" rel="noreferrer" key={`url-${match.index}`}>
          {token}
        </a>
      );
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = link?.[2] ?? "#";
      nodes.push(
        <a href={href} target="_blank" rel="noreferrer" key={`link-${match.index}`}>
          {link?.[1] ?? href}
        </a>
      );
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes.map((node, index) => <Fragment key={index}>{node}</Fragment>);
}

function renderLinesWithBreaks(lines: string[]) {
  return lines.flatMap((line, index) => {
    const nodes = renderInline(line);
    if (index === 0) return nodes;
    return [<br key={`br-${index}`} />, ...nodes];
  });
}
