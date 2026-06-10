interface HighlightedTextProps {
  text: string;
  query?: string;
}

export function HighlightedText({ text, query }: HighlightedTextProps) {
  const needle = query?.trim();
  if (!needle) {
    return <>{text || " "}</>;
  }

  const lowerText = text.toLocaleLowerCase();
  const lowerNeedle = needle.toLocaleLowerCase();
  const parts: Array<{ text: string; match: boolean }> = [];
  let cursor = 0;

  while (cursor < text.length) {
    const index = lowerText.indexOf(lowerNeedle, cursor);
    if (index < 0) {
      parts.push({ text: text.slice(cursor), match: false });
      break;
    }
    if (index > cursor) {
      parts.push({ text: text.slice(cursor, index), match: false });
    }
    parts.push({ text: text.slice(index, index + needle.length), match: true });
    cursor = index + needle.length;
  }

  if (!parts.length) {
    return <>{text || " "}</>;
  }

  return (
    <>
      {parts.map((part, index) =>
        part.match ? (
          <mark className="searchHit" key={`${part.text}-${index}`}>
            {part.text}
          </mark>
        ) : (
          part.text
        )
      )}
    </>
  );
}
