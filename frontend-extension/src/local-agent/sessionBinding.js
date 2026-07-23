/**
 * Resolve the immutable directory/endpoint binding for one local conversation.
 * The current directory is consulted only when no binding exists yet.
 */
export function resolveSessionBinding(existing, endpoint, initialDirectory) {
  if (existing?.endpoint && existing.endpoint !== endpoint) {
    throw new Error('该本机会话绑定到另一个 OpenCode 地址，请切回原地址或新建会话');
  }
  if (existing?.directory) {
    return { ...existing, endpoint };
  }
  if (!initialDirectory) {
    throw new Error('OpenCode 未返回当前工作目录');
  }
  return { directory: initialDirectory, endpoint };
}
