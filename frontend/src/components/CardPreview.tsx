import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
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
//  主题 CSS（scoped under .anki-card，与 core/pack_apkg.py 保持一致）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const CSS_DEFAULT = `
.anki-card {
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 18px; text-align: center; color: #2c3e50;
  background-color: #f8f9fa; margin: 0; padding: 10px;
}
.anki-card .container { max-width: 600px; margin: 0 auto; }
.anki-card .image-box img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-bottom: 10px; }
.anki-card .original { font-weight: 600; font-size: 1.2em; color: #000; margin-top: 15px; }
.anki-card .translation { color: #666; font-size: 0.95em; margin-top: 8px; }
.anki-card .notes { text-align: left; background: #fff; border-left: 4px solid #007bff; padding: 10px; margin-top: 15px; font-size: 0.9em; border-radius: 4px; white-space: pre-line; }
.anki-card .target-word { font-size: 2.5em; font-weight: 800; color: #007bff; margin: 40px 0 10px 0; }
.anki-card .word-meaning { font-size: 1.4em; color: #28a745; font-weight: 500; margin-bottom: 20px; }
.anki-card .hint { color: #999; font-size: 0.85em; margin-top: 20px; }
.anki-card .example-box { background: #f0f2f5; padding: 15px; border-radius: 12px; text-align: left; margin-top: 15px; }
.anki-card .example-box .tag { display: inline-block; font-size: 0.7em; padding: 2px 8px; background: #6c757d; color: white; border-radius: 4px; margin-bottom: 8px; }
.anki-card .example-box .image-box img { width: 100%; height: auto; border-radius: 8px; }
.anki-card .example-box .original { font-weight: 600; font-size: 1em; color: #333; margin: 8px 0; }
.anki-card hr#answer { border: none; border-top: 1px solid #ddd; margin: 16px 0; }
`;

const CSS_MINIMAL = `
.anki-card {
  font-family: Georgia, "Noto Serif SC", "Source Han Serif CN", serif;
  font-size: 20px; text-align: center; color: #1a1a2e;
  background-color: #fafaf8; margin: 0; padding: 0;
  position: relative; min-height: 300px;
  display: flex; align-items: center; justify-content: center;
}
.anki-card .bg-image {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  opacity: 0.12; background-size: cover; background-position: center;
  pointer-events: none;
}
.anki-card .container { position: relative; max-width: 560px; margin: 0 auto; padding: 40px 30px; }
.anki-card .image-box { display: none; }
.anki-card .divider { width: 40px; height: 1px; background: #c0b8a8; margin: 24px auto; }
.anki-card .original { font-weight: 600; font-size: 1.3em; line-height: 1.6; color: #1a1a2e; letter-spacing: 0.01em; }
.anki-card .translation { color: #8a8578; font-size: 0.95em; margin-top: 12px; line-height: 1.5; }
.anki-card .notes { text-align: left; color: #6b6560; font-size: 0.85em; margin-top: 20px; padding: 12px 0; border-top: 1px solid #e8e4dc; white-space: pre-line; font-family: "Courier New", monospace; line-height: 1.6; }
.anki-card .target-word { font-size: 3em; font-weight: 700; color: #1a1a2e; margin: 0 0 8px 0; letter-spacing: -0.02em; }
.anki-card .word-meaning { font-size: 1.3em; color: #8a8578; font-weight: 400; margin: 16px 0; }
.anki-card .hint { color: #c0b8a8; font-size: 0.8em; margin-top: 24px; letter-spacing: 0.05em; }
.anki-card .example-box { text-align: left; margin-top: 24px; padding-top: 20px; border-top: 1px solid #e8e4dc; }
.anki-card .example-box .tag { display: inline-block; font-size: 0.65em; padding: 2px 8px; color: #a09888; border: 1px solid #e0dcd4; border-radius: 2px; margin-bottom: 10px; letter-spacing: 0.1em; text-transform: uppercase; }
.anki-card .example-box .image-box { display: none; }
.anki-card .example-box .original { font-weight: 400; font-size: 0.95em; color: #3a3530; margin: 6px 0; line-height: 1.5; }
.anki-card hr#answer { border: none; display: none; }
`;

const CSS_NETFLIX = `
.anki-card {
  font-family: "Helvetica Neue", Arial, "PingFang SC", sans-serif;
  font-size: 18px; text-align: center; color: #e5e5e5;
  background-color: #141414; margin: 0; padding: 0;
}
.anki-card .container { max-width: 600px; margin: 0 auto; padding: 16px; }
.anki-card .image-box img { max-width: 100%; height: auto; border-radius: 6px; box-shadow: 0 8px 32px rgba(0,0,0,0.6); }
.anki-card .original { font-weight: 600; font-size: 1.15em; color: #ffffff; margin-top: 14px; line-height: 1.5; }
.anki-card .translation { color: #e50914; font-size: 0.95em; margin-top: 8px; font-weight: 500; }
.anki-card .notes { text-align: left; background: rgba(255,255,255,0.08); border-left: 3px solid #e50914; padding: 10px 12px; margin-top: 14px; font-size: 0.85em; border-radius: 0 4px 4px 0; white-space: pre-line; color: #b3b3b3; }
.anki-card .progress-bar { width: 100%; height: 3px; background: #333; margin-top: 20px; border-radius: 2px; overflow: hidden; }
.anki-card .progress-bar::after { content: ''; display: block; width: 35%; height: 100%; background: #e50914; border-radius: 2px; }
.anki-card .target-word { font-size: 2.8em; font-weight: 800; color: #ffffff; margin: 30px 0 8px 0; text-shadow: 0 2px 20px rgba(229,9,20,0.3); }
.anki-card .word-meaning { font-size: 1.3em; color: #e50914; font-weight: 600; margin-bottom: 16px; }
.anki-card .hint { color: #666; font-size: 0.85em; margin-top: 16px; }
.anki-card .example-box { background: rgba(255,255,255,0.06); padding: 14px; border-radius: 8px; text-align: left; margin-top: 14px; border: 1px solid rgba(255,255,255,0.08); }
.anki-card .example-box .tag { display: inline-block; font-size: 0.65em; padding: 2px 10px; background: #e50914; color: white; border-radius: 3px; margin-bottom: 8px; font-weight: 700; letter-spacing: 0.08em; }
.anki-card .example-box .image-box img { width: 100%; border-radius: 4px; }
.anki-card .example-box .original { font-weight: 600; font-size: 0.95em; color: #e5e5e5; margin: 8px 0; }
.anki-card hr#answer { border: none; border-top: 1px solid rgba(255,255,255,0.1); margin: 14px 0; }
`;

const CSS_DICTIONARY = `
.anki-card {
  font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
  font-size: 17px; text-align: left; color: #2d2a26;
  background-color: #fefcf3; margin: 0; padding: 0; line-height: 1.55;
}
.anki-card .container { max-width: 580px; margin: 0 auto; padding: 24px 28px; border: 1px solid #e0dcd0; box-shadow: 2px 2px 8px rgba(0,0,0,0.06); }
.anki-card .image-box { display: none; }
.anki-card .section-label { font-size: 0.7em; font-weight: 700; color: #8b7355; text-transform: uppercase; letter-spacing: 0.15em; margin: 16px 0 6px 0; padding-bottom: 4px; border-bottom: 1px solid #e8e2d4; }
.anki-card .section-label:first-child { margin-top: 0; }
.anki-card .original { font-weight: 600; font-size: 1.1em; color: #2d2a26; line-height: 1.6; }
.anki-card .translation { color: #5a5248; font-size: 0.95em; margin-top: 4px; }
.anki-card .notes { background: #f5f0e4; border-left: 3px solid #c4a96a; padding: 10px 12px; margin-top: 6px; font-size: 0.85em; border-radius: 0 3px 3px 0; white-space: pre-line; font-family: "Courier New", monospace; color: #4a4538; line-height: 1.6; }
.anki-card .thumb { float: right; width: 110px; margin: 0 0 8px 14px; border: 1px solid #d4cfc0; border-radius: 3px; }
.anki-card .thumb img { width: 100%; height: auto; display: block; border-radius: 2px; }
.anki-card .headword { font-size: 2.2em; font-weight: 700; color: #2d2a26; margin: 0; display: inline; }
.anki-card .word-meaning { font-size: 1.2em; color: #4a4538; font-weight: 600; margin: 10px 0; }
.anki-card .hint { color: #b0a890; font-size: 0.8em; margin-top: 12px; font-style: italic; }
.anki-card .example-box { background: #f5f0e4; padding: 12px 14px; border-radius: 4px; margin-top: 10px; border: 1px solid #e8e2d4; }
.anki-card .example-box .tag { display: inline-block; font-size: 0.6em; font-weight: 700; padding: 1px 6px; background: #8b7355; color: white; border-radius: 2px; margin-bottom: 6px; letter-spacing: 0.1em; text-transform: uppercase; }
.anki-card .example-box .image-box { display: none; }
.anki-card .example-box .original { font-weight: 600; font-size: 0.95em; color: #3a3530; margin: 4px 0; }
.anki-card .dict-divider { border: none; border-top: 2px solid #c4a96a; margin: 16px 0 12px 0; }
.anki-card .clearfix::after { content: ''; display: table; clear: both; }
.anki-card hr#answer { border: none; border-top: 2px solid #c4a96a; margin: 16px 0 12px 0; }
`;

const THEMES_CSS: Record<string, string> = {
  default: CSS_DEFAULT,
  minimal: CSS_MINIMAL,
  netflix: CSS_NETFLIX,
  dictionary: CSS_DICTIONARY,
};

/** 将 ThemeOverrides 注入到主题 CSS 前面，CardPreview 中使用 .anki-card 作用域 */
function buildOverrideCss(baseCss: string, overrides: ThemeOverrides): string {
  const declarations = Object.entries(overrides)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `  ${k}: ${v};`)
    .join('\n');
  if (!declarations) return baseCss;

  return `/* ── 用户自定义样式覆盖 ── */
.anki-card :root {
${declarations}
}
.anki-card .card { background-color: var(--card-bg, inherit) !important; color: var(--card-text, inherit) !important; padding: var(--card-padding, inherit) !important; border-radius: var(--card-radius, inherit) !important; box-shadow: var(--card-shadow, none) !important; }
.anki-card .original, .anki-card .sentence, .anki-card .subtitle-text { font-family: var(--font-sentence, inherit) !important; font-size: var(--font-size-sentence, inherit) !important; }
.anki-card .translation { color: var(--translation-color, inherit) !important; font-family: var(--font-translation, inherit) !important; font-size: var(--font-size-translation, inherit) !important; }
.anki-card .notes, .anki-card .annotation { color: var(--annotation-color, inherit) !important; }
.anki-card .container { border-color: var(--accent-color, inherit) !important; }
.anki-card hr, .anki-card hr#answer, .anki-card .divider { border-color: var(--accent-color, inherit) !important; }
${baseCss}`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  默认主题卡片组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DefaultSentenceFront = ({ card, videoFile }: { card: ProcessedCard; videoFile?: File }) => (
  <div className="anki-card">
    <div className="container">
      <div className="image-box">
        {card.screenshot_path ? <img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /> : <Placeholder videoFile={videoFile} timestamp={card.start_sec} />}
      </div>
    </div>
  </div>
);

const DefaultSentenceBack = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="image-box">{card.screenshot_path && <img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} />}</div>
      <hr id="answer" />
      <div className="text-content">
        <div className="original">{card.sentence}</div>
        {card.translation && <div className="translation">{card.translation}</div>}
        {card.notes && <div className="notes">{card.notes}</div>}
      </div>
    </div>
  </div>
);

const DefaultVocabFront = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="target-word">{card.word || card.sentence}</div>
      <div className="hint">{i18n.t('ankiCard.vocabHintDefault')}</div>
    </div>
  </div>
);

const DefaultVocabBack = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="target-word">{card.word || card.sentence}</div>
      {card.definition && <div className="word-meaning">{card.definition}</div>}
      <hr id="answer" />
      <div className="example-box">
        <div className="tag">{i18n.t('ankiCard.exampleTagDefault')}</div>
        {card.screenshot_path && <div className="image-box"><img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /></div>}
        <div className="original">{card.sentence}</div>
      </div>
    </div>
  </div>
);

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  极简沉浸主题卡片组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const MinimalSentenceFront = ({ card, videoFile }: CardComponentProps) => (
  <div className="anki-card">
    {card.screenshot_path ? (
      <div className="bg-image" style={{ backgroundImage: `url(${card.screenshot_path})` }} />
    ) : videoFile ? (
      <div className="bg-image"><Placeholder videoFile={videoFile} timestamp={card.start_sec} /></div>
    ) : null}
    <div className="container">
      <div className="image-box" />
    </div>
  </div>
);

const MinimalSentenceBack = ({ card, videoFile }: CardComponentProps) => (
  <div className="anki-card">
    {card.screenshot_path ? (
      <div className="bg-image" style={{ backgroundImage: `url(${card.screenshot_path})` }} />
    ) : videoFile ? (
      <div className="bg-image"><Placeholder videoFile={videoFile} timestamp={card.start_sec} /></div>
    ) : null}
    <div className="container">
      <div className="original">{card.sentence}</div>
      <div className="divider" />
      {card.translation && <div className="translation">{card.translation}</div>}
      {card.notes && <div className="notes">{card.notes}</div>}
    </div>
  </div>
);

const MinimalVocabFront = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="target-word">{card.word || card.sentence}</div>
      <div className="hint">{i18n.t('ankiCard.vocabHintMinimal')}</div>
    </div>
  </div>
);

const MinimalVocabBack = ({ card, videoFile }: CardComponentProps) => (
  <div className="anki-card">
    <div className="container">
      <div className="target-word">{card.word || card.sentence}</div>
      {card.definition && <div className="word-meaning">{card.definition}</div>}
      <div className="divider" />
      <div className="example-box">
        <div className="tag">{i18n.t('ankiCard.exampleTagMinimal')}</div>
        {card.screenshot_path ? (
          <div className="image-box"><img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /></div>
        ) : videoFile ? (
          <Placeholder videoFile={videoFile} timestamp={card.start_sec} />
        ) : null}
        <div className="original">{card.sentence}</div>
      </div>
    </div>
  </div>
);

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Netflix 剧照主题卡片组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const NetflixSentenceFront = ({ card, videoFile }: { card: ProcessedCard; videoFile?: File }) => (
  <div className="anki-card">
    <div className="container">
      <div className="image-box">
        {card.screenshot_path ? <img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /> : <Placeholder dark videoFile={videoFile} timestamp={card.start_sec} />}
      </div>
    </div>
  </div>
);

const NetflixSentenceBack = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="image-box">{card.screenshot_path && <img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} />}</div>
      <div className="original">{card.sentence}</div>
      {card.translation && <div className="translation">{card.translation}</div>}
      {card.notes && <div className="notes">{card.notes}</div>}
      <div className="progress-bar" />
    </div>
  </div>
);

const NetflixVocabFront = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="target-word">{card.word || card.sentence}</div>
      <div className="hint">{i18n.t('ankiCard.vocabHintNetflix')}</div>
    </div>
  </div>
);

const NetflixVocabBack = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="target-word">{card.word || card.sentence}</div>
      {card.definition && <div className="word-meaning">{card.definition}</div>}
      <div className="example-box">
        <div className="tag">{i18n.t('ankiCard.exampleTagNetflix')}</div>
        {card.screenshot_path && <div className="image-box"><img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /></div>}
        <div className="original">{card.sentence}</div>
      </div>
      <div className="progress-bar" />
    </div>
  </div>
);

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  硬核词典主题卡片组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DictSentenceFront = ({ card: _card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="section-label">{i18n.t('ankiCard.sentenceLabel')}</div>
      <div className="original" style={{ textAlign: 'center' }}>{i18n.t('ankiCard.listenAndRecall')}</div>
    </div>
  </div>
);

const DictSentenceBack = ({ card, videoFile }: CardComponentProps) => (
  <div className="anki-card">
    <div className="container clearfix">
      <div className="section-label">{i18n.t('ankiCard.sentenceLabel')}</div>
      <div className="thumb">
        {card.screenshot_path ? <img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /> : <Placeholder videoFile={videoFile} timestamp={card.start_sec} />}
      </div>
      <div className="original">{card.sentence}</div>
      {card.translation && <><div className="section-label">{i18n.t('ankiCard.translationLabel')}</div><div className="translation">{card.translation}</div></>}
      {card.notes && <><div className="section-label">{i18n.t('ankiCard.notesLabel')}</div><div className="notes">{card.notes}</div></>}
      <hr className="dict-divider" />
    </div>
  </div>
);

const DictVocabFront = ({ card }: { card: ProcessedCard }) => (
  <div className="anki-card">
    <div className="container">
      <div className="section-label">{i18n.t('ankiCard.entryLabel')}</div>
      <div><span className="headword">{card.word || card.sentence}</span></div>
      <div className="hint">{i18n.t('ankiCard.vocabHintDictionary')}</div>
    </div>
  </div>
);

const DictVocabBack = ({ card, videoFile }: CardComponentProps) => (
  <div className="anki-card">
    <div className="container clearfix">
      <div className="section-label">{i18n.t('ankiCard.entryLabel')}</div>
      <div className="thumb">
        {card.screenshot_path ? <img src={card.screenshot_path} alt={i18n.t('cardPreview.screenshot')} /> : <Placeholder videoFile={videoFile} timestamp={card.start_sec} />}
      </div>
      <div><span className="headword">{card.word || card.sentence}</span></div>
      {card.definition && <div className="word-meaning">{card.definition}</div>}
      <hr className="dict-divider" />
      <div className="section-label">{i18n.t('ankiCard.exampleLabel')}</div>
      <div className="example-box">
        <div className="tag">{i18n.t('ankiCard.usageTag')}</div>
        <div className="original">{card.sentence}</div>
      </div>
      {card.translation && <><div className="section-label">{i18n.t('ankiCard.translationLabel')}</div><div className="translation">{card.translation}</div></>}
      {card.notes && <><div className="section-label">{i18n.t('ankiCard.notesLabel')}</div><div className="notes">{card.notes}</div></>}
    </div>
  </div>
);

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  组件注册表
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type CardComponentProps = { card: ProcessedCard; videoFile?: File };

const THEME_COMPONENTS: Record<string, {
  sentence: { front: React.FC<CardComponentProps>; back: React.FC<CardComponentProps> };
  vocab: { front: React.FC<CardComponentProps>; back: React.FC<CardComponentProps> };
}> = {
  default: {
    sentence: { front: DefaultSentenceFront, back: DefaultSentenceBack },
    vocab: { front: DefaultVocabFront, back: DefaultVocabBack },
  },
  minimal: {
    sentence: { front: MinimalSentenceFront, back: MinimalSentenceBack },
    vocab: { front: MinimalVocabFront, back: MinimalVocabBack },
  },
  netflix: {
    sentence: { front: NetflixSentenceFront, back: NetflixSentenceBack },
    vocab: { front: NetflixVocabFront, back: NetflixVocabBack },
  },
  dictionary: {
    sentence: { front: DictSentenceFront, back: DictSentenceBack },
    vocab: { front: DictVocabFront, back: DictVocabBack },
  },
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  视频帧截取组件（客户端实时截帧，用于处理前预览）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const VideoFrame = ({ file, timestamp }: { file: File; timestamp: number }) => {
  const [dataUrl, setDataUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const urlRef = useRef('');

  useEffect(() => {
    let cancelled = false;
    urlRef.current = URL.createObjectURL(file);

    const video = document.createElement('video');
    video.preload = 'metadata';
    video.muted = true;
    video.playsInline = true;
    video.crossOrigin = 'anonymous';

    video.onloadedmetadata = () => {
      if (cancelled) return;
      video.currentTime = Math.max(0, timestamp - 0.1);
    };

    video.onseeked = () => {
      if (cancelled) return;
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 360;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      }
      setDataUrl(canvas.toDataURL('image/jpeg', 0.85));
      setLoading(false);
      URL.revokeObjectURL(urlRef.current);
    };

    video.onerror = () => {
      if (!cancelled) {
        setError(true);
        setLoading(false);
        URL.revokeObjectURL(urlRef.current);
      }
    };

    video.src = urlRef.current;

    return () => {
      cancelled = true;
      video.removeAttribute('src');
      video.load();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [file, timestamp]);

  if (loading) {
    return (
      <div className="flex items-center justify-center w-full h-40 bg-gray-100 dark:bg-gray-800 rounded-lg">
        <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error || !dataUrl) {
    return (
      <div className="flex items-center justify-center w-full h-40 bg-gray-100 dark:bg-gray-800 rounded-lg">
        <span className="text-xs text-gray-400">...</span>
      </div>
    );
  }

  return <img src={dataUrl} alt="preview frame" className="w-full h-auto rounded-lg" />;
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  占位组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const PLACEHOLDER_IMG = '/docs/演示图片.png';

const Placeholder = ({ dark, videoFile, timestamp }: { dark?: boolean; videoFile?: File; timestamp?: number }) => {
  if (videoFile && timestamp !== undefined) {
    return (
      <div className="w-full rounded-lg overflow-hidden">
        <VideoFrame file={videoFile} timestamp={timestamp} />
      </div>
    );
  }

  return (
    <div className={`flex items-center justify-center w-full rounded-lg overflow-hidden ${dark ? 'bg-gray-800' : 'bg-gray-200'}`}>
      <img src={PLACEHOLDER_IMG} alt="demo" className="w-full h-auto" />
    </div>
  );
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  自定义主题 iframe 面板
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface CustomThemeFiles {
  front: string;
  back: string;
  css: string;
  label: string;
}

/** 将 Anki 模板变量替换为卡片数据（含条件处理） */
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

  // 条件块：{{#Field}}...{{/Field}}
  for (const [field, value] of Object.entries(fields)) {
    const re = new RegExp(`{{#${field}}}([\\s\\S]*?){{/${field}}}`, 'g');
    html = html.replace(re, value ? '$1' : '');
  }

  // 反向条件块：{{^Field}}...{{/Field}}
  for (const [field, value] of Object.entries(fields)) {
    const re = new RegExp(`{{\\^${field}}}([\\s\\S]*?){{/${field}}}`, 'g');
    html = html.replace(re, value ? '' : '$1');
  }

  // 简单变量替换
  for (const [field, value] of Object.entries(fields)) {
    html = html.replace(new RegExp(`{{${field}}}`, 'g'), value);
  }

  return html;
}

const CustomThemePane = ({
  theme,
  card,
  showAnswer,
}: {
  theme: string;
  card: ProcessedCard;
  showAnswer: boolean;
}) => {
  const [files, setFiles] = useState<CustomThemeFiles | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    fetch(`/api/themes/custom/${theme}`)
      .then(r => {
        if (!r.ok) throw new Error('Theme not found');
        return r.json();
      })
      .then(data => {
        setFiles(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [theme]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error || !files) {
    return (
      <div className="text-center py-8 text-sm text-red-500">
        {error || 'Failed to load theme'}
      </div>
    );
  }

  const filledTpl = renderTemplate(showAnswer ? files.back : files.front, card);
  const html = `<!DOCTYPE html><html><head><style>${files.css}</style></head><body>${filledTpl}</body></html>`;

  return (
    <iframe
      srcDoc={html}
      sandbox="allow-scripts"
      className="w-full min-h-[300px] border-0"
      title="Custom Theme Preview"
    />
  );
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export const CardPreview = ({ cards, cardStyles, currentIndex, onPrevious, onNext, theme = 'default', themeOverrides, videoFile }: CardPreviewProps) => {
  const { t } = useTranslation();
  const [isPlaying, setIsPlaying] = useState(false);
  const [previewStyle, setPreviewStyle] = useState<string>(cardStyles[0] || 'sentence');
  const [showAnswer, setShowAnswer] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  const isCustomTheme = theme !== 'default' && theme !== 'minimal' && theme !== 'netflix' && theme !== 'dictionary';

  if (cards.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        {t('cardPreview.noCards')}
      </div>
    );
  }

  const card = cards[currentIndex];
  const themeComponents = THEME_COMPONENTS[theme] || THEME_COMPONENTS.default;
  const themeCss = THEMES_CSS[theme] || THEMES_CSS.default;
  const css = themeOverrides && Object.keys(themeOverrides).length > 0
    ? buildOverrideCss(themeCss, themeOverrides)
    : themeCss;

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

  const styleComponents = themeComponents[previewStyle as keyof typeof themeComponents] || themeComponents.sentence;
  const FrontComponent = styleComponents.front;
  const BackComponent = styleComponents.back;

  return (
    <div className="space-y-4">
      <style>{css}</style>

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

      {/* 卡片：正面 → 翻转 → 背面 */}
      <div className="border-2 border-dashed border-gray-300 rounded-lg overflow-hidden dark:border-gray-600">
        {isCustomTheme ? (
          <CustomThemePane theme={theme} card={card} showAnswer={showAnswer} />
        ) : showAnswer ? (
          <BackComponent card={card} videoFile={videoFile} />
        ) : (
          <FrontComponent card={card} videoFile={videoFile} />
        )}
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
