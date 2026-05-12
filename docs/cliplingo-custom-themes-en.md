# ClipLingo Custom Card Template Guide

> Intended for: Anki power users comfortable with HTML/CSS

---

## Overview

ClipLingo supports fully custom card appearance and layout through ZIP template imports. You control the front/back HTML markup, fonts, colors, animations — anything CSS can do.

Finished templates can be shared with others or submitted to the [ClipLingo Template Community](https://github.com/qinusui/cliplingo-templates) for all users to discover.

---

## File Structure

A valid template package is a `.zip` file with exactly four entries:

```
mytheme.zip
├── theme.json     required · template metadata
├── front.html     required · card front
├── back.html      required · card back
└── style.css      required · stylesheet
```

All four files are mandatory. Filenames are case-sensitive.

---

## Field Reference

Use `{{fieldname}}` placeholders in `front.html` and `back.html`:

| Field              | Content                | Example                               |
| ------------------ | ---------------------- | ------------------------------------- |
| `{{sentence}}`     | Original sentence      | `Well, the point is...`               |
| `{{translation}}`  | Translation            | `The point is...`                     |
| `{{annotation}}`   | Grammar/vocab notes    | `<b>the point</b> noun phrase...`     |
| `{{audio}}`        | Audio player           | `[sound:cliplingo_0001.mp3]`          |
| `{{screenshot}}`   | Screenshot image       | `<img src="cliplingo_0001.jpg">`      |
| `{{word}}`         | Target word            | `point`                               |
| `{{definition}}`   | Word definition        | `a particular matter`                 |

**Notes:**

- `{{audio}}` uses Anki's `[sound:filename]` syntax; Anki renders it as a player automatically
- `{{screenshot}}` is already a complete `<img>` tag — drop it in directly
- `{{annotation}}` may contain HTML; do not wrap it in `<pre>`

**Conditional blocks** are fully supported:

```html
{{#word}}
<div class="word-section">{{word}}</div>
{{/word}}

{{^screenshot}}
<p class="no-image">No screenshot available</p>
{{/screenshot}}
```

In `back.html`, use `{{FrontSide}}` to embed the entire front card:

```html
{{FrontSide}}
<hr>
<div class="translation">{{translation}}</div>
```

---

## File Descriptions

### theme.json

```json
{
  "name": "my-theme",
  "version": 1,
  "author": "Your Name",
  "description": "One-line description of the theme style"
}
```

| Field           | Required | Notes                                                   |
| --------------- | -------- | ------------------------------------------------------- |
| `name`          | Yes      | Display name in the app; must not conflict with existing themes |
| `version`       | Yes      | Use `1`                                                 |
| `author`        | No       | Shown when sharing with others                           |
| `description`   | No       | Shown in the template marketplace                        |

---

### front.html

The card front — typically shows only the sentence and screenshot, without revealing the answer:

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

The card back — shows the full information:

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

The stylesheet applies to both front and back. Anki merges front and back CSS into a single document, so avoid conflicting class names.

```css
/* Base card styling */
.card {
  font-family: "Noto Serif SC", serif;
  background-color: #1a1a2e;
  color: #eaeaea;
  padding: 24px;
  border-radius: 12px;
  max-width: 600px;
  margin: 0 auto;
}

/* Screenshot */
.screenshot img {
  width: 100%;
  border-radius: 8px;
  margin-bottom: 16px;
}

/* Sentence */
.sentence {
  font-size: 1.4em;
  line-height: 1.6;
  margin: 16px 0;
  text-align: center;
}

/* Divider */
.divider {
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.15);
  margin: 20px 0;
}

/* Translation */
.translation {
  font-size: 1.1em;
  color: #a0a0b0;
  text-align: center;
  margin-bottom: 12px;
}

/* Notes */
.annotation {
  font-size: 0.9em;
  color: #6c6c8a;
  line-height: 1.8;
}
```

---

## Full Example: Minimal Dark Theme

A complete, copy-paste-ready template.

**theme.json**

```json
{
  "name": "minimal-dark",
  "version": 1,
  "author": "ClipLingo",
  "description": "Dark background, clean typography, ideal for night study"
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

## Packaging & Importing

**Packaging**

Zip the four files directly — no parent folder inside the archive:

```
✓ Correct: zip root contains theme.json, front.html, etc.
✗ Wrong:   zip contains a mytheme/ folder with the files inside
```

macOS users: the system "Compress" function wraps everything in a folder. Use the command line instead:

```bash
cd mytheme/
zip ../mytheme.zip theme.json front.html back.html style.css
```

**Importing**

ClipLingo → Theme Selector → Custom Themes → **Import ZIP** → Choose file

The theme appears in the selector immediately, with a live preview in CardPreview.

---

## Important Notes

**Unsupported content**

- `<script>` tags are stripped automatically
- Inline event handlers (`onclick`, `onload`, etc.) are stripped automatically
- External fonts via CDN may not work in Anki's offline environment — use system fonts for safety

**Anki vs. Preview differences**

ClipLingo's CardPreview renders templates in an iframe, which may differ slightly from Anki's rendering engine. After importing into Anki, flip through a few actual cards to verify the result.

**Class name conflicts**

Anki reserves some class names (e.g., `.card`, `.night_mode`). Prefix your custom classes to avoid collisions:

```css
/* Recommended */
.cl-sentence { ... }
.cl-translation { ... }
```

---

## Sharing Templates

**Share the ZIP directly**

Send the `.zip` to friends or post it in communities. They just click "Import ZIP" in ClipLingo.

**Submit to the template community**

Head to [cliplingo-templates](https://github.com/qinusui/cliplingo-templates) and follow the repo instructions to submit a Pull Request. Once approved, all ClipLingo users can install your theme with one click from the in-app template marketplace.

Include a `preview.jpg` (recommended 600×400px) as the marketplace cover image with your submission.
