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
const BROWSER_PREVIEW_EXTENSION_SET = new Set([
  'html', 'htm', 'xht', 'xhtml', 'svg', 'xml', 'xsl', 'xslt', 'mhtml', 'mht',
  'pdf', 'txt', 'md', 'csv', 'json',
  'png', 'jpg', 'jpeg', 'gif', 'webp',
]);
const BROWSER_IMAGE_EXTENSION_SET = new Set([
  'svg', 'png', 'jpg', 'jpeg', 'gif', 'webp',
]);
const ACTIVE_WORKSPACE_EXTENSION_SET = new Set([
  'html', 'htm', 'xht', 'xhtml', 'svg', 'svgz', 'xml', 'xsl', 'xslt', 'mhtml', 'mht',
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

/** 后端可安全 inline、且浏览器能够直接展示的文件类型。 */
export function canPreviewInBrowser(path: string): boolean {
  const withoutQuery = path.split(/[?#]/, 1)[0] || '';
  const extension = withoutQuery.split('/').pop()?.split('.').pop()?.toLowerCase() || '';
  return BROWSER_PREVIEW_EXTENSION_SET.has(extension);
}

/** 可安全放进 img 元素的浏览器图片类型；HTML/PDF 等应打开预览页。 */
export function canRenderAsBrowserImage(path: string): boolean {
  const withoutQuery = path.split(/[?#]/, 1)[0] || '';
  const extension = withoutQuery.split('/').pop()?.split('.').pop()?.toLowerCase() || '';
  return BROWSER_IMAGE_EXTENSION_SET.has(extension);
}

/** 未显式请求安全预览时，这些格式必须保持下载响应。 */
export function shouldForceWorkspaceDownload(path: string): boolean {
  const withoutQuery = path.split(/[?#]/, 1)[0] || '';
  const extension = withoutQuery.split('/').pop()?.split('.').pop()?.toLowerCase() || '';
  return ACTIVE_WORKSPACE_EXTENSION_SET.has(extension);
}
