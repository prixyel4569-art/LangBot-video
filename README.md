# LangBot B 站链接解析与视频发送

本项目旨在解决 QQ 群里分享 B 站链接时，需要手动点开、且大模型回复会消耗 token 的问题。通过 LangBot 事件插件直接调用 B 站公开接口，自动回复标题、UP 主、时长、播放量、简介和封面，并附带一个 360p 视频；全程不经过大模型，降低了 token 成本和等待时间。

## 功能效果

聊天中出现 B 站视频链接时，机器人依次发送两条消息：

1. 文字信息 + 封面图；
2. 单独的视频文件。

拆成两条是必要的。QQ 对同一条消息里的“文字 + 图片 + 视频”混合结构只会渲染视频段，文字和封面会消失。

支持的链接：

- `https://www.bilibili.com/video/BV...`
- `https://www.bilibili.com/video/av...`
- `https://b23.tv/...`
- `https://bili2233.cn/...`

## 目录结构

```text
LangBot-B站视频解析/
├─ README.md
├─ 技术说明.md
├─ plugin/                         LangBot 插件源码
│  ├─ main.py
│  ├─ manifest.yaml
│  ├─ requirements.txt
│  ├─ assets/icon.svg
│  └─ components/event_listener/
│     ├─ __init__.py
│     ├─ bili_link_listener.py
│     └─ bili_link_listener.yaml
├─ patches/
│  └─ patch_video_support.py       LangBot 宿主视频消息补丁
└─ tests/
   ├─ test_message_chain.py        消息组件与 OneBot 转换测试
   └─ test_plugin_split.py         两条消息拆分测试（联网）
```

## 快速部署

### 1. 安装插件

把 `plugin/` 目录打包成 zip，在 LangBot 面板的插件管理里选择“本地安装”，安装后启用 `BiliLinkResolver`。

插件只依赖 LangBot 运行环境自带的 `langbot-plugin`，`requirements.txt` 仅作版本记录。

### 2. 给 LangBot 增加视频消息支持

LangBot 默认没有 `Video` 消息组件，直接发送视频会被替换成：

```text
Unknown Message: Unknown component type: Video
```

补丁必须用 LangBot 自带的 Python 运行：

```bash
# 先看会改哪些文件，不写入
/path/to/langbot/bin/python patches/patch_video_support.py --dry-run

# 确认后正式执行
/path/to/langbot/bin/python patches/patch_video_support.py
```

如果 LangBot 给插件创建了独立运行环境，需要指定环境根目录：

```bash
LANGBOT_ENV_ROOT=/path/to/langbot/data/plugin-runtime/environments \
  /path/to/langbot/bin/python patches/patch_video_support.py
```

补丁是幂等的，重复运行不会重复插入代码。修改第三方源码前会生成带时间戳的 `.bak-*` 备份。

### 3. 重启并验证

```bash
# 重启 LangBot（按你的部署方式选择）
pm2 restart langbot

# 验证组件注册和 OneBot 转换
/path/to/langbot/bin/python tests/test_message_chain.py

# 联网验证：文字/封面与视频被拆成两条消息
/path/to/langbot/bin/python tests/test_plugin_split.py
```

预期输出：

```text
OK: MessageChain -> ['Plain', 'Video']
OK: OneBot 消息段 -> {'type': 'video', 'data': {'file': '/tmp/example.mp4'}}
回复条数: 2
每条组件: [['Plain', 'Image'], ['Video']]
```

## 可调参数

在 `plugin/components/event_listener/bili_link_listener.py` 顶部：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `CACHE_TTL` | 600 秒 | 同一视频的元数据缓存时间 |
| `MAX_DESC` | 80 | 简介最大字符数 |
| `VIDEO_QN` | 16 | B 站清晰度编号，16 为 360p |
| `MAX_VIDEO_BYTES` | 30 MB | 超过则只发文字和封面 |

## 已知限制

- 未登录状态下 B 站通常只提供 360p，清晰度受平台限制。
- 视频需要先下载到服务器临时目录，再交给 NapCat 上传；会占用带宽和临时磁盘。
- 超过 30 MB 的视频会跳过，只保留文字和封面。
- `b23.tv` 短链对 Python `urllib` 可能返回 412，代码优先使用系统 `curl` 跟随跳转。
- NapCat 缺少 FFmpeg 时会打印缩略图生成失败，并改用默认缩略图；视频仍可发送，但封面帧可能不准确。
- LangBot 升级可能覆盖 `message.py` 和 `aiocqhttp.py`，升级后需要重新运行补丁。
- B 站接口不是稳定公开 API，字段或风控策略变化可能导致解析失败。

## 安全与隐私

- 不包含 API key、Cookie、账号密码、服务器地址或设备标识。
- 只请求 B 站公开接口；短链解析只针对 `b23.tv` / `bili2233.cn`，不会把聊天中的任意 URL 当作代理目标。
- 视频下载有 30 MB 上限，发送完成后删除 `/tmp` 临时文件。
- 不保存聊天内容，不做用户画像；运行日志由 LangBot / NapCat 自身管理。
- 插件会阻止“纯链接消息”进入默认 AI 流程，避免重复回复和额外 token 消耗。

更细的接口、事件模型和踩坑说明见 [技术说明.md](技术说明.md)。
