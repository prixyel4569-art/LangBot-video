from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.error

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import context, events
from langbot_plugin.api.entities.builtin.platform import message as platform_message

logger = logging.getLogger(__name__)

URL_RE = re.compile(
    r"https?://(?:www\.|m\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av\d+)"
    r"|https?://b23\.tv/[0-9A-Za-z]+"
    r"|https?://bili2233\.cn/[0-9A-Za-z]+"
)
BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)

API = "https://api.bilibili.com/x/web-interface/view"
SPI_API = "https://api.bilibili.com/x/frontend/finger/spi"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CACHE_TTL = 600
MAX_DESC = 80
VIDEO_QN = 16  # 360p（未登录时 B 站只给这一档）
# 与 NapCat 视频上传上限保持一致；超过则只发文字和封面。
MAX_VIDEO_BYTES = 100 * 1024 * 1024

_cache: dict[str, tuple[float, dict]] = {}
_buvid_cookie = ""
_buvid_lock = threading.Lock()


def _base_headers() -> dict:
    return {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://www.bilibili.com",
    }


def _get_buvid_cookie(force: bool = False) -> str:
    """获取并缓存 B 站匿名 buvid Cookie，避免接口 412。"""
    global _buvid_cookie
    with _buvid_lock:
        if _buvid_cookie and not force:
            return _buvid_cookie
        request = urllib.request.Request(SPI_API, headers=_base_headers())
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        payload = data.get("data") or {}
        b3 = payload.get("b_3")
        b4 = payload.get("b_4")
        if b3 and b4:
            _buvid_cookie = f"buvid3={b3}; buvid4={b4}"
        return _buvid_cookie


def _get_json(url: str, timeout: int = 10) -> dict:
    try:
        cookie = _get_buvid_cookie()
    except Exception as error:
        logger.debug("BiliLinkResolver: 获取 buvid 失败: %s", error)
        cookie = ""

    for attempt in range(2):
        headers = _base_headers()
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            if error.code == 412 and attempt == 0:
                try:
                    cookie = _get_buvid_cookie(force=True)
                except Exception as refresh_error:
                    logger.debug(
                        "BiliLinkResolver: 刷新 buvid 失败: %s", refresh_error
                    )
                    cookie = ""
                continue
            raise
    raise RuntimeError("Bili API request failed")


