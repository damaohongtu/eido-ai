"""
技能 API 端点

技能维护在本地 .claude/skills/ 目录，分两区：
  - system/<id>/       admin 上传 / 内置，所有用户只读可见
  - users/<safe>/<id>/ 普通用户私有，仅本人可见可改

所有写操作都要求登录；admin 通过 EIDO_ADMIN_USERS 白名单识别。
"""
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.services.claude_skill_service import get_claude_skill_service
from app.services.skill_management_service import get_skill_management_service

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".zip", ".md", ".skill"}


# ------------------------------------------------------------------ #
#  Response Schemas                                                    #
# ------------------------------------------------------------------ #

class SkillResponse(BaseModel):
    """单个技能的响应体，兼容前端 Skill interface"""
    id: str
    name: str
    description: str
    icon: Optional[str] = None
    output_schema: Optional[dict] = None
    is_system: bool = True
    is_public: bool = True
    is_active: bool = True
    version: int = 1
    usage_count: int = 0
    user_id: Optional[str] = None
    owner_type: str = "system"
    owner_user_id: Optional[str] = None
    is_owner: bool = False
    created_at: str
    updated_at: str
    allowed_tools: List[str] = []
    tools: list = []
    agents: list = []
    detail: Optional[str] = None  # SKILL.md 完整内容


class SkillListResponse(BaseModel):
    items: List[SkillResponse]
    total: int


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    content: str
    icon: Optional[str] = None


class UpdateSkillRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    icon: Optional[str] = None


class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileDeleteRequest(BaseModel):
    path: str


class FileMkdirRequest(BaseModel):
    path: str


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _meta_to_response(meta, *, viewer_user_id: Optional[str] = None) -> SkillResponse:
    """把 SkillMeta 转成响应；is_owner 表示 viewer 是否对该技能有写权限。"""
    if meta.owner_type == "system":
        is_owner = settings.is_admin(viewer_user_id)
    elif meta.owner_type == "user":
        is_owner = bool(viewer_user_id) and (meta.owner_user_id == viewer_user_id)
    else:
        is_owner = False
    return SkillResponse(
        id=meta.id,
        name=meta.name,
        description=meta.description,
        icon=meta.icon,
        output_schema=meta.output_schema,
        is_system=meta.is_system,
        is_public=meta.is_public,
        is_active=meta.is_active,
        version=meta.version,
        usage_count=meta.usage_count,
        user_id=meta.user_id,
        owner_type=meta.owner_type,
        owner_user_id=meta.owner_user_id,
        is_owner=is_owner,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
        allowed_tools=meta.allowed_tools,
        tools=meta.tools,
        agents=meta.agents,
        detail=meta.content,
    )


# ------------------------------------------------------------------ #
#  Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.get("/", response_model=SkillListResponse)
async def list_skills(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    search: Optional[str] = None,
    is_system: Optional[bool] = None,
    user_id: str = Depends(get_current_user_id),
):
    """获取技能列表：system 区 + 当前用户私有区。"""
    svc = get_claude_skill_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="技能服务未初始化")

    skills = svc.scan_skills(user_id=user_id)

    # 过滤
    if search:
        q = search.lower()
        skills = [s for s in skills if q in s.name.lower() or q in s.description.lower()]
    if is_system is not None:
        skills = [s for s in skills if s.is_system == is_system]

    total = len(skills)
    skills = skills[skip: skip + limit]

    logger.info(f"返回 {len(skills)} 个技能，共 {total} 个 user={user_id}")
    return SkillListResponse(
        items=[_meta_to_response(s, viewer_user_id=user_id) for s in skills],
        total=total,
    )


