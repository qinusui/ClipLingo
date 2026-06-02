import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from './i18n';
import { Film, Download, Info, Sparkles, ChevronDown, ChevronUp, MessageSquare, Sun, Moon, Monitor, BookOpen, GraduationCap, FolderOpen, X, ExternalLink, RefreshCw, RotateCcw, FileSpreadsheet, FileJson, Palette, CheckCircle } from 'lucide-react';
import { Button } from './components/Button';
import { Card, CardContent, CardHeader, CardTitle } from './components/Card';
import { ProgressBar } from './components/ProgressBar';
import { FileUpload } from './components/FileUpload';
import { SubtitleTable } from './components/SubtitleTable';
import { ProcessingStatus } from './components/ProcessingStatus';
import { CardPreview } from './components/CardPreview';
import { StyleThemeSelector } from './components/StyleThemeSelector';
import { CssVariableEditor } from './components/CssVariableEditor';
import { ThemeImporter } from './components/ThemeImporter';
import { TemplateMarketplace } from './components/TemplateMarketplace';
import { StyleGenerator } from './components/StyleGenerator';
import { AnkiSyncButton } from './components/AnkiSyncButton';
import { PreheatIndicator } from './components/PreheatIndicator';
import { SubtitleItem, ProcessedCard, AIRecommendation, CardStyle, CardTheme, ThemeOverrides, WorkflowPhase, AnnotationPurpose, ASREngine, TranslateService } from './types';
import { subtitleAPI, processAPI, translateAPI, API_BASE_URL } from './services/api';
import { themeAPI, type ThemeListItem } from './services/themeAPI';
import { pingAnki, fetchWordsFromAnki } from './services/ankiConnect';

import { useTheme } from './hooks/useTheme';
import { getFriendlyMessage, getApiErrorMessage } from './utils/errors';
import { toast } from './utils/toast';

// 格式化时间为 SRT 格式
function formatSRTTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')},${ms.toString().padStart(3, '0')}`;
}

// 生成 CSV 内容（utf-8-sig 编码，Excel 兼容）
function generateCSVContent(cards: ProcessedCard[]): string {
  const headers = ['sentence', 'translation', 'notes', 'word', 'definition'];
  const escapeCSV = (val: string | undefined) => {
    const s = val ?? '';
    if (s.includes('"') || s.includes(',') || s.includes('\n')) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  };
  const rows = cards.map(c => [
    escapeCSV(c.sentence),
    escapeCSV(c.translation),
    escapeCSV(c.notes),
    escapeCSV(c.word),
    escapeCSV(c.definition),
  ].join(','));
  return [headers.join(','), ...rows].join('\r\n');
}

// 生成 JSON 内容（完整数据）
function generateJSONContent(cards: ProcessedCard[]): string {
  return JSON.stringify(cards, null, 2);
}

// 触发浏览器下载（字符串内容）
function downloadString(content: string, filename: string, mimeType: string) {
  const blob = mimeType.includes('csv')
    ? new Blob(['﻿' + content], { type: mimeType + ';charset=utf-8;' })
    : new Blob([content], { type: mimeType + ';charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  URL.revokeObjectURL(url);
  a.remove();
}

// 直接浏览器下载（不经过 fetch+blob，避免大文件撑爆内存）
function downloadUrl(url: string, filename: string) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

type StepStatus = 'pending' | 'processing' | 'completed' | 'error';
type ProcessingStep = { id: string; status: StepStatus; error?: string };

const PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'parse', status: 'pending' },
  { id: 'media', status: 'pending' },
  { id: 'pack', status: 'pending' },
];

const MEDIA_PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'parse', status: 'pending' },
  { id: 'media', status: 'pending' },
];

const PACK_PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'pack', status: 'pending' },
];

const LANGUAGE_CODES = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es', 'it', 'pt', 'ru', 'ar', 'th', 'vi', 'nl', 'sv', 'pl', 'tr', 'hi', 'id'] as const;

function getLangName(code: string): string {
  return i18n.t(`app.lang.${code}`);
}

function buildPresetPrompt(template: string, sourceLanguage: string): string {
  return template.replace(/\{source_language\}/g, getLangName(sourceLanguage));
}

function buildAnnotationPrompt(template: string, sourceLanguage: string, targetLanguage: string): string {
  return template
    .replace(/\{source_language\}/g, getLangName(sourceLanguage))
    .replace(/\{target_language\}/g, getLangName(targetLanguage));
}

type PresetKey = 'grammar' | 'vocab';
type AnnotationPresetKey = 'grammar' | 'vocab';

// 从 localStorage 读取 AI 配置（持久化）
function loadAIConfig() {
  try {
    const raw = localStorage.getItem('anki_ai_config');
    if (raw) return JSON.parse(raw);
  } catch { /* localStorage 解析失败，返回默认配置 */ }
  return null;
}

// 全局重排字幕 index 为 1..N。selectedIndices / recommendations / corrections
// 均以 index 为键，后端按文件从 1 编号，多视频拼接会导致 index 冲突、跨视频串号。
// 所有 setSubtitles 入口都必须经过此函数，保证 index 全局唯一这一不变量。
function reindexSubtitles(subs: SubtitleItem[]): SubtitleItem[] {
  return subs.map((s, i) => ({ ...s, index: i + 1 }));
}

