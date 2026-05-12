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
  corrected_text?: string;
}

export type CardStyle = 'sentence' | 'vocab';

// 卡片主题（内置 + 自定义）
export type BuiltinTheme = 'default' | 'minimal' | 'netflix' | 'dictionary';
export type CardTheme = BuiltinTheme | string;

// 自定义主题元数据
export interface CustomThemeMeta {
  name: string;
  label: string;
  version?: number;
  author?: string;
  isCustom: true;
}

// CSS 变量覆盖（用户自定义样式）
export interface ThemeOverrides {
  '--card-bg'?: string;
  '--card-text'?: string;
  '--translation-color'?: string;
  '--annotation-color'?: string;
  '--accent-color'?: string;
  '--font-sentence'?: string;
  '--font-size-sentence'?: string;
  '--font-translation'?: string;
  '--font-size-translation'?: string;
  '--card-padding'?: string;
  '--card-radius'?: string;
  '--card-shadow'?: string;
}

// CSS 变量编辑器字段定义
export interface CssVariableField {
  key: keyof ThemeOverrides;
  label: string;
  type: 'color' | 'font' | 'size' | 'slider';
  options?: string[];  // for font selector
  min?: number;
  max?: number;
  step?: number;
}

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
