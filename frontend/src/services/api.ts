import axios from 'axios';
import type { SubtitleListResponse, ProcessResult, ProcessedCard, SubtitleItem, AIRecommendResponse, AnnotationPurpose, ASREngine, ASREngineInfo, TranslateService, TranslateServiceInfo, TranslateBatchResponse } from '../types';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 字幕相关 API
export const subtitleAPI = {
  // 上传字幕文件
  upload: async (file: File, minDuration: number = 1.0): Promise<SubtitleListResponse> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await api.post<SubtitleListResponse>(
      `/api/subtitles/upload?min_duration=${minDuration}`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );

    return response.data;
  },

  // 转录：启动任务
  startTranscribe: async (
    video: File,
    minDuration: number = 1.0,
    language?: string,
    modelName?: string,
    asrEngine?: ASREngine
  ): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('video', video);
    const params = new URLSearchParams();
    params.append('min_duration', minDuration.toString());
    if (language) params.append('language', language);
    if (modelName) params.append('model_name', modelName);
    if (asrEngine) params.append('asr_engine', asrEngine);

    const response = await api.post<{ task_id: string; status: string }>(
      `/api/subtitles/transcribe?${params.toString()}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 }
    );
    return response.data;
  },

  // 获取可用 ASR 引擎列表
  getASREngines: async (): Promise<{ engines: ASREngineInfo[] }> => {
    const response = await api.get('/api/subtitles/asr/engines');
    return response.data;
  },

  // Whisper 转录：获取进度
  getTranscribeProgress: async (taskId: string) => {
    const response = await api.get(`/api/subtitles/transcribe/progress/${taskId}`);
    return response.data as {
      status: string;
      step: number;
      total_steps: number;
      message: string;
      error?: string;
      error_code?: string;
      result?: SubtitleListResponse;
      whisper_progress?: {
        progress: number;
        transcribed_sec: number;
        duration_sec: number;
        text: string;
      };
    };
  },

  // Whisper 转录：取消任务
  cancelTranscribe: async (taskId: string) => {
    const response = await api.post(`/api/subtitles/transcribe/cancel/${taskId}`);
    return response.data;
  },

  // 获取示例字幕
  getExample: async (): Promise<SubtitleListResponse> => {
    const response = await api.get<SubtitleListResponse>('/api/subtitles/example');
    return response.data;
  },

  // AI 推荐：启动任务
  startRecommend: async (
    subtitles: SubtitleItem[],
    apiKey?: string,
    customPrompt?: string,
    batchSize?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string
  ): Promise<{ task_id: string; status: string }> => {
    const response = await api.post<{ task_id: string; status: string }>(
      '/api/subtitles/ai-recommend',
      { subtitles, api_key: apiKey || undefined, custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30, api_base: apiBase || undefined, model_name: modelName || undefined,
        source_language: sourceLanguage || 'en', target_language: targetLanguage || 'zh' }
    );
    return response.data;
  },

  // AI 推荐：获取进度
  getRecommendProgress: async (taskId: string) => {
    const response = await api.get(`/api/subtitles/ai-recommend/progress/${taskId}`);
    return response.data as {
      status: string;
      batch: number;
      total_batches: number;
      message: string;
      result?: AIRecommendResponse;
    };
  },

  // AI 推荐：SSE 流式
  startRecommendStream: async function* (
    subtitles: SubtitleItem[],
    apiKey?: string,
    customPrompt?: string,
    batchSize?: number,
    aiConcurrency?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[]; message?: string }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-recommend-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        api_key: apiKey || undefined,
        custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30,
        ai_concurrency: aiConcurrency ?? 3,
        api_base: apiBase || undefined,
        model_name: modelName || undefined,
        source_language: sourceLanguage || 'en',
        target_language: targetLanguage || 'zh'
      }),
      signal
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(err || `HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let doneReceived = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop()!;
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'done') {
              doneReceived = true;
            }
            yield event;
            if (doneReceived) break;
          }
        }
        if (doneReceived) break;
      }
    } catch (e) {
      // 浏览器在流关闭时可能抛出 TypeError，已收到 done 时忽略
      if (!doneReceived) throw e;
    } finally {
      try { await reader.cancel(); } catch {}
    }
  },

  // AI 筛选：SSE 流式（只返回 include/reason，不做翻译注释）
  startScreenStream: async function* (
    subtitles: SubtitleItem[],
    apiKey?: string,
    customPrompt?: string,
    batchSize?: number,
    aiConcurrency?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[]; message?: string }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-screen-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        api_key: apiKey || undefined,
        custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30,
        ai_concurrency: aiConcurrency ?? 3,
        api_base: apiBase || undefined,
        model_name: modelName || undefined,
        source_language: sourceLanguage || 'en',
        target_language: targetLanguage || 'zh'
      }),
      signal
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(err || `HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let doneReceived = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop()!;
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'done') {
              doneReceived = true;
            }
            yield event;
            if (doneReceived) break;
          }
        }
        if (doneReceived) break;
      }
    } catch (e) {
      // 浏览器在流关闭时可能抛出 TypeError，已收到 done 时忽略
      if (!doneReceived) throw e;
    } finally {
      try { await reader.cancel(); } catch {}
    }
  },

  // AI 修正：SSE 流式（修正 ASR 转录错误）
  startCorrectStream: async function* (
    subtitles: SubtitleItem[],
    apiKey?: string,
    aiConcurrency?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[]; message?: string }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-correct-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        api_key: apiKey || undefined,
        ai_concurrency: aiConcurrency ?? 3,
        api_base: apiBase || undefined,
        model_name: modelName || undefined,
        source_language: sourceLanguage || 'en',
        target_language: targetLanguage || 'zh'
      }),
      signal
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(err || `HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let doneReceived = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop()!;
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'done') {
              doneReceived = true;
            }
            yield event;
            if (doneReceived) break;
          }
        }
        if (doneReceived) break;
      }
    } catch (e) {
      // 浏览器在流关闭时可能抛出 TypeError，已收到 done 时忽略
      if (!doneReceived) throw e;
    } finally {
      try { await reader.cancel(); } catch {}
    }
  },

  // AI 注释：SSE 流式（根据用途生成翻译和注释）
  startAnnotateStream: async function* (
    subtitles: SubtitleItem[],
    purpose: AnnotationPurpose,
    apiKey?: string,
    customPrompt?: string,
    batchSize?: number,
    aiConcurrency?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal,
    taskId?: string
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[]; message?: string }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-annotate-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        purpose,
        api_key: apiKey || undefined,
        custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30,
        ai_concurrency: aiConcurrency ?? 3,
        api_base: apiBase || undefined,
        model_name: modelName || undefined,
        source_language: sourceLanguage || 'en',
        target_language: targetLanguage || 'zh',
        task_id: taskId || undefined
      }),
      signal
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(err || `HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let doneReceived = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop()!;
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'done') {
              doneReceived = true;
            }
            yield event;
            if (doneReceived) break;
          }
        }
        if (doneReceived) break;
      }
    } catch (e) {
      // 浏览器在流关闭时可能抛出 TypeError，已收到 done 时忽略
      if (!doneReceived) throw e;
    } finally {
      try { await reader.cancel(); } catch {}
    }
  },

  // 检查 ffmpeg 安装状态
  getFFmpegStatus: async (): Promise<{ installed: boolean; version: string | null; path: string | null }> => {
    const response = await api.get('/api/subtitles/ffmpeg/status');
    return response.data;
  },

  // 检查 Whisper 安装状态
  getWhisperStatus: async (): Promise<{ installed: boolean; mode: string }> => {
    const response = await api.get('/api/subtitles/whisper/status');
    return response.data;
  },

  // 安装 Whisper
  installWhisper: async (): Promise<{ status: string; message: string }> => {
    const response = await api.post('/api/subtitles/whisper/install', null, { timeout: 600000 });
    return response.data;
  },

  // 提取视频内嵌字幕
  extractEmbeddedSubs: async (
    video: File,
    streamIndex: number = 0,
    minDuration: number = 1.0
  ): Promise<{
    found: boolean;
    streams: Array<{ index: number; codec: string; language: string; title: string; text_based: boolean }>;
    extracted: {
      stream_index: number;
      codec: string;
      language: string;
      subtitles: SubtitleListResponse['subtitles'];
      total: number;
      filtered: number;
    } | null;
    message: string;
  }> => {
    const formData = new FormData();
    formData.append('video', video);
    const params = new URLSearchParams();
    params.append('stream_index', streamIndex.toString());
    params.append('min_duration', minDuration.toString());

    const response = await api.post(
      `/api/subtitles/extract-embedded-subs?${params.toString()}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 }
    );
    return response.data;
  },

};

