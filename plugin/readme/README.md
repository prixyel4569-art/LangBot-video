# B站链接解析（BiliLinkResolver）

聊天中出现 B 站视频链接时，自动回复标题、UP 主、时长、播放量、简介和封面，并单独发送一个 360p 视频。

**全程不经过大模型**：插件直接调用 B 站公开接口，不消耗任何 LLM token。

## 支持的链接

- `https://www.bilibili.com/video/BV...`
- `https://www.bilibili.com/video/av...`
- `https://b23.tv/...`（短链，自动跟随跳转）
- `https://bili2233.cn/...`

## 行为

- 私聊、群聊的普通消息都会检查
- 一条消息只解析第一个链接
- 文字和封面发一条，视频单独发一条；避免 QQ 混合消息只渲染视频
- 相同视频 10 分钟内走缓存，避免重复请求
- 自动获取并缓存 B 站匿名 `buvid3` / `buvid4` Cookie，避免元数据接口 412
- 纯链接消息会阻止默认 AI 流程；链接后还有文字时不影响正常对话
- 视频下载上限 100 MB，与 NapCat 上传上限保持一致；超出则只发文字和封面

## 前提

- 服务器能访问 `api.bilibili.com`（无需 key、无需 cookie）
- 系统有 `curl`，用于跟随 `b23.tv` 短链跳转
