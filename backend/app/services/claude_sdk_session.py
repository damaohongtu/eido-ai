"""Keep each SDK client's task-group lifecycle in one owning asyncio task."""

import asyncio
from contextlib import suppress


class ClaudeSdkSession:
    def __init__(self, options):
        from claude_agent_sdk import ClaudeSDKClient

        self.sdk = ClaudeSDKClient(options=options)
        self._stop = asyncio.Event()
        self._ready = asyncio.get_running_loop().create_future()
        self._owner = None

    async def connect(self):
        self._owner = asyncio.create_task(self._run())
        try:
            await self._ready
        except BaseException:
            await self.disconnect()
            raise

    async def _run(self):
        try:
            await self.sdk.connect()
            self._ready.set_result(None)
            await self._stop.wait()
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            # AnyIO cancel scopes must exit in the task that entered them.
            await self.sdk.disconnect()

    async def query(self, prompt):
        await self.sdk.query(prompt)

    def receive_response(self):
        return self.sdk.receive_response()

    async def interrupt(self):
        await self.sdk.interrupt()

    async def disconnect(self):
        self._stop.set()
        if self._owner:
            if not self._ready.done() or self._ready.cancelled():
                self._owner.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.shield(self._owner)
