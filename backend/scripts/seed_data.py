"""
数据库种子数据脚本
插入系统预置的Tool、Agent和Skill
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.models import Tool, Agent, Skill, User
import uuid


def seed_user(db):
    """创建默认用户"""
    default_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    existing = db.query(User).filter(User.id == default_user_id).first()
    
    if not existing:
        user = User(
            id=default_user_id,
            username="default_user",
            email="default@eido.local",
            password_hash="not_used_in_dev",  # 开发环境不使用密码
            role="USER",
            bio="默认开发用户"
        )
        db.add(user)
        db.commit()
        print(f"✓ 创建默认用户: {user.username}")
    else:
        print(f"- 默认用户已存在: {existing.username}")


def seed_tools(db):
    """插入系统工具"""
    tools = [
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "user_id": None,
            "name": "搜索引擎",
            "description": "搜索实时网络获取最新信息",
            "icon": "🔍",
            "category": "搜索",
            "parameters_schema": {},
            "config": {"mcp_server_url": "http://localhost:3002", "tool_name": "web_search"},
            "is_system": True,
            "is_active": True
        },
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
            "user_id": None,
            "name": "财报三表数据查询工具",
            "description": "用于获取利润表、现金流量表、资产负债表",
            "icon": "📊",
            "category": "计算",
            "parameters_schema": {},
            "config": {"mcp_server_url": "http://localhost:3001", "tool_name": "query_financial_statements"},
            "is_system": True,
            "is_active": True
        },
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000004"),
            "user_id": None,
            "name": "财报原文检索",
            "description": "用于检索会计政策、业务描述、异常项目说明",
            "icon": "📝",
            "category": "科学",
            "parameters_schema": {},
            "config": {"mcp_server_url": "http://localhost:3001", "tool_name": "search_financial_report_text"},
            "is_system": True,
            "is_active": True
        },
    ]
    
    for tool_data in tools:
        existing = db.query(Tool).filter(Tool.id == tool_data["id"]).first()
        if not existing:
            tool = Tool(**tool_data)
            db.add(tool)
            print(f"✓ 创建工具: {tool.name}")
        else:
            print(f"- 工具已存在: {existing.name}")
    
    db.commit()


def seed_agents(db):
    """插入系统Agent"""
    agents = [
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000101"),
            "user_id": None,
            "name": "通用助手",
            "description": "一个有用的通用 AI 助手",
            "icon": "🤖",
            "category": "通用",
            "parameters_schema": {},
            "config": {
                "system_prompt": "You are a helpful assistant.",
                "model": "gpt-4o",
                "temperature": 0.7
            },
            "is_system": True,
            "is_active": True
        },
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000102"),
            "user_id": None,
            "name": "研究分析师",
            "description": "用于深度财务分析",
            "icon": "🕵️",
            "category": "学术",
            "parameters_schema": {},
            "config": {
                "system_prompt": "You are a research expert.",
                "model": "gpt-4o",
                "temperature": 0.5
            },
            "is_system": True,
            "is_active": True
        },
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000103"),
            "user_id": None,
            "name": "业绩报告会分析",
            "description": "提取管理层对业绩变动的解释",
            "icon": "💻",
            "category": "技术",
            "parameters_schema": {},
            "config": {
                "system_prompt": "You are an earnings call analyst.",
                "model": "gpt-4o",
                "temperature": 0.3
            },
            "is_system": True,
            "is_active": True
        },
    ]
    
    for agent_data in agents:
        existing = db.query(Agent).filter(Agent.id == agent_data["id"]).first()
        if not existing:
            agent = Agent(**agent_data)
            db.add(agent)
            print(f"✓ 创建Agent: {agent.name}")
        else:
            print(f"- Agent已存在: {existing.name}")
    
    db.commit()


def seed_skills(db):
    """插入系统技能"""
    skills = [
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000201"),
            "user_id": None,
            "name": "财报点评",
            "description": """## 技能目标
在给定上市公司财报数据及相关公开信息的前提下，生成结构化、可直接用于投资研究的财报点评。

## 使用能力
- @财报三表数据查询工具：获取财务数据
- @财报原文检索：检索关键信息
- @业绩报告会分析：提取管理层观点
- @研究分析师：生成分析报告""",
            "icon": "🌐",
            "is_system": True,
            "is_active": True
        },
    ]
    
    for skill_data in skills:
        existing = db.query(Skill).filter(Skill.id == skill_data["id"]).first()
        if not existing:
            skill = Skill(**skill_data)
            db.add(skill)
            print(f"✓ 创建技能: {skill.name}")
        else:
            print(f"- 技能已存在: {existing.name}")
    
    db.commit()


def seed_default_user(db):
    """创建默认用户"""
    default_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    existing = db.query(User).filter(User.id == default_user_id).first()
    
    if not existing:
        user = User(
            id=default_user_id,
            username="default_user",
            email="default@eido.local",
            password_hash="not_used_in_dev",
            role="USER",
            bio="默认开发用户"
        )
        db.add(user)
        db.commit()
        print(f"✓ 创建默认用户: {user.username}")
    else:
        print(f"- 默认用户已存在: {existing.username}")


def main():
    """主函数"""
    print("=" * 60)
    print("开始插入种子数据到 Eido 数据库...")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        print("\n[0/4] 创建默认用户...")
        seed_user(db)
        
        print("\n[1/4] 插入系统工具...")
        seed_tools(db)
        
        print("\n[2/4] 插入系统Agent...")
        seed_agents(db)
        
        print("\n[3/4] 插入系统技能...")
        seed_skills(db)
        
        print("\n" + "=" * 60)
        print("✓ 种子数据插入完成！")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
