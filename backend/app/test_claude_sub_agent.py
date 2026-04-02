import asyncio
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from claude_agent_sdk.types import AgentDefinition
async def main():
    print("🚀 启动 Claude Agent SDK SubAgent Demo\n")
    agents = {
        "code_analyst": AgentDefinition(
            description="分析代码结构、查找文件、阅读代码。当需要探索和理解代码库时使用此 agent。",
            prompt=(
                "你是一个代码分析专家。你只能读取和搜索代码，不能修改任何文件。"
                "分析时请关注：代码结构、潜在问题、改进建议。用中文回答。"
            ),
            tools=["Read", "Glob", "Grep"],
            model="haiku",
        ),
        "file_writer": AgentDefinition(
            description="创建或修改文件。当需要写入文件内容时使用此 agent。",
            prompt=(
                "你是一个文件写入助手。你只负责根据指令创建或修改文件，不做额外分析。"
                "写入完成后简要说明做了什么。"
            ),
            tools=["Write", "Edit", "Read"],
            model="haiku",
        ),
    }
    async for message in query(
        prompt=(
            "请完成以下两步任务：\n"
            "1. 先分析 /tmp/eido_permission_test.txt 文件内容\n"
            "2. 然后在 /tmp 目录创建一个 sub_agent_result.txt，"
            "写入你对该文件的分析总结"
        ),
        options=ClaudeAgentOptions(
            agents=agents,
            allowed_tools=["Read", "Write", "Glob", "Grep", "Agent"],
            permission_mode="acceptEdits",
        ),
    ):
        if isinstance(message, ResultMessage) and message.subtype == "success":
            print(f"\n{'='*60}")
            print("📋 最终结果:")
            print(f"{'='*60}")
            print(message.result)
asyncio.run(main())