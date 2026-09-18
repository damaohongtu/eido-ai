"""Bounded script execution within the current runtime's session workspace."""

import asyncio
import os
import signal
import tempfile
from pathlib import Path


async def run_script(command: list[str], cwd: Path) -> dict:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = await asyncio.create_subprocess_exec(
            *command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=300)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            raise
        stdout.seek(0)
        stderr.seek(0)
        return {
            "returncode": process.returncode,
            "stdout": stdout.read(100_000).decode(errors="replace"),
            "stderr": stderr.read(100_000).decode(errors="replace"),
        }
