import { useTranslation } from 'react-i18next';
import { SubtitleItem, AIRecommendation } from '../types';
import { cn } from '../utils/cn';
import { Check } from 'lucide-react';

interface SubtitleTableProps {
  subtitles: SubtitleItem[];
  selectedIndices: Set<number>;
  onToggleSelection: (index: number) => void;
  onSelectAll: () => void;
  isAllSelected: boolean;
  recommendations: Map<number, AIRecommendation> | null;
  isRecommending: boolean;
  recommendBatch: number;
  recommendTotalBatches: number;
  learnedWords?: Map<string, string>;
}

export const SubtitleTable = ({
  subtitles,
  selectedIndices,
  onToggleSelection,
  onSelectAll,
  isAllSelected,
  recommendations,
  isRecommending,
  recommendBatch,
  recommendTotalBatches,
  learnedWords,
}: SubtitleTableProps) => {
  const { t } = useTranslation();
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const recommendedCount = recommendations
    ? Array.from(recommendations.values()).filter(r => r.include).length
    : 0;

  return (
    <div className="w-full border border-gray-200 rounded-lg overflow-hidden dark:border-gray-700">
      {/* 表头 */}
      <div className="bg-gray-50 grid grid-cols-12 gap-2 px-4 py-3 border-b border-gray-200 dark:bg-gray-750 dark:border-gray-700">
        <div
          className="col-span-1 flex items-center justify-center cursor-pointer select-none"
          onClick={onSelectAll}
          title={isAllSelected ? t('subtitleTable.deselectAll') : t('subtitleTable.selectAll')}
        >
          <div className={cn(
            'w-5 h-5 rounded border-2 flex items-center justify-center transition-colors',
            isAllSelected
              ? 'bg-primary-500 border-primary-500'
              : 'border-gray-300 hover:border-primary-400 dark:border-gray-600'
          )}>
            {isAllSelected && <Check className="w-3 h-3 text-white" strokeWidth={3} />}
          </div>
        </div>
        <div className="col-span-1 text-xs font-medium text-gray-500 dark:text-gray-400">{t('subtitleTable.columnIndex')}</div>
        <div className="col-span-5 text-xs font-medium text-gray-500 dark:text-gray-400">{t('subtitleTable.columnOriginal')}</div>
        <div className="col-span-2 text-xs font-medium text-gray-500 dark:text-gray-400">{t('subtitleTable.columnTime')}</div>
        <div className="col-span-1 text-xs font-medium text-gray-500 dark:text-gray-400">{t('subtitleTable.columnDuration')}</div>
        <div className="col-span-2 text-xs font-medium text-gray-500 dark:text-gray-400">
          {t('subtitleTable.columnAiFilter')}
          {recommendations && (
            <span className="ml-1 text-green-600 dark:text-green-400">({recommendedCount})</span>
          )}
        </div>
      </div>

      {/* 表格内容 */}
      <div className="max-h-96 overflow-y-auto">
        {isRecommending && subtitles.length > 0 && (
          <div className="px-4 py-2 bg-blue-50 text-blue-700 text-sm flex items-center gap-2 dark:bg-blue-900/30 dark:text-blue-400">
            <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            {recommendTotalBatches > 0
              ? t('subtitleTable.analyzingBatch', { batch: recommendBatch, total: recommendTotalBatches })
              : t('subtitleTable.analyzing')}
          </div>
        )}
        {subtitles.map((subtitle) => {
          const rec = recommendations?.get(subtitle.index);
          return (
            <div
              key={subtitle.index}
              onClick={() => onToggleSelection(subtitle.index)}
              className={cn(
                'grid grid-cols-12 gap-2 px-4 py-3 border-b border-gray-100 transition-colors cursor-pointer dark:border-gray-700',
                selectedIndices.has(subtitle.index)
                  ? 'bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/30 dark:hover:bg-blue-900/40'
                  : 'hover:bg-gray-50 dark:hover:bg-gray-700',
                rec?.include && !selectedIndices.has(subtitle.index) && 'bg-green-50 hover:bg-green-100 dark:bg-green-900/30 dark:hover:bg-green-900/40'
              )}
            >
              <div
                className="col-span-1 flex items-center justify-center cursor-pointer"
                onClick={(e) => { e.stopPropagation(); onToggleSelection(subtitle.index); }}
              >
                <div className={cn(
                  'w-5 h-5 rounded border-2 flex items-center justify-center transition-colors',
                  selectedIndices.has(subtitle.index)
                    ? 'bg-primary-500 border-primary-500'
                    : 'border-gray-300 hover:border-primary-400 dark:border-gray-600'
                )}>
                  {selectedIndices.has(subtitle.index) && (
                    <Check className="w-3 h-3 text-white" strokeWidth={3} />
                  )}
                </div>
              </div>
              <div className="col-span-1 text-sm text-gray-500 flex items-center dark:text-gray-400">
                {subtitle.index}
              </div>
              <div className="col-span-5 text-sm text-gray-900 flex items-center dark:text-gray-100">
                {subtitle.text}
              </div>
              <div className="col-span-2 text-sm text-gray-500 flex items-center dark:text-gray-400">
                {formatTime(subtitle.start_sec)} - {formatTime(subtitle.end_sec)}
              </div>
              <div className="col-span-1 text-sm text-gray-500 flex items-center dark:text-gray-400">
                {subtitle.duration.toFixed(1)}s
              </div>
              <div className="col-span-2 flex items-center">
                {rec ? (
                  (() => {
                    const word = rec.word?.trim().toLowerCase();
                    const isLearned = rec.include && word && learnedWords?.has(word);
                    return (
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full',
                          rec.reason?.startsWith(t('app.error.processingFailed'))
                            ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400'
                            : isLearned
                              ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400'
                              : rec.include
                                ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'
                                : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                        )}
                        title={isLearned ? t('subtitleTable.learnedTooltip', { word: rec.word }) : rec.reason}
                      >
                        {rec.reason?.startsWith(t('app.error.processingFailed')) ? t('subtitleTable.statusFailed') : isLearned ? t('subtitleTable.statusLearned') : rec.include ? t('subtitleTable.statusRecommended') : t('subtitleTable.statusSkip')}
                      </span>
                    );
                  })()
                ) : (
                  <span className="text-xs text-gray-400">-</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {subtitles.length === 0 && (
        <div className="p-8 text-center text-gray-500 dark:text-gray-400">
          {t('subtitleTable.noSubtitles')}
        </div>
      )}
    </div>
  );
};
