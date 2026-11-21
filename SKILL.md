---
name: l4d2-map-deployer
description: 根据用户输入的地图名，自动初始化并配置环境，从 Steam 抓取列表让用户选择。通过 Steam Web API + CDN 直链匿名下载 vpk（双端模式下优先在服务器端下载再拉回本地），自动检测必需物品依赖，并部署到本地和远端服务器。
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
---

# L4D2 创意工坊地图自动部署

运行环境为 WSL2。用户输入即为要搜索的地图名称。

**启动时切换到当前读取的 `SKILL.md` 所在目录。** Codex 与 Claude 的安装目录可能不同，使用这份说明同目录下的脚本和配置，不要跳到另一份技能目录。

所有后续操作均在此目录下执行。全部脚本只用 Python 标准库，直接用 `python3` 运行。无 uv、无 Docker、无 steamcmd。

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
- options:
  - `{"label": "默认路径 (推荐)", "description": "E:\\SteamLibrary\\steamapps\\common\\Left 4 Dead 2\\left4dead2\\addons"}`
  - `{"label": "自定义路径", "description": "手动输入其他路径"}`

收集后，使用 Write 写入 `l4d2_config.json`。**注意：需用 json.dumps 序列化以确保反斜杠正确转义**，格式如下：

```json
{
  "local": { "local_addons_dir": "<用户填写的路径>" },
  "deploy_mode": "local_only"
}
```

**若用户选择「双端部署」**，分两批使用 AskUserQuestion 收集信息。

第一批（服务器连接）：

- header: 「远端IP」 question: 「请输入远端服务器 IP 地址」
- header: 「SSH端口」 question: 「请输入 SSH 端口（默认 22，直接回车跳过）」
- header: 「用户名」 question: 「请输入 SSH 用户名（默认 root）」
- header: 「SSH密钥路径」 question: 「请输入 SSH 私钥绝对路径（留空则使用默认 ~/.ssh/id_ed25519）」

第二批（路径）：

- header: 「远端addons」 question: 「请输入远端 left4dead2/addons 路径（不确定填 auto）」
- header: 「本地addons」 question: 「请输入 Windows 端 left4dead2/addons 绝对路径」

收集后，**对空值做默认处理**：
- username 为空 → 用 `"root"`
- ssh_key_path 为空 → 用 `"~/.ssh/id_ed25519"`
- port 为空 → 用 `22`
- remote_addons_dir 为空 → 用 `"auto"`

使用 Write 写入 `l4d2_config.json`（**必须用 json.dumps 序列化**）：

```json
{
  "server": {
    "host": "<IP>",
    "port": <端口>,
    "username": "<用户名>",
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

使用 Bash 执行 `python3 fetch_list.py "<用户输入的地图名>"`。

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

输出完毕后，再使用 AskUserQuestion 弹出选择器。options 不足 4 个时，仅展示实际结果数量（不要含无意义的占位选项）；超过 4 个时优先取前 4 条放入 options，其余在 question 正文中列出。

解析用户回答得到 `<目标ID>`：
- 用户选了 `[N] 标题` → 取第 N 项的 ID
- 用户选了纯数字 → 直接作为 ID 使用
- 用户选了 Other 输入 → 取输入的第 N 项或纯数字 ID，同上规则
- 索引越界 → 提示「无效选择」，重新使用 AskUserQuestion 询问

---

## Step 2.5: 依赖检查

使用 Bash 执行 `python3 check_deps.py <目标ID>`。

- **无依赖** — 直接进入 Step 3，`<下载列表>` = `<目标ID>`
- **有依赖** — 向用户输出依赖清单，自动将主地图 + 所有依赖合并为 `<下载列表>`（ID 以逗号分隔），无需再次确认

---

## Step 3: CDN 直链下载

通过 Steam Web API 匿名获取 CDN 下载链接。`download.py` 只用 Python 标准库。

**命名规则**：VPK 命名为 `<查询名>_<工坊ID>.vpk`——主地图与依赖统一使用 Step 1 的用户 query 作为前缀，同一张地图及其依赖因此共享同一前缀，按文件名排序即可归组。远端与本地同名，便于日后按前缀整组清理。名称中的空白和 Windows 非法字符（`\ / : * ? " < > |`）会被替换为下划线。

下载器默认以 **4 条连接、每段 8MB** 下载同一文件；文件之间依次处理，避免并发数随依赖数量增长。仅使用 Python 标准库。

