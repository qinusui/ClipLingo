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

// ── 默认主题模板（复用 pack_apkg.py） ──

const CSS = `.card {
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
.nightMode .example-box .original { color: #ccc; }`;

const SENTENCE_FRONT = `<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
</div>`;

const SENTENCE_BACK = `<div class="container">
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
</div>`;

const VOCAB_FRONT = `<div class="container">
  <div class="target-word">{{Word}}</div>
  <div class="hint">试着回想这个词在视频里的意思</div>
</div>`;

const VOCAB_BACK = `<div class="container">
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
</div>`;

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
 * @param onProgress 进度回调
 * @param signal 中断信号
 */
export async function syncToAnki(
  cards: ProcessedCard[],
  deckName: string,
  apiBase: string,
  onProgress?: (p: SyncProgress) => void,
  signal?: AbortSignal,
): Promise<SyncResult> {
  const fullName = `${DECK_PREFIX}::${deckName}`;
  let added = 0;
  let skipped = 0;
  let failed = 0;

  // 1. 创建牌组
  await createDeck(fullName);

  // 2. 创建模型（幂等）
  await createModel({
    modelName: MODEL_NAME,
    inOrderFields: ['Screenshot', 'Audio', 'Sentence', 'Translation', 'Notes', 'Word', 'Definition'],
    css: CSS,
    cardTemplates: [
      { Name: 'Sentence Card', Front: SENTENCE_FRONT, Back: SENTENCE_BACK },
      { Name: 'Vocab Card', Front: VOCAB_FRONT, Back: VOCAB_BACK },
    ],
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

      if (card.screenshot_path) {
        const imgUrl = card.screenshot_path.startsWith('http')
          ? card.screenshot_path
          : `${apiBase}${card.screenshot_path}`;
        const imgBase64 = await urlToBase64(imgUrl);
        const imgName = `cliplingo_${String(i + 1).padStart(4, '0')}.jpg`;
        await storeMediaFile(imgName, imgBase64);
        screenshotField = `<img src="${imgName}">`;
      }

      if (card.audio_path) {
        const audioUrl = card.audio_path.startsWith('http')
          ? card.audio_path
          : `${apiBase}${card.audio_path}`;
        const audioBase64 = await urlToBase64(audioUrl);
        const audioName = `cliplingo_${String(i + 1).padStart(4, '0')}.mp3`;
        await storeMediaFile(audioName, audioBase64);
        audioField = `[sound:${audioName}]`;
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
