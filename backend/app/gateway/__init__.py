"""
Gateway 模块：
- 仅在 EIDO_SANDBOX_MODE=docker|k8s 时启用
- 负责 CAS 鉴权、用户沙盒生命周期（docker 容器或 K8s Pod）、业务 API 反向代理（含 SSE 透传）
- 单租户开发/单镜像部署仍走 backend/app/main.py 内置完整路由（兼容路径）
"""
