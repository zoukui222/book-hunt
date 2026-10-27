# book-hunt

> 给一个书名，按体裁路由到对应的公版书库，搜出候选版本，下载到本地，并留下可追溯的下载记录。

![version](https://img.shields.io/badge/version-1.0.0-green) ![python](https://img.shields.io/badge/python-3.9%2B-blue) ![deps](https://img.shields.io/badge/dependencies-none-brightgreen) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

---

## 它解决什么

"帮我把《红楼梦》下下来"/"英文版《傲慢与偏见》epub"/"《论语》全文 txt"——这类需求散落在十几个站点，格式不统一，下下来还经常是错页、HTML 假 epub、只有目录没有正文。这个工具把三件事固定下来：

1. **按体裁路由**：中文古籍走一个源，外国文学原文走另一个，在版作品直接劝你去买/借。
2. **选版本**：同一本书 Gutenberg 上可能有 5 个条目（不同扫描/不同版次），Standard Ebooks 只有一个精校版。工具把候选列出来，带许可和格式。
3. **留证据**：每本书落到 `<out>/manifest.jsonl`，记录来源 URL、许可、字节数、sha256、版本号。半年后想核对"这本是哪来的"不用靠记忆。

## 只连公版库，这是设计不是疏漏

| 源 | 覆盖 | 许可 | 格式 |
|---|---|---|---|
| **Project Gutenberg** | 7.5 万+ 本，含大量中文古籍与名著（紅樓夢、三國演義、山海經、三字經…） | 美国公版 | epub / txt / html |
| **Standard Ebooks** | 精校排版的英文公版书 | 公版（CC0 释放） | epub |
| **维基文库（中文）** | 古籍原文、民国前文献 | CC BY-SA 4.0 | 纯文本 |

在版作品（当代小说、1949 年后中文作品、在售译本）**不提供下载**，`--cat modern` 只输出合法渠道（微信读书/豆瓣阅读、图书馆数字借阅、纸书）。这不是"保守"，是这类需求的绝大多数纠纷都出在这里；工具做成能绕过的样子，最后出事的是用它的人。

## 安装

零依赖，Python 3.9+ 即可，不需要 `pip install`。

### 当 Hermes Agent skill

```bash
git clone https://github.com/zoukui222/book-hunt.git \
  "$HERMES_HOME/skills/productivity/book-hunt"
```

目录名必须和 `SKILL.md` 里的 `name:` 一致。装完 `/reload-skills` 或新开会话，然后说"用 book-hunt 下《论语》"。

### 当独立命令行工具

```bash
git clone https://github.com/zoukui222/book-hunt.git
cd book-hunt
python scripts/bookhunt.py probe
```

Windows 上给 Python 传路径用正斜杠（`C:/books`），别用 MSYS 的 `/c/books`。

## 用法

```bash
# 0. 先看本机能不能连上（换网络环境必跑）
python scripts/bookhunt.py probe

# 1. 搜
python scripts/bookhunt.py search "红楼梦" --limit 5
python scripts/bookhunt.py search "pride and prejudice"
python scripts/bookhunt.py search "论语" --cat ancient --json

# 2. 下
python scripts/bookhunt.py fetch gutenberg:1342 --out books --format epub
python scripts/bookhunt.py fetch "standardebooks:/ebooks/jane-austen/pride-and-prejudice" --out books
python scripts/bookhunt.py fetch "wikisource:論語" --out books --format txt --max-pages 200
```

### 分类路由

| `--cat` | 路由 | 适合 |
|---|---|---|
| `auto`（默认） | 含汉字 → classic，否则 foreign | 常见情况 |
| `foreign` | gutenberg → standardebooks | 外国文学原著（英文/法文/德文） |
| `classic` | gutenberg → wikisource | 中文名著（四大名著、聊斋、儒林外史） |
| `ancient` | gutenberg → wikisource | 古代文献（论语、山海经、黄帝内经） |
| `modern` | 无 | 在版作品，只给合法渠道 |

### 输出与落盘

- 文件名：`<source>-<书名>-<作者>.<ext>`，重名自动加 `-2`，字符清理过（Windows 非法字符已剔除）。
- 校验：下载后看文件头，`PK\x03\x04` 判 epub、`%PDF` 判 pdf、否则当文本；`--format txt` 却拿到 epub 会直接报错，不写盘。
- 记录：`<out>/manifest.jsonl`，一行一本：

```json
{"time": "2026-10-27T16:50:12", "source": "gutenberg", "id": "24264", "title": "紅樓夢",
 "author": "Xueqin Cao", "license": "public-domain", "page": "https://www.gutenberg.org/ebooks/24264",
 "url": "https://www.gutenberg.org/ebooks/24264.txt.utf-8", "file": "books/gutenberg-紅樓夢-Xueqin Cao.txt",
 "bytes": 2663455, "sha256": "ff15…", "version": "1.0.0"}
```

## 实测记录（2026-10-27，Windows 11，中国移动家宽）

网络环境说明很重要：这台机器**直连** Gutenberg / Standard Ebooks / 中文维基文库可用；openlibrary.org、archive.org、gutendex.com 不通（所以没接进来）。

| 查询 | 路由 | 命中 | 下载结果 |
|---|---|---|---|
| `pride and prejudice` | foreign | gutenberg:1342 + standardebooks | 24.3 MB epub（含插图版）/ 812 KB 精校 epub |
| `红楼梦` | classic | wikisource:紅樓夢 | 未下载（优先用下面的 Gutenberg 版） |
| `紅樓夢`（繁体） | classic | gutenberg:24264 | 2.6 MB txt |
| `论语` | classic | wikisource:論語 | 164.7 KB txt，23 篇全（序說 + 學而第一 … 堯曰第二十） |
| `三体` | classic | 无 | 命中 3 条判决书噪声被过滤，改给合法渠道 |

`probe` 当时三家均 200（1.3–1.5 s）。

## 已知限制

- **Gutenberg 中文书名是繁体**：搜"红楼梦"在 Gutenberg 侧没结果，要搜"紅樓夢"或用作者名。工具会提示，但不做简繁转换（没有可靠的内置表，宁可不做也不做错）。
- **维基文库有全文检索噪声**：判决书、讨论页会混进结果。工具按标题长度过滤，过滤条数会打印；短书名的古籍仍可能有零星噪声。
- **维基文库只能出 txt**：原文是 wiki 页面，图片、表格会丢；复杂版式的古籍建议找扫描版。
- **ctext.org 没接**：中国哲学书电子化计划明确要求研究用途走订阅，尊重站点规则，不做爬取。
- **网络敏感**：`probe` 全红不是脚本 bug，是到不了那些站点。换网络或加代理（`HTTPS_PROXY` 环境变量会被 urllib 自动采用）。
- **不做格式转换**：epub → txt/mobi 请用 `ffmpeg`/`calibre`，这本工具只管取。

## 许可

[MIT](LICENSE)。下载到的书籍内容版权归属各自来源站点与作者：Gutenberg 内容为美国公版，维基文库为 CC BY-SA 4.0（转载需署名 + 相同方式共享）。工具本身不存储、不分发任何书籍内容。
