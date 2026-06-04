import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, Bot, Check, Clock, Download, FileText, Film, GripHorizontal, Maximize2, Mic, Minimize2, Monitor, Moon, Pause, Play, Plus, Settings, Sun, Trash2, X } from 'lucide-react';
import { Button } from './components/Button';
import { ProgressBar } from './components/ProgressBar';
import { Card, CardContent, CardHeader, CardTitle } from './components/Card';
import { AnkiSyncButton } from './components/AnkiSyncButton';
import { subtitleAPI, processAPI, API_BASE_URL } from './services/api';
import type { AnnotationPurpose, ASREngine, ASREngineInfo, ProcessedCard, ProgressState, SubtitleItem } from './types';
import { toast } from './utils/toast';
import { getApiErrorMessage } from './utils/errors';
import { cn } from './utils/cn';
import { useTheme } from './hooks/useTheme';

type QueueStatus = 'captured' | 'annotating' | 'annotated' | 'media_processing' | 'ready' | 'error';

type CaptureDraft = {
  id: string;
  captureTaskId?: string;
  subtitleIndex: number;
  start_sec: number;
  end_sec: number;
  text: string;
  translation?: string;
  notes?: string;
  word?: string;
  definition?: string;
  audio_path?: string;
  screenshot_path?: string;
  audio_url?: string;
  screenshot_url?: string;
  video_name?: string;
  status: QueueStatus;
};

type AIConfig = {
  apiKey?: string;
  apiBase?: string;
  modelName?: string;
  aiConcurrency?: number;
  sourceLanguage?: string;
  targetLanguage?: string;
  annotationPrompt?: string;
};

type AnnotateItem = {
  index: number;
  translation?: string;
  notes?: string;
  word?: string;
  definition?: string;
};

type PlayerLanguage = 'zh' | 'en';

type PlayerCopy = {
  status: Record<QueueStatus, string>;
  playerTitle: string;
  returnMain: string;
  videoFile: string;
  subtitleFile: string;
  extractEmbedded: string;
  asrTranscribe: string;
  retranscribe: string;
  asrEngine: string;
  bcutEngine: string;
  unavailableSuffix: string;
  playerSettings: string;
  expandSettings: string;
  collapseSettings: string;
  captureSettings: string;
  pauseAfterCapture: string;
  cardStyle: string;
  sentenceCard: string;
  vocabCard: string;
  bothCards: string;
  cardTheme: string;
  defaultTheme: string;
  minimalTheme: string;
  dictionaryTheme: string;
  netflixTheme: string;
  showAnkiSync: string;
  fullscreenOverlays: string;
  whisperModel: string;
  sourceLanguage: string;
  autoDetect: string;
  asrUnavailableInline: string;
  audioCodecHint: string;
  compatiblePlaybackReady: string;
  preparingCompatiblePlayback: string;
  chooseVideo: string;
  play: string;
  pause: string;
  captureCurrent: string;
  shortcutHint: string;
  subtitleList: string;
  currentSubtitleLabel: string;
  subtitleEmpty: string;
  queueTitle: string;
  queueSourcePrefix: string;
  reselectVideoHint: string;
  mixedSources: string;
  freezeFailed: (message: string) => string;
  needMediaReady: string;
  grammarAnnotation: string;
  vocabAnnotation: string;
  originalText: string;
  translationLabel: string;
  notesLabel: string;
  wordLabel: string;
  definitionLabel: string;
  clear: string;
  remove: string;
  seekClip: string;
  queueEmpty: string;
  generateDeck: string;
  processingStatus: string;
  waitingProcess: string;
  task: string;
  downloadApkg: string;
  cardsGenerated: (count: number) => string;
  followSystem: string;
  lightMode: string;
  darkMode: string;
  fullscreen: string;
  exitFullscreen: string;
  fullscreenUnavailable: string;
  noSubtitleNearby: string;
  duplicateCapture: string;
  capturedToast: (text: string) => string;
  selectVideo: string;
  queueSourceMismatch: (name: string) => string;
  subtitlesLoaded: (count: number) => string;
  subtitleLoadFailed: (message: string) => string;
  noEmbedded: string;
  embeddedSource: (label: string) => string;
  embeddedExtracted: (count: number) => string;
  embeddedFailed: (message: string) => string;
  asrUnavailable: string;
  transcribePreparing: string;
  transcribing: string;
  asrSource: (count: number) => string;
  transcribed: (count: number) => string;
  transcribeFailed: (message: string) => string;
  needAIKey: string;
  annotateFailed: (message: string) => string;
  needCapture: string;
  processingStart: string;
  deckGenerated: (count: number) => string;
  processFailed: (message: string) => string;
  processError: string;
};

