# L4D2 创意工坊地图自动部署

一键将 Steam 创意工坊地图部署到本地和远端 L4D2 服务器。零外部依赖，仅需 Python 3 + SSH。

## 特性

- 🔍 Steam 工坊搜索 → 交互式选择
- 📦 自动检测必需物品依赖
- ⚡ 服务器端直连 Steam CDN 下载，再拉回本地（节省本地带宽）
- 🚀 自动部署到本地 Windows + 远端 Linux 服务器
- 🏷️ 统一命名 `<地图名>_<工坊ID>.vpk`，主地图与依赖共享前缀，两端同名，便于辨认与清理
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

## 并发下载

```bash
python3 download.py "ID1,ID2" "地图名" --workers 4
# 服务器上脱离 SSH 会话运行；返回 PID 后查询日志和状态
python3 download.py "ID1,ID2" "地图名" --workers 4 --background
cat l4d2_temp_dl/status.json
tail -n 20 l4d2_temp_dl/download.log
```

默认单文件 4 路连接、每段 8MB，文件之间串行。分段断流后自动续传，低于 512KB/s 持续 20 秒时重连，每段最多尝试 8 次；`--min-speed 0` 可禁用低速检测。CDN 不支持 Range 时退回单连接，重试从头开始。`--workers` 可以调整，续传时保持 `--chunk-size` 不变。

支持导入旧版未完成的 VPK；新断点位于 `vpk/<文件名>.vpk.parts/`，合并完成后才生成可部署的 VPK。非 VPK 依赖（如 PNG）明确跳过。失败时保留断点，重新执行相同命令恢复。

后台启动成功仅代表任务已启动，状态文件 PID 必须对应本次任务且 `state` 为 `completed` 才能部署；SSH 断线后重新读取状态，不要重复启动。同一输出目录由文件锁保护。仅部署状态 `files` 清单中的本次文件。

## 依赖

- Python 3.x（仅标准库）
- SSH 密钥登录（远端部署时）
- 远端服务器需有 `tmux` 会话 `l4d2` 用于服务重启

## 许可

MIT
