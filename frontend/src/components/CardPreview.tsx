import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ProcessedCard, CardTheme, ThemeOverrides } from '../types';
import { ChevronLeft, ChevronRight, Play, Pause, Loader2 } from 'lucide-react';

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

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  模板获取与缓存（只获取基础模板，不含 overrides）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface ThemeTemplate {
  name: string;
  css: string;
  sentence: { front: string; back: string };
  vocab: { front: string; back: string };
  isCustom: boolean;
}

const _baseTemplateCache = new Map<string, ThemeTemplate>();

async function fetchBaseTemplate(theme: string): Promise<ThemeTemplate> {
  const cached = _baseTemplateCache.get(theme);
  if (cached) return cached;

  const resp = await fetch('/api/themes/template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme }),
  });

  const parse = (data: any): ThemeTemplate => ({
    name: data.name,
    css: data.css,
    sentence: data.sentence,
    vocab: data.vocab,
    isCustom: data.isCustom || false,
  });

  if (!resp.ok) {
    const fb = await fetch('/api/themes/template', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: 'default' }),
    });
    const tpl = parse(await fb.json());
    _baseTemplateCache.set(theme, tpl);
    return tpl;
  }

  const tpl = parse(await resp.json());
  _baseTemplateCache.set(theme, tpl);
  return tpl;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  客户端 CSS 变量覆盖注入（与服务端 inject_theme_overrides 保持一致）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function buildOverrideCss(overrides?: ThemeOverrides): string {
  if (!overrides) return '';
  const entries = Object.entries(overrides).filter(([, v]) => v !== undefined && v !== '');
  if (entries.length === 0) return '';

  const declarations = entries.map(([k, v]) => `  ${k}: ${v};`).join('\n');

  return `/* ── 用户自定义样式覆盖 ── */
:root {
${declarations}
}

.card { background-color: var(--card-bg, inherit) !important; color: var(--card-text, inherit) !important; padding: var(--card-padding, inherit) !important; border-radius: var(--card-radius, inherit) !important; box-shadow: var(--card-shadow, none) !important; }
.original, .sentence, .subtitle-text { font-family: var(--font-sentence, inherit) !important; font-size: var(--font-size-sentence, inherit) !important; }
.translation { color: var(--translation-color, inherit) !important; font-family: var(--font-translation, inherit) !important; font-size: var(--font-size-translation, inherit) !important; }
.notes, .annotation { color: var(--annotation-color, inherit) !important; }
.container { border-color: var(--accent-color, inherit) !important; }
hr, hr#answer, .divider { border-color: var(--accent-color, inherit) !important; }
`;
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
  overrides,
  card,
  style,
  showAnswer,
}: {
  tpl: ThemeTemplate;
  overrides?: ThemeOverrides;
  card: ProcessedCard;
  style: string;
  showAnswer: boolean;
}) => {
  const overrideCss = buildOverrideCss(overrides);
  const fullCss = overrideCss + tpl.css;
  const tmpl = style === 'vocab' ? tpl.vocab : tpl.sentence;
  const htmlFragment = renderTemplate(showAnswer ? tmpl.back : tmpl.front, card);
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>${fullCss}</style></head><body>${htmlFragment}</body></html>`;

  return (
    <iframe
      key={`${style}-${showAnswer ? 'back' : 'front'}-${JSON.stringify(overrides)}`}
      srcDoc={html}
      sandbox={tpl.isCustom ? 'allow-scripts' : undefined}
      className="w-full min-h-[300px] border-0"
      title="Card Preview"
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
  videoFile: _videoFile,
}: CardPreviewProps) => {
  const { t } = useTranslation();
  const [isPlaying, setIsPlaying] = useState(false);
  const [previewStyle, setPreviewStyle] = useState<string>(cardStyles[0] || 'sentence');
  const [showAnswer, setShowAnswer] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [tpl, setTpl] = useState<ThemeTemplate | null>(null);
  const [tplLoading, setTplLoading] = useState(true);
  const [tplError, setTplError] = useState(false);

  // 只在主题变化时从后端获取基础模板（覆盖变化由客户端即时处理）
  useEffect(() => {
    let cancelled = false;
    setTplLoading(true);
    setTplError(false);
    fetchBaseTemplate(theme)
      .then(t => { if (!cancelled) { setTpl(t); setTplLoading(false); } })
      .catch(() => { if (!cancelled) { setTplError(true); setTplLoading(false); } });
    return () => { cancelled = true; };
  }, [theme]);

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

      {/* 卡片：iframe 渲染真实 Anki 模板（overrides 客户端即时注入） */}
      <div className="bg-white dark:bg-gray-900 rounded-lg overflow-hidden">
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
            key={`${theme}-${previewStyle}`}
            tpl={tpl}
            overrides={themeOverrides}
            card={card}
            style={previewStyle}
            showAnswer={showAnswer}
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
