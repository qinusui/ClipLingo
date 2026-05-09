# ClipLingo Release Notes

## v1.3.1 (2026-05-09)

**English**

### Bug Fixes

- **AnkiConnect sync card style now takes effect**: switching themes after first sync now updates model templates and CSS correctly
- **AnkiConnect sync blank card front**: sentence cards now display original text by default when screenshot/audio is empty
- **Batch Whisper transcription**: fixed Whisper being called for every file instead of only files without subtitles
- **ZIP download crash**: fixed subprocess encoding failure when install path contains Chinese characters
- **Chinese install path**: fixed TextIOWrapper GC prematurely closing buffer, now uses `reconfigure()` instead
- **Batch sync progress**: batch AnkiConnect sync now shows real-time progress bar with added/skipped/failed counters
- **Double parentheses in filter count**: removed duplicate parentheses and fixed selected count exceeding filtered total
- **Single-file transcription**: now correctly passes source language to Whisper for better accuracy

### UX Improvements

- **Annotating phase preview**: card template preview now visible during AI annotation, users can adjust styles while waiting
- **README notes**: added reminder to use English-only install paths; added language support description

**中文**

### Bug 修复

- **AnkiConnect 同步卡片样式不生效**：首次同步后切换主题现在能正确更新模型模板和 CSS
- **AnkiConnect 同步卡片正面空白**：句型卡在截图/音频为空时自动显示原文
- **批量 Whisper 转录错误**：修复批量处理时对每个文件都调用 Whisper 而非仅对无字幕文件调用
- **下载 ZIP 闪退**：修复安装路径含中文时 subprocess 编码失败
- **中文安装路径**：修复 TextIOWrapper 被 GC 过早关闭 buffer，改用 `reconfigure()` 重配
- **批量同步进度**：批量 AnkiConnect 同步现在显示实时进度条和添加/跳过/失败计数
- **筛选计数双层括号**：修复括号重复和筛选后已选数超过总数的问题
- **单文件转录**：正确传递源语言参数给 Whisper，提升识别准确率

### 用户体验优化

- **注释阶段预览**：AI 注释进行中即可预览卡片模板效果，等待时调整样式无需额外等待
- **README 补充**：添加安装路径使用纯英文的提示和语言对说明

---

## v1.3.0 (2026-05-08)

**English**

### English UI Internationalization

- Full Chinese/English UI switching powered by react-i18next
- Language toggle button in the header, preference persisted to localStorage
- Covers all components: alerts, prompt editors, card templates, batch queue, all four workflow steps

### Batch Processing Queue

- New batch queue supporting multiple videos at once
- Each video gets its own subtitle file; unmatched videos show a "Whisper Transcribe" indicator
- Videos without subtitles automatically trigger Whisper transcription
- Per-row subtitle file picker for flexible assignment

### Multi-Format Export

- **CSV Export**: utf-8-sig encoding, Excel-ready, 5 fields: sentence, translation, notes, word, definition
- **JSON Export**: complete card data with all fields including timestamps
- **ZIP Export**: bundles CSV + audio + screenshots into a single download
- Basic processing now works without an API key (translations and notes are left empty)

### Independent Prompt Customization

- Screening and annotation prompts are now independently editable
- New "Grammar & Sentence Patterns" and "Vocabulary" presets for annotation
- Backend `AIAnnotateRequest` accepts a `custom_prompt` parameter

### AnkiConnect Sync Improvements

- New `/api/anki-connect` proxy endpoint — the frontend no longer contacts AnkiConnect directly, eliminating CORS issues
- Non-breaking space placeholder for empty screenshots prevents Anki from rejecting notes
- Media upload failures no longer block the entire note; a single file failure only skips that item
- Card front fallback: shows original sentence text when Screenshot/Audio/Word fields are empty

### Bug Fixes

- Fixed port 8000 not released after browser close: heartbeat pings every 30s, backend auto-exits after 2 min of silence
- Fixed incorrect apkg download path in packaged builds: now uses `apkg_url` from the backend (includes `task_id` subdirectory)
- Fixed ffmpeg/ffprobe/Whisper spawning terminal windows in packaged builds: added `CREATE_NO_WINDOW` to all subprocess calls
- Fixed card style/theme selector not appearing when no API key is set

**中文**

### English UI 国际化

- 使用 react-i18next 实现完整的中英文界面切换
- 顶部导航栏新增语言切换按钮，偏好持久化到 localStorage
- 覆盖所有组件：提示框、prompt 编辑器、卡片模板、批处理队列、全部四个步骤

### 批量处理队列

- 新增批量处理队列，支持同时导入多个视频
- 每个视频可独立分配字幕文件，未匹配的视频显示「Whisper 转录」标识
- 无字幕的视频自动触发 Whisper 转录
- 每行单独的字幕文件选择器，灵活分配

### 多格式导出

