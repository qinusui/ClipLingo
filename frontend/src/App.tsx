import { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from './i18n';
import { Film, Download, Info, Sparkles, ChevronDown, ChevronUp, MessageSquare, Sun, Moon, Monitor, BookOpen, GraduationCap, FolderOpen, X, ExternalLink, RefreshCw, RotateCcw, FileSpreadsheet, FileJson, Palette } from 'lucide-react';
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
import { SubtitleItem, ProcessedCard, AIRecommendation, CardStyle, CardTheme, ThemeOverrides, WorkflowPhase, AnnotationPurpose } from './types';
import { subtitleAPI, processAPI, API_BASE_URL } from './services/api';
import { themeAPI, type ThemeListItem } from './services/themeAPI';
import { pingAnki, fetchWordsFromAnki } from './services/ankiConnect';

import { useTheme } from './hooks/useTheme';
import { getFriendlyMessage, getApiErrorMessage } from './utils/errors';

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
type ProcessingStep = { id: string; label: string; status: StepStatus; error?: string };

const PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'parse', label: i18n.t('app.processing.parseSubtitles'), status: 'pending' },
  { id: 'media', label: i18n.t('app.processing.cutAudioScreenshots'), status: 'pending' },
  { id: 'pack', label: i18n.t('app.processing.packAnkiDeck'), status: 'pending' },
];

const MEDIA_PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'parse', label: i18n.t('app.processing.parseSubtitles'), status: 'pending' },
  { id: 'media', label: i18n.t('app.processing.cutAudioScreenshots'), status: 'pending' },
];

