import re, sys, urllib.request

item_id = sys.argv[1] if len(sys.argv) > 1 else sys.exit("用法: python3 check_deps.py <ID>")

url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={item_id}"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})
try:
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode("utf-8", errors="ignore")
except Exception as e:
    sys.exit(f"[错误] 请求失败: {e}")

# 定位必需物品区域
m = re.search(r'id="RequiredItems"', html)
if not m:
    # 没有依赖项
    print(f"\n地图 {item_id} 无必需物品依赖。")
    sys.exit(0)

# 截取该区域（到下一个 </div> 的大区块结束，约 5000 字符内足够）
chunk = html[m.start():m.start() + 5000]

# 提取所有依赖项的 ID 和标题
deps = re.findall(
    r'workshop/filedetails/\?id=(\d+)[^>]*>\s*(?:<div[^>]*>\s*)?(.+?)\s*</',
    chunk, re.DOTALL,
)

if not deps:
    print(f"\n地图 {item_id} 未检测到必需物品。")
else:
    print(f"\n地图 {item_id} 依赖 {len(deps)} 个必需物品：\n")
    for i, (dep_id, dep_title) in enumerate(deps):
        dep_title = re.sub(r'<[^>]+>', '', dep_title).strip()
        print(f"  [{i+1}] ID: {dep_id}  |  标题: {dep_title}")
    print(f"\n总计: 主地图 + {len(deps)} 个依赖 = {1 + len(deps)} 个文件")

# 输出纯 ID 列表供脚本消费（最后一行，便于提取）
print(f"\n__DEP_IDS__: {item_id}," + ",".join(d[0] for d in deps))