@router.post("/upload", response_model=SkillResponse)
async def upload_skill(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """上传技能文件。支持 .zip、.md、.skill 格式，最大 10 MB。

    admin 上传 → system/<id>；普通用户上传 → users/<self>/<id>。
    """
    svc = get_claude_skill_service()
    mgmt_svc = get_skill_management_service()
    if svc is None or mgmt_svc is None:
        raise HTTPException(status_code=503, detail="技能服务未初始化")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，仅支持: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10 MB 限制")

    try:
        target_root = mgmt_svc._resolve_owner_dir(user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    try:
        if ext == ".zip" or ext == ".skill":
            meta = _extract_zip_skill(
                content, file.filename or "skill.zip", target_root, user_id
            )
        else:  # .md
            meta = _save_md_skill(
                content, file.filename or "skill.md", target_root, user_id
            )
        return _meta_to_response(meta, viewer_user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("上传技能失败")
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """获取单个技能详情（system 任意人可读，私有仅 owner 可读）。"""
    svc = get_claude_skill_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="技能服务未初始化")

    try:
        meta = svc.get_skill(skill_id, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")

    return _meta_to_response(meta, viewer_user_id=user_id)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """删除技能。系统技能仅 admin 可删；私有技能仅 owner 可删。"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")

    try:
        mgmt_svc.delete_skill(user_id, skill_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/", response_model=SkillResponse)
async def create_skill(
    request: CreateSkillRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建新技能。admin → system/，普通用户 → 私有区。"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        meta = mgmt_svc.create_skill(
            user_id=user_id,
            name=request.name,
            description=request.description,
            content=request.content,
            icon=request.icon,
        )
        return _meta_to_response(meta, viewer_user_id=user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("创建技能失败")
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    request: UpdateSkillRequest,
    user_id: str = Depends(get_current_user_id),
):
    """更新技能元数据或正文。"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        meta = mgmt_svc.update_skill(
            user_id=user_id,
            skill_id=skill_id,
            name=request.name,
            description=request.description,
            content=request.content,
            icon=request.icon,
        )
        return _meta_to_response(meta, viewer_user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{skill_id}/files")
async def list_files(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """列出技能目录下的文件树"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        return mgmt_svc.list_files(user_id, skill_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{skill_id}/files/read")
async def read_file(
    skill_id: str,
    path: str = Query(...),
    user_id: str = Depends(get_current_user_id),
):
    """读取技能目录下指定文件"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        return mgmt_svc.read_file(user_id, skill_id, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{skill_id}/files/write")
async def write_file(
    skill_id: str,
    request: FileWriteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """向技能目录写入文件"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        mgmt_svc.write_file(user_id, skill_id, request.path, request.content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{skill_id}/files/delete")
async def delete_file(
    skill_id: str,
    request: FileDeleteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """删除技能目录下指定文件"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        mgmt_svc.delete_file(user_id, skill_id, request.path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {request.path}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"删除失败: {e}")


@router.post("/{skill_id}/files/mkdir")
async def mkdir(
    skill_id: str,
    request: FileMkdirRequest,
    user_id: str = Depends(get_current_user_id),
):
    """在技能目录下创建子目录"""
    mgmt_svc = get_skill_management_service()
    if not mgmt_svc:
        raise HTTPException(status_code=503, detail="SkillManagementService not initialized")
    try:
        mgmt_svc.mkdir(user_id, skill_id, request.path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _slug(name: str) -> str:
    """将名称转为目录名 slug"""
    s = re.sub(r"[^\w\s-]", "", name)
    s = re.sub(r"[-\s]+", "-", s).strip().lower()
    return s or "skill"


def _parse_name_from_frontmatter(content: bytes) -> Optional[str]:
    """从 SKILL.md 的 frontmatter 解析 name"""
    try:
        text = content.decode("utf-8")
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end > 0:
                import yaml
                meta = yaml.safe_load(text[4:end]) or {}
                return meta.get("name")
    except Exception:
        pass
    return None


def _extract_zip_skill(content: bytes, filename: str, target_root: Path, user_id: str):
    """从 zip 解压并安装技能到 target_root（owner 区域）"""
    target_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
        names = zf.namelist()
        # 查找 SKILL.md
        skill_md_path = None
        for n in names:
            nnorm = n.replace("\\", "/").strip("/")
            if nnorm == "SKILL.md" or nnorm.endswith("/SKILL.md"):
                skill_md_path = n
                break
        if not skill_md_path:
            raise ValueError("ZIP 中未找到 SKILL.md")

        # 优先从 SKILL.md frontmatter 解析技能名作为目录名，避免使用 Archive 等通用名
        skill_md_content = zf.read(skill_md_path)
        name_from_fm = _parse_name_from_frontmatter(skill_md_content)
        if name_from_fm:
            skill_id = _slug(name_from_fm) or "uploaded-skill"
        else:
            skill_id = None

        # 确定解压前缀和 fallback 目录名
        path_parts = skill_md_path.replace("\\", "/").split("/")
        if len(path_parts) > 1:
            prefix = path_parts[0] + "/"
            fallback_id = _slug(path_parts[0]) or "uploaded-skill"
        else:
            prefix = ""
            fallback_id = Path(filename).stem
            if not re.match(r"^[\w-]+$", fallback_id):
                fallback_id = "uploaded-skill"

        if not skill_id:
            skill_id = fallback_id

        target_dir = target_root / skill_id
        if target_dir.exists():
            raise ValueError(f"技能目录已存在: {skill_id}")

        target_dir.mkdir(parents=True)
        for n in names:
            if n.endswith("/"):
                continue
            if prefix and not n.replace("\\", "/").startswith(prefix):
                continue
            data = zf.read(n)
            rel = n.replace("\\", "/")[len(prefix):] if prefix else n
            out = target_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)

    svc = get_claude_skill_service()
    return svc.get_skill(skill_id, user_id=user_id)


def _save_md_skill(content: bytes, filename: str, target_root: Path, user_id: str):
    """将 .md 文件保存为技能到 target_root（owner 区域）"""
    target_root.mkdir(parents=True, exist_ok=True)

    skill_id = _slug(Path(filename).stem) or "uploaded-skill"
    name = _parse_name_from_frontmatter(content) or skill_id
    skill_id = _slug(name) or skill_id

    target_dir = target_root / skill_id
    if target_dir.exists():
        raise ValueError(f"技能目录已存在: {skill_id}")

    target_dir.mkdir(parents=True)
    (target_dir / "SKILL.md").write_bytes(content)

    svc = get_claude_skill_service()
    return svc.get_skill(skill_id, user_id=user_id)
