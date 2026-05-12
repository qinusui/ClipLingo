import { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, Square, RefreshCw, CheckCircle, XCircle, Loader2, ExternalLink } from 'lucide-react';
import { Button } from './Button';
import { pingAnki } from '../services/ankiConnect';
import { syncToAnki, type SyncProgress, type SyncResult } from '../services/syncToAnki';
import type { ProcessedCard, ThemeOverrides } from '../types';

type SyncState = 'idle' | 'checking' | 'offline' | 'syncing' | 'done' | 'error';

interface Props {
  cards: ProcessedCard[];
  deckName: string;
  apiBase: string;
  cardStyles?: string[];
  theme?: string;
  themeOverrides?: ThemeOverrides;
}

export const AnkiSyncButton = ({ cards, deckName, apiBase, cardStyles, theme, themeOverrides }: Props) => {
  const { t } = useTranslation();
  const [state, setState] = useState<SyncState>('idle');
  const [progress, setProgress] = useState<SyncProgress | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const handleSync = useCallback(async () => {
    // 先检测 Anki 是否在线
    setState('checking');
    const online = await pingAnki();
    if (!online) {
      setState('offline');
      return;
    }

    // 开始同步
    setState('syncing');
    setProgress(null);
    setResult(null);
    setErrorMsg('');
    abortRef.current = new AbortController();

    try {
      const res = await syncToAnki(
        cards,
        deckName,
        apiBase,
        cardStyles,
        theme,
        themeOverrides,
        (p) => setProgress(p),
        abortRef.current.signal,
      );
      setResult(res);
      setState('done');
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setState('idle');
      } else {
        setErrorMsg(err instanceof Error ? err.message : String(err));
        setState('error');
      }
    }
  }, [cards, deckName, apiBase, cardStyles, theme, themeOverrides]);

  const handleCancel = () => {
    abortRef.current?.abort();
  };

  const handleRetry = () => {
    setState('idle');
    setResult(null);
    setErrorMsg('');
  };

  // ── idle: 显示同步按钮 ──
  if (state === 'idle') {
    return (
      <Button variant="outline" size="sm" onClick={handleSync} disabled={cards.length === 0}>
        <Upload className="w-4 h-4 mr-2" />
        {t('ankiSync.syncButton')}
      </Button>
    );
  }

  // ── checking: 检测 Anki ──
  if (state === 'checking') {
    return (
      <Button variant="outline" size="sm" disabled>
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        {t('ankiSync.checking')}
      </Button>
    );
  }

  // ── offline: Anki 未启动 ──
  if (state === 'offline') {
    return (
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled>
          <XCircle className="w-4 h-4 mr-2 text-red-500" />
          {t('ankiSync.notFound')}
        </Button>
        <a
          href="https://apps.ankiweb.net/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:underline dark:text-blue-400"
        >
          {t('ankiSync.downloadAnki')} <ExternalLink className="w-3 h-3 inline" />
        </a>
        <a
          href="https://ankiweb.net/shared/info/2055492159"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:underline dark:text-blue-400"
        >
          {t('ankiSync.installAnkiConnect')} <ExternalLink className="w-3 h-3 inline" />
        </a>
        <button
          onClick={handleRetry}
          className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        >
          {t('ankiSync.retry')}
        </button>
      </div>
    );
  }

  // ── syncing: 同步中 ──
  if (state === 'syncing' && progress) {
    const pct = Math.round((progress.current / progress.total) * 100);
    return (
      <div className="space-y-2 w-full max-w-md">
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-700 dark:text-gray-300">
            {t('ankiSync.syncing', { current: progress.current, total: progress.total })}
            <span className="ml-2 text-gray-400">
              +{progress.added}{t('ankiSync.addedShort')} {progress.skipped}{t('ankiSync.skippedShort')} {progress.failed}{t('ankiSync.failedShort')}
            </span>
          </span>
          <button
            onClick={handleCancel}
            className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700"
          >
            <Square className="w-3 h-3" /> {t('ankiSync.stop')}
          </button>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-600">
          <div
            className="bg-green-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
          {progress.currentSentence}
        </p>
      </div>
    );
  }

  // ── done: 完成 ──
  if (state === 'done' && result) {
    return (
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-sm text-green-700 dark:text-green-400">
          <CheckCircle className="w-4 h-4" />
          <span>
            {t('ankiSync.doneAdded', { added: result.added })}
            {result.skipped > 0 && t('ankiSync.doneSkipped', { skipped: result.skipped })}
            {result.failed > 0 && t('ankiSync.doneFailed', { failed: result.failed })}
          </span>
        </div>
        <button
          onClick={handleRetry}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <RefreshCw className="w-3 h-3" /> {t('ankiSync.syncAgain')}
        </button>
      </div>
    );
  }

  // ── error: 出错 ──
  if (state === 'error') {
    return (
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-sm text-red-600 dark:text-red-400">
          <XCircle className="w-4 h-4" />
          <span>{t('ankiSync.syncFailed')}{errorMsg}</span>
        </div>
        <button
          onClick={handleRetry}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <RefreshCw className="w-3 h-3" /> {t('ankiSync.retry')}
        </button>
      </div>
    );
  }

  return null;
};
