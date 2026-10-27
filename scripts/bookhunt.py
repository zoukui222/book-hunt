#!/usr/bin/env python3
"""bookhunt.py — 按书名搜公版书，从合法站点下载。

只连三类源，全部是公版/开放许可项目：
  gutenberg        Project Gutenberg（7.5 万+ 本，含中文古籍与名著）
  standardebooks   Standard Ebooks（精校英文公版 epub）
  wikisource       维基文库（CC BY-SA，中文公版原文）

在版书籍（受版权保护）不提供下载，脚本会给合法获取渠道。

用法:
    python scripts/bookhunt.py probe
    python scripts/bookhunt.py search "红楼梦" --limit 5
    python scripts/bookhunt.py search "pride and prejudice" --json
    python scripts/bookhunt.py fetch gutenberg:24264 --out books --format epub
    python scripts/bookhunt.py fetch standardebooks:/ebooks/jane-austen/pride-and-prejudice --out books

只依赖标准库。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
try:
    VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() or "dev"
except OSError:
    VERSION = "dev"

UA = f"book-hunt/{VERSION} (public-domain book fetcher; +https://github.com/zoukui222/book-hunt)"
ALLOWED_HOSTS = ("www.gutenberg.org", "gutenberg.org", "standardebooks.org",
                 "zh.wikisource.org", "en.wikisource.org", "zh.m.wikisource.org")
TIMEOUT = 25

LEGAL_CHANNELS = [
    "微信读书 / 豆瓣阅读 / 京东读书（在售电子版）",
    "当地公共图书馆数字借阅（国家图书馆、深圳图书馆等）",
    "Open Library 借阅（archive.org，部分地区可借）",
    "纸书：京东 / 当当 / 孔夫子旧书网",
]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def http_get(url: str, timeout: int = TIMEOUT) -> tuple[int, str, bytes]:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"拒绝访问非白名单域名：{host}（本工具只连公版书站点）")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", b""
    except Exception as e:  # 网络不通/超时
        return 0, f"error: {type(e).__name__}: {e}", b""


def get_text(url: str, timeout: int = TIMEOUT) -> str:
    status, ctype, body = http_get(url, timeout)
    if status != 200 or not body:
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", "replace")


def strip_tags(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = (h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    h = re.sub(r"[ \t\u3000]+", " ", h)
    h = re.sub(r"\n{3,}", "\n\n", h)
    return h.strip()


# --------------------------------------------------------------------------
# 源：Project Gutenberg
# --------------------------------------------------------------------------
GUT_SEARCH = "https://www.gutenberg.org/ebooks/search/?query={q}"
BOOKLINK = re.compile(r'<li class="booklink">.*?href="/ebooks/(\d+)".*?'
                      r'<span class="title">(.*?)</span>.*?'
                      r'(?:<span class="subtitle">(.*?)</span>)?', re.S)


def gutenberg_search(title: str, limit: int) -> list[dict]:
    html = get_text(GUT_SEARCH.format(q=urllib.parse.quote(title)))
    if not html:
        return []
    out, seen = [], set()
    for bid, t, a in BOOKLINK.findall(html):
        if bid in seen:
            continue
        seen.add(bid)
        out.append({
            "source": "gutenberg",
            "id": bid,
            "title": strip_tags(t),
            "author": strip_tags(a or ""),
            "lang": "zh" if re.search(r"[\u4e00-\u9fff]", t) else "en",
            "license": "public-domain",
            "formats": ["epub", "txt", "html"],
            "page": f"https://www.gutenberg.org/ebooks/{bid}",
        })
        if len(out) >= limit:
            break
    return out


def gutenberg_meta(bid: str) -> dict:
    """从书籍页 og:title 拿「书名 by 作者」。"""
    html = get_text(f"https://www.gutenberg.org/ebooks/{bid}")
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if not m:
        return {}
    raw = m.group(1)
    if " by " in raw:
        t, a = raw.rsplit(" by ", 1)
        return {"title": t.strip(), "author": a.strip()}
    return {"title": raw.strip()}


def gutenberg_fetch(item: dict, fmt: str) -> tuple[str, bytes]:
    bid = item["id"]
    if fmt == "txt":
        url = f"https://www.gutenberg.org/ebooks/{bid}.txt.utf-8"
    elif fmt == "html":
        url = f"https://www.gutenberg.org/ebooks/{bid}.html.images"
    else:
        url = f"https://www.gutenberg.org/ebooks/{bid}.epub3.images"
    status, ctype, body = http_get(url, timeout=90)
    if status != 200 or not body:
        raise RuntimeError(f"下载失败：HTTP {status} ({url})")
    return url, body


# --------------------------------------------------------------------------
# 源：Standard Ebooks
# --------------------------------------------------------------------------
SE_SEARCH = "https://standardebooks.org/ebooks?query={q}"
SE_LINK = re.compile(r'href="(/ebooks/[a-z0-9-]+/[a-z0-9-]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,90})')


def se_search(title: str, limit: int) -> list[dict]:
    html = get_text(SE_SEARCH.format(q=urllib.parse.quote_plus(title)))
    if not html:
        return []
    out, seen = [], set()
    for path, text in SE_LINK.findall(html):
        if path in seen:
            continue
        seen.add(path)
        t = strip_tags(text).strip() or path.rsplit("/", 1)[-1].replace("-", " ").title()
        out.append({
            "source": "standardebooks",
            "id": path,
            "title": t,
            "author": path.split("/")[-2].replace("-", " ").title(),
            "lang": "en",
            "license": "public-domain",
            "formats": ["epub"],
            "page": "https://standardebooks.org" + path,
        })
        if len(out) >= limit:
            break
    return out


def se_fetch(item: dict, fmt: str) -> tuple[str, bytes]:
    page = item["page"]
    html = get_text(page)
    if not html:
        raise RuntimeError(f"读不到书籍页面：{page}")
    hrefs = re.findall(r'href="([^"]+\.epub)"', html)
    hrefs = [h for h in hrefs if "kepub" not in h and "advanced" not in h]
    if not hrefs:
        raise RuntimeError("页面里没找到 epub 链接（站点结构可能变了）")
    url = urllib.parse.urljoin(page, hrefs[0])
    status, ctype, body = http_get(url, timeout=120)
    # 站点会先回一个「下载已开始」的 HTML 页面，meta refresh 到真正的文件
    if b"<html" in body[:200].lower() or "text/html" in ctype:
        m = re.search(rb'http-equiv="refresh"[^>]*url=([^"\'> ]+)', body)
        if m:
            real = urllib.parse.urljoin(url, m.group(1).decode("utf-8", "replace"))
            status, ctype, body = http_get(real, timeout=120)
    if status != 200 or not body.startswith(b"PK"):
        raise RuntimeError(f"下载失败：HTTP {status} {ctype}，{len(body)}B（可能被站点限流）")
    return url, body


# --------------------------------------------------------------------------
# 源：维基文库（CC BY-SA）
# --------------------------------------------------------------------------
WS_API = "https://zh.wikisource.org/w/api.php"


def ws_search(title: str, limit: int) -> list[dict]:
    q = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": title,
        "srlimit": limit, "format": "json", "srprop": "snippet",
    })
    raw = get_text(f"{WS_API}?{q}")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for hit in data.get("query", {}).get("search", []):
        out.append({
            "source": "wikisource",
            "id": hit["title"],
            "title": hit["title"],
            "author": "",
            "lang": "zh",
            "license": "CC-BY-SA-4.0",
            "formats": ["txt"],
            "page": "https://zh.wikisource.org/wiki/" + urllib.parse.quote(hit["title"].replace(" ", "_")),
        })
    return out


def _ws_html(page: str, base: str = "https://zh.wikisource.org") -> str:
    """用 action=parse 拿干净的正文 HTML（REST 页面会混进模板 JSON）。"""
    q = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "text",
                                "format": "json", "formatversion": "2", "redirects": "1"})
    raw = get_text(f"{base}/w/api.php?{q}")
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if "error" in data:
        return ""
    return data.get("parse", {}).get("text", "")


NOISE = re.compile(r"^[◄►\s|]+$")


def clean_ws(text: str) -> str:
    """去掉维基文库页面里的翻页箭头、姊妹计划、导航残留。"""
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s or NOISE.match(s):
            continue
        if s.startswith("姊妹计划") or s.startswith("◄") or s.startswith("►"):
            continue
        out.append(ln.rstrip())
    return "\n".join(out)


def ws_fetch(item: dict, fmt: str) -> tuple[str, bytes]:
    """取正文；如果拿到的是分卷索引页，顺着子页面把全本拼起来。"""
    base = "https://zh.wikisource.org"
    page = item["id"].replace("_", " ")
    url = f"{base}/wiki/{urllib.parse.quote(page.replace(' ', '_'))}"
    html = _ws_html(page, base)
    if not html:
        raise RuntimeError("维基文库取不到正文（页面不存在，或本机网络不通，见 probe）")
    text = strip_tags(html)
    if len(text) < 50:
        raise RuntimeError("正文过短，可能是消歧义页或空页")

    # 索引页特征：大量以「本书名/」开头的子页面链接，且正文本身不长
    prefix = page + "/"
    subs: list[str] = []
    for href in re.findall(r'href="/wiki/([^"#?]+)"', html):
        s = urllib.parse.unquote(href).replace("_", " ")
        if s.startswith(prefix) and s not in subs:
            subs.append(s)
    pages = int(item.get("max_pages") or 200)
    header = (f"{item['title']}\n来源：维基文库 {url}\n"
              f"许可：署名-相同方式共享 4.0 国际 (CC BY-SA 4.0)\n\n")
    if subs and len(text) < 40000:
        chunks = [header + "【目录】\n" + "\n".join(s[len(prefix):] for s in subs[:pages])]
        ok = 0
        for s in subs[:pages]:
            body = clean_ws(strip_tags(_ws_html(s, base)))
            if not body:
                continue
            ok += 1
            chunks.append(f"\n\n{'=' * 46}\n{s}\n{'=' * 46}\n{body}")
        if not ok:
            raise RuntimeError("子页面全取不到，可能是网络中断")
        return url, "".join(chunks).encode("utf-8")
    return url, (header + clean_ws(text)).encode("utf-8")


# --------------------------------------------------------------------------
# 路由
# --------------------------------------------------------------------------
SOURCES = {
    "gutenberg": (gutenberg_search, gutenberg_fetch, "https://www.gutenberg.org/ebooks/search/?query=x"),
    "standardebooks": (se_search, se_fetch, "https://standardebooks.org/ebooks?query=x"),
    "wikisource": (ws_search, ws_fetch, WS_API),
}

CATEGORY_PLAN = {
    "foreign": ["gutenberg", "standardebooks"],   # 外国文学原著
    "classic": ["gutenberg", "wikisource"],       # 中文名著
    "ancient": ["gutenberg", "wikisource"],       # 古代文献
}


def has_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s))


def plan(category: str, title: str) -> tuple[str, list[str]]:
    if category == "auto":
        category = "classic" if has_cjk(title) else "foreign"
    if category == "modern":
        return category, []
    return category, CATEGORY_PLAN.get(category, CATEGORY_PLAN["foreign"])


# --------------------------------------------------------------------------
# 下载落盘
# --------------------------------------------------------------------------
def safe_name(s: str, maxlen: int = 70) -> str:
    if not s:
        return ""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:maxlen].strip()


def sniff_ext(body: bytes) -> str:
    if body.startswith(b"PK\x03\x04"):
        return "epub"
    if body.startswith(b"%PDF"):
        return "pdf"
    return "txt"


def do_fetch(item: dict, out_dir: Path, fmt: str) -> dict:
    src = item["source"]
    _, fetcher, _ = SOURCES[src]
    url, body = fetcher(item, fmt)
    if not body:
        raise RuntimeError("空文件")
    ext = sniff_ext(body)
    if fmt == "txt" and ext != "txt":
        raise RuntimeError(f"要的是 txt，拿到的是 {ext}（{url}）")
    name = "-".join(x for x in (src, safe_name(item["title"]) or "book",
                                safe_name(item.get("author") or "")) if x)
    path = out_dir / f"{name}.{ext}"
    i = 2
    while path.exists():
        path = out_dir / f"{name}-{i}.{ext}"
        i += 1
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    rec = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": src,
        "id": item["id"],
        "title": item["title"],
        "author": item.get("author", ""),
        "license": item.get("license", ""),
        "page": item.get("page", ""),
        "url": url,
        "file": str(path),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "version": VERSION,
    }
    with open(out_dir / "manifest.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def cmd_probe(args) -> int:
    rows = []
    for name, (_, _, probe_url) in SOURCES.items():
        t0 = time.time()
        status, ctype, body = http_get(probe_url, timeout=12)
        rows.append({"source": name, "status": status, "ms": int((time.time() - t0) * 1000),
                     "ok": status == 200 and bool(body)})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            flag = "✅" if r["ok"] else "❌"
            print(f"{flag} {r['source']:<16} HTTP {r['status']:<4} {r['ms']:>5}ms")
        if not all(r["ok"] for r in rows):
            print("\n打不通的源在本机网络下不可用（不是脚本问题）。search 会自动跳过。")
    return 0 if any(r["ok"] for r in rows) else 1


def cmd_search(args) -> int:
    category, sources = plan(args.cat, args.title)
    if args.sources:
        sources = [s for s in args.sources.split(",") if s in SOURCES]
    if not sources:
        payload = {"query": args.title, "category": category, "results": [],
                   "note": "看来越是当代作品越受版权保护，这里不给你盗版链接。",
                   "legal_channels": LEGAL_CHANNELS}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"《{args.title}》判定为在版作品（category={category}），不提供下载源。")
            print("合法获取渠道：")
            for c in LEGAL_CHANNELS:
                print("  - " + c)
        return 0

    results, errors = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as ex:
        futs = {ex.submit(SOURCES[s][0], args.title, args.limit): s for s in sources}
        for fut in concurrent.futures.as_completed(futs, timeout=90):
            name = futs[fut]
            try:
                results.extend(fut.result())
            except Exception as e:
                errors[name] = f"{type(e).__name__}: {e}"
    raw_n = len(results)
    # 维基文库里全是全文检索的噪声（判决书、讨论页），标题长度远大于书名就判为不相关
    results = [r for r in results
               if r["source"] != "wikisource"
               or len(r["title"]) <= max(8, 3 * len(args.title))]
    dropped = raw_n - len(results)
    results.sort(key=lambda r: (sources.index(r["source"]) if r["source"] in sources else 9))

    if args.json:
        print(json.dumps({"query": args.title, "category": category, "sources": sources,
                          "results": results, "errors": errors, "filtered_out": dropped},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"查询：{args.title}   分类：{category}   源：{', '.join(sources)}")
    if not results:
        print("没有命中。可能的原因和办法：")
        print("  · Gutenberg 的中文书名是繁体，简繁不一致会漏——换繁体书名，或用作者名（如 Xueqin Cao）")
        print("  · 书名属于在版作品（受版权保护），公版库里本来就没有——见下面的合法渠道")
        print("  · 换个写法：书名去掉副标题、只留主名")
        if args.cat in ("auto", "classic", "ancient", "modern"):
            print("\n合法获取渠道：")
            for c in LEGAL_CHANNELS:
                print("  - " + c)
    for r in results:
        print(f"  [{r['source']}:{r['id']}] {r['title']}"
              f"{' — ' + r['author'] if r['author'] else ''}  ({r['license']}, {'/'.join(r['formats'])})")
    if dropped:
        print(f"  （已过滤 {dropped} 条标题明显不相关的结果，多为全文检索噪声）")
    for k, v in errors.items():
        print(f"  ! {k} 出错：{v}")
    if results:
        print("\n下载：python scripts/bookhunt.py fetch <source:id> --out books --format epub")
    return 0


def cmd_fetch(args) -> int:
    if ":" not in args.ref:
        print("ref 格式应为 source:id，例如 gutenberg:24264 或 standardebooks:/ebooks/a/b",
              file=sys.stderr)
        return 2
    src, ident = args.ref.split(":", 1)
    if src not in SOURCES:
        print(f"未知源：{src}（可选：{', '.join(SOURCES)}）", file=sys.stderr)
        return 2
    item = {"source": src, "id": ident, "title": args.title or ident,
            "author": args.author or "", "license": "", "page": "",
            "max_pages": args.max_pages}
    if src == "gutenberg":
        item["page"] = f"https://www.gutenberg.org/ebooks/{ident}"
        item["license"] = "public-domain"
        if not args.title:
            meta = gutenberg_meta(ident)
            if meta:
                item.update({"title": meta.get("title", ident), "author": meta.get("author", "")})
            else:
                item["title"] = ident
    elif src == "standardebooks":
        item["page"] = "https://standardebooks.org" + ident if ident.startswith("/") else ident
        item["license"] = "public-domain"
    elif src == "wikisource":
        item["page"] = "https://zh.wikisource.org/wiki/" + urllib.parse.quote(ident)
        item["license"] = "CC-BY-SA-4.0"

    out = Path(args.out).expanduser()
    if args.dry_run:
        print(json.dumps({**item, "out": str(out), "format": args.format}, ensure_ascii=False, indent=2))
        return 0
    try:
        rec = do_fetch(item, out, args.format)
    except Exception as e:
        print(f"❌ 下载失败：{e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    else:
        print(f"✅ {rec['title']}{' — ' + rec['author'] if rec['author'] else ''}")
        print(f"   文件：{rec['file']}")
        print(f"   大小：{rec['bytes'] / 1024:.1f} KB   sha256：{rec['sha256'][:16]}…")
        print(f"   来源：{rec['url']}")
        print(f"   记录：{Path(args.out) / 'manifest.jsonl'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="bookhunt", description="搜公版书并下载（古籍/名著/外国文学）")
    ap.add_argument("--version", action="version", version=f"book-hunt {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="测试各源连通性")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_probe)

    s = sub.add_parser("search", help="按书名搜索")
    s.add_argument("title")
    s.add_argument("--cat", default="auto",
                   choices=["auto", "foreign", "classic", "ancient", "modern"],
                   help="foreign=外国文学原著 classic=中文名著 ancient=古代文献 modern=在版（不下载）")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--sources", help="逗号分隔，覆盖分类默认路由，如 gutenberg,wikisource")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    f = sub.add_parser("fetch", help="按 source:id 下载")
    f.add_argument("ref", help="例如 gutenberg:24264")
    f.add_argument("--out", default="books")
    f.add_argument("--format", default="epub", choices=["epub", "txt", "html"])
    f.add_argument("--title")
    f.add_argument("--author")
    f.add_argument("--json", action="store_true")
    f.add_argument("--max-pages", type=int, default=200, help="维基文库分卷最多抓多少页")
    f.add_argument("--dry-run", action="store_true")
    f.set_defaults(func=cmd_fetch)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
