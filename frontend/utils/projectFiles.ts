import { isProjectOutputPath } from './projectOutputPath.js';

export { isProjectOutputPath };

/** Project 资料接口当前允许从会话 outputs/ 目录导入的文件扩展名。 */
export const PROJECT_MATERIAL_EXTENSIONS = [
  'md', 'pdf', 'csv', 'xls', 'xlsx',
  'html', 'htm', 'txt', 'json',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
  'doc', 'docx', 'ppt', 'pptx',
] as const;

const PROJECT_MATERIAL_EXTENSION_SET = new Set<string>(PROJECT_MATERIAL_EXTENSIONS);
const ACTIVE_WORKSPACE_EXTENSION_SET = new Set([
  'html', 'htm', 'xhtml', 'svg', 'xml', 'mhtml', 'mht',
  'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
]);
export const PROJECT_MATERIAL_ACCEPT = PROJECT_MATERIAL_EXTENSIONS
  .map((extension) => `.${extension}`)
  .join(',');

/**
 * 只有会话根目录的 outputs/ 才是可沉淀到 Project 的生成结果目录。
 * 同时兼容服务端/Agent 返回相对路径和位于会话工作区内的绝对路径。
 */
export function isSupportedProjectMaterial(
  path: string,
  displayName?: string,
  sessionId?: string,
): boolean {
  if (!isProjectOutputPath(path, sessionId)) return false;
  const name = displayName || path.split('/').pop() || '';
  const extension = name.split('.').pop()?.toLowerCase() || '';
  return PROJECT_MATERIAL_EXTENSION_SET.has(extension);
}

/** Generated active content must be downloaded, never same-origin navigated. */
export function shouldForceWorkspaceDownload(path: string): boolean {
  const withoutQuery = path.split(/[?#]/, 1)[0] || '';
  const extension = withoutQuery.split('/').pop()?.split('.').pop()?.toLowerCase() || '';
  return ACTIVE_WORKSPACE_EXTENSION_SET.has(extension);
}
