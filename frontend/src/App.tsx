import { useState, useEffect, useRef, useMemo } from 'react';
import { Film, Download, Info, Sparkles, ChevronDown, ChevronUp, MessageSquare, Sun, Moon, Monitor, BookOpen, GraduationCap, FolderOpen, X, ExternalLink, RefreshCw, FileSpreadsheet, FileJson } from 'lucide-react';
import { Button } from './components/Button';
import { Card, CardContent, CardHeader, CardTitle } from './components/Card';
import { ProgressBar } from './components/ProgressBar';
import { FileUpload } from './components/FileUpload';
import { SubtitleTable } from './components/SubtitleTable';
import { ProcessingStatus } from './components/ProcessingStatus';
import { CardPreview } from './components/CardPreview';
import { AnkiSyncButton } from './components/AnkiSyncButton';
import { SubtitleItem, ProcessedCard, AIRecommendation, CardStyle, CardTheme, WorkflowPhase, AnnotationPurpose } from './types';
import { subtitleAPI, processAPI, queueAPI, API_BASE_URL } from './services/api';
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

// 根据选中的字幕生成新的 SRT 文件内容
function generateSRTContent(subtitles: SubtitleItem[], selectedIndices: Set<number>): string {
  const selectedSubtitles = subtitles.filter(s => selectedIndices.has(s.index));
  let content = '';

  selectedSubtitles.forEach((sub, idx) => {
    content += `${idx + 1}\n`;
    content += `${formatSRTTime(sub.start_sec)} --> ${formatSRTTime(sub.end_sec)}\n`;
    content += `${sub.text}\n\n`;
  });

  return content;
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

// 触发浏览器下载
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

type StepStatus = 'pending' | 'processing' | 'completed' | 'error';
type ProcessingStep = { id: string; label: string; status: StepStatus; error?: string };

const PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'parse', label: '解析字幕', status: 'pending' },
  { id: 'media', label: '切割音频与截图', status: 'pending' },
  { id: 'pack', label: '打包 Anki 牌组', status: 'pending' },
];

const LANGUAGES = [
  { code: 'zh', name: '中文' },
  { code: 'en', name: '英语' },
  { code: 'ja', name: '日语' },
  { code: 'ko', name: '韩语' },
  { code: 'fr', name: '法语' },
  { code: 'de', name: '德语' },
  { code: 'es', name: '西班牙语' },
  { code: 'it', name: '意大利语' },
  { code: 'pt', name: '葡萄牙语' },
  { code: 'ru', name: '俄语' },
  { code: 'ar', name: '阿拉伯语' },
  { code: 'th', name: '泰语' },
  { code: 'vi', name: '越南语' },
  { code: 'nl', name: '荷兰语' },
  { code: 'sv', name: '瑞典语' },
  { code: 'pl', name: '波兰语' },
  { code: 'tr', name: '土耳其语' },
  { code: 'hi', name: '印地语' },
  { code: 'id', name: '印尼语' },
] as const;

function getLangName(code: string): string {
  return LANGUAGES.find(l => l.code === code)?.name ?? code;
}

function buildPresetPrompt(template: string, sourceLanguage: string): string {
  return template.replace(/\{source_language\}/g, getLangName(sourceLanguage));
}

function buildAnnotationPrompt(template: string, sourceLanguage: string, targetLanguage: string): string {
  return template
    .replace(/\{source_language\}/g, getLangName(sourceLanguage))
    .replace(/\{target_language\}/g, getLangName(targetLanguage));
}

const PRESET_TEMPLATES = {
  grammar: {
    label: '语法句型筛选',
    prompt: `你是{source_language}学习教材编写专家。对输入的字幕列表，每条判断是否值得作为学习材料：

判断标准：
- 有明确的语法知识点（如时态、从句、虚拟语气等）
- 有实用表达或固定搭配
- 对话内容有意义（非简单寒暄如'okay', 'yeah', 'uh-huh'等）
- 有文化背景或情境意义`,
  },
  vocab: {
    label: '词汇筛选',
    prompt: `你是{source_language}词汇教学专家。对输入的字幕列表，每条判断是否值得作为单词学习材料：

判断标准：
- 句子中包含高频核心词汇或学术词汇
- 包含值得掌握的动词短语、介词搭配或习语
- 包含一词多义、熟词僻义的实际用例
- 单词在语境中有助于理解和记忆
- 对话内容有意义（非简单寒暄如'okay', 'yeah', 'uh-huh'等）

对于 include=true 的句子，notes 字段需标注：重点单词-词性-释义，如遇词组则整体标注`,
  },
} as const;

type PresetKey = keyof typeof PRESET_TEMPLATES;

// 注释阶段预设模板
const ANNOTATION_TEMPLATES = {
  grammar: {
    label: '语法句型',
    prompt: `你是{source_language}学习教材编写专家。为输入的字幕列表（已筛选为值得学习的内容）提供翻译和语法句型注释。

返回格式（严格遵守）：
{{"items": [{{"index": 数字, "translation": "{target_language}翻译", "notes": "语法知识点和实用表达", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 所有项目必须包含 translation、notes、word、definition
- notes 应侧重语法结构和实用表达
- word 为句子中最值得背诵的核心单词或词组
- 保持原文顺序输出`,
  },
  vocab: {
    label: '背单词',
    prompt: `你是{target_language}词汇教学专家。为输入的字幕列表（已筛选为值得学习的内容）提供翻译和词汇注释。

返回格式（严格遵守）：
{{"items": [{{"index": 数字, "translation": "{target_language}翻译", "notes": "重点单词-词性-释义", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 所有项目必须包含 translation、notes、word、definition
- notes 格式：重点单词-词性-释义；遇词组则整体标注
- word 为句子中最值得背诵的核心单词或词组
- 保持原文顺序输出`,
  },
} as const;

type AnnotationPresetKey = keyof typeof ANNOTATION_TEMPLATES;

const DEFAULT_RECOMMEND_PROMPT = PRESET_TEMPLATES.grammar.prompt;

// 从 localStorage 读取 AI 配置（持久化）
function loadAIConfig() {
  try {
    const raw = localStorage.getItem('anki_ai_config');
    if (raw) return JSON.parse(raw);
  } catch {}
  return null;
}

