'use client';

import { useState, useEffect } from 'react';
import { Upload, File, Trash2, CheckCircle, Loader2, FileText, BarChart3 } from 'lucide-react';
import api from '@/lib/api';
import { formatFileSize, formatDate, getErrorMessage } from '@/lib/utils';
import { ErrorMessage, Button, Card, ConfirmDialog } from '@/components';
import { useToast } from '@/hooks/useToast';
import { useConfirm } from '@/hooks/useConfirm';
import { truncateFilePath } from '@/lib/path-utils';

interface FileItem {
  file_id: string;
  filename: string;
  dialect: string;
  file_size: number;
  created_at: string;
  lineages?: any[];
}

interface FilesManagementViewProps {
  onFilesChanged?: () => void;
  onUploadSuccess?: () => void;
}

export default function FilesManagementView({ onFilesChanged, onUploadSuccess }: FilesManagementViewProps = {}) {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Upload states
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [uploadStage, setUploadStage] = useState<'uploading' | 'analyzing' | 'complete'>('uploading');

  // Toast and confirmation hooks
  const { showToast } = useToast();
  const { confirm, confirmState, closeDialog } = useConfirm();

  useEffect(() => {
    loadFiles();
  }, []);

  const loadFiles = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.listFiles();
      setFiles(response.files || []);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      // Validate file type
      if (!selectedFile.name.endsWith('.xlsx') && !selectedFile.name.endsWith('.xls')) {
        setUploadError('Please select an Excel file (.xlsx or .xls)');
        return;
      }
      // Validate file size (100MB)
      if (selectedFile.size > 100 * 1024 * 1024) {
        setUploadError('File size must be less than 100MB');
        return;
      }
      setUploadFile(selectedFile);
      setUploadError(null);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      setUploadFile(droppedFile);
      setUploadError(null);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  };

  const handleUpload = async () => {
    if (!uploadFile) return;

    const fileName = uploadFile.name;
    setUploading(true);
    setUploadError(null);
    setUploadProgress(0);
    setUploadStage('uploading');

    try {
      await api.uploadFile(
        uploadFile,
        undefined,
        (progress) => {
          setUploadProgress(progress.percentage);
          if (progress.percentage >= 100) {
            setUploadStage('analyzing');
          }
        }
      );
      
      setUploadStage('complete');
      setUploadFile(null);
      setUploadProgress(0);
      
      // Reload files list
      await loadFiles();
      // Notify parent that files changed
      onFilesChanged?.();
      // Show success toast
      showToast(
        `Successfully uploaded and analyzed ${fileName}`,
        'success'
      );
      
      // Navigate to insights tab after successful upload
      setTimeout(() => {
        onUploadSuccess?.();
      }, 500); // Small delay to allow toast to be seen
    } catch (err) {
      const errorMsg = getErrorMessage(err);
      setUploadError(errorMsg);
      setUploadProgress(0);
      showToast(
        `Upload failed: ${errorMsg}`,
        'error',
        7000,
        {
          label: 'Retry',
          onClick: handleUpload
        }
      );
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (fileId: string, filename: string) => {
    const confirmed = await confirm({
      title: 'Delete File',
      message: `Are you sure you want to delete "${filename}"?\n\nThis will remove the file and all associated lineage data. This action cannot be undone.`,
      confirmText: 'Delete',
      cancelText: 'Cancel',
      confirmVariant: 'danger'
    });

    if (!confirmed) {
      return;
    }

    try {
      await api.deleteFile(fileId);
      await loadFiles();
      // Notify parent that files changed
      onFilesChanged?.();
      showToast(
        `Successfully deleted ${filename}`,
        'success'
      );
    } catch (err) {
      const errorMsg = getErrorMessage(err);
      showToast(
        `Failed to delete file: ${errorMsg}`,
        'error',
        7000,
        {
          label: 'Retry',
          onClick: () => handleDelete(fileId, filename)
        }
      );
    }
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        {/* Upload Section Skeleton */}
        <Card>
          <div className="h-6 bg-gray-200 rounded w-48 mb-4" />
          <div className="border-2 border-dashed border-gray-200 rounded-lg p-8">
            <div className="flex flex-col items-center">
              <div className="w-12 h-12 bg-gray-200 rounded mb-3" />
              <div className="h-5 bg-gray-200 rounded w-64 mb-1" />
              <div className="h-4 bg-gray-200 rounded w-48" />
            </div>
          </div>
        </Card>

        {/* Files List Skeleton */}
        <Card>
          <div className="h-6 bg-gray-200 rounded w-48 mb-4" />
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left">
                    <div className="h-3 bg-gray-200 rounded w-20" />
                  </th>
                  <th className="px-6 py-3 text-left">
                    <div className="h-3 bg-gray-200 rounded w-16" />
                  </th>
                  <th className="px-6 py-3 text-left">
                    <div className="h-3 bg-gray-200 rounded w-12" />
                  </th>
                  <th className="px-6 py-3 text-left">
                    <div className="h-3 bg-gray-200 rounded w-16" />
                  </th>
                  <th className="px-6 py-3 text-right">
                    <div className="h-3 bg-gray-200 rounded w-16 ml-auto" />
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {[1, 2, 3, 4, 5].map((i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="flex items-center">
                        <div className="w-5 h-5 bg-gray-200 rounded mr-3" />
                        <div className="h-4 bg-gray-200 rounded w-48" />
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="h-5 w-20 bg-gray-200 rounded-full" />
                    </td>
                    <td className="px-6 py-4">
                      <div className="h-4 bg-gray-200 rounded w-16" />
                    </td>
                    <td className="px-6 py-4">
                      <div className="h-4 bg-gray-200 rounded w-24" />
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="h-4 bg-gray-200 rounded w-16 ml-auto" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Upload Section */}
      <Card>
        <h2 className="text-xl font-bold text-gray-900 mb-4">Select Files</h2>
        
        <div 
          className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-blue-500 transition-colors cursor-pointer"
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        >
          <label className="cursor-pointer block">
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={handleFileChange}
              className="hidden"
              disabled={uploading}
            />
            <Upload className="w-12 h-12 mx-auto text-gray-400 mb-3" />
            <p className="text-lg font-semibold text-gray-700 mb-1">
              Click to upload or drag and drop
            </p>
            <p className="text-sm text-gray-500">
              Excel files (.xlsx, .xls) up to 100MB
            </p>
          </label>
        </div>

        {uploadFile && (
          <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-center justify-between">
            <div className="flex items-center space-x-3 min-w-0">
              <FileText className="w-8 h-8 text-blue-600 flex-shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-gray-900 break-words" title={uploadFile.name}>{truncateFilePath(uploadFile.name)}</p>
                <p className="text-sm text-gray-600">{formatFileSize(uploadFile.size)}</p>
              </div>
            </div>
            <CheckCircle className="w-6 h-6 text-green-600" />
          </div>
        )}

        {uploadError && (
          <div className="mt-4">
            <ErrorMessage message={uploadError} />
          </div>
        )}

        {uploadFile && (
          <>
            <Button
              onClick={handleUpload}
              disabled={uploading}
              fullWidth
              className="mt-4"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                  <span>
                    {uploadStage === 'uploading' && `Uploading... ${uploadProgress}%`}
                    {uploadStage === 'analyzing' && 'Analyzing...'}
                    {uploadStage === 'complete' && 'Complete!'}
                  </span>
                </>
              ) : (
                <>
                  <Upload className="w-5 h-5 mr-2" />
                  <span>Upload & Analyze</span>
                </>
              )}
            </Button>
            
            {uploading && uploadStage === 'uploading' && (
              <div className="mt-3">
                <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
                <p className="text-xs text-gray-600 mt-1 text-center">
                  Uploading file...
                </p>
              </div>
            )}
            
            {uploading && uploadStage === 'analyzing' && (
              <div className="mt-3">
                <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                  <div className="bg-blue-600 h-2 rounded-full animate-pulse w-full" />
                </div>
                <p className="text-xs text-gray-600 mt-1 text-center">
                  Analyzing file and generating lineage...
                </p>
              </div>
            )}
          </>
        )}

      </Card>

      {/* Files List */}
      <Card>
        <h2 className="text-xl font-bold text-gray-900 mb-4">
          Uploaded Files ({files.length})
        </h2>

        {error && (
          <div className="mb-4">
            <ErrorMessage message={error} />
            <Button onClick={loadFiles} className="mt-2" size="sm">
              Retry Loading Files
            </Button>
          </div>
        )}

        {files.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <File className="w-16 h-16 mx-auto mb-4 text-gray-300" />
            <p className="text-lg font-medium">No files uploaded yet</p>
            <p className="text-sm mt-2">Upload your first analyzer file to get started</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Filename
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Dialect
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Size
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Uploaded
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {files.map((file) => (
                  <tr key={file.file_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="flex items-center min-w-0">
                        <FileText className="w-5 h-5 text-gray-400 mr-3 flex-shrink-0" />
                        <span className="text-sm font-medium text-gray-900 break-words" title={file.filename}>
                          {truncateFilePath(file.filename)}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800 uppercase">
                        {file.dialect}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatFileSize(file.file_size)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDate(file.created_at)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => handleDelete(file.file_id, file.filename)}
                        className="text-red-600 hover:text-red-900 inline-flex items-center transition-colors"
                        title="Delete file"
                      >
                        <Trash2 className="w-4 h-4 mr-1" />
                        <span>Delete</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmState.isOpen}
        title={confirmState.title}
        message={confirmState.message}
        confirmText={confirmState.confirmText}
        cancelText={confirmState.cancelText}
        confirmVariant={confirmState.confirmVariant}
        onConfirm={confirmState.onConfirm}
        onCancel={confirmState.onCancel}
      />
    </div>
  );
}

