# ClipLingo 自定义卡片模板指南

> 适用对象：熟悉 HTML/CSS 的 Anki 深度用户

---

## 概览

ClipLingo 支持通过导入 ZIP 模板包来完全自定义卡片的外观和结构。你可以控制正面/背面的 HTML 布局、字体、颜色、动画效果——任何 CSS 能做到的事情都可以实现。

制作好的模板可以分享给他人，也可以提交到 [ClipLingo 模板社区](https://github.com/qinusui/cliplingo-templates) 供所有用户使用。

---

## 文件结构

一个合法的模板包是一个 `.zip` 文件，内部结构如下：

```
mytheme.zip
├── theme.json     必须 · 模板元数据
├── front.html     必须 · 卡片正面
├── back.html      必须 · 卡片背面
└── style.css      必须 · 样式
```

四个文件缺一不可，文件名大小写敏感。

---

## 字段参考

在 `front.html` 和 `back.html` 中使用 `{{字段名}}` 引用数据：

| 字段名               | 内容            | 示例值                              |
| ----------------- | ------------- | -------------------------------- |
| `{{sentence}}`    | 原文句子          | `Well, the point is...`          |
| `{{translation}}` | 翻译            | `重点是...`                         |
| `{{annotation}}`  | 语法/词汇注释（HTML） | `<b>the point</b> 名词短语...`       |
| `{{audio}}`       | 音频播放器         | `[sound:cliplingo_0001.mp3]`     |
| `{{screenshot}}`  | 截图图片          | `<img src="cliplingo_0001.jpg">` |
| `{{index}}`       | 字幕序号          | `1`                              |

**特殊字段：**

- `{{audio}}` 使用 Anki 的 `[sound:文件名]` 语法，Anki 会自动渲染为播放器
- `{{screenshot}}` 已经是完整的 `<img>` 标签，直接放进 HTML 即可
- `{{annotation}}` 内容可能包含 HTML 标签，不要用 `<pre>` 包裹它

在 `back.html` 中可以使用 `{{FrontSide}}` 来嵌入正面的完整内容：

```html
{{FrontSide}}
<hr>
<div class="translation">{{translation}}</div>
```

---

## 各文件详解

### theme.json

```json
{
  "name": "我的主题",
  "version": 1,
  "author": "你的名字",
  "description": "一句话描述这个主题的风格"
}
```

| 字段            | 是否必须 | 说明                    |
| ------------- | ---- | --------------------- |
| `name`        | 必须   | 主题名称，在应用内显示，不能与已有主题重名 |
| `version`     | 必须   | 填 `1` 即可              |
| `author`      | 可选   | 分享给他人时显示              |
| `description` | 可选   | 在模板市场中显示              |

---

### front.html

卡片正面，通常只显示句子和截图，不透露答案：

```html
<div class="card front">
  <div class="screenshot">
    {{screenshot}}
  </div>
  <div class="audio">
    {{audio}}
  </div>
  <div class="sentence">
    {{sentence}}
  </div>
</div>
```

---

### back.html

卡片背面，显示完整信息：

```html
{{FrontSide}}
<hr class="divider">
<div class="card back">
  <div class="translation">
    {{translation}}
  </div>
  <div class="annotation">
    {{annotation}}
  </div>
</div>
```

---

### style.css

样式文件对正面和背面都生效。Anki 会把正面和背面的 CSS 合并到同一个文档中，所以类名不要冲突。

```css
/* 基础卡片样式 */
.card {
  font-family: "Noto Serif SC", serif;
  background-color: #1a1a2e;
  color: #eaeaea;
  padding: 24px;
  border-radius: 12px;
  max-width: 600px;
  margin: 0 auto;
}

/* 截图 */
.screenshot img {
  width: 100%;
  border-radius: 8px;
  margin-bottom: 16px;
}

/* 例句 */
.sentence {
  font-size: 1.4em;
  line-height: 1.6;
  margin: 16px 0;
  text-align: center;
}

/* 分隔线 */
.divider {
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.15);
  margin: 20px 0;
}

/* 翻译 */
.translation {
  font-size: 1.1em;
  color: #a0a0b0;
  text-align: center;
  margin-bottom: 12px;
}

/* 注释 */
.annotation {
  font-size: 0.9em;
  color: #6c6c8a;
  line-height: 1.8;
}
```

---

## 完整示例：极简暗色主题

以下是一个完整可用的模板，可以直接复制修改。

**theme.json**

```json
{
  "name": "极简暗色",
  "version": 1,
  "author": "ClipLingo",
  "description": "深色背景，简洁排版，适合夜间学习"
}
```

**front.html**

```html
<div class="card front">
  <div class="shot">{{screenshot}}</div>
  <div class="aud">{{audio}}</div>
  <div class="sent">{{sentence}}</div>
</div>
```

**back.html**

```html
{{FrontSide}}
<hr class="sep">
<div class="card back">
  <div class="trans">{{translation}}</div>
  <div class="anno">{{annotation}}</div>
</div>
```

**style.css**

```css
.card {
  font-family: "Noto Serif SC", "Georgia", serif;
  background: #111118;
  color: #e8e8f0;
  padding: 28px;
  border-radius: 16px;
  max-width: 580px;
  margin: 0 auto;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.shot img {
  width: 100%;
  border-radius: 10px;
  margin-bottom: 20px;
  opacity: 0.92;
}

.sent {
  font-size: 1.5em;
  line-height: 1.65;
  text-align: center;
  letter-spacing: 0.01em;
  margin: 12px 0;
}

.sep {
  border: none;
  border-top: 1px solid #2a2a3a;
  margin: 22px 0;
}

.trans {
  font-size: 1.1em;
  color: #8888aa;
  text-align: center;
  margin-bottom: 14px;
}

.anno {
  font-size: 0.88em;
  color: #55556a;
  line-height: 1.9;
}
```

---

## 打包与导入

**打包**

将四个文件直接压缩为 ZIP，不要包含子文件夹：

```
✓ 正确：zip 根目录直接是 theme.json、front.html 等
✗ 错误：zip 里有一层 mytheme/ 文件夹再放文件
```

macOS 用户注意：用系统"压缩"功能会自动加一层文件夹，建议用命令行：

```bash
cd mytheme/
zip ../mytheme.zip theme.json front.html back.html style.css
```

**导入**

ClipLingo → 主题选择器 → 我的主题 → **导入 ZIP** → 选择文件

导入成功后主题立即出现在选择器中，CardPreview 同步更新预览。

---

## 注意事项

**不支持的内容**

- `<script>` 标签会被自动移除
- 内联事件（`onclick`、`onload` 等）会被自动移除
- 外部字体需要通过 `@import` 或 `@font-face` 引入，Anki 离线环境下外部 CDN 可能无法访问，建议使用系统字体或将字体文件一并打包（目前版本暂不支持字体文件，使用系统字体最稳妥）

**Anki 与预览的差异**

ClipLingo 内的 CardPreview 使用 iframe 渲染，和 Anki 客户端的渲染引擎略有差异。建议导入 Anki 后实际翻几张卡片确认效果。

**类名冲突**

Anki 本身有一些内置类名（如 `.card`、`.night_mode`），建议给自己的类名加前缀避免冲突：

```css
/* 推荐 */
.cl-sentence { ... }
.cl-translation { ... }
```

---

## 分享模板

做好的模板可以通过以下方式分享：

**直接分享 ZIP 文件**
发到群组、论坛或朋友，对方在 ClipLingo 里点"导入 ZIP"即可使用。

**提交到模板社区**
前往 [cliplingo-templates](https://github.com/qinusui/cliplingo-templates)，按照仓库说明提交 Pull Request。审核通过后，所有 ClipLingo 用户都能在应用内的模板市场里一键安装你的主题。

提交时需要额外提供一张 `preview.jpg`（建议尺寸 600×400px），作为模板市场的封面图。