function App() {
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
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [checkingEmbedded, setCheckingEmbedded] = useState(false);
  const [extractedSource, setExtractedSource] = useState('');

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [subtitleFile, setSubtitleFile] = useState<File | null>(null);

  // 批量处理模式
  const [batchMode, setBatchMode] = useState(false);
  const [batchFiles, setBatchFiles] = useState<Array<{ video: File; subtitle: File | null }>>([]);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchTasks, setBatchTasks] = useState<Array<{
    task_id: string;
    video_name: string;
    status: string;
    step: number;
    message: string;
    params?: {
      card_styles?: string[];
      theme?: string;
    };
    result?: {
      success: boolean;
      task_id: string;
      video_name: string;
      cards_count: number;
      apkg_url: string;
      cards: Array<{
        sentence: string;
        translation: string;
        notes: string;
        word?: string;
        definition?: string;
        start_sec: number;
        end_sec: number;
        audio_path?: string;
        screenshot_path?: string;
      }>;
    };
    error?: string;
  }>>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [subtitles, setSubtitles] = useState<SubtitleItem[]>([]);
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());

  const [isProcessing, setIsProcessing] = useState(false);
  const [processingSteps, setProcessingSteps] = useState(PROCESSING_STEPS);
  const [currentStep, setCurrentStep] = useState(-1);

  const [result, setResult] = useState<ProcessedCard[] | null>(null);
  const [apkgPath, setApkgPath] = useState<string | null>(null);
  const [apkgUrl, setApkgUrl] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const [previewIndex, setPreviewIndex] = useState(0);
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
  const [customPrompt, setCustomPrompt] = useState<string>(buildPresetPrompt(DEFAULT_RECOMMEND_PROMPT, savedConfig?.sourceLanguage || 'en'));
  const [promptPreset, setPromptPreset] = useState<PresetKey>('grammar');
  const [annotationPrompt, setAnnotationPrompt] = useState<string>(buildAnnotationPrompt(ANNOTATION_TEMPLATES.grammar.prompt, savedConfig?.sourceLanguage || 'en', savedConfig?.targetLanguage || 'zh'));
  const [annotationPreset, setAnnotationPreset] = useState<AnnotationPresetKey>('grammar');
  const [showAnnotationPromptEditor, setShowAnnotationPromptEditor] = useState(false);
  const [cardStyles, setCardStyles] = useState<Set<CardStyle>>(new Set(['sentence']));
  const [cardTheme, setCardTheme] = useState<CardTheme>('default');
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

  // 页面关闭时通知后端退出
  useEffect(() => {
    const handleUnload = () => {
      navigator.sendBeacon('/api/shutdown');
    };
    window.addEventListener('beforeunload', handleUnload);

    // 心跳：每 30 秒 ping 一次，后端超时 2 分钟无心跳自动关闭
    const heartbeatInterval = setInterval(() => {
      fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
    }, 30000);

    return () => {
      window.removeEventListener('beforeunload', handleUnload);
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

  const syncFromAnki = async () => {
    setSyncingFromAnki(true);
    try {
      const online = await pingAnki();
      if (!online) return;
      const words = await fetchWordsFromAnki();
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

  // ── 批量处理函数 ──

  const handleBatchAddFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    const videoExts = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.ts', '.m4v'];
    const subExts = ['.srt', '.ass', '.ssa', '.vtt', '.sub'];

    const videos = files.filter(f => videoExts.some(ext => f.name.toLowerCase().endsWith(ext)));
    const subs = files.filter(f => subExts.some(ext => f.name.toLowerCase().endsWith(ext)));

    // 按文件名（去掉扩展名）匹配字幕
    const subMap = new Map<string, File>();
    subs.forEach(s => {
      const base = s.name.replace(/\.[^.]+$/, '').toLowerCase();
      subMap.set(base, s);
    });

    const newBatch = videos.map(v => {
      const base = v.name.replace(/\.[^.]+$/, '').toLowerCase();
      return { video: v, subtitle: subMap.get(base) || null };
    });

    setBatchFiles(prev => [...prev, ...newBatch]);
    e.target.value = '';
  };

  const handleBatchRemove = (index: number) => {
    setBatchFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleBatchSetSubtitle = (index: number, file: File | null) => {
    setBatchFiles(prev => prev.map((f, i) => i === index ? { ...f, subtitle: file } : f));
  };

  const handleBatchSubmit = async () => {
    const videoFiles = batchFiles.map(f => f.video);
    const subtitleFiles = batchFiles.map(f => f.subtitle);

    const noSubCount = subtitleFiles.filter(s => !s).length;
    if (noSubCount > 0) {
      const ok = confirm(`${noSubCount} 个视频未匹配字幕，将自动使用 Whisper 转录。继续？`);
      if (!ok) return;
    }

    setBatchSubmitting(true);
    try {
      const result = await queueAPI.add(videoFiles, subtitleFiles, {
        apiKey: apiKey || undefined,
        apiBase: apiBase || undefined,
        modelName: modelName || undefined,
        language: sourceLanguage || undefined,
        whisperModel,
        paddingStartMs,
        paddingEndMs,
        cardStyles: Array.from(cardStyles),
        theme: cardTheme,
      });

      setBatchId(result.batch_id);
      setBatchTasks(result.tasks.map(t => ({
        ...t,
        step: 0,
        message: '等待中',
      })));

      // 启动轮询
      startBatchPolling(result.batch_id);
    } catch (err) {
      alert('提交失败: ' + getApiErrorMessage(err));
    } finally {
      setBatchSubmitting(false);
    }
  };

  const startBatchPolling = (bid: string) => {
    if (batchPollRef.current) clearInterval(batchPollRef.current);
    batchPollRef.current = setInterval(async () => {
      try {
        const status = await queueAPI.getStatus(bid);
        setBatchTasks(status.tasks);

        // 全部完成或失败时停止轮询
        const allDone = status.tasks.every(
          t => t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'
        );
        if (allDone || !status.running) {
          if (batchPollRef.current) clearInterval(batchPollRef.current);
        }
      } catch {
        // 轮询失败不中断
      }
    }, 1500);
  };

  const handleBatchCancelTask = async (taskId: string) => {
    try {
      await queueAPI.cancel(taskId);
    } catch {}
  };

  const handleBatchCancelAll = async () => {
    if (!batchId) return;
    try {
      await queueAPI.cancelBatch(batchId);
    } catch {}
  };

  const handleBatchSyncToAnki = async (task: typeof batchTasks[0]) => {
    if (!task.result?.cards) return;
    const { syncToAnki } = await import('./services/syncToAnki');
    const { pingAnki } = await import('./services/ankiConnect');
    const online = await pingAnki();
    if (!online) {
      alert('未检测到 Anki，请确保 Anki 已安装并运行');
      return;
    }
    try {
      const deckName = task.video_name.replace(/\.[^.]+$/, '');
      // 从任务参数中获取样式和主题
      const taskCardStyles = task.params?.card_styles || Array.from(cardStyles);
      const taskTheme = task.params?.theme || cardTheme;
      const res = await syncToAnki(task.result.cards, deckName, API_BASE_URL, taskCardStyles, taskTheme);
      alert(`同步完成：新增 ${res.added}，跳过 ${res.skipped}，失败 ${res.failed}`);
    } catch (err) {
      alert('同步失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  // 清理批量轮询
  useEffect(() => {
    return () => {
      if (batchPollRef.current) clearInterval(batchPollRef.current);
    };
  }, []);

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
    localStorage.setItem('anki_ai_config', JSON.stringify({ apiBase, modelName, apiKey, sourceLanguage, targetLanguage }));
  }, [apiBase, modelName, apiKey, sourceLanguage, targetLanguage]);

  // 源语言变化时，同步更新预设提示词中的语言名称
  useEffect(() => {
    for (const tmpl of Object.values(PRESET_TEMPLATES)) {
      const built = buildPresetPrompt(tmpl.prompt, sourceLanguage);
      for (const lang of LANGUAGES) {
        if (lang.code === sourceLanguage) continue;
        if (customPrompt === buildPresetPrompt(tmpl.prompt, lang.code)) {
          setCustomPrompt(built);
          break;
        }
      }
    }
    // 同步注释提示词
    for (const tmpl of Object.values(ANNOTATION_TEMPLATES)) {
      const built = buildAnnotationPrompt(tmpl.prompt, sourceLanguage, targetLanguage);
      for (const srcLang of LANGUAGES) {
        for (const tgtLang of LANGUAGES) {
          if (srcLang.code === sourceLanguage && tgtLang.code === targetLanguage) continue;
          if (annotationPrompt === buildAnnotationPrompt(tmpl.prompt, srcLang.code, tgtLang.code)) {
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
    { key: 'tiny',  label: 'tiny',   size: '~75 MB',  speed: '最快，精度最低' },
    { key: 'base',  label: 'base',   size: '~145 MB', speed: '较快，日常够用' },
    { key: 'small', label: 'small',  size: '~488 MB', speed: '中等，精度较好' },
    { key: 'medium',label: 'medium', size: '~1.5 GB', speed: '较慢，精度高' },
    { key: 'large', label: 'large',  size: '~2.9 GB', speed: '最慢，精度最高' },
  ];

  // 生成字幕 — 方案链：软字幕 > Whisper 转录
  const handleTranscribe = async () => {
    if (!videoFile || transcribingRef.current) return;
    if (transcribedVideoName.current === videoFile.name) return;

    setCheckingEmbedded(true);
    setExtractedSource('');

    try {
      // 优先提取内嵌软字幕
      const result = await subtitleAPI.extractEmbeddedSubs(videoFile, 0, minDuration);

      if (result.found && result.extracted) {
        setSubtitles(result.extracted.subtitles as SubtitleItem[]);
        setSelectedIndices(new Set(result.extracted.subtitles.map((s: SubtitleItem) => s.index)));
        setRecommendations(null);
        transcribedVideoName.current = videoFile.name;
        setExtractedSource(`从视频提取（${result.extracted.codec} / ${result.extracted.language}，${result.extracted.total} 条）`);
        setCheckingEmbedded(false);
        scrollToStep2();
        return;
      }

      if (result.found && !result.extracted) {
        // 内嵌字幕无法提取，提示使用 Whisper
        console.log('内嵌字幕无法提取:', result.message);
      }
    } catch (e) {
      console.error('检测字幕失败:', e);
      // 提取失败时静默继续到 Whisper 转录
    }

    setCheckingEmbedded(false);
    setShowModelPicker(true);
  };

  // 确认模型后开始转录
  const startTranscribe = async () => {
    if (!videoFile || transcribingRef.current) return;

    // 检查 Whisper 插件是否已安装
    try {
      const whisperStatus = await subtitleAPI.getWhisperStatus();
      if (!whisperStatus.installed) {
        alert('Whisper 未安装。\n\n开发环境请运行: pip install faster-whisper');
        return;
      }
    } catch (e) {
      console.error('检查 Whisper 状态失败:', e);
    }

    setShowModelPicker(false);
    transcribingRef.current = true;
    setIsTranscribing(true);
    setTranscribeStep(0);
    setTranscribeTotalSteps(4);
    setTranscribeMessage('准备转录...');

    try {
      const { task_id } = await subtitleAPI.startTranscribe(videoFile, minDuration, undefined, whisperModel);

      const pollInterval = setInterval(async () => {
        try {
          const progress = await subtitleAPI.getTranscribeProgress(task_id);

          setTranscribeStep(progress.step);
          setTranscribeTotalSteps(progress.total_steps);

          // 使用真实的转录进度（如果有）
          if (progress.whisper_progress) {
            const wp = progress.whisper_progress;
            const pct = Math.round(wp.progress * 100);
            whisperHasRealProgress.current = true;
            setTranscribeAnimProgress(pct);
            setWhisperText(wp.text || '');
            // 格式化时间轴文字
            const fmtTime = (sec: number) => {
              const m = Math.floor(sec / 60);
              const s = Math.floor(sec % 60);
              return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
            };
            setTranscribeMessage(`转录中 — ${fmtTime(wp.transcribed_sec)} / ${fmtTime(wp.duration_sec)}  ${pct}%`);
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
            transcribedVideoName.current = videoFile.name;
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
      alert('转录失败: ' + getApiErrorMessage(error));
      setIsTranscribing(false);
      transcribingRef.current = false;
    }
  };

  // 加载字幕
  const handleLoadSubtitles = async () => {
    if (!subtitleFile) return;

    try {
      setProcessingSteps(steps =>
        steps.map((s, i) =>
          i === 0 ? { ...s, status: 'processing' } : { ...s, status: 'pending' }
        )
      );
      setCurrentStep(0);

      const response = await subtitleAPI.upload(subtitleFile, minDuration);

      setSubtitles(response.subtitles);
      setSelectedIndices(new Set(response.subtitles.map(s => s.index)));
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
      alert('请先在配置中填写 API Key');
      return;
    }
    if (subtitles.length === 0) {
      alert('请先加载字幕');
      return;
    }
    if (selectedIndices.size === 0) {
      alert('请先勾选需要分析的句子');
      return;
    }

    setWorkflowPhase('screening');
    setIsRecommending(true);
    setRecommendations(new Map());
    setFailedIndices(new Set());
    setRecommendBatch(0);
    setRecommendTotalBatches(0);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const stream = subtitleAPI.startScreenStream(
        subtitles.filter(s => selectedIndices.has(s.index)),
        apiKey,
        customPrompt || undefined,
        recommendBatchSize,
        apiBase || undefined,
        modelName || undefined,
        sourceLanguage,
        targetLanguage,
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
          if (rec.reason?.startsWith('处理失败:')) {
            failed.add(index);
          }
        }
        setFailedIndices(failed);

        const recommendedIndices = Array.from(prev.values())
          .filter(r => r.include && !r.reason?.startsWith('处理失败:'))
          .map(r => r.index);
        setSelectedIndices(new Set(recommendedIndices));
        return prev;
      });

      setWorkflowPhase('screened');

    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('AI 筛选已中止');
      } else {
        console.error('AI 筛选失败:', error);
        alert('AI 筛选失败: ' + getApiErrorMessage(error));
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
      alert('请先配置 API Key');
      return;
    }

    const selectedSubs = subtitles.filter(s => {
      const rec = recommendations?.get(s.index);
      return rec?.include && selectedIndices.has(s.index);
    });

    if (selectedSubs.length === 0) {
      alert('请先选择需要注释的句子');
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
        controller.signal
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
              if (existing) {
                next.set(item.index, {
                  ...existing,
                  translation: item.translation,
                  notes: item.notes,
                  word: item.word,
                  definition: item.definition,
                });
              }
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
        alert('AI 注释失败: ' + getApiErrorMessage(error));
      }
      setWorkflowPhase('screened');
    }
  };

  // 仅选推荐
  const selectRecommended = () => {
    if (!recommendations) return;
    const recommendedIndices = Array.from(recommendations.values())
      .filter(r => r.include && !r.reason?.startsWith('处理失败:'))
      .map(r => r.index);
    setSelectedIndices(new Set(recommendedIndices));
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
          if (rec.reason?.startsWith('处理失败:')) {
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
        alert('重试失败: ' + getApiErrorMessage(error));
      }
      setIsRecommending(false);
    }
  };

  // 处理选中的字幕
  const handleProcess = async () => {
    if (!videoFile) {
      alert('请先上传视频文件');
      return;
    }
    if (subtitles.length === 0) {
      alert('请先加载或生成字幕');
      return;
    }

    if (selectedIndices.size === 0) {
      alert('请至少选择一条字幕');
      return;
    }

    setIsProcessing(true);
    setProcessingSteps(PROCESSING_STEPS.map(s => ({ ...s, status: 'pending' as const })));
    setCurrentStep(0);

    // 根据选中的字幕生成新的 SRT 文件
    const srtContent = generateSRTContent(subtitles, selectedIndices);
    const selectedSubtitleBlob = new Blob([srtContent], { type: 'text/plain' });
    const selectedSubtitleFile = new File([selectedSubtitleBlob], 'selected_subtitles.srt', { type: 'text/plain' });

    // 构建预处理数据
    // 有 AI 推荐时使用推荐结果，无推荐时使用空翻译/注释（跳过后端 AI 步骤）
    const preProcessed = subtitles
      .filter(s => selectedIndices.has(s.index))
      .map(s => {
        const rec = recommendations?.get(s.index);
        return {
          index: s.index,
          text: s.text,
          translation: rec?.translation || '',
          notes: rec?.notes || '',
          reason: rec?.reason || '',
          word: rec?.word || '',
          definition: rec?.definition || ''
        };
      });

    try {
      // 1. 上传并启动后台处理
      const { task_id } = await processAPI.uploadAndProcess(
        videoFile,
        selectedSubtitleFile,
        minDuration,
        apiKey || undefined,
        preProcessed,
        apiBase || undefined,
        modelName || undefined,
        paddingStartMs,
        paddingEndMs,
        Array.from(cardStyles),
        cardTheme
      );

      setTaskId(task_id);

      // 2. 轮询进度
      const pollInterval = setInterval(async () => {
        try {
          const progress = await processAPI.getProgress(task_id);

          // 更新步骤状态（后端 step 1-4 映射到前端 index 0-2）
          // 后端: 1=解析, 2=AI注释(跳过), 3=媒体切割, 4=打包
          // 前端: 0=解析, 1=媒体切割, 2=打包
          const stepIndex = progress.step <= 1 ? 0 : progress.step - 2;
          setCurrentStep(stepIndex);
          setProcessingSteps(steps => {
            const newSteps = [...steps];
            for (let i = 0; i < newSteps.length; i++) {
              if (i < stepIndex) {
                newSteps[i] = { ...newSteps[i], status: 'completed' as const };
              } else if (i === stepIndex) {
                newSteps[i] = { ...newSteps[i], status: 'processing' as const };
              }
            }
            return newSteps;
          });

          if (progress.status === 'completed' && progress.result) {
            clearInterval(pollInterval);
            setIsProcessing(false);
            setProcessingSteps(s => s.map(step => ({ ...step, status: 'completed' as const })));

            const r = progress.result;
            setApkgPath(r.apkg_path);
            setApkgUrl(r.apkg_url || null);

            if (r.cards && r.cards.length > 0) {
              setResult(r.cards);
              setPreviewIndex(0);
            } else {
              alert(`处理完成！生成了 ${r.cards_count} 张卡片。`);
            }
          }

          if (progress.status === 'error') {
            clearInterval(pollInterval);
            setIsProcessing(false);
            const errMsg = getFriendlyMessage(progress.error_code, progress.error || undefined);
            alert(`处理失败: ${errMsg}`);
            setProcessingSteps(s =>
              s.map((step) =>
                step.status === 'processing'
                  ? { ...step, status: 'error' as const, error: errMsg }
                  : step
              )
            );
          }
        } catch (e) {
          // 轮询失败不中断
        }
      }, 1000);

      // 保存 interval ID 以便清理
      (window as any).__pollInterval = pollInterval;

    } catch (error) {
      console.error('处理失败:', error);
      const errorMessage = getApiErrorMessage(error);
      alert(`处理失败: ${errorMessage}`);

      setProcessingSteps(s =>
        s.map((step) =>
          step.status === 'processing'
            ? { ...step, status: 'error' as const, error: errorMessage }
            : step
        )
      );
      setIsProcessing(false);
    }
  };

  // 下载文件
  const handleDownload = async () => {
    if (!apkgPath) return;

    try {
      // 使用后端返回的 apkg_url（包含 task_id 子目录）
      const downloadUrl = apkgUrl
        ? `${API_BASE_URL}${apkgUrl}`
        : `/download/${encodeURIComponent(apkgPath)}`;
      const response = await fetch(downloadUrl);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `下载失败 (HTTP ${response.status})`);
      }
      const blob = await response.blob();

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = apkgPath.split('/').pop() || 'deck.apkg';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();

      // 下载后清理服务端文件
      if (taskId) {
        try {
          await processAPI.cleanup(taskId);
        } catch (e) {
          console.error('清理文件失败:', e);
        }
      }

      // 清理界面状态，方便继续处理下一个视频
      setVideoFile(null);
      setSubtitleFile(null);
      setSubtitles([]);
      setSelectedIndices(new Set());
      setResult(null);
      setApkgPath(null);
      setApkgUrl(null);
      setRecommendations(null);
      setFailedIndices(new Set());
      setProcessingSteps(PROCESSING_STEPS);
      setCurrentStep(-1);
      setExtractedSource('');
      transcribedVideoName.current = null;
      setWorkflowPhase('idle');
      setAnnotationPurpose(null);
      setCardTheme('default');

    } catch (error) {
      console.error('下载失败:', error);
      alert('下载失败，请手动访问: ' + (apkgUrl || '/download/' + encodeURIComponent(apkgPath)));
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
                使用说明
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.open('https://github.com/qinusui/ClipLingo/issues', '_blank')}
              >
                <MessageSquare className="w-4 h-4 mr-2" />
                反馈
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleTheme}
                title={theme === 'system' ? '跟随系统' : theme === 'light' ? '浅色模式' : '深色模式'}
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
                发现新版本 <strong>v{updateInfo.latestVersion}</strong>，当前版本 v1.2.2
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
                前往下载
              </a>
              <button
                onClick={() => setUpdateDismissed(true)}
                className="p-1 text-blue-400 hover:text-blue-600 dark:hover:text-blue-300 transition-colors"
                title="忽略此更新"
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
                <h3 className="text-lg font-semibold">使用说明</h3>
                <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5 dark:bg-gray-700">
                  <button
                    onClick={() => setHelpTab('basic')}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      helpTab === 'basic'
                        ? 'bg-white text-gray-900 shadow dark:bg-gray-600 dark:text-gray-100'
                        : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                    }`}
                  >
                    基础
                  </button>
                  <button
                    onClick={() => setHelpTab('advanced')}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      helpTab === 'advanced'
                        ? 'bg-white text-gray-900 shadow dark:bg-gray-600 dark:text-gray-100'
                        : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                    }`}
                  >
                    进阶
                  </button>
                </div>
              </div>

              {helpTab === 'basic' ? (
                <ol className="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300">
                  <li>上传视频文件（.mp4 / .mkv / .avi）和字幕文件（.srt），或点击「生成字幕」自动转录</li>
                  <li>勾选目标句子，点击「开始处理」等待生成卡片</li>
                  <li>预览卡片，下载 .apkg 文件导入 Anki</li>
                </ol>
              ) : (
                <div className="space-y-4 text-sm text-gray-700 dark:text-gray-300">
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">基础功能（无需 AI）</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>上传视频和字幕，手动勾选句子即可生成卡片</li>
                      <li>卡片包含：原文、对应音频片段和视频截图</li>
                      <li>可调整最短时长、音频头尾 padding 等参数</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">AI 进阶功能（可选）</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>配置 AI 后可使用「AI 推荐」智能筛选有学习价值的句子</li>
                      <li>AI 自动翻译并生成词汇注释，卡片额外包含翻译和知识点</li>
                      <li>支持 OpenAI / DeepSeek / Ollama 等兼容接口</li>
                      <li>配置自动保存到浏览器，刷新无需重新填写</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">字幕获取</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>上传 .srt 字幕文件，或仅上传视频点击「生成字幕」使用 Whisper 转录</li>
                      <li>Whisper 模型可选 tiny / base / small / medium / large，越大越准但越慢</li>
                      <li>转录支持中/英/日等多语言，默认自动检测</li>
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-1 dark:text-gray-100">卡片生成</h4>
                    <ul className="list-disc list-inside space-y-1 ml-2">
                      <li>音频切割有 ±0.2s padding，先整体提取音轨再切片，高效不突兀</li>
                      <li>支持预览前后翻页，下载 .apkg 后导入 Anki 即可背诵</li>
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
                准备素材
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/* ffmpeg 未安装提示 */}
              {ffmpegInstalled === false && (
                <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg dark:bg-yellow-900/20 dark:border-yellow-800">
                  <div className="flex items-start gap-2">
                    <span className="text-yellow-600 dark:text-yellow-400">⚠️</span>
                    <div className="text-sm">
                      <p className="font-medium text-yellow-800 dark:text-yellow-300">ffmpeg 未安装</p>
                      <p className="text-yellow-700 dark:text-yellow-400 mt-1">
                        视频处理需要 ffmpeg 支持。请安装 ffmpeg 并添加到系统 PATH。
                      </p>
                      <a
                        href="https://ffmpeg.org/download.html"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-yellow-800 underline hover:text-yellow-900 dark:text-yellow-300 dark:hover:text-yellow-200"
                      >
                        下载 ffmpeg →
                      </a>
                    </div>
                  </div>
                </div>
              )}

              {/* 批量/单文件模式切换 */}
              {!isProcessing && !batchId && (
                <div className="flex items-center gap-2 mb-4">
                  <button
                    onClick={() => setBatchMode(false)}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${!batchMode ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'}`}
                  >
                    单文件处理
                  </button>
                  <button
                    onClick={() => setBatchMode(true)}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${batchMode ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'}`}
                  >
                    批量处理
                  </button>
                </div>
              )}

              {/* ── 批量模式：文件列表 + 提交 ── */}
              {batchMode && !batchId && (
                <div className="space-y-4">
                  <div className="border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-6 text-center">
                    <input
                      type="file"
                      id="batch-files"
                      multiple
                      accept=".mp4,.mkv,.avi,.mov,.webm,.srt,.ass,.vtt"
                      onChange={handleBatchAddFiles}
                      className="hidden"
                    />
                    <label htmlFor="batch-files" className="cursor-pointer">
                      <div className="text-gray-500 dark:text-gray-400">
                        <p className="text-sm font-medium">点击或拖拽添加视频和字幕文件</p>
                        <p className="text-xs mt-1">支持同时选择多个文件，按文件名自动匹配字幕</p>
                      </div>
                    </label>
                  </div>

                  {batchFiles.length > 0 && (
                    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 dark:bg-gray-800">
                          <tr>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 w-8">#</th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">视频文件</th>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">字幕文件</th>
                            <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 w-12">操作</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                          {batchFiles.map((f, i) => (
                            <tr key={i}>
                              <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                              <td className="px-3 py-2 font-medium text-gray-800 dark:text-gray-200">{f.video.name}</td>
                              <td className="px-3 py-2">
                                {f.subtitle ? (
                                  <span className="text-green-600 dark:text-green-400">{f.subtitle.name}</span>
                                ) : (
                                  <div className="flex items-center gap-2">
                                    <span className="text-yellow-600 dark:text-yellow-400 text-xs">Whisper 转录</span>
                                    <label className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 cursor-pointer">
                                      选字幕
                                      <input
                                        type="file"
                                        accept=".srt,.ass,.vtt,.ssa,.sub"
                                        className="hidden"
                                        onChange={(e) => {
                                          const file = e.target.files?.[0];
                                          if (file) handleBatchSetSubtitle(i, file);
                                        }}
                                      />
                                    </label>
                                  </div>
                                )}
                              </td>
                              <td className="px-3 py-2 text-center">
                                <button onClick={() => handleBatchRemove(i)} className="text-red-400 hover:text-red-600">
                                  <X className="w-4 h-4" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <Button
                    variant="primary"
                    className="w-full"
                    onClick={handleBatchSubmit}
                    disabled={batchFiles.length === 0 || batchSubmitting}
                    isLoading={batchSubmitting}
                  >
                    <Sparkles className="w-4 h-4 mr-2" />
                    提交 {batchFiles.length} 个任务
                  </Button>
                </div>
              )}

              {/* ── 批量模式：队列状态面板 ── */}
              {batchId && batchTasks.length > 0 && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200">
                      批量处理
                      <span className="ml-2 text-sm font-normal text-gray-500">
                        {batchTasks.filter(t => t.status === 'done').length}/{batchTasks.length} 完成
                      </span>
                    </h3>
                    <div className="flex gap-2">
                      {batchTasks.some(t => t.status === 'done') && (
                        <>
                          <a
                            href={queueAPI.downloadAllUrl(batchId || undefined)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-green-600 rounded-lg hover:bg-green-700"
                          >
                            <Download className="w-4 h-4" /> 全部下载 ZIP
                          </a>
                          <a
                            href={queueAPI.exportAllZipUrl(batchId || undefined)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-emerald-700 border border-emerald-300 rounded-lg hover:bg-emerald-50 dark:border-emerald-700 dark:text-emerald-400 dark:hover:bg-emerald-900/20"
                          >
                            <FolderOpen className="w-4 h-4" /> 带媒体 ZIP
                          </a>
                          <button
                            onClick={() => {
                              const allCards = batchTasks
                                .filter(t => t.status === 'done' && t.result?.cards)
                                .flatMap(t => t.result!.cards);
                              if (allCards.length === 0) return;
                              downloadString(generateCSVContent(allCards), 'ClipLingo_batch.csv', 'text/csv');
                            }}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-blue-600 border border-blue-300 rounded-lg hover:bg-blue-50 dark:border-blue-700 dark:hover:bg-blue-900/20"
                          >
                            <FileSpreadsheet className="w-4 h-4" /> CSV
                          </button>
                          <button
                            onClick={() => {
                              const allCards = batchTasks
                                .filter(t => t.status === 'done' && t.result?.cards)
                                .flatMap(t => t.result!.cards);
                              if (allCards.length === 0) return;
                              downloadString(generateJSONContent(allCards), 'ClipLingo_batch.json', 'application/json');
                            }}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-purple-600 border border-purple-300 rounded-lg hover:bg-purple-50 dark:border-purple-700 dark:hover:bg-purple-900/20"
                          >
                            <FileJson className="w-4 h-4" /> JSON
                          </button>
                        </>
                      )}
                      {batchTasks.some(t => t.status === 'waiting' || t.status === 'running') && (
                        <button
                          onClick={handleBatchCancelAll}
                          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-red-600 border border-red-300 rounded-lg hover:bg-red-50 dark:border-red-700 dark:hover:bg-red-900/20"
                        >
                          取消队列
                        </button>
                      )}
                      <button
                        onClick={() => { setBatchId(null); setBatchTasks([]); setBatchFiles([]); }}
                        className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400"
                      >
                        返回
                      </button>
                    </div>
                  </div>

                  {/* 整体进度条 */}
                  {(() => {
                    const doneCount = batchTasks.filter(t => t.status === 'done').length;
                    const pct = Math.round((doneCount / batchTasks.length) * 100);
                    return (
                      <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                        <div className="bg-primary-500 h-2 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                    );
                  })()}

                  {/* 任务列表 */}
                  <div className="space-y-2">
                    {batchTasks.map((task) => {
                      const statusIcon = {
                        waiting: '○',
                        running: '⟳',
                        done: '✓',
                        failed: '✗',
                        cancelled: '⊘',
                      }[task.status] || '?';
                      const statusColor = {
                        waiting: 'text-gray-400',
                        running: 'text-blue-500',
                        done: 'text-green-500',
                        failed: 'text-red-500',
                        cancelled: 'text-gray-400',
                      }[task.status] || 'text-gray-400';

                      return (
                        <div key={task.task_id} className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
                          <span className={`text-lg ${statusColor}`}>{statusIcon}</span>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">{task.video_name}</p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">{task.message}</p>
                            {task.status === 'running' && (
                              <div className="w-full bg-gray-200 rounded-full h-1.5 mt-1 dark:bg-gray-600">
                                <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${(task.step / 5) * 100}%` }} />
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            {task.status === 'done' && task.result && (
                              <>
                                <a
                                  href={`${API_BASE_URL}${task.result.apkg_url}`}
                                  className="text-xs text-blue-600 hover:underline dark:text-blue-400"
                                  download
                                >
                                  下载
                                </a>
                                <button
                                  onClick={() => handleBatchSyncToAnki(task)}
                                  className="text-xs text-green-600 hover:underline dark:text-green-400"
                                >
                                  同步 Anki
                                </button>
                              </>
                            )}
                            {task.status === 'waiting' && (
                              <button
                                onClick={() => handleBatchCancelTask(task.task_id)}
                                className="text-xs text-red-400 hover:text-red-600"
                              >
                                取消
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 单文件模式 UI */}
              {!batchMode && !batchId && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* 左侧：文件上传 */}
                <div className="lg:col-span-2 space-y-4">
                  <FileUpload
                    accept=".mp4,.mkv,.avi,.mov,.webm"
                    onFileSelect={(f) => { setVideoFile(f); transcribedVideoName.current = null; setExtractedSource(''); setSubtitles([]); setSelectedIndices(new Set()); setRecommendations(null); }}
                    selectedFile={videoFile}
                    onClear={() => { setVideoFile(null); transcribedVideoName.current = null; setExtractedSource(''); setSubtitles([]); setSelectedIndices(new Set()); setRecommendations(null); }}
                    label="视频文件"
                    icon="video"
                  />
                  <FileUpload
                    accept=".srt"
                    onFileSelect={setSubtitleFile}
                    selectedFile={subtitleFile}
                    onClear={() => setSubtitleFile(null)}
                    label="字幕文件（可选）"
                    icon="text"
                  />

                  {/* Whisper 模型选择器 */}
                  {showModelPicker && !isTranscribing && (
                    <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 space-y-3 dark:border-gray-600 dark:bg-gray-800">
                      <p className="text-sm font-medium text-gray-700 dark:text-gray-300">选择 Whisper 模型（首次使用会自动下载模型）</p>
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
                      <div className="flex gap-2">
                        <Button variant="primary" size="sm" onClick={startTranscribe}>
                          开始转录
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setShowModelPicker(false)}>
                          取消
                        </Button>
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
                          正在识别：「{whisperText}」
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
                        onClick={() => { setExtractedSource(''); setShowModelPicker(true); }}
                      >
                        改用 Whisper 转录
                      </button>
                    </div>
                  )}

                  {/* 字幕处理配置 */}
                  <div className="p-4 bg-gray-50 rounded-lg space-y-3 dark:bg-gray-800">
                    <div className="text-xs font-medium text-gray-600 dark:text-gray-400">字幕处理配置</div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">开头提前(ms)</label>
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
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">结尾延后(ms)</label>
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

                {/* 右侧：AI 配置 */}
                <div className="space-y-4">
                  <div className="text-sm font-medium text-gray-700 dark:text-gray-300">AI 配置</div>
                  {/* 折叠时显示摘要 */}
                  {!configExpanded && (
                    <div
                      className="flex items-center justify-between cursor-pointer p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors dark:bg-gray-800 dark:hover:bg-gray-700"
                      onClick={() => setConfigExpanded(true)}
                    >
                      <span className="text-sm text-gray-600 truncate dark:text-gray-400">
                        {getLangName(sourceLanguage)} → {getLangName(targetLanguage)} / {modelName}
                        {apiKey ? ` / ***${apiKey.slice(-4)}` : ' / 未设置 Key'}
                      </span>
                      <ChevronDown className="w-4 h-4 text-gray-400 shrink-0 dark:text-gray-500" />
                    </div>
                  )}
                  {/* 展开时显示完整配置 */}
                  {configExpanded && (
                    <div className="space-y-3 p-4 bg-gray-50 rounded-lg dark:bg-gray-800">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">API 地址</label>
                        <input
                          type="text"
                          value={apiBase}
                          onChange={(e) => setApiBase(e.target.value)}
                          placeholder="https://api.deepseek.com"
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">模型名称</label>
                        <input
                          type="text"
                          value={modelName}
                          onChange={(e) => setModelName(e.target.value)}
                          placeholder="deepseek-chat"
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">API Key</label>
                        <input
                          type="password"
                          value={apiKey}
                          onChange={(e) => { setApiKey(e.target.value); setTestResult(null); }}
                          placeholder="输入你的 API Key"
                          className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">源语言</label>
                          <select
                            value={sourceLanguage}
                            onChange={(e) => setSourceLanguage(e.target.value)}
                            className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                          >
                            {LANGUAGES.map(l => (
                              <option key={l.code} value={l.code}>{l.name}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">目标语言</label>
                          <select
                            value={targetLanguage}
                            onChange={(e) => setTargetLanguage(e.target.value)}
                            className="w-full px-2 py-1.5 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                          >
                            {LANGUAGES.map(l => (
                              <option key={l.code} value={l.code}>{l.name}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={handleTestConnection}
                          disabled={isTesting || !apiKey}
                        >
                          {isTesting ? '测试中...' : '测试连接'}
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={handleListModels}
                          disabled={!apiKey}
                        >
                          模型列表
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
                        <p className="text-xs text-red-500">获取模型列表失败，并不影响使用</p>
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
                              alert('无法打开日志文件夹');
                            }
                          }}
                        >
                          <FolderOpen className="w-3.5 h-3.5 mr-1" />
                          日志
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="flex-1"
                          onClick={() => setConfigExpanded(false)}
                        >
                          <ChevronUp className="w-4 h-4 mr-1" />
                          收起配置
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              )}

              {/* 单文件模式：确认操作行 */}
              {!batchMode && !batchId && (
              <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-3 flex-wrap">
                  {/* 状态指示 */}
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    videoFile
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
                  }`}>
                    {videoFile ? '✓' : '○'} 视频
                  </span>
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    subtitles.length > 0
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : subtitleFile
                        ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                        : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
                  }`}>
                    {subtitles.length > 0 ? `✓ 字幕 (${subtitles.length} 条)` : subtitleFile ? '○ 字幕待加载' : '○ 字幕'}
                  </span>

                  <div className="flex-1" />

                  {/* 操作按钮 */}
                  {subtitles.length > 0 ? (
                    <span className="text-sm text-green-600 dark:text-green-400 font-medium">字幕已就绪，进入下一步</span>
                  ) : subtitleFile ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleLoadSubtitles}
                      disabled={isProcessing}
                    >
                      加载字幕
                    </Button>
                  ) : videoFile ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleTranscribe}
                      disabled={isProcessing || isTranscribing || checkingEmbedded}
                    >
                      {checkingEmbedded ? '检测字幕中...' : isTranscribing ? '转录中...' : '生成字幕'}
                    </Button>
                  ) : (
                    <span className="text-sm text-gray-400 dark:text-gray-500">请先上传视频</span>
                  )}
                </div>
              </div>
              )}
            </CardContent>
          </Card>

          {/* Step 2 · AI 筛选 */}
          {subtitles.length > 0 && (
            <div ref={step2Ref}>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">2</span>
                  AI 筛选
                  <span className="text-sm font-normal text-gray-500 ml-2 dark:text-gray-400">
                    (已选 {selectedIndices.size} / {filteredSubtitles.length}{filteredSubtitles.length !== subtitles.length ? `，共 ${subtitles.length} 条` : ''})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {/* 规则筛选（前置） */}
                <div className="flex flex-wrap items-end gap-3 mb-4 p-3 bg-gray-50 rounded-lg dark:bg-gray-800/50">
                  <div className="flex items-center gap-1.5">
                    <label className="text-xs text-gray-500 dark:text-gray-400">时长</label>
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
                    <span className="text-xs text-gray-400">秒</span>
                  </div>

                  {recommendations && learnedWords.size > 0 && (
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={filterExcludeLearned}
                        onChange={e => setFilterExcludeLearned(e.target.checked)}
                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span className="text-xs text-gray-600 dark:text-gray-400">排除已学</span>
                    </label>
                  )}
                  <button
                    onClick={syncFromAnki}
                    disabled={syncingFromAnki}
                    className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
                    title="从 Anki 同步已学词汇"
                  >
                    <RefreshCw className={`w-3 h-3 ${syncingFromAnki ? 'animate-spin' : ''}`} />
                    {syncingFromAnki ? '同步中...' : '从 Anki 同步'}
                  </button>

                  <div className="flex items-center gap-1.5 flex-1 min-w-[160px]">
                    <label className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">排除词</label>
                    <input
                      type="text"
                      value={filterBlacklist}
                      onChange={e => setFilterBlacklist(e.target.value)}
                      className="flex-1 px-2 py-1 border border-gray-300 rounded text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                      placeholder="逗号分隔，如: oh, well, yeah"
                    />
                  </div>

                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    显示 {filteredSubtitles.length} / {subtitles.length}
                  </span>
                </div>

                {/* 工具栏 */}
                <div className="flex items-center gap-2 mb-4">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleAIScreen}
                    disabled={isRecommending || isProcessing || workflowPhase === 'annotating'}
                  >
                    <Sparkles className="w-4 h-4 mr-2" />
                    {workflowPhase === 'screening'
                      ? recommendTotalBatches > 0
                        ? `筛选中 ${recommendBatch}/${recommendTotalBatches}`
                        : 'AI 筛选中...'
                      : 'AI 筛选'}
                  </Button>
                  {workflowPhase === 'screening' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => abortControllerRef.current?.abort()}
                    >
                      停止
                    </Button>
                  )}
                  {recommendations && workflowPhase !== 'idle' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={selectRecommended}
                    >
                      仅选推荐
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
                      重试失败 ({failedIndices.size})
                    </Button>
                  )}
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
                    提示词
                  </Button>
                </div>

                {/* 提示词编辑器（仅筛选标准） */}
                {showPromptEditor && (
                  <div className="mb-4 p-4 bg-gray-50 rounded-lg space-y-3 dark:bg-gray-800">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">提示词预设</label>
                      <div className="flex gap-2">
                        {(Object.keys(PRESET_TEMPLATES) as PresetKey[]).map((key) => (
                          <button
                            key={key}
                            onClick={() => {
                              setPromptPreset(key);
                              setCustomPrompt(buildPresetPrompt(PRESET_TEMPLATES[key].prompt, sourceLanguage));
                            }}
                            disabled={isRecommending}
                            className={`px-3 py-1.5 rounded text-sm font-medium border transition-colors ${
                              promptPreset === key
                                ? 'bg-primary-500 text-white border-primary-500'
                                : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                            }`}
                          >
                            {PRESET_TEMPLATES[key].label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">提示词内容（可自由修改）</label>
                      <textarea
                        value={customPrompt}
                        onChange={(e) => setCustomPrompt(e.target.value)}
                        rows={4}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm font-mono dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                        placeholder="输入自定义提示词..."
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
                      筛选完成 — {Array.from(recommendations.values()).filter(r => r.include).length} 条推荐。
                      确认选择后，进入下一步进行注释翻译。
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
            </div>
          )}

          {/* Step 3 · AI 注释 */}
          {['screened', 'annotating', 'annotated'].includes(workflowPhase) && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">3</span>
                  AI 注释
                  <span className="text-sm font-normal text-gray-500 ml-2 dark:text-gray-400">
                    (已选 {selectedIndices.size} 条)
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>

                {/* 3a: 选择用途 */}
                {workflowPhase === 'screened' && (
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
                      注释提示词
                    </button>
                    {showAnnotationPromptEditor && (
                      <div className="mt-2 p-4 bg-gray-50 rounded-lg space-y-3 dark:bg-gray-800">
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">提示词预设</label>
                          <div className="flex gap-2">
                            {(Object.keys(ANNOTATION_TEMPLATES) as AnnotationPresetKey[]).map((key) => (
                              <button
                                key={key}
                                onClick={() => {
                                  setAnnotationPreset(key);
                                  setAnnotationPrompt(buildAnnotationPrompt(ANNOTATION_TEMPLATES[key].prompt, sourceLanguage, targetLanguage));
                                }}
                                className={`px-3 py-1.5 rounded text-sm font-medium border transition-colors ${
                                  annotationPreset === key
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                                }`}
                              >
                                {ANNOTATION_TEMPLATES[key].label}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400">提示词内容（可自由修改）</label>
                          <textarea
                            value={annotationPrompt}
                            onChange={(e) => setAnnotationPrompt(e.target.value)}
                            rows={4}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm font-mono dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                            placeholder="输入自定义注释提示词..."
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <button
                      onClick={() => handleAIAnnotate('grammar')}
                      disabled={isProcessing}
                      className="p-4 rounded-lg border-2 text-left transition-all border-gray-200 hover:border-primary-300 cursor-pointer dark:border-gray-700 dark:hover:border-primary-600"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <BookOpen className="w-5 h-5 text-primary-600 dark:text-primary-400" />
                        <span className="font-medium text-gray-900 dark:text-gray-100">语法句型</span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        侧重语法结构、句型分析、实用表达
                      </p>
                    </button>
                    <button
                      onClick={() => handleAIAnnotate('vocab')}
                      disabled={isProcessing}
                      className="p-4 rounded-lg border-2 text-left transition-all border-gray-200 hover:border-primary-300 cursor-pointer dark:border-gray-700 dark:hover:border-primary-600"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <GraduationCap className="w-5 h-5 text-primary-600 dark:text-primary-400" />
                        <span className="font-medium text-gray-900 dark:text-gray-100">背单词</span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        侧重生词提取、词性释义、语境记忆
                      </p>
                    </button>
                  </div>
                  </>
                )}

                {/* 3b: 注释进行中 + 主题/结构选择（等待时可配置） */}
                {workflowPhase === 'annotating' && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* 左：进度 */}
                    <div>
                      <div className="flex items-center gap-2 mb-3">
                        <div className="animate-spin w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full" />
                        <span className="text-sm text-gray-600 dark:text-gray-400">
                          {annotationPurpose === 'grammar' ? '语法句型' : '背单词'}模式 · 注释中
                          {annotateTotalBatches > 0 ? ` ${annotateBatch}/${annotateTotalBatches}` : '...'}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => abortControllerRef.current?.abort()}
                        >
                          停止
                        </Button>
                      </div>
                      {annotateTotalBatches > 0 && (
                        <ProgressBar progress={(annotateBatch / annotateTotalBatches) * 100} />
                      )}
                      <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
                        注释完成后可预览卡片并生成牌组
                      </p>
                    </div>
                    {/* 右：主题/结构选择（等待时配置） */}
                    <div className="space-y-3">
                      <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
                        <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">卡片结构</label>
                        <div className="flex gap-2">
                          {([
                            { key: 'sentence' as CardStyle, label: '句型卡', desc: '正面：截图+音频 → 背面：原文+翻译+注释' },
                            { key: 'vocab' as CardStyle, label: '词汇卡', desc: '正面：单词 → 背面：释义+例句（含截图音频）' },
                          ]).map(({ key, label, desc }) => (
                            <label
                              key={key}
                              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border cursor-pointer transition-colors ${
                                cardStyles.has(key)
                                  ? 'bg-primary-500 text-white border-primary-500'
                                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                              }`}
                              title={desc}
                            >
                              <input
                                type="checkbox"
                                checked={cardStyles.has(key)}
                                onChange={() => {
                                  setCardStyles(prev => {
                                    const next = new Set(prev);
                                    if (next.has(key)) {
                                      if (next.size > 1) next.delete(key);
                                    } else {
                                      next.add(key);
                                    }
                                    return next;
                                  });
                                }}
                                className="sr-only"
                              />
                              {label}
                            </label>
                          ))}
                        </div>
                      </div>
                      <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
                        <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">视觉主题</label>
                        <div className="grid grid-cols-4 gap-1.5">
                          {([
                            { key: 'default' as CardTheme, label: '经典', desc: '清爽简洁，适合日常学习' },
                            { key: 'minimal' as CardTheme, label: '极简沉浸', desc: '衬线字体，纸质书质感' },
                            { key: 'netflix' as CardTheme, label: 'Netflix', desc: '暗色剧照风，沉浸观影感' },
                            { key: 'dictionary' as CardTheme, label: '硬核词典', desc: '信息密集，专业词典排版' },
                          ]).map(({ key, label, desc }) => (
                            <button
                              key={key}
                              onClick={() => setCardTheme(key)}
                              title={desc}
                              className={`px-2 py-1.5 rounded text-xs font-medium border transition-colors ${
                                cardTheme === key
                                  ? 'bg-primary-500 text-white border-primary-500'
                                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* 3c: 注释完成 */}
                {workflowPhase === 'annotated' && (
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className="p-3 bg-green-50 border border-green-200 rounded-lg dark:bg-green-900/20 dark:border-green-800 flex-1">
                        <p className="text-sm text-green-700 dark:text-green-300">
                          注释完成 — {selectedIndices.size} 条句子
                          {annotationPurpose && `（${annotationPurpose === 'grammar' ? '语法句型' : '背单词'}模式）`}
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
                        重新选择
                      </Button>
                    </div>

                    {/* 主题/结构选择 */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
                        <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">卡片结构</label>
                        <div className="flex gap-2">
                          {([
                            { key: 'sentence' as CardStyle, label: '句型卡', desc: '正面：截图+音频 → 背面：原文+翻译+注释' },
                            { key: 'vocab' as CardStyle, label: '词汇卡', desc: '正面：单词 → 背面：释义+例句（含截图音频）' },
                          ]).map(({ key, label, desc }) => (
                            <label
                              key={key}
                              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border cursor-pointer transition-colors ${
                                cardStyles.has(key)
                                  ? 'bg-primary-500 text-white border-primary-500'
                                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                              }`}
                              title={desc}
                            >
                              <input
                                type="checkbox"
                                checked={cardStyles.has(key)}
                                onChange={() => {
                                  setCardStyles(prev => {
                                    const next = new Set(prev);
                                    if (next.has(key)) {
                                      if (next.size > 1) next.delete(key);
                                    } else {
                                      next.add(key);
                                    }
                                    return next;
                                  });
                                }}
                                className="sr-only"
                              />
                              {label}
                            </label>
                          ))}
                        </div>
                      </div>
                      <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
                        <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">视觉主题</label>
                        <div className="grid grid-cols-4 gap-1.5">
                          {([
                            { key: 'default' as CardTheme, label: '经典', desc: '清爽简洁，适合日常学习' },
                            { key: 'minimal' as CardTheme, label: '极简沉浸', desc: '衬线字体，纸质书质感' },
                            { key: 'netflix' as CardTheme, label: 'Netflix', desc: '暗色剧照风，沉浸观影感' },
                            { key: 'dictionary' as CardTheme, label: '硬核词典', desc: '信息密集，专业词典排版' },
                          ]).map(({ key, label, desc }) => (
                            <button
                              key={key}
                              onClick={() => setCardTheme(key)}
                              title={desc}
                              className={`px-2 py-1.5 rounded text-xs font-medium border transition-colors ${
                                cardTheme === key
                                  ? 'bg-primary-500 text-white border-primary-500'
                                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

              </CardContent>
            </Card>
          )}

          {/* Step 4 · 预览、生成与下载 */}
          {((selectedIndices.size > 0 && !['screening', 'annotating'].includes(workflowPhase)) || isProcessing || (result && result.length > 0)) && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="bg-primary-100 text-primary-700 rounded-full w-6 h-6 flex items-center justify-center text-sm font-bold dark:bg-primary-900/40 dark:text-primary-300">4</span>
                  预览与生成
                </CardTitle>
              </CardHeader>
              <CardContent>
                {/* 注释后预览 + 处理按钮 */}
                {(workflowPhase === 'annotated' || (workflowPhase === 'idle' && !recommendations)) && !isProcessing && !(result && result.length > 0) && (
                  <div className="space-y-4">
                    {recommendations && (
                      <CardPreview
                        cards={Array.from(recommendations.values())
                          .filter(r => r.include && r.translation && selectedIndices.has(r.index))
                          .map(r => ({
                            sentence: subtitles.find(s => s.index === r.index)?.text || '',
                            translation: r.translation || '',
                            notes: r.notes || '',
                            word: r.word,
                            definition: r.definition,
                            start_sec: subtitles.find(s => s.index === r.index)?.start_sec || 0,
                            end_sec: subtitles.find(s => s.index === r.index)?.end_sec || 0,
                          }))}
                        cardStyles={Array.from(cardStyles)}
                        theme={cardTheme}
                        currentIndex={previewIndex}
                        onPrevious={() => setPreviewIndex(Math.max(0, previewIndex - 1))}
                        onNext={() => {
                          const maxIndex = Array.from(recommendations.values())
                            .filter(r => r.include && r.translation && selectedIndices.has(r.index)).length - 1;
                          setPreviewIndex(Math.min(maxIndex, previewIndex + 1));
                        }}
                      />
                    )}
                    {!recommendations && (
                      <>
                        <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
                          <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">卡片结构</label>
                          <div className="flex gap-2">
                            {([
                              { key: 'sentence' as CardStyle, label: '句型卡', desc: '正面：截图+音频 → 背面：原文+翻译+注释' },
                              { key: 'vocab' as CardStyle, label: '词汇卡', desc: '正面：单词 → 背面：释义+例句（含截图音频）' },
                            ]).map(({ key, label, desc }) => (
                              <label
                                key={key}
                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border cursor-pointer transition-colors ${
                                  cardStyles.has(key)
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                                }`}
                                title={desc}
                              >
                                <input
                                  type="checkbox"
                                  checked={cardStyles.has(key)}
                                  onChange={() => {
                                    setCardStyles(prev => {
                                      const next = new Set(prev);
                                      if (next.has(key)) {
                                        if (next.size > 1) next.delete(key);
                                      } else {
                                        next.add(key);
                                      }
                                      return next;
                                    });
                                  }}
                                  className="sr-only"
                                />
                                {label}
                              </label>
                            ))}
                          </div>
                        </div>
                        <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
                          <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">视觉主题</label>
                          <div className="grid grid-cols-4 gap-1.5">
                            {([
                              { key: 'default' as CardTheme, label: '经典', desc: '清爽简洁，适合日常学习' },
                              { key: 'minimal' as CardTheme, label: '极简沉浸', desc: '衬线字体，纸质书质感' },
                              { key: 'netflix' as CardTheme, label: 'Netflix', desc: '暗色剧照风，沉浸观影感' },
                              { key: 'dictionary' as CardTheme, label: '硬核词典', desc: '信息密集，专业词典排版' },
                            ]).map(({ key, label, desc }) => (
                              <button
                                key={key}
                                onClick={() => setCardTheme(key)}
                                title={desc}
                                className={`px-2 py-1.5 rounded text-xs font-medium border transition-colors ${
                                  cardTheme === key
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                        <p className="text-xs text-gray-400 dark:text-gray-500">
                          未使用 AI 标注，将生成基础卡片（含原文、音频、截图，无翻译/注释）
                        </p>
                      </>
                    )}
                    <Button
                      variant="primary"
                      className="w-full"
                      onClick={handleProcess}
                      disabled={selectedIndices.size === 0 || !videoFile}
                    >
                      开始处理 ({selectedIndices.size} 条)
                    </Button>
                  </div>
                )}

                {/* 处理进度 */}
                {isProcessing && (
                  <div className="space-y-3">
                    <ProcessingStatus
                      steps={processingSteps}
                      currentStepIndex={currentStep}
                    />
                    <ProgressBar
                      progress={(currentStep + 1) / PROCESSING_STEPS.length * 100}
                    />
                  </div>
                )}

                {/* 处理完成：卡片预览 + 下载 */}
                {result && result.length > 0 && (
                  <div className="space-y-4">
                    <CardPreview
                      cards={result}
                      cardStyles={Array.from(cardStyles)}
                      theme={cardTheme}
                      currentIndex={previewIndex}
                      onPrevious={() => setPreviewIndex(Math.max(0, previewIndex - 1))}
                      onNext={() => setPreviewIndex(Math.min(result.length - 1, previewIndex + 1))}
                    />
                    <Button
                      variant="primary"
                      className="w-full"
                      onClick={handleDownload}
                    >
                      <Download className="w-4 h-4 mr-2" />
                      下载牌组 (.apkg)
                    </Button>
                    {taskId && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() => {
                          window.open(processAPI.exportZipUrl(taskId), '_blank');
                        }}
                      >
                        <FolderOpen className="w-4 h-4 mr-1" />
                        导出带媒体 ZIP
                      </Button>
                    )}
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        onClick={() => {
                          const filename = videoFile?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo';
                          downloadString(generateCSVContent(result), `${filename}.csv`, 'text/csv');
                        }}
                      >
                        <FileSpreadsheet className="w-4 h-4 mr-1" />
                        导出 CSV
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        onClick={() => {
                          const filename = videoFile?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo';
                          downloadString(generateJSONContent(result), `${filename}.json`, 'application/json');
                        }}
                      >
                        <FileJson className="w-4 h-4 mr-1" />
                        导出 JSON
                      </Button>
                    </div>
                    <div className="flex items-center gap-2">
                      <AnkiSyncButton
                        cards={result}
                        deckName={videoFile?.name?.replace(/\.[^.]+$/, '') || 'ClipLingo'}
                        apiBase={API_BASE_URL}
                        cardStyles={Array.from(cardStyles)}
                        theme={cardTheme}
                      />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
