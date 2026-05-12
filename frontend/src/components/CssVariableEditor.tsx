import { useTranslation } from 'react-i18next';
import { X, RotateCcw } from 'lucide-react';
import { ThemeOverrides, CssVariableField, CardTheme } from '../types';

const FONT_OPTIONS = [
  'system-ui, -apple-system, sans-serif',
  'Georgia, "Noto Serif", serif',
  '"Segoe UI", Roboto, sans-serif',
  '"Microsoft YaHei", "PingFang SC", sans-serif',
  'Consolas, "Courier New", monospace',
];

const FONT_LABELS: Record<string, string> = {
  'system-ui, -apple-system, sans-serif': 'System UI',
  'Georgia, "Noto Serif", serif': 'Serif',
  '"Segoe UI", Roboto, sans-serif': 'Segoe UI',
  '"Microsoft YaHei", "PingFang SC", sans-serif': 'YaHei / PingFang',
  'Consolas, "Courier New", monospace': 'Monospace',
};

const FIELDS: CssVariableField[] = [
  { key: '--card-bg', label: 'cssEditor.bgColor', type: 'color' },
  { key: '--card-text', label: 'cssEditor.textColor', type: 'color' },
  { key: '--accent-color', label: 'cssEditor.accentColor', type: 'color' },
  { key: '--translation-color', label: 'cssEditor.translationColor', type: 'color' },
  { key: '--annotation-color', label: 'cssEditor.annotationColor', type: 'color' },
  { key: '--font-sentence', label: 'cssEditor.fontSentence', type: 'font', options: FONT_OPTIONS },
  { key: '--font-translation', label: 'cssEditor.fontTranslation', type: 'font', options: FONT_OPTIONS },
  { key: '--font-size-sentence', label: 'cssEditor.fontSizeSentence', type: 'size' },
  { key: '--font-size-translation', label: 'cssEditor.fontSizeTranslation', type: 'size' },
  { key: '--card-padding', label: 'cssEditor.cardPadding', type: 'slider', min: 4, max: 40, step: 2 },
  { key: '--card-radius', label: 'cssEditor.cardRadius', type: 'slider', min: 0, max: 24, step: 2 },
  { key: '--card-shadow', label: 'cssEditor.cardShadow', type: 'slider', min: 0, max: 20, step: 1 },
];

interface CssVariableEditorProps {
  theme: CardTheme;
  overrides: ThemeOverrides;
  onChange: (overrides: ThemeOverrides) => void;
  onSave: () => void;
  onReset: () => void;
  onClose: () => void;
  hasUnsaved: boolean;
}

export const CssVariableEditor = ({
  overrides,
  onChange,
  onSave,
  onReset,
  onClose,
  hasUnsaved,
}: CssVariableEditorProps) => {
  const { t } = useTranslation();

  const getValue = (key: keyof ThemeOverrides): string => overrides[key] ?? '';

  const setValue = (key: keyof ThemeOverrides, value: string) => {
    onChange({ ...overrides, [key]: value });
  };

  const shadowToSlider = (val: string): number => {
    const m = val.match(/0\s+\d+px\s+(\d+)px/);
    return m ? parseInt(m[1]) : 0;
  };

  const sliderToShadow = (v: number): string =>
    v === 0 ? 'none' : `0 2px ${v}px rgba(0,0,0,0.15)`;

  const renderField = (field: CssVariableField) => {
    const val = getValue(field.key);

    switch (field.type) {
      case 'color':
        return (
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={val || '#ffffff'}
              onChange={e => setValue(field.key, e.target.value)}
              className="w-8 h-8 rounded border cursor-pointer"
            />
            <input
              type="text"
              value={val || ''}
              onChange={e => setValue(field.key, e.target.value)}
              placeholder="默认"
              className="flex-1 px-2 py-1 text-xs border rounded bg-white dark:bg-gray-700 dark:border-gray-600"
            />
          </div>
        );

      case 'font':
        return (
          <select
            value={val}
            onChange={e => setValue(field.key, e.target.value)}
            className="w-full px-2 py-1 text-xs border rounded bg-white dark:bg-gray-700 dark:border-gray-600"
          >
            <option value="">默认</option>
            {(field.options || []).map(f => (
              <option key={f} value={f}>{FONT_LABELS[f] || f}</option>
            ))}
          </select>
        );

      case 'size':
        return (
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={10}
              max={28}
              step={1}
              value={parseFloat(val) || 0}
              onChange={e => setValue(field.key, `${e.target.value}px`)}
              className="flex-1"
            />
            <span className="text-xs w-10 text-right tabular-nums">{val || '默认'}</span>
          </div>
        );

      case 'slider':
        if (field.key === '--card-shadow') {
          const sv = shadowToSlider(val);
          return (
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={field.min}
                max={field.max}
                step={field.step}
                value={sv}
                onChange={e => setValue(field.key, sliderToShadow(Number(e.target.value)))}
                className="flex-1"
              />
              <span className="text-xs w-8 text-right tabular-nums">{sv}px</span>
            </div>
          );
        }
        return (
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={field.min}
              max={field.max}
              step={field.step}
              value={parseFloat(val) || 0}
              onChange={e => setValue(field.key, `${e.target.value}px`)}
              className="flex-1"
            />
            <span className="text-xs w-10 text-right tabular-nums">{val || '默认'}</span>
          </div>
        );
    }
  };

  return (
    <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
          {t('cssEditor.title')}
        </span>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-2.5">
        {/* 颜色 */}
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
          {t('cssEditor.colors')}
        </div>
        {FIELDS.filter(f => f.type === 'color').map(f => (
          <label key={f.key} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-20 shrink-0">{t(f.label)}</span>
            <div className="flex-1">{renderField(f)}</div>
          </label>
        ))}

        {/* 字体 */}
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide pt-1">
          {t('cssEditor.fonts')}
        </div>
        {FIELDS.filter(f => f.type === 'font').map(f => (
          <label key={f.key} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-20 shrink-0">{t(f.label)}</span>
            <div className="flex-1">{renderField(f)}</div>
          </label>
        ))}

        {/* 字号 */}
        {FIELDS.filter(f => f.type === 'size').map(f => (
          <label key={f.key} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-20 shrink-0">{t(f.label)}</span>
            <div className="flex-1">{renderField(f)}</div>
          </label>
        ))}

        {/* 间距 */}
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide pt-1">
          {t('cssEditor.spacing')}
        </div>
        {FIELDS.filter(f => f.type === 'slider').map(f => (
          <label key={f.key} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-20 shrink-0">{t(f.label)}</span>
            <div className="flex-1">{renderField(f)}</div>
          </label>
        ))}
      </div>

      {/* 操作按钮 */}
      <div className="flex gap-2 mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
        <button
          onClick={onReset}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          <RotateCcw className="w-3 h-3" />
          {t('cssEditor.reset')}
        </button>
        <div className="flex-1" />
        <button
          onClick={onSave}
          disabled={!hasUnsaved}
          className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
            hasUnsaved
              ? 'bg-primary-500 text-white hover:bg-primary-600'
              : 'bg-gray-200 text-gray-400 cursor-not-allowed dark:bg-gray-700 dark:text-gray-500'
          }`}
        >
          {t('cssEditor.save')}
        </button>
      </div>
    </div>
  );
};
