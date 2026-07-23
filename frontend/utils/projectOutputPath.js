const SAFE_SESSION_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** Return whether an Agent-reported path can represent the session root outputs tree. */
export function isProjectOutputPath(path, sessionId) {
  const normalized = path.trim().replace(/\\/g, '/').replace(/\/+/g, '/');
  if (!normalized || normalized.split('/').includes('..')) return false;
  const relative = normalized.replace(/^\.\//, '');
  if (relative.startsWith('outputs/')) return true;

  // Absolute paths are supported only for the known server workspace layout.
  // This avoids offering promotion for arbitrary /tmp/outputs or another
  // conversation's output path; the backend remains the authority as well.
  const isAbsolute = normalized.startsWith('/') || /^[a-z]:\//i.test(normalized);
  if (!isAbsolute) return false;
  if (sessionId) {
    if (!SAFE_SESSION_ID.test(sessionId)) return false;
    return normalized.includes(`/workspaces/${sessionId}/outputs/`);
  }
  return /\/workspaces\/[A-Za-z0-9_-]{1,64}\/outputs\//.test(normalized);
}
