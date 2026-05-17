import { CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../utils/cn';

interface Step {
  id: string;
  label?: string;
  status: 'pending' | 'processing' | 'completed' | 'error';
  error?: string;
}

interface ProcessingStatusProps {
  steps: Step[];
  currentStepIndex: number;
  message?: string;
}

const STEP_I18N_MAP: Record<string, string> = {
  parse: 'app.processing.parseSubtitles',
  media: 'app.processing.cutAudioScreenshots',
  pack: 'app.processing.packAnkiDeck',
};

export const ProcessingStatus = ({ steps, currentStepIndex, message }: ProcessingStatusProps) => {
  const { t } = useTranslation();

  return (
    <div className="space-y-3">
      {message && (
        <div className="text-sm text-gray-600 dark:text-gray-400 px-1">
          {message}
        </div>
      )}
      {steps.map((step, index) => {
        const isActive = index === currentStepIndex;
        const isCompleted = index < currentStepIndex;
        // 优先使用 step.label（兼容旧代码），否则根据 step.id 实时翻译
        const displayLabel = step.label || t(STEP_I18N_MAP[step.id] || step.id);

        return (
          <div
            key={step.id}
            className={cn(
              'flex items-start gap-3 p-3 rounded-lg transition-colors',
              isActive && 'bg-blue-50 border border-blue-200 dark:bg-blue-900/30 dark:border-blue-800',
              isCompleted && 'bg-green-50 dark:bg-green-900/20',
              step.status === 'error' && 'bg-red-50 dark:bg-red-900/20'
            )}
          >
            <div className="flex-shrink-0 mt-0.5">
              {step.status === 'completed' && (
                <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
              )}
              {step.status === 'error' && (
                <XCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
              )}
              {step.status === 'processing' && (
                <Loader2 className="w-5 h-5 text-blue-600 animate-spin dark:text-blue-400" />
              )}
              {step.status === 'pending' && (
                <div className="w-5 h-5 rounded-full border-2 border-gray-300 dark:border-gray-600" />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p
                className={cn(
                  'text-sm font-medium',
                  isActive ? 'text-blue-700 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300'
                )}
              >
                {displayLabel}
              </p>
              {step.error && (
                <p className="text-xs text-red-600 mt-1 dark:text-red-400">{step.error}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
