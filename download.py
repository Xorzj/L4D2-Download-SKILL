"""Steam Workshop downloader: bounded parallel ranges, resumable parts, stdlib only."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request


MIB = 1024 * 1024
MAX_ATTEMPTS = 8
API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity", "Connection": "close"}


class RangeUnsupported(Exception):
    pass


class DownloadStopped(Exception):
    pass


def out_name(label, wid, orig):
    """Preserve the original extension; empty/.bin names are Workshop VPKs."""
    ext = os.path.splitext(orig)[1].lower()
    if ext in ("", ".bin"):
        ext = ".vpk"
    label = re.sub(r'[\\/:*?"<>|]', "_", label)
    label = re.sub(r"\s+", "_", label)
    label = re.sub(r"_+", "_", label).strip("._")
    return f"{label}_{wid}{ext}" if label and label != wid else f"{wid}{ext}"


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def open_url(url, start=None, end=None, timeout=15):
    headers = dict(HEADERS)
    if start is not None:
        headers["Range"] = f"bytes={start}-{end if end is not None else ''}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def validate_range(response, start, end, size):
    if response.status == 200:
        raise RangeUnsupported("CDN 忽略 Range，改用单连接下载")
    expected = f"bytes {start}-{end}/{size}"
    if response.status != 206 or response.headers.get("Content-Range") != expected:
        raise OSError(f"Range 响应不匹配: {response.status}, {response.headers.get('Content-Range')!r}; 预期 {expected}")
    length = response.headers.get("Content-Length")
    if length is not None and int(length) != end - start + 1:
        raise OSError("Content-Length 与请求分段长度不一致")
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise OSError("CDN 返回压缩响应，无法安全按字节续传")


class Progress:
    def __init__(self, size, counts):
        self.size = size
        self.counts = counts
        self.lock = threading.Lock()
        self.last_time = time.monotonic()
        self.last_bytes = sum(counts.values())

    def reset(self, counts):
        with self.lock:
            self.counts = counts
            self.last_time = time.monotonic()
            self.last_bytes = sum(counts.values())

    def update(self, key, count):
        with self.lock:
            self.counts[key] = count
            now = time.monotonic()
            total = sum(self.counts.values())
            elapsed = now - self.last_time
            if elapsed >= 2 or total - self.last_bytes >= 5 * MIB:
                rate = (total - self.last_bytes) / max(elapsed, 0.001) / MIB
                print(f"    进度: {total / MIB:.1f}/{self.size / MIB:.1f}MB ({total * 100 // self.size}%) | {rate:.2f}MB/s", flush=True)
                self.last_time, self.last_bytes = now, total


def read_into(response, target, have, expected, progress, key, stop, min_speed, slow_seconds):
    """read1 permits rate checks on short reads instead of waiting for a full buffer."""
    window_time = time.monotonic()
    window_bytes = 0
    read = getattr(response, "read1", response.read)
    with target.open("ab") as stream:
        while have < expected:
            if stop.is_set():
                raise DownloadStopped()
            chunk = read(min(64 * 1024, expected - have))
            if not chunk:
                raise OSError(f"连接提前结束: {have}/{expected} 字节")
            stream.write(chunk)
            have += len(chunk)
            window_bytes += len(chunk)
            progress.update(key, have)
            elapsed = time.monotonic() - window_time
            if have < expected and min_speed and elapsed >= slow_seconds:
                rate = window_bytes / elapsed
                if rate < min_speed:
                    raise OSError(f"持续低速 {rate / 1024:.0f}KB/s，重新建立连接")
                window_time, window_bytes = time.monotonic(), 0


def get_size(path):
    return path.stat().st_size if path.exists() else 0


def transfer(url, target, start, end, size, progress, key, stop, *,
             ranged=True, timeout=15, min_speed=512 * 1024, slow_seconds=20,
             max_attempts=MAX_ATTEMPTS, retry_delay=2):
    expected = end - start + 1
    for attempt in range(1, max_attempts + 1):
        if stop.is_set():
            raise DownloadStopped()
        have = get_size(target)
        if have == expected:
            return
        if have > expected:
            raise OSError(f"分段文件过大: {target.name}")
        try:
            offset = start + have
            # Without Range support, every retry must truncate the old full response.
            with open_url(url, offset if ranged else None, end if ranged else None, timeout) as response:
                if ranged:
                    validate_range(response, offset, end, size)
                else:
                    if response.status != 200:
                        raise OSError(f"完整下载响应错误: HTTP {response.status}")
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) != size:
                        raise OSError("完整下载长度与 Steam API 不一致")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise OSError("完整下载不接受压缩响应")
                    target.write_bytes(b"")
                    have = 0
                    progress.update(key, 0)
                read_into(response, target, have, expected, progress, key, stop, min_speed, slow_seconds)
            return
        except (RangeUnsupported, DownloadStopped):
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            print(f"    分段 {key} 第 {attempt}/{max_attempts} 次中断: {exc}", flush=True)
            if attempt == max_attempts:
                raise OSError(f"分段 {key} 重试耗尽；保留断点") from exc
            if stop.wait(min(retry_delay * attempt, 10)):
                raise DownloadStopped()


def seed_parts(source, parts):
    """Import an old downloader's contiguous partial VPK without downloading it again."""
    available = get_size(source)
    if not available:
        return
    with source.open("rb") as stream:
        for start, end, path in parts:
            count = min(end + 1, available) - start
            have = get_size(path)
            if count > have:
                stream.seek(start + have)
                with path.open("ab") as target:
                    remaining = count - have
                    while remaining:
                        data = stream.read(min(MIB, remaining))
                        if not data:
                            raise OSError("旧断点文件在导入时被截断")
                        target.write(data)
                        remaining -= len(data)
    print(f"    已导入旧断点: {available / MIB:.1f}MB", flush=True)