- 分段保存到 `<文件名>.vpk.parts/`，每段重试从已有字节继续，原版遗留的半成品 VPK 也会先导入分段续传。
- 单连接连续 20 秒低于 512KB/s 时重建连接；读取超时默认 15 秒，每段最多尝试 8 次。实际低带宽可用 `--min-speed 0` 关闭低速检测。
- 校验 HTTP 206、Content-Range 和分段大小，全部完成后原子合并成 `.vpk`。CDN 忽略 Range 时自动退回单连接，该情况下中断重试从头开始。
- `--workers 8` 可提高连接数；调整连接数不影响已有断点。续传时保持 `--chunk-size` 不变；URL、文件大小或分段配置不一致时保留断点并报错，避免混合文件版本。
- API 标明为 `.png`、`.jpg` 等非 VPK 的依赖会明确记录为跳过，不下载、不部署；空扩展名或 `.bin` 继续按原有 VPK 规则处理。

**首先使用 Read 检查 `l4d2_config.json` 的 `deploy_mode`，然后按模式分流：**

### 模式 A: `"both"` — 服务器端下载 → 拉回本地（默认）

利用服务器带宽直连 Steam CDN，避免本地网络瓶颈。

**3a. 从配置读取 SSH 参数：**

在后续 SCP/SSH 命令之前，先用 python3 内联读取配置中的服务器连接信息：

```bash
SRV_HOST=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server']['host'])")
SRV_PORT=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server'].get('port',22))")
SRV_USER=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server'].get('username','root'))")
SRV_KEY=$(python3 -c "import json,os; print(os.path.expanduser(json.load(open('l4d2_config.json'))['server'].get('ssh_key_path','~/.ssh/id_ed25519')))")
```

> 后续命令直接使用 `$SRV_HOST` `$SRV_PORT` `$SRV_USER` `$SRV_KEY` 变量。

**3b.** 上传下载脚本到服务器：

```bash
scp -P "$SRV_PORT" -i "$SRV_KEY" download.py "$SRV_USER@$SRV_HOST":/tmp/download_map.py
```

**3c.** 使用脚本自带的后台模式启动（与远端默认 shell 无关，fish 也可执行）：

```bash
ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "python3 /tmp/download_map.py '<下载列表>' '<查询名>' --workers 4 --background"
```

`--background` 将子进程放入独立会话，断开标准输入，输出写到 `/tmp/l4d2_temp_dl/download.log`，返回后台 PID。启动返回 0 仅表示启动已确认，**不能当作下载成功**。重复启动同一输出目录会被文件锁拒绝，且不会覆盖原任务状态。

定期查询日志及状态；每次间隔约 10–30 秒，无需保持一个长 SSH 会话：

```bash
ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "tail -n 20 /tmp/l4d2_temp_dl/download.log"
ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "cat /tmp/l4d2_temp_dl/status.json"
```

状态文件的 `pid` 必须与此次启动返回的 PID 对应：`running` 继续等待，`completed` 才进入下一步，`failed` 查看日志并保留断点。SSH 返回 255 时先重新查询状态；这只代表连接失败，不能直接推断远端下载进程已停止。状态长时间停在 running 时，通过 `ps -p <PID> -o pid=,etimes=,args=` 核实是否仍在运行；确认退出后才续传重启。不要盲目启动第二份任务或清理目录。

> `<查询名>` 必填。上例为本地 Bash 命令，查询名进入远端命令前须安全引用；复杂名称建议用本地 Python 的 `shlex.quote()` 生成远端每个参数，再以 `subprocess.run(["ssh", ..., remote_command])` 调用，避免手工嵌套引号。不要在默认 fish 中执行 Bash 的 `S1=$(...)`。需要 Bash 语法时显式调用 `bash -lc`，或用单次远端 Python 完成检测。

**3d.** 拉回 vpk 到本地：

```bash
mkdir -p l4d2_temp_dl/vpk
scp -P "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST":/tmp/l4d2_temp_dl/vpk/*.vpk l4d2_temp_dl/vpk/
```

### 模式 B: `"local_only"` — 本地下载

无服务器时使用，直接在本地拉取 Steam CDN：

```bash
python3 download.py "<下载列表>" "<查询名>" --workers 4
```

下载到 `l4d2_temp_dl/vpk/`，按命名规则重命名。

---

## Step 4: 验证产物

先确认 `l4d2_temp_dl/status.json` 的 `state` 为 `completed`，并按其 `files` 清单核对本次 VPK 已就位。若临时目录残留历史文件，后续 SCP/CP 改为逐个指定 `files` 中的文件名，避免通配符混入旧图。`.vpk.parts/` 仅为断点，不能部署：

```bash
ls -lh l4d2_temp_dl/vpk/
```

---

## Step 4.5: 部署范围确认

使用 Read 读取 `l4d2_config.json` 中的 `deploy_mode` 字段：

- **`"local_only"`** — 跳过询问，只部署本地
- **`"both"`** — 跳过询问，双端部署
- **`"ask"`**（或字段不存在）— 使用 AskUserQuestion 弹窗询问：
  - question: 「请选择部署范围」
  - header: 「部署范围」
  - options: `{label:"双端部署"}`, `{label:"仅本地"}`

