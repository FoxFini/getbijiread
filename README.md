# Get 笔记同步到 Notion

这个脚本会做三件事：

1. 从 Get 笔记 API 分页拉取全部笔记
2. 自动检查并补齐 Notion 数据库需要的字段
3. 以 `Get ID` 为唯一键，把笔记内容同步到 Notion 数据库中
4. 把元信息写入单独的 `元信息` 文本字段
5. 清洗正文格式，只保留更干净的 Markdown 文章结构
6. 会按 `Get ID` 去重，同一个笔记只保留一条激活记录
7. 会读取笔记详情，把原始链接和追加笔记一起同步
8. 页面正文顺序为：`追加笔记` -> `笔记`，`原文` 会作为子页面单独创建
9. `笔记链接` 只写入数据库字段，不再重复写进正文
10. 已附带 GitHub Actions 定时去重同步配置

## 准备环境

建议使用 Python 3.10+，脚本只用标准库，不需要额外安装依赖。

把下面 4 个环境变量填好：

```powershell
$env:GETNOTE_API_KEY="你的 Get API Key"
$env:GETNOTE_CLIENT_ID="你的 Get Client ID"
$env:NOTION_TOKEN="你的 Notion integration token"
$env:NOTION_DATABASE_ID="你的 Notion 数据库 URL 或 ID"
```

## 运行

```powershell
python .\sync_get_to_notion.py
```

只同步最新一条做测试：

```powershell
$env:SYNC_LATEST_ONLY="1"
python .\sync_get_to_notion.py
```

只同步指定笔记：

```powershell
$env:SYNC_NOTE_ID="1905282266709003896"
python .\sync_get_to_notion.py
```

同步指定数量：

```powershell
$env:SYNC_LIMIT="5"
python .\sync_get_to_notion.py
```

## GitHub 定时同步

仓库里已经带了 [sync.yml](F:\Codex Projects\Study Project\Getbijitongbu\.github\workflows\sync.yml)，会在北京时间每天 `08:00` 和 `16:00` 各跑一次，也支持手动触发。

你把项目推到 GitHub 后，在仓库 `Settings -> Secrets and variables -> Actions` 里添加这 4 个 Secrets：

- `GETNOTE_API_KEY`
- `GETNOTE_CLIENT_ID`
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

## 脚本会自动创建的 Notion 字段

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

数据库里原本的标题字段可以保留你现在的 `名称`。
