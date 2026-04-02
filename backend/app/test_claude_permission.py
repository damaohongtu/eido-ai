import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from claude_agent_sdk.types import (
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)


async def can_use_tool(
    tool_name: str, input_data: dict, context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    print(f"\n{'='*60}")
    print(f"🔒 工具审批请求: {tool_name}")
    print(f"{'='*60}")

    if tool_name == "Write":
        print(f"  文件路径: {input_data.get('file_path', 'N/A')}")
        content = input_data.get("content", "")
        preview = content[:200] + "..." if len(content) > 200 else content
        print(f"  写入内容预览:\n{preview}")
    elif tool_name == "Edit":
        print(f"  文件路径: {input_data.get('file_path', 'N/A')}")
        print(f"  替换内容: {input_data.get('old_string', '')[:100]}")
        print(f"  新内容:   {input_data.get('new_string', '')[:100]}")
    elif tool_name == "Bash":
        print(f"  命令: {input_data.get('command', 'N/A')}")
        if input_data.get("description"):
            print(f"  描述: {input_data['description']}")
    else:
        print(f"  参数: {input_data}")

    print(f"{'='*60}")
    response = input("是否允许执行? (y/n): ").strip().lower()

    if response == "y":
        print("✅ 已批准")
        return PermissionResultAllow(updated_input=input_data)
    else:
        print("❌ 已拒绝")
        return PermissionResultDeny(message="用户拒绝了此操作")


async def dummy_hook(input_data, tool_use_id, context):
    """Python SDK 要求：需要一个 PreToolUse hook 来保持流式连接，否则 can_use_tool 回调无法被触发"""
    return {"continue_": True}


async def prompt_stream():
    yield {
        "type": "user",
        "message": {
            "role": "user",
            "content": (
                "使用百度检索最新的财经新闻，在 /tmp 目录下创建一个使用当前时间戳命令的临时文件, 然后发送到邮箱 damaohongtu@126.com"
            ),
        },
    }


async def main():
    print("🚀 启动 Claude Agent SDK 权限审批 Demo")
    print("   所有写入操作都需要用户手动批准才能执行\n")

    try:
        async for message in query(
            prompt=prompt_stream(),
            options=ClaudeAgentOptions(
                allowed_tools=["Read", "Glob", "Grep"],
                setting_sources=["project"],
                can_use_tool=can_use_tool,
                hooks={
                    "PreToolUse": [HookMatcher(matcher=None, hooks=[dummy_hook])]
                },
            ),
        ):
            if isinstance(message, ResultMessage) and message.subtype == "success":
                print(f"\n{'='*60}")
                print("📋 最终结果:")
                print(f"{'='*60}")
                print(message.result)
    except Exception as e:
        if "Stream closed" in str(e):
            pass
        else:
            raise


asyncio.run(main())