- **CSV 导出**：utf-8-sig 编码，Excel 直接打开无乱码，包含句子/翻译/笔记/单词/释义五个文本字段
- **JSON 导出**：完整卡片数据，包含时间戳等全部字段
- **ZIP 导出**：打包 CSV + 音频 + 截图，一键下载全部素材
- 无需配置 AI API Key 也能完成基础处理（翻译和笔记留空）

### 独立 Prompt 自定义

- 筛选（Screening）和注释（Annotation）两个阶段的 prompt 现在独立可编辑
- 注释阶段新增「语法与句型」「词汇」预设模板
- 后端 `AIAnnotateRequest` 支持 `custom_prompt` 参数

### AnkiConnect 同步优化

- 后端新增 `/api/anki-connect` 代理端点，前端不再直连 AnkiConnect，彻底解决 CORS 跨域问题
- 截图为空时使用非断行空格占位，防止 Anki 拒绝添加笔记
- 媒体文件上传失败不影响整张卡片写入，单文件失败仅跳过该媒体
- 卡片正面空白回退：当截图/音频/单词字段为空时自动显示原文句子

### Bug 修复

- 修复关闭浏览器后端口 8000 仍被占用的问题：新增心跳机制，前端每 30 秒 ping 后端，2 分钟无心跳自动退出
- 修复打包版 apkg 下载路径错误：使用后端返回的 `apkg_url`（含 task_id 子目录）
- 修复打包版运行时 ffmpeg/ffprobe/Whisper 弹出命令行窗口：为所有 subprocess 调用添加 `CREATE_NO_WINDOW` 标志
- 修复未设置 API Key 时不显示卡片样式/主题选择器的问题

---

## v1.2.2 (2026-05-07)

**English**

### Update Check

- Auto-checks GitHub for the latest version on startup
- Shows an update banner at the top of the UI when a new version is found
- Supports manual update check

### Transcription Progress

- Real-time Whisper transcription progress display
- Transcription progress is included in the overall processing progress

### AnkiConnect Sync

- Send cards directly to Anki via AnkiConnect
- No need to manually import .apkg files
- Auto-detects AnkiConnect connection status

### Learned Words Sync

- Sync learned words from Anki back to ClipLingo
- Auto-skip already-learned words to avoid duplicates

**中文**

### 更新检查

- 启动时自动检查 GitHub 最新版本
- 发现新版本时在界面顶部显示更新提示
- 支持手动检查更新

### 转录进度

- Whisper 转录过程显示实时进度
- 转录进度包含在整体处理进度中

### AnkiConnect 同步

- 支持通过 AnkiConnect 直接将卡片发送到 Anki
- 无需手动导入 .apkg 文件
- 自动检测 AnkiConnect 连接状态

### 已学词汇同步

- 支持从 Anki 同步已学词汇到 ClipLingo
- 自动跳过已学过的单词，避免重复学习

---

## v1.2.1 (2026-05-06)

**English**

### Two-Phase AI Workflow

- AI recommendation split into **Screening** and **Annotation** phases
- Screening: quickly assesses each subtitle's learning value, returns `include`/`skip` with reasons
- Annotation: generates translations and grammar/vocab notes based on learning purpose
- Both phase prompts are independently customizable

### 4 Card Themes

- **Classic**: traditional Anki card style with complete information
- **Minimal Immersive**: clean design with minimal visual distraction
- **Netflix Stills**: Netflix screenshot-inspired style
- **Dictionary**: dictionary-style layout, ideal for vocab cards
- Each theme has unique CSS + HTML templates, with live preview before generation

### UX Flow Overhaul

- Step 1: bottom confirmation bar shows readiness status
- Step 2: rule filtering placed above the AI screening button for better workflow
- Step 3 split into sub-stages: 3a choose purpose → 3b wait for annotation & configure style → 3c done
- Original Steps 4+5 merged into new Step 4: preview + generate + download in one place
- Card theme/structure selection moved to the annotation waiting period to reduce idle time

### Whisper Transcription Enhancements

- New 30-minute watchdog timeout — auto-terminates subprocess on timeout
- New `POST /transcribe/cancel/{task_id}` endpoint for manual cancellation
- Subprocess resources cleaned up in `finally` block

### Checkpoint Fixes

- Checkpoint now saves all output-affecting params (model name, API base, language, card styles, theme)
- All params compared on resume; any change invalidates the checkpoint
- Fixed missing `theme` parameter during checkpoint restore

### License Change

- License changed from GNU GPL v3.0 to MIT License

**中文**

### 两阶段 AI 工作流

- AI 推荐拆分为**筛选（Screening）**和**注释（Annotation）**两个独立阶段
- 筛选阶段：快速评估每条字幕的学习价值，返回 `include`/`skip` 判断及理由
- 注释阶段：根据学习目的生成翻译和语法/词汇笔记
- 两个阶段的 prompt 均可独立自定义

### 4 种卡片主题

