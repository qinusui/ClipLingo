import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileVideo, FileText, Plus } from 'lucide-react';
import { cn } from '../utils/cn';

interface FileUploadProps {
  accept: string;
  onFileSelect?: (file: File) => void;
  onFilesSelect?: (files: File[]) => void;
  selectedFile?: File | null;
  selectedFiles?: File[];
  onClear?: () => void;
  label: string;
  icon?: 'video' | 'text';
  multiple?: boolean;
}

export const FileUpload = ({
  accept,
  onFileSelect,
  onFilesSelect,
  selectedFile,
  selectedFiles,
  onClear,
  label,
  icon = 'text',
  multiple = false,
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
      if (multiple && onFilesSelect) {
        onFilesSelect(files);
      } else {
        onFileSelect?.(files[0]);
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      if (multiple && onFilesSelect) {
        onFilesSelect(Array.from(files));
      } else {
        onFileSelect?.(files[0]);
      }
    }
  };

  const handleClick = () => {
    inputRef.current?.click();
  };

  const Icon = icon === 'video' ? FileVideo : FileText;

  const hasFiles = selectedFile || (selectedFiles && selectedFiles.length > 0);

  const dropZone = (
    <div
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        'border-2 border-dashed rounded-lg text-center cursor-pointer transition-colors',
        multiple && hasFiles
          ? 'p-3 border-gray-200 hover:border-primary-400 dark:border-gray-600 dark:hover:border-primary-500'
          : 'p-6 border-gray-300 hover:border-gray-400 dark:border-gray-600 dark:hover:border-gray-500',
        isDragging && 'border-primary-500 bg-primary-50 dark:bg-primary-900/30'
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleFileChange}
        className="hidden"
      />
      {multiple && hasFiles ? (
        <div className="flex items-center justify-center gap-1 text-gray-500 dark:text-gray-400">
          <Plus className="w-4 h-4" />
          <span className="text-sm">{t('fileUpload.addMore') || '继续添加'}</span>
        </div>
      ) : (
        <>
          <Upload className="w-8 h-8 text-gray-400 mx-auto mb-2 dark:text-gray-500" />
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {t('fileUpload.dropPrompt')}
          </p>
          <p className="text-xs text-gray-400 mt-1 dark:text-gray-500">
            {accept.replace(/,/g, ', ').toUpperCase()}
          </p>
        </>
      )}
    </div>
  );

  return (
    <div className="w-full">
      <p className="text-sm font-medium text-gray-700 mb-2 dark:text-gray-300">{label}</p>

      {hasFiles ? (
        <div className="space-y-2">
          {(selectedFiles && selectedFiles.length > 0 ? selectedFiles : selectedFile ? [selectedFile] : []).map((file, i) => (
            <div key={i} className="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-lg dark:bg-gray-700 dark:border-gray-600">
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <Icon className="w-5 h-5 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                <span className="text-sm text-gray-700 truncate dark:text-gray-200">{file.name}</span>
              </div>
            </div>
          ))}
          {multiple && dropZone}
          {onClear && (
            <button
              onClick={onClear}
              className="text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400"
            >
              {t('fileUpload.clearSelection') || '清除选择'}
            </button>
          )}
        </div>
      ) : (
        dropZone
      )}
    </div>
  );
};
