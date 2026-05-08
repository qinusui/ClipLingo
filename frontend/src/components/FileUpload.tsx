import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, X, FileVideo, FileText } from 'lucide-react';
import { cn } from '../utils/cn';

interface FileUploadProps {
  accept: string;
  onFileSelect: (file: File) => void;
  selectedFile?: File | null;
  onClear?: () => void;
  label: string;
  icon?: 'video' | 'text';
}

export const FileUpload = ({
  accept,
  onFileSelect,
  selectedFile,
  onClear,
  label,
  icon = 'text',
}: FileUploadProps) => {
  const { t } = useTranslation();
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      onFileSelect(files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      onFileSelect(files[0]);
    }
  };

  const handleClick = () => {
    inputRef.current?.click();
  };

  const Icon = icon === 'video' ? FileVideo : FileText;

  return (
    <div className="w-full">
      <p className="text-sm font-medium text-gray-700 mb-2 dark:text-gray-300">{label}</p>

      {selectedFile ? (
        <div className="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg dark:bg-gray-700 dark:border-gray-600">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <Icon className="w-5 h-5 text-gray-500 dark:text-gray-400 flex-shrink-0" />
            <span className="text-sm text-gray-700 truncate dark:text-gray-200">{selectedFile.name}</span>
          </div>
          {onClear && (
            <button
              onClick={onClear}
              className="ml-2 p-1 hover:bg-gray-200 rounded-md transition-colors dark:hover:bg-gray-600"
            >
              <X className="w-4 h-4 text-gray-500 dark:text-gray-400" />
            </button>
          )}
        </div>
      ) : (
        <div
          onClick={handleClick}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            'border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors',
            isDragging
              ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30'
              : 'border-gray-300 hover:border-gray-400 dark:border-gray-600 dark:hover:border-gray-500'
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            onChange={handleFileChange}
            className="hidden"
          />
          <Upload className="w-8 h-8 text-gray-400 mx-auto mb-2 dark:text-gray-500" />
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {t('fileUpload.dropPrompt')}
          </p>
          <p className="text-xs text-gray-400 mt-1 dark:text-gray-500">
            {accept.replace(/,/g, ', ').toUpperCase()}
          </p>
        </div>
      )}
    </div>
  );
};
