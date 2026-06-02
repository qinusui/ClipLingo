import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Download, Upload, Settings, ChevronDown, ChevronUp, Code, X, Loader2, Zap, Palette } from 'lucide-react';
import JSZip from 'jszip';
import { themeAPI } from '../services/themeAPI';

// ─── Mock 预览数据（无真实卡片时的回退） ───
const MOCK_CARD = {
  sentence: "Well, the point is, you can't just walk away from this.",
  translation: '重点是，你不能就这样一走了之。',
  annotation: '<b>walk away from</b> 动词短语，意为「逃避、放弃」<br>常见搭配：walk away from responsibility',
  audio: '',
  screenshot: '<img src="https://picsum.photos/400/200?random=1" style="width:100%" alt="screenshot">',
  word: 'walk away',
  definition: 'to leave a difficult situation rather than dealing with it',
};

interface PreviewCardData {
  sentence: string;
  translation: string;
  notes: string;
  word?: string;
  definition?: string;
  audio_path?: string;
  screenshot_path?: string;
}

function toScreenshotTag(screenshotPath?: string): string {
  if (!screenshotPath) return '';
  return `<img src="${screenshotPath}" style="width:100%" alt="screenshot">`;
}

function buildPreviewCard(card: PreviewCardData) {
  return {
    sentence: card.sentence || '',
    translation: card.translation || '',
    annotation: card.notes || '',
    audio: card.audio_path || '',
    screenshot: toScreenshotTag(card.screenshot_path),
    word: card.word || '',
    definition: card.definition || '',
  };
}

// ─── AI System Prompt（新建模式） ───
const SYSTEM_PROMPT = `你是 ClipLingo 卡片模板设计师。用户描述风格需求，你生成 HTML/CSS 模板。

## 可用占位符
- {{sentence}}     原文句子
- {{translation}}  翻译
- {{annotation}}   注释（可能含 HTML，不要用 <pre> 包裹）
- {{audio}}        [sound:cliplingo_0001.mp3]（Anki 音频语法）
- {{screenshot}}   <img src="cliplingo_0001.jpg">（已是完整 img 标签）
- {{word}}         核心词汇（词汇卡场景使用）
- {{definition}}   词汇释义（词汇卡场景使用）

## 重要：同时支持句型卡和词汇卡
模板会被同时用于两种卡片类型。使用 Anki 条件语法区分：
- {{#Word}}...{{/Word}} 包裹仅在词汇卡显示的内容
- {{^Word}}...{{/Word}} 包裹仅在句型卡显示的内容
- {{#screenshot}}...{{/screenshot}} 包裹仅有截图时显示的内容

## 输出格式
每次输出完整的三个文件，用以下标记包裹：

<FRONT_HTML>
<!-- front.html 完整内容 -->
</FRONT_HTML>

<BACK_HTML>
<!-- back.html 完整内容（用 {{FrontSide}} 嵌入正面内容） -->
</BACK_HTML>

<STYLE_CSS>
/* style.css 完整内容 */
</STYLE_CSS>

## 规范要求
- 不使用 <script> 标签
- 不使用内联事件（onclick 等）
- 自定义类名加 cl- 前缀避免与 Anki 冲突
- back.html 用 {{FrontSide}} 嵌入正面内容
- CSS 兼容 Anki WebView，避免 CSS 变量
- 图片用 max-width: 100% 保证响应式
- 优先使用系统字体`;

