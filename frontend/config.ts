/**
 * 全局路径配置
 * 所有静态资源路径都使用此前缀
 */

// 获取 Vite 配置的 base 路径
export const BASE_URL = import.meta.env.BASE_URL;

/**
 * 获取完整的资源路径
 * @param path 相对于 public 的路径，以 / 开头，如 /images/logo.png
 * @returns 完整路径，如 /ai-eido/images/logo.png
 */
export const getAssetUrl = (path: string): string => {
  // 确保路径以 / 开头
  const normalizedPath = path.startsWith('/') ? path.slice(1) : path;
  return `${BASE_URL}${normalizedPath}`;
};

// 导出常用路径前缀，方便直接使用
export const IMAGES_URL = `${BASE_URL}images/`;