function App() {
  const { t, i18n } = useTranslation();

  const presetTemplates = useMemo(() => ({
    grammar: { label: t('app.promptPreset.grammarScreen'), prompt: t('app.prompt.grammarScreenBody') },
    vocab: { label: t('app.promptPreset.vocabScreen'), prompt: t('app.prompt.vocabScreenBody') },
  }), [t]);

  const annotationTemplates = useMemo(() => ({
    grammar: { label: t('app.promptPreset.grammarAnnotate'), prompt: t('app.prompt.grammarAnnotateBody') },
    vocab: { label: t('app.promptPreset.vocabAnnotate'), prompt: t('app.prompt.vocabAnnotateBody') },
  }), [t]);
  const { theme, toggleTheme } = useTheme();
  const savedConfig = loadAIConfig();
  const [apiBase, setApiBase] = useState(savedConfig?.apiBase || 'https://api.deepseek.com');
  const [modelName, setModelName] = useState(savedConfig?.modelName || 'deepseek-chat');
  const [apiKey, setApiKey] = useState(savedConfig?.apiKey || '');
  const [aiConcurrency, setAiConcurrency] = useState(savedConfig?.aiConcurrency ?? 3);
  const [sourceLanguage, setSourceLanguage] = useState<string>(savedConfig?.sourceLanguage || 'en');
  const [targetLanguage, setTargetLanguage] = useState<string>(savedConfig?.targetLanguage || 'zh');
  const [configExpanded, setConfigExpanded] = useState(!savedConfig); // 首次展开
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ valid: boolean; message: string } | null>(null);
  const [modelList, setModelList] = useState<string[] | null>(null);
  const minDuration = 1.0; // 由 Step 2 的时长筛选替代，此处保留用于后端过滤零时长字幕
  const [paddingStartMs, setPaddingStartMs] = useState(200);
  const [paddingEndMs, setPaddingEndMs] = useState(200);
  const [whisperModel, setWhisperModel] = useState('base');
  const [asrEngine, setAsrEngine] = useState<ASREngine>('faster_whisper');
  const [mtService, setMtService] = useState<TranslateService>('bing');
  const [deeplApiKey, setDeeplApiKey] = useState(savedConfig?.deeplApiKey || '');
  const [mtCollapsed, setMtCollapsed] = useState(!!savedConfig?.apiKey);
  const [checkingEmbedded, setCheckingEmbedded] = useState(false);
  const [extractedSource, setExtractedSource] = useState('');

  const [videoFiles, setVideoFiles] = useState<File[]>([]);
  const [subtitleFiles, setSubtitleFiles] = useState<(File | null)[]>([]);
  // 每个视频贡献的字幕条数（与 videoFiles 一一对应，0=无字幕→后端 Whisper）
  const [subtitleCounts, setSubtitleCounts] = useState<number[]>([]);

  // 多视频模式
  const [mergeMode, setMergeMode] = useState(true);

  const [subtitles, setSubtitles] = useState<SubtitleItem[]>([]);
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());

  const [processingSteps, setProcessingSteps] = useState(PROCESSING_STEPS);
  const [currentStep, setCurrentStep] = useState(-1);
  const [processingMessage, setProcessingMessage] = useState('');

  const [result, setResult] = useState<ProcessedCard[] | null>(null);
  const [apkgPath, setApkgPath] = useState<string | null>(null);
  const [apkgUrl, setApkgUrl] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  // 两阶段处理流程
  const [processingPhase, setProcessingPhase] = useState<'idle' | 'media_processing' | 'awaiting_styles' | 'packing' | 'completed'>('idle');
  const [processedCards, setProcessedCards] = useState<ProcessedCard[] | null>(null);

  const [previewIndex, setPreviewIndex] = useState(0);
  // 预览只展示前 10 张，避免渲染几百个 iframe 卡顿
  const previewCards = useMemo(() => processedCards?.slice(0, 10) || [], [processedCards]);
  const previewResult = useMemo(() => result?.slice(0, 10) || [], [result]);
  const [showHelp, setShowHelp] = useState(false);
  const [helpTab, setHelpTab] = useState<'basic' | 'advanced'>('basic');

  // AI 推荐相关
  const [recommendations, setRecommendations] = useState<Map<number, AIRecommendation> | null>(null);
  const [failedIndices, setFailedIndices] = useState<Set<number>>(new Set());
  const [isRecommending, setIsRecommending] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const transcribingRef = useRef(false);
  const transcribedVideoName = useRef<string | null>(null);
  const step2Ref = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const scrollToStep2 = () => {
    setTimeout(() => step2Ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
  };
  const [transcribeStep, setTranscribeStep] = useState(0);
  const [, setTranscribeTotalSteps] = useState(4);
  const [transcribeMessage, setTranscribeMessage] = useState('');
  const [transcribeAnimProgress, setTranscribeAnimProgress] = useState(0);
  const transcribeAnimRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [whisperText, setWhisperText] = useState('');
  const whisperHasRealProgress = useRef(false);
  const [recommendBatch, setRecommendBatch] = useState(0);
  const [recommendTotalBatches, setRecommendTotalBatches] = useState(0);
  // 两阶段 AI 工作流
  const [workflowPhase, setWorkflowPhase] = useState<WorkflowPhase>('idle');
  const [annotationPurpose, setAnnotationPurpose] = useState<AnnotationPurpose | null>(null);
  const [annotateBatch, setAnnotateBatch] = useState(0);
  const [annotateTotalBatches, setAnnotateTotalBatches] = useState(0);
  // AI 字幕修正
  const [corrections, setCorrections] = useState<Map<number, string> | null>(null);
  const [correctBatch, setCorrectBatch] = useState(0);
  const [correctionHandled, setCorrectionHandled] = useState(false);
  const [deselectedCorrections, setDeselectedCorrections] = useState<Set<number>>(new Set());

  // 多视频批处理
  const [isBatchProcessing, setIsBatchProcessing] = useState(false);
  const [batchRemaining, setBatchRemaining] = useState(0);
  const [batchCompleted, setBatchCompleted] = useState(0);
  const [batchStepMessage, setBatchStepMessage] = useState('');
  const [batchDone, setBatchDone] = useState(false);
  const [batchCancelled, setBatchCancelled] = useState(false);
  const [batchPartialFailed, setBatchPartialFailed] = useState(false); // 批处理中途失败：牌组将不完整
  const batchAbortControllerRef = useRef<AbortController | null>(null);
  const screeningHandledRef = useRef(false); // 跟踪筛选是否真正执行过（区别于仅注释）
  const [pendingPack, setPendingPack] = useState(false); // 批处理完成后自动打包
  const [customPrompt, setCustomPrompt] = useState<string>(
    savedConfig?.customPrompt || buildPresetPrompt(t('app.prompt.grammarScreenBody'), savedConfig?.sourceLanguage || 'en')
  );
  const [promptPreset, setPromptPreset] = useState<PresetKey>('grammar');
  const [annotationPrompt, setAnnotationPrompt] = useState<string>(
    savedConfig?.annotationPrompt || buildAnnotationPrompt(t('app.prompt.grammarAnnotateBody'), savedConfig?.sourceLanguage || 'en', savedConfig?.targetLanguage || 'zh')
  );
  const [annotationPreset, setAnnotationPreset] = useState<AnnotationPresetKey>('grammar');
  const [showAnnotationPromptEditor, setShowAnnotationPromptEditor] = useState(false);
  const [selectRecommendedOnly, setSelectRecommendedOnly] = useState(false);
  const [cardStyles, setCardStyles] = useState<Set<CardStyle>>(new Set(['sentence']));
  const [cardTheme, setCardTheme] = useState<CardTheme>('default');
  const [themeOverrides, setThemeOverrides] = useState<Record<string, ThemeOverrides>>({});
  const [editingStyles, setEditingStyles] = useState(false);
  const [pendingOverrides, setPendingOverrides] = useState<ThemeOverrides>({});
  const [hasUnsavedOverrides, setHasUnsavedOverrides] = useState(false);
  const [customThemes, setCustomThemes] = useState<ThemeListItem[]>([]);
  const [showThemeImporter, setShowThemeImporter] = useState(false);
  const [showMarketplace, setShowMarketplace] = useState(false);
  const [showStyleGenerator, setShowStyleGenerator] = useState(false);
  const [styleGenInitialTheme, setStyleGenInitialTheme] = useState<{
    name: string; label: string; front: string; back: string; css: string;
  } | null>(null);
  const [showPromptEditor, setShowPromptEditor] = useState(false);
  const recommendBatchSize = 30;
  const [ffmpegInstalled, setFFmpegInstalled] = useState<boolean | null>(null);

  // 更新检查
  const [updateInfo, setUpdateInfo] = useState<{
    hasUpdate: boolean;
    latestVersion: string;
    downloadUrl: string;
    releaseNotes: string;
    releaseUrl: string;
  } | null>(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);

  // 已学单词记录
  const [learnedWords, setLearnedWords] = useState<Map<string, string>>(new Map());

  // 规则筛选
  const [filterMinDuration, setFilterMinDuration] = useState(1);
  const [filterMaxDuration, setFilterMaxDuration] = useState(15);
  const [filterExcludeLearned, setFilterExcludeLearned] = useState(true);
  const [filterBlacklist, setFilterBlacklist] = useState('');

  // 心跳：每 30 秒 ping 一次，后端超时 2 分钟无心跳自动关闭
  useEffect(() => {
    const heartbeatInterval = setInterval(() => {
      fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
    }, 30000);

    return () => {
      clearInterval(heartbeatInterval);
    };
  }, []);

  // 加载已学单词记录（启动时先从后端加载，再尝试从 Anki 同步）
  const [syncingFromAnki, setSyncingFromAnki] = useState(false);

  const loadLearnedWords = async () => {
    try {
      const resp = await fetch('/api/subtitles/learned-words');
      const data = await resp.json();
      if (data.words) {
        const map = new Map<string, string>();
        for (const [word, def] of Object.entries(data.words)) {
          map.set(word, def as string);
        }
        setLearnedWords(map);
      }
    } catch { /* 加载已学词汇失败，静默忽略 */ }
  };

  const syncFromAnki = async (fullSync: boolean = false) => {
    setSyncingFromAnki(true);
    try {
      const online = await pingAnki();
      if (!online) return;
      const words = await fetchWordsFromAnki(fullSync);
      if (words.length === 0) return;
      // 写入后端数据库
      await fetch('/api/subtitles/sync-learned-from-anki', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ words }),
      });
      // 重新加载
      await loadLearnedWords();
    } catch {
      // 静默失败
    } finally {
      setSyncingFromAnki(false);
    }
  };

  useEffect(() => {
    loadLearnedWords().then(() => {
      // 延迟 5 秒后尝试从 Anki 同步（不阻塞主流程）
      setTimeout(syncFromAnki, 5000);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 同步 subtitleFiles 长度与 videoFiles
  useEffect(() => {
    setSubtitleFiles(prev => {
      if (prev.length === videoFiles.length) return prev;
      const updated = [...prev];
      while (updated.length < videoFiles.length) updated.push(null);
      return updated.slice(0, videoFiles.length);
    });
  }, [videoFiles.length]);

  // 检测 ffmpeg 和 Whisper 插件安装状态（延迟 3 秒等后端就绪）
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const ffmpegStatus = await subtitleAPI.getFFmpegStatus();
        setFFmpegInstalled(ffmpegStatus.installed);
      } catch {
        setFFmpegInstalled(false);
      }
    };
    const timer = setTimeout(checkStatus, 3000);
    return () => clearTimeout(timer);
  }, []);

  // 启动时检查更新（延迟 5 秒，不阻塞主流程）
  useEffect(() => {
    const checkUpdate = async () => {
      try {
        const data = await processAPI.checkUpdate();
        if (data.has_update) {
          setUpdateInfo({
            hasUpdate: true,
            latestVersion: data.latest_version || '',
            downloadUrl: data.download_url || '',
            releaseNotes: data.release_notes || '',
            releaseUrl: data.release_url || '',
          });
        }
      } catch {
        // 静默失败，不影响正常使用
      }
    };
    const timer = setTimeout(checkUpdate, 5000);
    return () => clearTimeout(timer);
  }, []);

  // AI 配置变化时自动保存到 localStorage
  useEffect(() => {
    localStorage.setItem('anki_ai_config', JSON.stringify({ apiBase, modelName, apiKey, aiConcurrency, sourceLanguage, targetLanguage, customPrompt, annotationPrompt, deeplApiKey }));
  }, [apiBase, modelName, apiKey, aiConcurrency, sourceLanguage, targetLanguage, customPrompt, annotationPrompt, deeplApiKey]);

  // 源语言变化时，同步更新预设提示词中的语言名称
  useEffect(() => {
    for (const tmpl of Object.values(presetTemplates)) {
      const built = buildPresetPrompt(tmpl.prompt, sourceLanguage);
      for (const code of LANGUAGE_CODES) {
        if (code === sourceLanguage) continue;
        if (customPrompt === buildPresetPrompt(tmpl.prompt, code)) {
          setCustomPrompt(built);
          break;
        }
      }
    }
    // 同步注释提示词
    for (const tmpl of Object.values(annotationTemplates)) {
      const built = buildAnnotationPrompt(tmpl.prompt, sourceLanguage, targetLanguage);
      for (const srcCode of LANGUAGE_CODES) {
        for (const tgtCode of LANGUAGE_CODES) {
          if (srcCode === sourceLanguage && tgtCode === targetLanguage) continue;
          if (annotationPrompt === buildAnnotationPrompt(tmpl.prompt, srcCode, tgtCode)) {
            setAnnotationPrompt(built);
            return;
          }
        }
      }
    }
    // annotationPrompt/customPrompt/presetTemplates/annotationTemplates 的变化会触发本 effect 内 setState，
    // 加入依赖数组将形成循环更新，此处仅需响应语言变化
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceLanguage, targetLanguage]);

  // 转录进度动画
  useEffect(() => {
    const stepBase = [0, 10, 30, 100];

    if (!isTranscribing) {
      setTranscribeAnimProgress(0);
      whisperHasRealProgress.current = false;
      setWhisperText('');
      if (transcribeAnimRef.current) clearInterval(transcribeAnimRef.current);
      return;
    }

    const base = stepBase[transcribeStep] || 0;
    setTranscribeAnimProgress(base);

    if (transcribeStep === 2) {
      // 有真实进度时不启动模拟动画
      if (whisperHasRealProgress.current) return;
      transcribeAnimRef.current = setInterval(() => {
        setTranscribeAnimProgress(prev => {
          if (whisperHasRealProgress.current) {
            // 收到真实进度后停止模拟
            if (transcribeAnimRef.current) clearInterval(transcribeAnimRef.current);
            return prev;
          }
          if (prev < 30) return 30;
          if (prev >= 94) return 94;
          return Math.min(94, prev + 0.3);
        });
      }, 1000);
    } else {
      if (transcribeAnimRef.current) clearInterval(transcribeAnimRef.current);
    }

    return () => {
      if (transcribeAnimRef.current) clearInterval(transcribeAnimRef.current);
    };
  }, [isTranscribing, transcribeStep]);

  // ── 主题覆盖：加载 + 实时预览 ──
  useEffect(() => {
    themeAPI.loadOverrides(cardTheme).then(result => {
      const ov = result.variables || {};
      setThemeOverrides(prev => ({ ...prev, [cardTheme]: ov }));
      setPendingOverrides(ov);
      setHasUnsavedOverrides(false);
    });
  }, [cardTheme]);

  // 加载自定义主题列表
  useEffect(() => {
    themeAPI.listThemes().then(themes => {
      // 忽略空响应（服务器错误时 listThemes 返回 []），避免清空已有列表
      if (themes.length > 0) {
        setCustomThemes(themes.filter(t => !t.isBuiltin));
      }
    });
  }, []);

  const refreshCustomThemes = async () => {
    const themes = await themeAPI.listThemes();
    if (themes.length > 0) {
      setCustomThemes(themes.filter(t => !t.isBuiltin));
    }
  };

  const handleImportTheme = async (zipFile: File) => {
    await themeAPI.importZip(zipFile);
    await refreshCustomThemes();
  };

  const handleDeleteTheme = async (name: string) => {
    await themeAPI.deleteTheme(name);
    // 如果正选中被删除的主题，切回 default
    if (cardTheme === name) setCardTheme('default');
    await refreshCustomThemes();
  };

  // ── 主题覆盖：作用域预览（只影响卡片预览区域，不污染全局样式）──
  useEffect(() => {
    const vars = themeOverrides[cardTheme] || {};
    const scope = document.getElementById('card-preview-scope');
    if (!scope) return;
    Object.entries(vars).forEach(([k, v]) => {
      if (v) scope.style.setProperty(k, v);
      else scope.style.removeProperty(k);
    });
  }, [cardTheme, themeOverrides]);

  // 后台预热：筛选完成后静默启动注释预计算
  const preheatTriggeredRef = useRef(false);
  useEffect(() => {
    if (workflowPhase === 'screened' && taskId && apiKey && !preheatTriggeredRef.current) {
      preheatTriggeredRef.current = true;
      const recommendedSubs = subtitles.filter(s => selectedIndices.has(s.index));
      if (recommendedSubs.length > 0) {
        for (const purpose of ['grammar', 'vocab'] as AnnotationPurpose[]) {
          fetch(`${API_BASE_URL}/api/annotate/preheat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              task_id: taskId,
              subtitles: recommendedSubs,
              purpose,
              api_key: apiKey,
              api_base: apiBase || undefined,
              model_name: modelName || undefined,
              custom_prompt: annotationPrompt || undefined,
              batch_size: recommendBatchSize,
              source_language: sourceLanguage,
              target_language: targetLanguage,
            }),
          }).catch(() => {});
        }
      }
    }
    if (workflowPhase === 'screening' || workflowPhase === 'idle') {
      preheatTriggeredRef.current = false;
    }
    // 仅需在 workflowPhase / taskId / apiKey 变化时触发预热，其他 deps 加入后会导致预热频繁重启
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowPhase, taskId, apiKey]);

  // 多视频手动批处理触发函数（在步骤 4 中调用）
  const batchTriggeredRef = useRef(false);
  const handleTriggerBatch = useCallback(async () => {
    console.log('[批处理] handleTriggerBatch 被调用:', { isBatchProcessing, batchTriggered: batchTriggeredRef.current, videoCount: videoFiles.length, batchDone });
    if (isBatchProcessing || batchTriggeredRef.current) {
      console.warn('[批处理] 提前返回: isBatchProcessing=', isBatchProcessing, 'batchTriggered=', batchTriggeredRef.current);
      return;
    }
    if (videoFiles.length < 2) return;
    batchTriggeredRef.current = true;
    console.log('[批处理] 开始处理剩余视频...');

    const remainingNames = videoFiles.slice(1).map(f => f.name);
    // 保留 1:1 映射：null → 空字符串（不能 filter 掉，否则索引错位）
    const remainingSubs = subtitleFiles.slice(1).map(f => f ? f.name : "");

    const runCorrection = corrections !== null && !correctionHandled;
    const runScreening = screeningHandledRef.current;
    const runAnnotation = annotationPurpose !== null;

    // 检测是否使用了机器翻译（workflowPhase 为 annotated 但 annotationPurpose 为 null）
    const usedMT = workflowPhase === 'annotated' && annotationPurpose === null;

    setBatchRemaining(remainingNames.length);
    setBatchCompleted(0);
    setBatchPartialFailed(false); // 新一轮批处理：清除上次的部分失败提示
    setBatchCancelled(false);
    setIsBatchProcessing(true);

    const controller = new AbortController();
    batchAbortControllerRef.current = controller;

    try {
      for await (const event of processAPI.startBatchProcess({
        video_names: remainingNames,
        subtitle_files: remainingSubs,
        api_key: apiKey || undefined,
        api_base: apiBase || undefined,
        model_name: modelName || undefined,
        ai_concurrency: aiConcurrency,
        source_language: sourceLanguage,
        target_language: targetLanguage,
        run_correction: runCorrection,
        run_screening: runScreening,
        custom_screen_prompt: customPrompt || undefined,
        run_annotation: runAnnotation,
        annotation_purpose: annotationPurpose || undefined,
        custom_annotation_prompt: annotationPrompt || undefined,
        min_duration: filterMinDuration,
        mt_service: usedMT ? mtService : undefined,
        mt_api_key: usedMT ? (mtService === 'deepl' ? deeplApiKey : mtService === 'openai' ? apiKey : undefined) : undefined,
        mt_api_base: usedMT && mtService === 'openai' ? (apiBase || undefined) : undefined,
        mt_model_name: usedMT && mtService === 'openai' ? (modelName || undefined) : undefined,
      }, taskId || '', controller.signal)) {
        if (event.type === 'video_progress') {
          setBatchStepMessage(event.message || '');
        } else if (event.type === 'video_done') {
          setBatchCompleted(prev => prev + 1);
        } else if (event.type === 'video_failed') {
          // 单视频失败：批处理继续，仅标记部分失败，最终在 complete 汇总
          console.warn('[批处理] 视频失败，跳过继续:', event.video_name, event.message);
          setBatchPartialFailed(true);
        } else if (event.type === 'complete') {
          if (event.error) {
            // 流异常关闭的兜底事件，不要当作成功完成
            console.warn('[批处理] 流异常关闭，未完成批处理');
            toast.error(t('app.batch.error') + (event.message || '连接中断，请重试'));
            setBatchDone(false);
            setBatchPartialFailed(true); // 已完成视频结果已落盘，提示客户牌组将不完整
            setPendingPack(false);
            batchTriggeredRef.current = false;
            return;
          }
          const failed = event.failures?.length ?? 0;
          if (failed > 0) {
            // 部分视频失败：成功项已落盘，提示「X 成功 / Y 失败」并允许重试失败项
            console.warn(`[批处理] 完成（部分失败）：${event.successes ?? 0} 成功 / ${failed} 失败`);
            toast.error(t('app.batch.partialFailed', { success: event.successes ?? 0, failed }));
            setBatchPartialFailed(true);
            batchTriggeredRef.current = false; // 允许对失败项重试
          }
          console.log(`批量处理完成：${event.total_cards} 张卡片`);
          setBatchDone(true);
        } else if (event.type === 'cancelled') {
          console.log('[批处理] 已取消');
          setBatchCancelled(true);
          setBatchDone(false);
          setPendingPack(false);
          batchTriggeredRef.current = false;
          toast(t('app.batch.cancelled'));
        } else if (event.type === 'error') {
          console.error('批量处理错误:', event.error || event.message);
          toast.error(t('app.batch.error') + (event.error || event.message || ''));
          setBatchDone(false);
          setBatchPartialFailed(true); // 已完成视频结果已落盘，提示客户牌组将不完整
          setPendingPack(false);
          batchTriggeredRef.current = false; // 允许重试
          return;
        }
      }
    } catch (error: unknown) {
      console.error('批量处理失败:', error);
      toast.error(t('app.batch.error') + getApiErrorMessage(error));
      setBatchDone(false);
      setPendingPack(false);
      batchTriggeredRef.current = false; // 允许重试
    } finally {
      batchAbortControllerRef.current = null;
      setIsBatchProcessing(false);
    }
  }, [isBatchProcessing, videoFiles, subtitleFiles, corrections, correctionHandled,
    annotationPurpose, apiKey, apiBase, modelName, aiConcurrency, sourceLanguage, targetLanguage,
    customPrompt, annotationPrompt, filterMinDuration, taskId, t, mtService, deeplApiKey, workflowPhase, batchDone]);

  // 取消批处理
  const handleCancelBatch = useCallback(async () => {
    if (!taskId) return;
    // 1. 断开前端 SSE 连接
    batchAbortControllerRef.current?.abort();
    // 2. 通知后端取消
    try {
      await fetch(`${API_BASE_URL}/api/process/cancel/${taskId}`, { method: 'POST' });
    } catch { /* 后端取消失败不影响前端的取消状态 */ }
  }, [taskId]);

  // Esc 退出应用
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      fetch(`${API_BASE_URL}/api/shutdown`, { method: 'POST' }).finally(() => {
        window.close();
      });
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // 切换编辑器
  const handleToggleEditor = () => {
    if (editingStyles) {
      setEditingStyles(false);
    } else {
      setPendingOverrides(themeOverrides[cardTheme] || {});
      setHasUnsavedOverrides(false);
      setEditingStyles(true);
    }
  };

  // 切换主题（有未保存修改时自动保存当前更改，避免数据丢失）
  const handleSetCardTheme = async (theme: CardTheme) => {
    if (hasUnsavedOverrides && theme !== cardTheme) {
      if (!window.confirm(`${t('cssEditor.unsavedMessage')}\n\n即将保存当前更改到「${cardTheme}」并切换到新主题。`)) return;
      try {
        const result = await themeAPI.saveOverrides(cardTheme, pendingOverrides);
        if (result.ok) {
          setThemeOverrides(prev => ({ ...prev, [cardTheme]: { ...pendingOverrides } }));
        } else {
          toast.error(result.detail || '保存失败，请重试');
        }
      } catch { /* save failed silently */ }
      setHasUnsavedOverrides(false);
    }
    setCardTheme(theme);
  };

  const handleOverrideChange = (overrides: ThemeOverrides) => {
    setPendingOverrides(overrides);
    setHasUnsavedOverrides(true);
  };

  const handleSaveOverrides = async () => {
    const result = await themeAPI.saveOverrides(cardTheme, pendingOverrides);
    if (result.ok) {
      setThemeOverrides(prev => ({ ...prev, [cardTheme]: { ...pendingOverrides } }));
      setHasUnsavedOverrides(false);
    } else {
      toast.error(result.detail || '保存样式失败，请重试');
    }
  };

  const handleResetOverrides = () => {
    setPendingOverrides({});
    setHasUnsavedOverrides(true);
  };

  // 测试 AI 连接
  const handleTestConnection = async () => {
    if (!apiKey) return;
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await processAPI.testConnection(apiKey, apiBase, modelName);
      setTestResult(res);
    } catch (error) {
      setTestResult({ valid: false, message: getApiErrorMessage(error) });
    }
    setIsTesting(false);
  };

  // 获取模型列表
  const handleListModels = async () => {
    if (!apiKey) return;
    try {
      const res = await processAPI.listModels(apiKey, apiBase);
      setModelList(res.models);
    } catch {
      setModelList([]);
    }
  };

  const WHISPER_MODELS = [
    { key: 'tiny',  label: 'tiny',   size: '~75 MB',  speed: t('app.whisper.tiny') },
    { key: 'base',  label: 'base',   size: '~145 MB', speed: t('app.whisper.base') },
    { key: 'small', label: 'small',  size: '~488 MB', speed: t('app.whisper.small') },
    { key: 'medium',label: 'medium', size: '~1.5 GB', speed: t('app.whisper.medium') },
    { key: 'large', label: 'large',  size: '~2.9 GB', speed: t('app.whisper.large') },
  ];

  // 生成字幕 — 方案链：软字幕 > Whisper 转录
  const handleTranscribe = async () => {
    if (videoFiles.length === 0 || transcribingRef.current) return;
    if (transcribedVideoName.current === videoFiles[0].name) return;

    setCheckingEmbedded(true);
    setExtractedSource('');

    try {
      // 优先提取内嵌软字幕
      const result = await subtitleAPI.extractEmbeddedSubs(videoFiles[0], 0, minDuration);

      if (result.found && result.extracted) {
        const extracted = reindexSubtitles(result.extracted.subtitles as SubtitleItem[]);
        setSubtitles(extracted);
        setSelectedIndices(new Set(extracted.map((s: SubtitleItem) => s.index)));
        setRecommendations(null);
        const counts = new Array(videoFiles.length).fill(0);
        counts[0] = extracted.length;
        setSubtitleCounts(counts);
        transcribedVideoName.current = videoFiles[0].name;
        setExtractedSource(t('app.subtitleSource.extractedFromVideo', { codec: result.extracted.codec, language: result.extracted.language, total: result.extracted.total }));
        setCheckingEmbedded(false);
        scrollToStep2();
        return;
      }

      if (result.found && !result.extracted) {
        console.log('内嵌字幕无法提取:', result.message);
      }
    } catch (e) {
      console.error('检测字幕失败:', e);
    }

    setCheckingEmbedded(false);

    // 内嵌字幕不可用 → 启动 Whisper 转录
    try {
      const whisperStatus = await subtitleAPI.getWhisperStatus();
      if (!whisperStatus.installed) {
        toast.error(t('app.error.whisperNotInstalled'));
        return;
      }
    } catch (e) {
      console.error('检查 Whisper 状态失败:', e);
    }

    transcribingRef.current = true;
    setIsTranscribing(true);
    setTranscribeStep(0);
    setTranscribeTotalSteps(4);
    setTranscribeMessage(t('app.error.transcribePreparing'));

    try {
      const { task_id } = await subtitleAPI.startTranscribe(videoFiles[0], minDuration, sourceLanguage, whisperModel, asrEngine);

      const pollInterval = setInterval(async () => {
        try {
          const progress = await subtitleAPI.getTranscribeProgress(task_id);

          setTranscribeStep(progress.step);
          setTranscribeTotalSteps(progress.total_steps);

          if (progress.whisper_progress) {
            const wp = progress.whisper_progress;
            const pct = Math.round(wp.progress * 100);
            whisperHasRealProgress.current = true;
            setTranscribeAnimProgress(pct);
            setWhisperText(wp.text || '');
            const fmtTime = (sec: number) => {
              const m = Math.floor(sec / 60);
              const s = Math.floor(sec % 60);
              return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
            };
            setTranscribeMessage(t('app.error.transcribing', { transcribed: fmtTime(wp.transcribed_sec), duration: fmtTime(wp.duration_sec), pct: `${pct}` }));
          } else {
            setTranscribeMessage(progress.message);
          }

          if (progress.status === 'completed' && progress.result) {
            clearInterval(pollInterval);
            setIsTranscribing(false);
            transcribingRef.current = false;

            const transcribed = reindexSubtitles(progress.result.subtitles);
            setSubtitles(transcribed);
            setSelectedIndices(new Set(transcribed.map((s: SubtitleItem) => s.index)));
            setRecommendations(null);
            const counts = new Array(videoFiles.length).fill(0);
            counts[0] = transcribed.length;
            setSubtitleCounts(counts);
            transcribedVideoName.current = videoFiles[0].name;
            scrollToStep2();
          }

          if (progress.status === 'error') {
            clearInterval(pollInterval);
            setIsTranscribing(false);
            transcribingRef.current = false;
            toast.error(getFriendlyMessage(progress.error_code, progress.error));
          }
        } catch (e) {
          // 轮询失败不中断
        }
      }, 1000);

      (window as unknown as Record<string, unknown>).__transcribePoll = pollInterval;

    } catch (error) {
      console.error('转录失败:', error);
      toast.error(t('app.error.transcribeFailed') + getApiErrorMessage(error));
      setIsTranscribing(false);
      transcribingRef.current = false;
    }
  };

  // 加载字幕（每个视频独立加载，保留 per-video 边界）
  const handleLoadSubtitles = async () => {
    const validSubs = subtitleFiles.filter(f => f !== null);
    if (validSubs.length === 0) return;

    try {
      setProcessingSteps(steps =>
        steps.map((s, i) =>
          i === 0 ? { ...s, status: 'processing' } : { ...s, status: 'pending' }
        )
      );
      setCurrentStep(0);

      let allSubtitles: SubtitleItem[] = [];
      const counts: number[] = new Array(videoFiles.length).fill(0);

      for (let i = 0; i < subtitleFiles.length; i++) {
        const subFile = subtitleFiles[i];
        if (subFile) {
          const response = await subtitleAPI.upload(subFile, minDuration);
          counts[i] = response.subtitles.length;
          allSubtitles = allSubtitles.concat(response.subtitles);
        }
      }

      // 后端按文件从 1 开始编号，多视频拼接会导致 index 冲突，
      // 进而让 selectedIndices / recommendations（按 index 索引）跨视频互相干扰、
      // 并触发 React key 重复。这里全局重排成唯一 index。
      // 安全性：后端 _process_video_to_media 按位置 zip pre_processed，
      // 最终卡片 index 取自各视频重新解析的 SRT（本地 1..N），不依赖此处的值。
      allSubtitles = reindexSubtitles(allSubtitles);

      setSubtitleCounts(counts);
      setSubtitles(allSubtitles);
      setSelectedIndices(new Set(allSubtitles.map((s: SubtitleItem) => s.index)));
      scrollToStep2();

      setProcessingSteps(steps =>
        steps.map((s, i) =>
          i === 0 ? { ...s, status: 'completed' } : { ...s, status: 'pending' }
        )
      );
    } catch (error) {
      console.error('加载字幕失败:', error);
      setProcessingSteps(steps =>
        steps.map((s, i) =>
          i === 0 ? { ...s, status: 'error', error: String(error) } : s
        )
      );
    }
  };

  // AI 筛选字幕（第一阶段：只返回 include/reason）
  const handleAIScreen = async () => {
    if (!apiKey) {
      toast.error(t('app.error.needApiKey'));
      return;
    }
    if (subtitles.length === 0) {
      toast.error(t('app.error.needSubtitles'));
      return;
    }
    if (selectedIndices.size === 0) {
      toast.error(t('app.error.needSelectSentences'));
      return;
    }

    setWorkflowPhase('screening');
    setIsRecommending(true);
    setSelectRecommendedOnly(false);
    setRecommendations(new Map());
    setFailedIndices(new Set());
    setRecommendBatch(0);
    setRecommendTotalBatches(0);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      // 预过滤已学词汇，节省 AI 费用（跟随"排除已学词汇"复选框）
      const screenSubs = subtitles.filter(s => {
        if (!selectedIndices.has(s.index)) return false;
        if (filterExcludeLearned) {
          const rec = recommendations?.get(s.index);
          if (rec?.word && learnedWords.has(rec.word.toLowerCase().trim())) return false;
        }
        return true;
      });
      if (screenSubs.length === 0) {
        toast.error(t('app.error.allLearned'));
        setIsRecommending(false);
        setWorkflowPhase('idle');
        return;
      }

      const stream = subtitleAPI.startScreenStream(
        screenSubs,
        apiKey,
        customPrompt || undefined,
        recommendBatchSize,
        aiConcurrency,
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
        controller.signal
      );

      let receivedDone = false;
      try {
        for await (const event of stream) {
          if (event.type === 'start') {
            setRecommendTotalBatches(event.total_batches!);
          } else if (event.type === 'error') {
            throw new Error(event.message || 'AI 筛选失败');
          } else if (event.type === 'batch') {
            setRecommendBatch(event.batch!);
            setRecommendations(prev => {
              const next = new Map(prev || []);
              for (const item of event.items!) {
                next.set(item.index, item as unknown as AIRecommendation);
              }
              return next;
            });
          } else if (event.type === 'done') {
            setIsRecommending(false);
            receivedDone = true;
            break;
          }
        }
      } catch (error: unknown) {
        if (receivedDone) {
          console.debug('AI 筛选流已关闭:', error);
        } else if ((error as Error)?.message?.includes('input stream')) {
          console.debug('AI 筛选流意外关闭:', error);
        } else {
          throw error;
        }
      } finally {
        receivedDone = true;
      }

      // 流结束后，收集失败项、自动选中推荐的句子
      setRecommendations(prev => {
        if (!prev || prev.size === 0) return prev;
        const failed = new Set<number>();
        for (const [index, rec] of prev) {
          if (rec.reason?.startsWith(t('app.error.processingFailed'))) {
            failed.add(index);
          }
        }
        setFailedIndices(failed);

        if (selectRecommendedOnly) {
          const recommendedIndices = Array.from(prev.values())
            .filter(r => r.include && !r.reason?.startsWith(t('app.error.processingFailed')))
            .map(r => r.index);
          setSelectedIndices(new Set(recommendedIndices));
        }
        return prev;
      });

      screeningHandledRef.current = true;
      setWorkflowPhase('screened');

    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('AI 筛选已中止');
      } else {
        console.error('AI 筛选失败:', error);
        toast.error(t('app.error.aiScreenFailed') + getApiErrorMessage(error));
      }
      setIsRecommending(false);
      // 保留已有部分结果，回到 screened 状态（而非 idle）
      setRecommendations(prev => {
        if (prev && prev.size > 0) {
          screeningHandledRef.current = true;
          setWorkflowPhase('screened');
        } else {
          setWorkflowPhase('idle');
        }
        return prev;
      });
    }
  };

  // AI 注释字幕（第二阶段：根据用途生成翻译和注释）
  const handleAIAnnotate = async (purpose: AnnotationPurpose) => {
    if (!apiKey) {
      toast.error(t('app.error.needApiKey'));
      return;
    }

    const selectedSubs = subtitles.filter(s => selectedIndices.has(s.index));

    if (selectedSubs.length === 0) {
      toast.error(t('app.error.needSelectSentencesForAnnotation'));
      return;
    }

    setAnnotationPurpose(purpose);
    setWorkflowPhase('annotating');
    setAnnotateBatch(0);
    setAnnotateTotalBatches(0);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const stream = subtitleAPI.startAnnotateStream(
        selectedSubs,
        purpose,
        apiKey,
        annotationPrompt || undefined,
        recommendBatchSize,
        aiConcurrency,
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
        controller.signal,
        taskId || undefined
      );

      let streamEnded = false;
      try {
        for await (const event of stream) {
          if (event.type === 'start') {
            setAnnotateTotalBatches(event.total_batches!);
          } else if (event.type === 'error') {
            throw new Error(event.message || 'AI 注释失败');
          } else if (event.type === 'batch') {
            setAnnotateBatch(event.batch!);
            setRecommendations(prev => {
              const next = new Map(prev || []);
              for (const item of event.items!) {
                const existing = next.get(item.index);
                next.set(item.index, {
                  ...(existing || { include: true, reason: '', index: item.index }),
                  translation: (item as Record<string, unknown>).translation as string || '',
                  notes: (item as Record<string, unknown>).notes as string || '',
                  word: (item as Record<string, unknown>).word as string || '',
                  definition: (item as Record<string, unknown>).definition as string || '',
                });
              }
              return next;
            });
          } else if (event.type === 'done') {
            setWorkflowPhase('annotated');
            streamEnded = true;
            break;
          }
        }
      } catch (error: unknown) {
        if (streamEnded || (error as Error)?.name === 'AbortError') {
          console.debug('AI 注释流已关闭:', error);
          setWorkflowPhase('annotated');
          return;
        } else if ((error as Error)?.message?.includes('input stream')) {
          // 浏览器 SSE 流关闭时的假错误，忽略
          setWorkflowPhase('annotated');
          return;
        }
        throw error;
      } finally {
        streamEnded = true;
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('AI 注释已中止');
      } else {
        console.error('AI 注释失败:', error);
        toast.error(t('app.error.aiAnnotateFailed') + getApiErrorMessage(error));
      }
      setWorkflowPhase('screened');
    }
  };

  // AI 字幕修正
  const handleAICorrect = async () => {
    if (!apiKey) return;
    if (workflowPhase === 'correcting') return; // 防止重复点击

    const selectedSubs = subtitles.filter(s => selectedIndices.has(s.index));
    if (selectedSubs.length === 0) return;

    setWorkflowPhase('correcting');
    setCorrections(new Map());
    setCorrectBatch(0);
    setDeselectedCorrections(new Set());
    let streamEnded = false;
    try {
      const stream = subtitleAPI.startCorrectStream(
        selectedSubs, apiKey, aiConcurrency,
        apiBase || undefined, modelName || undefined,
        sourceLanguage, targetLanguage
      );

      for await (const event of stream) {
        if (event.type === 'start') {
          // no-op
        } else if (event.type === 'error') {
          throw new Error(event.message || 'AI 修正失败');
        } else if (event.type === 'batch' && event.items) {
          setCorrectBatch(prev => prev + 1);
          setCorrections(prev => {
            const next = new Map(prev);
            for (const item of event.items!) {
              if (item.corrected_text && item.corrected_text !== '') {
                next.set(item.index, item.corrected_text as string);
              }
            }
            return next;
          });
        } else if (event.type === 'done') {
          streamEnded = true;
          break;
        }
      }
    } catch (error: unknown) {
      if (streamEnded || (error as Error)?.name === 'AbortError') {
        console.debug('AI 修正流已关闭:', error);
      } else if ((error as Error)?.message?.includes('input stream')) {
        // 浏览器 SSE 流关闭时的假错误，忽略
      } else {
        console.error('AI 修正失败:', error);
        toast.error(t('app.error.aiCorrectFailed') + getApiErrorMessage(error));
        setWorkflowPhase('idle');
        return;
      }
    } finally {
      streamEnded = true;
    }
    setWorkflowPhase('corrected');
  };

  // 切换单条修正的选中状态
  const toggleCorrection = (index: number) => {
    setDeselectedCorrections(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  // 应用修正：将选中的 corrections 写入 subtitles[i].text
  const handleApplyCorrections = () => {
    if (!corrections) return;
    setSubtitles(prev => prev.map(s => {
      if (deselectedCorrections.has(s.index)) return s;
      const corrected = corrections.get(s.index);
      return (corrected && corrected !== s.text) ? { ...s, text: corrected } : s;
    }));
    setCorrectionHandled(true);
    setCorrections(null);
    setWorkflowPhase('idle');
  };

  // 跳过修正
  const handleSkipCorrections = () => {
    setCorrectionHandled(true);
    setCorrections(null);
    setWorkflowPhase('idle');
  };

  // 机器翻译（无 AI Key 时使用）
  const handleMTTranslate = async () => {
    const selectedSubs = subtitles.filter(s => selectedIndices.has(s.index));
    if (selectedSubs.length === 0) {
      toast.error(t('app.error.needSelectSentencesForAnnotation'));
      return;
    }
    if (mtService === 'deepl' && !deeplApiKey) {
      toast.error(t('app.error.deeplNeedApiKey'));
      return;
    }
    setWorkflowPhase('annotating');
    try {
      const texts = selectedSubs.map(s => s.text);
      const { translations } = await translateAPI.batch(
        texts, mtService, sourceLanguage, targetLanguage,
        deeplApiKey || undefined, undefined, undefined
      );
      setRecommendations(prev => {
        const next = new Map(prev);
        selectedSubs.forEach((sub, i) => {
          const existing = next.get(sub.index) || { index: sub.index, include: true, reason: '机器翻译' };
          next.set(sub.index, { ...existing, translation: translations[i] || '' });
        });
        return next;
      });
      setWorkflowPhase('annotated');
    } catch (error) {
      console.error('机器翻译失败:', error);
      toast.error(t('app.error.mtTranslateFailed') + getApiErrorMessage(error));
      setWorkflowPhase('screened');
    }
  };

  // 重试失败的批次
  const handleRetryFailed = async () => {
    if (!apiKey || failedIndices.size === 0) return;

    const failedSubtitles = subtitles.filter(s => failedIndices.has(s.index));
    if (failedSubtitles.length === 0) return;

    setIsRecommending(true);
    setFailedIndices(new Set());
    setRecommendBatch(0);
    setRecommendTotalBatches(0);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const stream = subtitleAPI.startScreenStream(
        failedSubtitles,
        apiKey,
        customPrompt || undefined,
        recommendBatchSize,
        aiConcurrency,
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
        controller.signal
      );

      let streamEnded = false;
      try {
        for await (const event of stream) {
          if (event.type === 'start') {
            setRecommendTotalBatches(event.total_batches!);
          } else if (event.type === 'error') {
            throw new Error(event.message || '重试失败');
          } else if (event.type === 'batch') {
            setRecommendBatch(event.batch!);
            setRecommendations(prev => {
              const next = new Map(prev || []);
              for (const item of event.items!) {
                next.set(item.index, item as unknown as AIRecommendation);
              }
              return next;
            });
          } else if (event.type === 'done') {
            setIsRecommending(false);
            streamEnded = true;
            break;
          }
        }
      } catch (error: unknown) {
        if (streamEnded || (error as Error)?.name === 'AbortError') {
          console.debug('重试流已关闭:', error);
        } else if ((error as Error)?.message?.includes('input stream')) {
          // 浏览器 SSE 流关闭时的假错误，忽略
        } else {
          throw error;
        }
      } finally {
        streamEnded = true;
      }

      // 重试后更新失败列表
      setRecommendations(prev => {
        if (!prev || prev.size === 0) return prev;
        const failed = new Set<number>();
        for (const [index, rec] of prev) {
          if (rec.reason?.startsWith(t('app.error.processingFailed'))) {
            failed.add(index);
          }
        }
        setFailedIndices(failed);
        return prev;
      });

    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('重试已中止');
      } else {
        console.error('重试失败:', error);
        toast.error(t('app.error.retryFailed') + getApiErrorMessage(error));
      }
      setIsRecommending(false);
    }
  };

  // ── Phase 1: 处理媒体（不打包） ──
  const handleProcessMedia = async () => {
    if (videoFiles.length === 0) { toast.error(t('app.error.needUploadVideo')); return; }
    if (subtitles.length === 0) { toast.error(t('app.error.needLoadSubtitles')); return; }
    if (selectedIndices.size === 0) { toast.error(t('app.error.needSelectOne')); return; }
    if (isRecommending || workflowPhase === 'screening' || workflowPhase === 'annotating') {
      toast.error(t('app.error.aiProcessingInProgress', 'AI 正在处理中，请等待完成后再操作'));
      return;
    }

    setProcessingPhase('media_processing');
    setProcessingSteps(MEDIA_PROCESSING_STEPS.map(s => ({ ...s, status: 'pending' as const })));
    setCurrentStep(0);
    setProcessingMessage('');

    // 构建预处理数据（同 handleProcess）
    const allPreProcessed = subtitles
      .filter(s => selectedIndices.has(s.index))
      .map(s => {
        const rec = recommendations?.get(s.index);
        return {
          index: s.index, text: rec?.corrected_text || s.text,
          translation: rec?.translation || '', notes: rec?.notes || '',
          reason: rec?.reason || '', word: rec?.word || '', definition: rec?.definition || ''
        };
      });

    // 按视频分组
    const perVideoSRTFiles: (File | null)[] = [];
    const perVideoPreProcessed: Record<string, unknown>[][] = videoFiles.map(() => []);
    let ppIdx = 0;
    let globalPos = 0;
    for (let vi = 0; vi < videoFiles.length; vi++) {
      const count = subtitleCounts[vi] || 0;
      const videoSubs = subtitles.slice(globalPos, globalPos + count);
      globalPos += count;
      const selectedSubs = videoSubs.filter(s => selectedIndices.has(s.index));
      if (selectedSubs.length === 0) {
        perVideoSRTFiles.push(new File([], `_auto_transcribe_${vi}.srt`, { type: 'text/plain' }));
        perVideoPreProcessed[vi] = [];
      } else {
        let srtContent = '';
        const videoPP: Record<string, unknown>[] = [];
        selectedSubs.forEach((sub, newIdx) => {
          srtContent += `${newIdx + 1}\n${formatSRTTime(sub.start_sec)} --> ${formatSRTTime(sub.end_sec)}\n${sub.text}\n\n`;
          if (ppIdx < allPreProcessed.length) { videoPP.push(allPreProcessed[ppIdx]); ppIdx++; }
        });
        perVideoSRTFiles.push(new File([srtContent], `video_${vi}_selected.srt`, { type: 'text/plain' }));
        perVideoPreProcessed[vi] = videoPP;
      }
    }

    // 检测是否使用了机器翻译（workflowPhase 为 annotated 但 annotationPurpose 为 null）
    const usedMT = workflowPhase === 'annotated' && annotationPurpose === null;

    try {
      const { task_id } = await processAPI.uploadAndProcessMedia(
        videoFiles, perVideoSRTFiles, mergeMode, minDuration,
        apiKey || undefined, perVideoPreProcessed, apiBase || undefined, modelName || undefined,
        paddingStartMs, paddingEndMs, sourceLanguage, targetLanguage,
        customPrompt || undefined, annotationPurpose || undefined, annotationPrompt || undefined,
        selectRecommendedOnly,
        usedMT ? mtService : undefined,
        usedMT ? (mtService === 'deepl' ? deeplApiKey : mtService === 'openai' ? apiKey : undefined) : undefined,
        usedMT && mtService === 'openai' ? (apiBase || undefined) : undefined,
        usedMT && mtService === 'openai' ? (modelName || undefined) : undefined,
      );
      setTaskId(task_id);

      const pollInterval = setInterval(async () => {
        try {
          const progress = await processAPI.getProgress(task_id);
          setProcessingMessage(progress.message || '');
          // 映射后端 step 到前端 MEDIA_PROCESSING_STEPS (2 steps)
          const stepIndex = progress.step <= 1 ? 0 : Math.min(1, progress.step - 2);
          setCurrentStep(stepIndex);
          setProcessingSteps(steps => {
            const newSteps = [...steps];
            for (let i = 0; i < newSteps.length; i++) {
              if (i < stepIndex) newSteps[i] = { ...newSteps[i], status: 'completed' as const };
              else if (i === stepIndex) newSteps[i] = { ...newSteps[i], status: 'processing' as const };
            }
            return newSteps;
          });

          if (progress.status === 'awaiting_styles' && progress.result?.cards) {
            clearInterval(pollInterval);
            setProcessedCards(progress.result.cards);
            setPreviewIndex(0);
            setProcessingPhase('awaiting_styles');
            setProcessingMessage(progress.message || '');
            setProcessingSteps(s => s.map(step => ({ ...step, status: 'completed' as const })));
          }
          if (progress.status === 'error') {
            clearInterval(pollInterval);
            const errMsg = getFriendlyMessage(progress.error_code, progress.error || undefined);
            toast.error(t('app.error.processingFailedPoll', { error: errMsg }));
            setProcessingSteps(s => s.map(step => step.status === 'processing' ? { ...step, status: 'error' as const, error: errMsg } : step));
            setProcessingPhase('idle');
          }
        } catch (e) { /* polling error, ignore */ }
      }, 1000);
    } catch (error) {
      console.error('媒体处理失败:', error);
      toast.error(t('app.error.processingFailedPoll', { error: getApiErrorMessage(error) }));
      setProcessingPhase('idle');
    }
  };

  // ── Phase 2: 生成牌组 ──
  const handleGenerateApkg = async () => {
    if (!taskId) return;
    setProcessingPhase('packing');
    setProcessingSteps(PACK_PROCESSING_STEPS.map(s => ({ ...s, status: 'pending' as const })));
    setCurrentStep(0);
    setProcessingMessage(t('app.processing.packingApkg'));

    try {
      await processAPI.generateApkg(
        taskId,
        Array.from(cardStyles),
        cardTheme,
        JSON.stringify(themeOverrides[cardTheme] || {}),
      );

      const pollInterval = setInterval(async () => {
        try {
          const progress = await processAPI.getProgress(taskId);
          setProcessingMessage(progress.message || '');
          setCurrentStep(progress.step);

          if (progress.status === 'completed' && progress.result) {
            clearInterval(pollInterval);
            setProcessingPhase('completed');
            setProcessingSteps(s => s.map(step => ({ ...step, status: 'completed' as const })));
            const r = progress.result;
            setApkgPath(r.apkg_path);
            setApkgUrl(r.apkg_url || null);
            if (r.cards && r.cards.length > 0) {
              setResult(r.cards);
              setPreviewIndex(0);
            }
          }
          if (progress.status === 'error') {
            clearInterval(pollInterval);
            const errMsg = getFriendlyMessage(progress.error_code, progress.error || undefined);
            toast.error(t('app.error.processingFailedPoll', { error: errMsg }));
            setProcessingSteps(s => s.map(step => step.status === 'processing' ? { ...step, status: 'error' as const, error: errMsg } : step));
            setProcessingPhase('awaiting_styles');
          }
        } catch (e) { /* ignore */ }
      }, 1000);
    } catch (error) {
      console.error('打包失败:', error);
      toast.error(t('app.error.processingFailedPoll', { error: getApiErrorMessage(error) }));
      setProcessingPhase('awaiting_styles');
    }
  };

  // 用 ref 保存 handleGenerateApkg 的最新版本，避免 useEffect 依赖问题
  const handleGenerateApkgRef = useRef(handleGenerateApkg);
  handleGenerateApkgRef.current = handleGenerateApkg;

  // 批处理完成后自动触发打包
  useEffect(() => {
    console.log('[useEffect] batchDone/pendingPack 变化:', { batchDone, pendingPack });
    if (batchDone && pendingPack) {
      console.log('[useEffect] 自动触发打包');
      setPendingPack(false);
      handleGenerateApkgRef.current();
    }
  }, [batchDone, pendingPack]);

  // 下载文件
  const handleDownload = async () => {
    if (!apkgPath) return;

    try {
      // apkgUrl 已是 /output/... 的相对路径，直接用，避免跨域
      const downloadUrl = apkgUrl || `/download/${encodeURIComponent(apkgPath)}`;

      // 直接浏览器下载，不经过 fetch+blob（大文件会撑爆内存）
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = apkgPath.split('/').pop() || 'deck.apkg';
      document.body.appendChild(a);
      a.click();
      a.remove();

      // 延迟清理服务端文件（等浏览器开始下载）
      if (taskId) {
        setTimeout(async () => {
          try { await processAPI.cleanup(taskId); } catch (e) { console.error('清理文件失败:', e); }
        }, 3000);
      }

      // 清理界面状态，方便继续处理下一个视频
      setVideoFiles([]);
      setSubtitleFiles([]);
      setSubtitleCounts([]);
      setSubtitles([]);
      setSelectedIndices(new Set());
      setResult(null);
      setApkgPath(null);
      setApkgUrl(null);
      setRecommendations(null);
      setFailedIndices(new Set());
      setProcessingSteps(PROCESSING_STEPS);
      setCurrentStep(-1);
      setProcessingMessage('');
      setExtractedSource('');
      transcribedVideoName.current = null;
      setWorkflowPhase('idle');
      setAnnotationPurpose(null);
      batchTriggeredRef.current = false;
      setIsBatchProcessing(false);
      setBatchDone(false);
      setCardTheme('default');
      setCorrectionHandled(false);
      setCorrections(null);
      setDeselectedCorrections(new Set());
  
    } catch (error) {
      console.error('下载失败:', error);
      toast.error(t('app.error.downloadFailed') + (apkgUrl || '/download/' + encodeURIComponent(apkgPath)));
    }
  };

  // 切换选中状态
  const toggleSelection = (index: number) => {
    const newSelected = new Set(selectedIndices);
    if (newSelected.has(index)) {
      newSelected.delete(index);
    } else {
      newSelected.add(index);
    }
    setSelectedIndices(newSelected);
  };

  // 规则筛选后的字幕
  const filteredSubtitles = useMemo(() => {
    const blacklist = filterBlacklist
      .split(/[,，\n]/)
      .map(k => k.trim().toLowerCase())
      .filter(k => k.length > 0);

    return subtitles.filter(s => {
      // 时长过滤
      if (s.duration < filterMinDuration) return false;
      if (filterMaxDuration > 0 && s.duration > filterMaxDuration) return false;

      // 排除已学单词（需要有 AI 推荐结果）
      if (filterExcludeLearned && recommendations) {
        const rec = recommendations.get(s.index);
        if (rec?.include && rec.word) {
          const word = rec.word.trim().toLowerCase();
          if (learnedWords.has(word)) return false;
        }
      }

      // 关键词排除
      if (blacklist.length > 0) {
        const text = s.text.toLowerCase();
        if (blacklist.some(k => text.includes(k))) return false;
      }

      return true;
    });
  }, [subtitles, filterMinDuration, filterMaxDuration, filterExcludeLearned, filterBlacklist, recommendations, learnedWords]);

  // 全选/取消全选（作用于筛选结果）
  const toggleSelectAll = () => {
    const filteredIndices = new Set(filteredSubtitles.map(s => s.index));
    const allSelected = filteredIndices.size > 0 && [...filteredIndices].every(i => selectedIndices.has(i));
    if (allSelected) {
      // 取消筛选结果的选中，保留非筛选项的选中状态
      const newSelected = new Set(selectedIndices);
      for (const i of filteredIndices) newSelected.delete(i);
      setSelectedIndices(newSelected);
    } else {
      // 选中所有筛选结果
      const newSelected = new Set(selectedIndices);
      for (const i of filteredIndices) newSelected.add(i);
      setSelectedIndices(newSelected);
    }
  };

  // 反选（作用于筛选结果）
  const invertSelection = () => {
    const filteredIndices = new Set(filteredSubtitles.map(s => s.index));
    const newSelected = new Set(selectedIndices);
    for (const i of filteredIndices) {
      if (newSelected.has(i)) {
        newSelected.delete(i);
      } else {
        newSelected.add(i);
      }
    }
    setSelectedIndices(newSelected);
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* 顶部导航 */}
      <nav className="bg-white border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-2">
              <Film className="w-8 h-8 text-primary-600" />
              <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">ClipLingo</h1>
            </div>
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowHelp(!showHelp)}
              >
                <Info className="w-4 h-4 mr-2" />
                {t('app.header.help')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.open('https://github.com/qinusui/ClipLingo/issues', '_blank')}
              >
                <MessageSquare className="w-4 h-4 mr-2" />
                {t('app.header.feedback')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={async () => {
                  try {
                    await processAPI.openLogs();
                  } catch {
                    toast.error(t('app.step1.cantOpenLogFolder'));
                  }
                }}
              >
                <FolderOpen className="w-4 h-4 mr-2" />
                {t('app.step1.logs')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  const next = i18n.language === 'zh' ? 'en' : 'zh';
                  i18n.changeLanguage(next);
                  localStorage.setItem('ui_language', next);
                }}
              >
                {i18n.language === 'zh' ? 'EN' : t('app.lang.zh')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleTheme}
                title={theme === 'system' ? t('app.header.followSystem') : theme === 'light' ? t('app.header.lightMode') : t('app.header.darkMode')}
              >
                {theme === 'system' ? <Monitor className="w-4 h-4" /> : theme === 'light' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </Button>
            </div>
          </div>
        </div>
      </nav>

      {/* 更新提示横幅 */}
      {updateInfo?.hasUpdate && !updateDismissed && (
        <div className="bg-blue-50 border-b border-blue-200 dark:bg-blue-900/30 dark:border-blue-700">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <Download className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0" />
              <p className="text-sm text-blue-800 dark:text-blue-200 truncate">
                {t('app.update.found', { version: updateInfo.latestVersion, current: '1.3.1' })}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <a
                href={updateInfo.downloadUrl || updateInfo.releaseUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                {t('app.update.download')}
              </a>
              <button
                onClick={() => setUpdateDismissed(true)}
                className="p-1 text-blue-400 hover:text-blue-600 dark:hover:text-blue-300 transition-colors"
                title={t('app.update.dismiss')}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* 使用说明 */}
        {showHelp && (
          <Card className="mb-6">
            <CardContent>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold">{t('app.help.title')}</h3>
                <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5 dark:bg-gray-700">
                  <button
                    onClick={() => setHelpTab('basic')}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      helpTab === 'basic'
                        ? 'bg-white text-gray-900 shadow dark:bg-gray-600 dark:text-gray-100'
                        : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                    }`}
                  >
                    {t('app.help.tabBasic')}
                  </button>
                  <button
                    onClick={() => setHelpTab('advanced')}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      helpTab === 'advanced'
                        ? 'bg-white text-gray-900 shadow dark:bg-gray-600 dark:text-gray-100'
                        : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                    }`}
                  >
                    {t('app.help.tabAdvanced')}
                  </button>
                </div>
              </div>

              {helpTab === 'basic' ? (
                <ol className="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300">
                  <li>{t('app.help.basic1')}</li>
                  <li>{t('app.help.basic2')}</li>
                  <li>{t('app.help.basic3')}</li>
                  <li>{t('app.help.basic4')}</li>
                </ol>
              ) : (
                <div className="space-y-4 text-sm text-gray-700 dark:text-gray-300">
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">{t('app.help.advancedBatchTitle')}</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>{t('app.help.advancedBatch1')}</li>
                      <li>{t('app.help.advancedBatch2')}</li>
                      <li>{t('app.help.advancedBatch3')}</li>
                      <li>{t('app.help.advancedBatch4')}</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">{t('app.help.advancedAiTitle')}</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>{t('app.help.advancedAi1')}</li>
                      <li>{t('app.help.advancedAi2')}</li>
                      <li>{t('app.help.advancedAi3')}</li>
                      <li>{t('app.help.advancedAi4')}</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">{t('app.help.advancedThemeTitle')}</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>{t('app.help.advancedTheme1')}</li>
                      <li>{t('app.help.advancedTheme2')}</li>
                      <li>{t('app.help.advancedTheme3')}</li>
                      <li>{t('app.help.advancedTheme4')}</li>
                      <li>{t('app.help.advancedTheme5')}</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">{t('app.help.advancedExportTitle')}</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>{t('app.help.advancedExport1')}</li>
                      <li>{t('app.help.advancedExport2')}</li>
                      <li>{t('app.help.advancedExport3')}</li>
                      <li>{t('app.help.advancedExport4')}</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">{t('app.help.advancedSubtitleTitle')}</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>{t('app.help.advancedSubtitle1')}</li>
                      <li>{t('app.help.advancedSubtitle2')}</li>
                      <li>{t('app.help.advancedSubtitle3')}</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">{t('app.help.advancedCardTitle')}</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>{t('app.help.advancedCard1')}</li>
                      <li>{t('app.help.advancedCard2')}</li>
                      <li>{t('app.help.advancedCard3')}</li>
                    </ul>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <div className="space-y-8">
          {/* Step 1 · 准备素材 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">1</span>
                {t('app.step1.title')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/* ffmpeg 未安装提示 */}
              {ffmpegInstalled === false && (
                <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg dark:bg-yellow-900/20 dark:border-yellow-800">
                  <div className="flex items-start gap-2">
                    <span className="text-yellow-600 dark:text-yellow-400">⚠️</span>
                    <div className="text-sm">
                      <p className="font-medium text-yellow-800 dark:text-yellow-300">{t('app.step1.ffmpegMissing')}</p>
                      <p className="text-yellow-700 dark:text-yellow-400 mt-1">
                        {t('app.step1.ffmpegHelp')}
                      </p>
                      <a
                        href="https://ffmpeg.org/download.html"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-yellow-800 underline hover:text-yellow-900 dark:text-yellow-300 dark:hover:text-yellow-200"
                      >
                        {t('app.step1.ffmpegDownload')}
                      </a>
                    </div>
                  </div>
                </div>
              )}

              {/* 合并/独立模式切换 */}
              {processingPhase === "idle" && (
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-xs text-gray-500 dark:text-gray-400">{t('app.step1.outputMode') || '输出模式'}:</span>
                  <button
                    onClick={() => setMergeMode(true)}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${mergeMode ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'}`}
                  >
                    {t('app.step1.modeMerge') || '合并牌组'}
                  </button>
                  <button
                    onClick={() => setMergeMode(false)}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${!mergeMode ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'}`}
                  >
                    {t('app.step1.modeIndependent') || '独立牌组'}
                  </button>
                </div>
              )}

              {/* 文件上传 */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* 左侧：文件上传 */}
                <div className="lg:col-span-2 space-y-4">
                  <FileUpload
                    accept=".mp4,.mkv,.avi,.mov,.webm"
                    onFilesSelect={(files) => {
                      setVideoFiles(prev => [...prev, ...Array.from(files)]);
                      transcribedVideoName.current = null;
                      setExtractedSource('');
                      setSubtitles([]);
                      setSubtitleCounts([]);
                      setSelectedIndices(new Set());
                      setRecommendations(null);
                      setCorrectionHandled(false);
                      setCorrections(null);
                      setDeselectedCorrections(new Set());
                                  }}
                    selectedFiles={videoFiles}
                    onClear={() => {
                      setVideoFiles([]);
                      setSubtitleFiles([]);
                      setSubtitleCounts([]);
                      transcribedVideoName.current = null;
                      setExtractedSource('');
                      setSubtitles([]);
                      setSelectedIndices(new Set());
                      setRecommendations(null);
                      setCorrectionHandled(false);
                      setCorrections(null);
                      setDeselectedCorrections(new Set());
                      batchTriggeredRef.current = false;
                      setIsBatchProcessing(false);
                      setBatchDone(false);
                                  }}
                    label={t('app.step1.videoFile')}
                    icon="video"
                    multiple
                  />

                  {/* 视频列表 */}
                  {videoFiles.length > 0 && (
                    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 dark:bg-gray-800">
                          <tr>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 w-8">#</th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">{t('app.step1.batchColVideo') || '视频文件'}</th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">{t('app.step1.batchColSubtitle') || '字幕文件'}</th>
                            <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 w-12">{t('app.step1.batchColAction') || '操作'}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                          {videoFiles.map((vf, i) => (
                            <tr key={i}>
                              <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                              <td className="px-3 py-2 font-medium text-gray-800 dark:text-gray-200 truncate max-w-[200px]" title={vf.name}>{vf.name}</td>
                              <td className="px-3 py-2">
                                {subtitleFiles[i] ? (
                                  <div className="flex items-center gap-1">
                                    <span className="text-green-600 dark:text-green-400 truncate max-w-[140px]" title={subtitleFiles[i]!.name}>{subtitleFiles[i]!.name}</span>
                                    <button
                                      onClick={() => {
                                        setSubtitleFiles(prev => { const next = [...prev]; next[i] = null; return next; });
                                      }}
                                      className="text-gray-400 hover:text-red-500 flex-shrink-0"
                                    >
                                      <X className="w-3 h-3" />
                                    </button>
                                  </div>
                                ) : (
                                  <label className="flex items-center gap-1 text-yellow-600 dark:text-yellow-400 text-xs cursor-pointer hover:text-yellow-800 dark:hover:text-yellow-300">
                                    <input
                                      type="file"
                                      accept=".srt,.ass,.vtt,.ssa,.sub"
                                      className="hidden"
                                      onChange={(e) => {
                                        const file = e.target.files?.[0];
                                        if (file) {
                                          setSubtitleFiles(prev => { const next = [...prev]; next[i] = file; return next; });
                                        }
                                      }}
                                    />
                                    <span>{t('app.step1.willAutoTranscribe') || '将自动转录'}</span>
                                    <span className="text-blue-500 ml-1">({t('app.step1.optionalSelectSub') || '可选字幕'})</span>
                                  </label>
                                )}
                              </td>
                              <td className="px-3 py-2 text-center">
                                <button
                                  onClick={() => {
                                    setVideoFiles(prev => prev.filter((_, j) => j !== i));
                                    setSubtitleFiles(prev => prev.filter((_, j) => j !== i));
                                  }}
                                  className="text-red-400 hover:text-red-600"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* ASR 引擎 + Whisper 模型选择器（有未配字幕的视频时显示） */}
                  {videoFiles.some((_, i) => !subtitleFiles[i]) && !isTranscribing && (
                    <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 space-y-3 dark:border-gray-600 dark:bg-gray-800">
                      {/* ASR 引擎选择 */}
                      <div>
                        <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                          {t('app.step1.asrEngineLabel')}
                        </p>
                        <div className="flex gap-2">
                          {([{
                            key: 'faster_whisper' as ASREngine, label: t('app.step1.asrEngineFasterWhisper'), hint: ''
                          }, {
                            key: 'bcut' as ASREngine, label: t('app.step1.asrEngineBcut'), hint: t('app.step1.asrEngineBcutHint')
                          }] as const).map(e => (
                            <label
                              key={e.key}
                              className={`flex-1 flex flex-col items-center gap-1 p-2 rounded cursor-pointer border text-center transition-colors ${
                                asrEngine === e.key
                                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 dark:border-primary-400'
                                  : 'border-gray-200 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700'
                              }`}
                            >
                              <input
                                type="radio"
                                name="asrEngine"
                                value={e.key}
                                checked={asrEngine === e.key}
                                onChange={() => setAsrEngine(e.key)}
                                className="hidden"
                              />
                              <span className="font-medium text-xs">{e.label}</span>
                              {e.hint && (
                                <span className="text-xs text-gray-400 dark:text-gray-500">{e.hint}</span>
                              )}
                            </label>
                          ))}
                        </div>
                      </div>

                      {/* Whisper 模型选择（仅本地引擎时显示） */}
                      {asrEngine === 'faster_whisper' && (
                        <div className="space-y-2">
                          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                            {t('app.step1.whisperModelHint')}
                          </p>
                          {WHISPER_MODELS.map(m => (
                            <label
                              key={m.key}
                              className={`flex items-center gap-3 p-2 rounded cursor-pointer border transition-colors ${
                                whisperModel === m.key
                                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 dark:border-primary-400'
                                  : 'border-gray-200 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700'
                              }`}
                            >
                              <input
                                type="radio"
                                name="whisperModel"
                                value={m.key}
                                checked={whisperModel === m.key}
                                onChange={() => setWhisperModel(m.key)}
                                className="w-4 h-4 text-primary-600"
                              />
                              <div className="flex-1">
                                <span className="font-medium text-sm">{m.label}</span>
                                <span className="text-xs text-gray-500 ml-2 dark:text-gray-400">{m.size}</span>
                              </div>
                              <span className="text-xs text-gray-400 dark:text-gray-500">{m.speed}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 转录进度 */}
                  {isTranscribing && (
                    <div className="space-y-1">
                      <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-600">
                        <div
                          className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                          style={{ width: `${transcribeAnimProgress}%` }}
                        />
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400">{transcribeMessage}</p>
                      {whisperText && (
                        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
                          {t('app.step1.transcribing', { text: whisperText })}
                        </p>
                      )}
                    </div>
                  )}

                  {/* 已提取内嵌字幕提示 */}
                  {extractedSource && (
                    <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 px-3 py-2 rounded border border-green-200 dark:text-green-400 dark:bg-green-900/30 dark:border-green-800">
                      <span className="flex-1">{extractedSource}</span>
                      <button
                        className="text-xs text-gray-500 underline hover:text-gray-700 shrink-0 dark:text-gray-400 dark:hover:text-gray-200"
                        onClick={() => { setExtractedSource(''); }}
                      >
                        {t('app.step1.useWhisperInstead')}
                      </button>
                    </div>
                  )}

                  {/* 字幕处理配置 */}
                  <div className="p-4 bg-gray-50 rounded-lg space-y-3 dark:bg-gray-800">
                    <div className="text-xs font-medium text-gray-600 dark:text-gray-400">{t('app.step1.subtitleConfigTitle')}</div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.paddingStart')}</label>
                        <input
                          type="number"
                          step="100"
                          min="100"
                          max="1000"
                          value={paddingStartMs}
                          onChange={(e) => setPaddingStartMs(parseInt(e.target.value) || 200)}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.paddingEnd')}</label>
                        <input
                          type="number"
                          step="100"
                          min="100"
                          max="1000"
                          value={paddingEndMs}
                          onChange={(e) => setPaddingEndMs(parseInt(e.target.value) || 200)}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* 右侧：内容语言 + AI 配置 */}
                <div className="space-y-6">
                  {/* 内容语言（始终可见） */}
                  <div className="space-y-3">
                    <div className="text-sm font-medium text-gray-700 dark:text-gray-300">{t('app.step1.languageSettings')}</div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.sourceLanguage')}</label>
                        <select
                          value={sourceLanguage}
                          onChange={(e) => setSourceLanguage(e.target.value)}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        >
                          {LANGUAGE_CODES.map(code => (
                            <option key={code} value={code}>{t(`app.lang.${code}`)}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.targetLanguage')}</label>
                        <select
                          value={targetLanguage}
                          onChange={(e) => setTargetLanguage(e.target.value)}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        >
                          {LANGUAGE_CODES.map(code => (
                            <option key={code} value={code}>{t(`app.lang.${code}`)}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* AI 配置 */}
                  <div className="space-y-4">
                  <div className="text-sm font-medium text-gray-700 dark:text-gray-300">{t('app.step1.aiConfigTitle')}</div>
                  {/* 折叠时显示摘要 */}
                  {!configExpanded && (
                    <div
                      className="flex items-center justify-between cursor-pointer p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors dark:bg-gray-800 dark:hover:bg-gray-700"
                      onClick={() => setConfigExpanded(true)}
                    >
                      <span className="text-sm text-gray-600 truncate dark:text-gray-400">
                        {modelName}
                        {apiKey ? ` / ***${apiKey.slice(-4)}` : ` / ${t('app.step1.noApiKey')}`}
                      </span>
                      <ChevronDown className="w-4 h-4 text-gray-400 shrink-0 dark:text-gray-500" />
                    </div>
                  )}
                  {/* 展开时显示完整配置 */}
                  {configExpanded && (
                    <div className="space-y-3 p-4 bg-gray-50 rounded-lg dark:bg-gray-800">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.apiBase')}</label>
                        <input
                          type="text"
                          value={apiBase}
                          onChange={(e) => setApiBase(e.target.value)}
                          placeholder="https://api.deepseek.com"
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.modelName')}</label>
                        <input
                          type="text"
                          value={modelName}
                          onChange={(e) => setModelName(e.target.value)}
                          placeholder="deepseek-chat"
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.apiKey')}</label>
                        <input
                          type="password"
                          value={apiKey}
                          onChange={(e) => { setApiKey(e.target.value); setTestResult(null); }}
                          placeholder={t('app.step1.apiKeyPlaceholder')}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step1.aiConcurrency')} (默认 3)</label>
                        <input
                          type="number"
                          min={1}
                          max={20}
                          value={aiConcurrency}
                          onChange={(e) => setAiConcurrency(parseInt(e.target.value) || 3)}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={handleTestConnection}
                          disabled={isTesting || !apiKey}
                        >
                          {isTesting ? t('app.step1.testing') : t('app.step1.testConnection')}
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={handleListModels}
                          disabled={!apiKey}
                        >
                          {t('app.step1.modelList')}
                        </Button>
                      </div>
                      {testResult && (
                        <p className={`text-xs ${testResult.valid ? 'text-green-600' : 'text-red-600'}`}>
                          {testResult.message}
                        </p>
                      )}
                      {modelList && modelList.length > 0 && (
                        <div className="max-h-24 overflow-y-auto border border-gray-200 rounded p-1 dark:border-gray-600">
                          {modelList.map(m => (
                            <button
                              key={m}
                              onClick={() => { setModelName(m); setModelList(null); }}
                              className={`block w-full text-left px-2 py-1 text-xs rounded hover:bg-gray-100 dark:hover:bg-gray-700 ${
                                m === modelName ? 'bg-primary-50 text-primary-700 font-medium dark:bg-primary-900/30 dark:text-primary-300' : 'text-gray-600 dark:text-gray-400'
                              }`}
                            >
                              {m}
                            </button>
                          ))}
                        </div>
                      )}
                      {modelList && modelList.length === 0 && (
                        <p className="text-xs text-red-500">{t('app.step1.modelListFailed')}</p>
                      )}
                      <div className="mt-1 flex justify-end">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setConfigExpanded(false)}
                        >
                          <ChevronUp className="w-4 h-4 mr-1" />
                          {t('app.step1.collapseConfig')}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
                </div>
              </div>

              {/* 确认操作行 */}
              <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-3 flex-wrap">
                  {/* 状态指示 */}
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    videoFiles.length > 0
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
                  }`}>
                    {videoFiles.length > 0 ? `✓ ${videoFiles.length}` : '○'} {t('app.step1.videoReady')}
                  </span>
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    subtitles.length > 0
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : subtitleFiles.some(f => f !== null)
                        ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                        : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
                  }`}>
                    {subtitles.length > 0 ? `✓ ${t('app.step1.subtitlesReady', { count: subtitles.length })}` : subtitleFiles.some(f => f !== null) ? `○ ${t('app.step1.subtitlesPending')}` : `○ ${t('app.step1.subtitleLabel')}`}
                  </span>

                  <div className="flex-1" />

                  {/* 操作按钮 */}
                  {subtitles.length > 0 ? (
                    <span className="text-sm text-green-600 dark:text-green-400 font-medium">{t('app.step1.subtitlesReadyGoNext')}</span>
                  ) : subtitleFiles.some(f => f !== null) ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleLoadSubtitles}
                      disabled={processingPhase !== "idle"}
                    >
                      {t('app.step1.loadSubtitles')}
                    </Button>
                  ) : videoFiles.length > 0 ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleTranscribe}
                      disabled={processingPhase !== "idle" || isTranscribing || checkingEmbedded}
                    >
                      {checkingEmbedded ? t('app.step1.checkingEmbedded') : isTranscribing ? t('app.step1.transcribingStatus') : t('app.step1.generateSubtitles')}
                    </Button>
                  ) : (
                    <span className="text-sm text-gray-400 dark:text-gray-500">{t('app.step1.uploadVideoFirst')}</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* AI 字幕修正面板 — 筛选前显示（可选） */}
          {selectedIndices.size > 0 && !!apiKey && workflowPhase === 'idle' && !correctionHandled && (
            <Card className="border-dashed border-primary-300 dark:border-primary-700">
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="text-sm font-medium text-gray-900 dark:text-gray-100">{t('app.step2.correctTitle')}</h4>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{t('app.step2.correctDesc')}</p>
                  </div>
                  <Button variant="secondary" size="sm" onClick={handleAICorrect}>
                    {t('app.step2.correctButton')}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* AI 修正进行中 */}
          {workflowPhase === 'correcting' && (
            <Card>
              <CardContent className="py-4">
                <div className="flex items-center gap-3">
                  <div className="animate-spin w-5 h-5 border-2 border-primary-500 border-t-transparent rounded-full" />
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{t('app.step2.correcting')}</p>
                    {correctBatch > 0 && (
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {t('app.step2.correctProgress', { batch: correctBatch })}
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* AI 修正完成 — diff 预览 + 应用/跳过 */}
          {workflowPhase === 'corrected' && corrections && (() => {
            // 只统计真正有变化的条目
            const changedItems = subtitles.filter(s => {
              if (!selectedIndices.has(s.index)) return false;
              const corrected = corrections.get(s.index);
              return corrected && corrected !== s.text;
            });
            const changedCount = changedItems.length;
            const selectedCount = changedCount - deselectedCorrections.size;
            const allSelected = deselectedCorrections.size === 0;
            return (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <CheckCircle className="w-5 h-5 text-green-500" />
                    {t('app.step2.correctDone', { count: changedCount })}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {changedCount > 0 && (
                    <div className="flex items-center gap-3 mb-3">
                      <button
                        onClick={() => setDeselectedCorrections(allSelected ? new Set(changedItems.map(s => s.index)) : new Set())}
                        className="text-xs text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
                      >
                        {allSelected ? t('app.step2.correctDeselectAll') : t('app.step2.correctSelectAll')}
                      </button>
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {t('app.step2.correctSelected', { selected: selectedCount, total: changedCount })}
                      </span>
                    </div>
                  )}
                  {/* Diff 列表 */}
                  <div className="max-h-80 overflow-y-auto space-y-2 mb-4">
                    {changedItems.map(s => {
                      const corrected = corrections.get(s.index)!;
                      const isSelected = !deselectedCorrections.has(s.index);
                      return (
                        <div key={s.index} className={`p-2 rounded text-sm flex items-start gap-2 transition-colors ${isSelected ? 'bg-gray-50 dark:bg-gray-800' : 'bg-gray-100 dark:bg-gray-900 opacity-50'}`}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleCorrection(s.index)}
                            className="mt-0.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="text-red-600 dark:text-red-400 line-through break-words">{s.text}</div>
                            <div className="text-green-700 dark:text-green-400 break-words">{corrected}</div>
                          </div>
                        </div>
                      );
                    })}
                    {changedCount === 0 && (
                      <p className="text-sm text-gray-500 dark:text-gray-400">{t('app.step2.correctNoChange')}</p>
                    )}
                  </div>
                  {/* 操作按钮 */}
                  <div className="flex gap-3">
                    <Button variant="primary" size="sm" onClick={handleApplyCorrections} disabled={selectedCount === 0}>
                      {t('app.step2.correctApply')} ({selectedCount})
                    </Button>
                    <Button variant="ghost" size="sm" onClick={handleSkipCorrections}>
                      {t('app.step2.correctSkip')}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })()}

          {/* Step 2 · 筛选字幕（修正进行中/完成时隐藏） */}
          {subtitles.length > 0 && workflowPhase !== 'correcting' && workflowPhase !== 'corrected' && (
            <div ref={step2Ref}>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">2</span>
                  {apiKey ? t('app.step2.title') : t('app.step2.titleNoAI')}
                  <span className="text-sm font-normal text-gray-500 ml-2 dark:text-gray-400">
                    ({t('app.step2.countInfo', { selected: filteredSubtitles.filter(s => selectedIndices.has(s.index)).length, total: filteredSubtitles.length, grandTotal: subtitles.length })})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {/* 规则筛选（前置） */}
                <div className="flex flex-wrap items-end gap-3 mb-4 p-3 bg-gray-50 rounded-lg dark:bg-gray-800/50">
                  <div className="flex items-center gap-1.5">
                    <label className="text-xs text-gray-500 dark:text-gray-400">{t('app.step2.duration')}</label>
                    <input
                      type="number"
                      value={filterMinDuration}
                      onChange={e => setFilterMinDuration(Math.max(0, Number(e.target.value)))}
                      className="w-14 px-1.5 py-1 border border-gray-300 rounded text-sm text-center dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                      min={0}
                      step={0.5}
                    />
                    <span className="text-xs text-gray-400">-</span>
                    <input
                      type="number"
                      value={filterMaxDuration}
                      onChange={e => setFilterMaxDuration(Math.max(0, Number(e.target.value)))}
                      className="w-14 px-1.5 py-1 border border-gray-300 rounded text-sm text-center dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                      min={0}
                      step={0.5}
                    />
                    <span className="text-xs text-gray-400">{t('app.step2.secondsUnit')}</span>
                  </div>

                  {recommendations && learnedWords.size > 0 && (
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={filterExcludeLearned}
                        onChange={e => setFilterExcludeLearned(e.target.checked)}
                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span className="text-xs text-gray-600 dark:text-gray-400">{t('app.step2.excludeLearned')}</span>
                    </label>
                  )}
                  <button
                    onClick={() => syncFromAnki()}
                    disabled={syncingFromAnki}
                    className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
                    title={t('app.step2.syncFromAnkiHelp')}
                  >
                    <RefreshCw className={`w-3 h-3 ${syncingFromAnki ? 'animate-spin' : ''}`} />
                    {syncingFromAnki ? t('app.step2.syncingFromAnki') : t('app.step2.syncFromAnki')}
                  </button>
                  <button
                    onClick={() => syncFromAnki(true)}
                    disabled={syncingFromAnki}
                    className="text-xs text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 underline disabled:opacity-50"
                    title={t('app.step2.fullSyncHelp')}
                  >
                    {t('app.step2.fullSync')}
                  </button>

                  <div className="flex items-center gap-1.5 flex-1 min-w-[160px]">
                    <label className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">{t('app.step2.excludeWords')}</label>
                    <input
                      type="text"
                      value={filterBlacklist}
                      onChange={e => setFilterBlacklist(e.target.value)}
                      className="flex-1 px-2 py-1 border border-gray-300 rounded text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                      placeholder={t('app.step2.excludeWordsPlaceholder')}
                    />
                  </div>

                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {t('app.step2.showFiltered', { filtered: filteredSubtitles.length, total: subtitles.length })}
                  </span>
                </div>

                {/* 工具栏 */}
                <div className="flex items-center gap-2 mb-4">
                  {!!apiKey && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleAIScreen}
                      disabled={isRecommending || processingPhase !== "idle" || workflowPhase === 'annotating'}
                    >
                      <Sparkles className="w-4 h-4 mr-2" />
                      {workflowPhase === 'screening'
                        ? recommendTotalBatches > 0
                          ? t('app.step2.aiScreeningBatch', { batch: recommendBatch, total: recommendTotalBatches })
                          : t('app.step2.aiScreening')
                        : t('app.step2.aiScreenButton')}
                    </Button>
                  )}
                  {workflowPhase === 'screening' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => abortControllerRef.current?.abort()}
                    >
                      {t('app.step2.stop')}
                    </Button>
                  )}
                  {!!apiKey && (
                    <Button
                      variant={selectRecommendedOnly ? 'primary' : 'ghost'}
                      size="sm"
                      onClick={() => {
                        if (selectRecommendedOnly) {
                          // 关闭：恢复选中全部字幕
                          const allDefault = new Set<number>();
                          filteredSubtitles?.forEach(s => allDefault.add(s.index));
                          setSelectedIndices(allDefault);
                          setSelectRecommendedOnly(false);
                        } else {
                          // 开启：只选推荐项
                          const recommended = new Set<number>();
                          recommendations?.forEach((r, idx) => {
                            if (r.include && !r.reason?.startsWith(t('app.error.processingFailed'))) {
                              recommended.add(idx);
                            }
                          });
                          setSelectedIndices(recommended);
                          setSelectRecommendedOnly(true);
                        }
                      }}
                      disabled={isRecommending}
                    >
                      {t('app.step2.selectRecommendedOnly')}
                    </Button>
                  )}
                  {filteredSubtitles.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={invertSelection}
                    >
                      {t('app.step2.invertSelection')}
                    </Button>
                  )}
                  {failedIndices.size > 0 && workflowPhase !== 'screening' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleRetryFailed}
                      disabled={isRecommending}
                      className="text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                    >
                      {t('app.step2.retryFailed', { count: failedIndices.size })}
                    </Button>
                  )}
                  {!!apiKey && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowPromptEditor(!showPromptEditor)}
                    >
                      {showPromptEditor ? (
                        <ChevronUp className="w-4 h-4 mr-1" />
                      ) : (
                        <ChevronDown className="w-4 h-4 mr-1" />
                      )}
                      {t('app.step2.promptToggle')}
                    </Button>
                  )}
                </div>

                {/* 提示词编辑器（仅筛选标准） */}
                {showPromptEditor && (
                  <div className="mb-4 p-4 bg-gray-50 rounded-lg space-y-3 dark:bg-gray-800">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step2.promptPreset')}</label>
                      <div className="flex gap-2">
                        {(Object.keys(presetTemplates) as PresetKey[]).map((key) => (
                          <button
                            key={key}
                            onClick={() => {
                              setPromptPreset(key);
                              setCustomPrompt(buildPresetPrompt(presetTemplates[key].prompt, sourceLanguage));
                            }}
                            disabled={isRecommending}
                            className={`px-3 py-1.5 rounded text-sm font-medium border transition-colors ${
                              promptPreset === key
                                ? 'bg-primary-500 text-white border-primary-500'
                                : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                            }`}
                          >
                            {presetTemplates[key].label}
                          </button>
                        ))}
                        <button
                          onClick={() => setCustomPrompt(buildPresetPrompt(presetTemplates[promptPreset].prompt, sourceLanguage))}
                          disabled={isRecommending}
                          className="ml-auto px-2 py-1.5 text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded hover:bg-gray-50 dark:text-gray-500 dark:hover:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700 disabled:opacity-50"
                          title={t('app.step2.resetDefault')}
                        >
                          <RotateCcw className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step2.promptContentLabel')}</label>
                      <textarea
                        value={customPrompt}
                        onChange={(e) => setCustomPrompt(e.target.value)}
                        rows={4}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm font-mono dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        placeholder={t('app.step2.promptPlaceholder')}
                        disabled={isRecommending}
                      />
                    </div>
                  </div>
                )}

                {/* 字幕表格 */}
                <SubtitleTable
                  subtitles={filteredSubtitles}
                  selectedIndices={selectedIndices}
                  onToggleSelection={toggleSelection}
                  onSelectAll={toggleSelectAll}
                  isAllSelected={filteredSubtitles.length > 0 && filteredSubtitles.every(s => selectedIndices.has(s.index))}
                  recommendations={recommendations}
                  isRecommending={isRecommending}
                  recommendBatch={recommendBatch}
                  recommendTotalBatches={recommendTotalBatches}
                  learnedWords={learnedWords}
                />

                {/* 筛选完成提示 */}
                {workflowPhase === 'screened' && recommendations && (
                  <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg dark:bg-green-900/20 dark:border-green-800">
                    <p className="text-sm text-green-700 dark:text-green-300">
                      {t('app.step2.screeningDone', { count: Array.from(recommendations.values()).filter(r => r.include).length })}
                    </p>
                    <PreheatIndicator taskId={taskId} />
                  </div>
                )}
              </CardContent>
            </Card>
            </div>
          )}


          {/* Step 3 · AI 注释（需要 API Key，修正进行中/完成时隐藏） */}
          {selectedIndices.size > 0 && !!apiKey && workflowPhase !== 'correcting' && workflowPhase !== 'corrected' && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">3</span>
                  {t('app.step3.title')}
                  <span className="text-sm font-normal text-gray-500 ml-2 dark:text-gray-400">
                    ({t('app.step3.countInfo', { count: selectedIndices.size })})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>

                {/* 3a: 选择用途（注释进行中/完成时隐藏，但仅机器翻译完成时仍可选） */}
                {(workflowPhase !== 'annotating' && (workflowPhase !== 'annotated' || annotationPurpose === null)) && (
                  <>
                  {/* 注释提示词编辑器 */}
                  <div className="mb-4">
                    <button
                      onClick={() => setShowAnnotationPromptEditor(!showAnnotationPromptEditor)}
                      className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    >
                      {showAnnotationPromptEditor ? (
                        <ChevronUp className="w-3 h-3" />
                      ) : (
                        <ChevronDown className="w-3 h-3" />
                      )}
                      {t('app.step3.annotationPrompt')}
                    </button>
                    {showAnnotationPromptEditor && (
                      <div className="mt-2 p-4 bg-gray-50 rounded-lg space-y-3 dark:bg-gray-800">
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step3.promptPreset')}</label>
                          <div className="flex gap-2">
                            {(Object.keys(annotationTemplates) as AnnotationPresetKey[]).map((key) => (
                              <button
                                key={key}
                                onClick={() => {
                                  setAnnotationPreset(key);
                                  setAnnotationPrompt(buildAnnotationPrompt(annotationTemplates[key].prompt, sourceLanguage, targetLanguage));
                                }}
                                className={`px-3 py-1.5 rounded text-sm font-medium border transition-colors ${
                                  annotationPreset === key
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                                }`}
                              >
                                {annotationTemplates[key].label}
                              </button>
                            ))}
                            <button
                              onClick={() => setAnnotationPrompt(buildAnnotationPrompt(annotationTemplates[annotationPreset].prompt, sourceLanguage, targetLanguage))}
                              className="ml-auto px-2 py-1.5 text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded hover:bg-gray-50 dark:text-gray-500 dark:hover:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700"
                              title={t('app.step2.resetDefault')}
                            >
                              <RotateCcw className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">{t('app.step3.promptContentLabel')}</label>
                          <textarea
                            value={annotationPrompt}
                            onChange={(e) => setAnnotationPrompt(e.target.value)}
                            rows={4}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm font-mono dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                            placeholder={t('app.step3.promptPlaceholder')}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <button
                      onClick={() => handleAIAnnotate('grammar')}
                      disabled={processingPhase !== "idle" || workflowPhase === 'screening'}
                      className="p-4 rounded-lg border-2 text-left transition-all border-gray-200 hover:border-primary-300 cursor-pointer dark:border-gray-700 dark:hover:border-primary-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <BookOpen className="w-5 h-5 text-primary-600 dark:text-primary-400" />
                        <span className="font-medium text-gray-900 dark:text-gray-100">{t('app.step3.modeGrammar')}</span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {t('app.step3.modeGrammarDesc')}
                      </p>
                    </button>
                    <button
                      onClick={() => handleAIAnnotate('vocab')}
                      disabled={processingPhase !== "idle" || workflowPhase === 'screening'}
                      className="p-4 rounded-lg border-2 text-left transition-all border-gray-200 hover:border-primary-300 cursor-pointer dark:border-gray-700 dark:hover:border-primary-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <GraduationCap className="w-5 h-5 text-primary-600 dark:text-primary-400" />
                        <span className="font-medium text-gray-900 dark:text-gray-100">{t('app.step3.modeVocab')}</span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {t('app.step3.modeVocabDesc')}
                      </p>
                    </button>
                  </div>
                  </>
                )}

                {/* 3b: 注释进行中 */}
                {workflowPhase === 'annotating' && (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <div className="animate-spin w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full" />
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {t('app.step3.annotating', {
                          mode: annotationPurpose === 'grammar' ? t('app.step3.modeGrammar') : t('app.step3.modeVocab'),
                          batch: annotateBatch,
                          total: annotateTotalBatches,
                        })}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => abortControllerRef.current?.abort()}
                      >
                        {t('app.step3.stop')}
                      </Button>
                    </div>
                    {annotateTotalBatches > 0 && (
                      <ProgressBar progress={(annotateBatch / annotateTotalBatches) * 100} />
                    )}
                    <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
                      {t('app.step3.annotatingHint')}
                    </p>
                  </div>
                )}

                {/* 3c: 注释完成（仅当使用了 AI 注释时显示，机器翻译不会设置 annotationPurpose） */}
                {workflowPhase === 'annotated' && annotationPurpose !== null && (
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className="p-3 bg-green-50 border border-green-200 rounded-lg dark:bg-green-900/20 dark:border-green-800 flex-1">
                        <p className="text-sm text-green-700 dark:text-green-300">
                          {t('app.step3.annotatedDone', {
                            count: selectedIndices.size,
                            mode: annotationPurpose === 'grammar' ? t('app.step3.modeGrammar') : t('app.step3.modeVocab'),
                          })}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setWorkflowPhase('screened');
                          setAnnotationPurpose(null);
                        }}
                      >
                        {t('app.step3.reselect')}
                      </Button>
                    </div>

                  </div>
                )}

              </CardContent>
            </Card>
          )}

          {/* Step 3 · 机器翻译（始终可见，有 AI Key 时可折叠） */}
          {selectedIndices.size > 0 && (
            <Card className={apiKey ? 'border-dashed' : ''}>
              <div
                className={apiKey ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50 rounded-t-xl' : ''}
                onClick={apiKey ? () => setMtCollapsed(!mtCollapsed) : undefined}
              >
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {apiKey && (
                    mtCollapsed ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronUp className="w-4 h-4 text-gray-400" />
                  )}
                  {!apiKey && (
                    <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">3</span>
                  )}
                  {t('app.step3.mtTitle')}
                  <span className="text-sm font-normal text-gray-500 ml-2 dark:text-gray-400">
                    ({t('app.step3.countInfo', { count: selectedIndices.size })})
                  </span>
                  {apiKey && mtCollapsed && (
                    <span className="text-xs text-gray-400 ml-auto dark:text-gray-500">{t('app.step3.mtCollapsedHint')}</span>
                  )}
                </CardTitle>
              </CardHeader>
              </div>
              {(!apiKey || !mtCollapsed) && (
              <CardContent>
                {(workflowPhase !== 'annotating' && workflowPhase !== 'annotated') && (
                  <div className="space-y-4">
                    {apiKey && (
                      <p className="text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 p-2 rounded">
                        {t('app.step3.mtHasAiHint')}
                      </p>
                    )}
                    <p className="text-sm text-gray-500 dark:text-gray-400">{t('app.step3.mtDesc')}</p>
                    {/* 翻译服务选择 */}
                    <div>
                      <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                        {t('app.step3.translateService')}
                      </p>
                      <div className="grid grid-cols-3 gap-2">
                        {([
                          { key: 'bing' as TranslateService, label: 'Bing', sub: t('app.step3.mtFree') },
                          { key: 'google' as TranslateService, label: 'Google', sub: t('app.step3.mtBackup') },
                          { key: 'deepl' as TranslateService, label: 'DeepL', sub: t('app.step3.mtNeedKey') },
                        ] as const).map(e => (
                          <label
                            key={e.key}
                            className={`flex flex-col items-center gap-0.5 p-2 rounded cursor-pointer border text-center transition-colors ${
                              mtService === e.key
                                ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 dark:border-primary-400'
                                : 'border-gray-200 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700'
                            }`}
                          >
                            <input
                              type="radio"
                              name="mtService"
                              value={e.key}
                              checked={mtService === e.key}
                              onChange={() => setMtService(e.key)}
                              className="hidden"
                            />
                            <span className="font-medium text-xs">{e.label}</span>
                            <span className="text-[10px] text-gray-400 dark:text-gray-500">{e.sub}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                    {/* DeepL API Key 输入 */}
                    {mtService === 'deepl' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">
                          DeepL API Key
                        </label>
                        <input
                          type="password"
                          value={deeplApiKey}
                          onChange={(e) => setDeeplApiKey(e.target.value)}
                          placeholder={t('app.step3.deeplKeyPlaceholder')}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                        <p className="text-[10px] text-gray-400 mt-1 dark:text-gray-500">
                          {t('app.step3.deeplKeyHint')}
                        </p>
                      </div>
                    )}
                    <button
                      onClick={handleMTTranslate}
                      disabled={processingPhase !== 'idle'}
                      className="w-full p-4 rounded-lg border-2 text-center transition-all border-primary-300 hover:border-primary-500 hover:bg-primary-50 dark:border-primary-700 dark:hover:bg-primary-900/30 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <div className="flex items-center justify-center gap-2 mb-1">
                        <Sparkles className="w-5 h-5 text-primary-600 dark:text-primary-400" />
                        <span className="font-medium text-gray-900 dark:text-gray-100">{t('app.step3.translateButton', { count: selectedIndices.size })}</span>
                      </div>
                    </button>
                  </div>
                )}
                {/* 翻译进行中 */}
                {workflowPhase === 'annotating' && (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <div className="animate-spin w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full" />
                      <span className="text-sm text-gray-600 dark:text-gray-400">{t('app.step3.translating')}</span>
                    </div>
                  </div>
                )}
                {/* 翻译完成（仅当使用了机器翻译时显示，即 annotationPurpose 为 null） */}
                {workflowPhase === 'annotated' && annotationPurpose === null && (
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className="p-3 bg-green-50 border border-green-200 rounded-lg dark:bg-green-900/20 dark:border-green-800 flex-1">
                        <p className="text-sm text-green-700 dark:text-green-300">
                          {t('app.step3.translatedDone', { count: selectedIndices.size })}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setWorkflowPhase('screened');
                          setAnnotationPurpose(null);
                        }}
                      >
                        {t('app.step3.reselect')}
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
              )}
            </Card>
          )}

          {/* Step 4 · 样式选择与处理 */}
          {((workflowPhase === 'annotated' || workflowPhase === 'screened' || (workflowPhase === 'idle' && !recommendations && subtitles.length > 0)) || processingPhase !== 'idle' || (result && result.length > 0)) && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">4</span>
                  {t('app.step4.title')}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {/* 4a: 处理媒体按钮 */}
                {processingPhase === 'idle' && !(result && result.length > 0) && (
                  <div className="space-y-4">
                    {!recommendations && (
                      <p className="text-xs text-gray-400 dark:text-gray-500">{t('app.step4.noAiNote')}</p>
                    )}
                    <Button
                      variant="primary"
                      className="w-full"
                      onClick={handleProcessMedia}
                    >
                      {t('app.step4.processMedia', { count: selectedIndices.size })}
                    </Button>
                    {selectedIndices.size === 0 && (
                      <p className="text-xs text-amber-600 dark:text-amber-400">{t('app.step4.needSelectSubtitles', '请至少在步骤 2 中选中一条字幕')}</p>
                    )}
                  </div>
                )}

                {/* 4b: 媒体处理进度 */}
                {processingPhase === 'media_processing' && (
                  <div className="space-y-3">
                    <ProcessingStatus
                      steps={processingSteps}
                      currentStepIndex={currentStep}
                      message={processingMessage}
                    />
                    <ProgressBar progress={(currentStep + 1) / MEDIA_PROCESSING_STEPS.length * 100} />
                  </div>
                )}

                {/* 4c: 样式预览（真实截图）+ 生成牌组按钮 */}
                {processingPhase === 'awaiting_styles' && (
                  <div className="space-y-4">
                    <StyleThemeSelector cardStyles={cardStyles} setCardStyles={setCardStyles} cardTheme={cardTheme} setCardTheme={handleSetCardTheme} showEditor={editingStyles} onToggleEditor={handleToggleEditor} customThemes={customThemes} onImportClick={() => setShowThemeImporter(true)} onBrowseClick={() => setShowMarketplace(true)} onDeleteTheme={handleDeleteTheme} onAIGenerateClick={async () => {
                      const isCustom = customThemes.some(t => t.name === cardTheme);
                      if (isCustom) {
                        const files = await themeAPI.getCustomThemeFiles(cardTheme);
                        if (files) {
                          setStyleGenInitialTheme({ name: files.name, label: files.label, front: files.front, back: files.back, css: files.css });
                        }
                      }
                      setShowStyleGenerator(true);
                    }} />
                    <button onClick={() => { setStyleGenInitialTheme(null); setShowStyleGenerator(true); }} className="mt-2 w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-purple-500 to-pink-500 text-white hover:from-purple-600 hover:to-pink-600 transition-all shadow-md">
                      <Palette className="w-4 h-4" />
                      {t('styleGenerator.aiGenerateStyle')}
                    </button>
                    {editingStyles && processedCards && processedCards.length > 0 ? (
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                        <CssVariableEditor
                          theme={cardTheme}
                          overrides={pendingOverrides}
                          onChange={handleOverrideChange}
                          onSave={handleSaveOverrides}
                          onReset={handleResetOverrides}
                          onClose={handleToggleEditor}
                          hasUnsaved={hasUnsavedOverrides}
                        />
                        <CardPreview
                          cards={previewCards}
                          cardStyles={Array.from(cardStyles)}
                          theme={cardTheme}
                          themeOverrides={pendingOverrides}
                          currentIndex={previewIndex}
                          onPrevious={() => setPreviewIndex(Math.max(0, previewIndex - 1))}
                          onNext={() => setPreviewIndex(Math.min(previewCards.length - 1, previewIndex + 1))}
                        />
                      </div>
                    ) : (
                      <>
                        {editingStyles && (
                          <CssVariableEditor
                            theme={cardTheme}
                            overrides={pendingOverrides}
                            onChange={handleOverrideChange}
                            onSave={handleSaveOverrides}
                            onReset={handleResetOverrides}
                            onClose={handleToggleEditor}
                            hasUnsaved={hasUnsavedOverrides}
                          />
                        )}
                        {previewCards.length > 0 && (
                          <CardPreview
                            cards={previewCards}
                            cardStyles={Array.from(cardStyles)}
                            theme={cardTheme}
                            themeOverrides={editingStyles ? pendingOverrides : themeOverrides[cardTheme]}
                            currentIndex={previewIndex}
                            onPrevious={() => setPreviewIndex(Math.max(0, previewIndex - 1))}
                            onNext={() => setPreviewIndex(Math.min(previewCards.length - 1, previewIndex + 1))}
                          />
                        )}
                      </>
                    )}
                    {videoFiles.length > 1 && isBatchProcessing && (
                      <Card className="border-primary-300 dark:border-primary-700">
                        <CardContent className="py-4">
                          <div className="flex items-center gap-3">
                            <div className="animate-spin w-5 h-5 border-2 border-primary-500 border-t-transparent rounded-full" />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                                {t('app.batch.title')}
                              </p>
                              <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                                {batchStepMessage || t('app.batch.processing', { completed: batchCompleted, total: batchRemaining })}
                              </p>
                              <div className="mt-2 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
                                <div
                                  className="bg-primary-500 h-1.5 rounded-full transition-all duration-300"
                                  style={{ width: `${batchRemaining > 0 ? (batchCompleted / batchRemaining) * 100 : 0}%` }}
                                />
                              </div>
                            </div>
                            <span className="text-xs text-gray-400 flex-shrink-0">
                              {batchCompleted}/{batchRemaining}
                            </span>
                            <button
                              onClick={handleCancelBatch}
                              className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-400 hover:text-red-500 transition-colors flex-shrink-0"
                              title={t('app.batch.cancel')}
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                        </CardContent>
                      </Card>
                    )}
                    {videoFiles.length > 1 && batchCancelled && (
                      <p className="text-sm text-amber-600 dark:text-amber-400">
                        {t('app.batch.cancelled')}
                      </p>
                    )}
                    {videoFiles.length > 1 && batchDone && (
                      <p className="text-sm text-green-600 dark:text-green-400">
                        {t('app.batch.title')} — {batchCompleted}/{batchRemaining} {t('app.batch.done', '完成')}
                      </p>
                    )}
                    {batchPartialFailed && (
                      <div className="rounded-md border border-amber-400 bg-amber-50 dark:border-amber-600 dark:bg-amber-950/40 p-3 text-sm text-amber-800 dark:text-amber-300">
                        {t('app.batch.partialWarning')}
                      </div>
                    )}
                    <Button
                      variant="primary"
                      className="w-full"
                      disabled={isBatchProcessing}
                      onClick={() => {
                        console.log('[按钮点击] 状态:', { videoCount: videoFiles.length, batchDone, isBatchProcessing });
                        if (videoFiles.length > 1 && !batchDone && !isBatchProcessing) {
                          // 多视频且未批处理：先触发批处理，完成后自动打包
                          console.log('[按钮点击] 触发批处理 + 延迟打包');
                          setPendingPack(true);
                          handleTriggerBatch();
                        } else {
                          // 单视频或批处理已完成：直接打包
                          console.log('[按钮点击] 直接打包');
                          handleGenerateApkg();
                        }
                      }}
                    >
                      {videoFiles.length > 1 && !batchDone
                        ? (isBatchProcessing
                          ? t('app.batch.processing', { completed: batchCompleted, total: batchRemaining })
                          : t('app.step4.generateApkgWithBatch', { count: videoFiles.length - 1 }))
                        : t('app.step4.generateApkg', { count: processedCards?.length || 0 })}
                    </Button>
                  </div>
                )}

                {/* 4d: 打包进度 */}
                {processingPhase === 'packing' && (
                  <div className="space-y-3">
                    <ProcessingStatus
                      steps={processingSteps}
                      currentStepIndex={currentStep}
                      message={processingMessage}
                    />
                    <ProgressBar progress={(currentStep + 1) / PACK_PROCESSING_STEPS.length * 100} />
                  </div>
                )}

                {/* 4e: 处理完成：卡片预览 + 下载（两阶段模式） */}
                {processingPhase === 'completed' && result && result.length > 0 && (
                  <div className="space-y-4">
                    {batchPartialFailed && (
                      <div className="rounded-md border border-amber-400 bg-amber-50 dark:border-amber-600 dark:bg-amber-950/40 p-3 text-sm text-amber-800 dark:text-amber-300">
                        {t('app.batch.partialWarning')}
                      </div>
                    )}
                    <CardPreview
                      cards={previewResult}
                      cardStyles={Array.from(cardStyles)}
                      theme={cardTheme}
                      themeOverrides={editingStyles ? pendingOverrides : themeOverrides[cardTheme]}
                      currentIndex={previewIndex}
                      onPrevious={() => setPreviewIndex(Math.max(0, previewIndex - 1))}
                      onNext={() => setPreviewIndex(Math.min(previewResult.length - 1, previewIndex + 1))}
                    />
                    <Button variant="primary" className="w-full" onClick={handleDownload}>
                      <Download className="w-4 h-4 mr-2" />
                      {t('app.step4.downloadApkg')}
                    </Button>
                    {taskId && (
                      <Button variant="outline" size="sm" className="w-full"
                        onClick={() => downloadUrl(processAPI.exportZipUrl(taskId), `ClipLingo_${taskId}_Media.zip`)}>
                        <FolderOpen className="w-4 h-4 mr-1" />
                        {t('app.step4.exportMediaZip')}
                      </Button>
                    )}
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" className="flex-1"
                        onClick={() => {
                          const filename = videoFiles[0]?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo';
                          downloadString(generateCSVContent(result), `${filename}.csv`, 'text/csv');
                        }}>
                        <FileSpreadsheet className="w-4 h-4 mr-1" />
                        {t('app.step4.exportCsv')}
                      </Button>
                      <Button variant="outline" size="sm" className="flex-1"
                        onClick={() => {
                          const filename = videoFiles[0]?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo';
                          downloadString(generateJSONContent(result), `${filename}.json`, 'application/json');
                        }}>
                        <FileJson className="w-4 h-4 mr-1" />
                        {t('app.step4.exportJson')}
                      </Button>
                    </div>
                    <div className="flex items-center gap-2">
                      <AnkiSyncButton
                        cards={result}
                        deckName={videoFiles[0]?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo'}
                        apiBase={API_BASE_URL}
                        cardStyles={Array.from(cardStyles)}
                        theme={cardTheme}
                        themeOverrides={themeOverrides[cardTheme]}
                      />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </main>

      {/* 自定义主题导入对话框 */}
      {showThemeImporter && (
        <ThemeImporter
          onImport={handleImportTheme}
          onClose={() => setShowThemeImporter(false)}
        />
      )}
      {showMarketplace && (
        <TemplateMarketplace
          onClose={() => setShowMarketplace(false)}
          onInstalled={refreshCustomThemes}
        />
      )}
      {showStyleGenerator && (
        <StyleGenerator
          onClose={() => { setShowStyleGenerator(false); setStyleGenInitialTheme(null); }}
          onImported={refreshCustomThemes}
          initialTheme={styleGenInitialTheme || undefined}
          previewCard={processedCards && processedCards.length > 0 ? processedCards[previewIndex] : undefined}
        />
      )}
    </div>
  );
}

export default App;
