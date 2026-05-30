---
name: l4d2-map-deployer
description: 根据用户输入的地图名，自动初始化并配置环境，从 Steam 抓取列表让用户选择。通过 Steam Web API + CDN 直链匿名下载 vpk，自动检测必需物品依赖，并部署到本地和远端服务器。
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
---

# L4D2 创意工坊地图自动部署

运行环境为 WSL2。用户输入即为要搜索的地图名称。

**启动时首先切换工作目录：**

```bash
cd ~/.claude/skills/l4d2-map-deployer
```

所有后续操作均在此目录下执行。uv 管理 Python 依赖（`pyproject.toml` 已含 `paramiko`），统一使用 `uv run python`。

---

## 前置检查: uv 环境

使用 Bash 检查 `uv --version`。

- **已安装** — 使用 Bash 执行 `uv sync` 确保依赖就位，然后继续 Step 0。
- **未安装** — 使用 Bash 自动安装：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装后执行 `export PATH="$HOME/.local/bin:$PATH"`，再执行 `uv sync`，然后继续 Step 0。

---

## Step 0: 环境检查与交互式配置

使用 Read 检查 `l4d2_config.json` 是否存在。

- **存在** — 跳过，进入 Step 1。
- **不存在** — 按以下子步骤收集并写入配置：

### 0a. 选择部署范围

使用 AskUserQuestion 询问：

- question: 「请选择默认部署范围」
- header: 「部署策略」
- options:
  - `{label: "双端部署", description: "同时部署到本地 Windows 和远端 Linux 服务器"}`
  - `{label: "仅本地", description: "只部署到本地 Windows，不同步远端"}`

### 0b. 收集信息

**若用户选择「仅本地」**，使用 AskUserQuestion 询问本地路径：

- header: 「本地addons路径」
- question: 「请输入 Windows 端 left4dead2/addons 的绝对路径」
- options: 提供一个默认路径和一个自定义选项，用户通过 Other 输入实际路径

收集后，使用 Write 写入 `l4d2_config.json`：

```json
{
  "local": { "local_addons_dir": "<用户填写的路径>" },
  "deploy_mode": "local_only"
}
```

**若用户选择「双端部署」**，分两批使用 AskUserQuestion 收集信息。

第一批（服务器连接）：

- header: 「远端IP」 question: 「请输入远端服务器 IP 地址」
- header: 「用户名」 question: 「请输入 SSH 用户名（默认 root）」
- header: 「SSH密钥路径」 question: 「请输入 SSH 私钥绝对路径（留空则使用默认 ~/.ssh/id_ed25519）」

第二批（路径）：

- header: 「远端addons」 question: 「请输入远端 left4dead2/addons 路径（不确定填 auto）」
- header: 「本地addons」 question: 「请输入 Windows 端 left4dead2/addons 绝对路径」

收集后，使用 Write 写入 `l4d2_config.json`：

```json
{
  "server": {
    "host": "<IP>",
    "username": "<用户名，默认 root>",
    "auth_type": "key",
    "ssh_key_path": "<SSH 私钥路径>",
    "remote_addons_dir": "<路径或 auto>"
  },
  "local": {
    "local_addons_dir": "<本地路径>"
  },
  "deploy_mode": "both"
}
```

远端认证仅支持 SSH 密钥登录，不支持密码。

### 0c. 继续

通知用户「配置已完成，开始搜索地图」，进入 Step 1。

---

## Step 1: Steam 工坊检索

使用 Bash 执行 `uv run python fetch_list.py "<用户输入的地图名>"`。

记录终端输出的全部结果（序号、ID、标题、描述、订阅数、大小、更新日期），供 Step 2 使用。

---

## Step 2: 地图选择

**必须先输出可见结果。** 将 Step 1 的搜索结果以清晰列表输出到聊天界面（含描述）：

```
搜索「xxx」的前 5 个结果：
[1] ID: xxx — 标题
    描述: （描述内容...）
[2] ID: xxx — 标题
    描述: （描述内容...）
...
```

输出完毕后，再使用 AskUserQuestion 弹出选择器。options 不足 4 个时用占位补齐，超过 4 个时优先取前 4 条放入 options，其余在 question 正文中列出。

解析用户回答得到 `<目标ID>`：1-5 取对应索引；纯数字直接使用。

---

## Step 2.5: 依赖检查

使用 Bash 执行 `uv run python check_deps.py <目标ID>`。

- **无依赖** — 直接进入 Step 3，`<下载列表>` = `<目标ID>`
- **有依赖** — 向用户输出依赖清单，自动将主地图 + 所有依赖合并为 `<下载列表>`（ID 以逗号分隔），无需再次确认

---

## Step 3: CDN 直链下载

无需 Docker/steamcmd。通过 Steam Web API 匿名获取 CDN 下载链接，直接从 Steam 服务器拉取 vpk 文件。

使用 Bash 执行：

```bash
uv run python download.py "<ID1,ID2,...>"
```

脚本自动：调用 API 获取 file_url → 跳过空壳 → 下载到 `l4d2_temp_dl/vpk/` → .bin 改 .vpk，预览图保留原名。

---

## Step 4: 验证产物

使用 Bash 确认 vpk 文件已就位：

```bash
ls -lh l4d2_temp_dl/vpk/
```

---

## Step 4.5: 部署范围确认

使用 Read 读取 `l4d2_config.json` 中的 `deploy_mode` 字段：

- **`"local_only"`** — 跳过询问，直接设置参数 `--local-only`
- **`"both"`** — 跳过询问，直接设置参数为空（双端部署）
- **`"ask"`**（或字段不存在）— 使用 AskUserQuestion 弹窗询问：
  - question: 「请选择部署范围」
  - header: 「部署范围」
  - options: `{label:"双端部署"}`, `{label:"仅本地"}`

根据选择或配置确定最终参数，传递给 Step 5。

---

## Step 5: 部署执行

使用 Bash 执行：

```bash
uv run python deploy.py <参数>
```

参数映射：双端部署（无参数）/ 仅本地（`--local-only`）

---

## Step 6: 收尾清理

使用 Bash 删除临时目录：

```bash
rm -rf l4d2_temp_dl
```

输出摘要：

```
========== 部署完成 ==========
下载项目:     <下载列表（主地图 + 依赖）>
本地路径:     <local_addons_dir>
远端主机:     <host>:<remote_addons_dir>
远端服务:     已重启
===============================
```

---

## 异常处理

- 前置检查 uv 安装失败 → 提示手动安装：`curl -LsSf https://astral.sh/uv/install.sh | sh`，终止
- Step 1 Steam 不可达 → 提示检查网络/代理，终止
- Step 3 下载失败 → 提示检查网络，CDN 可能限制并发，逐个重试，终止
- Step 4 无 vpk → 提示下载异常，保留 `l4d2_temp_dl` 供排查，终止
- Step 5 SSH 失败 → 提示检查 IP/端口/防火墙/凭据，终止
- Step 5 auto 搜索失败 → 提示手动填写 `remote_addons_dir`，终止
- 任何步骤失败立即终止，不执行后续步骤