// ─── AI System Prompt（修改模式） ───
const MODIFY_SYSTEM_PROMPT = `你是 ClipLingo 卡片模板设计师。用户会提供已有的模板文件，并根据其需求修改模板。

## 核心规则
- 用户的第一条消息包含当前模板 + 修改需求。必须立即输出修改后的完整模板文件。
- 禁止只回复确认消息（如"我理解了"、"请问你想怎么改"）——用户已经在第一条消息中说明了修改需求。
- 如果用户只说了简单的修改（如"把背景改成蓝色"），直接修改背景色并输出完整模板，不要追问。

## 可用占位符
- {{sentence}}     原文句子
- {{translation}}  翻译
- {{annotation}}   注释
- {{audio}}        [sound:cliplingo_0001.mp3]
- {{screenshot}}   <img src="cliplingo_0001.jpg">
- {{word}}         核心词汇
- {{definition}}   词汇释义

## 输出格式
每次输出完整的三个文件（修改后的完整版本，不是 diff），用以下标记包裹：

<FRONT_HTML>
<!-- front.html 完整内容 -->
</FRONT_HTML>

<BACK_HTML>
<!-- back.html 完整内容 -->
</BACK_HTML>

<STYLE_CSS>
/* style.css 完整内容 */
</STYLE_CSS>

## 规范要求
- 保留原有模板中好的设计，只修改用户要求的部分
- 不使用 <script> 标签或内联事件
- 自定义类名加 cl- 前缀
- back.html 用 {{FrontSide}} 嵌入正面内容
- CSS 兼容 Anki WebView`;

// ─── 类型 ───
interface TemplateFiles {
  front: string;
  back: string;
  css: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface ProviderConfig {
  apiKey: string;
  baseUrl: string;
  model: string;
}

// ─── 解析 AI 响应 ───
function parseAIResponse(text: string): TemplateFiles | null {
  const extract = (tag: string) => {
    const match = text.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, 'i'));
    return match ? match[1].trim() : null;
  };
  const front = extract('FRONT_HTML');
  const back = extract('BACK_HTML');
  const css = extract('STYLE_CSS');
  if (!front || !back || !css) return null;
  return { front, back, css };
}

// ─── 去除标记块，只保留自然语言 ───
function stripTags(text: string): string {
  return text
    .replace(/<FRONT_HTML>[\s\S]*?<\/FRONT_HTML>/gi, '')
    .replace(/<BACK_HTML>[\s\S]*?<\/BACK_HTML>/gi, '')
    .replace(/<STYLE_CSS>[\s\S]*?<\/STYLE_CSS>/gi, '')
    .trim();
}

// ─── 构建预览文档 ───
function fillPlaceholders(html: string, card: ReturnType<typeof buildPreviewCard>): string {
  return html
    .replace(/\{\{sentence\}\}/g, card.sentence)
    .replace(/\{\{translation\}\}/g, card.translation)
    .replace(/\{\{annotation\}\}/g, card.annotation)
    .replace(/\{\{audio\}\}/g, card.audio)
    .replace(/\{\{screenshot\}\}/g, card.screenshot)
    .replace(/\{\{word\}\}/g, card.word)
    .replace(/\{\{definition\}\}/g, card.definition);
}

function buildPreviewDoc(frontHtml: string, backHtml: string, css: string, cardData?: PreviewCardData): { frontDoc: string; backDoc: string } {
  const card = cardData ? buildPreviewCard(cardData) : MOCK_CARD;
  const frontFilled = fillPlaceholders(frontHtml, card);
  const frontDoc = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${frontFilled}</body></html>`;

  // 背面：把正面渲染结果注入 {{FrontSide}}
  const backWithFront = backHtml.replace(/\{\{FrontSide\}\}/g, frontFilled);
  const backFilled = fillPlaceholders(backWithFront, card);
  const backDoc = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${backFilled}</body></html>`;

  return { frontDoc, backDoc };
}