def download_file(url, out_path, size, *, workers=4, chunk_size=8 * MIB, **options):
    """Return success only after validated ranges are atomically assembled."""
    out_path = Path(out_path)
    stop = threading.Event()
    try:
        if size <= 0 or workers < 1 or chunk_size < 1:
            raise ValueError("文件大小、并发数和分段大小必须为正数")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if get_size(out_path) == size:
            return True
        state = out_path.with_name(out_path.name + ".parts")
        state.mkdir(exist_ok=True)
        manifest = state / "manifest.json"
        identity = {"url": url, "size": size, "chunk_size": chunk_size}
        if manifest.exists():
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            if previous != identity:
                raise ValueError(f"断点元数据与当前下载不一致，请检查或移走 {state} 后重试")
        else:
            write_json(manifest, identity)
        parts = [(start, min(start + chunk_size, size) - 1, state / f"{i:06d}.part")
                 for i, start in enumerate(range(0, size, chunk_size))]
        if get_size(out_path) > size:
            raise ValueError("现有文件大于 Steam API 声明大小，请检查后重试")
        for start, end, path in parts:
            if get_size(path) > end - start + 1:
                raise ValueError(f"分段文件过大: {path}")
        if out_path.exists():
            seed_parts(out_path, parts)
            out_path.unlink()  # Only complete files may retain the deployable .vpk name.
        single = state / "single.part"
        if single.exists():
            if get_size(single) > size:
                raise ValueError("单连接断点大于预期大小")
            seed_parts(single, parts)
        progress = Progress(size, {i: get_size(p) for i, (_, _, p) in enumerate(parts)})
        print(f"    {min(workers, len(parts))} 路下载，分段 {chunk_size / MIB:g}MB，已缓存 {sum(progress.counts.values()) / MIB:.1f}MB", flush=True)
        pending = [(i, start, end, p) for i, (start, end, p) in enumerate(parts) if get_size(p) != end - start + 1]
        if pending:
            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(transfer, url, p, start, end, size, progress, i, stop, **options)
                               for i, start, end, p in pending]
                    try:
                        for future in as_completed(futures):
                            future.result()
                    except BaseException:
                        stop.set()
                        for future in futures:
                            future.cancel()
                        raise
            except RangeUnsupported as exc:
                print(f"    {exc}；CDN 不支持断点时重试将从头开始", flush=True)
                stop.clear()
                progress.reset({"single": get_size(single)})
                transfer(url, single, 0, size - 1, size, progress, "single", stop, ranged=False, **options)
                if get_size(single) != size:
                    raise OSError("单连接下载大小校验失败")
                os.replace(single, out_path)
                shutil.rmtree(state)
                return True
        # Preserve every complete part until the atomic final rename succeeds.
        assembled = state / "assembled.tmp"
        with assembled.open("wb") as target:
            for start, end, path in parts:
                if get_size(path) != end - start + 1:
                    raise OSError(f"合并前分段长度错误: {path.name}")
                with path.open("rb") as source:
                    shutil.copyfileobj(source, target, MIB)
        if get_size(assembled) != size:
            raise OSError("合并后文件大小校验失败")
        os.replace(assembled, out_path)
        shutil.rmtree(state)
        return True
    except (OSError, ValueError) as exc:
        print(f"    [失败] {exc}", flush=True)
        return False
    finally:
        stop.set()


def fetch_details(ids):
    params = {"itemcount": str(len(ids))}
    params.update({f"publishedfileids[{i}]": wid for i, wid in enumerate(ids)})
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(API_URL, data=urllib.parse.urlencode(params).encode())
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            return {str(d["publishedfileid"]): d for d in data.get("response", {}).get("publishedfiledetails", [])}
        except (OSError, ValueError) as exc:
            print(f"  [API] 第 {attempt}/3 次请求失败: {exc}", flush=True)
            if attempt == 3:
                raise
            time.sleep(2 * attempt)


