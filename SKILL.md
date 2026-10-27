---
name: book-hunt
description: 按书名搜公版书并下载（古籍/名著/外国文学）。
version: 1.0.0
author: 刘政涛, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [books, public-domain, gutenberg, wikisource, 古籍, 名著]
    related_skills: [blocked-page-recovery]
---

# book-hunt · 搜书与下载

用户给一个书名（小说、古籍、名著、外国文学），先在公版书库里搜，能确定来源再下载到本地，写一份可追溯的 manifest（来源 URL、许可、字节数、sha256）。

**只连公版/开放许可站点**：Project Gutenberg、Standard Ebooks、维基文库。在版书（受版权保护）不找、不抓、不给盗版镜像链接，只给合法获取渠道。用户说"随便哪个站，能下就行"也不改这条——这不是技术问题。

## When to Use

- "帮我找《红楼梦》"/"下载英文版傲慢与偏见"/"《论语》全文 txt"
- 要给离线阅读器、语料库、做文本分析准备素材
- 需要确认某个公版书到底在哪个库、什么格式、什么许可

Don't use for：

- 在版畅销书/网文/教材的免费下载 → 直接给合法渠道（脚本里 `--cat modern` 就是干这个的）
- 想要全文检索/在线读 → 用 `web_extract` 或浏览器
- 需要扫描版古籍图片（国图中华古籍资源库那类）→ 本工具只处理文本/电子书文件

## 源与分类路由

| 分类 | 路由 | 内容 |
|---|---|---|
| `foreign` 外国文学原著 | gutenberg → standardebooks | 英/法/德等原文，公版，epub/txt |
| `classic` 中文名著 | gutenberg → wikisource | 四大名著等，Gutenberg 是繁体、epub/txt；维基文库是 CC BY-SA 纯文本 |
| `ancient` 古代文献 | gutenberg → wikisource | 论语/山海经/三字经这类，同上 |
| `modern` 在版作品 | 无源 | 只返回合法渠道清单 |

`--cat auto`（默认）：书名含汉字走 `classic`，否则 `foreign`。判断错了就显式传 `--cat`。

## Command Reference

```bash
cd "$HERMES_HOME/skills/productivity/book-hunt"
python scripts/bookhunt.py probe                                   # 各源连通性（先跑这个）
python scripts/bookhunt.py search "红楼梦" --limit 5                # 搜索
python scripts/bookhunt.py search "pride and prejudice" --json      # 机器可读
python scripts/bookhunt.py fetch gutenberg:1342 --out books --format epub
python scripts/bookhunt.py fetch "standardebooks:/ebooks/jane-austen/pride-and-prejudice" --out books
python scripts/bookhunt.py fetch "wikisource:論語" --out books --format txt --max-pages 200
```

`fetch` 落盘规则：`<source>-<书名>-<作者>.<ext>`，同重名自动加 `-2`；每下一本往 `<out>/manifest.jsonl` 追加一条记录（含 sha256）。下载完会校验文件头（`PK` = epub／`%PDF`／文本），对不上直接判失败，不留半截文件。

## 执行流程

1. **先 probe**：`probe` 打印三个源的 HTTP 状态。判据：至少一个 ✅。全 ❌ 说明本机网络到不了这些站点，别硬试。
2. **再 search**：拿到 `source:id`。判据：结果里至少一条标题与用户要的书一致（不是判决书、不是讨论页）。
3. **确认版本**：同一本书常有多个条目（不同译者/不同扫描质量）。优先 Gutenberg 的 epub3，其次 Standard Ebooks（精校），古籍纯文本用维基文库。判据：能说出选它的理由（版本/格式/大小）。
4. **fetch**：判据：打印 `✅ 书名` + 文件路径 + 大小，且 `manifest.jsonl` 新增一行。
5. **交付**：给 `MEDIA:<绝对路径>`，并说明来源站、许可、字节数。中文古籍提醒"维基文库是 CC BY-SA，转载要署名"。

## Pitfalls

- **Gutenberg 的中文书名是繁体**：搜"红楼梦"在 Gutenberg 侧颗粒无收，搜"紅樓夢"或作者名 `Xueqin Cao` 才有。脚本会给这条提示。
- **Gutenberg 拒绝爬架式 UA**：`/ebooks/search.opds` 直接 403，本工具走 `/ebooks/search/?query=` HTML 页 + `/ebooks/{id}.epub3.images` 直链，别改成 OPDS。
- **Standard Ebooks 的"下载已开始"页**：直链第一次会回一个 HTML 感谢页，靠 `<meta http-equiv="refresh">` 跳真正的文件。脚本已处理；自己写 curl 时容易误把 8 KB 的 HTML 当 epub 存下来。
- **维基文库页面是分卷索引**：《论语》《三国演义》主页面只有目录，正文在 `书名/篇名` 子页面里。脚本会顺子页面拼全文，`--max-pages` 控制上限（默认 200）。
- **维基文库 REST 接口脏**：`/api/rest_v1/page/html` 会把模板 JSON 塞进正文，必须用 `action=parse&prop=text`，再用 `clean_ws` 清掉翻页箭头。
- **全文检索噪声**：维基文库会返回一堆判决书、讨论页。脚本按标题长度过滤（`max(8, 3×查询长度)`），过滤条数会打印出来。
- **ctext.org 不要爬**：中国哲学书电子化计划明确要求研究用途走订阅，别把它加进源列表。
- **openlibrary / archive.org 本机直连不通**：所以没接进来。要接就从 `SOURCES` 加，`ALLOWED_HOSTS` 同步加域名，否则会被白名单拦住。

## Verification

```bash
python scripts/bookhunt.py probe
python scripts/bookhunt.py search "论语" --limit 3
python scripts/bookhunt.py fetch "wikisource:論語" --out /tmp/bt --format txt --max-pages 25
python -c "import pathlib,glob;[print(f, pathlib.Path(f).stat().st_size) for f in glob.glob('/tmp/bt/*.txt')]"
tail -1 /tmp/bt/manifest.jsonl
```

判据：`probe` 至少一个源 200；`search` 有命中且标题对得上；`fetch` 打印 ✅ 且文件大小 > 100 KB（古籍全文）/ > 300 KB（长篇小说 epub）；manifest 里 `sha256` 与 `bytes` 齐备。

## 合法性边界

- 这三家都是公版或开放许可：Gutenberg（美国公版）、Standard Ebooks（公版精校）、维基文库（CC BY-SA 4.0）。
- 中文维基文库内容转载需署名并以相同方式共享；脚本写进 txt 头的就是这条声明，别删。
- 在版作品（1949 年后仍在版权期的中文作品、当代外国文学译本）不在能力范围内，`--cat modern` 只会给合法渠道。