- **经典（Classic）**：传统 Anki 卡片风格，信息完整
- **极简沉浸（Minimal Immersive）**：简洁设计，减少视觉干扰
- **Netflix 剧照（Netflix Stills）**：模仿 Netflix 截图风格
- **词典（Dictionary）**：词典式排版，适合词汇卡
- 每种主题拥有独立的 CSS + HTML 模板，生成前可实时预览

### 界面流程重构

- 步骤 1：底部确认栏显示就绪状态
- 步骤 2：规则筛选置于 AI 筛选按钮上方，操作更直观
- 步骤 3 拆分为子阶段：3a 选择目的 → 3b 等待注释并配置样式 → 3c 完成
- 原步骤 4+5 合并为新步骤 4：预览 + 生成 + 下载一体化
- 卡片主题/结构选择移至注释等待阶段，减少空等时间

### Whisper 转录增强

- 新增 30 分钟看门狗超时保护，超时自动终止子进程
- 新增 `POST /transcribe/cancel/{task_id}` 端点支持用户手动取消
- 子进程资源在 `finally` 块中确保清理

### 检查点修复

- 检查点现在保存所有影响输出的参数（模型名、API 地址、语言、卡片样式、主题）
- 恢复时逐参数对比，任一变更则检查点失效
- 修复检查点恢复时缺少 theme 参数的问题

### 许可证变更

- 许可证从 GNU GPL v3.0 更换为 MIT License

---

## v1.1.0 (2026-05-05)

**English**

### Built-in Whisper — Out of the Box

- Whisper transcription engine (faster-whisper) now built into the main app — no separate plugin needed
- Removed `ClipLingo_Whisper_Setup.exe`; installers merged from two into one
- Installer ~170MB (compressed), ~670MB after installation

### AI Recommendation Performance

- Fully async concurrent processing: AsyncOpenAI + asyncio.Semaphore for concurrency control
- Dynamic batching: auto-batch by character count (max_chars=1500) to avoid oversized batches timing out
- Results returned in completion order: faster batches shown first, no more waiting for slow ones
- Timeout extended to 90s, with support for aborting in-progress recommendations
- Estimated 2–2.5× speed improvement

### Learning Progress Tracking

- Local SQLite database records learned words (`~/.cliplingo/progress.db`)
- Auto-marks words as learned after generating Anki cards
- AI recommendation auto-skips learned words to avoid duplicates
- "Learned" badge displayed in the subtitle table

### Subtitle Rule Filtering

- New client-side real-time filter supporting:
  - Duration range filtering (min/max)
  - Learned word exclusion
  - Keyword blacklist
- No more manual per-row checkboxes — much better experience for long videos

### Card Styles

- Multiple card style options (sentence cards + vocab cards)
- Card preview uses built-in Anki CSS for WYSIWYG
- Single-card flip effect, no more extra pages generated

### Other Improvements

- Replaced heartbeat polling with sendBeacon shutdown signal for better reliability
- sendBeacon ignored in dev mode to prevent HMR from triggering shutdown
- Removed redundant "Min Duration" input and "Batch Size" custom option
- Source and target language configurable (EN→ZH, JA→ZH, etc.)

**中文**

### Whisper 内置 — 开箱即用

- Whisper 转录引擎（faster-whisper）已内置到主程序，无需再单独安装插件
- 移除 `ClipLingo_Whisper_Setup.exe`，安装包从两个合并为一个
- 安装包体积 ~170MB（压缩后），安装后 ~670MB

### AI 推荐性能优化

- 全异步并发处理：使用 AsyncOpenAI + asyncio.Semaphore 控制并发
- 动态分批：按字符数自动分批（max_chars=1500），避免单批过大超时
- 按完成顺序返回：先完成的批次先显示，不再等待慢批次
- 超时延长至 90 秒，支持中止正在进行的推荐
- 预计速度提升 2-2.5 倍

### 学习进度追踪

- 本地 SQLite 数据库记录已学单词（`~/.cliplingo/progress.db`）
- 生成 Anki 卡片后自动标记已学单词
- AI 推荐时自动跳过已学单词，避免重复学习
- 字幕表格中显示「已学」标签

### 字幕规则筛选

- 新增客户端实时筛选器，支持：
  - 时长范围过滤（最短/最长）
  - 排除已学单词
  - 关键词黑名单
- 无需手动逐条勾选，大幅改善长视频体验

### 卡片样式

- 支持多卡片样式选择（句卡 + 词卡）
- 卡片预览内置 Anki CSS 样式，所见即所得
- 单卡翻转效果，不再生成多余页面

### 其他改进

- 替换心跳轮询为 sendBeacon 关机信号，更可靠
- 开发模式下忽略 sendBeacon，避免 HMR 误触发关机
- 移除冗余的「最短时长」输入框和「每批数量」自定义选项
- 支持配置源语言和目标语言（英→中、日→中等）
