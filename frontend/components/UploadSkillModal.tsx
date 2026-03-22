import React, { useState, useCallback } from 'react';
import { Modal } from 'antd';
import { api } from '../services/api';

interface UploadSkillModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const ALLOWED_EXT = ['.zip', '.md', '.skill'];
const MAX_SIZE = 10 * 1024 * 1024; // 10 MB

const UploadSkillModal: React.FC<UploadSkillModalProps> = ({ visible, onClose, onSuccess }) => {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateFile = (file: File): string | null => {
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) {
      return `不支持的文件格式，仅支持: ${ALLOWED_EXT.join(', ')}`;
    }
    if (file.size > MAX_SIZE) {
      return '文件大小超过 10 MB 限制';
    }
    return null;
  };

  const handleUpload = useCallback(async (file: File) => {
    const err = validateFile(file);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    setUploading(true);
    try {
      await api.uploadSkill(file);
      onSuccess();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败');
    } finally {
      setUploading(false);
    }
  }, [onSuccess, onClose]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(true);
  };

  const handleDragLeave = () => setDragActive(false);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    e.target.value = '';
  };

  const handleClose = () => {
    setError(null);
    setDragActive(false);
    onClose();
  };

  return (
    <Modal
      open={visible}
      onCancel={handleClose}
      title="Upload skill"
      footer={null}
      width={480}
      centered
      destroyOnClose
    >
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
          dragActive ? 'border-gray-400 bg-gray-50' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50/50'
        } ${uploading ? 'pointer-events-none opacity-70' : ''}`}
        onClick={() => document.getElementById('upload-skill-input')?.click()}
      >
        <input
          id="upload-skill-input"
          type="file"
          accept={ALLOWED_EXT.join(',')}
          className="hidden"
          onChange={handleFileInput}
          disabled={uploading}
        />
        <div className="flex justify-center gap-2 mb-4">
          <div className="w-12 h-14 bg-white rounded border border-gray-200 shadow-sm flex items-center justify-center text-xs text-gray-500 font-bold">
            ZIP
          </div>
          <div className="w-12 h-14 bg-white rounded border border-gray-200 shadow-sm flex items-center justify-center text-lg -ml-4">
            📄
          </div>
        </div>
        <p className="text-gray-800 font-medium mb-2">
          {uploading ? '上传中...' : 'Drag and drop or click to upload'}
        </p>
        <p className="text-sm text-gray-500">
          Supported formats: .zip, .md, .skill; max file size: 10 MB
        </p>
        {error && (
          <p className="mt-3 text-sm text-red-600">{error}</p>
        )}
      </div>
    </Modal>
  );
};

export default UploadSkillModal;
