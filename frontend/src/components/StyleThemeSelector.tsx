import { useTranslation } from 'react-i18next';
import { CardStyle, CardTheme } from '../types';
import type { ThemeListItem } from '../services/themeAPI';

interface StyleThemeSelectorProps {
  cardStyles: Set<CardStyle>;
  setCardStyles: React.Dispatch<React.SetStateAction<Set<CardStyle>>>;
  cardTheme: CardTheme;
  setCardTheme: (theme: CardTheme) => void;
  showEditor: boolean;
  onToggleEditor: () => void;
  customThemes?: ThemeListItem[];
  onImportClick?: () => void;
  onBrowseClick?: () => void;
  onDeleteTheme?: (name: string) => void;
}

const CARD_STYLES: { key: CardStyle }[] = [
  { key: 'sentence' },
  { key: 'vocab' },
];

const BUILTIN_THEMES: { key: CardTheme }[] = [
  { key: 'default' },
  { key: 'minimal' },
  { key: 'netflix' },
  { key: 'dictionary' },
];

export const StyleThemeSelector = ({
  cardStyles,
  setCardStyles,
  cardTheme,
  setCardTheme,
  showEditor,
  onToggleEditor,
  customThemes = [],
  onImportClick,
  onBrowseClick,
  onDeleteTheme,
}: StyleThemeSelectorProps) => {
  const { t } = useTranslation();
  const isCustom = customThemes.some(t => t.name === cardTheme);

  return (
    <div className="space-y-3">
      <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
        <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">
          {t('app.step3.cardStructure')}
        </label>
        <div className="flex gap-2">
          {CARD_STYLES.map(({ key }) => (
            <label
              key={key}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border cursor-pointer transition-colors ${
                cardStyles.has(key)
                  ? 'bg-primary-500 text-white border-primary-500'
                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
              }`}
              title={t(`app.cardStyle.${key}.desc`)}
            >
              <input
                type="checkbox"
                checked={cardStyles.has(key)}
                onChange={() => {
                  setCardStyles(prev => {
                    const next = new Set(prev);
                    if (next.has(key)) {
                      if (next.size > 1) next.delete(key);
                    } else {
                      next.add(key);
                    }
                    return next;
                  });
                }}
                className="sr-only"
              />
              {t(`app.cardStyle.${key}.label`)}
            </label>
          ))}
        </div>
      </div>
      <div className="p-3 bg-gray-50 rounded-lg dark:bg-gray-800">
        <label className="block text-xs font-medium text-gray-600 mb-1.5 dark:text-gray-400">
          {t('app.step3.visualTheme')}
        </label>

        {/* 内置主题 */}
        <div className="grid grid-cols-4 gap-1.5">
          {BUILTIN_THEMES.map(({ key }) => (
            <button
              key={key}
              onClick={() => setCardTheme(key)}
              title={t(`app.theme.${key}.desc`)}
              className={`px-2 py-1.5 rounded text-xs font-medium border transition-colors ${
                cardTheme === key
                  ? 'bg-primary-500 text-white border-primary-500'
                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
              }`}
            >
              {t(`app.theme.${key}.label`)}
            </button>
          ))}
        </div>

        {/* 自定义主题 */}
        {customThemes.length > 0 && (
          <div className="mt-2">
            <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
              {t('themeImporter.customThemes')}
            </div>
            <div className="grid grid-cols-4 gap-1.5">
              {customThemes.map(tm => (
                <div key={tm.name} className="relative group">
                  <button
                    onClick={() => setCardTheme(tm.name)}
                    title={tm.author ? `${tm.label} by ${tm.author}` : tm.label}
                    className={`w-full px-2 py-1.5 rounded text-xs font-medium border transition-colors truncate ${
                      cardTheme === tm.name
                        ? 'bg-primary-500 text-white border-primary-500'
                        : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                    }`}
                  >
                    {tm.label}
                  </button>
                  {onDeleteTheme && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(t('themeImporter.confirmDelete', { name: tm.label }))) {
                          onDeleteTheme(tm.name);
                        }
                      }}
                      className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      &times;
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 导入按钮 */}
        {onImportClick && (
          <button
            onClick={onImportClick}
            className="mt-2 w-full px-2 py-1.5 rounded text-xs font-medium border border-dashed border-gray-300 text-gray-400 hover:text-gray-600 hover:border-gray-400 dark:border-gray-600 dark:text-gray-500 dark:hover:text-gray-300 dark:hover:border-gray-500 transition-colors"
          >
            + {t('themeImporter.importTheme')}
          </button>
        )}
        {/* 浏览社区模板 */}
        {onBrowseClick && (
          <button
            onClick={onBrowseClick}
            className="mt-1 w-full px-2 py-1.5 rounded text-xs font-medium border border-dashed border-primary-300 text-primary-500 hover:text-primary-700 hover:border-primary-400 dark:border-primary-700 dark:text-primary-400 dark:hover:text-primary-300 dark:hover:border-primary-500 transition-colors"
          >
            {t('marketplace.browse')}
          </button>
        )}
      </div>
      {/* 编辑样式按钮 — 仅内置主题可用 */}
      {!isCustom && (
        <button
          onClick={onToggleEditor}
          className={`mt-2 w-full px-2 py-1.5 rounded text-xs font-medium border transition-colors ${
            showEditor
              ? 'bg-primary-500 text-white border-primary-500'
              : 'bg-white text-gray-500 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-400 dark:border-gray-600 dark:hover:bg-gray-600'
          }`}
        >
          {t('cssEditor.editCss')}
        </button>
      )}
    </div>
  );
};
