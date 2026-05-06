<p align="center">
  <img src="docs/logo.svg" width="120" />
</p>

<h1 align="center">ClipLingo</h1>

将视频 + 字幕文件自动转换为可导入 Anki 的牌组。

**定位：通过视频字幕学习外语的工具** — 支持任意语言对，无需 AI 即可使用基础功能，配置 AI 后可智能筛选有学习价值的句子。

## 为什么选择 ClipLingo

|           | ClipLingo                                         | subs2srs           | LanguageReactor |
| --------- | ------------------------------------------------- | ------------------ | --------------- |
| **运行方式**  | 本地运行，数据不离开你的电脑                                    | 本地运行，但依赖 Anki 插件生态 | 浏览器插件，在线服务      |
| **隐私**    | 所有文件和 API Key 仅在本地处理                              | 本地                 | 视频观看数据上传至服务器    |
| **AI 功能** | 可选，支持任意 OpenAI 兼容接口（DeepSeek / OpenAI / Ollama 等） | 无内置 AI             | 内置，但绑定其在线服务     |
| **语言对**   | 任意语言对，自由切换                                        | 英语为主               | 英语为主            |
| **上手难度**  | 下载即用，图形界面                                         | 需要熟悉 Anki + 命令行工具  | 浏览器插件，简单        |
| **输出格式**  | 直接生成 .apkg，导入 Anki 即可                             | 需要配合 Anki 导入       | 仅支持在线复习         |
| **字幕来源**  | 外挂 SRT + 内嵌软字幕 + Whisper 转录                       | 外挂 ASS/SRT         | 仅在线视频字幕         |

简而言之：**subs2srs 功能强大但上手门槛高，LanguageReactor 方便但数据不在自己手里。ClipLingo 兼顾易用性和隐私，AI 功能完全可选。**

## 下载与安装

**安装版（推荐）：**

- `ClipLingo_Setup.exe` — 主程序安装包，内置 Whisper 转录（~700MB）

安装后启动 `ClipLingo.exe`，浏览器访问 `http://localhost:8000`。

**免安装版：**

- `ClipLingo_portable.zip` — 解压即用（~700MB）

运行 `ClipLingo.exe`，浏览器访问 `http://localhost:8000`。

**Docker：**

```bash
git clone https://github.com/qinusui/ClipLingo.git
cd ClipLingo
docker-compose up -d
# 浏览器访问 http://localhost:8000
```

> 需要先安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)

**开发环境：**

```bash
pip install -r requirements.txt && cd backend && pip install -r requirements.txt && cd ../frontend && npm install && cd ..
scripts\start.bat  # Windows
# 或
./scripts/start.sh  # Linux/Mac
```

需要 Python 3.10+、ffmpeg（PATH 中）、Node.js 18+。

## 核心功能

- **Whisper 转录**：内置 faster-whisper，支持视频直接转录为字幕（英/日/韩等多语言）
- **AI 智能筛选**：自动评估每条字幕的学习价值，推荐值得记忆的句子
- **学习进度追踪**：本地 SQLite 记录已学单词，重复运行时自动跳过
- **规则筛选**：时长范围、已学排除、关键词黑名单，快速过滤大量字幕
- **多样式卡片**：句卡（原文+翻译）和词卡（单词+释义），预览即所得
- **内嵌字幕提取**：自动检测视频内嵌软字幕，无需手动准备 SRT 文件

## 配置

### AI 配置（可选）

如需使用 AI 翻译和智能筛选功能，在界面右侧「AI 配置」栏填写：

- **源语言 / 目标语言**：选择字幕语言和翻译目标语言，支持中、英、日、韩、法、德、西等 19 种语言
- **API 地址**：支持 OpenAI 兼容接口（DeepSeek / OpenAI / Ollama 等）
- **模型名称**：自定义模型
- **API Key**：自动持久化到 localStorage
- **测试连接** / **获取模型列表**：一键验证配置

> **隐私安全**：API Key 仅存储在浏览器本地（localStorage），不会上传到任何服务器，仅在本机与 localhost 后端通信时使用。电脑共用时注意清理浏览器数据。

### 字幕处理配置

左侧「字幕处理配置」栏可调整：

- **最短时长**：过滤过短的字幕（默认 1.0 秒）
- **开头提前**：音频切割时的头部 padding（默认 200ms）
- **结尾延后**：音频切割时的尾部 padding（默认 200ms）

## 使用流程

界面采用三步纵向布局：

1. **准备素材**：上传视频和字幕文件（或自动生成字幕），调整处理配置
2. **筛选内容**：手动勾选字幕，或使用「AI 推荐」智能筛选（需配置 AI）
3. **生成卡片**：点击「开始处理」生成并下载 Anki 牌组

**两种使用模式：**

- **基础模式**（无需 AI）：上传视频 → 自动提取/转录字幕 → 规则筛选或手动勾选 → 生成卡片
- **AI 模式**（可选）：配置 AI → 一键「AI 推荐」智能筛选 → 生成卡片（额外包含翻译和注释）

> 已学单词会自动记录，下次运行时 AI 推荐和规则筛选会自动跳过。

## 卡片格式

**基础模式（无 AI）：**

- **正面**：截图 + 音频（考察听力）
- **背面**：原文

**AI 模式（可选）：**

- **正面**：截图 + 音频（考察听力）
- **背面**：原文 + 翻译 + 词汇注释

## 卡片示例

![卡片格式示例](docs/example.png)


## License

This project is licensed under the MIT License.  
See the [LICENSE](LICENSE) file for details.