def _resolve_short(url: str, timeout: int = 10) -> str:
    # b23.tv 的 WAF 会按 TLS/HTTP 指纹拦截 Python 的 urllib（返回 412），
    # 但系统 curl 可以正常拿到 302。优先用 curl，失败再退回 urllib。
    curl = shutil.which("curl")
    if curl:
        try:
            result = subprocess.run(
                [
                    curl,
                    "-s",
                    "-o",
                    "/dev/null",
                    "-m",
                    str(timeout),
                    "-w",
                    "%{redirect_url}",
                    "-A",
                    UA,
                    "-H",
                    "Referer: https://www.bilibili.com/",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            target = (result.stdout or "").strip()
            if target:
                return target
        except Exception as error:
            logger.debug("BiliLinkResolver: curl 解析短链失败，退回 urllib: %s", error)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Range": "bytes=0-0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl()


def _fmt_duration(seconds) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fmt_count(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number >= 100_000_000:
        return f"{number / 100_000_000:.1f}亿"
    if number >= 10_000:
        return f"{number / 10_000:.1f}万"
    return str(number)


def _get_play_url(bvid: str, cid) -> tuple[str | None, int]:
    """取 360p 的 durl 直链（音视频已合并，无需 FFmpeg）。"""
    url = (
        "https://api.bilibili.com/x/player/playurl"
        f"?bvid={bvid}&cid={cid}&qn={VIDEO_QN}"
        "&fnval=1&fnver=0&fourk=0&platform=html5"
    )
    data = _get_json(url)
    if data.get("code") != 0:
        return None, 0
    durl = (data.get("data") or {}).get("durl") or []
    if not durl:
        return None, 0
    entry = durl[0]
    return entry.get("url"), int(entry.get("size") or 0)


def _download(url: str, path: str, timeout: int = 180) -> int:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with open(path, "wb") as handle:
            shutil.copyfileobj(response, handle)
    return os.path.getsize(path)


class BiliLinkListener(EventListener):
    """监听普通消息里的 B 站链接，直接回复解析结果（不经过 LLM）。"""

    async def initialize(self):
        await super().initialize()

        # 注意：必须监听 MessageReceived（管线之前触发），
        # 而不是 NormalMessageReceived（只有进入聊天阶段才触发）。
        # 群聊里没 @ 的消息会先被群响应规则拦下，收不到 Normal 事件。
        @self.handler(events.PersonMessageReceived)
        async def _on_person_message(event_context: context.EventContext):
            await self._handle(event_context)

        @self.handler(events.GroupMessageReceived)
        async def _on_group_message(event_context: context.EventContext):
            await self._handle(event_context)

    async def _handle(self, event_context: context.EventContext) -> None:
        try:
            text = str(event_context.event.message_chain)
        except Exception:
            return

        match = URL_RE.search(text)
        if not match:
            return

        url = match.group(0)
        info = await self._lookup(url)
        if not info:
            return

        chain = self._build_chain(info)
        if chain is None:
            return

        # 文字+封面单独一条消息；视频再单独一条。
        # QQ 对「文字/图片/视频」混合消息只会渲染视频段，导致简介和封面消失。
        try:
            await event_context.reply(chain)
        except Exception as error:
            logger.warning("BiliLinkResolver: 发送解析结果失败: %s", error)
            return

        await asyncio.sleep(0.3)
        video_chain = platform_message.MessageChain([])
        video_path = await self._attach_video(video_chain, info)
        if video_path:
            try:
                await event_context.reply(video_chain)
            except Exception as error:
                logger.warning("BiliLinkResolver: 发送视频失败: %s", error)
            finally:
                try:
                    os.remove(video_path)
                except OSError:
                    pass

        # 整条消息只有链接时，阻止默认流程（避免 AI 再回复一遍、白花 token）
        if not URL_RE.sub("", text).strip():
            event_context.prevent_default()

    async def _attach_video(self, chain, info: dict) -> str | None:
        """下载 360p 视频并挂到消息链上；失败或超限就只发文字+封面。"""
        bvid = info.get("bvid")
        cid = info.get("cid")
        if not bvid or not cid:
            return None
        try:
            play_url, size = await asyncio.to_thread(_get_play_url, bvid, cid)
            if not play_url or size <= 0 or size > MAX_VIDEO_BYTES:
                logger.info(
                    "BiliLinkResolver: 跳过视频（url=%s size=%s）", bool(play_url), size
                )
                return None
            path = f"/tmp/bili-{bvid}.mp4"
            await asyncio.to_thread(_download, play_url, path)
            chain.root.append(platform_message.Video(path=path))
            return path
        except Exception as error:
            logger.warning("BiliLinkResolver: 下载视频失败: %s", error)
            return None

    async def _lookup(self, url: str) -> dict | None:
        try:
            final_url = url
            if "b23.tv" in url or "bili2233.cn" in url:
                final_url = await asyncio.to_thread(_resolve_short, url)

            bv_match = BV_RE.search(final_url)
            if bv_match:
                key, value = "bvid", bv_match.group(0)
                cache_key = value
            else:
                av_match = AV_RE.search(final_url)
                if not av_match:
                    return None
                key, value = "aid", av_match.group(1)
                cache_key = "av" + value

            now = time.time()
            cached = _cache.get(cache_key)
            if cached and now - cached[0] < CACHE_TTL:
                return cached[1]

            data = await asyncio.to_thread(_get_json, f"{API}?{key}={value}")
            if data.get("code") != 0:
                logger.info(
                    "BiliLinkResolver: 接口返回 code=%s message=%s",
                    data.get("code"),
                    data.get("message"),
                )
                return None

            info = data.get("data") or {}
            _cache[cache_key] = (now, info)
            return info
        except Exception as error:
            logger.warning("BiliLinkResolver: 解析失败: %s", error)
            return None

    def _build_chain(self, info: dict):
        title = (info.get("title") or "").strip()
        if not title:
            return None

        owner = ((info.get("owner") or {}).get("name") or "").strip()
        stat = info.get("stat") or {}
        duration = _fmt_duration(info.get("duration"))
        views = _fmt_count(stat.get("view"))

        meta_parts = [part for part in (owner, duration, f"{views} 播放" if views else "") if part]
        lines = [f"【B站】{title}"]
        if meta_parts:
            lines.append(" · ".join(meta_parts))

        desc = (info.get("desc") or "").strip().replace("\r", " ").replace("\n", " ")
        if desc and desc != "-":
            if len(desc) > MAX_DESC:
                desc = desc[:MAX_DESC] + "…"
            lines.append(desc)

        chain: list = [platform_message.Plain(text="\n".join(lines))]

        picture = (info.get("pic") or "").strip()
        if picture:
            if picture.startswith("//"):
                picture = "https:" + picture
            elif picture.startswith("http://"):
                picture = "https://" + picture[len("http://"):]
            chain.append(platform_message.Image(url=picture))

        return platform_message.MessageChain(chain)
