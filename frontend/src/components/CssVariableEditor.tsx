import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { X, RotateCcw, Check, Undo2 } from 'lucide-react';
import { ThemeOverrides, CssVariableField, CardTheme } from '../types';
import { themeAPI } from '../services/themeAPI';

const COLOR_RE = /^#[0-9a-fA-F]{3,8}$|^[a-z]+$/;

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
  theme,
  overrides,
  onChange,
  onSave,
  onReset,
  onClose,
  hasUnsaved,
}: CssVariableEditorProps) => {
  const { t } = useTranslation();
  const [fields, setFields] = useState<CssVariableField[]>([]);
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [colorErrors, setColorErrors] = useState<Set<string>>(new Set());
  const [saveToast, setSaveToast] = useState(false);

  // 加载字段元数据和主题默认值
  useEffect(() => {
    themeAPI.getVariableFields().then(setFields);
  }, []);

  useEffect(() => {
    themeAPI.getThemeDefaults(theme).then(setDefaults);
  }, [theme]);

  const getValue = (key: string): string => overrides[key] ?? '';

  const setValue = (key: string, value: string) => {
    const next = { ...overrides };

    // 颜色校验
    if (value && fields.find(f => f.key === key)?.type === 'color') {
      if (!COLOR_RE.test(value)) {
        setColorErrors(prev => new Set(prev).add(key));
      } else {
        setColorErrors(prev => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    }

    if (value) {
      next[key] = value;
    } else {
      delete next[key];
    }
    onChange(next);
  };

  const resetKey = (key: string) => {
    const next = { ...overrides };
    delete next[key];
    setColorErrors(prev => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
    onChange(next);
  };

  const handleSave = () => {
    if (colorErrors.size > 0) return;
    onSave();
    setSaveToast(true);
    setTimeout(() => setSaveToast(false), 2000);
  };

  const hasColorError = colorErrors.size > 0;

  // ── 渲染单个字段 ──

  const renderField = (field: CssVariableField) => {
    const val = getValue(field.key);
    const def = defaults[field.key] || '';
    const isError = colorErrors.has(field.key);

    switch (field.type) {
      case 'color':
        return (
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={val || def || '#cccccc'}
              onChange={e => setValue(field.key, e.target.value)}
              className="w-8 h-8 rounded border cursor-pointer"
            />
            <input
              type="text"
              value={val || ''}
              onChange={e => setValue(field.key, e.target.value)}
              placeholder={def || '默认'}
              className={`flex-1 px-2 py-1 text-xs border rounded bg-white dark:bg-gray-700 dark:border-gray-600 ${
                isError ? 'border-red-400 ring-1 ring-red-300' : ''
              }`}
            />
          </div>
        );

      case 'font':
        return (
          <div className="space-y-1">
            <select
              value={val}
              onChange={e => setValue(field.key, e.target.value)}
              className="w-full px-2 py-1 text-xs border rounded bg-white dark:bg-gray-700 dark:border-gray-600"
            >
              <option value="">默认</option>
              {(field.options || []).map((f, i) => (
                <option key={f} value={f} style={{ fontFamily: f }}>
                  {(field.optionLabels || [])[i] || f}
                </option>
              ))}
            </select>
            {/* 字体预览样本 */}
            <div
              style={{ fontFamily: val || def || undefined }}
              className="text-xs text-gray-400 truncate px-1"
            >
              {(field.optionLabels || []).find((_, i) => (field.options || [])[i] === val) || val || '默认'} — The quick brown fox
            </div>
          </div>
        );

      case 'size':
        return (
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={field.min || 10}
              max={field.max || 28}
              step={field.step || 1}
              value={parseFloat(val) || parseFloat(def) || 16}
              onChange={e => setValue(field.key, `${e.target.value}px`)}
              className="flex-1"
            />
            <span className="text-xs w-10 text-right tabular-nums">{val || def || '默认'}</span>
          </div>
        );

      case 'slider':
        return (
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={field.min ?? 0}
              max={field.max ?? 40}
              step={field.step ?? 1}
              value={parseFloat(val) || parseFloat(def) || 0}
              onChange={e => setValue(field.key, `${e.target.value}${field.unit || 'px'}`)}
              className="flex-1"
            />
            <span className="text-xs w-12 text-right tabular-nums">{val || def || '默认'}</span>
          </div>
        );
    }
  };

  // ── 分组 ──

  const groups = [
    { id: 'colors', labelKey: 'cssEditor.colors' },
    { id: 'fonts', labelKey: 'cssEditor.fonts' },
    { id: 'sizes', labelKey: 'cssEditor.sizes' },
    { id: 'spacing', labelKey: 'cssEditor.spacing' },
    { id: 'shadow', labelKey: 'cssEditor.shadow' },
  ];

  return (
    <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800 relative">
      {/* 保存成功提示 */}
      {saveToast && (
        <div className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 bg-green-500 text-white text-xs rounded shadow-lg animate-pulse">
          <Check className="w-3 h-3" />
          {t('cssEditor.saved')}
        </div>
      )}

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

      <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
        {groups.map(group => {
          const groupFields = fields.filter(f => f.group === group.id);
          if (groupFields.length === 0) return null;

          return (
            <div key={group.id}>
              <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
                {t(group.labelKey)}
              </div>
              <div className="space-y-2">
                {groupFields.map(f => {
                  const val = getValue(f.key);
                  const hasValue = val !== undefined && val !== '';
                  return (
                    <label key={f.key} className="flex items-center gap-2">
                      <span className="text-xs text-gray-500 w-20 shrink-0">{t(`cssEditor.${f.key}`, f.label)}</span>
                      <div className="flex-1">{renderField(f)}</div>
                      {/* 单变量重置 */}
                      {hasValue && (
                        <button
                          onClick={() => resetKey(f.key)}
                          className="text-gray-300 hover:text-gray-500 dark:text-gray-600 dark:hover:text-gray-400 shrink-0"
                          title={t('cssEditor.resetKey', { key: f.label })}
                        >
                          <Undo2 className="w-3 h-3" />
                        </button>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* 颜色校验错误 */}
      {hasColorError && (
        <div className="mt-2 text-[10px] text-red-500">
          {t('cssEditor.invalidColor')}
        </div>
      )}

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
          onClick={handleSave}
          disabled={!hasUnsaved || hasColorError}
          className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
            hasUnsaved && !hasColorError
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