// 翻译相关 API
export const translateAPI = {
  // 获取可用翻译服务列表
  getServices: async (): Promise<{ services: TranslateServiceInfo[] }> => {
    const response = await api.get('/api/translate/services');
    return response.data;
  },

  // 批量翻译
  batch: async (
    texts: string[],
    service: TranslateService = 'bing',
    sourceLang: string = 'auto',
    targetLang: string = 'zh',
    apiKey?: string,
    apiBase?: string,
    modelName?: string
  ): Promise<TranslateBatchResponse> => {
    const response = await api.post<TranslateBatchResponse>('/api/translate/batch', {
      texts,
      service,
      source_lang: sourceLang,
      target_lang: targetLang,
      api_key: apiKey || undefined,
      api_base: apiBase || undefined,
      model_name: modelName || undefined,
    });
    return response.data;
  },
};

// 处理相关 API
export const processAPI = {
  // 上传文件并处理（支持多视频）
  uploadAndProcess: async (
    videoFiles: File[],
    subtitleFiles: (File | null)[],
    merge: boolean = true,
    minDuration: number = 1.0,
    apiKey?: string,
    preProcessed?: object[],
    apiBase?: string,
    modelName?: string,
    paddingStartMs?: number,
    paddingEndMs?: number,
    cardStyles?: string[],
    theme?: string,
    themeOverrides?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    screenPrompt?: string,
    annotationPurpose?: string,
    annotationPrompt?: string,
    selectRecommendedOnly?: boolean
  ): Promise<{ task_id: string; status: string; merge: boolean }> => {
    const formData = new FormData();
    videoFiles.forEach(f => formData.append('videos', f));
    subtitleFiles.forEach(f => { if (f) formData.append('subtitles', f); });
    formData.append('merge', merge.toString());
    formData.append('min_duration', minDuration.toString());
    if (apiKey) {
      formData.append('api_key', apiKey);
    }
    if (apiBase) {
      formData.append('api_base', apiBase);
    }
    if (modelName) {
      formData.append('model_name', modelName);
    }
    if (paddingStartMs !== undefined) {
      formData.append('padding_start_ms', paddingStartMs.toString());
    }
    if (paddingEndMs !== undefined) {
      formData.append('padding_end_ms', paddingEndMs.toString());
    }
    if (preProcessed && preProcessed.length > 0) {
      formData.append('pre_processed', JSON.stringify(preProcessed));
    }
    if (cardStyles && cardStyles.length > 0) {
      formData.append('card_styles', JSON.stringify(cardStyles));
    }
    if (theme) {
      formData.append('theme', theme);
    }
    if (themeOverrides) {
      formData.append('theme_overrides', themeOverrides);
    }
    if (sourceLanguage) {
      formData.append('source_language', sourceLanguage);
    }
    if (targetLanguage) {
      formData.append('target_language', targetLanguage);
    }
    if (screenPrompt) {
      formData.append('screen_prompt_criteria', screenPrompt);
    }
    if (annotationPurpose) {
      formData.append('annotation_purpose', annotationPurpose);
    }
    if (annotationPrompt) {
      formData.append('annotation_prompt_criteria', annotationPrompt);
    }
    if (selectRecommendedOnly !== undefined) {
      formData.append('select_recommended_only', selectRecommendedOnly.toString());
    }

    const response = await api.post<{ task_id: string; status: string; merge: boolean }>(
      '/api/process/upload-and-process',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );

    return response.data;
  },

  // Phase 1: 上传文件并仅处理媒体（不打包）
  uploadAndProcessMedia: async (
    videoFiles: File[],
    subtitleFiles: (File | null)[],
    merge: boolean = true,
    minDuration: number = 1.0,
    apiKey?: string,
    preProcessed?: object[],
    apiBase?: string,
    modelName?: string,
    paddingStartMs?: number,
    paddingEndMs?: number,
    sourceLanguage?: string,
    targetLanguage?: string,
    screenPrompt?: string,
    annotationPurpose?: string,
    annotationPrompt?: string,
    selectRecommendedOnly?: boolean
  ): Promise<{ task_id: string; status: string; merge: boolean }> => {
    const formData = new FormData();
    videoFiles.forEach(f => formData.append('videos', f));
    subtitleFiles.forEach(f => { if (f) formData.append('subtitles', f); });
    formData.append('merge', merge.toString());
    formData.append('min_duration', minDuration.toString());
    formData.append('stop_after_media', 'true');
    if (apiKey) formData.append('api_key', apiKey);
    if (apiBase) formData.append('api_base', apiBase);
    if (modelName) formData.append('model_name', modelName);
    if (paddingStartMs !== undefined) formData.append('padding_start_ms', paddingStartMs.toString());
    if (paddingEndMs !== undefined) formData.append('padding_end_ms', paddingEndMs.toString());
    if (preProcessed && preProcessed.length > 0) formData.append('pre_processed', JSON.stringify(preProcessed));
    if (sourceLanguage) formData.append('source_language', sourceLanguage);
    if (targetLanguage) formData.append('target_language', targetLanguage);
    if (screenPrompt) formData.append('screen_prompt_criteria', screenPrompt);
    if (annotationPurpose) formData.append('annotation_purpose', annotationPurpose);
    if (annotationPrompt) formData.append('annotation_prompt_criteria', annotationPrompt);
    if (selectRecommendedOnly !== undefined) formData.append('select_recommended_only', selectRecommendedOnly.toString());

    const response = await api.post<{ task_id: string; status: string; merge: boolean }>(
      '/api/process/upload-and-process',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
    return response.data;
  },

  // Phase 2: 从已处理的媒体生成 .apkg
  generateApkg: async (
    taskId: string,
    cardStyles?: string[],
    theme?: string,
    themeOverrides?: string,
  ): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('task_id', taskId);
    if (cardStyles && cardStyles.length > 0) formData.append('card_styles', JSON.stringify(cardStyles));
    if (theme) formData.append('theme', theme);
    if (themeOverrides) formData.append('theme_overrides', themeOverrides);

    const response = await api.post<{ task_id: string; status: string }>(
      '/api/process/generate-apkg',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
    return response.data;
  },

  // 开始处理
  start: async (
    videoPath: string,
    subtitlePath: string,
    minDuration: number = 1.0,
    apiKey?: string
  ): Promise<ProcessResult> => {
    const response = await api.post<ProcessResult>('/api/process/start', null, {
      params: {
        video_file_path: videoPath,
        subtitle_file_path: subtitlePath,
        min_duration: minDuration,
        api_key: apiKey,
      },
    });

    return response.data;
  },

  // 获取处理进度
  getProgress: async (taskId: string) => {
    const response = await api.get(`/api/process/progress/${taskId}`);
    return response.data as {
      task_id: string;
      status: string;
      step: number;
      total_steps: number;
      message: string;
      details: Record<string, number> | null;
      error: string | null;
      error_code: string | null;
      result: ProcessResult | null;
    };
  },

  // 清理输出文件
  cleanup: async (taskId: string) => {
    const response = await api.post('/api/process/cleanup', null, {
      params: { task_id: taskId },
    });
    return response.data;
  },

  // 测试 AI 连接
  testConnection: async (
    apiKey: string,
    apiBase: string,
    modelName: string
  ): Promise<{ valid: boolean; message: string }> => {
    const response = await api.post<{ valid: boolean; message: string }>(
      '/api/process/test-connection', null,
      { params: { api_key: apiKey, api_base: apiBase, model_name: modelName } }
    );
    return response.data;
  },

  // 获取模型列表
  listModels: async (
    apiKey: string,
    apiBase: string
  ): Promise<{ models: string[] }> => {
    const response = await api.post<{ models: string[] }>(
      '/api/process/list-models', null,
      { params: { api_key: apiKey, api_base: apiBase } }
    );
    return response.data;
  },

  // 打开日志文件夹
  openLogs: async () => {
    const response = await api.post('/api/open-logs');
    return response.data as { success: boolean; path: string };
  },

  // 检查更新
  checkUpdate: async () => {
    const response = await api.get('/api/check-update');
    return response.data as {
      has_update: boolean;
      current_version: string;
      latest_version?: string;
      download_url?: string;
      release_notes?: string;
      release_url?: string;
      error?: string;
    };
  },

  // 导出带媒体的 ZIP
  exportZipUrl: (taskId: string) => {
    return `${API_BASE_URL}/api/process/export-zip/${taskId}`;
  },
};

// 卡片相关 API
export const cardsAPI = {
  // 列出卡片
  list: async (apkgPath: string) => {
    const response = await api.get('/api/cards/list', {
      params: { apkg_path: apkgPath },
    });
    return response.data;
  },

  // 预览卡片
  preview: async (cards: ProcessedCard[]) => {
    const response = await api.post<{ html: string }>('/api/cards/preview', { cards });
    return response.data;
  },
};

// 健康检查
export const healthCheck = async () => {
  const response = await api.get('/health');
  return response.data;
};

export default api;
