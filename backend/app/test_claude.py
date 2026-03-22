import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher
import datetime

async def log_file_change(input_data, tool_use_id, context):
    file_path = input_data.get("tool_input", {}).get("file_path", "unknown")
    with open("./audit.log", "a") as f:
        f.write(f"{datetime.now()}: modified {file_path}\n")
    return {}

async def main():
    async for message in query(
        prompt="""
            点评财报：/Users/mao/Downloads/中望软件2024.pdf 
            注意： 所有的环境变量都已经设置在~/.bashrc，不需要再设置，直接使用即可；
        """,
        options=ClaudeAgentOptions(
            allowed_tools=["Bash", "Glob", "Read", "Write", "Edit", "WebFetch"],
            setting_sources=["project"],
            permission_mode="acceptEdits",
            hooks={
                "PostToolUse": [
                    HookMatcher(matcher="Edit|Write", hooks=[log_file_change])
                ]
            },
        ),
    ):
        print(message)

asyncio.run(main())