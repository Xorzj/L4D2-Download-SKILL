import json, os, sys, urllib.parse, urllib.request

ids_str = sys.argv[1] if len(sys.argv) > 1 else sys.exit("用法: python3 download.py <ID1,ID2,...>")
ids = [x.strip() for x in ids_str.split(",") if x.strip()]

# ── 调用 API 获取每个 ID 的下载信息 ──
api_params = {"itemcount": str(len(ids))}
for i, wid in enumerate(ids):
    api_params[f"publishedfileids[{i}]"] = wid

req = urllib.request.Request(
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
    data=urllib.parse.urlencode(api_params).encode(),
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
resp = urllib.request.urlopen(req, timeout=15)
api_data = json.loads(resp.read().decode())
details = {d["publishedfileid"]: d for d in api_data.get("response", {}).get("publishedfiledetails", [])}

# ── 准备下载目录 ──
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "l4d2_temp_dl", "vpk")
os.makedirs(base, exist_ok=True)

print(f"\n准备下载 {len(ids)} 个项目：\n")

for wid in ids:
    d = details.get(wid)
    if not d:
        print(f"  [跳过] {wid} — API 未返回数据")
        continue

    file_url = d.get("file_url", "")
    filename = d.get("filename", "")
    title = d.get("title", wid)
    size = int(d.get("file_size", 0))

    if not file_url:
        print(f"  [跳过] {title} — 无下载链接")
        continue

    # 跳过空壳文件
    if size < 1024:
        print(f"  [跳过] {title} — 文件过小 ({size}B)")
        continue

    # 确定输出文件名：非 vpk/bin 的保留原始扩展名（如预览图）
    name = os.path.basename(filename)
    if name.endswith(".bin"):
        name = name[:-4] + ".vpk"
    elif not name.endswith(".vpk"):
        # 预览图等，保留原名
        pass
    if name.endswith(".bin"):
        name = name[:-4] + ".vpk"
    if not name.endswith(".vpk"):
        name = name + ".vpk"
    out_path = os.path.join(base, name)

    # 检查是否已存在
    if os.path.exists(out_path) and os.path.getsize(out_path) == size:
        print(f"  [已存在] {name} ({size / 1024 / 1024:.0f}MB)")
        continue

    print(f"  [{title}] → {name} ({size / 1024 / 1024:.0f}MB)")

    # 下载
    dl_req = urllib.request.Request(file_url)
    dl_req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    try:
        dl_resp = urllib.request.urlopen(dl_req, timeout=300)
        with open(out_path, "wb") as f:
            downloaded = 0
            while True:
                chunk = dl_resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if size:
                    pct = downloaded * 100 // size
                    print(f"\r    进度: {downloaded / 1024 / 1024:.0f}MB / {size / 1024 / 1024:.0f}MB ({pct}%)", end="")
        print()
        print(f"    完成: {name}")
    except Exception as e:
        print(f"\n    [失败] {e}")
        # 清理残损文件
        if os.path.exists(out_path):
            os.remove(out_path)

print(f"\n下载完毕，文件位于: {base}/")
for f in sorted(os.listdir(base)):
    fpath = os.path.join(base, f)
    print(f"  {f}  ({os.path.getsize(fpath) / 1024 / 1024:.0f}MB)")
