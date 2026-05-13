/**
 * AnkiConnect 同步逻辑
 * 将 ProcessedCard 逐张同步到 Anki
 */

import i18n from '../i18n';
import type { ProcessedCard, ThemeOverrides } from '../types';
import {
  createDeck,
  createModel,
  urlToBase64,
  storeMediaFile,
  addNote,
} from './ankiConnect';

const MODEL_NAME = 'ClipLingo';
const DECK_PREFIX = 'ClipLingo';

// ── 模板缓存 ────────────────────────────────────────────

type ThemeTemplate = {
  css: string;
  sentence: { front: string; back: string };
  vocab: { front: string; back: string };
};

const _templateCache = new Map<string, ThemeTemplate>();

/** 从后端获取主题模板（内置 + 自定义），自动注入 CSS 变量覆盖 */
async function fetchTemplate(theme: string, overrides?: ThemeOverrides): Promise<ThemeTemplate> {
  const cacheKey = theme + '\x00' + JSON.stringify(overrides || {});
  const cached = _templateCache.get(cacheKey);
  if (cached) return cached;

  const resp = await fetch('/api/themes/template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme, overrides: overrides || undefined }),
  });
  if (!resp.ok) {
    // fallback: try default theme
    const fallbackResp = await fetch('/api/themes/template', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: 'default' }),
    });
    if (!fallbackResp.ok) {
      throw new Error(`无法加载主题模板: ${resp.status}`);
    }
    const data = await fallbackResp.json();
    const tpl: ThemeTemplate = {
      css: data.css,
      sentence: { front: data.sentence.front, back: data.sentence.back },
      vocab: { front: data.vocab.front, back: data.vocab.back },
    };
    _templateCache.set(cacheKey, tpl);
    return tpl;
  }
  const data = await resp.json();
  const tpl: ThemeTemplate = {
    css: data.css,
    sentence: { front: data.sentence.front, back: data.sentence.back },
    vocab: { front: data.vocab.front, back: data.vocab.back },
  };
  _templateCache.set(cacheKey, tpl);
  return tpl;
}

// ── 同步接口 ────────────────────────────────────────────

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
  themeOverrides?: ThemeOverrides,
  onProgress?: (p: SyncProgress) => void,
  signal?: AbortSignal,
): Promise<SyncResult> {
  const fullName = `${DECK_PREFIX}::${deckName}`;
  let added = 0;
  let skipped = 0;
  let failed = 0;

  // 每次同步生成唯一标识，防止跨批次媒体文件覆盖导致错位
  const uid = Math.random().toString(36).slice(2, 8);

  // 从后端获取主题模板（已注入 CSS 覆盖）
  const tpl = await fetchTemplate(theme || 'default', themeOverrides);
  const styles = cardStyles || ['sentence'];

  // 1. 创建牌组
  await createDeck(fullName);

  // 2. 根据 cardStyles 构建模板列表
  const cardTemplates: Array<{ Name: string; Front: string; Back: string }> = [];
  if (styles.includes('sentence')) {
    cardTemplates.push({
      Name: 'Sentence Card',
      Front: tpl.sentence.front,
      Back: tpl.sentence.back,
    });
  }
  if (styles.includes('vocab')) {
    cardTemplates.push({
      Name: 'Vocab Card',
      Front: tpl.vocab.front,
      Back: tpl.vocab.back,
    });
  }

  // 如果没有选择任何样式，默认使用 sentence
  if (cardTemplates.length === 0) {
    cardTemplates.push({
      Name: 'Sentence Card',
      Front: tpl.sentence.front,
      Back: tpl.sentence.back,
    });
  }

  // 3. 创建模型（幂等）—— Sentence 放首位作为排序字段（始终有内容）
  await createModel({
    modelName: MODEL_NAME,
    inOrderFields: ['Sentence', 'Screenshot', 'Audio', 'Translation', 'Notes', 'Word', 'Definition'],
    css: tpl.css,
    cardTemplates,
  });

  // 3. 逐张同步
  for (let i = 0; i < cards.length; i++) {
    if (signal?.aborted) {
      throw new DOMException(i18n.t('ankiSync.stop'), 'AbortError');
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
          const imgName = `cliplingo_${uid}_${String(i + 1).padStart(4, '0')}.jpg`;
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
          const audioName = `cliplingo_${uid}_${String(i + 1).padStart(4, '0')}.mp3`;
          await storeMediaFile(audioName, audioBase64);
          audioField = `[sound:${audioName}]`;
        }
      } catch {
        // 音频获取失败，跳过
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
