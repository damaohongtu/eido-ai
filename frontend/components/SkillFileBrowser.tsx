import React, { useState, useEffect, useCallback } from 'react';
import {
  Tree,
  Button,
  Input,
  Modal,
  message,
  Spin,
  Empty,
  Tooltip,
} from 'antd';
import type { TreeDataNode } from 'antd';
import {
  FileOutlined,
  FolderOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  FolderAddOutlined,
  DeleteOutlined,
  EditOutlined,
  SaveOutlined,
  CloseOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { BACKEND_URL } from '../constants';

interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: number;
  children?: FileNode[];
}

export interface SkillFileBrowserProps {
  skillId: string;
  isSystem: boolean;
  visible: boolean;
}

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '';
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function buildTreeData(nodes: FileNode[]): TreeDataNode[] {
  return nodes.map((node) => ({
    title: (
      <span className="flex items-center gap-1">
        {node.type === 'dir' ? (
          <FolderOutlined className="text-amber-500" />
        ) : (
          <FileOutlined className="text-blue-500" />
        )}
        <span className="text-sm text-gray-700">{node.name}</span>
        {node.type === 'file' && node.size !== undefined && (
          <span className="text-xs text-gray-400 ml-1">({formatBytes(node.size)})</span>
        )}
      </span>
    ),
    key: node.path,
    isLeaf: node.type === 'file',
    children: node.children ? buildTreeData(node.children) : undefined,
  }));
}

