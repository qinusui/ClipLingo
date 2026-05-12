import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Search, Download, CheckCircle, Loader2, ExternalLink, AlertCircle } from 'lucide-react';
import { marketplaceAPI, MarketplaceEntry } from '../services/marketplaceAPI';
import { themeAPI, ThemeListItem } from '../services/themeAPI';

interface TemplateMarketplaceProps {
  onClose: () => void;
  onInstalled: () => void;
}

export const TemplateMarketplace = ({ onClose, onInstalled }: TemplateMarketplaceProps) => {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<MarketplaceEntry[]>([]);
  const [installed, setInstalled] = useState<ThemeListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [installing, setInstalling] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [list, themes] = await Promise.all([
        marketplaceAPI.fetchList(),
        themeAPI.listThemes(),
      ]);
      setEntries(list);
      setInstalled(themes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load templates');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleInstall = async (entry: MarketplaceEntry) => {
    setInstalling(entry.name);
    try {
      await marketplaceAPI.install(entry);
      const themes = await themeAPI.listThemes();
      setInstalled(themes);
      onInstalled();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Install failed');
    } finally {
      setInstalling(null);
    }
  };

  const filtered = entries.filter(e => {
    const q = search.toLowerCase();
    return (
      e.label.toLowerCase().includes(q) ||
      e.name.toLowerCase().includes(q) ||
      (e.author || '').toLowerCase().includes(q) ||
      (e.description || '').toLowerCase().includes(q)
    );
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">
            {t('marketplace.title')}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-700 shrink-0">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t('marketplace.searchPlaceholder')}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
            </div>
          ) : error ? (
            <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/10 rounded-lg text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-16 text-gray-400 dark:text-gray-500 text-sm">
              {search ? t('marketplace.noResults') : t('marketplace.empty')}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {filtered.map(entry => {
                const isInstalled = marketplaceAPI.isInstalled(entry, installed);
                const isCurrent = installing === entry.name;
                const preview = marketplaceAPI.previewUrl(entry);

                return (
                  <div
                    key={entry.name}
                    className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden bg-white dark:bg-gray-750 hover:shadow-md transition-shadow"
                  >
                    {/* Preview image */}
                    <div className="aspect-[3/2] bg-gray-100 dark:bg-gray-700 overflow-hidden">
                      {preview ? (
                        <img
                          src={preview}
                          alt={entry.label}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-gray-300 dark:text-gray-600">
                          <ExternalLink className="w-8 h-8" />
                        </div>
                      )}
                    </div>

                    {/* Info */}
                    <div className="p-3 space-y-1.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
                            {entry.label}
                          </h3>
                          {entry.author && (
                            <p className="text-xs text-gray-400">{t('marketplace.byAuthor', { author: entry.author })}</p>
                          )}
                        </div>
                      </div>
                      {entry.description && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                          {entry.description}
                        </p>
                      )}

                      {/* Install button */}
                      <div className="pt-1">
                        {isInstalled ? (
                          <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400 font-medium">
                            <CheckCircle className="w-3.5 h-3.5" />
                            {t('marketplace.installed')}
                          </span>
                        ) : (
                          <button
                            onClick={() => handleInstall(entry)}
                            disabled={!!installing}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-60 transition-colors"
                          >
                            {isCurrent ? (
                              <>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                {t('marketplace.installing')}
                              </>
                            ) : (
                              <>
                                <Download className="w-3.5 h-3.5" />
                                {t('marketplace.install')}
                              </>
                            )}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 shrink-0">
          <a
            href="https://github.com/qinusui/cliplingo-templates"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-primary-600 dark:text-gray-400 dark:hover:text-primary-400 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            {t('marketplace.submitLink')}
          </a>
        </div>
      </div>
    </div>
  );
};
