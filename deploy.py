import json, os, shutil, sys, re

# 解析参数
do_local = True
do_remote = True
if "--local-only" in sys.argv:
    do_remote = False
elif "--remote-only" in sys.argv:
    do_local = False

BASE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE, "l4d2_config.json"), "r", encoding="utf-8") as f:
    cfg = json.load(f)

# ── 定位 vpk ──
vpk_dir = os.path.join(BASE, "l4d2_temp_dl", "vpk")
if not os.path.isdir(vpk_dir):
    sys.exit("[错误] 未找到下载目录 l4d2_temp_dl/vpk/")

vpks = [os.path.join(vpk_dir, f) for f in os.listdir(vpk_dir) if f.endswith(".vpk")]
if not vpks:
    sys.exit("[错误] 未找到 .vpk 文件")
print(f"[信息] vpk 文件: {[os.path.basename(p) for p in vpks]}")

# ── 本地部署 (Windows 路径 → WSL /mnt 路径) ──
if do_local:
    local = cfg["local"]["local_addons_dir"]
    m = re.match(r"^([A-Za-z]):(.*)", local)
    if m:
        local = f"/mnt/{m.group(1).lower()}{m.group(2).replace(chr(92), '/')}"
        print(f"[信息] Windows 路径 → WSL: {local}")
    os.makedirs(local, exist_ok=True)
    for v in vpks:
        dst = os.path.join(local, os.path.basename(v))
        shutil.copy2(v, dst)
        print(f"[本地] {os.path.basename(v)} → {dst}")
else:
    print("[本地] 跳过（--remote-only）")

# ── 远端部署 (Paramiko SSH + SFTP) ──
remote_ok = False
if do_remote:
    from paramiko import SSHClient, AutoAddPolicy, RSAKey, Ed25519Key
    import socket

    srv = cfg["server"]
    user = srv.get("username", "root")
    rd = srv["remote_addons_dir"]

    try:
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())

        print(f"[远端] 连接 {user}@{srv['host']} ...")
        kwargs = {"hostname": srv["host"], "username": user, "timeout": 30, "banner_timeout": 30}

        kp = os.path.expanduser(srv.get("ssh_key_path", "~/.ssh/id_ed25519"))
        key = None
        last_err = None
        for kc in [Ed25519Key, RSAKey]:
            try:
                key = kc.from_private_key_file(kp)
                break
            except Exception as e:
                last_err = e
                continue
        if key is not None:
            ssh.connect(pkey=key, **kwargs)
        else:
            print(f"[远端] 指定密钥读取失败 ({last_err})，尝试默认密钥 ...")
            kwargs["look_for_keys"] = True
            ssh.connect(**kwargs)

        if rd == "auto":
            print("[远端] 自动搜索 left4dead2/addons ...")
            _, out, _ = ssh.exec_command(
                "find / -type d -path '*/left4dead2/addons' 2>/dev/null | head -n 1",
                timeout=30,
            )
            rd = out.read().decode().strip()
            if not rd:
                raise Exception("自动搜索 addons 路径失败")
            print(f"[远端] 找到: {rd}")

        sftp = ssh.open_sftp()
        for v in vpks:
            rp = rd.rstrip("/") + "/" + os.path.basename(v)
            print(f"[远端上传] {os.path.basename(v)} → {rp}")
            sftp.put(v, rp)
        sftp.close()

        print("[远端] 通过 tmux 重启 l4d2 服务 ...")
        restart_cmd = (
            "tmux send-keys -t l4d2 C-c && "
            "sleep 1 && "
            "tmux send-keys -t l4d2 './start.sh' Enter"
        )
        _, out, err = ssh.exec_command(restart_cmd, timeout=15)
        ec = out.channel.recv_exit_status()
        if ec == 0:
            print("[远端] 已发送重启指令到 tmux 会话 l4d2")
        else:
            print(f"[远端] tmux 指令异常 (exit={ec}): {err.read().decode(errors='ignore')}")
        remote_ok = True

    except (socket.timeout, TimeoutError, Exception) as e:
        print(f"[远端] 失败: {e}")
    finally:
        try:
            ssh.close()
        except Exception:
            pass
else:
    print("[远端] 跳过（--local-only）")

if do_local and do_remote:
    if remote_ok:
        print("[完成] 双端部署结束")
    else:
        print("[完成] 本地部署成功，远端失败请手动处理")
elif do_local:
    print("[完成] 本地部署结束")
elif remote_ok:
    print("[完成] 远端部署结束")
