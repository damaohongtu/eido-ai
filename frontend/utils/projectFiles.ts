import { isProjectOutputPath } from './projectOutputPath.js';
import { SUPPORTED_FILE_ACCEPT, SUPPORTED_FILE_EXTENSIONS } from './supportedFiles';

export { isProjectOutputPath };

/** Project 资料接口当前允许从会话 outputs/ 目录导入的文件扩展名。 */
export const PROJECT_MATERIAL_EXTENSIONS = SUPPORTED_FILE_EXTENSIONS;

const PROJECT_MATERIAL_EXTENSION_SET = new Set<string>(PROJECT_MATERIAL_EXTENSIONS);
const BROWSER_PREVIEW_EXTENSION_SET = new Set([
  'html', 'htm', 'xht', 'xhtml', 'svg', 'xml', 'xsl', 'xslt', 'mhtml', 'mht',
  'pdf', 'txt', 'log', 'md', 'csv', 'tsv', 'json', 'jsonl', 'yaml', 'yml',
  'py', 'js', 'jsx', 'ts', 'tsx', 'java', 'go', 'rs', 'c', 'h', 'cpp', 'hpp',
  'sh', 'toml', 'ini', 'conf', 'properties',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff',
]);
const BROWSER_IMAGE_EXTENSION_SET = new Set([
  'svg', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff',
]);
const ACTIVE_WORKSPACE_EXTENSION_SET = new Set([
  'html', 'htm', 'xht', 'xhtml', 'svg', 'svgz', 'xml', 'xsl', 'xslt', 'mhtml', 'mht',
  'doc', 'docx', 'odt', 'rtf', 'ppt', 'pptx', 'odp',
  'xls', 'xlsx', 'xlsm', 'xlsb', 'ods', 'epub', 'zip', 'tar', 'gz', 'tgz', '7z',
]);
export const PROJECT_MATERIAL_ACCEPT = SUPPORTED_FILE_ACCEPT;

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
