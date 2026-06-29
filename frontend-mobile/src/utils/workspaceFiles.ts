import type { Message } from '../shared';

const DOWNLOADABLE_FILE_EXTENSIONS = [
  'md', 'pdf', 'csv', 'xls', 'xlsx', 'html', 'htm', 'txt', 'json',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
];
const DOWNLOADABLE_FILE_SOURCE =
  `((?:/|(?:outputs?|uploads|\\.claude/skills/[^\\s/]+/output)/)[^\\s"'()\`<>]+\\.(?:${DOWNLOADABLE_FILE_EXTENSIONS.join('|')}))`;
const DOWNLOADABLE_FILE_PATTERN = new RegExp(DOWNLOADABLE_FILE_SOURCE, 'gi');
const SINGLE_DOWNLOADABLE_FILE_PATTERN = new RegExp(`^${DOWNLOADABLE_FILE_SOURCE}$`, 'i');
const FILE_LINK_PATTERN = /\[[^\]]+\]\(([^)\s]+)\)/g;
const GENERATED_FILE_HINT_PATTERN = new RegExp(
  `(?:File created successfully at:|写入文件:|写入到文件:|保存为图片:|已保存为图片:|已导出到:|导出到:|生成文件:|输出文件:|保存到:|结果文件:)\\s*(${DOWNLOADABLE_FILE_SOURCE})`,
  'gi'
);
export const IMAGE_FILE_PATTERN = /\.(png|jpg|jpeg|gif|webp|svg)$/i;

export interface GeneratedFile {
  path: string;
  name: string;
  isImage: boolean;
}

export function normalizeWorkspacePath(rawPath: string): string | null {
  const trimmed = rawPath.trim().replace(/^<|>$/g, '').replace(/[),.;:]+$/g, '');
  if (!trimmed) return null;
  if (/^(https?:|data:|mailto:|#)/i.test(trimmed)) return null;
  if (!SINGLE_DOWNLOADABLE_FILE_PATTERN.test(trimmed)) return null;
  return trimmed;
}

function collectFileMatches(input: string, matcher: RegExp): string[] {
  const matches: string[] = [];
  matcher.lastIndex = 0;
  for (const match of input.matchAll(matcher)) {
    const candidate = match[1] || match[0];
    const normalized = normalizeWorkspacePath(candidate);
    if (normalized) matches.push(normalized);
  }
  matcher.lastIndex = 0;
  return matches;
}

export function extractGeneratedFiles(message: Message): GeneratedFile[] {
  const unique = new Map<string, GeneratedFile>();
  const addPath = (p: string) => {
    if (unique.has(p)) return;
    const segments = p.split('/');
    const name = segments[segments.length - 1] || p;
    unique.set(p, { path: p, name, isImage: IMAGE_FILE_PATTERN.test(p) });
  };
  collectFileMatches(message.content || '', FILE_LINK_PATTERN).forEach(addPath);
  collectFileMatches(message.content || '', DOWNLOADABLE_FILE_PATTERN).forEach(addPath);
  collectFileMatches(message.thinking || '', GENERATED_FILE_HINT_PATTERN).forEach(addPath);
  (message.thinkingLog || []).forEach((log) => {
    collectFileMatches(log, GENERATED_FILE_HINT_PATTERN).forEach(addPath);
  });
  return [...unique.values()];
}

export function isWorkspaceFileLink(href?: string): boolean {
  if (!href) return false;
  return normalizeWorkspacePath(href) !== null;
}
