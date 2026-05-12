import JSZip from 'jszip';
import { themeAPI, ThemeListItem } from './themeAPI';

const REGISTRY_URL =
  'https://raw.githubusercontent.com/qinusui/cliplingo-templates/main/index.json';
const REPO_BASE =
  'https://raw.githubusercontent.com/qinusui/cliplingo-templates/main';

export interface MarketplaceEntry {
  name: string;
  label: string;
  author?: string;
  description?: string;
  preview?: string;
  path: string;
  updated?: string;
}

export const marketplaceAPI = {
  /** 拉取社区模板列表 */
  fetchList: async (): Promise<MarketplaceEntry[]> => {
    const resp = await fetch(REGISTRY_URL);
    if (!resp.ok) throw new Error('Failed to fetch template registry');
    return resp.json();
  },

  /** 安装模板：从 GitHub raw 逐个拉取文件 → 构建 ZIP → 走现有导入端点 */
  install: async (entry: MarketplaceEntry): Promise<void> => {
    const base = `${REPO_BASE}/${entry.path}`;

    const [frontRes, backRes, cssRes, metaRes] = await Promise.all([
      fetch(`${base}/front.html`),
      fetch(`${base}/back.html`),
      fetch(`${base}/style.css`),
      fetch(`${base}/theme.json`),
    ]);

    if (!frontRes.ok || !backRes.ok || !cssRes.ok || !metaRes.ok) {
      throw new Error('Failed to fetch template files');
    }

    const [frontHtml, backHtml, styleCss] = await Promise.all([
      frontRes.text(),
      backRes.text(),
      cssRes.text(),
    ]);
    const metaJson = await metaRes.text();

    const zip = new JSZip();
    zip.file('theme.json', metaJson);
    zip.file('front.html', frontHtml);
    zip.file('back.html', backHtml);
    zip.file('style.css', styleCss);

    const zipBlob = await zip.generateAsync({ type: 'blob' });
    const zipFile = new File([zipBlob], `${entry.name}.zip`, { type: 'application/zip' });

    await themeAPI.importZip(zipFile);
  },

  /** 将 preview 相对路径转为完整 URL */
  previewUrl: (entry: MarketplaceEntry): string | null => {
    if (!entry.preview) return null;
    return `${REPO_BASE}/${entry.preview}`;
  },

  /** 检查模板是否已安装 */
  isInstalled: (entry: MarketplaceEntry, installed: ThemeListItem[]): boolean => {
    return installed.some(t => t.name === entry.name);
  },
};
