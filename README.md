# Get Note Sync

`Get Note Sync` 是一个重新实现的 Obsidian 插件，用 Get OpenAPI 直接把 Get 笔记同步到本地 vault。

它参考了 [geekhuashan/get-to-obsidian](https://github.com/geekhuashan/get-to-obsidian) 的使用目标，但实现路线改成了直接调用 API，而不是依赖浏览器导出 ZIP。这样同步链路更短，也更容易维护。

## 功能

- 直接使用 `GETNOTE_API_KEY` 和 `GETNOTE_CLIENT_ID` 拉取 Get 笔记
- 增量同步到 Obsidian，本地会记录每条笔记的签名和文件路径
- 自动按日期落盘到 `Get/Notes/YYYY-MM-DD/`
- 可选下载附件到 `Get/Attachments/<note-id>/`
- 支持同步引用内容、原文内容和子笔记
- 可选生成时间线总览笔记
- 可选生成 Obsidian Canvas 文件
- 支持启动自动同步和按小时自动同步

## 目录结构

默认情况下，插件会在 vault 中生成：

```text
Get/
├─ Notes/
│  └─ 2026-04-02/
│     └─ 笔记标题--1905282266709003896.md
├─ Attachments/
│  └─ 1905282266709003896/
│     └─ image.png
├─ Get Timeline.md
└─ Get Notes.canvas
```

## 使用

### 1. 安装依赖

```bash
npm install
```

### 2. 构建插件

```bash
npm run build
```

构建结果会生成在仓库根目录：

- `main.js`
- `manifest.json`
- `styles.css`

### 3. 放到 Obsidian 插件目录

将这三个文件复制到你的 vault：

```text
.obsidian/plugins/get-note-sync/
```

然后在 Obsidian 里启用 `Get Note Sync`。

### 4. 配置 Get OpenAPI

进入 Obsidian 的插件设置页，填入：

- `Get API Key`
- `Get Client ID`

然后根据需要调整落盘目录、自动同步、附件下载和生成文件选项。

## 开发

```bash
npm install
npm run dev
```

## GitHub Actions

仓库内置了一个构建工作流：

- `push main`
- `pull_request`
- `workflow_dispatch`

CI 会执行 `npm ci` 和 `npm run build`，并把 `main.js`、`manifest.json`、`styles.css` 作为构建产物上传。
