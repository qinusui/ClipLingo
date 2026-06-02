import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ProcessedCard, CardTheme, ThemeOverrides } from '../types';
import { ChevronLeft, ChevronRight, Play, Pause, Loader2 } from 'lucide-react';
import { themeAPI } from '../services/themeAPI';

interface CardPreviewProps {
  cards: ProcessedCard[];
  cardStyles: string[];
  currentIndex: number;
  onPrevious: () => void;
  onNext: () => void;
  theme?: CardTheme;
  themeOverrides?: ThemeOverrides;
  videoFile?: File;
}

interface ThemeTemplate {
  name: string;
  css: string;
  sentence: { front: string; back: string };
  vocab: { front: string; back: string };
  isCustom: boolean;
}

const _baseTemplateCache = new Map<string, ThemeTemplate>();

// 简易字符串 hash，避免把大段 CSS 字符串当 React key
function _hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return h;
}

async function fetchWithRetry(url: string, options: RequestInit, retries = 2): Promise<Response> {
  let lastErr: Error | null = null;
  for (let i = 0; i <= retries; i++) {
    try {
      const resp = await fetch(url, options);
      return resp;
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e));
      if (i < retries) {
        await new Promise(r => setTimeout(r, 1000 * (i + 1)));
      }
    }
  }
  throw lastErr!;
}

