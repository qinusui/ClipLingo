import { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, X, AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import JSZip from 'jszip';

interface ThemeImporterProps {
  onImport: (zipFile: File) => Promise<void>;
  onClose: () => void;
}

type ValidateState = 'idle' | 'validating' | 'valid' | 'invalid';

const REQUIRED_FILES = ['theme.json', 'front.html', 'back.html', 'style.css'];

export const ThemeImporter = ({ onImport, onClose }: ThemeImporterProps) => {
  const { t } = useTranslation();
  const [dragOver, setDragOver] = useState(false);
  const [validateState, setValidateState] = useState<ValidateState>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [importing, setImporting] = useState(false);
  const [successName, setSuccessName] = useState('');
  const fileRef = useRef<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateZip = useCallback(async (file: File) => {
    setValidateState('validating');
    setErrorMsg('');

    if (!file.name.toLowerCase().endsWith('.zip')) {
      setValidateState('invalid');
      setErrorMsg(t('themeImporter.invalidFormat'));
      return;
    }

    try {
      const buffer = await file.arrayBuffer();
      const zip = await JSZip.loadAsync(buffer);
      const names = new Set(Object.keys(zip.files).map(n => n.split('/').pop() || ''));

      const missing = REQUIRED_FILES.filter(f => !names.has(f));
      if (missing.length > 0) {
        setValidateState('invalid');
        setErrorMsg(t('themeImporter.missingFiles', { files: missing.join(', ') }));
        return;
      }

      // 读取并验证 theme.json
      const metaFile = zip.file('theme.json');
      if (!metaFile) {
        setValidateState('invalid');
        setErrorMsg(t('themeImporter.noThemeJson'));
        return;
      }

      const metaText = await metaFile.async('string');
      const meta = JSON.parse(metaText);
      if (!meta.name || !/^[a-zA-Z0-9_-]+$/.test(meta.name)) {
        setValidateState('invalid');
        setErrorMsg(t('themeImporter.invalidName'));
        return;
      }

      setValidateState('valid');
      fileRef.current = file;
    } catch (err) {
      setValidateState('invalid');
      if (err instanceof SyntaxError) {
        setErrorMsg(t('themeImporter.invalidJson'));
      } else {
        setErrorMsg(err instanceof Error ? err.message : t('themeImporter.invalidZip'));
      }
    }
  }, [t]);

  const handleFile = useCallback((file: File) => {
    fileRef.current = file;
    validateZip(file);
  }, [validateZip]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleImport = async () => {
    if (!fileRef.current || validateState !== 'valid') return;
    setImporting(true);
    try {
      await onImport(fileRef.current);
      setSuccessName(fileRef.current.name);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t('themeImporter.importFailed'));
      setValidateState('invalid');
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">
            {t('themeImporter.title')}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* Success */}
          {successName && (
            <div className="flex items-center gap-2 p-3 bg-green-50 dark:bg-green-900/20 rounded-lg text-sm text-green-700 dark:text-green-400">
              <CheckCircle className="w-4 h-4 shrink-0" />
              {t('themeImporter.success', { name: successName })}
            </div>
          )}

          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => inputRef.current?.click()}
            className={`relative border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              dragOver
                ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                : validateState === 'valid'
                  ? 'border-green-400 bg-green-50 dark:bg-green-900/10'
                  : validateState === 'invalid'
                    ? 'border-red-300 bg-red-50 dark:bg-red-900/10'
                    : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".zip"
              onChange={handleInputChange}
              className="hidden"
            />

            {validateState === 'validating' ? (
              <div className="space-y-2">
                <Loader2 className="w-8 h-8 mx-auto animate-spin text-primary-500" />
                <p className="text-sm text-gray-500">{t('themeImporter.validating')}</p>
              </div>
            ) : validateState === 'valid' ? (
              <div className="space-y-2">
                <CheckCircle className="w-8 h-8 mx-auto text-green-500" />
                <p className="text-sm text-green-600 dark:text-green-400">
                  {fileRef.current?.name}
                </p>
                <p className="text-xs text-gray-400">{t('themeImporter.ready')}</p>
              </div>
            ) : (
              <div className="space-y-2">
                <Upload className="w-8 h-8 mx-auto text-gray-400" />
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {t('themeImporter.dropHint')}
                </p>
                <p className="text-xs text-gray-400">{t('themeImporter.supportedFormat')}</p>
              </div>
            )}
          </div>

          {/* Error message */}
          {errorMsg && validateState === 'invalid' && (
            <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/10 rounded-lg text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Required files hint */}
          <div className="text-xs text-gray-400 dark:text-gray-500 space-y-1">
            <p className="font-medium">{t('themeImporter.requiredFiles')}:</p>
            <ul className="list-disc list-inside space-y-0.5">
              <li><code>theme.json</code> — {t('themeImporter.themeJsonDesc')}</li>
              <li><code>front.html</code> — {t('themeImporter.frontHtmlDesc')}</li>
              <li><code>back.html</code> — {t('themeImporter.backHtmlDesc')}</li>
              <li><code>style.css</code> — {t('themeImporter.styleCssDesc')}</li>
            </ul>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-5 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            {successName ? t('themeImporter.close') : t('themeImporter.cancel')}
          </button>
          {!successName && (
            <button
              onClick={handleImport}
              disabled={validateState !== 'valid' || importing}
              className={`px-4 py-2 text-sm rounded-lg font-medium flex items-center gap-2 ${
                validateState === 'valid' && !importing
                  ? 'bg-primary-500 text-white hover:bg-primary-600'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed dark:bg-gray-700 dark:text-gray-500'
              }`}
            >
              {importing && <Loader2 className="w-4 h-4 animate-spin" />}
              {t('themeImporter.import')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
