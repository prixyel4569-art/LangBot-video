#!/usr/bin/env python3
"""验证插件把「文字+封面」和「视频」拆成两条消息发送。

这是联网集成测试，会真实请求 B 站并下载一个 360p 视频。
运行方式（用 LangBot 自带的 Python）：
    /path/to/langbot/bin/python tests/test_plugin_split.py
"""
import asyncio
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugin"
sys.path.insert(0, str(PLUGIN_DIR))

from components.event_listener.bili_link_listener import BiliLinkListener
from langbot_plugin.api.entities.builtin.platform import message as pm


TEST_URL = "https://www.bilibili.com/video/BV1cL4y1i7xN"


class FakeEvent:
    message_chain = pm.MessageChain([pm.Plain(text=TEST_URL)])


class FakeContext:
    def __init__(self) -> None:
        self.event = FakeEvent()
        self.replies = []
        self.prevented = False

    async def reply(self, chain) -> None:
        self.replies.append([type(item).__name__ for item in chain.root])
        for item in chain.root:
            if isinstance(item, pm.Video) and item.path:
                size = os.path.getsize(item.path)
                print("视频临时文件:", item.path, size, "bytes")

    def prevent_default(self) -> None:
        self.prevented = True


async def main() -> None:
    context = FakeContext()
    await BiliLinkListener()._handle(context)
    print("回复条数:", len(context.replies))
    print("每条组件:", context.replies)
    print("已阻止默认流程:", context.prevented)

    assert context.replies[0] == ["Plain", "Image"], context.replies
    assert context.replies[1] == ["Video"], context.replies
    assert context.prevented is True
    print("OK: 文字/封面与视频已拆分为两条消息")


if __name__ == "__main__":
    asyncio.run(main())
