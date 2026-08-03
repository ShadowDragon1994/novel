from __future__ import annotations

import pytest

from device_gateway.adb import AdbClient, AdbError


class ReconnectingAdbClient(AdbClient):
    def __init__(self) -> None:
        super().__init__(executable="adb")
        self.calls: list[tuple[str, ...]] = []
        self.device_attempts = 0

    async def _run(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("-s", "127.0.0.1:50125"):
            self.device_attempts += 1
            if self.device_attempts == 1:
                raise AdbError("error: closed")
            return "ok"
        if args == ("connect", "127.0.0.1:50125"):
            return "connected"
        raise AssertionError(args)


@pytest.mark.asyncio
async def test_run_device_reconnects_once_after_closed_transport() -> None:
    adb = ReconnectingAdbClient()

    result = await adb.run_device("127.0.0.1:50125", "get-state")

    assert result == "ok"
    assert adb.calls == [
        ("-s", "127.0.0.1:50125", "get-state"),
        ("connect", "127.0.0.1:50125"),
        ("-s", "127.0.0.1:50125", "get-state"),
    ]


@pytest.mark.asyncio
async def test_run_device_reconnects_once_after_command_timeout() -> None:
    adb = ReconnectingAdbClient()
    original_run = adb._run

    async def timeout_once(*args: str) -> str:
        if args[:2] == ("-s", "127.0.0.1:50125") and adb.device_attempts == 0:
            adb.calls.append(args)
            adb.device_attempts += 1
            raise AdbError("ADB command timed out after 15s")
        return await original_run(*args)

    adb._run = timeout_once  # type: ignore[method-assign]

    assert await adb.run_device("127.0.0.1:50125", "shell", "input", "keyevent", "KEYCODE_HOME") == "ok"
    assert ("connect", "127.0.0.1:50125") in adb.calls