const PLAYER_COPY: Record<PlayerLanguage, PlayerCopy> = {
  zh: {
    status: {
      captured: '已捕获',
      annotating: '注释中',
      annotated: '已注释',
      media_processing: '制卡中',
      ready: '已生成',
      error: '失败',
    },
    playerTitle: 'ClipLingo 播放器模式',
    returnMain: '返回主界面',
    videoFile: '视频文件',
    subtitleFile: 'SRT 字幕文件',
    extractEmbedded: '提取内嵌字幕',
    asrTranscribe: 'ASR 转录',
    retranscribe: '重新生成',
    asrEngine: 'ASR 引擎',
    bcutEngine: '必剪 ASR',
    unavailableSuffix: '不可用',
    playerSettings: '播放器设置',
    expandSettings: '展开',
    collapseSettings: '收起',
    captureSettings: '捕获设置',
    pauseAfterCapture: '捕获后暂停视频',
    cardStyle: '卡片样式',
    sentenceCard: '句子卡',
    vocabCard: '词汇卡',
    bothCards: '句子 + 词汇',
    cardTheme: '卡片主题',
    defaultTheme: '默认',
    minimalTheme: '极简',
    dictionaryTheme: '词典',
    netflixTheme: 'Netflix',
    showAnkiSync: '显示 AnkiConnect 同步',
    fullscreenOverlays: '全屏覆盖层',
    whisperModel: 'Whisper 模型',
    sourceLanguage: '源语言',
    autoDetect: '自动检测',
    asrUnavailableInline: '当前 ASR 引擎不可用，请切换引擎或检查后端依赖。',
    audioCodecHint: 'Chrome 无声通常是音轨编码不兼容导致的，例如 AC3、EAC3、DTS。ClipLingo 会自动准备 MP4/AAC 兼容播放源；捕获截图和音频仍使用原视频。',
    compatiblePlaybackReady: '已切换到 MP4/AAC 兼容播放源',
    preparingCompatiblePlayback: '正在准备 Chrome 兼容播放源...',
    chooseVideo: '选择视频后开始播放',
    play: '播放',
    pause: '暂停',
    captureCurrent: '捕获当前句',
    shortcutHint: 'Space 播放/暂停 · S 捕获 · ↑/↓ 切换句子',
    subtitleList: '字幕列表',
    currentSubtitleLabel: '当前字幕',
    subtitleEmpty: '加载 SRT 后显示字幕',
    queueTitle: '捕获队列',
    queueSourcePrefix: '来源视频',
    reselectVideoHint: '生成前需重新选择视频',
    mixedSources: '多个视频',
    freezeFailed: (message) => `媒体捕获失败: ${message}`,
    needMediaReady: '请等待媒体捕获完成，或移除失败的句子',
    grammarAnnotation: '语法注释',
    vocabAnnotation: '词汇注释',
    originalText: '原文',
    translationLabel: '翻译',
    notesLabel: '注释',
    wordLabel: '词条',
    definitionLabel: '释义',
    clear: '清空',
    remove: '移除',
    seekClip: '跳到片段',
    queueEmpty: '播放时按 S 捕获当前字幕',
    generateDeck: '生成 Anki 牌组',
    processingStatus: '制卡状态',
    waitingProcess: '等待处理',
    task: 'Task',
    downloadApkg: '下载 .apkg',
    cardsGenerated: (count) => `已生成 ${count} 张卡片`,
    followSystem: '跟随系统',
    lightMode: '浅色模式',
    darkMode: '深色模式',
    fullscreen: '全屏',
    exitFullscreen: '退出全屏',
    fullscreenUnavailable: '当前浏览器不支持应用全屏',
    noSubtitleNearby: '附近没有可捕获的字幕',
    duplicateCapture: '这句已经在捕获队列中',
    capturedToast: (text) => `已捕获：${text}`,
    selectVideo: '请先选择视频',
    queueSourceMismatch: (name) => `当前队列来源为 ${name}，请确认选择的视频匹配`,
    subtitlesLoaded: (count) => `已加载 ${count} 条字幕`,
    subtitleLoadFailed: (message) => `字幕加载失败: ${message}`,
    noEmbedded: '没有找到可提取的内嵌字幕',
    embeddedSource: (label) => `内嵌字幕 ${label}`,
    embeddedExtracted: (count) => `已提取 ${count} 条内嵌字幕`,
    embeddedFailed: (message) => `提取内嵌字幕失败: ${message}`,
    asrUnavailable: '当前 ASR 引擎不可用，请切换引擎或检查后端环境',
    transcribePreparing: '准备转录...',
    transcribing: '转录中...',
    asrSource: (count) => `ASR 转录 ${count} 条`,
    transcribed: (count) => `已转录 ${count} 条字幕`,
    transcribeFailed: (message) => `转录失败: ${message}`,
    needAIKey: '请先在主界面配置 AI API Key',
    annotateFailed: (message) => `AI 注释失败: ${message}`,
    needCapture: '请先捕获字幕',
    processingStart: '开始处理捕获队列...',
    deckGenerated: (count) => `已生成 ${count} 张卡片`,
    processFailed: (message) => `制卡失败: ${message}`,
    processError: '处理失败',
  },
  en: {
    status: {
      captured: 'Captured',
      annotating: 'Annotating',
      annotated: 'Annotated',
      media_processing: 'Building',
      ready: 'Ready',
      error: 'Failed',
    },
    playerTitle: 'ClipLingo Player Mode',
    returnMain: 'Back to Main',
    videoFile: 'Video file',
    subtitleFile: 'SRT subtitle file',
    extractEmbedded: 'Extract embedded subs',
    asrTranscribe: 'ASR transcribe',
    retranscribe: 'Regenerate',
    asrEngine: 'ASR engine',
    bcutEngine: 'Bcut ASR',
    unavailableSuffix: 'unavailable',
    playerSettings: 'Player settings',
    expandSettings: 'Expand',
    collapseSettings: 'Collapse',
    captureSettings: 'Capture settings',
    pauseAfterCapture: 'Pause video after capture',
    cardStyle: 'Card style',
    sentenceCard: 'Sentence card',
    vocabCard: 'Vocabulary card',
    bothCards: 'Sentence + vocabulary',
    cardTheme: 'Card theme',
    defaultTheme: 'Default',
    minimalTheme: 'Minimal',
    dictionaryTheme: 'Dictionary',
    netflixTheme: 'Netflix',
    showAnkiSync: 'Show AnkiConnect sync',
    fullscreenOverlays: 'Fullscreen overlays',
    whisperModel: 'Whisper model',
    sourceLanguage: 'Source language',
    autoDetect: 'Auto detect',
    asrUnavailableInline: 'The selected ASR engine is unavailable. Switch engines or check backend dependencies.',
    audioCodecHint: 'No audio in Chrome is usually caused by unsupported audio codecs such as AC3, EAC3, or DTS. ClipLingo automatically prepares an MP4/AAC-compatible playback source; screenshots and clips still come from the original video.',
    compatiblePlaybackReady: 'Switched to MP4/AAC-compatible playback',
    preparingCompatiblePlayback: 'Preparing Chrome-compatible playback...',
    chooseVideo: 'Select a video to start playback',
    play: 'Play',
    pause: 'Pause',
    captureCurrent: 'Capture sentence',
    shortcutHint: 'Space play/pause · S capture · ↑/↓ switch sentence',
    subtitleList: 'Subtitles',
    currentSubtitleLabel: 'Current subtitle',
    subtitleEmpty: 'Load an SRT file to show subtitles',
    queueTitle: 'Capture Queue',
    queueSourcePrefix: 'Source video',
    reselectVideoHint: 'reselect the video before generating',
    mixedSources: 'Multiple videos',
    freezeFailed: (message) => `Media capture failed: ${message}`,
    needMediaReady: 'Wait for media capture to finish, or remove failed sentences',
    grammarAnnotation: 'Grammar notes',
    vocabAnnotation: 'Vocabulary notes',
    originalText: 'Original',
    translationLabel: 'Translation',
    notesLabel: 'Notes',
    wordLabel: 'Word',
    definitionLabel: 'Definition',
    clear: 'Clear',
    remove: 'Remove',
    seekClip: 'Jump to clip',
    queueEmpty: 'Press S during playback to capture the current subtitle',
    generateDeck: 'Generate Anki deck',
    processingStatus: 'Build Status',
    waitingProcess: 'Waiting',
    task: 'Task',
    downloadApkg: 'Download .apkg',
    cardsGenerated: (count) => `${count} cards generated`,
    followSystem: 'Follow system',
    lightMode: 'Light mode',
    darkMode: 'Dark mode',
    fullscreen: 'Fullscreen',
    exitFullscreen: 'Exit fullscreen',
    fullscreenUnavailable: 'App fullscreen is unavailable in this browser',
    noSubtitleNearby: 'No capturable subtitle nearby',
    duplicateCapture: 'This sentence is already in the queue',
    capturedToast: (text) => `Captured: ${text}`,
    selectVideo: 'Select a video first',
    queueSourceMismatch: (name) => `The current queue is from ${name}. Make sure the selected video matches.`,
    subtitlesLoaded: (count) => `Loaded ${count} subtitles`,
    subtitleLoadFailed: (message) => `Failed to load subtitles: ${message}`,
    noEmbedded: 'No extractable embedded subtitles found',
    embeddedSource: (label) => `Embedded subtitles ${label}`,
    embeddedExtracted: (count) => `Extracted ${count} embedded subtitles`,
    embeddedFailed: (message) => `Failed to extract embedded subtitles: ${message}`,
    asrUnavailable: 'The selected ASR engine is unavailable. Switch engines or check the backend environment.',
    transcribePreparing: 'Preparing transcription...',
    transcribing: 'Transcribing...',
    asrSource: (count) => `ASR transcription ${count} subtitles`,
    transcribed: (count) => `Transcribed ${count} subtitles`,
    transcribeFailed: (message) => `Transcription failed: ${message}`,
    needAIKey: 'Configure the AI API key in the main screen first',
    annotateFailed: (message) => `AI annotation failed: ${message}`,
    needCapture: 'Capture subtitles first',
    processingStart: 'Processing capture queue...',
    deckGenerated: (count) => `Generated ${count} cards`,
    processFailed: (message) => `Deck generation failed: ${message}`,
    processError: 'Processing failed',
  },
};

const PLAYER_QUEUE_STORAGE_KEY = 'cliplingo_player_queue_v1';
const PLAYER_ASR_STORAGE_KEY = 'cliplingo_player_asr_v1';
const PLAYER_FULLSCREEN_OVERLAY_STORAGE_KEY = 'cliplingo_player_fullscreen_overlays_v1';
const PLAYER_SETTINGS_STORAGE_KEY = 'cliplingo_player_settings_v1';
const CAPTURE_GRACE_BEFORE_SEC = 0.35;
const CAPTURE_GRACE_AFTER_SEC = 1.5;
const LANGUAGE_CODES = ['en', 'zh', 'ja', 'ko', 'fr', 'de', 'es', 'it', 'pt', 'ru', 'ar', 'th', 'vi'] as const;
const WHISPER_MODELS = [
  { key: 'tiny', label: 'tiny', size: '~75 MB' },
  { key: 'base', label: 'base', size: '~145 MB' },
  { key: 'small', label: 'small', size: '~488 MB' },
  { key: 'medium', label: 'medium', size: '~1.5 GB' },
  { key: 'large', label: 'large', size: '~2.9 GB' },
] as const;
const CARD_THEME_KEYS = ['default', 'minimal', 'dictionary', 'netflix'] as const;

type WhisperModel = typeof WHISPER_MODELS[number]['key'];
type PlayerCardStyleSetting = 'sentence' | 'vocab' | 'both';
type PlayerCardThemeSetting = typeof CARD_THEME_KEYS[number];

type PlayerASRSettings = {
  asrEngine: ASREngine;
  whisperModel: WhisperModel;
  transcribeLanguage: string;
};

type PlayerSettings = {
  pauseAfterCapture: boolean;
  annotationPurpose: AnnotationPurpose;
  cardStyle: PlayerCardStyleSetting;
  cardTheme: PlayerCardThemeSetting;
  showAnkiSync: boolean;
  showFullscreenSubtitleList: boolean;
  showFullscreenCaption: boolean;
};

type PlayerQueueSnapshot = {
  version: 1;
  queue: CaptureDraft[];
  queueVideoName?: string;
  subtitleSource?: string;
  savedAt?: string;
};

type FloatingPanel = 'subtitleList' | 'currentSubtitle';

type OverlayPosition = {
  x: number;
  y: number;
};

type PlayerFullscreenOverlaySettings = {
  subtitleListPosition: OverlayPosition;
  currentSubtitlePosition: OverlayPosition;
  showSubtitleList: boolean;
  showCurrentSubtitle: boolean;
};

