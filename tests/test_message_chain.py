#!/usr/bin/env python3
"""验证 LangBot 已正确注册 Video 组件，并能转换成 OneBot 视频消息段。

运行方式（用 LangBot 自带的 Python）：
    /path/to/langbot/bin/python tests/test_message_chain.py
"""
import asyncio

from langbot_plugin.api.entities.builtin.platform.message import MessageChain
from langbot.pkg.platform.sources.aiocqhttp import AiocqhttpMessageConverter


def main() -> None:
    chain = MessageChain.model_validate(
        [
            {"type": "Plain", "text": "hello"},
            {"type": "Video", "path": "/tmp/example.mp4"},
        ]
    )
    kinds = [type(item).__name__ for item in chain.root]
    assert kinds == ["Plain", "Video"], kinds

    segments, _, _ = asyncio.run(
        AiocqhttpMessageConverter.yiri2target(chain)
    )
    payload = list(segments)
    video = [
        item
        for item in payload
        if isinstance(item, dict) and item.get("type") == "video"
    ]
    assert video, payload
    assert video[0]["data"]["file"] == "/tmp/example.mp4", video

    print("OK: MessageChain ->", kinds)
    print(
        "OK: OneBot 消息段 ->",
        {"type": "video", "data": dict(video[0]["data"])},
    )


if __name__ == "__main__":
    main()
