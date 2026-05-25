import { ThemeOverrides, CssVariableField } from '../types';

const API_BASE = '/api/themes';

export interface ThemeListItem {
  name: string;
  label: string;
  isBuiltin: boolean;
  version?: number;
  author?: string;
  supportsVariables?: boolean;
}

export interface ThemeListResponse {
  themes: ThemeListItem[];
}

export interface ImportResult {
  success: boolean;
  name: string;
  label: string;
  version?: number;
  author?: string;
  supportsVariables?: boolean;
}

export interface ThemeDefaults {
  theme: string;
  defaults: Record<string, string>;
}

export interface PreviewCssResponse {
  css: string;
}

export const themeAPI = {
  /** 列出所有可用主题（内置 + 自定义） */
  listThemes: async (): Promise<ThemeListItem[]> => {
    const resp = await fetch(API_BASE);
    if (!resp.ok) return [];
    const data: ThemeListResponse = await resp.json();
    return data.themes || [];
  },

  /** 获取 CSS 变量元数据（字段定义） */
  getVariableFields: async (): Promise<CssVariableField[]> => {
    const resp = await fetch(`${API_BASE}/variables`);
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.fields || [];
  },

  /** 获取指定主题的 CSS 变量默认值 */
  getThemeDefaults: async (theme: string): Promise<Record<string, string>> => {
    const resp = await fetch(`${API_BASE}/variables/${theme}`);
    if (!resp.ok) return {};
    const data: ThemeDefaults = await resp.json();
    return data.defaults || {};
  },

  /** 加载指定主题的 CSS 变量覆盖 */
  loadOverrides: async (theme: string): Promise<{ variables: ThemeOverrides; isCustom?: boolean; supportsVariables?: boolean }> => {
    const resp = await fetch(`${API_BASE}/${theme}`);
    if (!resp.ok) return { variables: {} };
    const data = await resp.json();
    return {
      variables: data.variables || {},
      isCustom: data.isCustom || false,
      supportsVariables: data.supportsVariables || false,
    };
  },

  /** 保存指定主题的 CSS 变量覆盖，返回成功或错误信息 */
  saveOverrides: async (theme: string, variables: ThemeOverrides): Promise<{ ok: boolean; detail?: string }> => {
    const resp = await fetch(`${API_BASE}/${theme}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ variables }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      return { ok: false, detail: err.detail || `保存失败 (${resp.status})` };
    }
    return { ok: true };
  },

  /** 重置指定主题为默认 */
  resetOverrides: async (theme: string): Promise<void> => {
    await fetch(`${API_BASE}/${theme}`, { method: 'DELETE' });
  },

  /** 获取注入覆盖后的预览 CSS（替代客户端 buildOverrideCss） */
  getPreviewCss: async (theme: string, overrides: ThemeOverrides): Promise<string> => {
    const resp = await fetch(`${API_BASE}/preview-css`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme, overrides }),
    });
    if (!resp.ok) return '';
    const data: PreviewCssResponse = await resp.json();
    return data.css || '';
  },

  /** 导入自定义主题 ZIP 包 */
  importZip: async (zipFile: File): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append('file', zipFile);
    const resp = await fetch(`${API_BASE}/import`, {
      method: 'POST',
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '导入失败' }));
      throw new Error(err.detail || '导入失败');
    }
    return resp.json();
  },

  /** 删除自定义主题 */
  deleteTheme: async (name: string): Promise<void> => {
    const resp = await fetch(`${API_BASE}/custom/${name}`, { method: 'DELETE' });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '删除失败' }));
      throw new Error(err.detail || '删除失败');
    }
  },

  /** 获取自定义主题的源文件（供 AI 继续调整使用） */
  getCustomThemeFiles: async (name: string): Promise<{ name: string; label: string; front: string; back: string; css: string; supportsVariables?: boolean } | null> => {
    const resp = await fetch(`${API_BASE}/custom/${name}`);
    if (!resp.ok) return null;
    return resp.json();
  },
};