const PACK_PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'pack', label: i18n.t('app.processing.packAnkiDeck'), status: 'pending' },
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
  } catch {}
  return null;
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
  const [correctText, setCorrectText] = useState(false);
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
    } catch {}
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
    localStorage.setItem('anki_ai_config', JSON.stringify({ apiBase, modelName, apiKey, sourceLanguage, targetLanguage, customPrompt, annotationPrompt }));
  }, [apiBase, modelName, apiKey, sourceLanguage, targetLanguage, customPrompt, annotationPrompt]);

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
    themeAPI.loadOverrides(cardTheme).then(ov => {
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

  useEffect(() => {
    const vars = themeOverrides[cardTheme] || {};
    const root = document.documentElement;
    Object.entries(vars).forEach(([k, v]) => {
      if (v) root.style.setProperty(k, v);
      else root.style.removeProperty(k);
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
  }, [workflowPhase, taskId, apiKey]);

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

  const handleOverrideChange = (overrides: ThemeOverrides) => {
    setPendingOverrides(overrides);
    setHasUnsavedOverrides(true);
    // 即时预览：把变量应用到 document
    const root = document.documentElement;
    Object.entries(overrides).forEach(([k, v]) => {
      if (v) root.style.setProperty(k, v);
      else root.style.removeProperty(k);
    });
  };

  const handleSaveOverrides = async () => {
    await themeAPI.saveOverrides(cardTheme, pendingOverrides);
    setThemeOverrides(prev => ({ ...prev, [cardTheme]: { ...pendingOverrides } }));
    setHasUnsavedOverrides(false);
  };

  const handleResetOverrides = () => {
    setPendingOverrides({});
    setHasUnsavedOverrides(true);
    const root = document.documentElement;
    Object.keys(themeOverrides[cardTheme] || {}).forEach(k => root.style.removeProperty(k));
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
        setSubtitles(result.extracted.subtitles as SubtitleItem[]);
        setSelectedIndices(new Set(result.extracted.subtitles.map((s: SubtitleItem) => s.index)));
        setRecommendations(null);
        const counts = new Array(videoFiles.length).fill(0);
        counts[0] = result.extracted.subtitles.length;
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
        alert(t('app.error.whisperNotInstalled'));
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
      const { task_id } = await subtitleAPI.startTranscribe(videoFiles[0], minDuration, sourceLanguage, whisperModel);

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

            setSubtitles(progress.result.subtitles);
            setSelectedIndices(new Set(progress.result.subtitles.map((s: SubtitleItem) => s.index)));
            setRecommendations(null);
            const counts = new Array(videoFiles.length).fill(0);
            counts[0] = progress.result.subtitles.length;
            setSubtitleCounts(counts);
            transcribedVideoName.current = videoFiles[0].name;
            scrollToStep2();
          }

          if (progress.status === 'error') {
            clearInterval(pollInterval);
            setIsTranscribing(false);
            transcribingRef.current = false;
            alert(getFriendlyMessage(progress.error_code, progress.error));
          }
        } catch (e) {
          // 轮询失败不中断
        }
      }, 1000);

      (window as any).__transcribePoll = pollInterval;

    } catch (error) {
      console.error('转录失败:', error);
      alert(t('app.error.transcribeFailed') + getApiErrorMessage(error));
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
      alert(t('app.error.needApiKey'));
      return;
    }
    if (subtitles.length === 0) {
      alert(t('app.error.needSubtitles'));
      return;
    }
    if (selectedIndices.size === 0) {
      alert(t('app.error.needSelectSentences'));
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
        alert(t('app.error.allLearned'));
        setIsRecommending(false);
        setWorkflowPhase('idle');
        return;
      }

      const stream = subtitleAPI.startScreenStream(
        screenSubs,
        apiKey,
        customPrompt || undefined,
        recommendBatchSize,
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
        correctText,
        controller.signal
      );

      for await (const event of stream) {
        if (event.type === 'start') {
          setRecommendTotalBatches(event.total_batches!);
        } else if (event.type === 'batch') {
          setRecommendBatch(event.batch!);
          setRecommendations(prev => {
            const next = new Map(prev || []);
            for (const item of event.items!) {
              next.set(item.index, item);
            }
            return next;
          });
        } else if (event.type === 'done') {
          setIsRecommending(false);
        }
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

      setWorkflowPhase('screened');

    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('AI 筛选已中止');
      } else {
        console.error('AI 筛选失败:', error);
        alert(t('app.error.aiScreenFailed') + getApiErrorMessage(error));
      }
      setIsRecommending(false);
      // 保留已有部分结果，回到 screened 状态（而非 idle）
      setRecommendations(prev => {
        if (prev && prev.size > 0) {
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
      alert(t('app.error.needApiKey'));
      return;
    }

    const selectedSubs = subtitles.filter(s => selectedIndices.has(s.index));

    if (selectedSubs.length === 0) {
      alert(t('app.error.needSelectSentencesForAnnotation'));
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
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
        controller.signal,
        taskId || undefined
      );

      for await (const event of stream) {
        if (event.type === 'start') {
          setAnnotateTotalBatches(event.total_batches!);
        } else if (event.type === 'batch') {
          setAnnotateBatch(event.batch!);
          setRecommendations(prev => {
            const next = new Map(prev || []);
            for (const item of event.items!) {
              const existing = next.get(item.index);
              next.set(item.index, {
                ...(existing || { include: true, reason: '', index: item.index }),
                translation: item.translation || '',
                notes: item.notes || '',
                word: item.word || '',
                definition: item.definition || '',
              });
            }
            return next;
          });
        } else if (event.type === 'done') {
          setWorkflowPhase('annotated');
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('AI 注释已中止');
      } else {
        console.error('AI 注释失败:', error);
        alert(t('app.error.aiAnnotateFailed') + getApiErrorMessage(error));
      }
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
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
        correctText,
        controller.signal
      );

      for await (const event of stream) {
        if (event.type === 'start') {
          setRecommendTotalBatches(event.total_batches!);
        } else if (event.type === 'batch') {
          setRecommendBatch(event.batch!);
          setRecommendations(prev => {
            const next = new Map(prev || []);
            for (const item of event.items!) {
              next.set(item.index, item);
            }
            return next;
          });
        } else if (event.type === 'done') {
          setIsRecommending(false);
        }
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
        alert(t('app.error.retryFailed') + getApiErrorMessage(error));
      }
      setIsRecommending(false);
    }
  };

  // ── Phase 1: 处理媒体（不打包） ──
  const handleProcessMedia = async () => {
    if (videoFiles.length === 0) { alert(t('app.error.needUploadVideo')); return; }
    if (subtitles.length === 0) { alert(t('app.error.needLoadSubtitles')); return; }
    if (selectedIndices.size === 0) { alert(t('app.error.needSelectOne')); return; }
    if (isRecommending || workflowPhase === 'screening' || workflowPhase === 'annotating') return;

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
    const perVideoPreProcessed: any[][] = videoFiles.map(() => []);
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
        const videoPP: any[] = [];
        selectedSubs.forEach((sub, newIdx) => {
          srtContent += `${newIdx + 1}\n${formatSRTTime(sub.start_sec)} --> ${formatSRTTime(sub.end_sec)}\n${sub.text}\n\n`;
          if (ppIdx < allPreProcessed.length) { videoPP.push(allPreProcessed[ppIdx]); ppIdx++; }
        });
        perVideoSRTFiles.push(new File([srtContent], `video_${vi}_selected.srt`, { type: 'text/plain' }));
        perVideoPreProcessed[vi] = videoPP;
      }
    }

    try {
      const { task_id } = await processAPI.uploadAndProcessMedia(
        videoFiles, perVideoSRTFiles, mergeMode, minDuration,
        apiKey || undefined, perVideoPreProcessed, apiBase || undefined, modelName || undefined,
        paddingStartMs, paddingEndMs, sourceLanguage, targetLanguage,
        customPrompt || undefined, annotationPurpose || undefined, annotationPrompt || undefined,
        selectRecommendedOnly
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
            alert(t('app.error.processingFailedPoll', { error: errMsg }));
            setProcessingSteps(s => s.map(step => step.status === 'processing' ? { ...step, status: 'error' as const, error: errMsg } : step));
            setProcessingPhase('idle');
          }
        } catch (e) { /* polling error, ignore */ }
      }, 1000);
    } catch (error) {
      console.error('媒体处理失败:', error);
      alert(t('app.error.processingFailedPoll', { error: getApiErrorMessage(error) }));
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
            alert(t('app.error.processingFailedPoll', { error: errMsg }));
            setProcessingSteps(s => s.map(step => step.status === 'processing' ? { ...step, status: 'error' as const, error: errMsg } : step));
            setProcessingPhase('awaiting_styles');
          }
        } catch (e) { /* ignore */ }
      }, 1000);
    } catch (error) {
      console.error('打包失败:', error);
      alert(t('app.error.processingFailedPoll', { error: getApiErrorMessage(error) }));
      setProcessingPhase('awaiting_styles');
    }
  };

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
      setCardTheme('default');

    } catch (error) {
      console.error('下载失败:', error);
      alert(t('app.error.downloadFailed') + (apkgUrl || '/download/' + encodeURIComponent(apkgPath)));
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

                  {/* Whisper 模型选择器（有未配字幕的视频时显示） */}
                  {videoFiles.some((_, i) => !subtitleFiles[i]) && !isTranscribing && (
                    <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 space-y-3 dark:border-gray-600 dark:bg-gray-800">
                      <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        {t('app.step1.whisperModelHint')}
                      </p>
                      <div className="space-y-2">
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
                      <div className="flex gap-2 mt-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="flex-1 text-gray-500"
                          onClick={async () => {
                            try {
                              await processAPI.openLogs();
                            } catch {
                              alert(t('app.step1.cantOpenLogFolder'));
                            }
                          }}
                        >
                          <FolderOpen className="w-3.5 h-3.5 mr-1" />
                          {t('app.step1.logs')}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="flex-1"
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

          {/* Step 2 · 筛选字幕 */}
          {subtitles.length > 0 && (
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
                    <label className="flex items-center gap-1.5 cursor-pointer ml-2">
                      <input
                        type="checkbox"
                        checked={selectRecommendedOnly}
                        onChange={e => setSelectRecommendedOnly(e.target.checked)}
                        disabled={isRecommending}
                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span className="text-xs text-gray-600 dark:text-gray-400">{t('app.step2.selectRecommendedOnly')}</span>
                    </label>
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
                    <label className="flex items-center gap-1.5 cursor-pointer ml-2">
                      <input
                        type="checkbox"
                        checked={correctText}
                        onChange={e => setCorrectText(e.target.checked)}
                        disabled={isRecommending}
                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span className="text-xs text-gray-600 dark:text-gray-400">{t('app.step2.correctText')}</span>
                    </label>
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

          {/* Step 3 · AI 注释（需要 API Key） */}
          {selectedIndices.size > 0 && !!apiKey && (
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

                {/* 3a: 选择用途 */}
                {(workflowPhase !== 'annotating' && workflowPhase !== 'annotated') && (
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

                {/* 3c: 注释完成 */}
                {workflowPhase === 'annotated' && (
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
                      disabled={selectedIndices.size === 0 || videoFiles.length === 0}
                    >
                      {t('app.step4.processMedia', { count: selectedIndices.size })}
                    </Button>
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
                    <StyleThemeSelector cardStyles={cardStyles} setCardStyles={setCardStyles} cardTheme={cardTheme} setCardTheme={setCardTheme} showEditor={editingStyles} onToggleEditor={handleToggleEditor} customThemes={customThemes} onImportClick={() => setShowThemeImporter(true)} onBrowseClick={() => setShowMarketplace(true)} onDeleteTheme={handleDeleteTheme} onAIGenerateClick={async () => {
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
                    <Button
                      variant="primary"
                      className="w-full"
                      onClick={handleGenerateApkg}
                    >
                      {t('app.step4.generateApkg', { count: processedCards?.length || 0 })}
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