def run(args):
    ids = list(dict.fromkeys(x.strip() for x in args.ids.split(",") if x.strip()))
    if not ids or any(not wid.isdecimal() for wid in ids):
        raise ValueError("请输入逗号分隔的工坊数字 ID")
    details = fetch_details(ids)
    failed, skipped, completed = [], [], []
    print(f"准备下载 {len(ids)} 个项目：", flush=True)
    for wid in ids:
        detail = details.get(wid)
        if not detail or detail.get("result", 1) != 1:
            print(f"  [失败] {wid} — API 未返回有效数据", flush=True)
            failed.append(wid)
            continue
        title = detail.get("title", wid)
        filename = detail.get("filename", "")
        name = out_name(args.query.strip() or title, wid, filename)
        if Path(name).suffix != ".vpk":
            print(f"  [跳过非 VPK] {title} — {filename}", flush=True)
            skipped.append(wid)
            continue
        url = detail.get("file_url", "")
        size = int(detail.get("file_size", 0))
        if not url or size < 1024:
            print(f"  [跳过空壳] {title} — 无链接或文件过小 ({size}B)", flush=True)
            skipped.append(wid)
            continue
        print(f"  [{title}] → {name} ({size / MIB:.1f}MB)", flush=True)
        if not download_file(url, args.output_dir / name, size, workers=args.workers,
                             chunk_size=args.chunk_size * MIB, timeout=args.timeout,
                             min_speed=args.min_speed * 1024, slow_seconds=args.slow_seconds,
                             max_attempts=args.max_attempts):
            failed.append(wid)
        else:
            completed.append(name)
            print(f"    完成: {name}", flush=True)
    # A PNG-only selection or empty shell is not a successful map download.
    if not completed and not failed:
        failed.append("未得到可部署的 VPK")
    return {"state": "failed" if failed else "completed", "failed": failed,
            "skipped": skipped, "files": sorted(completed), "output_dir": str(args.output_dir)}


def parse_args(argv=None):
    base = Path(__file__).resolve().parent / "l4d2_temp_dl"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", help="工坊 ID，以逗号分隔")
    parser.add_argument("query", nargs="?", default="", help="统一文件名前缀")
    parser.add_argument("--workers", type=int, default=4, help="单文件最大并发连接数 (默认 4；文件之间串行)")
    parser.add_argument("--chunk-size", type=int, default=8, help="每段 MB (默认 8；续传时保持一致)")
    parser.add_argument("--timeout", type=float, default=15, help="连接及读取超时秒数")
    parser.add_argument("--min-speed", type=float, default=512, help="单连接最低 KB/s，0 禁用低速重连")
    parser.add_argument("--slow-seconds", type=float, default=20, help="持续低速检测窗口秒数")
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS, help="每段最多尝试次数")
    parser.add_argument("--output-dir", type=Path, default=base / "vpk")
    parser.add_argument("--background", action="store_true", help="脱离 SSH 会话运行，立即返回 PID")
    parser.add_argument("--log-file", type=Path, default=base / "download.log")
    parser.add_argument("--status-file", type=Path, default=base / "status.json")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 32 or min(args.chunk_size, args.timeout, args.slow_seconds, args.max_attempts) <= 0 or args.min_speed < 0:
        parser.error("workers 范围为 1..32；大小、超时、窗口、次数必须为正；min-speed 不能为负")
    for field in ("output_dir", "log_file", "status_file"):
        setattr(args, field, getattr(args, field).resolve())
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.background:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-u", str(Path(__file__).resolve()),
                   *[arg for arg in (sys.argv[1:] if argv is None else argv) if arg != "--background"]]
        with args.log_file.open("ab", buffering=0) as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        print(f"后台 PID: {process.pid}\n日志: {args.log_file}\n状态: {args.status_file}", flush=True)
        # Wait for this child to acquire the lock and replace any previous job's status.
        # This also makes a duplicate launch return failure without overwriting its status.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if json.loads(args.status_file.read_text(encoding="utf-8")).get("pid") == process.pid:
                    return 0  # Launch acknowledgement only; check final state separately.
            except (OSError, ValueError):
                pass
            if process.poll() is not None:
                print("后台任务未成功启动，请检查日志；原任务状态不会被覆盖", file=sys.stderr)
                return 1
            time.sleep(0.05)
        print("后台启动尚未确认，进程可能仍在运行；先检查 PID/日志，勿重复启动", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / ".download.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[失败] 此目录已有下载任务；请查询日志/状态，避免重复启动", file=sys.stderr)
            return 1
        status = {"state": "running", "pid": os.getpid(), "ids": args.ids, "started_at": time.time()}
        write_json(args.status_file, status)
        try:
            status.update(run(args))
        except (Exception, KeyboardInterrupt) as exc:
            status.update(state="failed", error=str(exc) or type(exc).__name__)
            print(f"[失败] {status['error']}", flush=True)
        status["finished_at"] = time.time()
        write_json(args.status_file, status)
        print(f"下载状态: {status['state']}；文件位于 {args.output_dir}", flush=True)
        return 0 if status["state"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
