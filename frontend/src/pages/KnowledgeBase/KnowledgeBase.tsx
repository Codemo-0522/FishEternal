/**
 * 知识库管理页面
 * 独立的知识库系统，与RAGFlow并存
 * 支持创建知识库、上传文档、向量解析、检索测试等功能
 */
import React, { useState, useEffect, useRef } from 'react';
import {
  Layout,
  Card,
  Button,
  Input,
  Select,
  Table,
  Space,
  Modal,
  message,
  Tag,
  Tooltip,
  Progress,
  Empty,
  Descriptions,
  Upload,
  Popconfirm,
  Alert,
  InputNumber,
  Switch,
  List,
  Typography,
  Badge,
  Statistic,
  Row,
  Col,
  Form,
  Divider,
} from 'antd';
import {
  PlusOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  DeleteOutlined,
  EditOutlined,
  SearchOutlined,
  UploadOutlined,
  DownloadOutlined,
  EyeOutlined,
  ReloadOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  SyncOutlined,
  ArrowLeftOutlined,
  PlayCircleOutlined,
  ShareAltOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import authAxios from '../../utils/authAxios';
import type { ColumnsType } from 'antd/es/table';
import styles from './KnowledgeBase.module.css';
import {
  shareKnowledgeBase,
  unshareKnowledgeBase,
} from '../../api/kbMarketplace';
import { useAuthStore } from '../../stores/authStore';

const { Header, Content } = Layout;
const { Search } = Input;
const { Option } = Select;
const { Title, Text, Paragraph } = Typography;
const { Dragger } = Upload;

// ==================== 类型定义 ====================

/** 知识库配置 */
interface KnowledgeBase {
  id: string;
  name: string;
  collection_name: string;
  description?: string;
  vector_db: string;
  embedding_config: {
    provider: string;
    model: string;
    base_url?: string;
    api_key?: string;
    local_model_path?: string;
  };
  split_params: {
    chunk_size: number;
    chunk_overlap: number;
    separators: string[];
    // 智能分片配置
    chunking_strategy?: string;
    use_sentence_boundary?: boolean;
    semantic_threshold?: number;
    preserve_structure?: boolean;
    ast_parsing?: boolean;
    enable_hierarchy?: boolean;
    parent_chunk_size?: number;
  };
  search_params?: {
    distance_metric: string;
    similarity_threshold: number;
    top_k: number;
  };
  // 兼容旧版字段
  similarity_threshold: number;
  top_k: number;
  created_at: string;
  updated_at: string;
  document_count: number;
  chunk_count: number;
  // 后端原始数据结构（用于更新）
  kb_settings?: Record<string, any>;
  // 共享信息（后端直接返回）
  sharing_info?: {
    is_shared: boolean;
    shared_at: string;
    shared_kb_id: string;
  };
}

/** 文档信息 */
interface Document {
  id: string;
  kb_id: string;
  filename: string;
  file_size: number;
  file_type: string;
  upload_time: string;
  status: 'pending' | 'uploaded' | 'processing' | 'completed' | 'failed';
  chunk_count: number;
  error_message?: string;
  metadata?: Record<string, any>;
  file_url?: string;  // MinIO 文件路径
  // 任务进度信息
  progress?: number;  // 进度百分比 (0.0-1.0)
  progress_msg?: string;  // 进度描述信息
  // 知识图谱构建状态
  kg_status?: 'not_built' | 'building' | 'success' | 'failed';
  kg_error_message?: string;
  kg_built_time?: string;
}

/** 分片信息 */
interface Chunk {
  id: string;
  content: string;
  metadata: Record<string, any>;
  chunk_index: number;
}

/** 检索结果 */
interface SearchResult {
  chunk_id: string;
  content: string;
  score: number;
  distance: number;
  metadata: Record<string, any>;
  document_name?: string;
}

/** Embedding服务商 */
interface EmbeddingProvider {
  id: string;
  name: string;
  baseUrl?: string;
  apiKey?: string;
  models: string[];
  defaultModel: string;
  enabled: boolean;
}

// ==================== 主组件 ====================

const KnowledgeBase: React.FC = () => {
  // ==================== 状态管理 ====================
  
  const token = useAuthStore((state) => state.token);
  
  // 视图状态
  const [currentView, setCurrentView] = useState<'list' | 'detail'>('list');
  const [selectedKB, setSelectedKB] = useState<KnowledgeBase | null>(null);
  
  // 知识库列表
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [kbLoading, setKbLoading] = useState(false);
  const [kbSearchText, setKbSearchText] = useState('');
  
  
  // 文档列表
  const [documents, setDocuments] = useState<Document[]>([]);
  const [docLoading, setDocLoading] = useState(false);
  const [docSearchText, setDocSearchText] = useState('');
  const [docStatusFilter, setDocStatusFilter] = useState<string>('all'); // 文档状态筛选
  const [docFileTypeFilter, setDocFileTypeFilter] = useState<string>('all'); // 文件类型筛选
  const [docKgStatusFilter, setDocKgStatusFilter] = useState<string>('all'); // 知识图谱状态筛选
  
  // 模态框控制
  const [createKBModalVisible, setCreateKBModalVisible] = useState(false);
  const [editKBModalVisible, setEditKBModalVisible] = useState(false);
  const [uploadDocModalVisible, setUploadDocModalVisible] = useState(false);
  const [searchTestModalVisible, setSearchTestModalVisible] = useState(false);
  const [chunksModalVisible, setChunksModalVisible] = useState(false);
  
  // 文档分页
  const [documentsPagination, setDocumentsPagination] = useState({
    current: 1,
    pageSize: 10,
    total: 0,
  });
  
  // 分片查看
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksPagination, setChunksPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  });
  
  // 表单数据
  const [kbForm, setKbForm] = useState({
    name: '',
    description: '',
    collection_name: '',
    vector_db: 'chroma',
    embedding_provider: '',
    embedding_model: '',
    embedding_base_url: '',
    embedding_api_key: '',
    chunk_size: 2048,
    chunk_overlap: 100,
    separators: ['。', '！', '？', '，', ' ', '','\n\n', '\n', ].join('\n'),
    distance_metric: 'cosine',  // 默认距离度量：余弦距离（文本检索）
    similarity_threshold: 0.3,  // 默认相似度阈值：0.3（范围0-1，1表示最相似，宽松场景推荐0.3-0.5）
    top_k: 5,
    // 智能分片配置
    chunking_strategy: 'document_aware',  // 分片策略：simple, semantic, document_aware, hierarchical
    use_sentence_boundary: true,  // 使用句子边界
    semantic_threshold: 0.5,  // 语义阈值
    preserve_structure: true,  // 保持结构完整性
    ast_parsing: true,  // 使用AST解析（代码文件）
    enable_hierarchy: false,  // 启用层级分片
    parent_chunk_size: 4096,  // 父分片大小
  });
  
  // Embedding服务商
  const [embeddingProviders, setEmbeddingProviders] = useState<EmbeddingProvider[]>([]);
  const [defaultEmbeddingProvider, setDefaultEmbeddingProvider] = useState<string>('');
  
  // 文件上传
  const [uploadFileList, setUploadFileList] = useState<any[]>([]);
  const [batchUploading, setBatchUploading] = useState(false);
  const [processingSelection, setProcessingSelection] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  
  // 新增：队列上传进度状态
  const [queueState, setQueueState] = useState({
    enabled: false,
    totalBatches: 0,
    currentBatch: 0,
    uploadedFiles: 0,
    totalFiles: 0,
    uploadedBytes: 0,
    totalBytes: 0,
    percent: 0
  });
  
  // 检索测试
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  
  // 统计信息
  const [statistics, setStatistics] = useState({
    total_kbs: 0,
    total_documents: 0,
    total_chunks: 0,
    total_size: 0,
  });
  
  // 轮询控制
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  
  // 批量解析 - 独立跟踪系统
  const [batchParsing, setBatchParsing] = useState(false);
  const [batchParseProgress, setBatchParseProgress] = useState({ completed: 0, total: 0, failed: 0 });
  const batchParseDocListRef = useRef<string[]>([]); // 记录批量解析的文档ID列表
  
  // 批量创建知识图谱 - 独立跟踪系统
  const [batchCreatingKG, setBatchCreatingKG] = useState(false);
  const [kgCreationProgress, setKgCreationProgress] = useState({ completed: 0, total: 0, failed: 0 });
  const batchKGDocListRef = useRef<string[]>([]); // 记录批量创建KG的文档ID列表
  const kgPollIntervalRef = useRef<NodeJS.Timeout | null>(null); // 轮询定时器
  
  // ==================== 生命周期 ====================
  
  useEffect(() => {
    loadEmbeddingProviders();
    loadKnowledgeBases();
    loadStatistics();
    
    return () => {
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
      }
      if (kgPollIntervalRef.current) {
        clearInterval(kgPollIntervalRef.current);
      }
    };
  }, []);
  
  // 自动刷新处理中的任务
  useEffect(() => {
    if (!autoRefresh) return;
    
    const hasProcessing = documents.some(
      doc => doc.status === 'pending' || doc.status === 'processing'
    );
    
    if (hasProcessing && selectedKB) {
      pollingTimerRef.current = setTimeout(() => {
        loadDocuments(selectedKB.id, true, documentsPagination.current, documentsPagination.pageSize);
      }, 3000);
    }
    
    return () => {
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
      }
    };
  }, [documents, autoRefresh, selectedKB]);
  
  // 批量解析进度跟踪 - 基于批量解析的文档列表
  useEffect(() => {
    if (!batchParsing || batchParseDocListRef.current.length === 0) return;
    
    // 只统计批量解析列表中的文档
    const batchDocs = documents.filter(doc => batchParseDocListRef.current.includes(doc.id));
    
    if (batchDocs.length === 0) return;
    
    const completed = batchDocs.filter(doc => doc.status === 'completed').length;
    const failed = batchDocs.filter(doc => doc.status === 'failed').length;
    const total = batchParseDocListRef.current.length;
    
    setBatchParseProgress({ completed, total, failed });
    
    // 所有文档都处理完成（成功或失败）
    if (completed + failed >= total) {
      setBatchParsing(false);
      batchParseDocListRef.current = []; // 清空列表
      
      if (completed > 0) {
        message.success(`批量解析完成：成功 ${completed} 个${failed > 0 ? `，失败 ${failed} 个` : ''}`);
      } else {
        message.error(`批量解析失败：所有 ${failed} 个文档都失败了`);
      }
    }
  }, [documents, batchParsing]);
  
  // ==================== API调用 ====================
  
  /** 加载Embedding服务商 */
  const loadEmbeddingProviders = async () => {
    try {
      const response = await authAxios.get('/api/embedding-config/user');
      const configs = response.data.configs || {};
      
      const providers: EmbeddingProvider[] = Object.entries(configs)
        .filter(([_, config]: any) => config.enabled)
        .map(([id, config]: any) => ({
          id,
          name: config.name || id,
          baseUrl: config.base_url || '',
          apiKey: config.api_key || '',
          models: config.models || [],
          defaultModel: config.default_model || '',
          enabled: true,
        }));
      
      setEmbeddingProviders(providers);
      
      // 获取默认服务商
      const defaultResponse = await authAxios.get('/api/embedding-config/default');
      if (defaultResponse.data.success) {
        setDefaultEmbeddingProvider(defaultResponse.data.provider_id);
        
        // 自动填充默认服务商
        const defaultProvider = providers.find(p => p.id === defaultResponse.data.provider_id);
        if (defaultProvider) {
          setKbForm(prev => ({
            ...prev,
            embedding_provider: defaultProvider.id,
            embedding_model: defaultProvider.defaultModel,
            embedding_base_url: defaultProvider.baseUrl || '',
            embedding_api_key: defaultProvider.apiKey || '',
          }));
        }
      }
    } catch (error: any) {
      console.error('加载Embedding服务商失败:', error);
      message.error('加载Embedding配置失败');
    }
  };
  
  /** 加载知识库列表 */
  const loadKnowledgeBases = async (silent = false) => {
    if (!silent) setKbLoading(true);
    try {
      const response = await authAxios.get('/api/kb/list');
      const kbs = response.data.knowledge_bases || [];
      setKnowledgeBases(kbs);
    } catch (error: any) {
      console.error('加载知识库列表失败:', error);
      message.error(error.response?.data?.detail || '加载知识库列表失败');
    } finally {
      if (!silent) setKbLoading(false);
    }
  };
  
  /** 加载文档列表 */
  const loadDocuments = async (kbId: string, silent = false, page = 1, pageSize = 10) => {
    if (!silent) setDocLoading(true);
    try {
      const skip = (page - 1) * pageSize;
      const response = await authAxios.get(`/api/kb/${kbId}/documents`, {
        params: { skip, limit: pageSize }
      });
      setDocuments(response.data.documents || []);
      // 更新分页信息
      if (response.data.pagination) {
        setDocumentsPagination({
          current: response.data.pagination.page,
          pageSize: response.data.pagination.page_size,
          total: response.data.pagination.total,
        });
      }
    } catch (error: any) {
      console.error('加载文档列表失败:', error);
      message.error(error.response?.data?.detail || '加载文档列表失败');
    } finally {
      if (!silent) setDocLoading(false);
    }
  };
  
  /** 加载分片列表 */
  const loadChunks = async (kbId: string, docId: string, page = 1, pageSize = 20) => {
    setChunksLoading(true);
    try {
      const response = await authAxios.get(
        `/api/kb/${kbId}/documents/${docId}/chunks`,
        { params: { page, page_size: pageSize } }
      );
      
      setChunks(response.data.chunks || []);
      setChunksPagination({
        current: response.data.pagination.page,
        pageSize: response.data.pagination.page_size,
        total: response.data.pagination.total,
      });
      
      return response.data;
    } catch (error: any) {
      console.error('加载分片列表失败:', error);
      message.error(error.response?.data?.detail || '加载分片列表失败');
      return null;
    } finally {
      setChunksLoading(false);
    }
  };
  
  /** 打开分片查看模态框 */
  const handleViewChunks = async (document: Document) => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    setSelectedDocument(document);
    setChunksModalVisible(true);
    
    // 加载分片数据
    await loadChunks(selectedKB.id, document.id, 1, 20);
  };
  
  /** 加载统计信息 */
  const loadStatistics = async () => {
    try {
      const response = await authAxios.get('/api/kb/statistics');
      // 后端直接返回统计数据对象，不是嵌套在 statistics 字段中
      setStatistics(response.data || {
        total_kbs: 0,
        total_documents: 0,
        total_chunks: 0,
        total_size: 0,
      });
    } catch (error: any) {
      console.error('加载统计信息失败:', error);
    }
  };
  
  /** 共享知识库 */
  const handleShareKB = async (kb: KnowledgeBase) => {
    if (!token) {
      message.error('请先登录');
      return;
    }
    
    Modal.confirm({
      title: '共享知识库到广场',
      content: (
        <div>
          <p>确认将「{kb.name}」共享到知识库广场？</p>
          <p style={{ color: '#999', fontSize: 12 }}>
            共享后，其他用户可以看到您的知识库元数据并拉取使用。
            您的 API Key 等敏感信息不会被共享。
          </p>
        </div>
      ),
      onOk: async () => {
        try {
          await shareKnowledgeBase(token, kb.id, undefined);  // 不传递description，使用原知识库的实时描述
          message.success('共享成功！');
          await loadKnowledgeBases(true); // 重新加载列表以更新 sharing_info
        } catch (error: any) {
          message.error(error.message || '共享失败');
        }
      },
    });
  };
  
  /** 取消共享知识库 */
  const handleUnshareKB = async (kb: KnowledgeBase) => {
    if (!token) {
      message.error('请先登录');
      return;
    }
    
    Modal.confirm({
      title: '取消共享知识库',
      content: (
        <div>
          <p>确认取消共享「{kb.name}」？</p>
          <p style={{ color: '#999', fontSize: 12 }}>
            取消共享后，其他用户将无法在广场看到此知识库。
            已拉取的用户仍可继续使用。
          </p>
        </div>
      ),
      onOk: async () => {
        try {
          await unshareKnowledgeBase(token, kb.id);
          message.success('已取消共享');
          await loadKnowledgeBases(true); // 重新加载列表以更新 sharing_info
        } catch (error: any) {
          message.error(error.message || '取消共享失败');
        }
      },
    });
  };
  
  /** 创建知识库 */
  const handleCreateKB = async () => {
    if (!kbForm.name.trim()) {
      message.error('请输入知识库名称');
      return;
    }
    
    if (!kbForm.collection_name.trim()) {
      message.error('请输入Collection名称');
      return;
    }
    
    if (!kbForm.embedding_provider) {
      message.error('请选择Embedding服务商');
      return;
    }
    
    if (!kbForm.embedding_model) {
      message.error('请选择Embedding模型');
      return;
    }
    
    try {
      const payload = {
        name: kbForm.name.trim(),
        description: kbForm.description.trim(),
        collection_name: kbForm.collection_name.trim(),
        vector_db: kbForm.vector_db,
        embedding_config: {
          provider: kbForm.embedding_provider,
          model: kbForm.embedding_model,
          ...(kbForm.embedding_base_url && { base_url: kbForm.embedding_base_url }),
          ...(kbForm.embedding_api_key && { api_key: kbForm.embedding_api_key }),
          ...(kbForm.embedding_provider === 'local' && {
            local_model_path: `checkpoints/embeddings/${kbForm.embedding_model}`
          }),
        },
        split_params: {
          chunk_size: kbForm.chunk_size,
          chunk_overlap: kbForm.chunk_overlap,
          separators: kbForm.separators.split('\n').map(s => s.trim()).filter(Boolean),
          // 智能分片配置
          chunking_strategy: kbForm.chunking_strategy,
          use_sentence_boundary: kbForm.use_sentence_boundary,
          semantic_threshold: kbForm.semantic_threshold,
          preserve_structure: kbForm.preserve_structure,
          ast_parsing: kbForm.ast_parsing,
          enable_hierarchy: kbForm.enable_hierarchy,
          parent_chunk_size: kbForm.parent_chunk_size,
        },
        search_params: {
          distance_metric: kbForm.distance_metric,
          similarity_threshold: kbForm.similarity_threshold,
          top_k: kbForm.top_k,
        },
        // 兼容旧版字段
        similarity_threshold: kbForm.similarity_threshold,
        top_k: kbForm.top_k,
      };
      
      await authAxios.post('/api/kb/create', payload);
      message.success('知识库创建成功');
      setCreateKBModalVisible(false);
      resetKbForm();
      loadKnowledgeBases();
      loadStatistics();
    } catch (error: any) {
      console.error('创建知识库失败:', error);
      message.error(error.response?.data?.detail || '创建知识库失败');
    }
  };
  
  /** 更新知识库 */
  const handleUpdateKB = async () => {
    if (!selectedKB) return;
    
    try {
      // 构建更新后的 kb_settings（保持与数据库结构一致）
      const updatedKbSettings = {
        ...selectedKB.kb_settings,  // 保留原有设置（如 enabled, vector_db, collection_name, embeddings）
        split_params: {
          chunk_size: kbForm.chunk_size,
          chunk_overlap: kbForm.chunk_overlap,
          separators: kbForm.separators.split('\n').map(s => s.trim()).filter(Boolean),
          // 智能分片配置
          chunking_strategy: kbForm.chunking_strategy,
          use_sentence_boundary: kbForm.use_sentence_boundary,
          semantic_threshold: kbForm.semantic_threshold,
          preserve_structure: kbForm.preserve_structure,
          ast_parsing: kbForm.ast_parsing,
          enable_hierarchy: kbForm.enable_hierarchy,
          parent_chunk_size: kbForm.parent_chunk_size,
        },
        search_params: {
          distance_metric: kbForm.distance_metric,
          similarity_threshold: kbForm.similarity_threshold,
          top_k: kbForm.top_k,
        },
        // 兼容旧版字段
        similarity_threshold: kbForm.similarity_threshold,
        top_k: kbForm.top_k,
      };
      
      const payload = {
        name: kbForm.name.trim(),
        description: kbForm.description.trim(),
        kb_settings: updatedKbSettings,  // ✅ 完整的 kb_settings 对象
      };
      
      const response = await authAxios.put(`/api/kb/${selectedKB.id}`, payload);
      message.success('知识库配置已更新');
      setEditKBModalVisible(false);
      
      // 重新加载知识库列表
      await loadKnowledgeBases();
      
      // 更新 selectedKB（使用后端返回的最新数据）
      if (response.data) {
        setSelectedKB(response.data);
      }
    } catch (error: any) {
      console.error('更新知识库失败:', error);
      message.error(error.response?.data?.detail || '更新知识库失败');
    }
  };
  
  /** 删除知识库 */
  const handleDeleteKB = async (kbId: string) => {
    try {
      await authAxios.delete(`/api/kb/${kbId}`);
      message.success('知识库已删除');
      loadKnowledgeBases();
      loadStatistics();
      if (selectedKB?.id === kbId) {
        setSelectedKB(null);
        setCurrentView('list');
      }
    } catch (error: any) {
      console.error('删除知识库失败:', error);
      message.error(error.response?.data?.detail || '删除知识库失败');
    }
  };
  
  /** 支持拖拽文件夹：递归遍历DataTransferItem条目 - 优化性能 */
  const collectFilesFromItems = async (items: DataTransferItemList): Promise<File[]> => {
    let collectedCount = 0;
    let lastUpdateTime = Date.now();
    
    const getAllFiles = async (entry: any, pathPrefix = ''): Promise<File[]> => {
      return new Promise<File[]>((resolve) => {
        if (!entry) return resolve([]);
        if (entry.isFile) {
          entry.file((file: File) => {
            // 保留相对路径信息（若可用）
            (file as any).webkitRelativePath = pathPrefix + file.name;
            collectedCount++;
            
            // 每收集100个文件更新一次提示(限流，避免频繁更新UI)
            const now = Date.now();
            if (collectedCount % 100 === 0 && now - lastUpdateTime > 1000) {
              console.log(`[KnowledgeBase] 已扫描 ${collectedCount} 个文件...`);
              lastUpdateTime = now;
            }
            
            resolve([file]);
          }, () => resolve([]));
        } else if (entry.isDirectory) {
          const reader = entry.createReader();
          const entries: any[] = [];
          const readEntries = () => {
            reader.readEntries(async (batch: any[]) => {
              if (!batch.length) {
                // 限制并发数，避免同时递归太多目录导致卡顿
                const CONCURRENT_LIMIT = 10;
                const allNested: File[] = [];
                
                for (let i = 0; i < entries.length; i += CONCURRENT_LIMIT) {
                  const chunk = entries.slice(i, i + CONCURRENT_LIMIT);
                  const nested = await Promise.all(
                    chunk.map((ent) => getAllFiles(ent, pathPrefix + entry.name + '/'))
                  );
                  allNested.push(...nested.flat());
                  
                  // 让出主线程控制权
                  if (entries.length > 50 && i % 50 === 0) {
                    await new Promise(r => setTimeout(r, 0));
                  }
                }
                
                resolve(allNested);
              } else {
                entries.push(...batch);
                readEntries();
              }
            }, () => resolve([]));
          };
          readEntries();
        } else {
          resolve([]);
        }
      });
    };

    const tasks: Promise<File[]>[] = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const entry = (it as any).webkitGetAsEntry ? (it as any).webkitGetAsEntry() : null;
      if (entry) {
        tasks.push(getAllFiles(entry));
      } else if (it.kind === 'file') {
        const file = it.getAsFile();
        if (file) tasks.push(Promise.resolve([file]));
      }
    }
    
    const fileGroups = await Promise.all(tasks);
    const allFiles = fileGroups.flat();
    
    console.log(`[KnowledgeBase] 文件夹扫描完成，共找到 ${allFiles.length} 个文件`);
    
    return allFiles;
  };

  /** 统一的文件过滤与列表变更处理 - 优化大量文件性能 */
  const handleUploadChange: any = ({ fileList: newFileList }: any) => {
    console.log('=== [KnowledgeBase] 文件列表变更 ===');
    console.log('[KnowledgeBase] 新文件列表长度:', newFileList.length);
    
    const allowed = new Set([
      // 文本文档
      '.txt', '.pdf', '.doc', '.docx', '.md', '.markdown', '.html', '.htm', '.json', '.csv', '.xlsx', '.xls', '.ppt', '.pptx', '.rtf', '.odt', '.epub', '.tex', '.log', '.rst', '.org',
      // 代码与配置
      '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.kt', '.kts', '.scala', '.go', '.rs', '.rb', '.php', '.cs', '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.m', '.mm', '.swift', '.dart', '.lua', '.pl', '.pm', '.r', '.jl', '.sql', '.sh', '.bash', '.zsh', '.ps1', '.psm1', '.bat', '.cmd', '.vb', '.vbs', '.groovy', '.gradle', '.make', '.mk', '.cmake', '.toml', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.properties', '.env', '.editorconfig', '.dockerfile', '.gql', '.graphql', '.svelte', '.vue',
      // 图片
      '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.svg', '.ico', '.heic'
    ]);

    // 大量文件时显示提示（仅显示一次）
    if (newFileList.length > 100) {
      setProcessingSelection(true);
    }

    // 使用 requestIdleCallback 分片处理，避免阻塞主线程
    const processBatch = async () => {
      const BATCH_SIZE = 50; // 每批处理50个文件
      const filtered: any[] = [];
      let skipped = 0;

      for (let i = 0; i < newFileList.length; i += BATCH_SIZE) {
        const batch = newFileList.slice(i, i + BATCH_SIZE);
        
        // 使用 Promise + setTimeout 让出主线程控制权
        await new Promise<void>((resolve) => {
          setTimeout(() => {
            batch.forEach((f: any) => {
              const name = f.name || '';
              const ext = name.includes('.') ? name.substring(name.lastIndexOf('.')).toLowerCase() : '';
              if (allowed.has(ext)) {
                filtered.push(f);
              } else {
                skipped++;
              }
            });
            resolve();
          }, 0);
        });

        // 实时更新进度（仅控制台输出）
        if (newFileList.length > 100 && i % (BATCH_SIZE * 5) === 0) {
          const progress = Math.round((i / newFileList.length) * 100);
          console.log(`[KnowledgeBase] 文件筛选进度: ${progress}%`);
        }
      }

      // 处理完成 - 仅在有需要时显示一次提示
      if (skipped > 0) {
        message.warning(`有 ${skipped} 个文件类型不被支持，已自动忽略`);
      }

      console.log(`[KnowledgeBase] 最终筛选结果: ${filtered.length} 个有效文件`);
      setUploadFileList(filtered);
      setProcessingSelection(false);
    };

    // 启动异步处理
    processBatch().catch(err => {
      console.error('[KnowledgeBase] 文件处理失败:', err);
      message.error('文件处理失败，请重试');
      setProcessingSelection(false);
    });
  };

  /** 处理拖拽文件/文件夹 - 优化大量文件性能 */
  const handleDrop: any = async (e: any) => {
    setIsDragOver(false);
    try {
      console.log('[KnowledgeBase] onDrop 触发，处理拖拽的文件/文件夹');
      const items = e.dataTransfer?.items as DataTransferItemList | undefined;
      const filesList = e.dataTransfer?.files as FileList | undefined;

      // 优先使用 DataTransferItemList 以便支持目录遍历
      if (items && items.length > 0) {
        let hasDirectory = false;
        for (let i = 0; i < items.length; i++) {
          const entry = (items[i] as any).webkitGetAsEntry ? (items[i] as any).webkitGetAsEntry() : null;
          if (entry && entry.isDirectory) { hasDirectory = true; break; }
        }
        // 仅当包含目录时，接管默认行为
        if (hasDirectory) {
          e.preventDefault?.();
          e.stopPropagation?.();
          // 显示一次扫描提示
          const hide = message.loading('正在扫描文件夹，请稍候...', 0);
          
          setProcessingSelection(true);
          const files = await collectFilesFromItems(items);
          
          // 关闭加载提示
          hide();
          
          const mapped: any[] = files.map((f, idx) => ({
            uid: `${Date.now()}_${idx}_${f.name}`,
            name: f.name,
            size: f.size,
            status: 'done',
            originFileObj: f as any,
          }));
          const merged = [...uploadFileList, ...mapped];
          handleUploadChange({ fileList: merged } as any);
          return;
        } else {
          // 非目录，直接处理
          const files = Array.from(filesList || []).map(f => f as File);
          const mapped: any[] = files.map((f, idx) => ({
            uid: `${Date.now()}_${idx}_${f.name}`,
            name: f.name,
            size: f.size,
            status: 'done',
            originFileObj: f as any,
          }));
          const merged = [...uploadFileList, ...mapped];
          handleUploadChange({ fileList: merged } as any);
          return;
        }
      }

      // 退化方案：某些环境无 items，仅有 files
      if (filesList && filesList.length > 0) {
        setProcessingSelection(true);
        const files = Array.from(filesList);
        
        const mapped: any[] = files.map((f, idx) => ({
          uid: `${Date.now()}_${idx}_${f.name}`,
          name: f.name,
          size: f.size,
          status: 'done',
          originFileObj: f as any,
        }));
        const merged = [...uploadFileList, ...mapped];
        handleUploadChange({ fileList: merged } as any);
      }
    } catch (err) {
      console.error('[KnowledgeBase] 处理拖拽数据失败:', err);
      message.error('文件拖拽处理失败，请重试');
      setProcessingSelection(false);
    }
  };

  /** 上传文档（队列分批上传） */
  const handleUploadDocuments = async () => {
    console.log('=== [KnowledgeBase] 开始上传流程 ===');
    console.log('[KnowledgeBase] 当前文件列表长度:', uploadFileList.length);

    if (uploadFileList.length === 0) {
      console.warn('[KnowledgeBase] 没有选择文件');
      message.warning('请选择要上传的文件');
      return;
    }

    if (!selectedKB?.id) {
      console.error('[KnowledgeBase] 没有选择知识库');
      message.error('请先选择知识库');
      return;
    }

    // 大量文件时，弹出确认对话框
    if (uploadFileList.length > 100) {
      return new Promise<void>((resolve) => {
        Modal.confirm({
          title: '批量上传确认',
          content: (
            <div>
              <p>您即将上传 <strong>{uploadFileList.length}</strong> 个文件到知识库。</p>
              <p style={{ color: '#faad14' }}>
                ⚠️ 提示：大量文件上传可能需要较长时间，建议您：
              </p>
              <ul style={{ paddingLeft: 20, margin: '8px 0' }}>
                <li>保持网络连接稳定</li>
                <li>不要关闭浏览器窗口</li>
                <li>耐心等待上传完成</li>
              </ul>
              <p>确定要继续吗？</p>
            </div>
          ),
          okText: '确定上传',
          cancelText: '取消',
          icon: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
          onOk: async () => {
            await performUpload();
            resolve();
          },
          onCancel: () => {
            resolve();
          },
        });
      });
    }

    // 文件数量不多，直接上传
    await performUpload();
  };

  /** 执行实际的上传操作 */
  const performUpload = async () => {
    if (!selectedKB?.id) {
      message.error('未选择知识库');
      return;
    }

    try {
      console.log('[KnowledgeBase] 开始验证和处理文件...');

      // 统一提取 File 对象
      const files: File[] = uploadFileList.map((file) => {
        const actual = (file as any).originFileObj instanceof File
          ? (file as any).originFileObj as File
          : (file as any) as File;
        return actual;
      });

      // 计算批次（根据实际需求调整，这里简化为每批最多50个文件）
      const MAX_FILES_PER_BATCH = 50;
      const MAX_BYTES_PER_BATCH = 500 * 1024 * 1024; // 500MB

      type Batch = { files: File[]; size: number };
      const batches: Batch[] = [];
      let current: Batch = { files: [], size: 0 };

      for (const f of files) {
        const nextCount = current.files.length + 1;
        const nextSize = current.size + (f.size || 0);
        if (nextCount > MAX_FILES_PER_BATCH || nextSize > MAX_BYTES_PER_BATCH) {
          if (current.files.length > 0) {
            batches.push(current);
          }
          current = { files: [f], size: f.size || 0 };
        } else {
          current.files.push(f);
          current.size = nextSize;
        }
      }
      if (current.files.length > 0) batches.push(current);

      // 队列信息
      const totalFiles = files.length;
      const totalBytes = files.reduce((acc, f) => acc + (f.size || 0), 0);
      
      console.log(`[KnowledgeBase] 上传计划: ${totalFiles} 个文件, ${batches.length} 个批次`);
      
      // 始终启用进度条
      setQueueState({
        enabled: true,
        totalBatches: batches.length,
        currentBatch: 0,
        uploadedFiles: 0,
        totalFiles,
        uploadedBytes: 0,
        totalBytes,
        percent: 0
      });

      setBatchUploading(true);

      // 逐批、逐文件上传（按文件粒度更新进度）
      let uploadedFiles = 0;
      let uploadedBytes = 0;
      let failCount = 0;
      
      for (let i = 0; i < batches.length; i++) {
        const batch = batches[i];
        setQueueState(prev => ({
          ...prev,
          currentBatch: i + 1
        }));

        console.log(`[KnowledgeBase] 处理批次 ${i + 1}/${batches.length}, 包含 ${batch.files.length} 个文件`);

        for (const f of batch.files) {
          try {
            const formData = new FormData();
            // 🔧 创建新的 File 对象，只保留文件名（去除路径信息）
            // 因为浏览器会使用 webkitRelativePath 作为文件名上传
            const cleanFile = new File([f], f.name, { type: f.type });
            formData.append('file', cleanFile);
            await authAxios.post(`/api/kb/${selectedKB.id}/upload`, formData);
            
            uploadedFiles += 1;
            uploadedBytes += f.size || 0;
            setQueueState(prev => ({
              ...prev,
              uploadedFiles,
              uploadedBytes,
              percent: Math.min(100, Math.round((uploadedFiles / totalFiles) * 100))
            }));
          } catch (error: any) {
            // 🔧 不在循环中弹出错误提示，仅记录到控制台，统一在最后提示
            console.error(`上传文件 ${f.name} 失败:`, error);
            failCount++;
          }
        }
      }

      console.log('[KnowledgeBase] 上传完成');
      const successCount = uploadedFiles - failCount;
      
      if (successCount > 0) {
        message.success(`成功上传 ${successCount} 个文件${failCount > 0 ? `，失败 ${failCount} 个` : ''}。请点击"解析"按钮开始处理文档。`, 5);
      } else {
        message.error('所有文件上传失败');
      }
      
      // 全部上传完成后刷新列表
      await loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
      await loadStatistics();
      setUploadDocModalVisible(false);
      setUploadFileList([]);
      setQueueState(prev => ({ ...prev, enabled: false }));
    } catch (error) {
      console.error('=== [KnowledgeBase] 上传失败 ===');
      console.error('[KnowledgeBase] 错误详情:', {
        error,
        message: error instanceof Error ? error.message : '未知错误',
        stack: error instanceof Error ? error.stack : undefined
      });
      message.error(`文档上传失败: ${error instanceof Error ? error.message : '未知错误'}`);
      setQueueState(prev => ({ ...prev, enabled: false }));
    } finally {
      setBatchUploading(false);
    }
  };
  
  /** 解析文档 */
  const handleParseDocument = async (docId: string) => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    try {
      const response = await authAxios.post(`/api/kb/${selectedKB.id}/documents/${docId}/parse`);
      message.success(response.data.message || '文档解析任务已提交');
      
      // 刷新文档列表
      setTimeout(() => {
        loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
      }, 1000);
    } catch (error: any) {
      console.error('解析文档失败:', error);
      message.error(error.response?.data?.detail || '解析文档失败');
    }
  };

  /** 重置文档状态（清理卡住的文档） */
  const handleResetDocumentStatus = async (docId: string, filename: string) => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    try {
      await authAxios.post(`/api/kb/${selectedKB.id}/documents/${docId}/reset-status`);
      message.success(`文档「${filename}」状态已重置，可以重新解析了`);
      
      // 刷新文档列表
      loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
    } catch (error: any) {
      console.error('重置文档状态失败:', error);
      message.error(error.response?.data?.detail || '重置文档状态失败');
    }
  };
  
  /** 批量解析未解析的文档 */
  const handleBatchParseDocuments = async () => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    // 获取所有未解析的文档（状态为 uploaded）
    const unparsedDocs = documents.filter(doc => doc.status === 'uploaded');
    
    if (unparsedDocs.length === 0) {
      message.warning('没有需要解析的文档');
      return;
    }
    
    // 确认对话框
    Modal.confirm({
      title: '批量解析文档',
      content: `确定要解析 ${unparsedDocs.length} 个未解析的文档吗？`,
      okText: '确定',
      cancelText: '取消',
      onOk: async () => {
        // 记录批量解析的文档ID列表
        const docIds = unparsedDocs.map(doc => doc.id);
        batchParseDocListRef.current = docIds;
        
        // 初始化进度
        setBatchParsing(true);
        setBatchParseProgress({ completed: 0, total: docIds.length, failed: 0 });
        
        try {
          // 使用后端批量解析API
          const response = await authAxios.post(`/api/kb/${selectedKB.id}/documents/batch-parse`, {
            doc_ids: docIds,
            priority: 'normal'
          });
          
          if (response.data.submitted > 0) {
            message.success(
              `成功提交 ${response.data.submitted} 个文档的解析任务` +
              (response.data.failed > 0 ? `，${response.data.failed} 个提交失败` : '')
            );
          } else {
            message.error('所有文档提交失败');
            setBatchParsing(false);
            batchParseDocListRef.current = [];
          }
          
          // 显示错误详情（如果有）
          if (response.data.errors && response.data.errors.length > 0) {
            console.error('批量解析错误:', response.data.errors);
          }
          
        } catch (error: any) {
          console.error('批量解析失败:', error);
          setBatchParsing(false);
          batchParseDocListRef.current = [];
          message.error(error.response?.data?.detail || '批量解析失败');
        }
        
        // 刷新文档列表（进度会通过 useEffect 自动更新）
        setTimeout(() => {
          loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
        }, 1000);
      },
    });
  };
  
  /** 解析总文档 - 解析知识库中所有未解析的文档（不受分页限制） */
  const handleParseAllDocuments = async () => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    // 确认对话框
    Modal.confirm({
      title: '解析总文档',
      content: (
        <div>
          <p>此操作将解析知识库中<strong>所有未解析</strong>的文档（不受当前分页限制）。</p>
          <p style={{ color: '#1890ff', marginTop: 8 }}>
            系统会自动筛选状态为"未解析"的文档，避免重复解析。
          </p>
          <p style={{ color: '#ff4d4f', marginTop: 8 }}>
            注意：任务将在后台执行，请耐心等待。
          </p>
        </div>
      ),
      okText: '确定',
      cancelText: '取消',
      width: 500,
      onOk: async () => {
        try {
          // 调用新的批量解析所有文档API
          const response = await authAxios.post(`/api/kb/${selectedKB.id}/documents/batch-parse-all`, {
            priority: 'normal'
          });
          
          const { submitted, failed, total } = response.data;
          
          if (submitted > 0) {
            message.success(
              `已成功提交 ${submitted} 个文档的解析任务` +
              (failed > 0 ? `，${failed} 个提交失败` : '') +
              `（总计: ${total}）`
            );
          } else if (total === 0) {
            message.info('没有需要解析的文档');
          } else {
            message.error('所有文档提交失败');
          }
          
          // 显示错误详情（如果有）
          if (response.data.errors && response.data.errors.length > 0) {
            console.error('批量解析错误:', response.data.errors);
          }
          
          // 刷新文档列表
          setTimeout(() => {
            loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
          }, 1000);
          
        } catch (error: any) {
          console.error('批量解析所有文档失败:', error);
          message.error(error.response?.data?.detail || '批量解析失败');
        }
      },
    });
  };

  /** 创建总文档知识图谱 - 为知识库中所有未创建图谱的JSON文档创建知识图谱（不受分页限制） */
  const handleCreateAllKnowledgeGraphs = async () => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    // 确认对话框
    Modal.confirm({
      title: '创建总文档知识图谱',
      content: (
        <div>
          <p>此操作将为知识库中<strong>所有未创建知识图谱</strong>的JSON文档创建知识图谱（不受当前分页限制）。</p>
          <p style={{ color: '#1890ff', marginTop: 8 }}>
            系统会自动筛选：
          </p>
          <ul style={{ fontSize: 12, color: '#666' }}>
            <li>文件类型必须是 .json</li>
            <li>图谱状态为"未构建"或"构建失败"</li>
          </ul>
          <p style={{ color: '#ff4d4f', marginTop: 8 }}>
            注意：此操作将调用Neo4j创建知识图谱，任务将在后台执行。
          </p>
        </div>
      ),
      okText: '确定',
      cancelText: '取消',
      width: 600,
      onOk: () => {
        // 🎯 立即启动后台任务，不阻塞模态框关闭
        (async () => {
          // 初始化进度
          setBatchCreatingKG(true);
          setKgCreationProgress({ completed: 0, total: 0, failed: 0 });
          
          try {
            message.info('正在提交批量任务到队列...');
            
            // 🆕 使用新的批量构建所有知识图谱API
            const response = await authAxios.post('/api/knowledge-graph/batch-build-all', {
              kb_id: selectedKB.id,
            });
            
            const { batch_id, total_tasks } = response.data;
            
            if (total_tasks === 0) {
              message.info('没有需要构建知识图谱的JSON文档');
              setBatchCreatingKG(false);
              return;
            }
            
            message.success(`已成功提交 ${total_tasks} 个任务到队列，批次ID: ${batch_id.substring(0, 8)}...`);
            
            // 更新初始总数
            setKgCreationProgress({ completed: 0, total: total_tasks, failed: 0 });
            
            // 清除旧的轮询定时器
            if (kgPollIntervalRef.current) {
              clearInterval(kgPollIntervalRef.current);
            }
            
            // 开始轮询进度
            kgPollIntervalRef.current = setInterval(async () => {
              try {
                const statusResponse = await authAxios.get(`/api/knowledge-graph/batch-status/${batch_id}`);
                const { completed, failed, total_tasks: total, status } = statusResponse.data;
                
                // 更新进度（基于批量API的实际进度）
                setKgCreationProgress({ completed, total, failed });
                
                // 检查是否完成
                if (status === 'completed' || status === 'partial_failed') {
                  if (kgPollIntervalRef.current) {
                    clearInterval(kgPollIntervalRef.current);
                    kgPollIntervalRef.current = null;
                  }
                  setBatchCreatingKG(false);
                  
                  if (status === 'completed') {
                    message.success(`🎉 批量任务完成！成功: ${completed}/${total}`);
                  } else {
                    message.warning(`⚠️ 批量任务完成，成功: ${completed}，失败: ${failed}，总计: ${total}`);
                  }
                  
                  // 刷新文档列表
                  if (selectedKB) {
                    await loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
                  }
                }
                
              } catch (error: any) {
                console.error('轮询进度失败:', error);
                // 不终止轮询，继续尝试
              }
            }, 2000); // 每2秒轮询一次
            
            // 设置最大轮询时间（24小时）
            setTimeout(() => {
              if (kgPollIntervalRef.current) {
                clearInterval(kgPollIntervalRef.current);
                kgPollIntervalRef.current = null;
                setBatchCreatingKG(false);
                message.info('已停止进度轮询（超时），任务仍在后台执行');
              }
            }, 24 * 60 * 60 * 1000);
            
          } catch (error: any) {
            console.error('批量提交知识图谱任务失败:', error);
            setBatchCreatingKG(false);
            message.error(error.response?.data?.detail || '批量提交失败');
          }
        })();
        
        // 🎯 不返回 Promise，模态框立即关闭
      },
    });
  };
  
  /** 批量创建知识图谱 - 为所有筛选出来的JSON文件创建知识图谱 */
  const handleBatchCreateKnowledgeGraph = async () => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    // 获取所有筛选出来的JSON文件（不受分页限制）
    // 只处理未构建(not_built)和失败(failed)的文档
    const jsonDocs = documents.filter(doc => {
      const matchesSearch = doc.filename.toLowerCase().includes(docSearchText.toLowerCase());
      
      let matchesStatus = true;
      if (docStatusFilter === 'uploaded') {
        matchesStatus = doc.status === 'uploaded';
      } else if (docStatusFilter === 'completed') {
        matchesStatus = doc.status === 'completed';
      } else if (docStatusFilter === 'failed') {
        matchesStatus = doc.status === 'failed';
      }
      
      // 必须是.json文件
      const fileExt = doc.filename.toLowerCase().split('.').pop() || '';
      const isJsonFile = fileExt === 'json';
      
      // 知识图谱状态：只允许未构建(not_built)和失败(failed)的文档
      const kgStatus = doc.kg_status || 'not_built';
      const canBuildKG = kgStatus === 'not_built' || kgStatus === 'failed';
      
      return matchesSearch && matchesStatus && isJsonFile && canBuildKG;
    });
    
    if (jsonDocs.length === 0) {
      message.warning('没有符合条件的JSON文件');
      return;
    }
    
    // 确认对话框
    Modal.confirm({
      title: '批量创建知识图谱',
      content: (
        <div>
          <p>确定要为以下 <strong>{jsonDocs.length}</strong> 个JSON文件创建知识图谱吗？</p>
          <ul style={{ maxHeight: 200, overflowY: 'auto', fontSize: 12 }}>
            {jsonDocs.slice(0, 10).map(doc => (
              <li key={doc.id}>{doc.filename}</li>
            ))}
            {jsonDocs.length > 10 && <li>... 还有 {jsonDocs.length - 10} 个文件</li>}
          </ul>
          <p style={{ color: '#ff4d4f', marginTop: 8 }}>
            注意：此操作将调用Neo4j创建知识图谱，任务将在后台执行。
          </p>
        </div>
      ),
      okText: '确定',
      cancelText: '取消',
      width: 600,
      onOk: () => {
        // 🎯 立即启动后台任务，不阻塞模态框关闭
        (async () => {
          // 记录批量创建KG的文档ID列表
          const doc_ids = jsonDocs.map(doc => doc.id);
          batchKGDocListRef.current = doc_ids;
          
          // 初始化进度
          setBatchCreatingKG(true);
          setKgCreationProgress({ completed: 0, total: doc_ids.length, failed: 0 });
          
          try {
            message.info('正在提交批量任务到队列...');
            
            // 🆕 使用新的批量API（一次性提交所有任务）
            const response = await authAxios.post('/api/knowledge-graph/batch-build', {
              doc_ids: doc_ids,
              kb_id: selectedKB.id,
              clear_existing: false,
            });
            
            const { batch_id, total_tasks } = response.data;
            
            message.success(`已成功提交 ${total_tasks} 个任务到队列，批次ID: ${batch_id.substring(0, 8)}...`);
            
            // 清除旧的轮询定时器
            if (kgPollIntervalRef.current) {
              clearInterval(kgPollIntervalRef.current);
            }
            
            // 开始轮询进度
            kgPollIntervalRef.current = setInterval(async () => {
              try {
                const statusResponse = await authAxios.get(`/api/knowledge-graph/batch-status/${batch_id}`);
                const { completed, failed, total_tasks: total, status } = statusResponse.data;
                
                // 更新进度（基于批量API的实际进度）
                setKgCreationProgress({ completed, total, failed });
                
                // 检查是否完成
                if (status === 'completed' || status === 'partial_failed') {
                  if (kgPollIntervalRef.current) {
                    clearInterval(kgPollIntervalRef.current);
                    kgPollIntervalRef.current = null;
                  }
                  setBatchCreatingKG(false);
                  batchKGDocListRef.current = [];
                  
                  if (status === 'completed') {
                    message.success(`🎉 批量任务完成！成功: ${completed}/${total}`);
                  } else {
                    message.warning(`⚠️ 批量任务完成，成功: ${completed}，失败: ${failed}，总计: ${total}`);
                  }
                  
                  // 刷新文档列表
                  if (selectedKB) {
                    await loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
                  }
                }
                
              } catch (error: any) {
                console.error('轮询进度失败:', error);
                // 不终止轮询，继续尝试
              }
            }, 2000); // 每2秒轮询一次
            
            // 设置最大轮询时间（24小时）
            setTimeout(() => {
              if (kgPollIntervalRef.current) {
                clearInterval(kgPollIntervalRef.current);
                kgPollIntervalRef.current = null;
                setBatchCreatingKG(false);
                batchKGDocListRef.current = [];
                message.info('已停止进度轮询（超时），任务仍在后台执行');
              }
            }, 24 * 60 * 60 * 1000);
            
          } catch (error: any) {
            console.error('批量提交知识图谱任务失败:', error);
            setBatchCreatingKG(false);
            batchKGDocListRef.current = [];
            message.error(error.response?.data?.detail || '批量提交失败');
          }
        })();
        
        // 🎯 不返回 Promise，模态框立即关闭
      },
    });
  };
  
  /** 下载文档原文 */
  const handleDownloadDocument = async (docId: string, filename: string) => {
    if (!selectedKB) {
      message.error('未选择知识库');
      return;
    }
    
    try {
      const response = await authAxios.get(
        `/api/kb/${selectedKB.id}/documents/${docId}/download`,
        { responseType: 'blob' }
      );
      
      // 创建下载链接
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      
      message.success('文档下载成功');
    } catch (error: any) {
      console.error('下载文档失败:', error);
      message.error(error.response?.data?.detail || '下载文档失败');
    }
  };
  
  /** 删除文档 */
  const handleDeleteDocument = async (docId: string) => {
    try {
      if (!selectedKB) {
        message.error('未选择知识库');
        return;
      }
      await authAxios.delete(`/api/kb/${selectedKB.id}/documents/${docId}`);
      message.success('文档已删除');
      loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize);
      loadStatistics();
    } catch (error: any) {
      console.error('删除文档失败:', error);
      message.error(error.response?.data?.detail || '删除文档失败');
    }
  };
  
  /** 检索测试 */
  const handleSearchTest = async () => {
    if (!selectedKB) {
      message.error('请先选择知识库');
      return;
    }
    
    if (!searchQuery.trim()) {
      message.error('请输入检索内容');
      return;
    }
    
    setSearching(true);
    try {
      const response = await authAxios.post(`/api/kb/${selectedKB.id}/search`, {
        query: searchQuery.trim(),
        top_k: selectedKB.search_params?.top_k || selectedKB.top_k,
        similarity_threshold: selectedKB.search_params?.similarity_threshold || selectedKB.similarity_threshold,
        distance_metric: selectedKB.search_params?.distance_metric || 'cosine',  // 从kb_settings动态加载距离度量
      });
      
      setSearchResults(response.data.results || []);
      
      if (response.data.results.length === 0) {
        message.info('未找到相关内容，请尝试调大过滤强度数值');
      } else {
        message.success(`找到 ${response.data.results.length} 条相关结果`);
      }
    } catch (error: any) {
      console.error('检索失败:', error);
      message.error(error.response?.data?.detail || '检索失败');
    } finally {
      setSearching(false);
    }
  };
  
  // ==================== 工具函数 ====================
  
  const resetKbForm = () => {
    const defaultProvider = embeddingProviders.find(p => p.id === defaultEmbeddingProvider) || embeddingProviders[0];
    setKbForm({
      name: '',
      description: '',
      collection_name: '',
      vector_db: 'chroma',
      embedding_provider: defaultProvider?.id || '',
      embedding_model: defaultProvider?.defaultModel || '',
      embedding_base_url: (defaultProvider?.baseUrl || ''),
      embedding_api_key: (defaultProvider?.apiKey || ''),
      chunk_size: 1024,
      chunk_overlap: 100,
      separators: ['\n\n', '\n', '。', '！', '？', '，', ' ', ''].join('\n'),
      distance_metric: 'cosine',
      similarity_threshold: 0.3,
      top_k: 5,
      // 智能分片配置
      chunking_strategy: 'document_aware',
      use_sentence_boundary: true,
      semantic_threshold: 0.5,
      preserve_structure: true,
      ast_parsing: true,
      enable_hierarchy: false,
      parent_chunk_size: 4096,
    });
  };
  
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };
  
  const formatDate = (dateString: string): string => {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };
  
  /** 获取知识库状态标签（基于chunk_count） */
  const getKBStatusTag = (chunkCount: number) => {
    if (chunkCount > 0) {
      return (
        <Tag icon={<CheckCircleOutlined />} color="success">
          已就绪
        </Tag>
      );
    }
    return (
      <Tag icon={<ClockCircleOutlined />} color="default">
        无数据
      </Tag>
    );
  };
  
  /** 获取文档状态标签 */
  const getDocStatusTag = (status: string, record?: Document) => {
    const statusConfig: Record<string, { color: string; icon: React.ReactNode; text: string; style?: React.CSSProperties }> = {
      pending: { color: 'default', icon: <ClockCircleOutlined />, text: '等待中' },
      uploaded: { 
        color: 'default', 
        icon: <FileTextOutlined />, 
        text: '未解析',
        style: { 
          backgroundColor: 'var(--tag-unparsed-bg, rgba(0, 0, 0, 0.06))',
          color: 'var(--tag-unparsed-text, rgba(0, 0, 0, 0.45))',
          borderColor: 'var(--tag-unparsed-border, rgba(0, 0, 0, 0.15))'
        }
      },
      processing: { color: 'processing', icon: <SyncOutlined spin />, text: '解析中' },
      completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
      failed: { color: 'error', icon: <ExclamationCircleOutlined />, text: '失败' },
    };
    
    const config = statusConfig[status] || statusConfig.pending;
    
    // 如果是 processing 状态且有进度信息，显示进度百分比
    if (status === 'processing' && record?.progress !== undefined && record.progress > 0) {
      const progressPercent = Math.round(record.progress * 100);
      return (
        <Tag icon={config.icon} color={config.color}>
          {progressPercent}%
        </Tag>
      );
    }
    
    return (
      <Tag icon={config.icon} color={config.color} style={config.style}>
        {config.text}
      </Tag>
    );
  };
  
  /** 获取知识图谱构建状态标签 */
  const getKgStatusTag = (kgStatus?: string, kgErrorMessage?: string) => {
    const status = kgStatus || 'not_built';
    const statusConfig: Record<string, { color: string; icon: React.ReactNode; text: string }> = {
      not_built: { color: 'default', icon: <ClockCircleOutlined />, text: '未构建' },
      building: { color: 'processing', icon: <SyncOutlined spin />, text: '构建中' },
      success: { color: 'success', icon: <CheckCircleOutlined />, text: '已构建' },
      failed: { color: 'error', icon: <ExclamationCircleOutlined />, text: '构建失败' },
    };
    
    const config = statusConfig[status] || statusConfig.not_built;
    const tag = (
      <Tag icon={config.icon} color={config.color}>
        {config.text}
      </Tag>
    );
    
    // 如果有错误信息，添加提示
    if (status === 'failed' && kgErrorMessage) {
      return (
        <Tooltip title={kgErrorMessage}>
          {tag}
        </Tooltip>
      );
    }
    
    return tag;
  };
  
  // 过滤知识库
  const filteredKBs = knowledgeBases.filter(kb =>
    kb.name.toLowerCase().includes(kbSearchText.toLowerCase()) ||
    kb.collection_name.toLowerCase().includes(kbSearchText.toLowerCase())
  );
  
  // 过滤文档
  const filteredDocs = documents.filter(doc => {
    const matchesSearch = doc.filename.toLowerCase().includes(docSearchText.toLowerCase());
    
    let matchesStatus = true;
    if (docStatusFilter === 'uploaded') {
      matchesStatus = doc.status === 'uploaded';
    } else if (docStatusFilter === 'completed') {
      matchesStatus = doc.status === 'completed';
    } else if (docStatusFilter === 'failed') {
      matchesStatus = doc.status === 'failed';
    }
    
    // 文件类型筛选
    let matchesFileType = true;
    if (docFileTypeFilter !== 'all') {
      const fileExt = doc.filename.toLowerCase().split('.').pop() || '';
      matchesFileType = fileExt === docFileTypeFilter;
    }
    
    // 知识图谱状态筛选（仅对JSON文件生效）
    let matchesKgStatus = true;
    const fileExt = doc.filename.toLowerCase().split('.').pop() || '';
    if (docFileTypeFilter === 'json' && fileExt === 'json' && docKgStatusFilter !== 'all') {
      const kgStatus = doc.kg_status || 'not_built';
      matchesKgStatus = kgStatus === docKgStatusFilter;
    }
    
    return matchesSearch && matchesStatus && matchesFileType && matchesKgStatus;
  });
  
  // ==================== 表格列定义 ====================
  
  const kbColumns: ColumnsType<KnowledgeBase> = [
    {
      title: '知识库名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      fixed: 'left',
      render: (text, record) => (
        <Space>
          <DatabaseOutlined style={{ fontSize: 16, color: '#1890ff' }} />
          <a onClick={() => {
            setSelectedKB(record);
            setCurrentView('detail');
            setDocumentsPagination({ current: 1, pageSize: 10, total: 0 });
            loadDocuments(record.id);
          }}>
            {text}
          </a>
        </Space>
      ),
    },
    {
      title: 'Collection',
      dataIndex: 'collection_name',
      key: 'collection_name',
      width: 180,
      ellipsis: true,
      render: (text) => (
        <Tooltip title={text}>
          <Text code>{text}</Text>
        </Tooltip>
      ),
    },
    {
      title: '向量数据库',
      dataIndex: 'vector_db',
      key: 'vector_db',
      width: 120,
      render: (text) => {
        const dbConfig: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
          chroma: { color: 'blue', icon: <DatabaseOutlined />, label: 'ChromaDB' },
          faiss: { color: 'green', icon: <ThunderboltOutlined />, label: 'FAISS' },
        };
        const config = dbConfig[text] || { color: 'default', icon: null, label: text };
        return (
          <Tag color={config.color} icon={config.icon}>
            {config.label}
          </Tag>
        );
      },
    },
    {
      title: 'Embedding',
      key: 'embedding',
      width: 180,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.embedding_config?.provider || '未知'}
          </Text>
          <Text style={{ fontSize: 12 }}>{record.embedding_config?.model || '未知'}</Text>
        </Space>
      ),
    },
    {
      title: '文档数',
      dataIndex: 'document_count',
      key: 'document_count',
      width: 100,
      align: 'center',
      render: (count) => <Badge count={count} showZero color="blue" />,
    },
    {
      title: '分片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
      align: 'center',
      render: (count) => <Badge count={count} showZero color="green" />,
    },
    {
      title: '状态',
      dataIndex: 'chunk_count',
      key: 'kb_status',
      width: 100,
      align: 'center',
      render: (chunkCount) => getKBStatusTag(chunkCount),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (date) => formatDate(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      fixed: 'right',
      render: (_: any, record: KnowledgeBase) => {
        // 直接从 record 中读取共享状态，不需要再调用 API
        const isShared = record.sharing_info?.is_shared || false;
        
        return (
          <Space size="small">
            <Tooltip title="查看详情">
              <Button
                type="link"
                size="small"
                icon={<EyeOutlined />}
                onClick={() => {
                  setSelectedKB(record);
                  setCurrentView('detail');
                  setDocumentsPagination({ current: 1, pageSize: 10, total: 0 });
                  loadDocuments(record.id);
                }}
              />
            </Tooltip>
            <Tooltip title="编辑配置">
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={async () => {
                  setSelectedKB(record);
                  await loadEmbeddingProviders(); // 重新加载 embedding 配置
                  setKbForm({
                    name: record.name,
                    description: record.description || '',
                    collection_name: record.collection_name,
                    vector_db: record.vector_db,
                    embedding_provider: record.embedding_config?.provider || 'local',
                    embedding_model: record.embedding_config?.model || '',
                    embedding_base_url: record.embedding_config?.base_url || '',
                    embedding_api_key: record.embedding_config?.api_key || '',
                    chunk_size: record.split_params.chunk_size,
                    chunk_overlap: record.split_params.chunk_overlap,
                    separators: record.split_params.separators.join('\n'),
                    distance_metric: record.search_params?.distance_metric || 'cosine',
                    similarity_threshold: record.search_params?.similarity_threshold || record.similarity_threshold,
                    top_k: record.search_params?.top_k || record.top_k,
                    // 智能分片配置
                    chunking_strategy: record.split_params.chunking_strategy || 'document_aware',
                    use_sentence_boundary: record.split_params.use_sentence_boundary ?? true,
                    semantic_threshold: record.split_params.semantic_threshold || 0.5,
                    preserve_structure: record.split_params.preserve_structure ?? true,
                    ast_parsing: record.split_params.ast_parsing ?? true,
                    enable_hierarchy: record.split_params.enable_hierarchy || false,
                    parent_chunk_size: record.split_params.parent_chunk_size || 4096,
                  });
                  setEditKBModalVisible(true);
                }}
              />
            </Tooltip>
            {isShared ? (
              <Tooltip title="取消共享">
                <Button
                  type="link"
                  size="small"
                  icon={<GlobalOutlined />}
                  onClick={() => handleUnshareKB(record)}
                  style={{ color: '#52c41a' }}
                />
              </Tooltip>
            ) : (
              <Tooltip title="共享到广场">
                <Button
                  type="link"
                  size="small"
                  icon={<ShareAltOutlined />}
                  onClick={() => handleShareKB(record)}
                />
              </Tooltip>
            )}
            <Popconfirm
              title="确定删除此知识库吗？"
              description="此操作将删除所有关联的文档和向量数据，且无法恢复！"
              onConfirm={() => handleDeleteKB(record.id)}
              okText="确定"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Tooltip title="删除">
                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];
  
  const docColumns: ColumnsType<Document> = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      width: 250,
      ellipsis: true,
      render: (text) => (
        <Space>
          <FileTextOutlined style={{ fontSize: 14 }} />
          <Tooltip title={text}>
            <span>{text}</span>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '文件类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 100,
      render: (type: string) => <Tag>{type.toUpperCase()}</Tag>,
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (size) => formatFileSize(size),
    },
    {
      title: '分片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 100,
      align: 'center',
      render: (count) => <Badge count={count} showZero color="green" />,
    },
    {
      title: 'RAG',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      align: 'center',
      render: (status, record) => getDocStatusTag(status, record),
    },
    {
      title: '知识图谱',
      key: 'kg_status',
      width: 120,
      align: 'center',
      render: (_, record) => {
        // 只有JSON文件才显示知识图谱状态
        const fileExt = record.filename.toLowerCase().split('.').pop() || '';
        if (fileExt !== 'json') {
          return <Text type="secondary">-</Text>;
        }
        return getKgStatusTag(record.kg_status, record.kg_error_message);
      },
    },
    {
      title: '上传时间',
      dataIndex: 'upload_time',
      key: 'upload_time',
      width: 160,
      render: (date) => formatDate(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {/* 解析按钮 - 只有 uploaded 状态才显示 */}
          {record.status === 'uploaded' && (
            <Tooltip title="解析文档">
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => handleParseDocument(record.id)}
              >
                解析
              </Button>
            </Tooltip>
          )}
          
          {/* 重置按钮 - 只有 processing 或 failed 状态才显示 */}
          {(record.status === 'processing' || record.status === 'failed') && (
            <Tooltip title={`重置状态（当前：${record.status === 'processing' ? '解析中' : '失败'}）`}>
              <Popconfirm
                title="确定重置文档状态吗？"
                description={`将清除当前的${record.status === 'processing' ? '解析中' : '失败'}状态，使其可以重新解析`}
                onConfirm={() => handleResetDocumentStatus(record.id, record.filename)}
                okText="确定"
                cancelText="取消"
              >
                <Button
                  type="default"
                  size="small"
                  icon={<ReloadOutlined />}
                  danger={record.status === 'failed'}
                >
                  重置
                </Button>
              </Popconfirm>
            </Tooltip>
          )}
          
          {/* 下载按钮 - 只有有 file_url 才显示 */}
          {record.file_url && (
            <Tooltip title="下载原文">
              <Button
                type="link"
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => handleDownloadDocument(record.id, record.filename)}
              />
            </Tooltip>
          )}
          
          {/* 查看分片 - 只有 completed 状态才显示 */}
          {record.status === 'completed' && record.chunk_count > 0 && (
            <Tooltip title="查看分片">
              <Button
                type="link"
                size="small"
                icon={<EyeOutlined />}
                onClick={() => handleViewChunks(record)}
              />
            </Tooltip>
          )}
          
          <Popconfirm
            title="确定删除此文档吗？"
            description="此操作将删除文档及其所有分片数据，且无法恢复！"
            onConfirm={() => handleDeleteDocument(record.id)}
            okText="确定"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];
  
  // ==================== 渲染函数 ====================
  
  /** 渲染知识库列表视图 */
  const renderListView = () => (
    <div className={styles.listView}>
      {/* 统计卡片 */}
      <Row gutter={16} className={styles.statisticsRow}>
        <Col xs={24} sm={12} md={6}>
          <Card className={styles.statCard}>
            <Statistic
              title="知识库总数"
              value={statistics.total_kbs}
              prefix={<DatabaseOutlined />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card className={styles.statCard}>
            <Statistic
              title="文档总数"
              value={statistics.total_documents}
              prefix={<FileTextOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card className={styles.statCard}>
            <Statistic
              title="分片总数"
              value={statistics.total_chunks}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#cf1322' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card className={styles.statCard}>
            <Statistic
              title="总存储"
              value={formatFileSize(statistics.total_size)}
              prefix={<DatabaseOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>
      
      {/* 操作栏 */}
      <Card className={styles.actionCard}>
        <Space className={styles.actionBar} wrap>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={async () => {
              resetKbForm();
              await loadEmbeddingProviders(); // 重新加载 embedding 配置
              setCreateKBModalVisible(true);
            }}
          >
            创建知识库
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => loadKnowledgeBases()}>
            刷新
          </Button>
          <Search
            placeholder="搜索知识库名称或Collection"
            allowClear
            style={{ width: 300 }}
            value={kbSearchText}
            onChange={(e) => setKbSearchText(e.target.value)}
          />
        </Space>
      </Card>
      
      {/* 知识库表格 */}
      <Card className={styles.tableCard}>
        <Table
          columns={kbColumns}
          dataSource={filteredKBs}
          rowKey="id"
          loading={kbLoading}
          scroll={{ x: 1400 }}
          pagination={{
            defaultPageSize: 10,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 个知识库`,
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无知识库，点击上方【创建知识库】按钮开始"
              />
            ),
          }}
        />
      </Card>
    </div>
  );
  
  /** 渲染知识库详情视图 */
  const renderDetailView = () => (
    <div className={styles.detailView}>
      {/* 返回按钮 */}
      <Card className={styles.backCard}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => {
            setCurrentView('list');
            setSelectedKB(null);
            setDocuments([]);
          }}
        >
          返回列表
        </Button>
      </Card>
      
      {/* 知识库信息 */}
      <Card
        title={
          <Space>
            <DatabaseOutlined style={{ fontSize: 20 }} />
            <span>{selectedKB?.name}</span>
            {getKBStatusTag(selectedKB?.chunk_count || 0)}
          </Space>
        }
        extra={
          <Space>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={() => setSearchTestModalVisible(true)}
            >
              检索测试
            </Button>
            <Button
              icon={<SettingOutlined />}
              onClick={async () => {
                if (selectedKB) {
                  await loadEmbeddingProviders(); // 重新加载 embedding 配置
                  setKbForm({
                    name: selectedKB.name,
                    description: selectedKB.description || '',
                    collection_name: selectedKB.collection_name,
                    vector_db: selectedKB.vector_db,
                    embedding_provider: selectedKB.embedding_config?.provider || 'local',
                    embedding_model: selectedKB.embedding_config?.model || '',
                    embedding_base_url: selectedKB.embedding_config?.base_url || '',
                    embedding_api_key: selectedKB.embedding_config?.api_key || '',
                    chunk_size: selectedKB.split_params.chunk_size,
                    chunk_overlap: selectedKB.split_params.chunk_overlap,
                    separators: selectedKB.split_params.separators.join('\n'),
                    distance_metric: selectedKB.search_params?.distance_metric || 'cosine',
                    similarity_threshold: selectedKB.search_params?.similarity_threshold || selectedKB.similarity_threshold,
                    top_k: selectedKB.search_params?.top_k || selectedKB.top_k,
                    // 智能分片配置
                    chunking_strategy: selectedKB.split_params.chunking_strategy || 'document_aware',
                    use_sentence_boundary: selectedKB.split_params.use_sentence_boundary ?? true,
                    semantic_threshold: selectedKB.split_params.semantic_threshold || 0.5,
                    preserve_structure: selectedKB.split_params.preserve_structure ?? true,
                    ast_parsing: selectedKB.split_params.ast_parsing ?? true,
                    enable_hierarchy: selectedKB.split_params.enable_hierarchy || false,
                    parent_chunk_size: selectedKB.split_params.parent_chunk_size || 4096,
                  });
                  setEditKBModalVisible(true);
                }
              }}
            >
              配置
            </Button>
          </Space>
        }
        className={styles.infoCard}
      >
        <Descriptions bordered column={{ xs: 1, sm: 2, md: 3 }}>
          <Descriptions.Item label="Collection">{selectedKB?.collection_name}</Descriptions.Item>
          <Descriptions.Item label="向量数据库">
            {selectedKB?.vector_db === 'chroma' && (
              <Tag color="blue" icon={<DatabaseOutlined />}>ChromaDB</Tag>
            )}
            {selectedKB?.vector_db === 'faiss' && (
              <Tag color="green" icon={<ThunderboltOutlined />}>FAISS</Tag>
            )}
            {selectedKB?.vector_db && selectedKB.vector_db !== 'chroma' && selectedKB.vector_db !== 'faiss' && (
              <Tag>{selectedKB.vector_db}</Tag>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Embedding服务商">{selectedKB?.embedding_config?.provider || '未知'}</Descriptions.Item>
          <Descriptions.Item label="Embedding模型">{selectedKB?.embedding_config?.model || '未知'}</Descriptions.Item>
          <Descriptions.Item label="分片大小">{selectedKB?.split_params.chunk_size}</Descriptions.Item>
          <Descriptions.Item label="分片重叠">{selectedKB?.split_params.chunk_overlap}</Descriptions.Item>
          <Descriptions.Item label="相似度阈值">{selectedKB?.search_params?.similarity_threshold || selectedKB?.similarity_threshold}</Descriptions.Item>
          <Descriptions.Item label="返回分片数">{selectedKB?.search_params?.top_k || selectedKB?.top_k}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{selectedKB && formatDate(selectedKB.created_at)}</Descriptions.Item>
          <Descriptions.Item label="描述" span={3}>{selectedKB?.description || '无'}</Descriptions.Item>
        </Descriptions>
      </Card>
      
      {/* 文档管理 */}
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>文档管理</span>
            <Badge count={documents.length} showZero />
          </Space>
        }
        extra={
          <Space>
            <Switch
              checkedChildren="自动刷新"
              unCheckedChildren="手动刷新"
              checked={autoRefresh}
              onChange={setAutoRefresh}
            />
            <Button
              icon={<ReloadOutlined />}
              onClick={() => selectedKB && loadDocuments(selectedKB.id, false, documentsPagination.current, documentsPagination.pageSize)}
            />
            <Button
              type="primary"
              icon={<UploadOutlined />}
              onClick={() => setUploadDocModalVisible(true)}
            >
              上传文档
            </Button>
          </Space>
        }
        className={styles.documentCard}
      >
        {/* 批量解析进度条 - 仅在批量解析时显示 */}
        {batchParsing && (
          <Alert
            message={
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Space size={16}>
                  <Text strong>
                    <SyncOutlined spin style={{ marginRight: 6 }} />
                    批量解析进行中
                  </Text>
                  <Tag color="processing" icon={<SyncOutlined spin />}>
                    解析中 {batchParseProgress.total - batchParseProgress.completed - batchParseProgress.failed}
                  </Tag>
                  {batchParseProgress.completed > 0 && (
                    <Tag color="success" icon={<CheckCircleOutlined />}>
                      已完成 {batchParseProgress.completed}
                    </Tag>
                  )}
                  {batchParseProgress.failed > 0 && (
                    <Tag color="error" icon={<ExclamationCircleOutlined />}>
                      失败 {batchParseProgress.failed}
                    </Tag>
                  )}
                </Space>
                <Progress 
                  percent={Math.round((batchParseProgress.completed / batchParseProgress.total) * 100)} 
                  status="active"
                  strokeColor={{
                    '0%': '#108ee9',
                    '100%': '#87d068',
                  }}
                  format={(percent) => `${percent}% (${batchParseProgress.completed}/${batchParseProgress.total})`}
                />
              </Space>
            }
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        {/* 筛选和操作栏 */}
        <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
          <Space wrap>
            <Search
              placeholder="搜索文档名称"
              allowClear
              style={{ width: 300 }}
              value={docSearchText}
              onChange={(e) => setDocSearchText(e.target.value)}
            />
            <Select
              value={docStatusFilter}
              onChange={setDocStatusFilter}
              style={{ width: 150 }}
            >
              <Option value="all">全部状态</Option>
              <Option value="uploaded">未解析</Option>
              <Option value="completed">解析成功</Option>
              <Option value="failed">解析失败</Option>
            </Select>
            <Select
              value={docFileTypeFilter}
              onChange={(value) => {
                setDocFileTypeFilter(value);
                // 切换文件类型时，重置知识图谱状态筛选
                if (value !== 'json') {
                  setDocKgStatusFilter('all');
                }
              }}
              style={{ width: 150 }}
              placeholder="文件类型"
            >
              <Option value="all">全部类型</Option>
              <Option value="json">JSON文件</Option>
              <Option value="pdf">PDF文件</Option>
              <Option value="txt">TXT文件</Option>
              <Option value="md">Markdown文件</Option>
              <Option value="doc">Word文档</Option>
              <Option value="docx">Word文档(新)</Option>
            </Select>
            
            {/* 知识图谱状态筛选 - 仅在选择JSON文件类型时显示 */}
            {docFileTypeFilter === 'json' && (
              <Select
                value={docKgStatusFilter}
                onChange={setDocKgStatusFilter}
                style={{ width: 160 }}
                placeholder="图谱状态"
              >
                <Option value="all">全部图谱状态</Option>
                <Option value="not_built">未构建</Option>
                <Option value="building">构建中</Option>
                <Option value="success">构建成功</Option>
                <Option value="failed">构建失败</Option>
              </Select>
            )}
          </Space>
          
          <Space>
            {/* 批量解析按钮 - 仅在筛选为"未解析"且有未解析文档时显示 */}
            {docStatusFilter === 'uploaded' && documents.filter(d => d.status === 'uploaded').length > 0 && (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleBatchParseDocuments}
                loading={batchParsing}
              >
                {batchParsing 
                  ? `解析中 (${batchParseProgress.completed}/${batchParseProgress.total})` 
                  : `解析全部 (${documents.filter(d => d.status === 'uploaded').length})`}
              </Button>
            )}
            
            {/* 🆕 解析总文档按钮 - 不受筛选和分页限制，始终显示 */}
            <Tooltip title="解析知识库中所有未解析的文档（不受当前筛选和分页限制）">
              <Button
                type="default"
                icon={<PlayCircleOutlined />}
                onClick={handleParseAllDocuments}
                style={{ borderColor: '#1890ff', color: '#1890ff' }}
              >
                解析总文档
              </Button>
            </Tooltip>
            
            {/* 批量创建知识图谱按钮 - 仅在筛选为JSON且有可构建的JSON文件时显示 */}
            {docFileTypeFilter === 'json' && (() => {
              // 统计可以构建知识图谱的JSON文件（未构建或失败的）
              const buildableJsonDocs = documents.filter(d => {
                const fileExt = d.filename.toLowerCase().split('.').pop() || '';
                const kgStatus = d.kg_status || 'not_built';
                return fileExt === 'json' && (kgStatus === 'not_built' || kgStatus === 'failed');
              });
              return buildableJsonDocs.length > 0 && (
                <Button
                  type="primary"
                  icon={<ShareAltOutlined />}
                  onClick={handleBatchCreateKnowledgeGraph}
                  loading={batchCreatingKG}
                  style={{ background: '#52c41a', borderColor: '#52c41a' }}
                >
                  {batchCreatingKG 
                    ? `提交中 (${kgCreationProgress.completed}/${kgCreationProgress.total})` 
                    : `创建知识图谱 (${buildableJsonDocs.length})`}
                </Button>
              );
            })()}
            
            {/* 🆕 创建总文档知识图谱按钮 - 不受筛选和分页限制，始终显示 */}
            <Tooltip title="为知识库中所有未创建图谱的JSON文档创建知识图谱（不受当前筛选和分页限制）">
              <Button
                type="default"
                icon={<ShareAltOutlined />}
                onClick={handleCreateAllKnowledgeGraphs}
                loading={batchCreatingKG}
                style={{ borderColor: '#52c41a', color: '#52c41a' }}
              >
                创建总文档图谱
              </Button>
            </Tooltip>
          </Space>
        </Space>
        
        {/* 批量创建知识图谱进度提示 */}
        {batchCreatingKG && (
          <Alert
            message="正在提交知识图谱构建任务"
            description={
              <div>
                <Progress 
                  percent={Math.round((kgCreationProgress.completed / kgCreationProgress.total) * 100)} 
                  status="active"
                  strokeColor="#52c41a"
                />
                <div style={{ marginTop: 8 }}>
                  已提交: {kgCreationProgress.completed}/{kgCreationProgress.total}
                  {kgCreationProgress.failed > 0 && `, 失败: ${kgCreationProgress.failed}`}
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: '#666' }}>
                  提示：任务已在后台处理，即使关闭页面也会继续执行...
                </div>
              </div>
            }
            type="success"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}
        
        <Table
          columns={docColumns}
          dataSource={filteredDocs}
          rowKey="id"
          loading={docLoading}
          scroll={{ x: 1200 }}
          pagination={{
            current: documentsPagination.current,
            pageSize: documentsPagination.pageSize,
            total: documentsPagination.total,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 个文档`,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: async (page, pageSize) => {
              if (selectedKB) {
                await loadDocuments(selectedKB.id, false, page, pageSize);
              }
            },
            onShowSizeChange: async (current, size) => {
              if (selectedKB) {
                await loadDocuments(selectedKB.id, false, current, size);
              }
            },
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无文档，点击上方【上传文档】按钮开始"
              />
            ),
          }}
        />
      </Card>
    </div>
  );
  
  // ==================== 主渲染 ====================
  
  return (
    <div className={styles.knowledgeBase}>
      <Layout className={styles.layout}>
        <Header className={styles.header}>
          <div className={styles.headerContent}>
            <Space size="large">
              <Space>
                <DatabaseOutlined style={{ fontSize: 24 }} />
                <Title level={3} style={{ margin: 0 }}>知识库管理</Title>
              </Space>
              <Tag color="blue">独立RAG引擎</Tag>
            </Space>
          </div>
        </Header>
        
        <Content className={styles.content}>
          {currentView === 'list' ? renderListView() : renderDetailView()}
        </Content>
      </Layout>
      
      {/* 创建知识库模态框 */}
      <Modal
        title={
          <Space>
            <DatabaseOutlined />
            <span>创建知识库</span>
          </Space>
        }
        open={createKBModalVisible}
        onOk={handleCreateKB}
        onCancel={() => {
          setCreateKBModalVisible(false);
          resetKbForm();
        }}
        width={800}
        okText="创建"
        cancelText="取消"
      >
        <Form layout="vertical" className={styles.kbForm}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="知识库名称" required>
                <Input
                  placeholder="请输入知识库名称"
                  value={kbForm.name}
                  onChange={(e) => setKbForm({ ...kbForm, name: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="Collection名称" required>
                <Input
                  placeholder="用于向量数据库的集合名称"
                  value={kbForm.collection_name}
                  onChange={(e) => setKbForm({ ...kbForm, collection_name: e.target.value })}
                />
              </Form.Item>
            </Col>
          </Row>
          
          <Form.Item label="描述">
            <Input.TextArea
              rows={3}
              placeholder="请输入知识库描述（可选）"
              value={kbForm.description}
              onChange={(e) => setKbForm({ ...kbForm, description: e.target.value })}
            />
          </Form.Item>
          
          <Divider>向量配置</Divider>
          
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="向量数据库">
                <Select
                  value={kbForm.vector_db}
                  onChange={(value) => setKbForm({ ...kbForm, vector_db: value })}
                  placeholder="选择向量数据库"
                >
                  <Option value="chroma">
                    <Space>
                      <DatabaseOutlined />
                      ChromaDB
                    </Space>
                  </Option>
                  <Option value="faiss">
                    <Space>
                      <ThunderboltOutlined />
                      FAISS
                    </Space>
                  </Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="Embedding服务商" required>
                <Select
                  placeholder="选择Embedding服务商"
                  value={kbForm.embedding_provider}
                  onChange={(value) => {
                const provider = embeddingProviders.find(p => p.id === value);
                if (provider) {
                  setKbForm({
                    ...kbForm,
                    embedding_provider: value,
                    embedding_model: provider.defaultModel,
                    embedding_base_url: provider.baseUrl || '',
                    embedding_api_key: provider.apiKey || '',
                  });
                }
                  }}
                >
                  {embeddingProviders.map(p => (
                    <Option key={p.id} value={p.id}>
                      {p.name}
                      {p.id === defaultEmbeddingProvider && <Tag color="blue" style={{ marginLeft: 8 }}>默认</Tag>}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="Embedding模型" required>
                <Select
                  placeholder="选择模型"
                  value={kbForm.embedding_model}
                  onChange={(value) => setKbForm({ ...kbForm, embedding_model: value })}
                  disabled={!kbForm.embedding_provider}
                >
                  {embeddingProviders
                    .find(p => p.id === kbForm.embedding_provider)
                    ?.models.map(m => (
                      <Option key={m} value={m}>{m}</Option>
                    ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          
          <Divider>分片配置</Divider>
          
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item 
                label="分片策略"
                tooltip="选择适合您文档类型的分片策略"
              >
                <Select
                  value={kbForm.chunking_strategy}
                  onChange={(value) => setKbForm({ ...kbForm, chunking_strategy: value })}
                  optionLabelProp="label"
                >
                  <Option value="document_aware" label="文档感知分片（推荐）">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>文档感知分片（推荐）</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        自动识别文档类型（JSON/代码/Markdown等），保持结构完整性
                      </div>
                    </div>
                  </Option>
                  <Option value="semantic" label="语义分片">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>语义分片</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        基于句子边界和语义相似度，保持语义连贯性
                      </div>
                    </div>
                  </Option>
                  <Option value="simple" label="简单分片">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>简单分片</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        基于分隔符的传统方法，适合简单文本
                      </div>
                    </div>
                  </Option>
                  <Option value="hierarchical" label="层级分片">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>层级分片</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        创建父子分片关系，提供多层次上下文
                      </div>
                    </div>
                  </Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          
          {(kbForm.chunking_strategy === 'document_aware' || kbForm.chunking_strategy === 'semantic') && (
            <Alert
              message="智能分片特性"
              description={
                <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                  {kbForm.chunking_strategy === 'document_aware' && (
                    <>
                      <li>JSON文件：保持对象/数组完整性</li>
                      <li>代码文件：按函数/类边界分片，保留import上下文</li>
                      <li>Markdown：按标题层级分片</li>
                      <li>自动降级：无法识别时使用语义分片</li>
                    </>
                  )}
                  {kbForm.chunking_strategy === 'semantic' && (
                    <>
                      <li>智能句子边界检测（中英文）</li>
                      <li>保持语义连贯性</li>
                      <li>避免在句子中间截断</li>
                    </>
                  )}
                </ul>
              }
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
          )}
          
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="分片大小">
                <InputNumber
                  min={100}
                  step={50}
                  style={{ width: '100%' }}
                  value={kbForm.chunk_size}
                  onChange={(value) => setKbForm({ ...kbForm, chunk_size: value || 2048 })}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="分片重叠">
                <InputNumber
                  min={0}
                  max={2000}
                  step={10}
                  style={{ width: '100%' }}
                  value={kbForm.chunk_overlap}
                  onChange={(value) => setKbForm({ ...kbForm, chunk_overlap: value || 100 })}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="返回分片数">
                <InputNumber
                  min={1}
                  max={20}
                  style={{ width: '100%' }}
                  value={kbForm.top_k}
                  onChange={(value) => setKbForm({ ...kbForm, top_k: value || 5 })}
                />
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item 
                label="匹配算法"
                tooltip="不同的算法适用于不同的检索场景，创建后不可修改"
              >
                <Select
                  style={{ width: '100%' }}
                  value={kbForm.distance_metric}
                  onChange={(value) => {
                    // 切换算法时保持统一的相似度阈值（后端已统一转换为0-1分数）
                    setKbForm({ 
                      ...kbForm, 
                      distance_metric: value,
                      // 保持当前阈值，因为现在所有距离度量都使用统一的0-1相似度分数
                    });
                  }}
                >
                  <Option value="cosine">
                    <Tooltip title="推荐用于文本检索、问答系统。计算语义方向的相似度，数值越小表示内容越相关。">
                      余弦匹配（推荐文本检索）
                    </Tooltip>
                  </Option>
                  <Option value="l2">
                    <Tooltip title="适合图像检索或需要精确匹配的场景。计算向量之间的直线距离，数值越小表示越相似。">
                      欧氏距离（推荐图像检索）
                    </Tooltip>
                  </Option>
                  <Option value="ip">
                    <Tooltip title="适合已归一化的向量数据。计算内积相关性，数值越小表示越相关（ChromaDB使用负内积）。">
                      内积匹配（高级用法）
                    </Tooltip>
                  </Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item 
                label="相似度阈值"
                tooltip="相似度越小，越容易检索到内容，推荐0.3"
              >
                <InputNumber
                  min={0}
                  max={1}
                  step={0.05}
                  style={{ width: '100%' }}
                  value={kbForm.similarity_threshold}
                  onChange={(value) => {
                    setKbForm({ ...kbForm, similarity_threshold: value ?? 0.3 });
                  }}
                />
              </Form.Item>
            </Col>
          </Row>
          
          {/* 只有简单分片和层级分片需要配置分隔符 */}
          {(kbForm.chunking_strategy === 'simple' || kbForm.chunking_strategy === 'hierarchical') && (
            <Row gutter={16}>
              <Col span={24}>
                <Form.Item
                  label="文本分隔符"
                  tooltip="每行一个分隔符，支持转义字符（如 \n 表示换行）"
                >
                  <Input.TextArea
                    rows={4}
                    placeholder="\\n\\n&#10;\\n&#10;。&#10;！&#10;？&#10;，&#10; "
                    value={kbForm.separators}
                    onChange={(e) => setKbForm({ ...kbForm, separators: e.target.value })}
                  />
                </Form.Item>
              </Col>
            </Row>
          )}
        </Form>
      </Modal>
      
      {/* 编辑知识库模态框 */}
      <Modal
        title={
          <Space>
            <EditOutlined />
            <span>编辑知识库配置</span>
          </Space>
        }
        open={editKBModalVisible}
        onOk={handleUpdateKB}
        onCancel={() => setEditKBModalVisible(false)}
        width={800}
        okText="保存"
        cancelText="取消"
      >
        <Alert
          message="配置说明"
          description="匹配算法在创建后不可修改（向量索引结构依赖此配置）。其他配置可以修改，新配置将应用于后续上传的文档。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Form layout="vertical" className={styles.kbForm}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="知识库名称">
                <Input
                  value={kbForm.name}
                  onChange={(e) => setKbForm({ ...kbForm, name: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="Collection名称">
                <Input value={kbForm.collection_name} disabled />
              </Form.Item>
            </Col>
          </Row>
          
          <Form.Item label="描述">
            <Input.TextArea
              rows={3}
              value={kbForm.description}
              onChange={(e) => setKbForm({ ...kbForm, description: e.target.value })}
            />
          </Form.Item>
          
          <Divider>分片配置</Divider>
          
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item 
                label="分片策略"
                tooltip="选择适合您文档类型的分片策略，修改后将应用于后续上传的文档"
              >
                <Select
                  value={kbForm.chunking_strategy}
                  onChange={(value) => setKbForm({ ...kbForm, chunking_strategy: value })}
                  optionLabelProp="label"
                >
                  <Option value="document_aware" label="文档感知分片（推荐）">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>文档感知分片（推荐）</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        自动识别文档类型（JSON/代码/Markdown等），保持结构完整性
                      </div>
                    </div>
                  </Option>
                  <Option value="semantic" label="语义分片">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>语义分片</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        基于句子边界和语义相似度，保持语义连贯性
                      </div>
                    </div>
                  </Option>
                  <Option value="simple" label="简单分片">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>简单分片</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        基于分隔符的传统方法，适合简单文本
                      </div>
                    </div>
                  </Option>
                  <Option value="hierarchical" label="层级分片">
                    <div>
                      <div style={{ fontWeight: 'bold' }}>层级分片</div>
                      <div style={{ fontSize: 12, color: '#888' }}>
                        创建父子分片关系，提供多层次上下文
                      </div>
                    </div>
                  </Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          
          {(kbForm.chunking_strategy === 'document_aware' || kbForm.chunking_strategy === 'semantic') && (
            <Alert
              message="智能分片特性"
              description={
                <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                  {kbForm.chunking_strategy === 'document_aware' && (
                    <>
                      <li>JSON文件：保持对象/数组完整性</li>
                      <li>代码文件：按函数/类边界分片，保留import上下文</li>
                      <li>Markdown：按标题层级分片</li>
                      <li>自动降级：无法识别时使用语义分片</li>
                    </>
                  )}
                  {kbForm.chunking_strategy === 'semantic' && (
                    <>
                      <li>智能句子边界检测（中英文）</li>
                      <li>保持语义连贯性</li>
                      <li>避免在句子中间截断</li>
                    </>
                  )}
                </ul>
              }
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
          )}
          
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="分片大小">
                <InputNumber
                  min={100}
                  step={50}
                  style={{ width: '100%' }}
                  value={kbForm.chunk_size}
                  onChange={(value) => setKbForm({ ...kbForm, chunk_size: value || 2048 })}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="分片重叠">
                <InputNumber
                  min={0}
                  max={2000}
                  step={10}
                  style={{ width: '100%' }}
                  value={kbForm.chunk_overlap}
                  onChange={(value) => setKbForm({ ...kbForm, chunk_overlap: value || 100 })}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="返回分片数">
                <InputNumber
                  min={1}
                  max={20}
                  style={{ width: '100%' }}
                  value={kbForm.top_k}
                  onChange={(value) => setKbForm({ ...kbForm, top_k: value || 5 })}
                />
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item 
                label="匹配算法"
                tooltip="创建后不可修改，因为向量索引结构依赖此配置"
              >
                <Input
                  disabled
                  style={{ width: '100%' }}
                  value={
                    kbForm.distance_metric === 'cosine' ? '余弦匹配 - 文本语义检索' :
                    kbForm.distance_metric === 'l2' ? '欧氏距离 - 图像/精确匹配' :
                    kbForm.distance_metric === 'ip' ? '内积匹配 - 归一化向量' :
                    kbForm.distance_metric
                  }
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item 
                label="相似度阈值"
                tooltip="相似度越小，越容易检索到内容，推荐0.3"
              >
                <InputNumber
                  min={0}
                  max={1}
                  step={0.05}
                  style={{ width: '100%' }}
                  value={kbForm.similarity_threshold}
                  onChange={(value) => {
                    setKbForm({ ...kbForm, similarity_threshold: value ?? 0.3 });
                  }}
                />
              </Form.Item>
            </Col>
          </Row>
          
          {/* 只有简单分片和层级分片需要配置分隔符 */}
          {(kbForm.chunking_strategy === 'simple' || kbForm.chunking_strategy === 'hierarchical') && (
            <Row gutter={16}>
              <Col span={24}>
                <Form.Item
                  label="文本分隔符"
                  tooltip="每行一个分隔符，支持转义字符（如 \n 表示换行）"
                >
                  <Input.TextArea
                    rows={4}
                    placeholder="\\n\\n&#10;\\n&#10;。&#10;！&#10;？&#10;，&#10; "
                    value={kbForm.separators}
                    onChange={(e) => setKbForm({ ...kbForm, separators: e.target.value })}
                  />
                </Form.Item>
              </Col>
            </Row>
          )}
        </Form>
      </Modal>
      
      {/* 上传文档模态框 */}
      <Modal
        title="上传文档"
        open={uploadDocModalVisible}
        onOk={handleUploadDocuments}
        onCancel={() => {
          setUploadDocModalVisible(false);
          setUploadFileList([]);
        }}
        width={600}
        okText="开始上传"
        cancelText="取消"
        confirmLoading={batchUploading}
        okButtonProps={{ disabled: uploadFileList.length === 0 || batchUploading }}
      >
        <Alert
          message="上传说明"
          description={
            <div>
              <div>支持单次或批量上传；可选择文件夹或多选文件；拖拽可同时支持文件与文件夹。</div>
              <div>系统支持文本、代码、图片等多种格式；自动过滤不支持的文件类型。</div>
              <div>大量文件将自动排队分批上传，并显示进度。</div>
            </div>
          }
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
        />
        <Form layout="vertical">
          <div style={{ marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#ff4d4f' }}>*</span>
            <Text style={{ margin: 0 }}>目标知识库</Text>
            <Text type="secondary">{selectedKB?.name || '-'}</Text>
          </div>

          <div
            className={`kb-dragger-has-scroll${uploadFileList.length > 0 ? ' kb-has-files' : ''}${isDragOver ? ' kb-drag-active' : ''}`}
            onDragEnter={() => setIsDragOver(true)}
            onDragOverCapture={(ev: React.DragEvent<HTMLDivElement>) => { ev.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDropCapture={handleDrop as any}
          >
            <Dragger
              multiple
              fileList={uploadFileList.slice(0, 20)}
              onChange={handleUploadChange}
              beforeUpload={() => false}
              disabled={batchUploading}
              accept={[
                // 文本文档
                '.txt','.pdf','.doc','.docx','.md','.markdown','.html','.htm','.json','.csv','.xlsx','.xls','.ppt','.pptx','.rtf','.odt','.epub','.tex','.log','.rst','.org',
                // 代码与配置
                '.py','.js','.jsx','.ts','.tsx','.java','.kt','.kts','.scala','.go','.rs','.rb','.php','.cs','.cpp','.cc','.cxx','.c','.h','.hpp','.m','.mm','.swift','.dart','.lua','.pl','.pm','.r','.jl','.sql','.sh','.bash','.zsh','.ps1','.psm1','.bat','.cmd','.vb','.vbs','.groovy','.gradle','.make','.mk','.cmake','.toml','.yaml','.yml','.ini','.cfg','.conf','.properties','.env','.editorconfig','.dockerfile','.gql','.graphql','.svelte','.vue',
                // 图片
                '.png','.jpg','.jpeg','.gif','.bmp','.tiff','.tif','.webp','.svg','.ico','.heic'
              ].join(',')}
              showUploadList={{ showRemoveIcon: true }}
            >
              <p className="ant-upload-drag-icon">
                <UploadOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
              <p className="ant-upload-hint">
                支持单个或批量上传；拖拽时文件与文件夹均可识别。
              </p>
            </Dragger>
          </div>

          {uploadFileList.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Text type="secondary" style={{ margin: 0, fontSize: 12 }}>
                  待上传文件 ({uploadFileList.length}){uploadFileList.length > 20 && ' - 仅显示前20个'}
                </Text>
                {processingSelection && (
                  <Text type="secondary" style={{ margin: 0, fontSize: 12 }}>
                    <SyncOutlined spin style={{ marginRight: 4 }} />
                    正在处理文件列表...
                  </Text>
                )}
              </div>
              {uploadFileList.length > 20 && (
                <Alert
                  message={`已选择 ${uploadFileList.length} 个文件，列表仅显示前 20 个。点击"开始上传"将上传所有文件。`}
                  type="info"
                  showIcon
                  style={{ marginTop: 8, fontSize: 12 }}
                />
              )}
            </div>
          )}

          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <Upload
              multiple
              directory={false}
              fileList={[]}
              onChange={handleUploadChange}
              beforeUpload={() => false}
              showUploadList={false}
              accept={[
                '.txt','.pdf','.doc','.docx','.md','.markdown','.html','.htm','.json','.csv','.xlsx','.xls','.ppt','.pptx','.rtf','.odt','.epub','.tex','.log','.rst','.org',
                '.py','.js','.jsx','.ts','.tsx','.java','.kt','.kts','.scala','.go','.rs','.rb','.php','.cs','.cpp','.cc','.cxx','.c','.h','.hpp','.m','.mm','.swift','.dart','.lua','.pl','.pm','.r','.jl','.sql','.sh','.bash','.zsh','.ps1','.psm1','.bat','.cmd','.vb','.vbs','.groovy','.gradle','.make','.mk','.cmake','.toml','.yaml','.yml','.ini','.cfg','.conf','.properties','.env','.editorconfig','.dockerfile','.gql','.graphql','.svelte','.vue',
                '.png','.jpg','.jpeg','.gif','.bmp','.tiff','.tif','.webp','.svg','.ico','.heic'
              ].join(',')}
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
            <Upload
              multiple
              directory={true}
              fileList={[]}
              onChange={handleUploadChange}
              beforeUpload={() => false}
              showUploadList={false}
            >
              <Button icon={<UploadOutlined />}>选择文件夹</Button>
            </Upload>
          </div>

          <style>{`
            .kb-dragger-has-scroll .ant-upload-list {
              max-height: 320px;
              overflow: auto;
              margin-top: 4px;
            }
            .kb-drag-active {
              transition: all 0.15s ease-in-out;
            }
            .kb-drag-active .ant-upload.ant-upload-drag {
              border-color: #1677ff !important;
              background: rgba(22, 119, 255, 0.04);
              box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.15) inset;
            }
            .kb-drag-active .ant-upload.ant-upload-drag .ant-upload-drag-container .ant-upload-text {
              color: #1677ff;
            }
          `}</style>

          {queueState.enabled && (
            <div style={{ marginTop: 16 }}>
              <Title level={5}>上传进度</Title>
              <div style={{ marginBottom: 8 }}>
                批次 {queueState.currentBatch}/{queueState.totalBatches}，
                文件 {queueState.uploadedFiles}/{queueState.totalFiles}
              </div>
              <Progress percent={queueState.percent} status={batchUploading ? 'active' : undefined} />
              <Text type="secondary">
                {formatFileSize(queueState.uploadedBytes)} / {formatFileSize(queueState.totalBytes)}
              </Text>
            </div>
          )}
        </Form>
      </Modal>
      
      {/* 检索测试模态框 */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined />
            <span>知识库检索测试</span>
          </Space>
        }
        open={searchTestModalVisible}
        onCancel={() => {
          setSearchTestModalVisible(false);
          setSearchQuery('');
          setSearchResults([]);
        }}
        width={900}
        footer={null}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Search
            placeholder="输入检索内容..."
            enterButton={<Button type="primary" icon={<SearchOutlined />}>检索</Button>}
            size="large"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onSearch={handleSearchTest}
            loading={searching}
          />
          
          {searchResults.length > 0 && (
            <Alert
              message={`找到 ${searchResults.length} 条相关结果`}
              type="success"
              showIcon
            />
          )}
          
          <List
            loading={searching}
            dataSource={searchResults}
            locale={{
              emptyText: <Empty description="暂无检索结果，请输入内容进行检索" />
            }}
            renderItem={(item, index) => (
              <List.Item key={item.chunk_id}>
                <Card
                  size="small"
                  style={{ width: '100%' }}
                  title={
                    <Space>
                      <Badge count={index + 1} style={{ backgroundColor: '#1890ff' }} />
                      <Text>相似度分数: {item.score?.toFixed(4) || 'N/A'}</Text>
                      <Tag color="blue">
                        {(selectedKB?.search_params?.distance_metric || 'cosine') === 'cosine' ? '余弦距离' : 
                         (selectedKB?.search_params?.distance_metric || 'cosine') === 'l2' ? 'L2距离' : 
                         '内积距离'}: {item.distance?.toFixed(4) || 'N/A'}
                      </Tag>
                    </Space>
                  }
                >
                  <Paragraph ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>
                    {item.content}
                  </Paragraph>
                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      来源: {item.document_name || '未知文档'}
                    </Text>
                  </div>
                </Card>
              </List.Item>
            )}
          />
        </Space>
      </Modal>
      
      {/* 查看分片模态框 */}
      <Modal
        title={
          <Space>
            <FileTextOutlined />
            <span>文档分片</span>
            {selectedDocument && (
              <>
                <Divider type="vertical" />
                <Text type="secondary" style={{ fontSize: 14 }}>
                  {selectedDocument.filename}
                </Text>
                <Tag color="green">{selectedDocument.chunk_count} 个分片</Tag>
              </>
            )}
          </Space>
        }
        open={chunksModalVisible}
        onCancel={() => {
          setChunksModalVisible(false);
          setSelectedDocument(null);
          setChunks([]);
          setChunksPagination({ current: 1, pageSize: 20, total: 0 });
        }}
        width={1000}
        footer={null}
        className={styles.chunksModal}
      >
        <div className={styles.chunksContainer}>
          {selectedDocument && (
            <Alert
              message="文档信息"
              description={
                <Space direction="vertical" size="small">
                  <Text>文件名: {selectedDocument.filename}</Text>
                  <Text>文件类型: {selectedDocument.file_type.toUpperCase()}</Text>
                  <Text>文件大小: {formatFileSize(selectedDocument.file_size)}</Text>
                  <Text>分片总数: {selectedDocument.chunk_count}</Text>
                </Space>
              }
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
          )}
          
          <List
            loading={chunksLoading}
            dataSource={chunks}
            locale={{
              emptyText: <Empty description="该文档暂无分片" />
            }}
            pagination={{
              current: chunksPagination.current,
              pageSize: chunksPagination.pageSize,
              total: chunksPagination.total,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 个分片`,
              onChange: async (page, pageSize) => {
                if (selectedKB && selectedDocument) {
                  await loadChunks(selectedKB.id, selectedDocument.id, page, pageSize);
                }
              },
              pageSizeOptions: ['10', '20', '50', '100'],
            }}
            renderItem={(chunk) => (
              <List.Item key={chunk.id} className={styles.chunkItem}>
                <Card
                  size="small"
                  className={styles.chunkCard}
                  title={
                    <Space>
                      <Badge 
                        count={chunk.chunk_index} 
                        style={{ 
                          backgroundColor: '#52c41a',
                          fontSize: 12,
                          height: 20,
                          lineHeight: '20px',
                        }} 
                      />
                      <Text strong>分片 #{chunk.chunk_index}</Text>
                      <Divider type="vertical" />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        ID: {chunk.id.substring(0, 8)}...
                      </Text>
                    </Space>
                  }
                  extra={
                    <Tag color="blue">
                      长度: {chunk.content.length} 字符
                    </Tag>
                  }
                >
                  <div className={styles.chunkContent}>
                    <Paragraph
                      ellipsis={{
                        rows: 5,
                        expandable: true,
                        symbol: '展开',
                      }}
                      style={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        marginBottom: 0,
                      }}
                    >
                      {chunk.content}
                    </Paragraph>
                  </div>
                  
                  {chunk.metadata && Object.keys(chunk.metadata).length > 0 && (
                    <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-color)' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        元数据:
                      </Text>
                      <div style={{ marginTop: 4 }}>
                        {Object.entries(chunk.metadata).map(([key, value]) => (
                          <Tag key={key} style={{ marginBottom: 4 }}>
                            {key}: {String(value)}
                          </Tag>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              </List.Item>
            )}
          />
        </div>
      </Modal>
    </div>
  );
};

export default KnowledgeBase;

