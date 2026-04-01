# Get 笔记同步到 Notion

这个项目会把 Get 笔记同步到 Notion 数据库，并自动做去重。

当前同步逻辑包括：
- 从 Get API 拉取笔记列表和笔记详情
- 自动补齐 Notion 数据库所需字段
- 按 `Get ID` 去重，同一条笔记只保留一条激活记录
- 同步笔记链接到独立字段 `笔记链接`
- 把追加笔记放进正文的折叠块
- 把原文单独创建成主页面顶部的子页面 `原文`
- 支持 GitHub Actions 每 4 小时定时去重同步

## Notion 字段

脚本会自动检查并创建这些字段：

- `Get ID`
- `元信息`
- `笔记链接`
- `笔记类型`
- `来源`
- `标签`
- `主题`
- `创建时间`
- `更新时间`
- `是否子笔记`
- `子笔记数`
- `同步时间`

数据库原本的标题字段可以继续用你的 `名称`。

## 本地同步

### 1. 准备

建议使用 Python 3.10+。脚本只使用标准库，不需要安装第三方依赖。

需要这 4 个环境变量：

```powershell
$env:GETNOTE_API_KEY="你的 Get API Key"
$env:GETNOTE_CLIENT_ID="你的 Get Client ID"
$env:NOTION_TOKEN="你的 Notion integration token"
$env:NOTION_DATABASE_ID="你的 Notion 数据库 URL 或 ID"
```

也可以参考 [.env.example](F:\Codex Projects\Study Project\Getbijitongbu\.env.example) 自己保存一份本地配置。

### 2. 运行全量同步

```powershell
python .\sync_get_to_notion.py
```

### 3. 测试模式

只同步最新一条：

```powershell
$env:SYNC_LATEST_ONLY="1"
python .\sync_get_to_notion.py
```

只同步指定笔记：

```powershell
$env:SYNC_NOTE_ID="1905282266709003896"
python .\sync_get_to_notion.py
```

只同步指定数量：

```powershell
$env:SYNC_LIMIT="5"
python .\sync_get_to_notion.py
```

### 3.1 时间与重试参数（可选）

```powershell
# 内容不变时是否也刷新“同步时间”（默认 1）
$env:TOUCH_SYNC_TIME_ON_SKIP="1"

# 笔记详情接口超时/重试（默认 20 秒、3 次）
$env:GET_DETAIL_TIMEOUT_SECONDS="20"
$env:GET_DETAIL_MAX_RETRIES="3"

# 全局接口超时/重试（默认 60 秒、8 次）
$env:HTTP_TIMEOUT_SECONDS="60"
$env:HTTP_MAX_RETRIES="8"
```

### 4. 同步后的页面结构

主页面内容顺序是：
- `原文` 子页面
- `追加笔记`
- `笔记`
- `引用内容`（如果有）

其中：
- `原文` 不放在正文里，而是作为单独子页面创建
- 页面标题直接使用 Notion 数据库这一行的标题，不再在正文里重复输出一个主标题
- `笔记链接` 不放在正文里，只保留在数据库字段
- `追加笔记` 会以折叠块形式展示

## GitHub 同步

### 1. 仓库内容

这个项目已经包含 GitHub Actions 工作流：

- [sync.yml](F:\Codex Projects\Study Project\Getbijitongbu\.github\workflows\sync.yml)

建议先手动运行第一次，之后 GitHub Actions 会按每 4 小时一次自动执行去重同步。

当前对应北京时间的触发时间是：
- `00:00`
- `04:00`
- `08:00`
- `12:00`
- `16:00`
- `20:00`

也支持在 GitHub Actions 页面手动触发。

注意：GitHub 的 `schedule` 只能按固定 cron 时间触发，不能做到“严格从第一次运行开始每隔 4 小时”。
当前实现是先支持手动运行第一次，之后再按固定 4 小时周期触发。
另外 GitHub 的 `schedule` 用 UTC 解释，并且会有队列延迟，实际触发时间可能晚几分钟到十几分钟。

### 2. GitHub 仓库需要配置的 Secrets

在仓库中进入：
`Settings -> Secrets and variables -> Actions`

添加这 4 个 repository secrets：

- `GETNOTE_API_KEY`
- `GETNOTE_CLIENT_ID`
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

### 3. 首次检查

Secrets 配好后，可以去：
`Actions -> Sync Get Notes To Notion -> Run workflow`

手动先跑一次，确认：
- 能正常访问 Get API
- 能正常访问 Notion 数据库
- 页面去重和内容结构符合预期

## 主要文件

- [sync_get_to_notion.py](F:\Codex Projects\Study Project\Getbijitongbu\sync_get_to_notion.py)：主同步脚本
- [README.md](F:\Codex Projects\Study Project\Getbijitongbu\README.md)：使用说明
- [.env.example](F:\Codex Projects\Study Project\Getbijitongbu\.env.example)：环境变量示例
- [sync.yml](F:\Codex Projects\Study Project\Getbijitongbu\.github\workflows\sync.yml)：GitHub 定时同步工作流
