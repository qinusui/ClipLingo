import { useTranslation } from 'react-i18next';
import { cn } from '../utils/cn';

interface ProgressBarProps {
  progress: number;
  className?: string;
  showLabel?: boolean;
  label?: string;
}

export const ProgressBar = ({ progress, className, showLabel = true, label }: ProgressBarProps) => {
  const { t } = useTranslation();
  const percentage = Math.min(100, Math.max(0, progress));

  return (
    <div className={cn('w-full', className)}>
      {showLabel && (
        <div className="flex justify-between text-sm text-gray-600 mb-1 dark:text-gray-400">
          <span>{label || t('progressBar.defaultLabel')}</span>
          <span>{percentage.toFixed(0)}%</span>
        </div>
      )}
      <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden dark:bg-gray-700">
        <div
          className="bg-primary-600 h-2 rounded-full transition-all duration-300 ease-out"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};
