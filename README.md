# L4D2 创意工坊地图自动部署

一键将 Steam 创意工坊地图部署到本地和远端 L4D2 服务器。零外部依赖，仅需 Python 3 + SSH。

## 特性

- 🔍 Steam 工坊搜索 → 交互式选择
- 📦 自动检测必需物品依赖
- ⚡ 服务器端直连 Steam CDN 下载，再拉回本地（节省本地带宽）
- 🚀 自动部署到本地 Windows + 远端 Linux 服务器
- 🔄 远端部署后自动重启 L4D2 服务
- 🪶 纯 Python 标准库 + shell，无 Docker/steamcmd/uv

## 安装

```bash
mkdir -p ~/.claude/skills
cd ~/.claude/skills
git clone https://github.com/Xorzj/L4D2-Download-SKILL.git
```

首次运行时，按提示配置服务器连接信息和本地 addons 路径，或手动复制模板：

```bash
cp l4d2_config.example.json l4d2_config.json
# 编辑 l4d2_config.json 填入实际配置
```

## 配置说明

`l4d2_config.json`：

| 字段 | 说明 |
|------|------|
| `server.host` | 远端服务器 IP |
| `server.port` | SSH 端口（默认 22） |
| `server.username` | SSH 用户名 |
| `server.ssh_key_path` | SSH 私钥路径 |
| `server.remote_addons_dir` | 远端 addons 路径，填 `"auto"` 自动搜索 |
| `local.local_addons_dir` | Windows 端 addons 绝对路径 |
| `deploy_mode` | `"both"` 双端 / `"local_only"` 仅本地 |

## 使用

在 Claude Code 中输入：

```
/l4d2-map-deployer 狂潮珠江 v1.0
```

或直接描述地图名即可触发。

## 依赖

- Python 3.x（仅标准库）
- SSH 密钥登录（远端部署时）
- 远端服务器需有 `tmux` 会话 `l4d2` 用于服务重启

## 许可

MIT
