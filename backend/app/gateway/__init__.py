"""
Gateway 模块：
- 仅在 EIDO_SANDBOX_MODE=docker 时启用
- 负责 CAS 鉴权、用户沙箱容器生命周期、业务 API 反向代理（含 SSE 透传）
- 单租户开发/单镜像部署仍走 backend/app/main.py 内置完整路由（兼容路径）
"""