function loadAIConfig(): AIConfig {
  try {
    const raw = localStorage.getItem('anki_ai_config');
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function isASREngine(value: unknown): value is ASREngine {
  return value === 'faster_whisper' || value === 'bcut';
}

function isWhisperModel(value: unknown): value is WhisperModel {
  return WHISPER_MODELS.some((model) => model.key === value);
}

function isAnnotationPurpose(value: unknown): value is AnnotationPurpose {
  return value === 'grammar' || value === 'vocab';
}

function isPlayerCardStyle(value: unknown): value is PlayerCardStyleSetting {
  return value === 'sentence' || value === 'vocab' || value === 'both';
}

function isPlayerCardTheme(value: unknown): value is PlayerCardThemeSetting {
  return CARD_THEME_KEYS.some((theme) => theme === value);
}

function cardStylesFromSetting(setting: PlayerCardStyleSetting): string[] {
  if (setting === 'both') return ['sentence', 'vocab'];
  return [setting];
}

function loadPlayerASRSettings(defaultLanguage?: string): PlayerASRSettings {
  try {
    const raw = localStorage.getItem(PLAYER_ASR_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) as Partial<PlayerASRSettings> : {};
    return {
      asrEngine: isASREngine(parsed.asrEngine) ? parsed.asrEngine : 'faster_whisper',
      whisperModel: isWhisperModel(parsed.whisperModel) ? parsed.whisperModel : 'base',
      transcribeLanguage: typeof parsed.transcribeLanguage === 'string'
        ? parsed.transcribeLanguage
        : (defaultLanguage || ''),
    };
  } catch {
    return {
      asrEngine: 'faster_whisper',
      whisperModel: 'base',
      transcribeLanguage: defaultLanguage || '',
    };
  }
}

function loadPlayerSettings(overlaySettings: PlayerFullscreenOverlaySettings): PlayerSettings {
  const defaults: PlayerSettings = {
    pauseAfterCapture: false,
    annotationPurpose: 'grammar',
    cardStyle: 'sentence',
    cardTheme: 'default',
    showAnkiSync: true,
    showFullscreenSubtitleList: overlaySettings.showSubtitleList,
    showFullscreenCaption: overlaySettings.showCurrentSubtitle,
  };

  try {
    const raw = localStorage.getItem(PLAYER_SETTINGS_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<PlayerSettings>;
    return {
      pauseAfterCapture: typeof parsed.pauseAfterCapture === 'boolean' ? parsed.pauseAfterCapture : defaults.pauseAfterCapture,
      annotationPurpose: isAnnotationPurpose(parsed.annotationPurpose) ? parsed.annotationPurpose : defaults.annotationPurpose,
      cardStyle: isPlayerCardStyle(parsed.cardStyle) ? parsed.cardStyle : defaults.cardStyle,
      cardTheme: isPlayerCardTheme(parsed.cardTheme) ? parsed.cardTheme : defaults.cardTheme,
      showAnkiSync: typeof parsed.showAnkiSync === 'boolean' ? parsed.showAnkiSync : defaults.showAnkiSync,
      showFullscreenSubtitleList: typeof parsed.showFullscreenSubtitleList === 'boolean' ? parsed.showFullscreenSubtitleList : defaults.showFullscreenSubtitleList,
      showFullscreenCaption: typeof parsed.showFullscreenCaption === 'boolean' ? parsed.showFullscreenCaption : defaults.showFullscreenCaption,
    };
  } catch {
    return defaults;
  }
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function getCapturableSubtitle(subtitles: SubtitleItem[], time: number): SubtitleItem | null {
  const current = subtitles.find((s) => time >= s.start_sec && time <= s.end_sec);
  if (current) return current;

  const recentPrevious = [...subtitles]
    .reverse()
    .find((s) => time > s.end_sec && time <= s.end_sec + CAPTURE_GRACE_AFTER_SEC);
  if (recentPrevious) return recentPrevious;

  return subtitles.find((s) => time < s.start_sec && time >= s.start_sec - CAPTURE_GRACE_BEFORE_SEC) || null;
}

function getPersistentSubtitle(subtitles: SubtitleItem[], time: number): SubtitleItem | null {
  const current = subtitles.find((s) => time >= s.start_sec && time <= s.end_sec);
  if (current) return current;

  return [...subtitles].reverse().find((s) => time > s.end_sec) || null;
}

function previewText(text: string): string {
  return text.length > 28 ? `${text.slice(0, 28)}...` : text;
}

function getPlayerLanguage(language: string): PlayerLanguage {
  return language.startsWith('en') ? 'en' : 'zh';
}

function toSubtitleItem(item: CaptureDraft, index: number): SubtitleItem {
  return {
    index: index + 1,
    start_sec: item.start_sec,
    end_sec: item.end_sec,
    duration: item.end_sec - item.start_sec,
    text: item.text,
  };
}

function statusLabel(status: QueueStatus, text: PlayerCopy): string {
  return text.status[status];
}

function revokeObjectUrl(url: string) {
  if (url.startsWith('blob:')) URL.revokeObjectURL(url);
}

function isQueueStatus(value: unknown): value is QueueStatus {
  return value === 'captured'
    || value === 'annotating'
    || value === 'annotated'
    || value === 'media_processing'
    || value === 'ready'
    || value === 'error';
}

function restoreQueueStatus(item: CaptureDraft): QueueStatus {
  if (item.status === 'annotating' || item.status === 'media_processing' || item.status === 'ready') {
    if (!item.audio_path || !item.screenshot_path) return 'error';
    return item.translation || item.notes || item.word || item.definition ? 'annotated' : 'captured';
  }
  return item.status;
}

function restoreCaptureDraft(value: unknown, fallbackIndex: number): CaptureDraft | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Partial<CaptureDraft>;
  if (
    typeof item.text !== 'string'
    || typeof item.start_sec !== 'number'
    || typeof item.end_sec !== 'number'
    || !Number.isFinite(item.start_sec)
    || !Number.isFinite(item.end_sec)
  ) {
    return null;
  }

  const subtitleIndex = typeof item.subtitleIndex === 'number' && Number.isFinite(item.subtitleIndex)
    ? item.subtitleIndex
    : fallbackIndex + 1;
  const status = isQueueStatus(item.status) ? restoreQueueStatus(item as CaptureDraft) : 'captured';

  return {
    id: typeof item.id === 'string' && item.id ? item.id : `${subtitleIndex}-${item.start_sec}`,
    subtitleIndex,
    start_sec: item.start_sec,
    end_sec: item.end_sec,
    text: item.text,
    translation: typeof item.translation === 'string' ? item.translation : undefined,
    notes: typeof item.notes === 'string' ? item.notes : undefined,
    word: typeof item.word === 'string' ? item.word : undefined,
    definition: typeof item.definition === 'string' ? item.definition : undefined,
    captureTaskId: typeof item.captureTaskId === 'string' ? item.captureTaskId : undefined,
    audio_path: typeof item.audio_path === 'string' ? item.audio_path : undefined,
    screenshot_path: typeof item.screenshot_path === 'string' ? item.screenshot_path : undefined,
    audio_url: typeof item.audio_url === 'string' ? item.audio_url : undefined,
    screenshot_url: typeof item.screenshot_url === 'string' ? item.screenshot_url : undefined,
    video_name: typeof item.video_name === 'string' ? item.video_name : undefined,
    status,
  };
}

function loadPlayerQueueSnapshot(): PlayerQueueSnapshot | null {
  try {
    const raw = localStorage.getItem(PLAYER_QUEUE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PlayerQueueSnapshot>;
    const queue = Array.isArray(parsed.queue)
      ? parsed.queue.map(restoreCaptureDraft).filter((item): item is CaptureDraft => Boolean(item))
      : [];
    if (queue.length === 0) return null;

    return {
      version: 1,
      queue,
      queueVideoName: typeof parsed.queueVideoName === 'string' ? parsed.queueVideoName : undefined,
      subtitleSource: typeof parsed.subtitleSource === 'string' ? parsed.subtitleSource : undefined,
      savedAt: typeof parsed.savedAt === 'string' ? parsed.savedAt : undefined,
    };
  } catch {
    return null;
  }
}

function getDefaultOverlayPosition(panel: FloatingPanel): OverlayPosition {
  if (typeof window === 'undefined') {
    return panel === 'subtitleList' ? { x: 760, y: 64 } : { x: 320, y: 560 };
  }

  if (panel === 'subtitleList') {
    return {
      x: Math.max(12, window.innerWidth - 460),
      y: 64,
    };
  }

  return {
    x: Math.max(12, (window.innerWidth - Math.min(768, window.innerWidth - 24)) / 2),
    y: Math.max(80, window.innerHeight - 170),
  };
}

function clampOverlayPosition(position: OverlayPosition, panel: FloatingPanel): OverlayPosition {
  if (typeof window === 'undefined') return position;
  const width = panel === 'subtitleList' ? Math.min(448, window.innerWidth - 24) : Math.min(768, window.innerWidth - 24);
  const height = panel === 'subtitleList' ? Math.min(460, window.innerHeight - 96) : 96;

  return {
    x: Math.min(Math.max(12, position.x), Math.max(12, window.innerWidth - width - 12)),
    y: Math.min(Math.max(12, position.y), Math.max(12, window.innerHeight - height - 12)),
  };
}

function restoreOverlayPosition(value: unknown, panel: FloatingPanel): OverlayPosition {
  if (!value || typeof value !== 'object') return getDefaultOverlayPosition(panel);
  const position = value as Partial<OverlayPosition>;
  if (
    typeof position.x !== 'number'
    || typeof position.y !== 'number'
    || !Number.isFinite(position.x)
    || !Number.isFinite(position.y)
  ) {
    return getDefaultOverlayPosition(panel);
  }
  return clampOverlayPosition({ x: position.x, y: position.y }, panel);
}

function loadPlayerFullscreenOverlaySettings(): PlayerFullscreenOverlaySettings {
  const defaults: PlayerFullscreenOverlaySettings = {
    subtitleListPosition: getDefaultOverlayPosition('subtitleList'),
    currentSubtitlePosition: getDefaultOverlayPosition('currentSubtitle'),
    showSubtitleList: true,
    showCurrentSubtitle: true,
  };

  try {
    const raw = localStorage.getItem(PLAYER_FULLSCREEN_OVERLAY_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<PlayerFullscreenOverlaySettings>;
    return {
      subtitleListPosition: restoreOverlayPosition(parsed.subtitleListPosition, 'subtitleList'),
      currentSubtitlePosition: restoreOverlayPosition(parsed.currentSubtitlePosition, 'currentSubtitle'),
      showSubtitleList: typeof parsed.showSubtitleList === 'boolean' ? parsed.showSubtitleList : defaults.showSubtitleList,
      showCurrentSubtitle: typeof parsed.showCurrentSubtitle === 'boolean' ? parsed.showCurrentSubtitle : defaults.showCurrentSubtitle,
    };
  } catch {
    return defaults;
  }
}

export default function PlayerMode() {
  const { i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const language = getPlayerLanguage(i18n.language);
  const text = PLAYER_COPY[language];
  const [restoredSnapshot] = useState(loadPlayerQueueSnapshot);
  const [initialASRSettings] = useState(() => loadPlayerASRSettings(loadAIConfig().sourceLanguage));
  const [initialOverlaySettings] = useState(loadPlayerFullscreenOverlaySettings);
  const [initialPlayerSettings] = useState(() => loadPlayerSettings(initialOverlaySettings));
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoSessionId, setVideoSessionId] = useState('');
  const [videoUrl, setVideoUrl] = useState('');
  const [playbackSource, setPlaybackSource] = useState<'local' | 'preparing' | 'compatible'>('local');
  const [subtitleFile, setSubtitleFile] = useState<File | null>(null);
  const [subtitleSource, setSubtitleSource] = useState(restoredSnapshot?.subtitleSource || '');
  const [subtitles, setSubtitles] = useState<SubtitleItem[]>([]);
  const [queue, setQueue] = useState<CaptureDraft[]>(() => restoredSnapshot?.queue || []);
  const [queueVideoName, setQueueVideoName] = useState(restoredSnapshot?.queueVideoName || '');
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isAnnotating, setIsAnnotating] = useState(false);
  const [isExtractingEmbedded, setIsExtractingEmbedded] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcribeMessage, setTranscribeMessage] = useState('');
  const [transcribeProgress, setTranscribeProgress] = useState<ProgressState>({
    mode: 'indeterminate',
    message: '',
  });
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');
  const [processingProgress, setProcessingProgress] = useState<ProgressState>({
    mode: 'indeterminate',
    message: '',
  });
  const [taskId, setTaskId] = useState<string | null>(null);
  const [apkgUrl, setApkgUrl] = useState<string | null>(null);
  const [cards, setCards] = useState<ProcessedCard[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [pauseAfterCapture, setPauseAfterCapture] = useState(initialPlayerSettings.pauseAfterCapture);
  const [annotationPurpose, setAnnotationPurpose] = useState<AnnotationPurpose>(initialPlayerSettings.annotationPurpose);
  const [playerCardStyle, setPlayerCardStyle] = useState<PlayerCardStyleSetting>(initialPlayerSettings.cardStyle);
  const [playerCardTheme, setPlayerCardTheme] = useState<PlayerCardThemeSetting>(initialPlayerSettings.cardTheme);
  const [showAnkiSync, setShowAnkiSync] = useState(initialPlayerSettings.showAnkiSync);
  const [asrEngine, setAsrEngine] = useState<ASREngine>(initialASRSettings.asrEngine);
  const [whisperModel, setWhisperModel] = useState<WhisperModel>(initialASRSettings.whisperModel);
  const [transcribeLanguage, setTranscribeLanguage] = useState(initialASRSettings.transcribeLanguage);
  const [asrEngines, setAsrEngines] = useState<ASREngineInfo[]>([]);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenNotice, setFullscreenNotice] = useState('');
  const [showFullscreenSubtitleList, setShowFullscreenSubtitleList] = useState(initialPlayerSettings.showFullscreenSubtitleList);
  const [showFullscreenCaption, setShowFullscreenCaption] = useState(initialPlayerSettings.showFullscreenCaption);
  const [subtitleListPosition, setSubtitleListPosition] = useState(initialOverlaySettings.subtitleListPosition);
  const [currentSubtitlePosition, setCurrentSubtitlePosition] = useState(initialOverlaySettings.currentSubtitlePosition);
  const playerShellRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const subtitleButtonRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
  const fullscreenNoticeTimerRef = useRef<number | null>(null);
  const videoSessionRequestRef = useRef(0);

  const capturableSubtitle = useMemo(() => {
    return getCapturableSubtitle(subtitles, currentTime);
  }, [currentTime, subtitles]);

  const displayedSubtitle = useMemo(() => {
    return getPersistentSubtitle(subtitles, currentTime);
  }, [currentTime, subtitles]);

  const activeSubtitleIndex = displayedSubtitle?.index || capturableSubtitle?.index || null;
  const capturedKeys = useMemo(() => new Set(queue.map((item) => `${item.video_name || queueVideoName}:${item.subtitleIndex}`)), [queue, queueVideoName]);
  const queueSourceNames = useMemo(() => {
    const names: string[] = [];
    queue.forEach((item) => {
      const name = item.video_name || queueVideoName;
      if (name && !names.includes(name)) names.push(name);
    });
    return names;
  }, [queue, queueVideoName]);
  const queueSourceLabel = queueSourceNames.length > 1
    ? text.mixedSources
    : queueSourceNames[0] || queueVideoName;
  const queueHasPendingMedia = queue.some((item) => item.status === 'media_processing' || !item.audio_path || !item.screenshot_path);
  const selectedASREngine = useMemo(() => asrEngines.find((engine) => engine.id === asrEngine), [asrEngine, asrEngines]);
  const selectedEngineUnavailable = asrEngines.length > 0 && selectedASREngine?.available === false;
  const selectedCardStyles = useMemo(() => cardStylesFromSetting(playerCardStyle), [playerCardStyle]);
  const themeTitle = theme === 'system' ? text.followSystem : theme === 'light' ? text.lightMode : text.darkMode;

  const toggleLanguage = () => {
    const next = language === 'zh' ? 'en' : 'zh';
    void i18n.changeLanguage(next);
    localStorage.setItem('ui_language', next);
  };

  useEffect(() => {
    const heartbeatInterval = setInterval(() => {
      fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
    }, 30000);
    return () => clearInterval(heartbeatInterval);
  }, []);

  useEffect(() => {
    subtitleAPI.getASREngines()
      .then((result) => setAsrEngines(result.engines))
      .catch(() => setAsrEngines([]));
  }, []);

  useEffect(() => {
    return () => {
      if (videoUrl) revokeObjectUrl(videoUrl);
    };
  }, [videoUrl]);

  useEffect(() => {
    try {
      const settings: PlayerASRSettings = { asrEngine, whisperModel, transcribeLanguage };
      localStorage.setItem(PLAYER_ASR_STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // localStorage can fail in private mode; settings simply fall back to defaults.
    }
  }, [asrEngine, whisperModel, transcribeLanguage]);

  useEffect(() => {
    try {
      const settings: PlayerSettings = {
        pauseAfterCapture,
        annotationPurpose,
        cardStyle: playerCardStyle,
        cardTheme: playerCardTheme,
        showAnkiSync,
        showFullscreenSubtitleList,
        showFullscreenCaption,
      };
      localStorage.setItem(PLAYER_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Player preferences are non-critical; controls still work with in-memory state.
    }
  }, [
    pauseAfterCapture,
    annotationPurpose,
    playerCardStyle,
    playerCardTheme,
    showAnkiSync,
    showFullscreenSubtitleList,
    showFullscreenCaption,
  ]);

  useEffect(() => {
    try {
      if (queue.length === 0) {
        localStorage.removeItem(PLAYER_QUEUE_STORAGE_KEY);
        return;
      }

      const snapshot: PlayerQueueSnapshot = {
        version: 1,
        queue: queue.map((item) => ({ ...item, status: restoreQueueStatus(item) })),
        queueVideoName,
        subtitleSource,
        savedAt: new Date().toISOString(),
      };
      localStorage.setItem(PLAYER_QUEUE_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
      // localStorage can fail in private mode or when storage is full; queue still works in memory.
    }
  }, [queue, queueVideoName, subtitleSource]);

  useEffect(() => {
    try {
      const settings: PlayerFullscreenOverlaySettings = {
        subtitleListPosition,
        currentSubtitlePosition,
        showSubtitleList: showFullscreenSubtitleList,
        showCurrentSubtitle: showFullscreenCaption,
      };
      localStorage.setItem(PLAYER_FULLSCREEN_OVERLAY_STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Overlay preferences are non-critical; fullscreen still works with defaults.
    }
  }, [subtitleListPosition, currentSubtitlePosition, showFullscreenSubtitleList, showFullscreenCaption]);

  useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === playerShellRef.current);
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, []);

  useEffect(() => {
    if (!isFullscreen) return;
    setSubtitleListPosition((position) => clampOverlayPosition(position, 'subtitleList'));
    setCurrentSubtitlePosition((position) => clampOverlayPosition(position, 'currentSubtitle'));
  }, [isFullscreen]);

  useEffect(() => {
    return () => {
      if (fullscreenNoticeTimerRef.current) {
        window.clearTimeout(fullscreenNoticeTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!activeSubtitleIndex) return;
    subtitleButtonRefs.current.get(activeSubtitleIndex)?.scrollIntoView({
      block: 'center',
      behavior: 'smooth',
    });
  }, [activeSubtitleIndex, isFullscreen, showFullscreenSubtitleList]);

  const seekRelativeSubtitle = (direction: -1 | 1) => {
    if (subtitles.length === 0) return;

    const activeIndex = activeSubtitleIndex
      ? subtitles.findIndex((subtitle) => subtitle.index === activeSubtitleIndex)
      : -1;
    let targetIndex: number;

    if (activeIndex >= 0) {
      targetIndex = activeIndex + direction;
    } else {
      const nextSubtitleIndex = subtitles.findIndex((subtitle) => currentTime < subtitle.start_sec);
      const timelineIndex = nextSubtitleIndex >= 0 ? nextSubtitleIndex : subtitles.length;
      targetIndex = direction > 0 ? timelineIndex : timelineIndex - 1;
    }

    const target = subtitles[Math.min(subtitles.length - 1, Math.max(0, targetIndex))];
    if (target) seekToSubtitle(target);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.tagName === 'SELECT' || target?.isContentEditable) return;
      if (event.code === 'Space') {
        event.preventDefault();
        void togglePlay();
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        seekRelativeSubtitle(-1);
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        seekRelativeSubtitle(1);
      }
      if (event.key.toLowerCase() === 's') {
        event.preventDefault();
        captureCurrentSubtitle();
      }
      if (event.key.toLowerCase() === 'f') {
        event.preventDefault();
        toggleFullscreen();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  const handleVideoChange = (file: File | null) => {
    const requestId = videoSessionRequestRef.current + 1;
    videoSessionRequestRef.current = requestId;
    if (videoUrl) revokeObjectUrl(videoUrl);
    setVideoFile(file);
    setVideoSessionId('');
    setPlaybackSource(file ? 'preparing' : 'local');
    setVideoUrl(file ? URL.createObjectURL(file) : '');
    setCards([]);
    setTaskId(null);
    setApkgUrl(null);
    if (!file) return;

    if (queue.length === 0 || !queueVideoName) {
      setQueueVideoName(file.name);
    } else if (queueVideoName !== file.name) {
      toast.warning(text.queueSourceMismatch(queueVideoName));
    }

    void processAPI.createPlayerVideoSession(file)
      .then((session) => {
        if (videoSessionRequestRef.current !== requestId) return;
        if (session.video_name === file.name) {
          setVideoSessionId(session.session_id);
          if (session.playback_url) {
            const video = videoRef.current;
            const current = video?.currentTime || 0;
            const wasPlaying = Boolean(video && !video.paused);
            setVideoUrl((currentUrl) => {
              revokeObjectUrl(currentUrl);
              return `${API_BASE_URL}${session.playback_url}`;
            });
            setPlaybackSource('compatible');
            window.setTimeout(() => {
              const nextVideo = videoRef.current;
              if (!nextVideo) return;
              nextVideo.currentTime = current;
              if (wasPlaying) void nextVideo.play().catch(() => {});
            }, 0);
            toast(text.compatiblePlaybackReady);
          } else {
            setPlaybackSource('local');
          }
        }
      })
      .catch((error) => {
        if (videoSessionRequestRef.current !== requestId) return;
        setPlaybackSource('local');
        toast.error(text.freezeFailed(getApiErrorMessage(error)));
      });
  };

  const handleSubtitleChange = async (file: File | null) => {
    setSubtitleFile(file);
    setSubtitleSource(file?.name || '');
    setSubtitles([]);
    if (!file) return;

    try {
      const result = await subtitleAPI.upload(file, 0);
      setSubtitles(result.subtitles);
      toast(text.subtitlesLoaded(result.subtitles.length));
    } catch (error) {
      toast.error(text.subtitleLoadFailed(getApiErrorMessage(error)));
    }
  };

  const extractEmbeddedSubtitles = async () => {
    if (!videoFile) {
      toast.error(text.selectVideo);
      return;
    }

    setIsExtractingEmbedded(true);
    try {
      const result = await subtitleAPI.extractEmbeddedSubs(videoFile, 0, 0);
      if (!result.extracted || result.extracted.subtitles.length === 0) {
        toast.warning(result.message || text.noEmbedded);
        return;
      }

      setSubtitleFile(null);
      setSubtitleSource(text.embeddedSource(result.extracted.language || result.extracted.codec));
      setSubtitles(result.extracted.subtitles);
      toast(text.embeddedExtracted(result.extracted.subtitles.length));
    } catch (error) {
      toast.error(text.embeddedFailed(getApiErrorMessage(error)));
    } finally {
      setIsExtractingEmbedded(false);
    }
  };

  const transcribeVideo = async (forceTranscribe: boolean = false) => {
    if (!videoFile) {
      toast.error(text.selectVideo);
      return;
    }
    if (selectedEngineUnavailable) {
      toast.error(text.asrUnavailable);
      return;
    }

    setIsTranscribing(true);
    setTranscribeMessage(text.transcribePreparing);
    setTranscribeProgress({ mode: 'indeterminate', message: text.transcribePreparing });

    try {
      const started = await subtitleAPI.startTranscribe(
        videoFile,
        0,
        transcribeLanguage.trim() || undefined,
        asrEngine === 'faster_whisper' ? whisperModel : undefined,
        asrEngine,
        forceTranscribe
      );

      while (true) {
        const progress = await subtitleAPI.getTranscribeProgress(started.task_id);
        setTranscribeMessage(progress.message || text.transcribing);
        if (progress.whisper_progress) {
          const wp = progress.whisper_progress;
          const pct = Math.round(wp.progress * 100);
          setTranscribeProgress({
            mode: 'determinate',
            message: progress.message || text.transcribing,
            progress: pct,
            current: wp.transcribed_sec,
            total: wp.duration_sec,
            unit: 'seconds',
            detail: wp.text,
          });
        } else if (progress.cached) {
          setTranscribeProgress({
            mode: 'determinate',
            message: progress.message || text.transcribed(progress.result?.subtitles.length || 0),
            progress: 100,
          });
        } else {
          setTranscribeProgress({
            mode: 'indeterminate',
            message: progress.message || text.transcribing,
          });
        }

        if (progress.status === 'completed' && progress.result) {
          setSubtitleFile(null);
          setSubtitleSource(text.asrSource(progress.result.subtitles.length));
          setSubtitles(progress.result.subtitles);
          const completedMessage = progress.cached
            ? progress.message || text.transcribed(progress.result.subtitles.length)
            : text.transcribed(progress.result.subtitles.length);
          setTranscribeProgress({
            mode: 'determinate',
            message: completedMessage,
            progress: 100,
          });
          toast(completedMessage);
          return;
        }

        if (progress.status === 'error') {
          throw new Error(progress.error || text.transcribeFailed(''));
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (error) {
      toast.error(text.transcribeFailed(getApiErrorMessage(error)));
    } finally {
      setIsTranscribing(false);
    }
  };

  const togglePlay = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      await video.play();
    } else {
      video.pause();
    }
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => toast.error(text.fullscreenUnavailable));
      return;
    }

    const shell = playerShellRef.current;
    if (!shell || !document.fullscreenEnabled || !shell.isConnected) {
      toast.error(text.fullscreenUnavailable);
      return;
    }

    void shell.requestFullscreen().catch(() => toast.error(text.fullscreenUnavailable));
  };

  const showFullscreenNotice = (message: string) => {
    setFullscreenNotice(message);
    if (fullscreenNoticeTimerRef.current) {
      window.clearTimeout(fullscreenNoticeTimerRef.current);
    }
    fullscreenNoticeTimerRef.current = window.setTimeout(() => setFullscreenNotice(''), 1800);
  };

  const startOverlayDrag = (event: ReactPointerEvent<HTMLElement>, panel: FloatingPanel) => {
    if (event.button !== 0) return;
    event.preventDefault();

    const startX = event.clientX;
    const startY = event.clientY;
    const initial = panel === 'subtitleList' ? subtitleListPosition : currentSubtitlePosition;
    const updatePosition = panel === 'subtitleList' ? setSubtitleListPosition : setCurrentSubtitlePosition;

    const onPointerMove = (moveEvent: PointerEvent) => {
      updatePosition(clampOverlayPosition({
        x: initial.x + moveEvent.clientX - startX,
        y: initial.y + moveEvent.clientY - startY,
      }, panel));
    };

    const onPointerUp = () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  const seekToSubtitle = (subtitle: SubtitleItem) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = subtitle.start_sec;
    video.focus();
  };

  const captureSubtitle = (subtitle: SubtitleItem | null) => {
    if (!subtitle) {
      toast.warning(text.noSubtitleNearby);
      return;
    }
    if (!videoFile) {
      toast.error(text.selectVideo);
      return;
    }
    if (queue.some((item) => (item.video_name || queueVideoName) === videoFile.name && item.subtitleIndex === subtitle.index)) {
      toast.warning(text.duplicateCapture);
      return;
    }
    if (queue.length === 0 && videoFile.name) {
      setQueueVideoName(videoFile.name);
    }
    const captureId = `${videoFile.name}-${subtitle.index}-${subtitle.start_sec}`;
    setQueue((items) => {
      return [
        ...items,
        {
          id: captureId,
          subtitleIndex: subtitle.index,
          start_sec: subtitle.start_sec,
          end_sec: subtitle.end_sec,
          text: subtitle.text,
          video_name: videoFile.name,
          status: 'media_processing',
        },
      ];
    });
    if (pauseAfterCapture) {
      videoRef.current?.pause();
    }
    const message = text.capturedToast(previewText(subtitle.text));
    if (isFullscreen) {
      showFullscreenNotice(message);
    } else {
      toast(message);
    }

    void processAPI.freezePlayerCapture(videoSessionId ? null : videoFile, {
      subtitleIndex: subtitle.index,
      start_sec: subtitle.start_sec,
      end_sec: subtitle.end_sec,
      text: subtitle.text,
      videoSessionId: videoSessionId || undefined,
    }).then((result) => {
      setQueue((items) => items.map((item) => item.id === captureId ? {
        ...item,
        captureTaskId: result.task_id,
        audio_path: result.audio_path,
        screenshot_path: result.screenshot_path,
        audio_url: result.audio_url,
        screenshot_url: result.screenshot_url,
        video_name: result.video_name || videoFile.name,
        status: 'captured',
      } : item));
    }).catch((error) => {
      setQueue((items) => items.map((item) => item.id === captureId ? { ...item, status: 'error' } : item));
      toast.error(text.freezeFailed(getApiErrorMessage(error)));
    });
  };

  const captureCurrentSubtitle = () => captureSubtitle(capturableSubtitle);

  const removeFromQueue = (id: string) => {
    setQueue((items) => items.filter((item) => item.id !== id));
  };

  const updateQueueItem = (id: string, patch: Partial<Pick<CaptureDraft, 'text' | 'translation' | 'notes' | 'word' | 'definition'>>) => {
    setQueue((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item));
    setCards([]);
    setTaskId(null);
    setApkgUrl(null);
  };

  const seekToQueueItem = (item: CaptureDraft) => {
    seekToSubtitle(toSubtitleItem(item, Math.max(0, item.subtitleIndex - 1)));
  };

  const clearQueue = () => {
    setQueue([]);
    setQueueVideoName(videoFile?.name || '');
    setCards([]);
    setTaskId(null);
    setApkgUrl(null);
  };

  const annotateQueue = async () => {
    const aiConfig = loadAIConfig();
    if (!aiConfig.apiKey) {
      toast.error(text.needAIKey);
      return;
    }

    const targets = queue.filter((item) => (
      item.status === 'captured'
      || (item.status === 'error' && Boolean(item.audio_path && item.screenshot_path))
    ));
    if (targets.length === 0) return;

    setIsAnnotating(true);
    setQueue((items) => items.map((item) => targets.some((t) => t.id === item.id) ? { ...item, status: 'annotating' } : item));

    try {
      const subtitlesToAnnotate = targets.map(toSubtitleItem);
      for await (const event of subtitleAPI.startAnnotateStream(
        subtitlesToAnnotate,
        annotationPurpose,
        aiConfig.apiKey,
        aiConfig.annotationPrompt || undefined,
        30,
        aiConfig.aiConcurrency ?? 3,
        aiConfig.apiBase,
        aiConfig.modelName,
        aiConfig.sourceLanguage || 'en',
        aiConfig.targetLanguage || 'zh'
      )) {
        if (event.type === 'batch' && event.items) {
          const byIndex = new Map<number, AnnotateItem>();
          event.items.forEach((item) => byIndex.set(item.index, item as unknown as AnnotateItem));
          setQueue((items) => items.map((item) => {
            const targetIndex = targets.findIndex((target) => target.id === item.id);
            const rec = targetIndex >= 0 ? byIndex.get(targetIndex + 1) : undefined;
            return rec
              ? {
                  ...item,
                  translation: rec.translation || '',
                  notes: rec.notes || '',
                  word: rec.word || '',
                  definition: rec.definition || '',
                  status: 'annotated',
                }
              : item;
          }));
        }
        if (event.type === 'error') {
          throw new Error(event.message || text.annotateFailed(''));
        }
      }
    } catch (error) {
      setQueue((items) => items.map((item) => item.status === 'annotating' ? { ...item, status: 'error' } : item));
      toast.error(text.annotateFailed(getApiErrorMessage(error)));
    } finally {
      setIsAnnotating(false);
    }
  };

  const processQueue = async () => {
    if (queue.length === 0) {
      toast.error(text.needCapture);
      return;
    }
    if (queueHasPendingMedia) {
      toast.error(text.needMediaReady);
      return;
    }

    const ordered = [...queue];
    const frozenCaptures = ordered.map((item) => ({
      start_sec: item.start_sec,
      end_sec: item.end_sec,
      text: item.text,
      translation: item.translation || '',
      notes: item.notes || '',
      word: item.word || '',
      definition: item.definition || '',
      audio_path: item.audio_path || '',
      screenshot_path: item.screenshot_path || '',
      video_name: item.video_name || queueVideoName || 'ClipLingo Player',
    }));

    setIsProcessing(true);
    setProcessingProgress({ mode: 'indeterminate', message: text.processingStart });
    setProcessingMessage(text.processingStart);
    setQueue((items) => items.map((item) => ({ ...item, status: 'media_processing' })));

    try {
      const started = await processAPI.preparePlayerCaptures(frozenCaptures);
      setTaskId(started.task_id);

      await pollUntil(started.task_id, 'awaiting_styles');

      await processAPI.generateApkg(started.task_id, selectedCardStyles, playerCardTheme, '{}');
      const completed = await pollUntil(started.task_id, 'completed');
      const result = completed.result;
      setApkgUrl(result?.apkg_url || null);
      setCards(result?.cards || []);
      setQueue((items) => items.map((item) => ({ ...item, status: 'ready' })));
      toast(text.deckGenerated(result?.cards_count || ordered.length));
    } catch (error) {
      setQueue((items) => items.map((item) => item.status === 'media_processing' ? { ...item, status: 'error' } : item));
      toast.error(text.processFailed(getApiErrorMessage(error)));
    } finally {
      setIsProcessing(false);
    }
  };

  const pollUntil = async (id: string, targetStatus: 'awaiting_styles' | 'completed') => {
    while (true) {
      const progress = await processAPI.getProgress(id);
      setProcessingMessage(progress.message || '');
      const details = progress.details;
      const current = typeof details?.current === 'number' ? details.current : undefined;
      const total = typeof details?.total === 'number' ? details.total : undefined;
      if (typeof current === 'number' && typeof total === 'number' && total > 0) {
        setProcessingProgress({
          mode: 'determinate',
          message: progress.message || '',
          progress: Math.round((current / total) * 100),
          current,
          total,
          unit: details?.unit === 'items' ? 'items' : undefined,
        });
      } else {
        setProcessingProgress({
          mode: 'indeterminate',
          message: progress.message || '',
        });
      }
      if (progress.status === targetStatus) return progress;
      if (progress.status === 'error') throw new Error(progress.error || text.processError);
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  };

  const subtitleListCard = (
    <Card className={cn(
      isFullscreen && 'fixed z-30 hidden h-[min(52vh,460px)] w-[min(28rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-md border-white/10 bg-black/65 text-white shadow-2xl backdrop-blur dark:border-white/10 dark:bg-black/65 md:flex',
      isFullscreen && !showFullscreenSubtitleList && 'md:hidden'
    )}
    style={isFullscreen ? { left: subtitleListPosition.x, top: subtitleListPosition.y } : undefined}
    >
      <CardHeader
        className={cn(isFullscreen && 'shrink-0 cursor-move border-white/10 p-3 dark:border-white/10')}
        onPointerDown={isFullscreen ? (event) => startOverlayDrag(event, 'subtitleList') : undefined}
      >
        <CardTitle className={cn('flex items-center gap-2 text-base', isFullscreen && 'text-white')}>
          {isFullscreen ? <GripHorizontal className="h-4 w-4 text-gray-300" /> : <Clock className="h-4 w-4" />}
          {text.subtitleList}
          {(subtitleSource || subtitleFile) && (
            <span className="text-xs font-normal text-gray-400">{subtitleSource || subtitleFile?.name}</span>
          )}
          {isFullscreen && (
            <button
              type="button"
              className="ml-auto rounded p-1 text-gray-300 hover:bg-white/10 hover:text-white"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => setShowFullscreenSubtitleList(false)}
              title={text.remove}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className={cn(isFullscreen && 'min-h-0 flex-1 p-0')}>
        <div className={cn(
          'max-h-[420px] overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700',
          isFullscreen && 'h-full max-h-none rounded-none border-0'
        )}>
          {subtitles.map((subtitle) => {
            const active = activeSubtitleIndex === subtitle.index;
            const captured = capturedKeys.has(`${videoFile?.name || queueVideoName}:${subtitle.index}`);
            return (
              <button
                key={`${subtitle.index}-${subtitle.start_sec}`}
                ref={(node) => {
                  if (node) {
                    subtitleButtonRefs.current.set(subtitle.index, node);
                  } else {
                    subtitleButtonRefs.current.delete(subtitle.index);
                  }
                }}
                type="button"
                onClick={() => seekToSubtitle(subtitle)}
                onDoubleClick={() => captureSubtitle(subtitle)}
                className={cn(
                  'grid w-full grid-cols-[56px_minmax(0,1fr)_72px] gap-3 border-b border-gray-100 px-3 py-2 text-left text-sm transition-colors last:border-b-0 dark:border-gray-700',
                  active ? 'bg-primary-50 text-primary-900 dark:bg-primary-900/30 dark:text-primary-100' : 'hover:bg-gray-50 dark:hover:bg-gray-700',
                )}
              >
                <span className="text-xs text-gray-400">{formatTime(subtitle.start_sec)}</span>
                <span className="min-w-0">{subtitle.text}</span>
                <span className={cn('inline-flex items-center justify-end gap-1 text-xs', captured ? 'text-green-600 dark:text-green-400' : 'text-gray-400')}>
                  {captured && <Check className="h-3 w-3" />}
                  {captured ? text.status.captured : `${subtitle.duration.toFixed(1)}s`}
                </span>
              </button>
            );
          })}
          {subtitles.length === 0 && (
            <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
              {text.subtitleEmpty}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );

  const queueCard = (
    <Card className={cn(
      isFullscreen && 'flex h-full min-h-0 flex-col overflow-hidden rounded-md border-white/10 bg-black/65 text-white shadow-2xl backdrop-blur dark:border-white/10 dark:bg-black/65'
    )}>
      <CardHeader className={cn(isFullscreen && 'shrink-0 border-white/10 p-3 dark:border-white/10')}>
        <CardTitle className={cn('text-base', isFullscreen && 'text-white')}>{text.queueTitle} ({queue.length})</CardTitle>
      </CardHeader>
      <CardContent className={cn(
        'space-y-3',
        isFullscreen && 'flex min-h-0 flex-1 flex-col p-3'
      )}>
        {queueSourceLabel && (
          <div className={cn(
            'rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400',
            isFullscreen && 'bg-white/10 text-gray-200 dark:bg-white/10 dark:text-gray-200'
          )}>
            {text.queueSourcePrefix}: {queueSourceLabel}
          </div>
        )}
        <div className="flex gap-2">
          <select
            value={annotationPurpose}
            onChange={(e) => setAnnotationPurpose(e.target.value as AnnotationPurpose)}
            className="min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
          >
            <option value="grammar">{text.grammarAnnotation}</option>
            <option value="vocab">{text.vocabAnnotation}</option>
          </select>
          <Button variant="outline" size="sm" onClick={() => void annotateQueue()} disabled={queue.length === 0 || isAnnotating || isProcessing}>
            <Bot className="mr-1.5 h-4 w-4" />
            AI
          </Button>
          <Button variant="outline" size="sm" onClick={clearQueue} disabled={queue.length === 0 || isProcessing}>
            {text.clear}
          </Button>
        </div>

        <div className={cn(
          'max-h-[460px] space-y-2 overflow-y-auto',
          isFullscreen && 'min-h-0 flex-1 max-h-none'
        )}>
          {queue.map((item, index) => {
            const editingDisabled = isProcessing || item.status === 'annotating' || item.status === 'media_processing';
            return (
              <div
                key={item.id}
                className={cn(
                  'rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700',
                  isFullscreen && 'border-white/10 bg-white/5 dark:border-white/10'
                )}
              >
                <div className="mb-2 flex items-center gap-2">
                  <span className="font-medium text-gray-500 dark:text-gray-400">#{index + 1}</span>
                  <div className="min-w-0">
                    <button
                      type="button"
                      onClick={() => seekToQueueItem(item)}
                      className="rounded px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-100 hover:text-primary-600 disabled:hover:bg-transparent disabled:hover:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-primary-300"
                      title={text.seekClip}
                      disabled={!videoUrl || Boolean(item.video_name && item.video_name !== videoFile?.name)}
                    >
                      {formatTime(item.start_sec)} - {formatTime(item.end_sec)}
                    </button>
                    {item.video_name && (
                      <div className="truncate px-1.5 text-[11px] text-gray-400 dark:text-gray-500">
                        {item.video_name}
                      </div>
                    )}
                  </div>
                  <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                    {statusLabel(item.status, text)}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFromQueue(item.id)}
                    className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-700"
                    disabled={isProcessing}
                    title={text.remove}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                <label className="block">
                  <span className={cn('mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400', isFullscreen && 'text-gray-300')}>
                    {text.originalText}
                  </span>
                  <textarea
                    value={item.text}
                    onChange={(event) => updateQueueItem(item.id, { text: event.target.value })}
                    disabled={editingDisabled}
                    rows={2}
                    className={cn(
                      'w-full resize-y rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:disabled:bg-gray-700',
                      isFullscreen && 'border-white/10 bg-black/30 text-white placeholder:text-gray-500 dark:border-white/10 dark:bg-black/30'
                    )}
                  />
                </label>

                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <label className="block">
                    <span className={cn('mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400', isFullscreen && 'text-gray-300')}>
                      {text.wordLabel}
                    </span>
                    <input
                      value={item.word || ''}
                      onChange={(event) => updateQueueItem(item.id, { word: event.target.value })}
                      disabled={editingDisabled}
                      className={cn(
                        'w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:disabled:bg-gray-700',
                        isFullscreen && 'border-white/10 bg-black/30 text-white dark:border-white/10 dark:bg-black/30'
                      )}
                    />
                  </label>
                  <label className="block">
                    <span className={cn('mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400', isFullscreen && 'text-gray-300')}>
                      {text.definitionLabel}
                    </span>
                    <input
                      value={item.definition || ''}
                      onChange={(event) => updateQueueItem(item.id, { definition: event.target.value })}
                      disabled={editingDisabled}
                      className={cn(
                        'w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:disabled:bg-gray-700',
                        isFullscreen && 'border-white/10 bg-black/30 text-white dark:border-white/10 dark:bg-black/30'
                      )}
                    />
                  </label>
                </div>

                <label className="mt-2 block">
                  <span className={cn('mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400', isFullscreen && 'text-gray-300')}>
                    {text.translationLabel}
                  </span>
                  <textarea
                    value={item.translation || ''}
                    onChange={(event) => updateQueueItem(item.id, { translation: event.target.value })}
                    disabled={editingDisabled}
                    rows={2}
                    className={cn(
                      'w-full resize-y rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:disabled:bg-gray-700',
                      isFullscreen && 'border-white/10 bg-black/30 text-white dark:border-white/10 dark:bg-black/30'
                    )}
                  />
                </label>

                <label className="mt-2 block">
                  <span className={cn('mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400', isFullscreen && 'text-gray-300')}>
                    {text.notesLabel}
                  </span>
                  <textarea
                    value={item.notes || ''}
                    onChange={(event) => updateQueueItem(item.id, { notes: event.target.value })}
                    disabled={editingDisabled}
                    rows={2}
                    className={cn(
                      'w-full resize-y rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:disabled:bg-gray-700',
                      isFullscreen && 'border-white/10 bg-black/30 text-white dark:border-white/10 dark:bg-black/30'
                    )}
                  />
                </label>
              </div>
            );
          })}
          {queue.length === 0 && (
            <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
              {text.queueEmpty}
            </div>
          )}
        </div>

        <Button className="w-full" onClick={() => void processQueue()} disabled={queue.length === 0 || queueHasPendingMedia || isProcessing}>
          <Download className="mr-2 h-4 w-4" />
          {text.generateDeck}
        </Button>
      </CardContent>
    </Card>
  );

  const processingStatusCard = !isFullscreen && (isProcessing || processingMessage || apkgUrl) ? (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{text.processingStatus}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ProgressBar
          progress={processingProgress.progress ?? 0}
          indeterminate={processingProgress.mode !== 'determinate'}
        />
        <div className="text-sm text-gray-500 dark:text-gray-400">
          {processingProgress.message || processingMessage || text.waitingProcess}
        </div>
        {processingProgress.mode === 'determinate'
          && typeof processingProgress.current === 'number'
          && typeof processingProgress.total === 'number'
          && (
            <div className="text-xs text-gray-400 dark:text-gray-500">
              {processingProgress.current}/{processingProgress.total}
            </div>
          )}
        {taskId && <div className="text-xs text-gray-400">{text.task}: {taskId}</div>}
        {apkgUrl && (
          <a
            href={apkgUrl}
            className="inline-flex w-full items-center justify-center rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            download
          >
            {text.downloadApkg}
          </a>
        )}
        {showAnkiSync && cards.length > 0 && (
          <div className="flex justify-center">
            <AnkiSyncButton
              cards={cards}
              deckName={videoFile?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo Player'}
              apiBase={API_BASE_URL}
              cardStyles={selectedCardStyles}
              theme={playerCardTheme}
            />
          </div>
        )}
        {cards.length > 0 && (
          <div className="text-sm text-green-600 dark:text-green-400">{text.cardsGenerated(cards.length)}</div>
        )}
      </CardContent>
    </Card>
  ) : null;

  return (
    <div
      ref={playerShellRef}
      className={cn(
        'min-h-screen bg-gray-50 text-gray-900 dark:bg-gray-900 dark:text-gray-100',
        isFullscreen && 'h-screen overflow-hidden bg-black text-gray-100 dark:bg-black'
      )}
    >
      <nav className={cn(
        'border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800',
        isFullscreen && 'fixed right-3 top-3 z-40 border-0 bg-transparent text-white dark:border-0 dark:bg-transparent'
      )}>
        <div className={cn(
          'mx-auto flex min-h-[3.5rem] max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-2 sm:px-6 lg:px-8',
          isFullscreen && 'min-h-0 max-w-none justify-end gap-1 rounded-md bg-black/45 px-2 py-2 shadow-lg backdrop-blur'
        )}>
          <div className={cn('flex items-center gap-2', isFullscreen && 'hidden')}>
            <Film className="h-6 w-6 text-primary-600" />
            <span className="font-semibold">{text.playerTitle}</span>
          </div>
          <div className="flex items-center gap-1">
            {isFullscreen && !showFullscreenSubtitleList && (
              <Button variant="ghost" size="sm" onClick={() => setShowFullscreenSubtitleList(true)} title={text.subtitleList}>
                <Clock className="h-4 w-4" />
              </Button>
            )}
            {isFullscreen && !showFullscreenCaption && (
              <Button variant="ghost" size="sm" onClick={() => setShowFullscreenCaption(true)} title={text.currentSubtitleLabel}>
                <FileText className="h-4 w-4" />
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={toggleLanguage}>
              {language === 'zh' ? 'EN' : '中文'}
            </Button>
            <Button variant="ghost" size="sm" onClick={toggleTheme} title={themeTitle}>
              {theme === 'system' ? <Monitor className="h-4 w-4" /> : theme === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="sm" onClick={toggleFullscreen} title={isFullscreen ? text.exitFullscreen : text.fullscreen}>
              {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              {!isFullscreen && <span className="ml-2 hidden sm:inline">{text.fullscreen}</span>}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => window.location.assign('/')}>
              <ArrowLeft className={cn('h-4 w-4', !isFullscreen && 'mr-2')} />
              {!isFullscreen && text.returnMain}
            </Button>
          </div>
        </div>
      </nav>

      <main className={cn(
        'mx-auto grid max-w-7xl gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_360px]',
        isFullscreen && 'fixed inset-0 z-0 block max-w-none overflow-hidden p-0'
      )}>
        <section className={cn(
          'space-y-4',
          isFullscreen && 'contents'
        )}>
          {!isFullscreen && (
          <div className="grid gap-3 rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.videoFile}</span>
              <input
                type="file"
                accept="video/*"
                onChange={(e) => handleVideoChange(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-primary-600 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white dark:text-gray-300"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.subtitleFile}</span>
              <input
                type="file"
                accept=".srt,text/plain"
                onChange={(e) => void handleSubtitleChange(e.target.files?.[0] || null)}
                className="block w-full text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-gray-700 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white dark:text-gray-300"
              />
            </label>
            <div className="flex items-end">
              <Button
                variant="outline"
                className="w-full whitespace-nowrap"
                onClick={() => void extractEmbeddedSubtitles()}
                disabled={!videoFile || isExtractingEmbedded || isTranscribing || isProcessing}
                isLoading={isExtractingEmbedded}
              >
                <FileText className="mr-2 h-4 w-4" />
                {text.extractEmbedded}
              </Button>
            </div>
            <div className="flex items-end gap-2">
              <Button
                variant="outline"
                className="min-w-0 flex-1 whitespace-nowrap"
                onClick={() => void transcribeVideo(false)}
                disabled={!videoFile || selectedEngineUnavailable || isTranscribing || isExtractingEmbedded || isProcessing}
                isLoading={isTranscribing}
              >
                <Mic className="mr-2 h-4 w-4" />
                {text.asrTranscribe}
              </Button>
              <Button
                variant="ghost"
                className="whitespace-nowrap"
                onClick={() => void transcribeVideo(true)}
                disabled={!videoFile || selectedEngineUnavailable || isTranscribing || isExtractingEmbedded || isProcessing}
              >
                {text.retranscribe}
              </Button>
            </div>
            <div className="grid gap-3 border-t border-gray-100 pt-3 dark:border-gray-700 lg:col-span-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.asrEngine}</span>
                <select
                  value={asrEngine}
                  onChange={(e) => setAsrEngine(e.target.value as ASREngine)}
                  disabled={isTranscribing || isExtractingEmbedded || isProcessing}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                >
                  {(['faster_whisper', 'bcut'] as ASREngine[]).map((engine) => {
                    const info = asrEngines.find((item) => item.id === engine);
                    const unavailable = asrEngines.length > 0 && info?.available === false;
                    return (
                      <option key={engine} value={engine} disabled={unavailable}>
                        {info?.name || (engine === 'faster_whisper' ? 'Faster Whisper' : text.bcutEngine)}{unavailable ? ` (${text.unavailableSuffix})` : ''}
                      </option>
                    );
                  })}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.whisperModel}</span>
                <select
                  value={whisperModel}
                  onChange={(e) => setWhisperModel(e.target.value as WhisperModel)}
                  disabled={asrEngine !== 'faster_whisper' || isTranscribing || isExtractingEmbedded || isProcessing}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm disabled:bg-gray-100 disabled:text-gray-400 dark:border-gray-600 dark:bg-gray-800 dark:disabled:bg-gray-700"
                >
                  {WHISPER_MODELS.map((model) => (
                    <option key={model.key} value={model.key}>
                      {model.label} {model.size}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.sourceLanguage}</span>
                <select
                  value={transcribeLanguage}
                  onChange={(e) => setTranscribeLanguage(e.target.value)}
                  disabled={isTranscribing || isExtractingEmbedded || isProcessing}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                >
                  <option value="">{text.autoDetect}</option>
                  {LANGUAGE_CODES.map((code) => (
                    <option key={code} value={code}>{code}</option>
                  ))}
                </select>
              </label>
              {selectedEngineUnavailable && (
                <div className="text-xs text-red-500 lg:col-span-3">
                  {text.asrUnavailableInline}
                </div>
              )}
            </div>
          </div>
          )}

          {!isFullscreen && (
            <Card>
              <CardHeader className="p-3">
                <div className="flex items-center justify-between gap-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Settings className="h-4 w-4" />
                    {text.playerSettings}
                  </CardTitle>
                  <Button variant="ghost" size="sm" onClick={() => setShowSettings((value) => !value)}>
                    {showSettings ? text.collapseSettings : text.expandSettings}
                  </Button>
                </div>
              </CardHeader>
              {showSettings && (
                <CardContent className="space-y-4 p-3">
                  <div className="grid gap-3 lg:grid-cols-3">
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.captureSettings}</span>
                      <select
                        value={annotationPurpose}
                        onChange={(e) => setAnnotationPurpose(e.target.value as AnnotationPurpose)}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                      >
                        <option value="grammar">{text.grammarAnnotation}</option>
                        <option value="vocab">{text.vocabAnnotation}</option>
                      </select>
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.cardStyle}</span>
                      <select
                        value={playerCardStyle}
                        onChange={(e) => setPlayerCardStyle(e.target.value as PlayerCardStyleSetting)}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                      >
                        <option value="sentence">{text.sentenceCard}</option>
                        <option value="vocab">{text.vocabCard}</option>
                        <option value="both">{text.bothCards}</option>
                      </select>
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{text.cardTheme}</span>
                      <select
                        value={playerCardTheme}
                        onChange={(e) => setPlayerCardTheme(e.target.value as PlayerCardThemeSetting)}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                      >
                        <option value="default">{text.defaultTheme}</option>
                        <option value="minimal">{text.minimalTheme}</option>
                        <option value="dictionary">{text.dictionaryTheme}</option>
                        <option value="netflix">{text.netflixTheme}</option>
                      </select>
                    </label>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700">
                      <input
                        type="checkbox"
                        checked={pauseAfterCapture}
                        onChange={(e) => setPauseAfterCapture(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>{text.pauseAfterCapture}</span>
                    </label>
                    <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700">
                      <input
                        type="checkbox"
                        checked={showAnkiSync}
                        onChange={(e) => setShowAnkiSync(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>{text.showAnkiSync}</span>
                    </label>
                    <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700">
                      <input
                        type="checkbox"
                        checked={showFullscreenSubtitleList}
                        onChange={(e) => setShowFullscreenSubtitleList(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>{text.fullscreenOverlays}: {text.subtitleList}</span>
                    </label>
                    <label className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700">
                      <input
                        type="checkbox"
                        checked={showFullscreenCaption}
                        onChange={(e) => setShowFullscreenCaption(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>{text.fullscreenOverlays}: {text.currentSubtitleLabel}</span>
                    </label>
                  </div>
                </CardContent>
              )}
            </Card>
          )}

          {!isFullscreen && (isTranscribing || transcribeMessage) && (
            <div className="rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
              <ProgressBar
                progress={transcribeProgress.progress ?? 0}
                indeterminate={transcribeProgress.mode !== 'determinate'}
              />
              <div className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                {transcribeProgress.message || transcribeMessage}
              </div>
              {transcribeProgress.mode === 'determinate'
                && transcribeProgress.unit === 'seconds'
                && typeof transcribeProgress.current === 'number'
                && typeof transcribeProgress.total === 'number'
                && (
                  <div className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                    {formatDuration(transcribeProgress.current)} / {formatDuration(transcribeProgress.total)}
                  </div>
                )}
              {transcribeProgress.detail && (
                <div className="mt-1 truncate text-xs text-gray-400 dark:text-gray-500">
                  {transcribeProgress.detail}
                </div>
              )}
            </div>
          )}

          <div className={cn(
            'relative overflow-hidden rounded-lg border border-gray-200 bg-black dark:border-gray-700',
            isFullscreen && 'fixed inset-0 z-0 rounded-none border-0 dark:border-0'
          )}>
            {videoUrl ? (
              <video
                ref={videoRef}
                src={videoUrl}
                controls
                className={cn(
                  'aspect-video w-full bg-black',
                  isFullscreen && 'h-full aspect-auto object-contain'
                )}
                onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
              />
            ) : (
              <div className={cn(
                'flex aspect-video items-center justify-center text-sm text-gray-400',
                isFullscreen && 'h-full min-h-[18rem] aspect-auto'
              )}>
                {text.chooseVideo}
              </div>
            )}
            {isFullscreen && displayedSubtitle && showFullscreenCaption && (
              <div
                className="absolute z-30 w-[min(48rem,calc(100vw-1.5rem))] overflow-hidden rounded-md border border-white/10 bg-black/70 text-white shadow-2xl backdrop-blur"
                style={{ left: currentSubtitlePosition.x, top: currentSubtitlePosition.y }}
              >
                <div
                  className="flex cursor-move items-center justify-between gap-2 border-b border-white/10 px-2 py-1.5 text-xs text-gray-300"
                  onPointerDown={(event) => startOverlayDrag(event, 'currentSubtitle')}
                >
                  <span className="inline-flex items-center gap-1">
                    <GripHorizontal className="h-3.5 w-3.5" />
                    {text.currentSubtitleLabel}
                  </span>
                  <button
                    type="button"
                    className="rounded p-1 text-gray-300 hover:bg-white/10 hover:text-white"
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={() => setShowFullscreenCaption(false)}
                    title={text.remove}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="px-4 py-2 text-center text-lg leading-relaxed">
                  {displayedSubtitle.text}
                </div>
              </div>
            )}
            {isFullscreen && fullscreenNotice && (
              <div className="pointer-events-none absolute left-1/2 top-20 z-50 -translate-x-1/2 rounded-full bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-2xl">
                {fullscreenNotice}
              </div>
            )}
          </div>

          {videoUrl && playbackSource !== 'local' && (
            <div className={cn(
              'flex gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100',
              isFullscreen && 'hidden'
            )}>
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" />
              <div>
                <span className="font-medium">
                  {playbackSource === 'compatible' ? text.compatiblePlaybackReady : text.preparingCompatiblePlayback}
                </span>
                <span className="ml-1">{text.audioCodecHint}</span>
              </div>
            </div>
          )}

          {!isFullscreen && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
              <Button onClick={() => void togglePlay()} disabled={!videoUrl}>
                {isPlaying ? <Pause className="mr-2 h-4 w-4" /> : <Play className="mr-2 h-4 w-4" />}
                {isPlaying ? text.pause : text.play}
              </Button>
              <Button variant="outline" onClick={captureCurrentSubtitle} disabled={!videoFile || !capturableSubtitle}>
                <Plus className="mr-2 h-4 w-4" />
                {text.captureCurrent}
              </Button>
              <div className="ml-auto text-sm text-gray-500 dark:text-gray-400">
                {text.shortcutHint} · F {text.fullscreen}
              </div>
            </div>
          )}

          {!isFullscreen && queueCard}
          {isFullscreen && subtitleListCard}
        </section>

        <aside className={cn(
          'space-y-4',
          isFullscreen && 'fixed bottom-24 left-3 z-30 hidden h-[min(38vh,360px)] w-[min(28rem,calc(100vw-1.5rem))] min-h-0 space-y-0 xl:block'
        )}>
          {!isFullscreen && subtitleListCard}
          {isFullscreen && queueCard}
          {processingStatusCard}
        </aside>
      </main>
    </div>
  );
}