async function fetchBaseTemplate(theme: string): Promise<ThemeTemplate> {
  const cached = _baseTemplateCache.get(theme);
  if (cached) return cached;

  const resp = await fetchWithRetry('/api/themes/template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme }),
  });

  const parse = (data: { name: string; css: string; sentence: { front: string; back: string }; vocab: { front: string; back: string }; isCustom: boolean }): ThemeTemplate => ({
    name: data.name,
    css: data.css,
    sentence: data.sentence,
    vocab: data.vocab,
    isCustom: data.isCustom || false,
  });

  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }));
    console.warn(`[CardPreview] 主题 "${theme}" 加载失败 (${resp.status}): ${detail.detail}，回退到 default`);
    const fb = await fetchWithRetry('/api/themes/template', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: 'default' }),
    });
    if (!fb.ok) {
      const fbDetail = await fb.json().catch(() => ({ detail: fb.statusText }));
      throw new Error(`默认主题加载也失败 (${fb.status}): ${fbDetail.detail}`);
    }
    const tpl = parse(await fb.json());
    return tpl;
  }

  const tpl = parse(await resp.json());
  _baseTemplateCache.set(theme, tpl);
  return tpl;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Anki 模板变量填充
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderTemplate(tpl: string, card: ProcessedCard): string {
  const fields: Record<string, string> = {
    Sentence: card.sentence || '',
    Translation: card.translation || '',
    Notes: card.notes || '',
    Word: card.word || '',
    Definition: card.definition || '',
    Screenshot: card.screenshot_path
      ? `<img src="${card.screenshot_path}" alt="screenshot">`
      : '',
    Audio: card.audio_path
      ? `<audio controls src="${card.audio_path}"></audio>`
      : '',
  };

  let html = tpl;

  for (const [field, value] of Object.entries(fields)) {
    const re = new RegExp(`{{#${field}}}([\\s\\S]*?){{/${field}}}`, 'g');
    html = html.replace(re, value ? '$1' : '');
  }

  for (const [field, value] of Object.entries(fields)) {
    const re = new RegExp(`{{\\^${field}}}([\\s\\S]*?){{/${field}}}`, 'g');
    html = html.replace(re, value ? '' : '$1');
  }

  for (const [field, value] of Object.entries(fields)) {
    html = html.replace(new RegExp(`{{${field}}}`, 'g'), value);
  }

  return html;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  iframe 渲染面板
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const TemplatePane = ({
  tpl,
  overrideCss,
  card,
  style,
  showAnswer,
  cardScopeId,
}: {
  tpl: ThemeTemplate;
  overrideCss: string;
  card: ProcessedCard;
  style: string;
  showAnswer: boolean;
  cardScopeId: string;
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const tmpl = style === 'vocab' ? tpl.vocab : tpl.sentence;
  const htmlFragment = renderTemplate(showAnswer ? tmpl.back : tmpl.front, card);

  // 覆盖层在前，主题 CSS 在后；覆盖层的 !important 会覆盖主题默认样式
  let html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>`;
  if (overrideCss) {
    html += `${overrideCss}\n`;
  }
  html += `${tpl.css}</style></head><body><div class="card">${htmlFragment}</div></body></html>`;

  const handleLoad = () => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    try {
      const body = iframe.contentWindow?.document?.body;
      if (body) {
        iframe.style.height = body.scrollHeight + 'px';
      }
    } catch {
      // 跨域或 sandbox 限制时忽略
    }
  };

  return (
    <iframe
      ref={iframeRef}
      key={`${cardScopeId}-${style}-${showAnswer ? 'back' : 'front'}`}
      srcDoc={html}
      sandbox={tpl.isCustom ? 'allow-scripts allow-same-origin' : undefined}
      className="w-full min-h-[300px] border-0"
      title="Card Preview"
      onLoad={handleLoad}
    />
  );
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export const CardPreview = ({
  cards,
  cardStyles,
  currentIndex,
  onPrevious,
  onNext,
  theme = 'default',
  themeOverrides,
}: CardPreviewProps) => {
  const { t } = useTranslation();
  const [isPlaying, setIsPlaying] = useState(false);
  const [previewStyle, setPreviewStyle] = useState<string>(cardStyles[0] || 'sentence');
  const [showAnswer, setShowAnswer] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [tpl, setTpl] = useState<ThemeTemplate | null>(null);
  const [tplLoading, setTplLoading] = useState(true);
  const [tplError, setTplError] = useState(false);
  const [overrideCss, setOverrideCss] = useState('');
  const overrideTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // 卡片唯一标识，用于 React key 和 iframe scope 隔离
  const cardScopeId = `clip-cls-${currentIndex}-${_hashStr(JSON.stringify(cards[currentIndex]?.sentence ?? ''))}`;

  // 主题变化时获取基础模板（不含覆盖），同时清除缓存和旧覆盖
  useEffect(() => {
    let cancelled = false;
    setTplLoading(true);
    setTplError(false);
    setOverrideCss('');
    _baseTemplateCache.delete(theme);
    fetchBaseTemplate(theme)
      .then(t => { if (!cancelled) { setTpl(t); setTplLoading(false); } })
      .catch((err) => { if (!cancelled) { console.error('[CardPreview] 模板加载失败:', err); setTplError(true); setTplLoading(false); } });
    return () => { cancelled = true; };
  }, [theme]);

  // 覆盖变化时通过 API 获取覆盖层 CSS（debounced）
  useEffect(() => {
    if (overrideTimerRef.current) clearTimeout(overrideTimerRef.current);
    if (!themeOverrides || Object.keys(themeOverrides).filter(k => themeOverrides[k]).length === 0) {
      setOverrideCss('');
      return;
    }
    overrideTimerRef.current = setTimeout(() => {
      themeAPI.getPreviewCss(theme, themeOverrides).then(css => {
        setOverrideCss(css || '');
      });
    }, 150);
    return () => { if (overrideTimerRef.current) clearTimeout(overrideTimerRef.current); };
  }, [themeOverrides, theme]);

  if (cards.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        {t('cardPreview.noCards')}
      </div>
    );
  }

  const card = cards[currentIndex];

  const handlePlayPause = () => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setIsPlaying(false);
    } else {
      audioRef.current.play().catch(() => {});
      setIsPlaying(true);
    }
  };

  const handleAudioEnded = () => setIsPlaying(false);

  const handleChangeCard = (fn: () => void) => {
    setIsPlaying(false);
    setShowAnswer(false);
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    fn();
  };

  return (
    <div className="space-y-4">
      {/* 导航 + 样式切换 */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => handleChangeCard(onPrevious)}
          disabled={currentIndex === 0}
          className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors dark:hover:bg-gray-700"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-600 dark:text-gray-400">
            {t('cardPreview.cardCount', { current: currentIndex + 1, total: cards.length })}
          </span>
          {cardStyles.length > 1 && (
            <div className="flex bg-gray-200 dark:bg-gray-700 rounded-lg p-0.5">
              {cardStyles.includes('sentence') && (
                <button
                  onClick={() => { setPreviewStyle('sentence'); setShowAnswer(false); }}
                  className={`px-2 py-0.5 text-xs rounded-md transition-colors ${
                    previewStyle === 'sentence'
                      ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm'
                      : 'text-gray-600 dark:text-gray-400'
                  }`}
                >
                  {t('cardPreview.sentenceCard')}
                </button>
              )}
              {cardStyles.includes('vocab') && (
                <button
                  onClick={() => { setPreviewStyle('vocab'); setShowAnswer(false); }}
                  className={`px-2 py-0.5 text-xs rounded-md transition-colors ${
                    previewStyle === 'vocab'
                      ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm'
                      : 'text-gray-600 dark:text-gray-400'
                  }`}
                >
                  {t('cardPreview.vocabCard')}
                </button>
              )}
            </div>
          )}
        </div>

        <button
          onClick={() => handleChangeCard(onNext)}
          disabled={currentIndex === cards.length - 1}
          className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors dark:hover:bg-gray-700"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>

      {/* 卡片预览容器（CSS 变量作用域隔离） */}
      <div id="card-preview-scope" className="bg-white dark:bg-gray-900 rounded-lg overflow-hidden">
        {tplLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
          </div>
        ) : tplError ? (
          <div className="text-center py-8 text-sm text-red-500">
            {t('cardPreview.loadError')}
          </div>
        ) : tpl ? (
          <TemplatePane
            key={`${theme}-${previewStyle}-${currentIndex}`}
            tpl={tpl}
            overrideCss={overrideCss}
            card={card}
            style={previewStyle}
            showAnswer={showAnswer}
            cardScopeId={cardScopeId}
          />
        ) : null}
      </div>

      {/* 显示/隐藏答案 */}
      <button
        onClick={() => setShowAnswer(!showAnswer)}
        className="w-full py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm"
      >
        {showAnswer ? t('cardPreview.showFront') : t('cardPreview.showAnswer')}
      </button>

      {/* 音频控制 */}
      <div className="flex items-center justify-center gap-3">
        {card.audio_path ? (
          <>
            <audio ref={audioRef} src={card.audio_path} onEnded={handleAudioEnded} preload="auto" />
            <button
              onClick={handlePlayPause}
              className="inline-flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600 text-sm"
            >
              {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              {isPlaying ? t('cardPreview.pause') : t('cardPreview.playAudio')}
            </button>
          </>
        ) : (
          <span className="text-sm text-gray-400">{t('cardPreview.noAudio')}</span>
        )}
      </div>
    </div>
  );
};
