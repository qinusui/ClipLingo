import axios from 'axios';
import type { SubtitleListResponse, ProcessResult, ProcessedCard, SubtitleItem, AIRecommendResponse, AnnotationPurpose } from '../types';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

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

  // Whisper 转录：启动任务
  startTranscribe: async (
    video: File,
    minDuration: number = 1.0,
    language?: string,
    modelName?: string
  ): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('video', video);
    const params = new URLSearchParams();
    params.append('min_duration', minDuration.toString());
    if (language) params.append('language', language);
    if (modelName) params.append('model_name', modelName);

    const response = await api.post<{ task_id: string; status: string }>(
      `/api/subtitles/transcribe?${params.toString()}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 }
    );
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
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[] }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-recommend-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        api_key: apiKey || undefined,
        custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30,
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

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop()!;
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          yield JSON.parse(line.slice(6));
        }
      }
    }
  },

  // AI 筛选：SSE 流式（只返回 include/reason，不做翻译注释）
  startScreenStream: async function* (
    subtitles: SubtitleItem[],
    apiKey?: string,
    customPrompt?: string,
    batchSize?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[] }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-screen-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        api_key: apiKey || undefined,
        custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30,
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

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop()!;
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          yield JSON.parse(line.slice(6));
        }
      }
    }
  },

  // AI 注释：SSE 流式（根据用途生成翻译和注释）
  startAnnotateStream: async function* (
    subtitles: SubtitleItem[],
    purpose: AnnotationPurpose,
    apiKey?: string,
    customPrompt?: string,
    batchSize?: number,
    apiBase?: string,
    modelName?: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    signal?: AbortSignal
  ): AsyncGenerator<{ type: string; total_batches?: number; batch?: number; items?: any[] }> {
    const response = await fetch(`${API_BASE_URL}/api/subtitles/ai-annotate-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtitles,
        purpose,
        api_key: apiKey || undefined,
        custom_prompt: customPrompt || undefined,
        batch_size: batchSize ?? 30,
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

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop()!;
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          yield JSON.parse(line.slice(6));
        }
      }
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

// 处理相关 API
export const processAPI = {
  // 上传文件并处理
  uploadAndProcess: async (
    videoFile: File,
    subtitleFile: File,
    minDuration: number = 1.0,
    apiKey?: string,
    preProcessed?: object[],
    apiBase?: string,
    modelName?: string,
    paddingStartMs?: number,
    paddingEndMs?: number,
    cardStyles?: string[],
    theme?: string
  ): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('video', videoFile);
    formData.append('subtitle', subtitleFile);
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

    const response = await api.post<{ task_id: string; status: string }>(
      '/api/process/upload-and-process',
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

// 队列批量处理 API
export const queueAPI = {
  // 批量添加任务
  add: async (
    videoFiles: File[],
    subtitleFiles: (File | null)[],
    params: {
      apiKey?: string;
      apiBase?: string;
      modelName?: string;
      minDuration?: number;
      language?: string;
      whisperModel?: string;
      forceTranscribe?: boolean;
      paddingStartMs?: number;
      paddingEndMs?: number;
      cardStyles?: string[];
      theme?: string;
    } = {}
  ): Promise<{ batch_id: string; tasks: Array<{ task_id: string; video_name: string; status: string }>; total: number }> => {
    const formData = new FormData();
    videoFiles.forEach(f => formData.append('videos', f));
    subtitleFiles.forEach(f => { if (f) formData.append('subtitles', f); });
    if (params.apiKey) formData.append('api_key', params.apiKey);
    if (params.apiBase) formData.append('api_base', params.apiBase);
    if (params.modelName) formData.append('model_name', params.modelName);
    if (params.minDuration !== undefined) formData.append('min_duration', params.minDuration.toString());
    if (params.language) formData.append('language', params.language);
    if (params.whisperModel) formData.append('whisper_model', params.whisperModel);
    if (params.forceTranscribe) formData.append('force_transcribe', 'true');
    if (params.paddingStartMs !== undefined) formData.append('padding_start_ms', params.paddingStartMs.toString());
    if (params.paddingEndMs !== undefined) formData.append('padding_end_ms', params.paddingEndMs.toString());
    if (params.cardStyles) formData.append('card_styles', JSON.stringify(params.cardStyles));
    if (params.theme) formData.append('theme', params.theme);

    const response = await api.post('/api/queue/add', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    });
    return response.data;
  },

  // 获取队列状态
  getStatus: async (batchId?: string) => {
    const params: Record<string, string> = {};
    if (batchId) params.batch_id = batchId;
    const response = await api.get('/api/queue/status', { params });
    return response.data as {
      batch_id: string | null;
      tasks: Array<{
        task_id: string;
        video_name: string;
        status: string;
        step: number;
        message: string;
        result?: {
          success: boolean;
          task_id: string;
          video_name: string;
          cards_count: number;
          apkg_path: string;
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
      }>;
      total: number;
      done: number;
      failed: number;
      cancelled: number;
      running: boolean;
    };
  },

  // 取消单个任务
  cancel: async (taskId: string) => {
    const response = await api.delete(`/api/queue/${taskId}`);
    return response.data;
  },

  // 取消整个批次
  cancelBatch: async (batchId: string) => {
    const response = await api.delete(`/api/queue/batch/${batchId}`);
    return response.data;
  },

  // 下载全部 ZIP
  downloadAllUrl: (batchId?: string) => {
    const base = API_BASE_URL;
    const params = batchId ? `?batch_id=${batchId}` : '';
    return `${base}/api/queue/download-all${params}`;
  },

  // 导出带媒体的 ZIP（批量）
  exportAllZipUrl: (batchId?: string) => {
    const base = API_BASE_URL;
    const params = batchId ? `?batch_id=${batchId}` : '';
    return `${base}/api/queue/export-all-zip${params}`;
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