// ─── 导出 ZIP ───
async function exportZip(template: TemplateFiles, themeName: string): Promise<void> {
  const zip = new JSZip();
  zip.file('front.html', template.front);
  zip.file('back.html', template.back);
  zip.file('style.css', template.css);
  zip.file('theme.json', JSON.stringify({
    name: themeName,
    label: themeName,
    version: 1,
    author: 'ClipLingo Style Generator',
  }, null, 2));

  const blob = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${themeName}.zip`;
  document.body.appendChild(a);
  a.click();
  URL.revokeObjectURL(url);
  a.remove();
}

// ─── 导入到 ClipLingo ───
async function importToApp(template: TemplateFiles, themeName: string): Promise<void> {
  const zip = new JSZip();
  zip.file('front.html', template.front);
  zip.file('back.html', template.back);
  zip.file('style.css', template.css);
  zip.file('theme.json', JSON.stringify({
    name: themeName,
    label: themeName,
    version: 1,
    author: 'ClipLingo Style Generator',
  }, null, 2));

  const blob = await zip.generateAsync({ type: 'blob' });
  const file = new File([blob], `${themeName}.zip`, { type: 'application/zip' });
  await themeAPI.importZip(file);
}

// ─── localStorage 持久化 Provider 配置 ───
const LS_KEY = 'stylegen_provider';

function loadProviderConfig(): ProviderConfig {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { apiKey: '', baseUrl: '', model: '' };
}

function saveProviderConfig(cfg: ProviderConfig) {
  localStorage.setItem(LS_KEY, JSON.stringify(cfg));
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  预览面板
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const PreviewPane = ({ template, activeTab, previewCard }: { template: TemplateFiles | null; activeTab: 'front' | 'back'; previewCard?: PreviewCardData }) => {
  if (!template) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
        生成模板后将在此显示预览
      </div>
    );
  }

  const { frontDoc, backDoc } = buildPreviewDoc(template.front, template.back, template.css, previewCard);
  const doc = activeTab === 'front' ? frontDoc : backDoc;

  return (
    <iframe
      srcDoc={doc}
      sandbox="allow-scripts allow-same-origin"
      className="w-full h-full min-h-[400px] border-0 bg-white"
      title="Card Preview"
    />
  );
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  快捷风格标签
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const QUICK_STYLES = [
  { emoji: '🌙', label: '暗色系', prompt: '深色背景，柔和浅色文字，Netflix 字幕风格' },
  { emoji: '☀️', label: '亮色系', prompt: '白色背景，简洁干净，适合打印' },
  { emoji: '📖', label: '学术风', prompt: '类似词典排版，古典衬线字体，适合深度阅读' },
  { emoji: '🎬', label: '影视风', prompt: '类似电影字幕，宽荧幕比例，沉浸式暗色背景' },
  { emoji: '🎮', label: '赛博朋克', prompt: '赛博朋克风格，霓虹色调，深色背景配荧光色文字' },
  { emoji: '🌸', label: '清新风', prompt: '柔和配色，圆角卡片，留白充裕，适合日常学习' },
];

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface InitialTheme {
  name: string;
  label: string;
  front: string;
  back: string;
  css: string;
}

interface StyleGeneratorProps {
  onClose: () => void;
  onImported?: () => void;
  initialTheme?: InitialTheme;
  previewCard?: PreviewCardData;
}

function buildInitialMessage(theme: InitialTheme): string {
  return `我正在微调一个已有的卡片模板「${theme.label}」。请先阅读当前模板文件，然后在用户提出修改需求后直接修改模板。

注意：不要只回复确认消息！必须直接输出修改后的完整模板文件。如果用户只说了一个简单的修改，立即输出修改后的完整模板。

当前模板文件：

<FRONT_HTML>
${theme.front}
</FRONT_HTML>

<BACK_HTML>
${theme.back}
</BACK_HTML>

<STYLE_CSS>
${theme.css}
</STYLE_CSS>`;
}

export const StyleGenerator = ({ onClose, onImported, initialTheme, previewCard }: StyleGeneratorProps) => {
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    initialTheme
      ? [{ role: 'user', content: buildInitialMessage(initialTheme) }]
      : []
  );
  const [input, setInput] = useState('');
  // 修改模式：立即用当前模板初始化预览，用户无需等待即可看到要改什么
  const [template, setTemplate] = useState<TemplateFiles | null>(() =>
    initialTheme
      ? { front: initialTheme.front, back: initialTheme.back, css: initialTheme.css }
      : null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [previewTab, setPreviewTab] = useState<'front' | 'back'>('front');
  const [showConfig, setShowConfig] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importOk, setImportOk] = useState(false);
  const [provider, setProvider] = useState<ProviderConfig>(loadProviderConfig);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // 持久化 provider 配置
  useEffect(() => { saveProviderConfig(provider); }, [provider]);

  // 自动滚动到最新消息
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const isModifyMode = !!initialTheme;

  const handleSend = useCallback(async (text?: string) => {
    const userInput = (text ?? input).trim();
    if (!userInput || loading) return;

    setInput('');
    setError('');

    const newMessages: ChatMessage[] = [
      ...messages,
      { role: 'user', content: userInput },
    ];
    setMessages(newMessages);
    setLoading(true);

    try {
      const resp = await fetch('/api/style-generator/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: newMessages,
          system_prompt: isModifyMode ? MODIFY_SYSTEM_PROMPT : SYSTEM_PROMPT,
          model: provider.model || undefined,
          api_key: provider.apiKey || undefined,
          base_url: provider.baseUrl || undefined,
          max_tokens: 4000,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: '请求失败' }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const data = await resp.json();
      const aiText = data.text;

      const parsed = parseAIResponse(aiText);
      if (parsed) setTemplate(parsed);

      setMessages([...newMessages, { role: 'assistant', content: aiText }]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '未知错误';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [input, messages, loading, provider, isModifyMode]);

  const handleExport = useCallback(async () => {
    if (!template) return;
    setExporting(true);
    try {
      await exportZip(template, 'my-card-theme');
    } finally {
      setExporting(false);
    }
  }, [template]);

  const handleImport = useCallback(async () => {
    if (!template) return;
    setImporting(true);
    setImportOk(false);
    setError('');
    try {
      await importToApp(template, `generated-${Date.now()}`);
      // 必须先刷新列表再标记成功，否则用户可能在列表更新前关掉弹窗
      await onImported?.();
      setImportOk(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入失败');
    } finally {
      setImporting(false);
    }
  }, [template, onImported]);

  // 对话区只展示自然语言部分（不含标记块）
  const displayContent = (msg: ChatMessage) => {
    if (msg.role === 'user') return msg.content;
    // 尝试解析，如果有模板则只展示自然语言部分
    const stripped = stripTags(msg.content);
    return stripped || msg.content;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-6xl mx-4 h-[90vh] flex flex-col overflow-hidden">
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <Palette className="w-5 h-5 text-primary-500" />
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">
              ClipLingo 卡片样式生成器
            </h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ── Body ── */}
        <div className="flex-1 flex min-h-0">
          {/* 左侧：对话区 */}
          <div className="w-1/2 border-r border-gray-200 dark:border-gray-700 flex flex-col min-w-0">
            {/* 快捷风格 */}
            {messages.length === 0 && (
              <div className="px-4 pt-3 pb-2 shrink-0">
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
                  你好！描述你想要的卡片风格，AI 将为你生成 HTML/CSS 模板。
                </p>
                <div className="flex flex-wrap gap-2">
                  {QUICK_STYLES.map(s => (
                    <button
                      key={s.label}
                      onClick={() => handleSend(s.prompt)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-full border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                    >
                      <span>{s.emoji}</span> {s.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {messages.map((m, i) => (
                <div key={i} className={`${m.role === 'user' ? 'text-right' : 'text-left'}`}>
                  <div className={`inline-block max-w-[90%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === 'user'
                      ? 'bg-primary-500 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200'
                  }`}>
                    {displayContent(m)}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex items-center gap-2 text-gray-400 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  AI 正在生成...
                </div>
              )}
              {error && (
                <div className="p-3 bg-red-50 dark:bg-red-900/10 rounded-lg text-sm text-red-600 dark:text-red-400">
                  {error}
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* 输入栏 */}
            <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                  placeholder="描述你想要的卡片风格..."
                  disabled={loading}
                  className="flex-1 px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                />
                <button
                  onClick={() => handleSend()}
                  disabled={loading || !input.trim()}
                  className="px-3 py-2 rounded-lg bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-50 transition-colors"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {/* 右侧：预览区 */}
          <div className="w-1/2 flex flex-col min-w-0">
            {/* 预览标签切换 + 操作按钮 */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700 shrink-0">
              <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-700 rounded-lg p-0.5">
                <button
                  onClick={() => setPreviewTab('front')}
                  className={`px-3 py-1 text-xs rounded-md transition-colors ${
                    previewTab === 'front' ? 'bg-white dark:bg-gray-600 shadow-sm font-medium' : 'text-gray-500'
                  }`}
                >
                  正面
                </button>
                <button
                  onClick={() => setPreviewTab('back')}
                  className={`px-3 py-1 text-xs rounded-md transition-colors ${
                    previewTab === 'back' ? 'bg-white dark:bg-gray-600 shadow-sm font-medium' : 'text-gray-500'
                  }`}
                >
                  背面
                </button>
              </div>

              <div className="flex items-center gap-1.5">
                {template && (
                  <>
                    <button
                      onClick={handleExport}
                      disabled={exporting}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-md border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
                    >
                      {exporting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                      导出 ZIP
                    </button>
                    <button
                      onClick={handleImport}
                      disabled={importing}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-md bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-50 transition-colors"
                    >
                      {importOk ? '已导入' : importing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                      {importOk ? '已导入' : '导入应用'}
                    </button>
                  </>
                )}
                <button
                  onClick={() => setShowConfig(!showConfig)}
                  className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md transition-colors ${
                    showConfig ? 'bg-gray-200 dark:bg-gray-600' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700'
                  }`}
                >
                  <Settings className="w-3 h-3" />
                  模型配置
                  {showConfig ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
              </div>
            </div>

            {/* 模型配置面板 */}
            {showConfig && (
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 space-y-2 shrink-0">
                <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                  <Zap className="w-3 h-3" />
                  支持 DeepSeek / OpenAI / Qwen / 豆包 等所有 OpenAI 兼容接口
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="block text-[10px] text-gray-400 mb-0.5">API Key</label>
                    <input
                      type="password"
                      value={provider.apiKey}
                      onChange={e => setProvider(p => ({ ...p, apiKey: e.target.value }))}
                      placeholder="sk-..."
                      className="w-full px-2 py-1 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] text-gray-400 mb-0.5">Base URL</label>
                    <input
                      type="text"
                      value={provider.baseUrl}
                      onChange={e => setProvider(p => ({ ...p, baseUrl: e.target.value }))}
                      placeholder="https://api.deepseek.com"
                      className="w-full px-2 py-1 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] text-gray-400 mb-0.5">Model</label>
                    <input
                      type="text"
                      value={provider.model}
                      onChange={e => setProvider(p => ({ ...p, model: e.target.value }))}
                      placeholder="deepseek-chat"
                      className="w-full px-2 py-1 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  </div>
                </div>
                <p className="text-[10px] text-gray-400">
                  留空则使用服务器默认配置（DeepSeek）。配置仅保存在本地浏览器。
                </p>
              </div>
            )}

            {/* 预览 iframe */}
            <div className="flex-1 overflow-auto p-4">
              <PreviewPane template={template} activeTab={previewTab} previewCard={previewCard} />
            </div>

            {/* 文件源码查看 */}
            {template && (
              <div className="border-t border-gray-200 dark:border-gray-700 shrink-0">
                <FileTabs template={template} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  文件源码查看子组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const FileTabs = ({ template }: { template: TemplateFiles }) => {
  const [tab, setTab] = useState<'front' | 'back' | 'css'>('front');

  const files: Record<'front' | 'back' | 'css', string> = {
    front: template.front,
    back: template.back,
    css: template.css,
  };

  return (
    <div>
      <div className="flex items-center gap-1 px-4 pt-2">
        {(['front', 'back', 'css'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1 text-xs rounded-t-md transition-colors ${
              tab === t
                ? 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 font-medium'
                : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
            }`}
          >
            <Code className="w-3 h-3 inline mr-1" />
            {t === 'front' ? 'front.html' : t === 'back' ? 'back.html' : 'style.css'}
          </button>
        ))}
      </div>
      <pre className="mx-4 mb-3 p-3 bg-gray-100 dark:bg-gray-700 rounded-lg rounded-tl-none text-xs text-gray-700 dark:text-gray-300 overflow-auto max-h-32 whitespace-pre-wrap font-mono">
        {files[tab]}
      </pre>
    </div>
  );
};
