import { ThemeOverrides } from '../types';

const API_BASE = '/api/themes';

export interface ThemeListItem {
  name: string;
  label: string;
  isBuiltin: boolean;
  version?: number;
  author?: string;
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
}

export const themeAPI = {
  /** 列出所有可用主题（内置 + 自定义） */
  listThemes: async (): Promise<ThemeListItem[]> => {
    const resp = await fetch(API_BASE);
    if (!resp.ok) return [];
    const data: ThemeListResponse = await resp.json();
    return data.themes || [];
  },

  /** 加载指定主题的 CSS 变量覆盖 */
  loadOverrides: async (theme: string): Promise<ThemeOverrides> => {
    const resp = await fetch(`${API_BASE}/${theme}`);
    if (!resp.ok) return {};
    const data = await resp.json();
    return data.variables || {};
  },

  /** 保存指定主题的 CSS 变量覆盖 */
  saveOverrides: async (theme: string, variables: ThemeOverrides): Promise<void> => {
    await fetch(`${API_BASE}/${theme}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ variables }),
    });
  },

  /** 重置指定主题为默认 */
  resetOverrides: async (theme: string): Promise<void> => {
    await fetch(`${API_BASE}/${theme}`, { method: 'DELETE' });
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
};
