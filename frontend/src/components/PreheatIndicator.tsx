import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

interface PreheatIndicatorProps {
  taskId: string | null;
}

export function PreheatIndicator({ taskId }: PreheatIndicatorProps) {
  const { t } = useTranslation();
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!taskId) {
      setDone(0);
      setTotal(0);
      return;
    }

    const poll = async () => {
      try {
        const resp = await fetch(`/api/annotate/preheat/${taskId}/status`);
        if (!resp.ok) return;
        const data = await resp.json();
        setDone(data.done);
        setTotal(data.total);
        if (data.done + (data.failed || 0) >= data.total && data.total > 0) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
        }
      } catch {
        // 轮询失败不影响主流程
      }
    };

    poll();
    timerRef.current = setInterval(poll, 2000);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [taskId]);

  if (total === 0 || done + (done === total ? 0 : 0) >= total) {
    // 预热完成后短暂显示提示，然后自动隐藏
    if (done > 0 && done >= total) {
      return (
        <div className="text-xs text-green-600 dark:text-green-400 mt-1">
          {t('app.step2.preheatDone')}
        </div>
      );
    }
    return null;
  }

  return (
    <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
      {t('app.step2.preheating', { done, total })}
    </div>
  );
}
