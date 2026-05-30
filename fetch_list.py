import json, re, sys, time, urllib.parse, urllib.request

query = sys.argv[1] if len(sys.argv) > 1 else sys.exit("用法: python3 fetch_list.py <地图名>")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

browse_url = (
    "https://steamcommunity.com/workshop/browse/"
    f"?appid=550&searchtext={urllib.request.quote(query)}&browsesort=textsearch"
)
req = urllib.request.Request(browse_url, headers=HEADERS)
try:
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode("utf-8", errors="ignore")
except Exception as e:
    sys.exit(f"[错误] 请求失败: {e}")


# ── 路径 1: 从 React SSR window.SSR.renderContext 提取 ──
def extract_from_ssr(html):
    # window.SSR.renderContext=JSON.parse("{...}");
    # 外层 JSON 含 queryData 字段（本身是 JSON 字符串），需三重解码
    m = re.search(r'window\.SSR\.renderContext\s*=\s*JSON\.parse\("((?:[^"\\]|\\.)*)"\)', html)
    if not m:
        return []
    raw = m.group(1)
    try:
        outer_str = json.loads('"' + raw + '"')
        outer = json.loads(outer_str)
    except (json.JSONDecodeError, TypeError):
        return []

    query_data_str = outer.get("queryData", "")
    if not query_data_str:
        return []
    try:
        query_data = json.loads(query_data_str)
    except (json.JSONDecodeError, TypeError):
        return []

    queries = query_data.get("queries", [])
    results = None
    for q in queries:
        qk = q.get("queryKey", [])
        data = q.get("state", {}).get("data")
        if isinstance(data, dict) and isinstance(data.get("results"), list) and data["results"]:
            # 搜索结果的 queryKey 为 ["workshop_browse", {...search params...}]
            if isinstance(qk, list) and len(qk) >= 1 and qk[0] == "workshop_browse":
                results = data["results"]
                break

    if not results:
        return []

    items = []
    seen = set()
    for r in results:
        item_id = r.get("publishedfileid", "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        items.append({
            "id": item_id,
            "title": (r.get("title") or "").strip(),
            "desc": (r.get("short_description") or "").strip(),
            "subscriptions": r.get("subscriptions", 0) or 0,
            "favorited": r.get("favorited", 0) or 0,
            "views": r.get("views", 0) or 0,
            "file_size": int(r.get("file_size", 0) or 0),
            "time_updated": r.get("time_updated", 0) or 0,
        })
    return items


# ── 路径 2 (Legacy): SharedFileBindMouseHover + Steam Web API ──
def extract_from_legacy(html):
    items = []
    seen = set()
    for m in re.finditer(r'SharedFileBindMouseHover\s*\(\s*"[^"]*"\s*,\s*false\s*,\s*', html):
        start = m.end()
        depth = 0
        end = start
        for i in range(start, min(start + 5000, len(html))):
            ch = html[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        json_str = html[start:end]
        try:
            data = json.loads(json_str)
            item_id = data.get("id", "")
            if item_id and item_id not in seen:
                seen.add(item_id)
                items.append({
                    "id": item_id,
                    "title": data.get("title", "").strip(),
                    "desc": data.get("description", "").strip(),
                    "subscriptions": 0,
                    "favorited": 0,
                    "views": 0,
                    "file_size": 0,
                    "time_updated": 0,
                })
        except json.JSONDecodeError:
            continue

    if not items:
        return []

    ids = [it["id"] for it in items[:5]]
    api_params = {"itemcount": str(len(ids))}
    for i, wid in enumerate(ids):
        api_params[f"publishedfileids[{i}]"] = wid

    api_req = urllib.request.Request(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
        data=urllib.parse.urlencode(api_params).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        api_resp = urllib.request.urlopen(api_req, timeout=15)
        api_data = json.loads(api_resp.read().decode())
        details = {d["publishedfileid"]: d for d in api_data.get("response", {}).get("publishedfiledetails", [])}
    except Exception:
        details = {}

    for it in items:
        d = details.get(it["id"], {})
        it["subscriptions"] = d.get("subscriptions", 0) or 0
        it["favorited"] = d.get("favorited", 0) or 0
        it["views"] = d.get("views", 0) or 0
        it["file_size"] = int(d.get("file_size", 0) or 0)
        it["time_updated"] = d.get("time_updated", 0) or 0

    return items


# ── 输出 ──
def format_output(items, query):
    count = min(5, len(items))
    print(f"\n搜索 '{query}' 的前 {count} 个结果：\n")
    for i in range(count):
        it = items[i]
        subs = it.get("subscriptions", 0)
        favs = it.get("favorited", 0)
        views = it.get("views", 0)
        ts = it.get("time_updated", 0)
        updated = time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "未知"
        size_mb = int(it.get("file_size", 0)) / (1024 * 1024) if it.get("file_size") else 0

        desc = it["desc"]
        if len(desc) > 300:
            desc = desc[:300] + "..."

        print(f"  [{i+1}] ID: {it['id']}")
        print(f"      标题: {it['title']}")
        print(f"      描述: {desc}")
        parts = [f"订阅 {subs:,}"]
        if favs:
            parts.append(f"收藏 {favs:,}")
        if views:
            parts.append(f"浏览 {views:,}")
        if size_mb:
            parts.append(f"{size_mb:.0f}MB")
        parts.append(f"更新 {updated}")
        print(f"      数据: {'  |  '.join(parts)}")
        print()


# ── 主流程: SSR 优先, Legacy 兜底 ──
items = extract_from_ssr(html)
if not items:
    items = extract_from_legacy(html)

if not items:
    sys.exit("[错误] 未找到任何结果，请检查地图名称拼写或网络连接。")

format_output(items, query)
