"""
技能 API 端点

技能由本地 .claude/skills/ 目录维护。支持通过上传文件添加技能。
"""
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.core.config import settings
from app.services.claude_skill_service import get_claude_skill_service

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
    created_at: str
    updated_at: str
    allowed_tools: List[str] = []
    tools: list = []
    agents: list = []


class SkillListResponse(BaseModel):
    items: List[SkillResponse]
    total: int


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _meta_to_response(meta) -> SkillResponse:
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
        created_at=meta.created_at,
        updated_at=meta.updated_at,
        allowed_tools=meta.allowed_tools,
        tools=meta.tools,
        agents=meta.agents,
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
):
    """获取技能列表（来自本地 .claude/skills/ 目录）"""
    svc = get_claude_skill_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="技能服务未初始化")

    skills = svc.scan_skills()

    # 过滤
    if search:
        q = search.lower()
        skills = [s for s in skills if q in s.name.lower() or q in s.description.lower()]
    if is_system is not None:
        skills = [s for s in skills if s.is_system == is_system]

    total = len(skills)
    skills = skills[skip: skip + limit]

    logger.info(f"返回 {len(skills)} 个技能，共 {total} 个")
    return SkillListResponse(items=[_meta_to_response(s) for s in skills], total=total)


@router.post("/upload", response_model=SkillResponse)
async def upload_skill(file: UploadFile = File(...)):
    """上传技能文件。支持 .zip、.md、.skill 格式，最大 10 MB。"""
    svc = get_claude_skill_service()
    if svc is None:
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

    skills_dir = Path(settings.SKILLS_DIR)
    skills_dir.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".zip" or ext == ".skill":
            meta = _extract_zip_skill(content, file.filename or "skill.zip", skills_dir)
        else:  # .md
            meta = _save_md_skill(content, file.filename or "skill.md", skills_dir)
        return _meta_to_response(meta)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("上传技能失败")
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str):
    """获取单个技能详情"""
    svc = get_claude_skill_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="技能服务未初始化")

    try:
        meta = svc.get_skill(skill_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")

    logger.info(f"返回技能: {meta.name}")
    return _meta_to_response(meta)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str):
    """删除用户通过上传安装的技能（内置技能不可删除）。"""
    svc = get_claude_skill_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="技能服务未初始化")

    try:
        svc.delete_user_upload(skill_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except PermissionError:
        raise HTTPException(status_code=403, detail="仅支持删除通过上传安装的技能")
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


def _extract_zip_skill(content: bytes, filename: str, skills_dir: Path):
    """从 zip 解压并安装技能"""
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

        target_dir = skills_dir / skill_id
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
    svc.mark_user_upload(skill_id)
    return svc.get_skill(skill_id)


def _save_md_skill(content: bytes, filename: str, skills_dir: Path):
    """将 .md 文件保存为技能"""
    skill_id = _slug(Path(filename).stem) or "uploaded-skill"
    name = _parse_name_from_frontmatter(content) or skill_id
    skill_id = _slug(name) or skill_id

    target_dir = skills_dir / skill_id
    if target_dir.exists():
        raise ValueError(f"技能目录已存在: {skill_id}")

    target_dir.mkdir(parents=True)
    (target_dir / "SKILL.md").write_bytes(content)

    svc = get_claude_skill_service()
    svc.mark_user_upload(skill_id)
    return svc.get_skill(skill_id)
