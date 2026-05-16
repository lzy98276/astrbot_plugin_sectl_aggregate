# astrbot_plugin_sectl_aggregate

思拓创联聚合插件 - 为 AstrBot 提供回声洞投稿、查询、编辑、删除和 QQ 绑定功能。

## 功能

- **回声洞投稿**：匿名发布内容到回声洞
- **查看回声洞**：随机查看或按编号查看
- **编辑/删除**：管理自己发布的回声洞
- **QQ 绑定**：绑定 QQ 号用于身份验证

## 指令

| 指令 | 说明 |
|------|------|
| `help` | 查看帮助菜单 |
| `回声洞 投稿 内容` | 投稿一条新的回声洞 |
| `回声洞 查看 [编号]` | 随机查看或按编号查看 |
| `回声洞 编辑 编号 新内容` | 编辑自己发布的回声洞 |
| `回声洞 删除 编号` | 删除自己发布的回声洞 |
| `绑定 QQ号` | 申请 QQ 绑定 Key |
| `绑定状态` | 查看当前账号 QQ 绑定状态 |

## 配置

在 AstrBot 管理面板中配置以下参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_base_url` | 回声洞 API 基础地址 | `https://appwrite.sectl.cn` |
| `api_token` | API 认证 Token | 空 |
| `internal_token` | 内部投稿 Token | 空 |
| `request_timeout` | 请求超时时间（秒） | `10.0` |
| `retry_count` | 重试次数 | `2` |

## 安装

1. 将插件文件夹复制到 AstrBot 的 `data/plugins/` 目录下
2. 重启 AstrBot
3. 在管理面板中配置插件参数

## 依赖

- AstrBot >= 3.4.0
- aiohttp（HTTP 客户端）

## 开发

```bash
# 运行测试
python -m pytest tests/
```

## License

MIT
