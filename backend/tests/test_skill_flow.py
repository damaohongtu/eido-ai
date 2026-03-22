"""
端到端测试脚本
测试"财报点评"技能的完整执行流程
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 设置UTF-8编码
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

from app.core.database import AsyncSessionLocal
from app.models.skill import Skill
from app.services.mcp_registry import mcp_registry
from app.services.skill_parser import skill_parser
from app.services.workflow_compiler import workflow_compiler
from app.services.skill_runtime import skill_runtime
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_full_flow():
    """测试完整流程"""
    
    print("=" * 80)
    print("【财报点评技能 - 端到端测试】")
    print("=" * 80)
    
    async with AsyncSessionLocal() as db:
        try:
            # Step 1: 加载系统能力
            print("\n[1/5] 加载系统能力到MCP Registry...")
            await mcp_registry.load_from_database(db)
            
            print(f"  ✓ 已加载 {len(mcp_registry.list_tools())} 个工具")
            print(f"  ✓ 已加载 {len(mcp_registry.list_agents())} 个Agent")
            
            # 打印注册的能力
            print("\n  注册的工具:")
            for tool_id, tool_info in mcp_registry.list_tools().items():
                print(f"    - {tool_info['name']} ({tool_id[:8]}...)")
            
            print("\n  注册的Agent:")
            for agent_id, agent_info in mcp_registry.list_agents().items():
                print(f"    - {agent_info['name']} ({agent_id[:8]}...)")
            
            # Step 2: 查询财报点评技能
            print("\n[2/5] 查询财报点评技能...")
            result = await db.execute(
                select(Skill).where(Skill.name == "财报点评")
            )
            skill = result.scalar_one_or_none()
            
            if not skill:
                print("  ✗ 未找到财报点评技能，请先运行种子数据脚本")
                return
            
            print(f"  ✓ 找到技能: {skill.name}")
            print(f"    描述: {skill.description[:100]}...")
            
            # Step 3: 解析技能文档
            print("\n[3/5] 解析技能文档...")
            user_query = "分析中望软件2024Q3财报"
            parsed = await skill_parser.parse(skill.description, user_query)
            
            if not parsed.parse_success:
                print(f"  ✗ 解析失败: {parsed.parse_errors}")
                return
            
            intent = parsed.intent
            print(f"  ✓ 解析成功")
            print(f"    任务类型: {intent.task_type}")
            print(f"    所需能力: {len(intent.capabilities)} 个")
            
            for cap in intent.capabilities:
                status = "✓" if cap.capability_id else "✗"
                print(f"      {status} {cap.type}: {cap.name} ({cap.capability_id or '未找到'})")
            
            print(f"    执行顺序: {intent.execution_order}")
            
            # Step 4: 编译工作流
            print("\n[4/5] 编译LangGraph工作流...")
            workflow = workflow_compiler.compile(intent)
            print(f"  ✓ 工作流编译成功")
            
            # Step 5: 执行工作流（非流式）
            print(f"\n[5/5] 执行技能: {user_query}")
            print("-" * 80)
            
            result = await skill_runtime.execute(skill, user_query)
            
            if result["success"]:
                print("\n✓ 技能执行成功！")
                print("\n【执行结果】:")
                print(result["output"])
                
                print("\n【执行轨迹】:")
                for trace in result["execution_trace"]:
                    print(f"  - {trace}")
            else:
                print(f"\n✗ 技能执行失败: {result.get('error')}")
            
            print("\n" + "=" * 80)
            print("测试完成！")
            print("=" * 80)
            
        except Exception as e:
            logger.error(f"测试失败: {e}", exc_info=True)
            print(f"\n✗ 测试异常: {e}")


async def test_stream_flow():
    """测试流式执行"""
    
    print("\n" + "=" * 80)
    print("【测试流式执行】")
    print("=" * 80)
    
    async with AsyncSessionLocal() as db:
        try:
            # 加载能力
            await mcp_registry.load_from_database(db)
            
            # 查询技能
            result = await db.execute(
                select(Skill).where(Skill.name == "财报点评")
            )
            skill = result.scalar_one_or_none()
            
            if not skill:
                print("✗ 未找到财报点评技能")
                return
            
            user_query = "分析中望软件2024Q3财报"
            print(f"\n执行技能: {skill.name}")
            print(f"用户问题: {user_query}\n")
            
            # 流式执行
            async for event in skill_runtime.execute_stream(skill, user_query):
                # 打印SSE事件
                print(event, end='', flush=True)
            
            print("\n流式执行完成！")
            
        except Exception as e:
            logger.error(f"流式测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="测试财报点评技能")
    parser.add_argument("--stream", action="store_true", help="测试流式执行")
    args = parser.parse_args()
    
    if args.stream:
        asyncio.run(test_stream_flow())
    else:
        asyncio.run(test_full_flow())
