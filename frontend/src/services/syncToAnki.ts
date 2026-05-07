/**
 * AnkiConnect 同步逻辑
 * 将 ProcessedCard 逐张同步到 Anki
 */

import type { ProcessedCard } from '../types';
import {
  createDeck,
  createModel,
  urlToBase64,
  storeMediaFile,
  addNote,
} from './ankiConnect';

const MODEL_NAME = 'ClipLingo';
const DECK_PREFIX = 'ClipLingo';

// ── 主题配置（复用 pack_apkg.py） ──

type ThemeConfig = {
  css: string;
  sentence: { front: string; back: string };
  vocab: { front: string; back: string };
};

const THEMES: Record<string, ThemeConfig> = {
  default: {
    css: `.card {
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 18px;
  text-align: center;
  color: #2c3e50;
  background-color: #f8f9fa;
  margin: 0;
  padding: 10px;
}
.container { max-width: 600px; margin: 0 auto; }
.image-box img {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  margin-bottom: 10px;
}
.original { font-weight: 600; font-size: 1.2em; color: #000; margin-top: 15px; }
.translation { color: #666; font-size: 0.95em; margin-top: 8px; }
.notes {
  text-align: left;
  background: #fff;
  border-left: 4px solid #007bff;
  padding: 10px;
  margin-top: 15px;
  font-size: 0.9em;
  border-radius: 4px;
  white-space: pre-line;
}
.target-word {
  font-size: 2.5em;
  font-weight: 800;
  color: #007bff;
  margin: 40px 0 10px 0;
}
.word-meaning {
  font-size: 1.4em;
  color: #28a745;
  font-weight: 500;
  margin-bottom: 20px;
}
.hint {
  color: #999;
  font-size: 0.85em;
  margin-top: 20px;
}
.example-box {
  background: #f0f2f5;
  padding: 15px;
  border-radius: 12px;
  text-align: left;
  margin-top: 15px;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.7em;
  padding: 2px 8px;
  background: #6c757d;
  color: white;
  border-radius: 4px;
  margin-bottom: 8px;
}
.example-box .image-box img { width: 100%; height: auto; border-radius: 8px; }
.example-box .original { font-weight: 600; font-size: 1em; color: #333; margin: 8px 0; }
.nightMode .card { background-color: #1e1e1e; color: #eee; }
.nightMode .translation { color: #aaa; }
.nightMode .notes { background: #2d2d2d; border-left-color: #375a7f; }
.nightMode .target-word { color: #4da6ff; }
.nightMode .word-meaning { color: #5cb85c; }
.nightMode .hint { color: #666; }
.nightMode .example-box { background: #2d2d2d; }
.nightMode .example-box .original { color: #ccc; }`,
    sentence: {
      front: `<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
</div>`,
      back: `<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <hr id="answer">
  <div class="text-content">
    <div class="original">{{Sentence}}</div>
    {{#Translation}}
    <div class="translation">{{Translation}}</div>
    {{/Translation}}
    {{#Notes}}
    <div class="notes">{{Notes}}</div>
    {{/Notes}}
  </div>
</div>`,
    },
    vocab: {
      front: `<div class="container">
  <div class="target-word">{{Word}}</div>
  <div class="hint">试着回想这个词在视频里的意思</div>
</div>`,
      back: `<div class="container">
  <div class="target-word">{{Word}}</div>
  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}
  <hr id="answer">
  <div class="example-box">
    <div class="tag">CONTEXT / 例句</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
</div>`,
    },
  },
  minimal: {
    css: `.card {
  font-family: Georgia, "Noto Serif SC", "Source Han Serif CN", serif;
  font-size: 20px;
  text-align: center;
  color: #1a1a2e;
  background-color: #fafaf8;
  margin: 0;
  padding: 0;
  position: relative;
  min-height: 80vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bg-image {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  opacity: 0.12;
  background-size: cover;
  background-position: center;
  pointer-events: none;
}
.container {
  position: relative;
  max-width: 560px;
  margin: 0 auto;
  padding: 40px 30px;
}
.image-box { display: none; }
.divider {
  width: 40px;
  height: 1px;
  background: #c0b8a8;
  margin: 24px auto;
}
.original {
  font-weight: 600;
  font-size: 1.3em;
  line-height: 1.6;
  color: #1a1a2e;
  letter-spacing: 0.01em;
}
.translation {
  color: #8a8578;
  font-size: 0.95em;
  margin-top: 12px;
  line-height: 1.5;
}
.notes {
  text-align: left;
  background: #f5f2ec;
  border-left: 3px solid #c0b8a8;
  padding: 12px 14px;
  margin-top: 20px;
  font-size: 0.88em;
  border-radius: 0 4px 4px 0;
  white-space: pre-line;
  color: #5a5550;
}
.target-word {
  font-size: 2.8em;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 8px 0;
  letter-spacing: -0.02em;
}
.hint {
  color: #b0a898;
  font-size: 0.85em;
  font-style: italic;
}
.word-meaning {
  font-size: 1.2em;
  color: #6b8f71;
  font-weight: 500;
  margin: 16px 0;
}
.divider { margin: 20px auto; }
.example-box {
  background: #f5f2ec;
  padding: 20px;
  border-radius: 8px;
  text-align: left;
  margin-top: 20px;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.65em;
  padding: 2px 8px;
  background: transparent;
  color: #b0a898;
  border: 1px solid #d4cdc0;
  border-radius: 3px;
  margin-bottom: 10px;
  letter-spacing: 0.05em;
}
.example-box .image-box { display: block; }
.example-box .image-box img { width: 100%; height: auto; border-radius: 6px; margin-bottom: 12px; }
.example-box .original { font-weight: 600; font-size: 1em; color: #1a1a2e; margin: 8px 0; line-height: 1.5; }
.nightMode .card { background-color: #1a1a1a; color: #d4cdc0; }
.nightMode .original { color: #e8e0d4; }
.nightMode .translation { color: #8a8578; }
.nightMode .notes { background: #252520; border-left-color: #5a5550; color: #a09888; }
.nightMode .target-word { color: #e8e0d4; }
.nightMode .hint { color: #666; }
.nightMode .word-meaning { color: #7da882; }
.nightMode .example-box { background: #252520; }
.nightMode .example-box .original { color: #a09888; }`,
    sentence: {
      front: `<div class="bg-image" style="background-image: url({{Screenshot}})"></div>
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
</div>`,
      back: `<div class="bg-image" style="background-image: url({{Screenshot}})"></div>
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="original">{{Sentence}}</div>
  <div class="divider"></div>
  {{#Translation}}
  <div class="translation">{{Translation}}</div>
  {{/Translation}}
  {{#Notes}}
  <div class="notes">{{Notes}}</div>
  {{/Notes}}
</div>`,
    },
    vocab: {
      front: `<div class="container">
  <div class="target-word">{{Word}}</div>
  <div class="hint">recall the meaning from context</div>
</div>`,
      back: `<div class="container">
  <div class="target-word">{{Word}}</div>
  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}
  <div class="divider"></div>
  <div class="example-box">
    <div class="tag">CONTEXT</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
</div>`,
    },
  },
  netflix: {
    css: `.card {
  font-family: "Helvetica Neue", Arial, "PingFang SC", sans-serif;
  font-size: 18px;
  text-align: center;
  color: #e5e5e5;
  background-color: #141414;
  margin: 0;
  padding: 0;
}
.container { max-width: 600px; margin: 0 auto; padding: 16px; }
.image-box img {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.6);
}
.audio-box { margin-top: 8px; }
.original {
  font-weight: 600;
  font-size: 1.15em;
  color: #ffffff;
  margin-top: 14px;
  line-height: 1.5;
}
.translation {
  color: #e50914;
  font-size: 0.95em;
  margin-top: 8px;
  font-weight: 500;
}
.notes {
  text-align: left;
  background: rgba(255,255,255,0.08);
  border-left: 3px solid #e50914;
  padding: 10px 12px;
  margin-top: 14px;
  font-size: 0.85em;
  border-radius: 0 4px 4px 0;
  white-space: pre-line;
  color: #b3b3b3;
}
.progress-bar {
  width: 100%;
  height: 3px;
  background: #333;
  margin-top: 20px;
  border-radius: 2px;
}
.target-word {
  font-size: 3em;
  font-weight: 800;
  color: #e50914;
  margin: 30px 0 10px 0;
  text-shadow: 0 2px 8px rgba(229,9,20,0.3);
}
.hint {
  color: #666;
  font-size: 0.85em;
  margin-top: 16px;
}
.word-meaning {
  font-size: 1.3em;
  color: #e5e5e5;
  font-weight: 500;
  margin: 16px 0;
}
.example-box {
  background: rgba(255,255,255,0.05);
  padding: 16px;
  border-radius: 6px;
  text-align: left;
  margin-top: 16px;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.65em;
  padding: 2px 8px;
  background: #e50914;
  color: white;
  border-radius: 3px;
  margin-bottom: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.example-box .image-box img { width: 100%; height: auto; border-radius: 4px; margin-bottom: 10px; }
.example-box .original { font-weight: 600; font-size: 1em; color: #e5e5e5; margin: 8px 0; }
.nightMode .card { background-color: #0a0a0a; }
.nightMode .translation { color: #ff3d47; }
.nightMode .notes { background: rgba(255,255,255,0.04); border-left-color: #b20710; }
.nightMode .target-word { color: #ff3d47; }
.nightMode .word-meaning { color: #e5e5e5; }
.nightMode .hint { color: #555; }
.nightMode .example-box { background: rgba(255,255,255,0.03); }
.nightMode .example-box .original { color: #e5e5e5; }`,
    sentence: {
      front: `<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
</div>`,
      back: `<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="original">{{Sentence}}</div>
  {{#Translation}}
  <div class="translation">{{Translation}}</div>
  {{/Translation}}
  {{#Notes}}
  <div class="notes">{{Notes}}</div>
  {{/Notes}}
  <div class="progress-bar"></div>
</div>`,
    },
    vocab: {
      front: `<div class="container">
  <div class="target-word">{{Word}}</div>
  <div class="hint">recall from the scene</div>
</div>`,
      back: `<div class="container">
  <div class="target-word">{{Word}}</div>
  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}
  <div class="example-box">
    <div class="tag">SCENE CONTEXT</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
</div>`,
    },
  },
  dictionary: {
    css: `.card {
  font-family: "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
  font-size: 17px;
  text-align: left;
  color: #2d2a26;
  background-color: #fefcf3;
  margin: 0;
  padding: 0;
  line-height: 1.55;
}
.container {
  max-width: 580px;
  margin: 0 auto;
  padding: 24px 28px;
  border: 1px solid #e0dcd0;
  box-shadow: 2px 2px 8px rgba(0,0,0,0.06);
}
.image-box { display: none; }
.section-label {
  font-size: 0.7em;
  font-weight: 700;
  color: #8b7355;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  margin: 16px 0 6px 0;
  padding-bottom: 4px;
  border-bottom: 1px solid #e8e2d4;
}
.section-label:first-child { margin-top: 0; }
.original {
  font-weight: 600;
  font-size: 1.1em;
  color: #2d2a26;
  line-height: 1.6;
}
.translation {
  color: #5a5248;
  font-size: 0.95em;
  margin-top: 4px;
}
.notes {
  background: #f5f0e4;
  border-left: 3px solid #c4a96a;
  padding: 10px 12px;
  margin-top: 6px;
  font-size: 0.85em;
  border-radius: 0 3px 3px 0;
  white-space: pre-line;
  color: #4a4540;
}
.dict-divider {
  border: none;
  border-top: 1px solid #e0dcd0;
  margin: 16px 0;
}
.clearfix::after {
  content: "";
  display: table;
  clear: both;
}
.thumb {
  float: right;
  width: 140px;
  margin: 0 0 12px 16px;
  border: 1px solid #e0dcd0;
  padding: 3px;
  background: #fff;
}
.thumb .image-box { display: block; }
.thumb .image-box img { width: 100%; height: auto; display: block; }
.target-word {
  font-size: 2em;
  font-weight: 700;
  color: #2d2a26;
  margin: 0 0 4px 0;
}
.phonetic {
  font-size: 0.95em;
  color: #8b7355;
  font-style: italic;
  margin-bottom: 16px;
}
.hint {
  color: #b0a898;
  font-size: 0.82em;
  font-style: italic;
  margin-top: 16px;
}
.word-meaning {
  font-size: 1.05em;
  color: #2d2a26;
  margin: 8px 0;
}
.example-box {
  background: #f8f4ea;
  padding: 14px 16px;
  border-radius: 4px;
  text-align: left;
  margin-top: 12px;
  border: 1px solid #e8e2d4;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.6em;
  padding: 1px 6px;
  background: #8b7355;
  color: #fefcf3;
  border-radius: 2px;
  margin-bottom: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.example-box .image-box img { width: 100%; height: auto; border-radius: 3px; margin-bottom: 8px; }
.example-box .original { font-weight: 600; font-size: 0.95em; color: #2d2a26; margin: 6px 0; }
.nightMode .card { background-color: #1e1c18; color: #d4cdc0; }
.nightMode .container { border-color: #3a3530; box-shadow: 2px 2px 8px rgba(0,0,0,0.3); }
.nightMode .section-label { color: #a09888; border-bottom-color: #3a3530; }
.nightMode .original { color: #e8e0d4; }
.nightMode .translation { color: #a09888; }
.nightMode .notes { background: #2a2720; border-left-color: #8b7355; color: #b0a898; }
.nightMode .dict-divider { border-top-color: #3a3530; }
.nightMode .thumb { border-color: #3a3530; }
.nightMode .target-word { color: #e8e0d4; }
.nightMode .phonetic { color: #a09888; }
.nightMode .hint { color: #666; }
.nightMode .word-meaning { color: #d4cdc0; }
.nightMode .example-box { background: #2a2720; border-color: #3a3530; }
.nightMode .example-box .original { color: #a09888; }`,
    sentence: {
      front: `<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
  <div class="section-label">Sentence</div>
  <div class="original" style="text-align: center;">聆听音频，回忆句子</div>
</div>`,
      back: `<div class="container clearfix">
  <div class="section-label">Sentence</div>
  {{#Screenshot}}
  <div class="thumb"><div class="image-box">{{Screenshot}}</div></div>
  {{/Screenshot}}
  <div class="original">{{Sentence}}</div>

  {{#Translation}}
  <div class="section-label">Translation</div>
  <div class="translation">{{Translation}}</div>
  {{/Translation}}

  {{#Notes}}
  <div class="section-label">Notes</div>
  <div class="notes">{{Notes}}</div>
  {{/Notes}}

  <hr class="dict-divider">
  <div class="audio-box">{{Audio}}</div>
</div>`,
    },
    vocab: {
      front: `<div class="container">
  <div class="target-word">{{Word}}</div>
  <div class="phonetic">listen & recall</div>
  <div class="hint">回忆该词在视频语境中的含义</div>
</div>`,
      back: `<div class="container">
  <div class="target-word">{{Word}}</div>

  {{#Definition}}
  <div class="section-label">Definition</div>
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}

  <div class="section-label">Context</div>
  <div class="example-box">
    <div class="tag">VIDEO CONTEXT</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
</div>`,
    },
  },
};

