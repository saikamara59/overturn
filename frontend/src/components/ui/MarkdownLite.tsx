import { Fragment } from 'react';

/** Inline pass: **bold** only — built as React nodes, never HTML. */
function inline(text: string, key: number): JSX.Element {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <Fragment key={key}>
      {parts.map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : p))}
    </Fragment>
  );
}

type Block =
  | { kind: 'h'; text: string }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'p'; lines: string[] };

function parse(text: string): Block[] {
  const blocks: Block[] = [];
  for (const line of text.split('\n')) {
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    if (heading) {
      blocks.push({ kind: 'h', text: heading[1].replace(/\*\*/g, '') });
    } else if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol';
      const item = (bullet ?? numbered)![1];
      if (last?.kind === kind) last.items.push(item);
      else blocks.push({ kind, items: [item] });
    } else if (!line.trim()) {
      if (last?.kind === 'p') blocks.push({ kind: 'p', lines: [] });
    } else if (last?.kind === 'p') {
      last.lines.push(line);
    } else {
      blocks.push({ kind: 'p', lines: [line] });
    }
  }
  return blocks.filter((b) => b.kind !== 'p' || b.lines.length > 0);
}

/**
 * Minimal display-only markdown renderer for LLM output (headings, bold,
 * bullet/numbered lists, paragraphs). Everything else is plain text; no
 * HTML is ever parsed, so model output cannot inject markup.
 */
export function MarkdownLite({ text }: { text: string }) {
  return (
    <div className="md-lite">
      {parse(text).map((b, i) => {
        if (b.kind === 'h') return <div key={i} className="md-h">{b.text}</div>;
        if (b.kind === 'p') {
          return (
            <p key={i} className="md-p">
              {b.lines.map((l, j) => (
                <Fragment key={j}>
                  {j > 0 && ' '}
                  {inline(l, j)}
                </Fragment>
              ))}
            </p>
          );
        }
        const items = b.items.map((it, j) => <li key={j}>{inline(it, j)}</li>);
        return b.kind === 'ul'
          ? <ul key={i} className="md-list">{items}</ul>
          : <ol key={i} className="md-list">{items}</ol>;
      })}
    </div>
  );
}