---

## Step 5: 部署执行

直接用 shell 命令完成。

### 5a. 读取配置变量

```bash
# 本地路径（自动转换 Windows 盘符 E:\... → /mnt/e/...）
LOCAL_DIR=$(python3 -c "
import json, re
cfg = json.load(open('l4d2_config.json'))
p = cfg['local']['local_addons_dir']
m = re.match(r'^([A-Za-z]):(.*)', p)
print(f'/mnt/{m.group(1).lower()}{m.group(2).replace(chr(92),chr(47))}' if m else p)
")
```

若双端部署，同时读取远端参数（注意 Bash 不共享变量，需重新读取）：

```bash
SRV_HOST=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server']['host'])")
SRV_PORT=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server'].get('port',22))")
SRV_USER=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server'].get('username','root'))")
SRV_KEY=$(python3 -c "import json,os; print(os.path.expanduser(json.load(open('l4d2_config.json'))['server'].get('ssh_key_path','~/.ssh/id_ed25519')))")
REMOTE_DIR=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server']['remote_addons_dir'])")
```

> 若 `REMOTE_DIR` 为 `"auto"`，需要先用 `ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "find / -type d -path '*/left4dead2/addons' 2>/dev/null | head -n 1"` 自动探测。

### 5b. 本地部署

```bash
cp l4d2_temp_dl/vpk/*.vpk "$LOCAL_DIR"/
echo "[本地] vpk → $LOCAL_DIR"
```

### 5c. 远端部署（仅双端模式）

vpk 已在服务器 `/tmp/l4d2_temp_dl/vpk/`，直接 cp 到 addons 目录：

```bash
ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "cp /tmp/l4d2_temp_dl/vpk/*.vpk $REMOTE_DIR/"
echo "[远端] vpk → $REMOTE_DIR"
```

重启 L4D2 服务：

```bash
ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "tmux send-keys -t l4d2 C-c && sleep 1 && tmux send-keys -t l4d2 './start.sh' Enter"
echo "[远端] 已重启 l4d2 服务"
```

---

## Step 6: 收尾清理

使用 Bash 删除本地临时目录和服务器端残留文件。**注意：若与 Step 5 分开调用，SSH 变量会丢失，需先重新读取：**

```bash
SRV_HOST=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server']['host'])")
SRV_PORT=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server'].get('port',22))")
SRV_USER=$(python3 -c "import json; print(json.load(open('l4d2_config.json'))['server'].get('username','root'))")
SRV_KEY=$(python3 -c "import json,os; print(os.path.expanduser(json.load(open('l4d2_config.json'))['server'].get('ssh_key_path','~/.ssh/id_ed25519')))")
rm -rf l4d2_temp_dl && ssh -p "$SRV_PORT" -i "$SRV_KEY" "$SRV_USER@$SRV_HOST" "rm -rf /tmp/l4d2_temp_dl /tmp/download_map.py"
```

> 若 `local_only` 模式，只清理 `rm -rf l4d2_temp_dl`。

输出摘要：

- **双端部署：**
  ```
  ========== 部署完成 ==========
  下载项目:     <下载列表（主地图 + 依赖）>
  本地路径:     <local_addons_dir>
  远端主机:     <host>:<remote_addons_dir>
  远端服务:     已重启
  ===============================
  ```

- **仅本地：**
  ```
  ========== 部署完成 ==========
  下载项目:     <下载列表（主地图 + 依赖）>
  本地路径:     <local_addons_dir>
  ===============================
  ```

---

## 异常处理

- Step 1 Steam 不可达 → 提示检查网络/代理，终止
- Step 3 下载持续低速 → 脚本自动按分段重连；耗尽重试时保留断点，核实任务已退出后重新执行相同命令续传
- Step 3 SSH 断连/返回 255 → 重连查询远端 PID、状态和日志，不能直接判定后台下载失败
- Step 3 服务器下载状态为 failed → 检查日志和网络，保留分段，不进入部署
- Step 3 SCP 拉回失败 → 提示检查 SSH 连接，终止
- Step 3 本地下载失败 → 保留分段并检查日志；可降低 `--workers` 重试，或用 `--min-speed 0` 适应低带宽
- Step 4 无 vpk → 提示下载异常，保留 `l4d2_temp_dl` 供排查，终止
- Step 5 SSH 失败 → 提示检查 IP/端口/防火墙/凭据，终止
- Step 5 auto 搜索失败 → 提示手动填写 `remote_addons_dir`，终止
- 下载未确认完成时不执行部署/重启/清理；普通 SSH 断连可继续只读查询远端状态
- 成功部署后才按 Step 6 清理；失败时保留日志、状态文件和分段以便恢复
