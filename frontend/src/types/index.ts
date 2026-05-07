// API 响应类型
export interface SubtitleItem {
  index: number;
  start_sec: number;
  end_sec: number;
  text: string;
  duration: number;
  selected?: boolean;
}

export interface SubtitleListResponse {
  subtitles: SubtitleItem[];
  total: number;
  filtered: number;
}

export interface ProcessResult {
  success: boolean;
  message: string;
  cards_count: number;
  apkg_path: string | null;
  apkg_url?: string;
  task_id?: string;
  cards: ProcessedCard[];
}

export interface ProcessedCard {
  sentence: string;
  translation: string;
  notes: string;
  word?: string;
  definition?: string;
  start_sec: number;
  end_sec: number;
  audio_path?: string;
  screenshot_path?: string;
}

export interface AIRecommendation {
  index: number;
  include: boolean;
  reason: string;
  translation?: string;
  notes?: string;
  word?: string;
  definition?: string;
}

export type CardStyle = 'sentence' | 'vocab';

// 卡片主题
export type CardTheme = 'default' | 'minimal' | 'netflix' | 'dictionary';

// 工作流阶段
export type WorkflowPhase = 'idle' | 'screening' | 'screened' | 'annotating' | 'annotated' | 'generating';

// AI 注释用途
export type AnnotationPurpose = 'grammar' | 'vocab';

export interface AIRecommendResponse {
  recommendations: AIRecommendation[];
}

export interface ProcessProgress {
  step: string;
  message: string;
  progress: number;
  total_steps: number;
  current_step: number;
}
