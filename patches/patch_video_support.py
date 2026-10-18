#!/usr/bin/env python3
"""给 LangBot 增加视频消息支持。

做两件事：
1. 在 langbot_plugin 的 message.py 中增加 Video 组件，并注册到
   MessageChain._get_component_types() 的类型表；
2. 在 OneBot(aiocqhttp) 适配器中增加 Video -> {'type': 'video'} 的转换。

必须用 LangBot 自带的 Python 运行，例如：
    /path/to/langbot/bin/python patch_video_support.py

如果 LangBot 为插件创建了独立运行环境，可用环境变量指定其根目录：
    LANGBOT_ENV_ROOT=/path/to/langbot/data/plugin-runtime/environments \
        /path/to/langbot/bin/python patch_video_support.py

先加 --dry-run 可以只看会改哪些文件，不写入。
"""
from __future__ import annotations

import glob
import importlib.util
import os
import py_compile
import shutil
import sys
import time
from pathlib import Path


def _module_file(name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if not spec or not spec.origin:
        return None
    return Path(spec.origin).resolve()


langbot_plugin_init = _module_file("langbot_plugin")
langbot_init = _module_file("langbot")
if not langbot_plugin_init or not langbot_init:
    print("错误：找不到 langbot / langbot_plugin，请用 LangBot 自带的 Python 运行。")
    raise SystemExit(1)

HOST_MSG = (
    langbot_plugin_init.parent
    / "api/entities/builtin/platform/message.py"
)
ADAPTER = langbot_init.parent / "pkg/platform/sources/aiocqhttp.py"

VIDEO_CLASS = (
    '\n\nclass Video(MessageComponent):\n'
    '    """Video."""\n'
    '\n'
    '    type: str = "Video"\n'
    '    """Type of the message component."""\n'
    '    video_id: typing.Optional[str] = pydantic.Field(default="")\n'
    '    """The video_id of the video."""\n'
    '    url: typing.Optional[str] = pydantic.Field(default="")\n'
    '    """The URL of the video."""\n'
    '    path: typing.Optional[str] = pydantic.Field(default="")\n'
    '    """The local path of the video."""\n'
    '    base64: typing.Optional[str] = pydantic.Field(default="")\n'
    '    """The Base64 encoding of the video."""\n'
)

MSG_ANCHOR = "\nclass File(MessageComponent):"
REG_ANCHOR = '            "Image": Image,\n'
REG_LINE = '            "Video": Video,\n'

VOICE_TAIL = (
    "                elif msg.path:\n"
    "                    arg = msg.path\n"
    "                    msg_list.append(aiocqhttp.MessageSegment.record(msg.path))\n"
)

VIDEO_BRANCH = (
    "                elif msg.path:\n"
    "                    arg = msg.path\n"
    "                    msg_list.append(aiocqhttp.MessageSegment.record(msg.path))\n"
    "            elif type(msg) is platform_message.Video:\n"
    "                arg = ''\n"
    "                if msg.path:\n"
    "                    arg = msg.path\n"
    "                elif msg.url:\n"
    "                    arg = msg.url\n"
    "                elif msg.base64:\n"
    "                    arg = f'base64://{_normalize_base64_payload(msg.base64)}'\n"
    "                if arg:\n"
    "                    msg_list.append({'type': 'video', 'data': {'file': arg}})\n"
)


def _backup(path: Path) -> Path:
    target = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, target)
    return target


def _write(path: Path, text: str, dry_run: bool, changed: list[str]) -> None:
    if dry_run:
        print("* [dry-run] 将修改:", path)
        changed.append(str(path))
        return

    bak = _backup(path)
    path.write_text(text, encoding="utf-8")
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as error:
        shutil.copy2(bak, path)
        print("!! 语法失败，已回滚:", path, error)
        raise SystemExit(1)
    print("* 已修改:", path)
    changed.append(str(path))


def _patch_message_file(path: Path, dry_run: bool, changed: list[str]) -> None:
    if not path.exists():
        print("= 跳过（不存在）:", path)
        return

    original = path.read_text(encoding="utf-8")
    text = original

    if "class Video(MessageComponent):" not in text:
        if text.count(MSG_ANCHOR) != 1:
            print("!! 类锚点匹配 %d 次，跳过: %s" % (text.count(MSG_ANCHOR), path))
            return
        text = text.replace(MSG_ANCHOR, VIDEO_CLASS + MSG_ANCHOR, 1)

    if REG_LINE not in text:
        if text.count(REG_ANCHOR) != 1:
            print("!! 注册锚点匹配 %d 次，跳过: %s" % (text.count(REG_ANCHOR), path))
            return
        text = text.replace(REG_ANCHOR, REG_ANCHOR + REG_LINE, 1)

    if text == original:
        print("= 已支持 Video（跳过）:", path)
        return
    _write(path, text, dry_run, changed)


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    changed: list[str] = []

    targets = [HOST_MSG]
    env_root = os.environ.get("LANGBOT_ENV_ROOT", "").strip()
    if env_root:
        env_glob = str(
            Path(env_root)
            / "sha256"
            / "*"
            / "site-packages/langbot_plugin/api/entities/builtin/platform/message.py"
        )
        targets.extend(Path(item) for item in glob.glob(env_glob))
    else:
        print(
            "提示：未设置 LANGBOT_ENV_ROOT，只修改宿主环境；"
            "插件独立环境如已存在，请设置该变量后重跑。"
        )

    seen = set()
    for path in targets:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        _patch_message_file(path, dry_run, changed)

    if ADAPTER.exists():
        text = ADAPTER.read_text(encoding="utf-8")
        if "platform_message.Video" in text:
            print("= 适配器已支持 video（跳过）:", ADAPTER)
        elif text.count(VOICE_TAIL) == 1:
            _write(ADAPTER, text.replace(VOICE_TAIL, VIDEO_BRANCH, 1), dry_run, changed)
        else:
            print(
                "!! 适配器锚点匹配 %d 次，未修改: %s"
                % (text.count(VOICE_TAIL), ADAPTER)
            )
    else:
        print("= 跳过（不存在）:", ADAPTER)

    print()
    print(("将修改" if dry_run else "已修改"), "文件数:", len(changed))


if __name__ == "__main__":
    main()
