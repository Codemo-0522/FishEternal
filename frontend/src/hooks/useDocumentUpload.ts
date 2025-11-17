/**
 * 文档上传 Hook
 * 提供统一的文档上传、进度跟踪、任务状态查询功能
 */
import { useState, useCallback } from 'react';
import { message as antdMessage } from 'antd';
import authAxios from '../utils/authAxios';

export interface KbSettings {
  enabled: boolean;
  collection_name: string;
  embedding_provider?: string;
  embedding_model?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  [key: string]: any;
}

export interface UploadOptions {
  file: File;
  kbSettings: KbSettings;
  sessionId?: string;
  priority?: 'LOW' | 'NORMAL' | 'HIGH';
  onProgress?: (progress: number) => void;
  onSuccess?: (result: UploadResult) => void;
  onError?: (error: string) => void;
}

export interface UploadResult {
  ok: boolean;
  task_id?: string;
  chunks?: number;
  status: 'processing' | 'success' | 'error';
  message: string;
  error?: string;
  metadata?: Record<string, any>;
}

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  result?: any;
  error?: string;
  retry_count: number;
  metadata?: Record<string, any>;
}

export const useDocumentUpload = () => {
  const [uploading, setUploading] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  /**
   * 上传文档（异步处理）
   */
  const uploadDocument = useCallback(async (options: UploadOptions): Promise<UploadResult> => {
    const {
      file,
      kbSettings,
      sessionId,
      priority = 'NORMAL',
      onProgress,
      onSuccess,
      onError
    } = options;

    try {
      setUploading(true);
      setUploadProgress(0);

      // 构建表单数据
      const formData = new FormData();
      formData.append('file', file);
      formData.append('kb_settings_json', JSON.stringify(kbSettings));
      if (sessionId) {
        formData.append('session_id', sessionId);
      }
      formData.append('priority', priority);

      // 发送上传请求
      const response = await authAxios.post<UploadResult>(
        '/api/kb/upload_and_ingest',
        formData,
        {
          onUploadProgress: (progressEvent: any) => {
            if (progressEvent.total) {
              const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
              setUploadProgress(percent);
              onProgress?.(percent);
            }
          }
        }
      );

      const result = response.data;

      // 如果返回了任务ID，保存以便后续查询
      if (result.task_id) {
        setCurrentTaskId(result.task_id);
      }

      setUploadProgress(100);
      onSuccess?.(result);

      return result;

    } catch (error: any) {
      const errorMsg = error?.response?.data?.detail || error?.message || '上传失败';
      onError?.(errorMsg);
      throw new Error(errorMsg);

    } finally {
      setUploading(false);
    }
  }, []);

  /**
   * 查询任务状态
   */
  const getTaskStatus = useCallback(async (taskId: string): Promise<TaskStatus> => {
    try {
      const response = await authAxios.get<TaskStatus>(`/api/kb/task_status/${taskId}`);
      return response.data;
    } catch (error: any) {
      const errorMsg = error?.response?.data?.detail || error?.message || '查询任务状态失败';
      throw new Error(errorMsg);
    }
  }, []);

  /**
   * 轮询任务状态直到完成
   */
  const pollTaskStatus = useCallback(async (
    taskId: string,
    options?: {
      interval?: number;
      maxAttempts?: number;
      onProgress?: (status: TaskStatus) => void;
      onComplete?: (status: TaskStatus) => void;
      onError?: (error: string) => void;
    }
  ): Promise<TaskStatus> => {
    const {
      interval = 2000,
      maxAttempts = 150, // 5分钟（2秒 * 150）
      onProgress,
      onComplete,
      onError
    } = options || {};

    let attempts = 0;

    return new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        attempts++;

        try {
          const status = await getTaskStatus(taskId);
          
          onProgress?.(status);

          // 任务完成
          if (status.status === 'completed') {
            clearInterval(timer);
            onComplete?.(status);
            resolve(status);
            return;
          }

          // 任务失败
          if (status.status === 'failed' || status.status === 'cancelled') {
            clearInterval(timer);
            const error = status.error || '任务处理失败';
            onError?.(error);
            reject(new Error(error));
            return;
          }

          // 超时
          if (attempts >= maxAttempts) {
            clearInterval(timer);
            const error = '任务处理超时';
            onError?.(error);
            reject(new Error(error));
            return;
          }

        } catch (error: any) {
          clearInterval(timer);
          const errorMsg = error?.message || '查询任务状态失败';
          onError?.(errorMsg);
          reject(error);
        }
      }, interval);
    });
  }, [getTaskStatus]);

  /**
   * 上传并等待完成（带进度提示）
   */
  const uploadAndWait = useCallback(async (
    options: UploadOptions
  ): Promise<{ uploadResult: UploadResult; taskStatus?: TaskStatus }> => {
    
    // 1. 上传文档
    const uploadResult = await uploadDocument(options);

    // 2. 如果是异步处理，轮询任务状态
    if (uploadResult.task_id) {
      antdMessage.loading({
        content: '正在处理文档...',
        key: 'document-processing',
        duration: 0
      });

      try {
        const taskStatus = await pollTaskStatus(uploadResult.task_id, {
          onProgress: (status) => {
            if (status.progress > 0) {
              antdMessage.loading({
                content: `处理中... ${status.progress}%`,
                key: 'document-processing',
                duration: 0
              });
            }
          },
          onComplete: (status) => {
            antdMessage.destroy('document-processing');
            antdMessage.success(`文档处理完成！生成 ${status.result?.chunks || 0} 个分片`);
          },
          onError: (error) => {
            antdMessage.destroy('document-processing');
            antdMessage.error(error);
          }
        });

        return { uploadResult, taskStatus };

      } catch (error: any) {
        antdMessage.destroy('document-processing');
        throw error;
      }

    } else {
      // 同步处理，直接返回
      return { uploadResult };
    }
  }, [uploadDocument, pollTaskStatus]);

  /**
   * 重置状态
   */
  const reset = useCallback(() => {
    setUploading(false);
    setCurrentTaskId(null);
    setUploadProgress(0);
  }, []);

  return {
    // 状态
    uploading,
    currentTaskId,
    uploadProgress,

    // 方法
    uploadDocument,
    getTaskStatus,
    pollTaskStatus,
    uploadAndWait,
    reset
  };
};