const SkillFileBrowser: React.FC<SkillFileBrowserProps> = ({
  skillId,
  isSystem,
  visible,
}) => {
  const [treeData, setTreeData] = useState<TreeDataNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedNodeType, setSelectedNodeType] = useState<'file' | 'dir' | null>(null);
  const [fileContent, setFileContent] = useState<string>('');
  const [fileLoading, setFileLoading] = useState(false);
  const [isBinary, setIsBinary] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState('');
  const [saving, setSaving] = useState(false);

  // Modals
  const [newFileModalOpen, setNewFileModalOpen] = useState(false);
  const [newFilePath, setNewFilePath] = useState('');
  const [newFileContent, setNewFileContent] = useState('');

  const [newFolderModalOpen, setNewFolderModalOpen] = useState(false);
  const [newFolderPath, setNewFolderPath] = useState('');

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string>('');

  const fetchTree = useCallback(async () => {
    if (!visible || !skillId) return;
    setLoading(true);
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/v1/skills/${skillId}/files`,
        { credentials: 'include' }
      );
      if (res.status === 401) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `获取文件列表失败: ${res.status}`);
      }
      const data: FileNode[] = await res.json();
      setTreeData(buildTreeData(data));
    } catch (e) {
      const msg = e instanceof Error ? e.message : '获取文件列表失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  }, [skillId, visible]);

  useEffect(() => {
    if (visible) {
      fetchTree();
    }
  }, [visible, fetchTree]);

  const fetchFileContent = async (path: string) => {
    setFileLoading(true);
    setIsBinary(false);
    setFileContent('');
    setIsEditing(false);
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/v1/skills/${skillId}/files/read?path=${encodeURIComponent(path)}`,
        { credentials: 'include' }
      );
      if (res.status === 401) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        // If backend can't decode as text, treat as binary
        if (res.status === 500 || err.detail?.includes('decode') || err.detail?.includes('Unicode')) {
          setIsBinary(true);
          return;
        }
        throw new Error(err.detail || `读取文件失败: ${res.status}`);
      }
      const data = await res.json();
      setFileContent(data.content || '');
    } catch (e) {
      const msg = e instanceof Error ? e.message : '读取文件失败';
      // Heuristic: if it mentions decode/encoding, treat as binary
      if (msg.toLowerCase().includes('decode') || msg.toLowerCase().includes('unicode') || msg.toLowerCase().includes('binary')) {
        setIsBinary(true);
      } else {
        message.error(msg);
      }
    } finally {
      setFileLoading(false);
    }
  };

  const handleSelect = (_: React.Key[], info: { node: TreeDataNode; selected: boolean }) => {
    const path = info.node.key as string;
    const isFile = info.node.isLeaf;
    if (info.selected) {
      setSelectedPath(path);
      setSelectedNodeType(isFile ? 'file' : 'dir');
      if (isFile) {
        fetchFileContent(path);
      } else {
        setFileContent('');
        setIsBinary(false);
        setIsEditing(false);
      }
    } else {
      setSelectedPath(null);
      setSelectedNodeType(null);
      setFileContent('');
      setIsBinary(false);
      setIsEditing(false);
    }
  };

  const handleWriteFile = async (path: string, content: string) => {
    setSaving(true);
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/v1/skills/${skillId}/files/write`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, content }),
        }
      );
      if (res.status === 401) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `保存失败: ${res.status}`);
      }
      message.success('保存成功');
      await fetchTree();
      // If we saved the currently selected file, refresh its content
      if (selectedPath === path) {
        setFileContent(content);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '保存失败';
      message.error(msg);
      throw e;
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/v1/skills/${skillId}/files/delete`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: deleteTarget }),
        }
      );
      if (res.status === 401) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `删除失败: ${res.status}`);
      }
      message.success('删除成功');
      if (selectedPath === deleteTarget) {
        setSelectedPath(null);
        setSelectedNodeType(null);
        setFileContent('');
        setIsBinary(false);
      }
      await fetchTree();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '删除失败';
      message.error(msg);
    } finally {
      setDeleteModalOpen(false);
      setDeleteTarget('');
    }
  };

  const handleMkdir = async () => {
    if (!newFolderPath.trim()) {
      message.warning('请输入目录路径');
      return;
    }
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/v1/skills/${skillId}/files/mkdir`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: newFolderPath.trim() }),
        }
      );
      if (res.status === 401) {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `创建目录失败: ${res.status}`);
      }
      message.success('目录创建成功');
      setNewFolderModalOpen(false);
      setNewFolderPath('');
      await fetchTree();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '创建目录失败';
      message.error(msg);
    }
  };

  const handleCreateNewFile = async () => {
    if (!newFilePath.trim()) {
      message.warning('请输入文件路径');
      return;
    }
    try {
      await handleWriteFile(newFilePath.trim(), newFileContent);
      setNewFileModalOpen(false);
      setNewFilePath('');
      setNewFileContent('');
      // Select the newly created file
      setSelectedPath(newFilePath.trim());
      setSelectedNodeType('file');
      setFileContent(newFileContent);
    } catch {
      // error already shown
    }
  };

  const startEdit = () => {
    setEditedContent(fileContent);
    setIsEditing(true);
  };

  const cancelEdit = () => {
    setIsEditing(false);
    setEditedContent('');
  };

  const saveEdit = async () => {
    if (!selectedPath) return;
    await handleWriteFile(selectedPath, editedContent);
    setIsEditing(false);
    setEditedContent('');
  };

  const confirmDelete = () => {
    if (!selectedPath) return;
    // SKILL.md should not be deletable
    if (selectedPath === 'SKILL.md' || selectedPath.endsWith('/SKILL.md')) {
      message.warning('SKILL.md 不允许删除');
      return;
    }
    setDeleteTarget(selectedPath);
    setDeleteModalOpen(true);
  };

  const canEdit = !isSystem && selectedNodeType === 'file' && !isBinary;
  const canDelete =
    !isSystem &&
    selectedPath !== null &&
    selectedPath !== 'SKILL.md' &&
    !selectedPath.endsWith('/SKILL.md');

  if (!visible) return null;

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      {!isSystem && (
        <div className="flex items-center gap-2 mb-3 px-1">
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              setNewFilePath('');
              setNewFileContent('');
              setNewFileModalOpen(true);
            }}
          >
            新建文件
          </Button>
          <Button
            size="small"
            icon={<FolderAddOutlined />}
            onClick={() => {
              setNewFolderPath('');
              setNewFolderModalOpen(true);
            }}
          >
            新建文件夹
          </Button>
          <Tooltip title="刷新">
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={fetchTree}
              loading={loading}
            />
          </Tooltip>
          <div className="flex-1" />
          {canEdit && (
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={startEdit}
              disabled={isEditing}
            >
              编辑
            </Button>
          )}
          {canDelete && (
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={confirmDelete}
            >
              删除
            </Button>
          )}
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-1 gap-3 min-h-0">
        {/* Tree Panel */}
        <div className="w-2/5 min-w-[180px] border border-gray-200 rounded-lg overflow-auto bg-white p-2">
          {loading && treeData.length === 0 ? (
            <div className="flex justify-center py-8">
              <Spin size="small" />
            </div>
          ) : treeData.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文件" className="py-8" />
          ) : (
            <Tree
              treeData={treeData}
              showLine
              defaultExpandAll
              onSelect={handleSelect}
              selectedKeys={selectedPath ? [selectedPath] : []}
              switcherIcon={({ expanded }) =>
                expanded ? (
                  <FolderOpenOutlined className="text-amber-500 text-xs" />
                ) : (
                  <FolderOutlined className="text-amber-500 text-xs" />
                )
              }
            />
          )}
        </div>

        {/* Content Panel */}
        <div className="flex-1 border border-gray-200 rounded-lg overflow-hidden bg-white flex flex-col">
          {selectedNodeType === 'file' ? (
            <>
              <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
                <span className="text-xs text-gray-500 font-mono truncate">
                  {selectedPath}
                </span>
                {isEditing && (
                  <span className="text-xs text-blue-500">编辑中</span>
                )}
              </div>
              <div className="flex-1 p-3 overflow-auto">
                {fileLoading ? (
                  <div className="flex justify-center py-8">
                    <Spin />
                  </div>
                ) : isBinary ? (
                  <div className="flex flex-col items-center justify-center h-full text-gray-400">
                    <FileOutlined className="text-4xl mb-2" />
                    <p>二进制文件，无法显示内容</p>
                  </div>
                ) : isEditing ? (
                  <Input.TextArea
                    value={editedContent}
                    onChange={(e) => setEditedContent(e.target.value)}
                    className="font-mono text-sm"
                    style={{ minHeight: '300px', resize: 'vertical' }}
                    autoSize={{ minRows: 12, maxRows: 30 }}
                  />
                ) : (
                  <pre className="font-mono text-sm text-gray-700 whitespace-pre-wrap break-all">
                    {fileContent || <span className="text-gray-300">空文件</span>}
                  </pre>
                )}
              </div>
              {isEditing && (
                <div className="px-3 py-2 border-t border-gray-100 bg-gray-50 flex items-center gap-2 justify-end">
                  <Button
                    size="small"
                    icon={<CloseOutlined />}
                    onClick={cancelEdit}
                  >
                    取消
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    icon={<SaveOutlined />}
                    onClick={saveEdit}
                    loading={saving}
                  >
                    保存
                  </Button>
                </div>
              )}
            </>
          ) : selectedNodeType === 'dir' ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <FolderOutlined className="text-4xl mb-2 text-amber-400" />
              <p>已选择目录: {selectedPath}</p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-gray-300">
              <FileOutlined className="text-4xl mb-2" />
              <p>点击左侧文件查看内容</p>
            </div>
          )}
        </div>
      </div>

      {/* New File Modal */}
      <Modal
        title="新建文件"
        open={newFileModalOpen}
        onOk={handleCreateNewFile}
        onCancel={() => {
          setNewFileModalOpen(false);
          setNewFilePath('');
          setNewFileContent('');
        }}
        okText="创建"
        cancelText="取消"
        confirmLoading={saving}
      >
        <div className="space-y-3">
          <div>
            <label className="block text-sm text-gray-600 mb-1">文件路径</label>
            <Input
              placeholder="例如: scripts/helper.py"
              value={newFilePath}
              onChange={(e) => setNewFilePath(e.target.value)}
              onPressEnter={handleCreateNewFile}
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">文件内容</label>
            <Input.TextArea
              placeholder="输入文件内容..."
              value={newFileContent}
              onChange={(e) => setNewFileContent(e.target.value)}
              className="font-mono text-sm"
              autoSize={{ minRows: 6, maxRows: 16 }}
            />
          </div>
        </div>
      </Modal>

      {/* New Folder Modal */}
      <Modal
        title="新建文件夹"
        open={newFolderModalOpen}
        onOk={handleMkdir}
        onCancel={() => {
          setNewFolderModalOpen(false);
          setNewFolderPath('');
        }}
        okText="创建"
        cancelText="取消"
      >
        <div>
          <label className="block text-sm text-gray-600 mb-1">目录路径</label>
          <Input
            placeholder="例如: scripts/utils"
            value={newFolderPath}
            onChange={(e) => setNewFolderPath(e.target.value)}
            onPressEnter={handleMkdir}
          />
        </div>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        title="确认删除"
        open={deleteModalOpen}
        onOk={handleDelete}
        onCancel={() => {
          setDeleteModalOpen(false);
          setDeleteTarget('');
        }}
        okText="删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <p>
          确定删除 <strong>{deleteTarget}</strong> 吗？此操作不可恢复。
        </p>
      </Modal>
    </div>
  );
};

export default SkillFileBrowser;
