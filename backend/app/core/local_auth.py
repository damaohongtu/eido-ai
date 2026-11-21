"""本地账号密码认证（AUTH_MODE=local）。

密码不以明文落盘：.env 中仅保存 PBKDF2-SHA256 哈希，
格式 ``pbkdf2:sha256:<iterations>$<salt-hex>$<hash-hex>``。

部署时生成哈希（密码经 stdin 传入，避免进入 shell 历史）::

    python3 -c "from app.core.local_auth import hash_password; print(hash_password(input()))"
"""

import hashlib
import hmac
import logging
import re
import secrets
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

_HASH_RE = re.compile(r"^pbkdf2:sha256:(\d+)\$([0-9a-f]+)\$([0-9a-f]+)$")
DEFAULT_ITERATIONS = 600_000


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    salt_hex: str | None = None,
) -> str:
    """生成可存储的 PBKDF2 哈希串。"""
    salt = bytes.fromhex(salt_hex) if salt_hex is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2:sha256:{iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """恒定时间校验密码；格式非法一律 False 并告警。"""
    match = _HASH_RE.match(stored.strip())
    if not match:
        logger.warning("LOCAL_AUTH_PASSWORD_HASH 格式非法（应为 pbkdf2:sha256:<iter>$<salt>$<hash>）")
        return False
    iterations, salt_hex, expected_hex = int(match.group(1)), match.group(2), match.group(3)
    try:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), iterations
        )
    except (ValueError, OverflowError):
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


class LoginThrottle:
    """每 IP 登录失败滑动窗口限速（防在线爆破与 PBKDF2 CPU 滥用）。

    单进程内存实现，重启即清零——足够单机部署使用。
    """

    def __init__(self, max_failures: int = 10, window_seconds: int = 300) -> None:
        self._max_failures = max_failures
        self._window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, now: float) -> deque[float]:
        failures = self._failures[ip]
        while failures and now - failures[0] > self._window:
            failures.popleft()
        return failures

    def is_blocked(self, ip: str, *, now: float | None = None) -> bool:
        failures = self._failures.get(ip)
        if not failures:
            return False
        current = time.monotonic() if now is None else now
        return len(self._prune(ip, current)) >= self._max_failures

    def record_failure(self, ip: str, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self._prune(ip, current).append(current)

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)
