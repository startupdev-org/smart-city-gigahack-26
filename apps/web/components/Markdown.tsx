"use client";

import React from "react";

type Source = {
  document?: string;
  url?: string | null;
  quote?: string;
  page?: number | null;
};

export function annexLabel(index: number, source?: Source, lang: "ro" | "ru" | "en" = "ro"): string {
  const prefix = lang === "ru" ? "Прил." : lang === "en" ? "Ann." : "Anexa";
  const raw = (source?.document || "").trim();
  if (!raw) return `${prefix} ${index}`;
  // Prefer short hint from title
  const short = raw
    .replace(/\s+/g, " ")
    .replace(/^ANUN[ȚT]\s*[-–:]?\s*/i, "")
    .slice(0, 28);
  return short ? `${prefix} ${index}` : `${prefix} ${index}`;
}

/** Lightweight Markdown with annex-style citation chips. */
export function Markdown({
  text,
  sources = [],
  lang = "ro",
}: {
  text: string;
  sources?: Source[];
  lang?: "ro" | "ru" | "en";
}) {
  const cleaned = scrubPlaceholders(text || "");
  const lines = cleaned.split("\n");
  const blocks: React.ReactNode[] = [];
  let listBuf: { ordered: boolean; items: string[] } | null = null;

  const flushList = () => {
    if (!listBuf) return;
    const Tag = listBuf.ordered ? "ol" : "ul";
    blocks.push(
      <Tag key={`l-${blocks.length}`} className="md-list">
        {listBuf.items.map((it, i) => (
          <li key={i}>{inline(it, sources, lang)}</li>
        ))}
      </Tag>
    );
    listBuf = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const ul = line.match(/^\s*[-*•]\s+(.+)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ul || ol) {
      const ordered = Boolean(ol);
      const item = (ul || ol)![1];
      if (!listBuf || listBuf.ordered !== ordered) {
        flushList();
        listBuf = { ordered, items: [item] };
      } else listBuf.items.push(item);
      continue;
    }
    flushList();
    if (!line.trim()) {
      blocks.push(<div key={`sp-${i}`} className="md-sp" />);
      continue;
    }
    blocks.push(
      <p key={`p-${i}`} className="md-p">
        {inline(line, sources, lang)}
      </p>
    );
  }
  flushList();
  return <div className="md">{blocks}</div>;
}

function scrubPlaceholders(s: string): string {
  return s
    .replace(/\[expire_date\]/gi, "")
    .replace(/\[featured_image\]/gi, "")
    .replace(/§LINK§[^§\n]*§?/g, "")
    .replace(/Download is available until[^\n]*/gi, "")
    .replace(/Disponibil[ăa]\s+pân[aă]\s+la\s*\[[^\]]*\]/gi, "")
    .replace(/https?:\/\/[^\s)>\]]+/gi, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function inline(
  s: string,
  sources: Source[],
  lang: "ro" | "ru" | "en"
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const cleaned = scrubPlaceholders(s);
  const re =
    /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\[\d+\])/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(cleaned))) {
    if (m.index > last) parts.push(cleaned.slice(last, m.index));
    const tok = m[0];
    if (/^\[\d+\]$/.test(tok)) {
      const n = Number(tok.slice(1, -1));
      const src = sources[n - 1];
      const label = annexLabel(n, src, lang);
      const node = (
        <a
          key={key++}
          className="cite-tag"
          href={src?.url || undefined}
          target="_blank"
          rel="noreferrer"
          title={src?.quote || src?.document || label}
          onClick={(e) => {
            if (!src?.url) e.preventDefault();
          }}
        >
          {label}
        </a>
      );
      parts.push(node);
    } else if (tok.startsWith("**")) {
      parts.push(<strong key={key++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*")) {
      parts.push(<em key={key++}>{tok.slice(1, -1)}</em>);
    } else if (tok.startsWith("`")) {
      parts.push(<code key={key++}>{tok.slice(1, -1)}</code>);
    } else if (tok.startsWith("[")) {
      const mm = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (mm) {
        parts.push(
          <a key={key++} href={mm[2]} target="_blank" rel="noreferrer">
            {mm[1]}
          </a>
        );
      } else parts.push(tok);
    }
    last = m.index + tok.length;
  }
  if (last < cleaned.length) parts.push(cleaned.slice(last));
  return parts;
}
