from __future__ import annotations

from langbot_plugin.api.definition.plugin import BasePlugin


class BiliLinkResolver(BasePlugin):
    """B 站链接解析插件：事件监听器在 components/event_listener 下。"""

    def __init__(self):
        super().__init__()

    async def initialize(self) -> None:
        pass
