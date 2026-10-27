# 变更记录

语义化版本；版本唯一源是根目录 `VERSION`。

## [1.0.1] — 2026-10-27

### 修复

- 维基文库正文清洗补两条：去掉段首的「[编辑]」链接残留，以及文末「Public domainPublic domainfalsefalse」横幅（该页自身署名声明已写在 txt 头部）。
- 实测：《素女經》16.1 KB，至理第一 … 好女第廿二 全篇无残留标记。

## [1.0.0] — 2026-10-27

首个公开版本。

### 新增

- `scripts/bookhunt.py`：单文件 CLI，三个子命令 `probe` / `search` / `fetch`，零第三方依赖。
- 三个公版源：Project Gutenberg（含中文繁体馆藏）、Standard Ebooks（精校 epub）、中文维基文库（CC BY-SA 纯文本）。
- 体裁路由：`foreign` / `classic` / `ancient` / `modern`，默认按书名是否含汉字自动判断。
- 下载校验：按文件头判 epub/pdf/txt；`--format` 与实际类型不符直接失败，不写半截文件。
- 落盘记录：`<out>/manifest.jsonl` 逐本追加来源、许可、字节数、sha256、工具版本。
- Standard Ebooks「下载已开始」中间页自动跟随 `meta refresh`。
- 维基文库分卷索引自动拼接子页面全文（`--max-pages` 限流），并清理翻页箭头、姊妹计划等导航残留。
- 全文检索噪声过滤：按标题长度剔除判决书/讨论页，过滤条数显式打印。
- 白名单域名校验：`ALLOWED_HOSTS` 之外一律拒绝，防止被当成任意 URL 下载器。
- `--cat modern` 只输出合法获取渠道，不提供任何在版书下载源。

### 已知问题

- Gutenberg 中文馆藏书名为繁体，简体查询会漏，未做简繁转换。
- 维基文库输出为纯文本，图片/表格丢失。
- openlibrary.org、archive.org、gutendex.com 在开发网络下不可达，未接入。