function getThemeConfig(theme: string): ThemeConfig {
  return THEMES[theme] || THEMES['default'];
}

// ── 同步接口 ──

export interface SyncProgress {
  current: number;
  total: number;
  added: number;
  skipped: number;
  failed: number;
  currentSentence: string;
}

export type SyncResult = {
  added: number;
  skipped: number;
  failed: number;
};

/**
 * 将卡片列表同步到 Anki
 * @param cards 处理后的卡片数据
 * @param deckName 牌组名称（通常是视频文件名）
 * @param apiBase 后端地址，用于拼接媒体文件 URL
 * @param cardStyles 卡片样式列表，如 ['sentence']、['vocab']、['sentence', 'vocab']
 * @param theme 主题名称，如 'default'、'minimal'、'netflix'、'dictionary'
 * @param onProgress 进度回调
 * @param signal 中断信号
 */
export async function syncToAnki(
  cards: ProcessedCard[],
  deckName: string,
  apiBase: string,
  cardStyles?: string[],
  theme?: string,
  onProgress?: (p: SyncProgress) => void,
  signal?: AbortSignal,
): Promise<SyncResult> {
  const fullName = `${DECK_PREFIX}::${deckName}`;
  let added = 0;
  let skipped = 0;
  let failed = 0;

  // 获取主题配置
  const themeConfig = getThemeConfig(theme || 'default');
  const styles = cardStyles || ['sentence'];

  // 1. 创建牌组
  await createDeck(fullName);

  // 2. 根据 cardStyles 构建模板列表
  const cardTemplates: Array<{ Name: string; Front: string; Back: string }> = [];
  if (styles.includes('sentence')) {
    cardTemplates.push({
      Name: 'Sentence Card',
      Front: themeConfig.sentence.front,
      Back: themeConfig.sentence.back,
    });
  }
  if (styles.includes('vocab')) {
    cardTemplates.push({
      Name: 'Vocab Card',
      Front: themeConfig.vocab.front,
      Back: themeConfig.vocab.back,
    });
  }

  // 如果没有选择任何样式，默认使用 sentence
  if (cardTemplates.length === 0) {
    cardTemplates.push({
      Name: 'Sentence Card',
      Front: themeConfig.sentence.front,
      Back: themeConfig.sentence.back,
    });
  }

  // 3. 创建模型（幂等）
  await createModel({
    modelName: MODEL_NAME,
    inOrderFields: ['Screenshot', 'Audio', 'Sentence', 'Translation', 'Notes', 'Word', 'Definition'],
    css: themeConfig.css,
    cardTemplates,
  });

  // 3. 逐张同步
  for (let i = 0; i < cards.length; i++) {
    if (signal?.aborted) {
      throw new DOMException('同步已取消', 'AbortError');
    }

    const card = cards[i];

    onProgress?.({
      current: i + 1,
      total: cards.length,
      added,
      skipped,
      failed,
      currentSentence: card.sentence,
    });

    try {
      // 上传媒体文件
      let screenshotField = '';
      let audioField = '';

      try {
        if (card.screenshot_path) {
          const imgUrl = card.screenshot_path.startsWith('http')
            ? card.screenshot_path
            : `${apiBase}${card.screenshot_path}`;
          const imgBase64 = await urlToBase64(imgUrl);
          const imgName = `cliplingo_${String(i + 1).padStart(4, '0')}.jpg`;
          await storeMediaFile(imgName, imgBase64);
          screenshotField = `<img src="${imgName}">`;
        }
      } catch {
        // 截图获取失败，使用占位符（Screenshot 是排序字段，不能为空）
      }

      try {
        if (card.audio_path) {
          const audioUrl = card.audio_path.startsWith('http')
            ? card.audio_path
            : `${apiBase}${card.audio_path}`;
          const audioBase64 = await urlToBase64(audioUrl);
          const audioName = `cliplingo_${String(i + 1).padStart(4, '0')}.mp3`;
          await storeMediaFile(audioName, audioBase64);
          audioField = `[sound:${audioName}]`;
        }
      } catch {
        // 音频获取失败，跳过
      }

      // Screenshot 是 Anki 排序字段，不能为空，否则笔记会被拒绝
      if (!screenshotField) {
        screenshotField = '&nbsp;';
      }

      // 添加笔记
      await addNote({
        deckName: fullName,
        modelName: MODEL_NAME,
        fields: {
          Screenshot: screenshotField,
          Audio: audioField,
          Sentence: card.sentence,
          Translation: card.translation || '',
          Notes: card.notes || '',
          Word: card.word || '',
          Definition: card.definition || '',
        },
        options: { allowDuplicate: false },
        tags: ['cliplingo'],
      });

      added++;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('duplicate')) {
        skipped++;
      } else {
        failed++;
        console.warn(`卡片 #${i + 1} 同步失败:`, msg);
      }
    }
  }

  return { added, skipped, failed };
}
