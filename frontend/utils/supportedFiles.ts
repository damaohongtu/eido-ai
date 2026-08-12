/** Keep this list aligned with backend/app/services/supported_files.py. */
export const SUPPORTED_FILE_EXTENSIONS = [
  // Documents and text
  'md', 'pdf', 'txt', 'log', 'rtf', 'doc', 'docx', 'odt',
  'ppt', 'pptx', 'odp', 'epub',
  // Data and spreadsheets
  'csv', 'tsv', 'xls', 'xlsx', 'xlsm', 'xlsb', 'ods',
  'json', 'jsonl', 'yaml', 'yml', 'xml', 'sql', 'parquet',
  // Code and configuration
  'py', 'js', 'jsx', 'ts', 'tsx', 'java', 'go', 'rs', 'c', 'h', 'cpp', 'hpp',
  'sh', 'toml', 'ini', 'conf', 'properties',
  // Browser artifacts, images and archives
  'html', 'htm', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'svg',
  'zip', 'tar', 'gz', 'tgz', '7z',
] as const;

const SUPPORTED_FILE_EXTENSION_SET = new Set<string>(SUPPORTED_FILE_EXTENSIONS);

export const SUPPORTED_FILE_ACCEPT = SUPPORTED_FILE_EXTENSIONS
  .map((extension) => `.${extension}`)
  .join(',');

export const SUPPORTED_FILE_HINT = '文档、文本/日志、表格、代码、图片或压缩包';

export function isSupportedFileName(name: string): boolean {
  const extension = name.split('.').pop()?.toLowerCase() || '';
  return SUPPORTED_FILE_EXTENSION_SET.has(extension);
}
