import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Layout, Select, Switch, Input, Button, message, Collapse, Tooltip, Dropdown, Modal, InputNumber, Slider, Checkbox, Tag, Alert, theme as antdTheme, DatePicker, Form, Tabs, List, Avatar, Popconfirm, Spin } from 'antd';
import { Upload } from 'antd';
import dayjs from 'dayjs';
import ReactMarkdown from 'react-markdown';
import * as JsonViewer from '@uiw/react-json-view';
import hljs from 'highlight.js';
// 不在这里静态导入样式，而是在组件中动态加载
import { 
  SendOutlined, 
  UserOutlined, 
  FileTextOutlined,
  RobotOutlined,
  SoundOutlined,
  ApiOutlined,
  GlobalOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
  MenuOutlined,
  PlusOutlined,
  AudioOutlined,
  QuestionCircleOutlined,
  PhoneOutlined,
  AppstoreOutlined,
  CopyOutlined,
  DownOutlined,
  UpOutlined,
  PictureOutlined,
  ExclamationCircleOutlined,
  SearchOutlined,
  DownloadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  CloseOutlined,
  DatabaseOutlined,
  RightOutlined,
  CompressOutlined,
  SettingOutlined,
  BgColorsOutlined,
  HeartOutlined,
  TeamOutlined,
  UsergroupAddOutlined,
  UserAddOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  CrownOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SwapOutlined,
  NodeIndexOutlined,
} from '@ant-design/icons';
import styles from './Chat.module.css';
import { useChatStore } from '../../stores/chatStore';
import type { ChatSession } from '../../stores/chatStore';
import { useThemeStore } from '../../stores/themeStore';
import { useAuthStore } from '../../stores/authStore';
import { useGroupChatStore } from '../../stores/groupChatStore';
import type { Group, GroupMessage } from '../../stores/groupChatStore';
import { useLazyLoadMessages } from './useLazyLoadMessages';
import { useScrollLoader } from './useScrollLoader';
import { useSmartRecorder } from '../../hooks/useSmartRecorder';
import { useDocumentUpload } from '../../hooks/useDocumentUpload';
import { useAudioQueue } from '../../hooks/useAudioQueue';
import { getFullUrl, buildFullUrl } from '../../config';
import { useNavigate } from 'react-router-dom';
import AvatarCropper from '../../components/AvatarCropper';
import { VADStatus, type VADStatusType } from '../../components/VADStatus';
import ThemeToggle from '../../components/ThemeToggle';
import ImageCompressor from '../../components/ImageCompressor';
import ToolConfigPanel from '../../components/chat/ToolConfigPanel';
import GroupStrategyConfigModal from '../../components/GroupStrategyConfig';
import authAxios from '../../utils/authAxios';
import api from '../../utils/api';
// 导入logo图片
import deepseekLogo from '../../static/logo/deepseek.png';
import doubaoLogo from '../../static/logo/doubao.png';
import bailianLogo from '../../static/logo/bailian.png';
import siliconflowLogo from '../../static/logo/siliconflow.png';
import zhipuLogo from '../../static/logo/zhipu.png';
import hunyuanLogo from '../../static/logo/hunyuan.png';
import moonshotLogo from '../../static/logo/moonshot_dark.png';
import moonshotWhiteLogo from '../../static/logo/moonshot.png';
import stepfunLogo from '../../static/logo/stepfun.png';
import chatWSManager from '../../utils/ChatWSManager';
import ollamaLogo from '../../static/logo/ollama_dark.png';
import ollamaWhiteLogo from '../../static/logo/ollama.png';
import huoshanLogo from '../../static/logo/huoshan.png';
import localsLogo from '../../static/logo/locals.png';
import chromaLogo from '../../static/logo/chroma.png';
import defaultAvatar from '../../static/avatar/default-avatar.png';
import bytedanceVoicesData from './byteDance_tts.json';
import xfyunVoicesData from './xfyun_tts.json';
import defaultModelAvatar from '../../static/avatar/default-avatar-model.png';
import modelsConfigData from '../ModelConfig/models_config.json';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';

// 从配置文件中提取参数定义和默认参数
const paramDefinitions = (modelsConfigData as any).paramDefinitions;
const defaultParams = (modelsConfigData as any).defaultParams;

const { Sider } = Layout;
const { Option } = Select;
const { Panel } = Collapse;


interface ModelSettings {
  modelService: string;
  baseUrl: string;
  apiKey: string;
  modelName: string;
  modelParams?: Record<string, any>;
}

// 🆕 知识图谱元数据接口
export interface GraphMetadata {
  graph_id: string;
  tool_name: string;
  query: string;
  node_count: number;
  edge_count: number;
  created_at: string;
  nodes: Array<{
    id: string;
    label: string;
    properties: Record<string, any>;
  }>;
  edges: Array<{
    source: string;
    target: string;
    relation: string;
    properties?: Record<string, any>;
  }>;
}

// 消息接口
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  images?: string[];
  reference?: any[];
  graph_metadata?: GraphMetadata[]; // 🆕 图谱可视化数据
  id?: string;
  create_time?: string;
  sender_id?: string; // 用于群聊中查找发送者头像
  sender_name?: string; // 发送者名称
}

// 自定义模型类型定义
interface CustomModel {
  id: string;
  displayName: string;
  supportsImage: boolean;
}

// 从后端获取所有已启用的服务商配置
const fetchEnabledProviders = async (): Promise<Array<{ id: string; name: string; baseUrl: string; apiKey: string; models: string[]; customModels?: CustomModel[] }>> => {
  try {
    const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
    const token = authState.state?.token;
    
    if (!token) {
      console.error('[Chat] 没有找到认证token');
      return [];
    }

    const response = await fetch('/api/model-config', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      console.error('[Chat] 获取模型配置失败');
      return [];
    }

    const data = await response.json();
    const modelConfigs = data.model_configs || {};
    
    const enabledProviders = Object.entries(modelConfigs)
      .filter(([_, config]: any) => config.enabled)
      .map(([id, config]: any) => {
        const customModels = config.custom_models || [];
        const baseModels = config.models || [];
        
        // 将自定义模型的 ID 合并到模型列表中
        const customModelIds = customModels.map((cm: any) => cm.id);
        const allModels = [...baseModels, ...customModelIds];
        
        return {
          id,
          name: config.name || id,
          baseUrl: config.base_url,
          apiKey: config.api_key,
          models: allModels,
          customModels: customModels
        };
      });
    
    return enabledProviders;
  } catch (error) {
    console.error('[Chat] 获取已启用服务商配置时出错:', error);
    return [];
  }
};

// 从后端获取所有已启用的 Embedding 服务商配置
const fetchEnabledEmbeddingProviders = async (): Promise<Array<{ id: string; name: string; baseUrl: string; apiKey: string; models: string[]; defaultModel: string }>> => {
  try {
    const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
    const token = authState.state?.token;
    
    if (!token) {
      console.error('[Chat] 没有找到认证token');
      return [];
    }

    const response = await fetch('/api/embedding-config/user', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      console.error('[Chat] 获取Embedding配置失败');
      return [];
    }

    const data = await response.json();
    if (!data.success || !data.configs) {
      console.error('[Chat] Embedding配置数据格式错误');
      return [];
    }
    
    const embeddingConfigs = data.configs;
    
    const enabledEmbeddingProviders = Object.entries(embeddingConfigs)
      .filter(([_, config]: any) => config.enabled)
      .map(([id, config]: any) => ({
        id,
        name: config.name || id,
        baseUrl: config.base_url || '',
        apiKey: config.api_key || '',
        models: config.models || [],
        defaultModel: config.default_model || ''
      }));
    
    return enabledEmbeddingProviders;
  } catch (error) {
    console.error('[Chat] 获取已启用Embedding服务商配置时出错:', error);
    return [];
  }
};

// 获取默认的 Embedding 服务商
const fetchDefaultEmbeddingProvider = async (): Promise<string | null> => {
  try {
    const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
    const token = authState.state?.token;
    
    if (!token) {
      console.error('[Chat] 没有找到认证token');
      return null;
    }

    const response = await fetch('/api/embedding-config/default', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      console.error('[Chat] 获取默认Embedding配置失败');
      return null;
    }

    const data = await response.json();
    if (data.success && data.provider_id) {
      return data.provider_id;
    }
    
    return null;
  } catch (error) {
    console.error('[Chat] 获取默认Embedding服务商时出错:', error);
    return null;
  }
};

// 🆕 获取用户的知识库列表
const fetchKnowledgeBaseList = async (): Promise<any[]> => {
  try {
    const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
    const token = authState.state?.token;
    
    if (!token) {
      console.error('[Chat] 没有找到认证token');
      return [];
    }

    const response = await fetch('/api/kb/list?include_pulled=true', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      console.error('[Chat] 获取知识库列表失败');
      return [];
    }

    const data = await response.json();
    if (data.success && data.knowledge_bases) {
      console.log('[Chat] 成功获取知识库列表:', data.knowledge_bases.length, '个');
      return data.knowledge_bases;
    }
    
    return [];
  } catch (error) {
    console.error('[Chat] 获取知识库列表时出错:', error);
    return [];
  }
};

// 模型服务配置 - 根据主题动态返回不同图标
const getModelServices = (isDarkTheme: boolean) => [
  { value: 'deepseek', label: 'DeepSeek', logo: deepseekLogo },
  { value: 'doubao', label: '豆包', logo: doubaoLogo },
  { value: 'bailian', label: '通义千问', logo: bailianLogo },
  { value: 'siliconflow', label: '硅基流动', logo: siliconflowLogo },
  { value: 'zhipu', label: '智谱AI', logo: zhipuLogo },
  { value: 'hunyuan', label: '腾讯混元', logo: hunyuanLogo },
  { value: 'moonshot', label: 'Moonshot', logo: isDarkTheme ? moonshotWhiteLogo : moonshotLogo },
  { value: 'stepfun', label: 'StepFun', logo: stepfunLogo },
  { value: 'ollama', label: 'Ollama', logo: isDarkTheme ? ollamaWhiteLogo : ollamaLogo },
] as const;

// Embedding 服务配置 - 根据主题动态返回不同图标
const getEmbeddingServices = (isDarkTheme: boolean) => [
  { value: 'ark', label: '火山引擎（豆包）', logo: huoshanLogo },
  { value: 'ollama', label: 'Ollama', logo: isDarkTheme ? ollamaWhiteLogo : ollamaLogo },
  { value: 'local', label: '本地模型', logo: localsLogo },
] as const;

// 从JSON配置中获取模型信息的辅助函数
const getModelInfoFromConfig = (providerId: string, modelValue: string) => {
  const providerConfig = (modelsConfigData as any).providers[providerId];
  if (!providerConfig || !providerConfig.models) {
    return null;
  }
  return providerConfig.models.find((m: any) => m.value === modelValue);
};

// 获取模型的参数配置（合并 paramDefinitions 和具体参数值）
const getModelParamsSchema = (modelService: string, modelName: string): any[] => {
  // 从配置中查找模型的参数配置
  const providerConfig = (modelsConfigData as any).providers[modelService];
  if (!providerConfig) {
    return [];
  }
  
  // 查找模型对象
  const modelConfig = providerConfig.models?.find((m: any) => m.value === modelName);
  
  // 使用模型自定义的params，如果没有则使用全局defaultParams
  const paramsConfig = modelConfig?.params || defaultParams;
  
  // 合并 paramDefinitions 中的 label、description、type
  return paramsConfig.map((param: any) => {
    const definition = paramDefinitions[param.key] || {};
    return {
      ...param,
      label: definition.label || param.key,
      description: definition.description || '',
      type: definition.type || param.type || 'number',
      mapTo: param.key // 直接映射到同名参数
    };
  });
};

// 获取模型的默认参数值
const getModelDefaultParams = (modelService: string, modelName: string): Record<string, any> => {
  const schema = getModelParamsSchema(modelService, modelName);
  
  const result: Record<string, any> = {};
  schema.forEach((param: any) => {
    result[param.key] = param.default;
  });
  
  console.log(`📋 获取模型默认参数 [${modelService}/${modelName}]:`, result);
  
  return result;
};

// 将MinIO URL转换为HTTP API URL（移到组件外部以便复用）
const convertMinioUrlToHttp = (minioUrl: string): string => {
  try {
    if (!minioUrl || !minioUrl.startsWith('minio://')) {
      return minioUrl;
    }
    
    // 解析 minio://bucket/path/to/file.jpg
    const urlParts = minioUrl.replace('minio://', '').split('/');
    if (urlParts.length < 2) {
      return minioUrl;
    }
    
    const pathParts = urlParts.slice(1); // 去掉 bucket 名称
    
    // 用户头像：users/{userId}/avatar/{filename}
    if (pathParts.length === 4 && pathParts[0] === 'users' && pathParts[2] === 'avatar') {
      return buildFullUrl(`/api/auth/avatar/${pathParts[1]}/${pathParts[3]}`);
    }
    
    // 传统会话角色头像：users/{userId}/sessions/{sessionId}/role_avatar/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'role_avatar') {
      return buildFullUrl(`/api/auth/role-avatar/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }
    
    // 传统会话背景图：users/{userId}/sessions/{sessionId}/role_background/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'role_background') {
      return buildFullUrl(`/api/auth/role-background/${pathParts[3]}`);
    }
    
    // 传统会话消息图片：users/{userId}/sessions/{sessionId}/message_image/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'message_image') {
      return buildFullUrl(`/api/auth/message-image/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }
    
    // 新格式会话消息图片：users/{userId}/{sessionId}/{messageId}/{filename}
    if (pathParts.length === 5 && pathParts[0] === 'users') {
      return buildFullUrl(`/api/auth/new-message-image/${pathParts[1]}/${pathParts[2]}/${pathParts[3]}/${pathParts[4]}`);
    }
    
    // 群聊头像：group-chats/{groupId}/{filename}
    if (pathParts.length === 3 && pathParts[0] === 'group-chats') {
      return buildFullUrl(`/api/auth/group-avatar/${pathParts[1]}/${pathParts[2]}`);
    }
    
    return minioUrl; // 如果解析失败，返回原URL
  } catch (error) {
    console.error('转换MinIO URL失败:', error);
    return minioUrl; // 出错时返回原URL
  }
};

const Chat: React.FC = () => {
  const { token } = antdTheme.useToken();
  const navigate = useNavigate();
  const [deletingAccount, setDeletingAccount] = useState(false);
  // 状态管理
  const [enableVoice, setEnableVoice] = useState(() => {
    const saved = localStorage.getItem('enableVoice');
    return saved !== null ? JSON.parse(saved) : false;  // 默认为false
  });
  const [enableTextCleaning, setEnableTextCleaning] = useState(() => {
    const saved = localStorage.getItem('enableTextCleaning');
    return saved !== null ? JSON.parse(saved) : true;  // 默认为true
  });
  
  // 默认文本清洗正则表达式（与原硬编码规则一致，换行分隔）
  const defaultCleaningPatterns = String.raw`\([^)]*\)
（[^）]*）
\[[^\]]*\]
【[^】]*】
\{[^}]*\}
<[^>]*>
\*[^*]*\*`;
  
  const [textCleaningPatterns, setTextCleaningPatterns] = useState(() => {
    const saved = localStorage.getItem('textCleaningPatterns');
    return saved !== null ? saved : defaultCleaningPatterns;
  });
  
  const [preserveQuotes, setPreserveQuotes] = useState(() => {
    const saved = localStorage.getItem('preserveQuotes');
    return saved !== null ? JSON.parse(saved) : true;
  });
  
  const [cleaningPatternsModalVisible, setCleaningPatternsModalVisible] = useState(false);
  
  const [currentMessage, setCurrentMessage] = useState('');
  const [sent_flag, setSentFlag] = useState(false);  // 添加发送标记状态
  
  // @ 成员功能相关状态
  const [mentionMenuVisible, setMentionMenuVisible] = useState(false);
  const [mentionSearchText, setMentionSearchText] = useState('');
  const [mentionCursorPosition, setMentionCursorPosition] = useState(0);
  const [mentionAtPosition, setMentionAtPosition] = useState(0); // @符号的位置
  const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0); // 当前选中的成员索引
  const [mentionSelectCount, setMentionSelectCount] = useState(0); // 当前菜单打开期间已选择的次数
  
  // 智能语音输入相关状态（带 VAD 自动停止）
  const { isRecording, isSpeaking, currentVolume, recordingDuration, startRecording, stopRecording, cancelRecording } = useSmartRecorder();
  const [isTranscribing, setIsTranscribing] = useState(false); // 转录中状态
  const [vadStatus, setVadStatus] = useState<VADStatusType>('idle'); // VAD状态
  
  const [systemPrompt, setSystemPrompt] = useState<string>('');
  const [systemPromptModalVisible, setSystemPromptModalVisible] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  const messageListRef = useRef<HTMLDivElement>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const hasEverOpenedRef = useRef<boolean>(false);
  const suppressReconnectToastUntilRef = useRef<number>(0);
  const hiddenBgInputRef = useRef<HTMLInputElement>(null);

  const [editingSession, setEditingSession] = useState<ChatSession | null>(null);
  const [newSessionName, setNewSessionName] = useState('');
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [isDesktop, setIsDesktop] = useState(window.innerWidth > 992);
  const [siderVisible, setSiderVisible] = useState(false);
  // 群成员面板显示控制：当窗口宽度 > 900px 时才显示
  const [showGroupMemberPanel, setShowGroupMemberPanel] = useState(window.innerWidth > 900);
  // 背景图片相关
  const [backgroundImageUrl, setBackgroundImageUrl] = useState<string>('');
  // Track last manual set time to avoid race with background fetch
  const backgroundManuallySetAtRef = useRef<number>(0);
  // Track latest background fetch sequence to prevent stale updates
  const backgroundFetchSeqRef = useRef<number>(0);
  // Keep current object URL to revoke when updating background
  const backgroundObjectUrlRef = useRef<string | null>(null);
  
  // 缓存尚未附着到消息上的引用数据，避免创建空气泡
  const pendingReferenceRef = useRef<any | null>(null);
  
  // 🆕 知识图谱可视化相关状态
  const [graphViewerVisible, setGraphViewerVisible] = useState(false);
  const [selectedGraphData, setSelectedGraphData] = useState<GraphMetadata[]>([]);
  
  // 记录"修改背景图片"的目标（可能是当前会话，也可能是其他会话）
  const [backgroundUploadTarget, setBackgroundUploadTarget] = useState<
    | { type: 'traditional'; sessionId: string }
    | { type: 'group'; groupId: string }
    | null
  >(null);

  

  // 图片相关状态
  const [selectedImages, setSelectedImages] = useState<File[]>([]);
  const [imagePreviews, setImagePreviews] = useState<string[]>([]);
  const [isImageUploading, setIsImageUploading] = useState(false);
  const [currentSessionSupportsImage, setCurrentSessionSupportsImage] = useState(false);
  const [imageModalVisible, setImageModalVisible] = useState(false);
  const [selectedImage, setSelectedImage] = useState<string>('');
  const [compressorModalVisible, setCompressorModalVisible] = useState(false);
  const [isViewingPendingImage, setIsViewingPendingImage] = useState(false);
    const [isModelTyping, setIsModelTyping] = useState(false); // 模型正在输入状态
  const [typingText, setTypingText] = useState('正在输入中...'); // 🎯 动态输入提示文本
  // 设置模态框可见性
  const [settingsModalVisible, setSettingsModalVisible] = useState(false);
   
   // 图片预览增强状态
  const [imageScale, setImageScale] = useState(1);
  const [imagePosition, setImagePosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [initialFitScale, setInitialFitScale] = useState(1); // 初始适配缩放比例
  const [imageNaturalSize, setImageNaturalSize] = useState({ width: 0, height: 0 });

  // 引用的文档信息（支持多个）
  const [referencedDocs, setReferencedDocs] = useState<Array<{ filename: string; docId: string; kbId: string }>>([]);

  // 删除消息相关状态
  const [deleteMessageModalVisible, setDeleteMessageModalVisible] = useState(false);
  const [messageToDelete, setMessageToDelete] = useState<{index: number, content: string} | null>(null);

  // 修改消息相关状态
  const [editMessageModalVisible, setEditMessageModalVisible] = useState(false);
  const [messageToEdit, setMessageToEdit] = useState<{index: number, content: string, images?: string[]} | null>(null);
  const [editedContent, setEditedContent] = useState('');
  const [editedImages, setEditedImages] = useState<string[]>([]);

  // 导出对话数据相关状态
  const [exportChatModalVisible, setExportChatModalVisible] = useState(false);
  const [exportingSession, setExportingSession] = useState<ChatSession | null>(null);
  const [exportFileName, setExportFileName] = useState('');
  const [exportFormat, setExportFormat] = useState<'txt' | 'json'>('txt');
  const [exportIncludeTimestamps, setExportIncludeTimestamps] = useState<boolean>(true);
  const [exportIncludeSystemPrompts, setExportIncludeSystemPrompts] = useState<boolean>(true);
  
  // 管理深度思考展开状态
  const [thinkingSectionStates, setThinkingSectionStates] = useState<{[key: string]: boolean}>({});
  
  // 创建一个稳定的切换函数
  const toggleThinkingSection = useCallback((stateKey: string) => {
    setThinkingSectionStates(prev => ({
      ...prev,
      [stateKey]: !prev[stateKey]
    }));
  }, []);
  // 在组件顶部添加新的状态
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<{
    session_id: string; // 添加会话ID
    modelSettings: ModelSettings;
    systemPrompt: string;
    contextCount: number | null; // 添加上下文数量，null表示不限制
  } | null>(null);
  const [enabledProviders, setEnabledProviders] = useState<Array<{ id: string; name: string; baseUrl: string; apiKey: string; models: string[]; customModels?: CustomModel[] }>>([]);
  
  // Embedding 服务商状态
  const [enabledEmbeddingProviders, setEnabledEmbeddingProviders] = useState<Array<{ id: string; name: string; baseUrl: string; apiKey: string; models: string[]; defaultModel: string }>>([]);
  const [defaultEmbeddingProviderId, setDefaultEmbeddingProviderId] = useState<string>('');

  // 知识库配置状态
  const [kbConfigModalVisible, setKbConfigModalVisible] = useState(false);
  const [kbConfigActiveTab, setKbConfigActiveTab] = useState('knowledge'); // 新增：控制知识库配置模态框的标签页
  const [toolConfigModalVisible, setToolConfigModalVisible] = useState(false);
  const [kbEditingSession, setKbEditingSession] = useState<ChatSession | null>(null);
  const [kbConfig, setKbConfig] = useState<any>({
    enabled: false,
    vector_db: 'chroma',
    collection_name: '',
    kb_prompt_template: '',
    similarity_threshold: 10, // 相似度阈值（L2距离），距离小于此值的结果才会被返回
    embeddings: undefined, // 不设置默认值，必须由用户在 ModelConfig 配置
    split_params: {
      chunk_size: 500,
      chunk_overlap: 100,
      separators: ['\n\n', '\n', '。', '！', '？', '，', ' ', '']
    },
    // 🆕 多知识库配置
    kb_ids: [], // 知识库ID列表（可选1个或多个）
    top_k_per_kb: 3, // 每个知识库返回结果数
    final_top_k: 10, // 最终返回总结果数
    merge_strategy: 'weighted_score' // 合并策略
  });
  
  // 🆕 知识库列表状态
  const [availableKnowledgeBases, setAvailableKnowledgeBases] = useState<any[]>([]);
  const [kbListLoading, setKbListLoading] = useState(false);
  
  // 用于跟踪配置是否已加载，避免重复加载覆盖用户输入
  const kbConfigLoadedRef = useRef(false);

  // 保存知识库配置标签页（检索配置）
  const handleSaveKnowledgeConfig = async () => {
    if (!kbEditingSession) { message.error('未选择会话'); return; }
    
    // 从当前完整配置中提取知识库配置相关字段
    const knowledgeConfig = {
      enabled: kbConfig.enabled,
      kb_prompt_template: kbConfig.kb_prompt_template,
      kb_ids: kbConfig.kb_ids,
      top_k: kbConfig.top_k,
      top_k_per_kb: kbConfig.top_k_per_kb,
      final_top_k: kbConfig.final_top_k,
      merge_strategy: kbConfig.merge_strategy
    };
    
    try {
      // 获取当前会话的完整配置，然后只更新知识库配置字段
      const currentKbSettings = (kbEditingSession as any).kb_settings || {};
      const updatedSettings = { ...currentKbSettings, ...knowledgeConfig };
      
      await updateSession(kbEditingSession.session_id, { kb_settings: updatedSettings } as any);
      message.success('知识库配置已保存');
      setKbConfigModalVisible(false);
      setKbEditingSession(null);
      await useChatStore.getState().fetchSessions();
    } catch (e) {
      console.error(e);
      message.error('保存失败');
    }
  };

  // 保存角色记忆标签页（底层配置）
  const handleSaveMemoryConfig = async () => {
    if (!kbEditingSession) { message.error('未选择会话'); return; }
    
    // 基础校验
    if (kbConfig.enabled) {
      if (!kbConfig.collection_name?.trim()) { message.error('请输入知识库名称'); return; }
      if (kbConfig.embeddings?.provider === 'ollama') {
        if (!kbConfig.embeddings?.base_url) { message.error('请输入 Ollama 服务地址'); return; }
        if (!kbConfig.embeddings?.model) { message.error('请选择 Ollama 模型'); return; }
      } else if (kbConfig.embeddings?.provider === 'local') {
        if (!kbConfig.embeddings?.model) { 
          message.error('请选择本地嵌入模型'); 
          return; 
        }
      } else if (kbConfig.embeddings?.provider === 'ark') {
        if (!kbConfig.embeddings?.api_key) { message.error('请输入火山引擎 API Key'); return; }
        if (!kbConfig.embeddings?.model) { message.error('请选择火山引擎嵌入模型'); return; }
      }
    }
    
    // 从当前完整配置中提取底层配置相关字段
    const memoryConfig = {
      enabled: kbConfig.enabled,
      vector_db: kbConfig.vector_db,
      collection_name: kbConfig.collection_name,
      embeddings: kbConfig.embeddings,
      split_params: kbConfig.split_params
    };
    
    // 准备要保存的配置
    let configToSave = { ...memoryConfig };
    if (configToSave.embeddings?.provider === 'local' && configToSave.embeddings?.model) {
      configToSave.embeddings.local_model_path = `checkpoints/embeddings/${configToSave.embeddings.model}`;
    }
    
    try {
      // 获取当前会话的完整配置，然后只更新底层配置字段
      const currentKbSettings = (kbEditingSession as any).kb_settings || {};
      const updatedSettings = { ...currentKbSettings, ...configToSave };
      
      await updateSession(kbEditingSession.session_id, { kb_settings: updatedSettings } as any);
      message.success('角色记忆配置已保存');
      setKbConfigModalVisible(false);
      setKbEditingSession(null);
      await useChatStore.getState().fetchSessions();
    } catch (e) {
      console.error(e);
      message.error('保存失败');
    }
  };

  // 根据当前活动标签页调用对应的保存函数
  const handleSaveKbConfig = async () => {
    if (kbConfigActiveTab === 'knowledge') {
      await handleSaveKnowledgeConfig();
    } else if (kbConfigActiveTab === 'memory') {
      await handleSaveMemoryConfig();
    }
  };

  // KB 文件上传与解析（使用新的 Hook）
  const kbFileInputRef = useRef<HTMLInputElement>(null);
  const [kbSelectedFile, setKbSelectedFile] = useState<File | null>(null);
  const { uploadAndWait, uploading: kbParsing } = useDocumentUpload();

  const handleKbFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files && e.target.files[0];
    setKbSelectedFile(f || null);
  }, []);

  const handleKbParseFile = useCallback(async () => {
    if (!kbSelectedFile) { message.error('请先选择文件'); return; }
    if (!kbConfig.enabled) { message.error('请先启用知识库'); return; }
    if (!kbConfig.collection_name?.trim()) { message.error('请输入知识库名称'); return; }
    if (!kbEditingSession) { message.error('未选择会话'); return; }

    try {
      // 使用新的文档上传 Hook
      await uploadAndWait({
        file: kbSelectedFile,
        kbSettings: kbConfig,
        sessionId: kbEditingSession.session_id,
        priority: 'NORMAL'
      });
      
      // 刷新会话列表
      await useChatStore.getState().fetchSessions();
      const latestSessions = useChatStore.getState().sessions;
      const latest = latestSessions.find(s => s.session_id === kbEditingSession.session_id);
      if (latest) setKbEditingSession(latest as any);
      
    } catch (err: any) {
      // 错误已在 Hook 内部处理
      console.error('文档上传失败:', err);
    }
  }, [kbSelectedFile, kbConfig, kbEditingSession, uploadAndWait]);

  // 添加电脑端侧边栏折叠状态
  const [desktopSiderCollapsed, setDesktopSiderCollapsed] = useState(false);

  // 用户头像相关状态
  const [userAvatarModalVisible, setUserAvatarModalVisible] = useState(false);
  const [userAvatar, setUserAvatar] = useState<string>('');
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  
  // 用户个性化信息状态
  const [userFullName, setUserFullName] = useState<string>('');
  const [userGender, setUserGender] = useState<string>('');
  const [userBirthDate, setUserBirthDate] = useState<string>('');  // 改为出生日期
  const [userSignature, setUserSignature] = useState<string>('');
  const [isSavingProfile, setIsSavingProfile] = useState(false);

  // 处理TTS配置点击
  const handleTtsConfigClick = async (session: ChatSession) => {
    console.log('[TTS] 开始处理TTS配置点击');
    console.log('[TTS] 目标会话:', session.session_id, session.name);
    
    try {
      // 从authStore获取token
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;
      
      if (!token) {
        console.error('[TTS] 没有找到认证token');
        message.error('请先登录');
        return;
      }
      
      console.log('[TTS] 开始查询会话TTS配置');
      
      // 查询会话的TTS配置
      const response = await fetch(`/api/chat/sessions/${session.session_id}/tts-config`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });
      
      console.log('[TTS] API响应状态:', response.status, response.statusText);
      
      if (response.ok) {
        const result = await response.json();
        console.log('[TTS] 查询结果:', result);
        
        if (result.success && result.has_config && result.tts_settings) {
          const ttsSettings = result.tts_settings;
          console.log('[TTS] 找到已保存的TTS配置');
          console.log('[TTS] 服务商:', ttsSettings.provider);
          // 安全日志：不打印包含敏感信息的配置详情
          console.log('[TTS] 配置已加载 (包含', Object.keys(ttsSettings.config || {}).length, '个配置项)');
          console.log('[TTS] 音色ID:', ttsSettings.voice_settings?.voice_id || '未设置');
          
          // 设置TTS配置状态
          setTtsConfig({
            provider: ttsSettings.provider,
            config: ttsSettings.config || {},
            voiceSettings: ttsSettings.voice_settings || {}
          });
          
          // 设置选中的TTS服务商
          setSelectedTtsProvider(ttsSettings.provider);
          
          console.log('[TTS] 自动填入配置完成，直接打开配置模态框');
          
          // 直接打开TTS配置模态框，跳过服务商选择
          setTtsConfigModalVisible(true);
          
          message.success(`已加载 ${ttsSettings.provider === 'xfyun' ? '讯飞云' : '字节跳动'} TTS配置`);
        } else {
          console.log('[TTS] 未找到TTS配置，显示服务商选择界面');
          // 没有配置，显示服务商选择界面
          setTtsProviderModalVisible(true);
        }
      } else {
        const errorText = await response.text();
        console.error('[TTS] 查询TTS配置失败:', response.status, response.statusText, errorText);
        message.error('查询TTS配置失败');
        
        // 出错时也显示服务商选择界面
        setTtsProviderModalVisible(true);
      }
    } catch (error) {
      console.error('[TTS] 查询TTS配置异常:', error);
      message.error('查询TTS配置失败');
      
      // 出错时也显示服务商选择界面
      setTtsProviderModalVisible(true);
    }
  };

  // 角色信息相关状态
  const [roleInfoModalVisible, setRoleInfoModalVisible] = useState(false);
  const [roleAvatar, setRoleAvatar] = useState<string>('');
  const [isUploadingRoleAvatar, setIsUploadingRoleAvatar] = useState(false);

  // 头像裁剪相关状态
  const [userAvatarCropperVisible, setUserAvatarCropperVisible] = useState(false);
  const [roleAvatarCropperVisible, setRoleAvatarCropperVisible] = useState(false);
  const [tempAvatarUrl, setTempAvatarUrl] = useState<string>('');

  // TTS相关状态
  const [ttsProviderModalVisible, setTtsProviderModalVisible] = useState(false);
  const [ttsConfigModalVisible, setTtsConfigModalVisible] = useState(false);
  const [selectedTtsProvider, setSelectedTtsProvider] = useState<string>('');
  const [ttsConfig, setTtsConfig] = useState<{
    provider: string;
    config: Record<string, string>;
    voiceSettings?: Record<string, any>;
  }>({
    provider: '',
    config: {},
    voiceSettings: {}
  });
  // 用户全局TTS配置（从ModelConfig加载）
  const [userGlobalTtsConfigs, setUserGlobalTtsConfigs] = useState<Record<string, any>>({});
  const [voiceGenderFilter, setVoiceGenderFilter] = useState<'all' | 'male' | 'female'>('all');
  const [showVoiceSearch, setShowVoiceSearch] = useState(false);
  const [voiceSearchQuery, setVoiceSearchQuery] = useState('');

  // 系统设置：对话背景开关（默认关闭），持久化到 localStorage
  const [enableChatBackground, setEnableChatBackground] = useState<boolean>(() => {
    try {
      return localStorage.getItem('enableChatBackground') === '1';
    } catch {
      return false;
    }
  });

  // 系统设置：消息气泡和输入框透明度（0-100，默认100不透明），持久化到 localStorage
  const [messageOpacity, setMessageOpacity] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('messageOpacity');
      return saved ? parseInt(saved, 10) : 100;
    } catch {
      return 100;
    }
  });

  // 检查模型是否支持图片（包含自定义模型）
  const checkModelSupportsImage = useCallback((modelService: string, modelName: string): boolean => {
    // 首先检查是否有自定义模型
    const provider = enabledProviders.find(p => p.id === modelService);
    if (provider && provider.customModels) {
      const customModel = provider.customModels.find(cm => cm.id === modelName);
      if (customModel) {
        return customModel.supportsImage;
      }
    }
    
    // 然后从配置文件检查模型配置
    const modelInfo = getModelInfoFromConfig(modelService, modelName);
    return modelInfo?.supportsImage || false;
  }, [enabledProviders]);

  useEffect(() => {
    try {
      localStorage.setItem('enableChatBackground', enableChatBackground ? '1' : '0');
    } catch {}
  }, [enableChatBackground]);

  // 持久化消息透明度设置
  useEffect(() => {
    try {
      localStorage.setItem('messageOpacity', messageOpacity.toString());
    } catch {}
  }, [messageOpacity]);

  // 点击输入框外部时关闭@菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (mentionMenuVisible) {
        const target = event.target as HTMLElement;
        // 检查是否点击在输入框或@菜单内
        const clickedInsideInput = inputRef.current?.resizableTextArea?.textArea?.contains(target);
        const clickedInsideMentionMenu = target.closest('[data-mention-menu]');
        
        if (!clickedInsideInput && !clickedInsideMentionMenu) {
          setMentionMenuVisible(false);
          setMentionSelectCount(0); // 重置选择计数
        }
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [mentionMenuVisible]);

  // 自动滚动到选中的@成员项
  useEffect(() => {
    if (mentionMenuVisible && mentionSelectedIndex >= 0) {
      const selectedElement = document.querySelector(`[data-mention-item="${mentionSelectedIndex}"]`);
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [mentionSelectedIndex, mentionMenuVisible]);

  // 处理电脑端侧边栏折叠
  const toggleDesktopSider = () => {
    setDesktopSiderCollapsed(prev => !prev);
  };



  // 图片处理函数
  const handleImageSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files) {
      const processedFiles: File[] = [];
      
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        
        // 检查文件类型
        if (!file.type.startsWith('image/')) {
          message.error(`文件 ${file.name} 不是图片格式`);
          continue;
        }
        
        // 检查文件大小 (限制为10MB)
        if (file.size > 10 * 1024 * 1024) {
          message.error(`图片文件 ${file.name} 大小不能超过10MB`);
          continue;
        }
        
        try {
          // 为了确保与后端PNG格式完全兼容，所有图片都转换为PNG
          console.log(`按钮上传图片格式: ${file.type}，转换为PNG以确保兼容性`);
          const processedFile = await convertImageToPNG(file);
          
          processedFiles.push(processedFile);
        
        // 创建预览
        const reader = new FileReader();
        reader.onload = (e) => {
          const preview = e.target?.result as string;
          setImagePreviews(prev => [...prev, preview]);
        };
          reader.readAsDataURL(processedFile);
        } catch (error) {
          console.error(`图片处理失败 ${file.name}:`, error);
          message.error(`图片 ${file.name} 处理失败，请重试`);
          continue;
        }
      }
      
      if (processedFiles.length > 0) {
        setSelectedImages(prev => [...prev, ...processedFiles]);
        message.success(`成功添加 ${processedFiles.length} 张图片`);
      }
    }
  };

  const handleImageRemove = (index: number) => {
    setSelectedImages(prev => prev.filter((_, i) => i !== index));
    setImagePreviews(prev => prev.filter((_, i) => i !== index));
  };

  const handleImageRemoveAll = () => {
    setSelectedImages([]);
    setImagePreviews([]);
  };

  const handleImageClick = (imageUrl: string, isPending: boolean = false) => {
    setSelectedImage(imageUrl);
    setImageModalVisible(true);
    setIsViewingPendingImage(isPending);
    // 重置图片状态
    setImageScale(1);
    setImagePosition({ x: 0, y: 0 });
    setIsDragging(false);
  };

  const handleImageModalClose = () => {
    setImageModalVisible(false);
    setSelectedImage('');
    // 重置图片状态
    setImageScale(1);
    setImagePosition({ x: 0, y: 0 });
    setIsDragging(false);
    setInitialFitScale(1);
    setImageNaturalSize({ width: 0, height: 0 });
    // 清理定时器
    if (wheelTimeoutRef.current) {
      clearTimeout(wheelTimeoutRef.current);
    }
  };

  // 处理图片压缩
  const handleImageCompress = () => {
    // 只有当显示的是待发送图片时才允许压缩
    if (isViewingPendingImage && imagePreviews.length > 0 && selectedImages.length > 0) {
      setCompressorModalVisible(true);
    } else {
      message.warning('只能压缩待发送的图片');
    }
  };

  const handleCompressorCancel = () => {
    setCompressorModalVisible(false);
  };

  const handleCompressorConfirm = (compressedImages: File[], compressedPreviews: string[]) => {
    // 更新待发送的图片列表
    setSelectedImages(compressedImages);
    setImagePreviews(compressedPreviews);
    setCompressorModalVisible(false);
    setImageModalVisible(false);
    message.success(`已压缩 ${compressedImages.length} 张图片`);
  };

  // 图片预览容器鼠标滚动事件处理
  const handleImagePreviewWheel = (event: React.WheelEvent) => {
    event.preventDefault();
    const container = event.currentTarget;
    const scrollAmount = event.deltaY > 0 ? 100 : -100;
    container.scrollLeft += scrollAmount;
  };

  // 计算图片的最佳适配缩放比例
  const calculateFitScale = (imageWidth: number, imageHeight: number, containerWidth: number, containerHeight: number) => {
    if (imageWidth === 0 || imageHeight === 0 || containerWidth === 0 || containerHeight === 0) {
      return 1;
    }

    // 计算宽度和高度的缩放比例
    const widthScale = containerWidth / imageWidth;
    const heightScale = containerHeight / imageHeight;
    
    // 选择较小的缩放比例，确保图片完全适应容器
    const fitScale = Math.min(widthScale, heightScale);
    
    // 限制最小和最大缩放比例
    return Math.min(Math.max(fitScale, 0.1), 1);
  };

  // 图片加载完成后计算适配比例
  const handleImageLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.target as HTMLImageElement;
    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;
    
    // 保存图片原始尺寸
    setImageNaturalSize({ width: naturalWidth, height: naturalHeight });
    
    // 获取容器尺寸（需要减去padding）
    const container = img.closest(`.${styles.imageModalContainer}`) as HTMLElement;
    if (container) {
      const containerRect = container.getBoundingClientRect();
      const containerWidth = containerRect.width - 40; // 减去左右padding (20px * 2)
      const containerHeight = containerRect.height - 40; // 减去上下padding (20px * 2)
      
      // 计算最佳适配比例
      const fitScale = calculateFitScale(naturalWidth, naturalHeight, containerWidth, containerHeight);
      
      console.log('图片自适应计算:', {
        naturalWidth,
        naturalHeight,
        containerWidth,
        containerHeight,
        fitScale
      });
      
      // 设置初始适配比例
      setInitialFitScale(fitScale);
      setImageScale(fitScale);
    }
    
    // 确保图片可见
    img.style.visibility = 'visible';
  };

  // 图片预览操作函数
  const handleImageZoomIn = () => {
    setImageScale(prev => Math.min(prev + 0.2, initialFitScale * 3)); // 基于初始适配比例的3倍
  };

  const handleImageZoomOut = () => {
    setImageScale(prev => Math.max(prev - 0.2, initialFitScale * 0.1)); // 基于初始适配比例的0.1倍
  };

  const handleImageResetZoom = () => {
    setImageScale(initialFitScale); // 重置到初始适配比例
    setImagePosition({ x: 0, y: 0 });
  };

  // 适合窗口大小
  const handleImageFitToWindow = () => {
    if (imageNaturalSize.width > 0 && imageNaturalSize.height > 0) {
      const container = document.querySelector(`.${styles.imageModalContainer}`) as HTMLElement;
      if (container) {
        const containerRect = container.getBoundingClientRect();
        const containerWidth = containerRect.width - 40;
        const containerHeight = containerRect.height - 40;
        
        const fitScale = calculateFitScale(
          imageNaturalSize.width, 
          imageNaturalSize.height, 
          containerWidth, 
          containerHeight
        );
        
        setImageScale(fitScale);
        setImagePosition({ x: 0, y: 0 });
      }
    }
  };



  const handleImageDownload = async () => {
    if (!selectedImage) return;
    
    try {
      const response = await fetch(selectedImage);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `image_${Date.now()}.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      message.success('图片下载成功');
    } catch (error) {
      console.error('下载图片失败:', error);
      message.error('图片下载失败');
    }
  };

  // 图片拖拽处理 - 使用useCallback优化性能
  const handleImageMouseDown = useCallback((e: React.MouseEvent) => {
    if (imageScale <= initialFitScale) return; // 只有超过初始适配比例时才能拖拽
    setIsDragging(true);
    setDragStart({
      x: e.clientX - imagePosition.x,
      y: e.clientY - imagePosition.y
    });
    e.preventDefault();
  }, [imageScale, initialFitScale, imagePosition.x, imagePosition.y]);

  const handleImageMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || imageScale <= initialFitScale) return;
    setImagePosition({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y
    });
  }, [isDragging, imageScale, initialFitScale, dragStart.x, dragStart.y]);

  const handleImageMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // 鼠标滚轮缩放 - 使用节流优化性能
  const wheelTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  const handleImageWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    
    // 清除之前的定时器
    if (wheelTimeoutRef.current) {
      clearTimeout(wheelTimeoutRef.current);
    }
    
    // 设置新的定时器，节流处理
    wheelTimeoutRef.current = setTimeout(() => {
      const delta = e.deltaY > 0 ? -0.1 : 0.1; // 适中的缩放步长
      setImageScale(prev => {
        const minScale = initialFitScale * 0.1; // 基于初始适配比例的最小值
        const maxScale = initialFitScale * 3;   // 基于初始适配比例的最大值
        const newScale = Math.max(minScale, Math.min(maxScale, prev + delta));
        return Math.round(newScale * 100) / 100; // 保留两位小数，减少重渲染
      });
    }, 16); // 约60fps
  }, [initialFitScale]);

  // 键盘事件处理
  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      if (!imageModalVisible) return;
      
      switch (e.key) {
        case 'Escape':
          handleImageModalClose();
          break;
        case '+':
        case '=':
          handleImageZoomIn();
          break;
        case '-':
          handleImageZoomOut();
          break;
        case '0':
          handleImageResetZoom();
          break;
      }
    };

    document.addEventListener('keydown', handleKeyPress);
    return () => document.removeEventListener('keydown', handleKeyPress);
  }, [imageModalVisible]);

  // 用户头像相关处理函数
  const handleUserAvatarClick = () => {
    setUserAvatarModalVisible(true);
  };

  const handleUserAvatarModalClose = () => {
    setUserAvatarModalVisible(false);
  };

  const handleAvatarUpload = async (file: File) => {
    try {
      // 检查文件类型
      if (!file.type.startsWith('image/')) {
        message.error('请选择图片文件');
        return false;
      }
      
      // 检查文件大小 (限制为5MB)
      if (file.size > 5 * 1024 * 1024) {
        message.error('头像文件大小不能超过5MB');
        return false;
      }
      
      // 创建临时URL用于裁剪
      const tempUrl = URL.createObjectURL(file);
      setTempAvatarUrl(tempUrl);
      setUserAvatarCropperVisible(true);
      
      return false; // 阻止默认上传行为
    } catch (error) {
      console.error('头像处理失败:', error);
      message.error('头像处理失败，请重试');
      return false;
    }
  };

  const handleAvatarSave = async () => {
    // 保存用户个性化信息
    try {
      setIsSavingProfile(true);
      
      const profileData: any = {
        full_name: userFullName || '',
        gender: userGender || '',
        signature: userSignature || ''
      };
      
      // 只在出生日期有值时才发送
      if (userBirthDate) {
        profileData.birth_date = userBirthDate;
      }
      
      const response = await authAxios.put('/api/auth/profile', profileData);
      
      if (response.status === 200) {
        message.success('个人信息保存成功');
        
        // 刷新用户信息（重新获取最新数据）
        try {
          const userResponse = await authAxios.get('/api/auth/me');
          if (userResponse.status === 200) {
            // 使用updateUser方法更新authStore中的用户信息
            updateUser(userResponse.data);
          }
        } catch (err) {
          console.error('刷新用户信息失败:', err);
        }
        
        setUserAvatarModalVisible(false);
      } else {
        message.error('保存失败，请重试');
      }
    } catch (error: any) {
      console.error('保存用户信息失败:', error);
      message.error(error.response?.data?.detail || '保存失败');
    } finally {
      setIsSavingProfile(false);
    }
  };

  // 用户头像裁剪处理函数
  const handleUserAvatarCropConfirm = async (croppedImageUrl: string) => {
    try {
      setIsUploadingAvatar(true);
      
      // 将裁剪后的图片转换为base64
      const response = await fetch(croppedImageUrl);
      const blob = await response.blob();
      const base64 = await convertImageToBase64(blob as File);
      
      // 上传到后端
      const uploadResponse = await fetch('/api/auth/upload-avatar', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${useAuthStore.getState().token}`
        },
        body: JSON.stringify({
          avatar: base64
        })
      });
      
      if (uploadResponse.ok) {
        const result = await uploadResponse.json();
        setUserAvatar(result.avatar_url);
        // 立即更新user对象，使头像立即显示
        if (user) {
          updateUser({ ...user, avatar_url: result.avatar_url });
        }
        message.success('头像上传成功');
        setUserAvatarCropperVisible(false);
        setTempAvatarUrl('');
      } else {
        const error = await uploadResponse.json();
        message.error(error.detail || '头像上传失败');
      }
    } catch (error) {
      console.error('头像上传失败:', error);
      message.error('头像上传失败，请重试');
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  const handleUserAvatarCropCancel = () => {
    setUserAvatarCropperVisible(false);
    setTempAvatarUrl('');
  };

  // 角色头像相关处理函数
  const handleRoleAvatarUpload = async (file: File) => {
    try {
      // 检查文件类型
      if (!file.type.startsWith('image/')) {
        message.error('请选择图片文件');
        return false;
      }
      
      // 检查文件大小 (限制为5MB)
      if (file.size > 5 * 1024 * 1024) {
        message.error('头像文件大小不能超过5MB');
        return false;
      }
      
      // 创建临时URL用于裁剪
      const tempUrl = URL.createObjectURL(file);
      setTempAvatarUrl(tempUrl);
      setRoleAvatarCropperVisible(true);
      
      return false; // 阻止默认上传行为
    } catch (error) {
      console.error('角色头像处理失败:', error);
      message.error('角色头像处理失败，请重试');
      return false;
    }
  };

  const handleRoleInfoSave = async () => {
    if (!newSessionName.trim()) {
      message.error('会话名称不能为空');
      return;
    }

    try {
      setIsUploadingRoleAvatar(true);

      // 更新会话名称
      if (editingSession) {
        await updateSession(editingSession.session_id, { 
          name: newSessionName.trim() 
        });
      } else {
        return;
      }

      message.success('会话名称保存成功');
      setRoleInfoModalVisible(false);
      setNewSessionName('');
      setEditingSession(null);
      setRoleAvatar('');
    } catch (error) {
      console.error('会话名称保存失败:', error);
      message.error('会话名称保存失败，请重试');
    } finally {
      setIsUploadingRoleAvatar(false);
    }
  };

  // 角色头像裁剪处理函数
  const handleRoleAvatarCropConfirm = async (croppedImageUrl: string) => {
    try {
      setIsUploadingRoleAvatar(true);
      
      // 将裁剪后的图片转换为base64
      const response = await fetch(croppedImageUrl);
      const blob = await response.blob();
      const base64 = await convertImageToBase64(blob as File);
      
      // 计算要上传的会话ID
      const sessionIdForUpload = editingSession?.session_id || '';
      if (!sessionIdForUpload) {
        throw new Error('缺少会话ID');
      }
      
      // 上传到后端
      const uploadEndpoint = '/api/auth/upload-role-avatar';
      const body: any = { avatar: base64, session_id: sessionIdForUpload };
      const uploadResponse = await fetch(uploadEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${useAuthStore.getState().token}`
        },
        body: JSON.stringify(body)
      });
      
      if (uploadResponse.ok) {
        const result = await uploadResponse.json();
        setRoleAvatar(result.avatar_url);
        message.success('角色头像上传成功');
        setRoleAvatarCropperVisible(false);
        setTempAvatarUrl('');
        
        // 更新本地会话中的角色头像
        if (editingSession) {
          await updateSession(editingSession.session_id, {
            role_avatar_url: result.avatar_url
          });
        }
      } else {
        const error = await uploadResponse.json();
        message.error(error.detail || '角色头像上传失败');
      }
    } catch (error) {
      console.error('角色头像上传失败:', error);
      message.error('角色头像上传失败，请重试');
    } finally {
      setIsUploadingRoleAvatar(false);
    }
  };

  const handleRoleAvatarCropCancel = () => {
    setRoleAvatarCropperVisible(false);
    setTempAvatarUrl('');
  };

  const convertImageToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // 移除 data:image/[format];base64, 前缀，只保留base64部分
        const base64 = result.split(',')[1];
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  const convertImagesToBase64 = async (files: File[]): Promise<string[]> => {
    const promises = files.map(file => convertImageToBase64(file));
    return Promise.all(promises);
  };

  // 将图片转换为标准PNG格式（用于确保API兼容性）
  const convertImageToPNG = (file: File): Promise<File> => {
    return new Promise((resolve, reject) => {
      // 创建图片对象
      const img = new Image();
      img.onload = () => {
        // 创建canvas
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        
        if (!ctx) {
          reject(new Error('无法创建canvas context'));
          return;
        }

        // 设置canvas尺寸
        canvas.width = img.width;
        canvas.height = img.height;

        // 绘制图片到canvas
        ctx.drawImage(img, 0, 0);

        // 转换为PNG格式的blob
        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error('无法转换图片格式'));
            return;
          }

          // 创建新的File对象，确保是PNG格式
          const pngFile = new File(
            [blob], 
            file.name.replace(/\.[^/.]+$/, '.png'), // 替换扩展名为.png
            { type: 'image/png' }
          );
          
          resolve(pngFile);
        }, 'image/png', 0.95); // 转换为PNG，质量0.95
      };

      img.onerror = () => {
        reject(new Error('图片加载失败'));
      };

      // 加载图片
      const reader = new FileReader();
      reader.onload = (e) => {
        img.src = e.target?.result as string;
      };
      reader.onerror = () => {
        reject(new Error('文件读取失败'));
      };
      reader.readAsDataURL(file);
    });
  };

  // 从store获取状态和方法
  const { createSession, sessions, isLoading, error, fetchSessions, currentSession, setCurrentSession, updateSession, updateSessionMessageCount, deleteSession } = useChatStore();
  const { logout, user, updateUser } = useAuthStore(); // 添加user和updateUser
  const { theme } = useThemeStore(); // 获取主题状态
  
  // 群聊相关 Store
  const { 
    groups, 
    currentGroupId, 
    messages: groupMessages, 
    messageMetadata: groupMessageMetadata,
    fetchGroups, 
    selectGroup, 
    sendMessage: sendGroupMessage,
    connectWebSocket: connectGroupWebSocket,
    disconnectWebSocket: disconnectGroupWebSocket,
    clearCurrentGroup,
    setCurrentUserId,
    createGroup,
    updateGroup,
    addMember,
    removeMember,
    aiGoOnline,
    aiGoOffline,
    loadMoreMessages: loadMoreGroupMessages
  } = useGroupChatStore();

  // 根据主题动态加载 highlight.js 样式
  useEffect(() => {
    // 动态导入本地的 highlight.js 样式文件
    if (theme === 'dark') {
      import('highlight.js/styles/github-dark.css');
    } else {
      import('highlight.js/styles/github.css');
    }
  }, [theme]);

  // 根据主题获取模型服务配置
  const MODEL_SERVICES = useMemo(() => getModelServices(theme === 'dark'), [theme]);
  const EMBEDDING_SERVICES = useMemo(() => getEmbeddingServices(theme === 'dark'), [theme]);

  // 初始化用户头像
  useEffect(() => {
    if (user?.avatar_url) {
      setUserAvatar(user.avatar_url);
    }
  }, [user?.avatar_url]);

  // 初始化用户个性化信息
  useEffect(() => {
    if (user) {
      setUserFullName(user.full_name || '');
      setUserGender(user.gender || '');
      setUserBirthDate(user.birth_date || '');  // 使用出生日期
      setUserSignature(user.signature || '');
    }
  }, [user]);

  // 加载已启用的模型服务商配置
  useEffect(() => {
    const loadEnabledProviders = async () => {
      const providers = await fetchEnabledProviders();
      setEnabledProviders(providers);
    };
    
    if (configModalVisible) {
      loadEnabledProviders();
    }
  }, [configModalVisible]);

  // 加载已启用的 Embedding 服务商配置
  useEffect(() => {
    const loadEnabledEmbeddingProviders = async () => {
      const providers = await fetchEnabledEmbeddingProviders();
      const defaultProviderId = await fetchDefaultEmbeddingProvider();
      
      setEnabledEmbeddingProviders(providers);
      if (defaultProviderId) {
        setDefaultEmbeddingProviderId(defaultProviderId);
      }
    };
    
    if (kbConfigModalVisible) {
      loadEnabledEmbeddingProviders();
    }
  }, [kbConfigModalVisible]);

  // 加载用户的全局TTS配置
  useEffect(() => {
    if (ttsProviderModalVisible || ttsConfigModalVisible) {
      fetchUserGlobalTtsConfigs();
    }
  }, [ttsProviderModalVisible, ttsConfigModalVisible]);

  // 添加会话ID的引用，用于消息隔离
  const currentSessionIdRef = useRef<string | null>(null);

  // 基于所选会话加载知识库配置，仅在模态框打开时加载一次
  useEffect(() => {
    // 如果模态框关闭，重置加载标记
    if (!kbConfigModalVisible) {
      kbConfigLoadedRef.current = false;
      return;
    }
    
    // 如果模态框打开但没有选中会话，或者配置已加载过，跳过
    if (!kbEditingSession || kbConfigLoadedRef.current) return;

    const latest = sessions.find(s => s.session_id === kbEditingSession.session_id) || kbEditingSession;
    const kb = (latest as any).kb_settings || {};
    const hasSessionKb = kb && Object.keys(kb).length > 0;

    // 如果会话有配置，直接使用会话配置
    if (hasSessionKb) {
    const defaults = {
      enabled: false,
      vector_db: 'chroma',
      collection_name: '',
      kb_prompt_template: '',
      embeddings: {
        provider: 'ollama',
        model: '',
          base_url: '',
          api_key: ''
      },
      split_params: {
        chunk_size: 500,
        chunk_overlap: 100,
        separators: ['\n\n', '\n', '。', '！', '？', '，', ' ', '']
        },
        similarity_threshold: 10
    } as any;

      const merged = {
        ...defaults,
        ...kb,
        embeddings: { ...defaults.embeddings, ...(kb?.embeddings || {}) },
        split_params: { ...defaults.split_params, ...(kb?.split_params || {}) }
      } as any;

      // 若未设置知识库提示词，则默认填入当前会话原始提示词
      if (!merged.kb_prompt_template && (kbEditingSession as any)?.system_prompt) {
        merged.kb_prompt_template = (kbEditingSession as any).system_prompt;
      }
      setKbConfig(merged);
    } else {
      // 首次配置：使用默认的 Embedding 服务商
      const defaultProvider = enabledEmbeddingProviders.find(p => p.id === defaultEmbeddingProviderId) 
                           || enabledEmbeddingProviders[0];
      
      const defaults = {
        enabled: false,
        vector_db: 'chroma',
        collection_name: '',
        kb_prompt_template: (kbEditingSession as any)?.system_prompt || '',
        embeddings: defaultProvider ? {
          provider: defaultProvider.id,
          model: defaultProvider.defaultModel,
          base_url: defaultProvider.baseUrl,
          api_key: defaultProvider.apiKey,
          // 如果是本地模型，添加 local_model_path
          ...(defaultProvider.id === 'local' ? { local_model_path: `checkpoints/embeddings/${defaultProvider.defaultModel}` } : {})
        } : undefined, // 没有配置 embedding provider 时，不设置默认值
        split_params: {
          chunk_size: 500,
          chunk_overlap: 100,
          separators: ['\n\n', '\n', '。', '！', '？', '，', ' ', '']
        },
        similarity_threshold: 10
      } as any;

      setKbConfig(defaults);
    }
    
    // 标记配置已加载
    kbConfigLoadedRef.current = true;
  }, [kbConfigModalVisible, kbEditingSession, sessions, enabledEmbeddingProviders, defaultEmbeddingProviderId]);

  // 当 sessions 更新时，若KB配置模态框打开，则用最新的会话对象同步 kbEditingSession（以便刷新 kb_parsed 等状态）
  useEffect(() => {
    if (!kbConfigModalVisible || !kbEditingSession) return;
    const latest = sessions.find(s => s.session_id === kbEditingSession.session_id);
    if (latest && (latest as any).kb_parsed !== (kbEditingSession as any).kb_parsed) {
      setKbEditingSession(latest as any);
    }
  }, [sessions, kbConfigModalVisible, kbEditingSession]);

  // 使用音频队列播放器
  const { addToQueue, clearQueue, skipSequence } = useAudioQueue();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true);
  const smoothScrollIntervalRef = useRef<number | null>(null);
  const isUserScrollingRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  
  // 新增：传统会话批量删除相关状态
  const [traditionalBatchModalVisible, setTraditionalBatchModalVisible] = useState(false);
  const [selectedTraditionalSessionIds, setSelectedTraditionalSessionIds] = useState<string[]>([]);

  // 群聊相关模态框状态
  const [createGroupModalVisible, setCreateGroupModalVisible] = useState(false);
  const [manageGroupModalVisible, setManageGroupModalVisible] = useState(false);
  const [managingGroup, setManagingGroup] = useState<Group | null>(null);

  // 企业级懒加载消息管理
  const lazyLoadMessages = useLazyLoadMessages({
    sessionId: currentSession?.session_id || null
  });
  
  // 使用懒加载的messages和setMessages
  const { messages: traditionalMessages, setMessages, loadMoreMessages, hasMore, isLoading: isLoadingMore, reset: resetLazyLoad, handleInitialHistory } = lazyLoadMessages;
  
  // 根据当前会话类型选择消息源
  const messages = useMemo(() => {
    if (currentSession?.session_type === 'group' && currentGroupId) {
      // 群聊模式：使用群聊消息，并转换为 ChatMessage 格式
      const groupMsgs = groupMessages[currentGroupId] || [];
      const currentGroup = groups.find(g => g.group_id === currentGroupId);
      
      return groupMsgs.map((gm: GroupMessage) => {
        // 🔥 修复：在群聊中正确区分消息定位
        // 消息定位逻辑：
        // - 当前用户的消息 → 'user'（右侧）
        // - 其他用户和AI的消息 → 'assistant'（左侧）
        const role = gm.sender_id === user?.id ? 'user' : 'assistant';
        
        return {
          id: gm.message_id,
          role,
          content: gm.content,
          timestamp: gm.timestamp,
          sender_name: gm.sender_name,
          sender_id: gm.sender_id, // 保留sender_id用于头像查找
          images: gm.images || [],  // 🆕 包含图片
          reference: gm.reference || []  // 🆕 包含知识库引用（与普通会话字段名一致）
        };
      }) as ChatMessage[];
    }
    // 传统模式或助手模式：使用懒加载消息
    return traditionalMessages;
  }, [currentSession, currentGroupId, groupMessages, traditionalMessages, user?.id, groups]);
  
  // 根据当前会话类型选择加载函数和状态
  const isGroupChat = currentSession?.session_type === 'group' && currentGroupId;
  const groupMetadata = isGroupChat && currentGroupId ? groupMessageMetadata[currentGroupId] : null;
  
  const effectiveLoadMore = isGroupChat 
    ? async () => {
        if (currentGroupId) {
          await loadMoreGroupMessages(currentGroupId);
        }
      }
    : loadMoreMessages;
  
  const effectiveIsLoading = isGroupChat 
    ? groupMetadata?.isLoading || false
    : isLoadingMore;
  
  // 滚动加载器（使用messageListRef作为容器）
  useScrollLoader({
    containerRef: messageListRef,
    onLoadMore: effectiveLoadMore,
    threshold: 100,
    isLoading: effectiveIsLoading  // 传入加载状态，用于精确控制滚动恢复时机
  });

  // 处理输入容器点击事件，自动聚焦到输入框
  const handleInputContainerClick = (e: React.MouseEvent) => {
    // 如果点击的是按钮或其他交互元素，不要聚焦输入框
    const target = e.target as HTMLElement;
    if (target.closest('button') || target.closest('.ant-btn')) {
      return;
    }
    // 聚焦到输入框
    if (inputRef.current) {
      inputRef.current.focus();
    }
  };
  const [messageCountUpdated, setMessageCountUpdated] = useState(false); // 跟踪消息数量是否已更新
  
  // 检查是否在底部
  const isNearBottom = useCallback(() => {
    const container = messageListRef.current;
    if (!container) return true;
    const threshold = 10; // 阈值设为10px
    return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
  }, []);

  // 停止平滑滚动
  const stopSmoothScroll = useCallback(() => {
    if (smoothScrollIntervalRef.current) {
      clearInterval(smoothScrollIntervalRef.current);
      smoothScrollIntervalRef.current = null;
    }
  }, []);

  // 启动平滑滚动到底部
  const startSmoothScrollToBottom = useCallback(() => {
    // 如果已经在滚动中，不要重复启动
    if (smoothScrollIntervalRef.current) {
      return;
    }
    
    const container = messageListRef.current;
    if (!container) return;

    // 平滑滚动参数：每帧滚动的像素数
    // 设置为每帧20px，约60fps，每秒滚动约1200px，符合人眼舒适的阅读速度
    const pixelsPerFrame = 20;
    
    smoothScrollIntervalRef.current = window.setInterval(() => {
      const container = messageListRef.current;
      if (!container) {
        stopSmoothScroll();
        return;
      }

      const currentScroll = container.scrollTop;
      const maxScroll = container.scrollHeight - container.clientHeight;
      const distance = maxScroll - currentScroll;

      if (distance <= 1) {
        // 已经到底部，停止滚动
        container.scrollTop = maxScroll;
        stopSmoothScroll();
      } else {
        // 继续平滑滚动，直接增加像素数
        container.scrollTop += Math.min(pixelsPerFrame, distance);
      }
    }, 16); // 约60fps
  }, [stopSmoothScroll]);

  // 处理滚动事件
  const handleScroll = useCallback(() => {
    const container = messageListRef.current;
    if (!container) return;

    const currentScrollTop = container.scrollTop;
    const scrollDirection = currentScrollTop - lastScrollTopRef.current;
    lastScrollTopRef.current = currentScrollTop;

    // 检测用户主动向上滚动（离开底部）
    if (scrollDirection < 0 && !isUserScrollingRef.current) {
      console.log('[Scroll] 用户向上滚动，停止自动滚动');
      isUserScrollingRef.current = true;
      setShouldAutoScroll(false);
      stopSmoothScroll();
    }
    
    // 检测用户滚动回到底部
    if (isNearBottom() && isUserScrollingRef.current && !smoothScrollIntervalRef.current) {
      console.log('[Scroll] 用户回到底部，恢复自动滚动');
      isUserScrollingRef.current = false;
      setShouldAutoScroll(true);
    }
  }, [isNearBottom, stopSmoothScroll]);

  // 清理WebSocket连接
  const cleanupWebSocket = useCallback(() => {
    console.log('[Chat] 清理WebSocket连接');
    try { chatWSManager.close(); } catch {}
    // 清理引用
    currentSessionIdRef.current = null;
  }, []);

  // 监听窗口大小变化
  useEffect(() => {
    const handleResize = () => {
      const mobile = window.innerWidth <= 768;
      const desktop = window.innerWidth > 992;
      const hasSpaceForGroupPanel = window.innerWidth > 1400;
      setIsMobile(mobile);
      setIsDesktop(desktop);
      setShowGroupMemberPanel(hasSpaceForGroupPanel);
      if (mobile) {
        setSiderVisible(false);
      }
      
      // 移动端视口高度处理：防止地址栏隐藏导致的布局闪烁
      // 使用 visualViewport API 获取实际可见区域高度
      if (mobile && 'visualViewport' in window && window.visualViewport) {
        const viewport = window.visualViewport;
        // 只在视口高度变化显著时才更新（避免频繁触发）
        const currentHeight = viewport.height;
        const storedHeight = parseInt(localStorage.getItem('viewport-height') || '0');
        
        if (Math.abs(currentHeight - storedHeight) > 50) {
          localStorage.setItem('viewport-height', currentHeight.toString());
        }
      }
    };

    // 初始调用
    handleResize();
    
    // 监听窗口大小变化
    window.addEventListener('resize', handleResize);
    
    // 监听 visualViewport 变化（移动端地址栏显示/隐藏）
    if ('visualViewport' in window && window.visualViewport) {
      window.visualViewport.addEventListener('resize', handleResize);
    }
    
    return () => {
      window.removeEventListener('resize', handleResize);
      if ('visualViewport' in window && window.visualViewport) {
        window.visualViewport.removeEventListener('resize', handleResize);
      }
    };
  }, []);

  // 监听语音相关状态变化并保存到localStorage
  useEffect(() => {
    localStorage.setItem('enableVoice', JSON.stringify(enableVoice));
  }, [enableVoice]);

  useEffect(() => {
    localStorage.setItem('enableTextCleaning', JSON.stringify(enableTextCleaning));
  }, [enableTextCleaning]);

  useEffect(() => {
    localStorage.setItem('textCleaningPatterns', textCleaningPatterns);
  }, [textCleaningPatterns]);

  useEffect(() => {
    localStorage.setItem('preserveQuotes', JSON.stringify(preserveQuotes));
  }, [preserveQuotes]);
  // 组件初始化 - 获取会话和TTS配置
  useEffect(() => {
    console.log('[Chat] 组件初始化 - 开始获取数据');
    fetchSessions(); // 获取用户的所有会话
    
    fetchUserGlobalTtsConfigs(); // 获取用户全局TTS配置
    
    // 初始化群聊：设置当前用户ID并获取群组列表
    if (user?.id) {
      setCurrentUserId(user.id);
      fetchGroups().catch(err => console.error('[Chat] 获取群组列表失败:', err));
    }
  }, [fetchSessions, user?.id, setCurrentUserId, fetchGroups]);

  // 获取用户全局TTS配置
  const fetchUserGlobalTtsConfigs = async () => {
    try {
      const response = await authAxios.get('/api/tts-config/user');
      if (response.data && response.data.configs) {
        setUserGlobalTtsConfigs(response.data.configs);
        console.log('[TTS] 加载用户全局TTS配置成功:', response.data.configs);
      }
    } catch (error) {
      console.error('[TTS] 加载用户全局TTS配置失败:', error);
    }
  };

  // 处理System Prompt设置
  const handleSystemPromptSave = () => {
    setSystemPromptModalVisible(false);
    if (systemPrompt.trim()) {
      message.success('System Prompt已保存，将在创建新会话时使用');
    } else {
      setSystemPrompt('');
      message.info('System Prompt已清除，将使用默认值');
    }
  };

  // 修改创建会话的函数 - 从 ModelConfig 获取默认模型配置
  const handleCreateSession = async () => {
    console.log('[Chat] 点击创建新会话按钮');

    try {
      setIsProcessing(true);

      // 1. 从后端获取默认模型配置
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/model-config/default', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();

      if (!result.success || !result.config) {
        message.error('请先在模型配置页面设置默认模型');
        setIsProcessing(false);
      return;
    }

      const defaultConfig = result.config;
      const providerId = result.provider_id;

      console.log('[Chat] 获取到的默认模型配置:', defaultConfig);

    // 2. 获取默认模型参数
      const defaultParams = getModelDefaultParams(providerId, defaultConfig.default_model);
    console.log('[Chat] 获取到的默认模型参数:', defaultParams);

      // 3. 构建完整的模型配置
    const completeModelSettings = {
        modelService: providerId,
        baseUrl: defaultConfig.base_url,
        apiKey: defaultConfig.api_key || '',
        modelName: defaultConfig.default_model,
      modelParams: defaultParams
    };
    // 安全日志：不打印包含API密钥的完整配置
    console.log('[Chat] 模型配置完成:', completeModelSettings.modelService, '/', completeModelSettings.modelName);

      // 4. 直接创建会话（已在 ModelConfig 中测试过，无需重复测试）
      const newSession = await createSession(completeModelSettings, systemPrompt);
      console.log('[Chat] 新会话创建成功');
      message.success('新会话创建成功');

      // 5. 切换到新创建的会话
      if (newSession) {
        await handleSessionChange(newSession);
      }
    } catch (error) {
      console.error('[Chat] 创建会话失败:', error);
      message.error('创建会话失败');
    } finally {
      setIsProcessing(false);
    }
  };

  // 处理退出登录
  const handleLogout = () => {
    console.log('[Chat] 用户请求退出登录');
    logout();
  };

  // 注销账号
  const handleDeleteAccount = useCallback(() => {
    if (deletingAccount) return;
    Modal.confirm({
      title: '确认注销账号',
      content: '此操作将删除该账号下的所有传统会话、所有智能助手会话以及该账号在 MinIO 中的所有图片（users/{user_id}/ 前缀）。操作不可恢复，确定继续吗？',
      okText: '永久删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          setDeletingAccount(true);
          await authAxios.delete(getFullUrl('/api/auth/account'));
          message.success('账号已注销');
          try { logout(); } catch {}
          localStorage.removeItem('token');
          navigate('/welcome');
        } catch (e: any) {
          message.error(e?.message || '注销失败');
        } finally {
          setDeletingAccount(false);
        }
      }
    });
  }, [deletingAccount, navigate]);

  // 添加滚动事件监听
  useEffect(() => {
    const container = messageListRef.current;
    if (container) {
      container.addEventListener('scroll', handleScroll);
      return () => container.removeEventListener('scroll', handleScroll);
    }
  }, [handleScroll]);

  // 清理平滑滚动定时器
  useEffect(() => {
    return () => {
      stopSmoothScroll();
    };
  }, [stopSmoothScroll]);

  // 会话切换时的标志
  const isSessionSwitchingRef = useRef(false);
  const prevSessionIdRef = useRef<string | null>(null);
  const clearSwitchingFlagTimerRef = useRef<number | null>(null);
  const [isMessagesVisible, setIsMessagesVisible] = useState(true); // 控制消息列表可见性
  
  // 会话切换时，重置状态（不依赖 messages.length，避免加载历史消息时重复触发）
  useEffect(() => {
    const currentSessionId = currentSession?.session_id || null;
    
    // 检测会话切换
    if (currentSessionId !== prevSessionIdRef.current) {
      console.log('[Scroll] 检测到会话切换:', prevSessionIdRef.current, '->', currentSessionId);
      prevSessionIdRef.current = currentSessionId;
      
      // 清除之前的定时器
      if (clearSwitchingFlagTimerRef.current) {
        clearTimeout(clearSwitchingFlagTimerRef.current);
        clearSwitchingFlagTimerRef.current = null;
      }
      
      // 🔑 隐藏消息列表，避免显示顶部内容
      setIsMessagesVisible(false);
      
      // 设置会话切换标志，阻止平滑滚动
      isSessionSwitchingRef.current = true;
      
      // 重置自动滚动状态
      isUserScrollingRef.current = false;
      setShouldAutoScroll(true);
      stopSmoothScroll();
      
      console.log('[Scroll] 会话切换标志已设置，消息列表已隐藏');
    }
  }, [currentSession?.session_id, stopSmoothScroll]);
  
  // 监听消息加载完成，在会话切换后滚动到底部
  useEffect(() => {
    // 只在会话切换标志为 true 时执行
    if (!isSessionSwitchingRef.current) {
      return;
    }
    
    // 等待消息渲染完成后，瞬间滚动到底部
    const container = messageListRef.current;
    if (container && messages.length > 0) {
      console.log('[Scroll] 会话切换 - 消息更新，准备瞬间滚动到底部，消息数量:', messages.length);
      
      // 使用 requestAnimationFrame 确保 DOM 已更新
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (container && isSessionSwitchingRef.current) {
            const targetScrollTop = container.scrollHeight;
            console.log('[Scroll] 会话切换 - 瞬间滚动到底部:', targetScrollTop);
            container.scrollTop = targetScrollTop;
            
            // 🔑 滚动完成后立即显示消息列表
            setIsMessagesVisible(true);
          }
        });
      });
      
      // 🔑 使用防抖机制：每次消息更新都重置定时器
      // 只有在消息不再更新（500ms内没有新消息）后，才清除会话切换标志
      if (clearSwitchingFlagTimerRef.current) {
        clearTimeout(clearSwitchingFlagTimerRef.current);
      }
      
      clearSwitchingFlagTimerRef.current = window.setTimeout(() => {
        console.log('[Scroll] 会话切换 - 消息加载完成（500ms内无新消息），清除会话切换标志');
        isSessionSwitchingRef.current = false;
        clearSwitchingFlagTimerRef.current = null;
      }, 500);
    }
  }, [messages]);

  // 在消息更新后触发平滑滚动
  useEffect(() => {
    // 如果正在切换会话，不启动平滑滚动
    if (isSessionSwitchingRef.current) {
      return;
    }
    
    if (shouldAutoScroll && !isUserScrollingRef.current) {
      // 如果处于自动滚动状态且用户没有手动滚动，启动平滑滚动
      startSmoothScrollToBottom();
    }
  }, [messages, shouldAutoScroll, startSmoothScrollToBottom]);

  // 监听"正在输入中..."气泡的显示，自动平滑滚动到底部
  useEffect(() => {
    if (isModelTyping) {
      console.log('[Scroll] "正在输入中..."气泡显示，触发平滑滚动到底部');
      
      // 等待 DOM 更新后再滚动
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          startSmoothScrollToBottom();
        });
      });
    }
  }, [isModelTyping, startSmoothScrollToBottom]);

  // 监听 VAD 状态变化，更新 UI 状态
  useEffect(() => {
    console.log('[VAD状态监听] 状态变化:', {
      isRecording,
      isSpeaking,
      isTranscribing,
      currentVadStatus: vadStatus
    });

    if (isTranscribing) {
      // 转录中
      console.log('[VAD状态] → transcribing (转录中)');
      setVadStatus('transcribing');
    } else if (isRecording) {
      if (isSpeaking) {
        // 正在说话
        console.log('[VAD状态] → speaking (检测到语音)');
        setVadStatus('speaking');
      } else {
        // 这里需要区分两种情况：
        // 1. 刚开始录音，还没检测到语音 -> 保持 'recording' 状态
        // 2. 检测到语音后又静音了 -> 设置为 'silence'
        // 我们通过检查当前状态来判断
        setVadStatus(prev => {
          // 如果之前是 speaking，现在不说话了，说明进入静音倒计时
          if (prev === 'speaking') {
            console.log('[VAD状态] → silence (静音倒计时)');
            return 'silence';
          }
          // 否则保持 recording 状态（等待检测到语音）
          console.log('[VAD状态] → recording (等待语音)');
          return 'recording';
        });
      }
    } else {
      // 既不录音也不转录
      console.log('[VAD状态] → idle (空闲)');
      setVadStatus('idle');
    }
  }, [isRecording, isSpeaking, isTranscribing]);

  // 播放音频（使用队列播放器）
  const playAudio = useCallback((audioUrl: string, sequence?: number) => {
    console.log('[Chat] playAudio 被调用，enableVoice:', enableVoice, 'audioUrl:', audioUrl, 'sequence:', sequence);
    
    if (!enableVoice) {
      console.log('[Chat] 语音播放已关闭，跳过音频播放');
      return;
    }
    
    // 使用相对路径，通过 Vite 代理访问（开发环境）或直接访问（生产环境）
    console.log('[Chat] 添加音频到队列（相对路径）:', audioUrl, 'sequence:', sequence);
    
    // 添加到音频队列（带序号）
    addToQueue(audioUrl, sequence);
  }, [enableVoice, addToQueue]);

  // 播放Base64音频数据（优化版：使用异步解码，避免阻塞主线程）
  const playAudioData = useCallback((audioData: string, mimeType: string, sequence?: number) => {
    console.log('[Chat] playAudioData 被调用，enableVoice:', enableVoice, 'mimeType:', mimeType, 'sequence:', sequence);
    
    if (!enableVoice) {
      console.log('[Chat] 语音播放已关闭，跳过音频播放');
      return;
    }
    
    // 使用 requestIdleCallback 或 setTimeout 异步解码，避免阻塞主线程
    const decodeAsync = () => {
      try {
        // 优化方法1: 使用 fetch API 的 data URL（浏览器内部优化）
        const dataUrl = `data:${mimeType};base64,${audioData}`;
        
        // 直接使用 data URL，浏览器会在需要时才解码
        console.log('[Chat] 添加Base64音频到队列:', mimeType, '数据长度:', audioData.length, 'sequence:', sequence);
        
        // 添加到音频队列（带序号）
        addToQueue(dataUrl, sequence);
      } catch (error) {
        console.error('[Chat] Base64音频处理失败:', error);
      }
    };
    
    // 使用 requestIdleCallback（空闲时处理）或 setTimeout（降级方案）
    if ('requestIdleCallback' in window) {
      requestIdleCallback(decodeAsync);
    } else {
      setTimeout(decodeAsync, 0);
    }
  }, [enableVoice, addToQueue]);

  // 建立WebSocket连接
  const establishConnection = () => {
    // 🚫 跳过群聊会话（群聊有专门的 WebSocket 管理）
    if (currentSession?.session_type === 'group') {
      console.log('[Chat] 跳过群聊会话，使用专门的群聊 WebSocket');
      return;
    }
    
    // 检查是否有当前会话
    if (!currentSession?.session_id) {
      console.log('[Chat] 提示：当前没有选择会话');
      return;
    }

    // 更新当前会话ID引用
    currentSessionIdRef.current = currentSession!.session_id;

    // 构建WebSocket URL - 根据当前页面协议自动选择 ws 或 wss
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host; // 使用当前页面的 host
    const wsUrl = `${protocol}//${host}/api/chat/ws/chat/${currentSession!.session_id}`;

    console.log('[Chat] 使用连接管理器建立WebSocket连接:', wsUrl);
    // 在发起新连接后短时间内抑制重连提示，避免创建/切换会话时的瞬时抖动误报
    suppressReconnectToastUntilRef.current = Date.now() + 4000;

    // 更新会话上下文并注册回调
    chatWSManager.updateSessionContext({ url: wsUrl, sessionId: currentSessionIdRef.current! });
    chatWSManager.setCallbacks({
      onOpen: () => {
        reconnectAttemptsRef.current = 0;
        hasEverOpenedRef.current = true;
        // 请求会话历史
        chatWSManager.send({ type: 'fetch_history', session_id: currentSession!.session_id });
      },
      onAuthSuccess: () => {
        console.log('[Chat] 认证成功');
      },
      onMessage: (event: MessageEvent) => {
        const expectedSessionId = currentSession?.session_id;
        if (currentSessionIdRef.current !== expectedSessionId) {
          console.log('[Chat] 忽略非当前会话的消息');
          return;
        }
        try {
          const data = JSON.parse(event.data);
          console.debug('[Chat] WS 消息到达:', { type: data?.type, hasContent: Boolean(data?.content), hasRef: Boolean(data?.reference), raw: data });
          if (data.type === 'error') {
            console.error('[Chat] 收到错误消息:', data.content);
            
            // 检查是否是异常数据注入错误
            if (data.content?.includes('异常数据') || data.content?.includes('过长') || data.content?.includes('异常注入')) {
              Modal.error({
                title: '检测到异常响应',
                content: (
                  <div>
                    <p>系统检测到AI返回了异常长度的响应，这可能是：</p>
                    <ul>
                      <li>模型输出异常</li>
                      <li>提示词导致的无限循环</li>
                      <li>系统被恶意注入</li>
                    </ul>
                    <p style={{ marginTop: 12, color: '#ff4d4f' }}>
                      <strong>为保护您的浏览器不崩溃，此次请求已被拒绝且未保存。</strong>
                    </p>
                    <p style={{ marginTop: 8 }}>
                      建议：请尝试简化问题、减少上下文或更换提示词后重新发送。
                    </p>
                  </div>
                ),
                okText: '我知道了',
                width: 520,
              });
            } else {
              message.error(data.content);
            }
            
            setIsModelTyping(false);
            setIsProcessing(false);
            return;
          }
          if (data.type === 'done') {
            // done 时兜底附着一次 pending 引用
            if (pendingReferenceRef.current) {
              const pending = pendingReferenceRef.current;
              console.debug('[Chat] done 阶段附着 pending 引用，条数:', Array.isArray(pending) ? pending.length : (pending ? 1 : 0));
              setMessages(prevMessages => {
                const last = prevMessages[prevMessages.length - 1];
                if (last && last.role === 'assistant') {
                  const hasRef = Array.isArray(last.reference) ? last.reference.length > 0 : Boolean(last.reference);
                  if (!hasRef) {
                    const updated = [...prevMessages];
                    updated[updated.length - 1] = { ...last, reference: pending } as any;
                    return updated;
                  }
                }
                return prevMessages;
              });
              pendingReferenceRef.current = null;
            }
            if (!data.success) {
              console.error('[Chat] 处理失败:', data.error);
              if (!data.error?.includes?.('API调用失败')) {
                message.error(data.error || '处理失败');
              }
            } else {
              // 处理成功时的逻辑
              setMessages(prevMessages => {
                const updatedMessages = [...prevMessages];
                
                // 🔑 如果有 user_timestamp，更新最后一条用户消息的时间戳
                if (data.user_timestamp) {
                  for (let i = updatedMessages.length - 1; i >= 0; i--) {
                    if (updatedMessages[i].role === 'user') {
                      updatedMessages[i] = { ...updatedMessages[i], timestamp: data.user_timestamp } as any;
                      console.log('[Chat] 已更新用户消息时间戳:', data.user_timestamp);
                      break;
                    }
                  }
                }
                
                // 如果有保存的图片，更新用户消息
                if (data.saved_images && data.saved_images.length > 0) {
                  for (let i = updatedMessages.length - 1; i >= 0; i--) {
                    if (updatedMessages[i].role === 'user') {
                      updatedMessages[i] = { ...updatedMessages[i], images: data.saved_images } as any;
                      break;
                    }
                  }
                }
                
                // 🔑 如果有 assistant_timestamp，更新最后一条 AI 消息的时间戳
                if (data.assistant_timestamp) {
                  for (let i = updatedMessages.length - 1; i >= 0; i--) {
                    if (updatedMessages[i].role === 'assistant') {
                      updatedMessages[i] = { ...updatedMessages[i], timestamp: data.assistant_timestamp } as any;
                      console.log('[Chat] 已更新AI消息时间戳:', data.assistant_timestamp);
                      break;
                    }
                  }
                }
                
                // 🆕 如果有 graph_metadata，更新最后一条 AI 消息的图谱元数据
                if (data.graph_metadata && Array.isArray(data.graph_metadata) && data.graph_metadata.length > 0) {
                  for (let i = updatedMessages.length - 1; i >= 0; i--) {
                    if (updatedMessages[i].role === 'assistant') {
                      updatedMessages[i] = { ...updatedMessages[i], graph_metadata: data.graph_metadata } as any;
                      console.log('[Chat] 已更新AI消息图谱元数据:', data.graph_metadata.length, '个图谱');
                      break;
                    }
                  }
                }
                
                return updatedMessages;
              });
            }
              if (currentSession) {
                setMessages(prevMessages => {
                  const currentMessages = prevMessages.length;
                    updateSessionMessageCount(currentSession.session_id, currentMessages);
                    setMessageCountUpdated(true);
                  return prevMessages;
                });
            }
            setIsModelTyping(false);
            setIsProcessing(false);
            return;
          }
          if (data.type === 'history') {
            // 企业级懒加载：使用专门的处理函数
            const converted: ChatMessage[] = (data.messages || []).map((msg: any) => ({
              role: msg.role,
              content: msg.content || '',
              timestamp: msg.timestamp || msg.create_time || msg.created_at,
              images: msg.images,
              reference: msg.reference, // 这里后端已经尽量展开为富引用
              graph_metadata: msg.graph_metadata, // 🆕 知识图谱元数据
              id: msg.id
            }));
            
            handleInitialHistory({
              messages: converted,
              total: data.total,
              loaded: data.loaded,
              has_more: data.has_more
            });
            
            console.log('[Chat] 收到历史消息（懒加载）:', {
              显示消息数: converted.length,
              总消息数: data.total,
              还有更多: data.has_more
            });
            return;
          }
          
          // 🎯 处理工具状态消息（仅记录日志，不在浮动气泡中显示）
          if (data.type === 'tool_status') {
            const toolName = data.tool || '工具';
            const status = data.status;
            
            // 仅在控制台记录工具状态，不更新UI
            if (status === 'calling') {
              console.log(`[Chat] 🔧 工具调用中: ${toolName}`, data.args);
            } else if (status === 'success') {
              console.log(`[Chat] ✅ 工具成功: ${toolName}`);
            } else if (status === 'error') {
              console.error(`[Chat] ❌ 工具失败: ${toolName}`, data.error);
            }
            
            // 不显示在浮动气泡中，直接返回
            return;
          }
          
          if (data.type === 'message') {
            setIsModelTyping(false);
            let didAttachPending = false;
            setMessages(prevMessages => {
              const last = prevMessages[prevMessages.length - 1];
              const attachReference = (msg: any) => {
                if (!pendingReferenceRef.current) return msg;
                const hasRef = Array.isArray((msg as any).reference)
                  ? ((msg as any).reference as any[]).length > 0
                  : Boolean((msg as any).reference);
                if (!hasRef) {
                  console.debug('[Chat] message 阶段附着 pending 引用');
                  didAttachPending = true;
                  return { ...msg, reference: pendingReferenceRef.current };
                }
                return msg;
              };
              if (last && last.role === 'assistant') {
                const updated = [...prevMessages];
                const normalizedRef = (() => {
                  let r = data.reference?.chunks || data.reference;
                  if (r && !Array.isArray(r)) {
                    if (typeof r === 'object') r = Object.values(r);
                    else r = [r];
                  }
                  return r;
                })();
                if (normalizedRef) {
                  console.debug('[Chat] 收到内嵌引用(normalized):', Array.isArray(normalizedRef) ? normalizedRef.length : 1);
                }
                
                // 🛡️ 前端防护：检查chunk和总内容长度
                const MAX_CONTENT_LENGTH = 1000000; // 100万字符限制
                const MAX_CHUNK_LENGTH = 100000; // 单个chunk 10万字符限制
                const incomingChunk = data.content || '';
                const currentContent = last.content || '';
                
                // 检查单个chunk长度
                if (incomingChunk.length > MAX_CHUNK_LENGTH) {
                  console.error(`⚠️ 前端检测到异常大的chunk！长度=${incomingChunk.length}`);
                  console.error(`异常chunk前500字符: ${incomingChunk.substring(0, 500)}`);
                  message.error('检测到异常数据，已停止接收');
                  return prevMessages;
                }
                
                // 检查累积内容长度
                const newTotalLength = currentContent.length + incomingChunk.length;
                if (newTotalLength > MAX_CONTENT_LENGTH) {
                  console.error(`⚠️ 前端内容长度超限！当前=${currentContent.length}，chunk=${incomingChunk.length}，总计=${newTotalLength}`);
                  message.warning('响应内容过长，已停止接收');
                  return prevMessages;
                }
                
                const merged = { ...last, content: currentContent + incomingChunk, reference: normalizedRef || last.reference } as any;
                updated[updated.length - 1] = attachReference(merged) as any;
                
                // 🆕 实时检测并展开 think 内容
                const newContent = merged.content;
                if (newContent.includes('<think>')) {
                  // 正在输出或已输出 think 内容，立即展开所有 think 部分
                  const parts = parseThinkingContent(newContent);
                  const messageId = last.timestamp || `msg-${prevMessages.length - 1}`;
                  
                  parts.forEach((part, index) => {
                    if (part.type === 'thinking') {
                      const stateKey = `${messageId}-think-${index}`;
                      setThinkingSectionStates(prev => {
                        if (!prev[stateKey]) {
                          console.log('[Chat] 🔓 实时展开 think 内容:', stateKey);
                          return { ...prev, [stateKey]: true };
                        }
                        return prev;
                      });
                    }
                  });
                }
                
                return updated;
              }
              const normalizedRef = (() => {
                let r = data.reference?.chunks || data.reference;
                if (r && !Array.isArray(r)) {
                  if (typeof r === 'object') r = Object.values(r);
                  else r = [r];
                }
                return r;
              })();
              if (normalizedRef) {
                console.debug('[Chat] 首条助手消息附带引用(normalized):', Array.isArray(normalizedRef) ? normalizedRef.length : 1);
              }
              // 使用后端返回的时间戳（如果有），否则使用当前时间
              const aiTimestamp = data.assistant_timestamp || new Date().toISOString();
              // 生成唯一ID，确保key稳定（即使timestamp后续被更新）
              const messageId = data.message_id || `temp-ai-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
              const created = attachReference({ role: 'assistant', content: data.content || '', timestamp: aiTimestamp, reference: normalizedRef, id: messageId } as any);
              
              // 🆕 实时检测并展开 think 内容（首条消息）
              const content = data.content || '';
              if (content.includes('<think>')) {
                const parts = parseThinkingContent(content);
                parts.forEach((part, index) => {
                  if (part.type === 'thinking') {
                    const stateKey = `${aiTimestamp}-think-${index}`;
                    setThinkingSectionStates(prev => {
                      if (!prev[stateKey]) {
                        console.log('[Chat] 🔓 实时展开 think 内容（首条）:', stateKey);
                        return { ...prev, [stateKey]: true };
                      }
                      return prev;
                    });
                  }
                });
              }
              
              return [...prevMessages, created as any];
            });
            // 仅在实际附着后才清空缓存
            if (didAttachPending) {
              console.debug('[Chat] 已清空 pending 引用');
              pendingReferenceRef.current = null;
            } else {
              console.debug('[Chat] 未附着 pending 引用，保留以待 done 阶段');
            }
            return;
          }
          if (data.type === 'reference') {
            // 仅缓存引用，等待消息气泡出现后再附着，避免创建空气泡
                let referenceData: any = data.reference?.chunks || data.reference;
            if (referenceData) {
              // 统一展开为数组

              const maybeChunks = (referenceData as any)?.chunks;
              if (Array.isArray(maybeChunks)) {
                referenceData = maybeChunks;
              } else if (!Array.isArray(referenceData)) {
                  if (typeof referenceData === 'object') referenceData = Object.values(referenceData);
                  else referenceData = [referenceData];
                }
            }
            console.debug('[Chat] 收到引用事件，规范化后条数:', Array.isArray(referenceData) ? referenceData.length : (referenceData ? 1 : 0), referenceData?.[0]);
            // 如果已经有最后一条助手消息，将引用追加到现有引用数组中
            let attachedImmediately = false;
            setMessages(prev => {
              const last = prev[prev.length - 1];
              if (last && last.role === 'assistant') {
                // 🔧 修复：追加引用而不是覆盖
                const updated = [...prev];
                const existingRefs = Array.isArray(last.reference) ? last.reference : [];
                const newRefs = Array.isArray(referenceData) ? referenceData : [];
                updated[updated.length - 1] = { 
                  ...last, 
                  reference: [...existingRefs, ...newRefs] 
                } as any;
                attachedImmediately = true;
                console.debug(`[Chat] 引用事件追加到现有助手消息 (已有${existingRefs.length}条，新增${newRefs.length}条，总计${existingRefs.length + newRefs.length}条)`);
                return updated;
              }
              return prev;
            });
            if (!attachedImmediately) {
              // 否则缓存，等 message/done 再附着
              // 🔧 修复：追加到pending引用
              const existingPending = Array.isArray(pendingReferenceRef.current) ? pendingReferenceRef.current : [];
              const newRefs = Array.isArray(referenceData) ? referenceData : [];
              pendingReferenceRef.current = [...existingPending, ...newRefs];
              console.debug(`[Chat] 追加引用到 pending (已有${existingPending.length}条，新增${newRefs.length}条，总计${existingPending.length + newRefs.length}条)`);
            } else {
              console.debug('[Chat] 已在引用事件中完成附着，不缓存 pending');
            }
            return;
          }
          if (data.type === 'audio') {
            console.log('[Chat] 收到音频消息:', data);
            if (enableVoice) { 
              // 判断是Base64数据还是URL
              if (data.data && data.mime_type) {
                console.log('[Chat] 语音已启用，调用 playAudioData，类型:', data.mime_type, '序号:', data.sequence);
                playAudioData(data.data, data.mime_type, data.sequence);
              } else if (data.file) {
                console.log('[Chat] 语音已启用，调用 playAudio，文件路径:', data.file, '序号:', data.sequence);
                playAudio(data.file, data.sequence);
              }
            } else {
              console.log('[Chat] 语音未启用，跳过播放');
            }
            return;
          }
          
          // 处理TTS失败消息
          if (data.type === 'audio_failed') {
            console.warn('[Chat] TTS失败:', { sequence: data.sequence, text: data.text, error: data.error });
            if (enableVoice && data.sequence !== undefined) {
              // 跳过失败的序号
              skipSequence(data.sequence, `TTS失败: ${data.error}`);
              // 可选：显示错误提示
              message.warning(`语音合成失败 (序号${data.sequence}): ${data.text?.substring(0, 30)}...`);
            }
            return;
          }
        } catch (error) {
          console.error('[Chat] 解析WebSocket消息失败:', error);
          message.error('消息处理失败');
          setIsProcessing(false);
        }
      },
      onClose: () => {
        setIsModelTyping(false);
      },
      onError: () => {
        if (hasEverOpenedRef.current && Date.now() > suppressReconnectToastUntilRef.current) {
          message.error('连接中断，正在尝试重连...');
        }
        setIsModelTyping(false);
      }
    });

    // 发起连接
    chatWSManager.connect();
  };

  // 处理移动端侧边栏切换
  const toggleMobileSider = () => {
    setSiderVisible(prev => !prev);
  };

  // 处理移动端侧边栏关闭
  const handleOverlayClick = () => {
    if (isMobile) {
      setSiderVisible(false);
    }
  };

  // 渲染遮罩层
  const renderOverlay = () => {
    if (!isMobile) return null;
    return (
      <div 
        className={`${styles.overlay} ${siderVisible ? styles.overlayVisible : ''}`}
        onClick={handleOverlayClick}
      />
    );
  };

  // 修改会话切换处理函数
  const handleSessionChange = useCallback(async (session: ChatSession | null) => {
    console.log('[Chat] 切换传统会话:', session);
    
    // 🔒 防止重复点击：如果点击的是当前会话，直接返回
    if (session?.session_id === currentSession?.session_id) {
      console.log('[Chat] ⚠️ 重复点击当前会话，忽略操作');
      // 仅在移动端关闭侧边栏
      if (isMobile) {
        setSiderVisible(false);
      }
      return;
    }
    
    // 在移动端关闭侧边栏
    if (isMobile) {
      setSiderVisible(false);
    }
    
    // 清理当前WebSocket连接
    cleanupWebSocket();
    
    // 🆕 断开群聊WebSocket并清除群聊ID（切换到非群聊会话）
    disconnectGroupWebSocket();
    clearCurrentGroup();
    
    // 更新当前会话ID引用
    currentSessionIdRef.current = session?.session_id || null;
    
    // 企业级优化：重置懒加载状态
    resetLazyLoad();
    
    // 重置消息数量更新标志
    setMessageCountUpdated(false);
    
    // 清理深度思考状态
    setThinkingSectionStates({});
    
    // 重置滚动状态，确保新会话能自动滚动到底部
    isUserScrollingRef.current = false;
    setShouldAutoScroll(true);
    stopSmoothScroll();
    
    // 设置新的当前会话（使用 store 最新对象以确保包含 kb_settings 等最新字段）
    const refreshed = session ? (sessions.find(s => s.session_id === session.session_id) || session) : null;
    setCurrentSession(refreshed as any);
    
    // 检查新会话是否支持图片
    if (session) {
      const sessionModelService = session.model_settings.modelService;
      const sessionModelName = session.model_settings.modelName;
      const supportsImage = checkModelSupportsImage(sessionModelService, sessionModelName);
      
      setCurrentSessionSupportsImage(supportsImage);
    } else {
      setCurrentSessionSupportsImage(false);
    }
  }, [isMobile, cleanupWebSocket, disconnectGroupWebSocket, clearCurrentGroup, setCurrentSession, resetLazyLoad, currentSession, stopSmoothScroll, checkModelSupportsImage, sessions]);
  
  // 处理群聊选择
  const handleGroupSelect = useCallback((group: Group) => {
    console.log('[Chat] 🔄 切换到群聊:', group.name);
    
    // 🔒 防止重复点击
    if (currentGroupId === group.group_id && currentSession?.session_type === 'group') {
      console.log('[Chat] ⚠️ 重复点击当前群聊，忽略操作');
      if (isMobile) {
        setSiderVisible(false);
      }
      return;
    }
    
    // 在移动端关闭侧边栏
    if (isMobile) {
      setSiderVisible(false);
    }
    
    // 清理传统WebSocket连接
    cleanupWebSocket();
    
    // 断开旧的群聊WebSocket
    disconnectGroupWebSocket();
    
    // 创建群聊会话对象
    const groupSession: ChatSession = {
      session_id: `group_${group.group_id}`,
      name: group.name,
      created_at: group.created_at,
      model_settings: {
        modelService: '',
        baseUrl: '',
        apiKey: '',
        modelName: ''
      },
      session_type: 'group',
      group_id: group.group_id,
      role_avatar_url: group.avatar
    };
    
    setCurrentSession(groupSession);
    selectGroup(group.group_id);
    
    // 连接群聊WebSocket
    const token = useAuthStore.getState().token;
    if (token && user?.id) {
      connectGroupWebSocket(group.group_id, user.id, token);
    }
    
    // 重置状态
    resetLazyLoad();
    setMessageCountUpdated(false);
    isUserScrollingRef.current = false;
    setShouldAutoScroll(true);
    
  }, [currentGroupId, currentSession, isMobile, cleanupWebSocket, disconnectGroupWebSocket, selectGroup, connectGroupWebSocket, user?.id, resetLazyLoad]);
  
  // 新增：传统会话 - 头部菜单
  const getTraditionalHeaderMenu = () => ({
    items: [
      {
        key: 'batchDeleteTraditional',
        icon: <DeleteOutlined />,
        label: '批量删除传统会话',
      },
    ],
    onClick: ({ key, domEvent }: any) => {
        domEvent.stopPropagation();
        if (key === 'batchDeleteTraditional') {
          // 默认不选中任何会话
          setSelectedTraditionalSessionIds([]);
          setTraditionalBatchModalVisible(true);
        }
    },
  });

  // 新增：传统会话 - 执行批量删除
  const handleBatchDeleteTraditionalSessions = async () => {
    const idsToDelete = selectedTraditionalSessionIds;
    if (!idsToDelete || idsToDelete.length === 0) {
      message.warning('请先选择要删除的会话');
      return;
    }
    try {
      await Promise.all(idsToDelete.map(id => deleteSession(id)));
      message.success('选中的传统会话已删除');
      setSelectedTraditionalSessionIds([]);
      setTraditionalBatchModalVisible(false);
    } catch (e) {
      console.error('[Chat] 批量删除传统会话失败:', e);
      message.error('批量删除失败，请重试');
    }
  };

  // 在会话变化时立即重新建立连接（避免发送前URL/会话ID尚未更新）
  useEffect(() => {
    if (currentSession) {
      console.log('[Chat] 当前会话变化，立即建立连接', {
        会话: currentSession?.session_id
      });
      establishConnection();
      return;
    }
    
    // 组件卸载时清理连接
    return () => {
      console.log('[Chat] 组件卸载，清理WebSocket连接');
      cleanupWebSocket();
    };
  }, [currentSession]);

  // 检查当前会话的图片支持状态
  useEffect(() => {
    if (currentSession) {
      const sessionModelService = currentSession.model_settings.modelService;
      const sessionModelName = currentSession.model_settings.modelName;
      const supportsImage = checkModelSupportsImage(sessionModelService, sessionModelName);
      
      setCurrentSessionSupportsImage(supportsImage);
    } else {
      setCurrentSessionSupportsImage(false);
    }
  }, [currentSession, checkModelSupportsImage]);

  // 修改发送消息的函数
  const sendMessage = async (override?: { text?: string; files?: File[]; previews?: string[] }) => {
    console.log('[Chat] 开始发送消息流程');
    const overrideText = override?.text;
    const overrideFiles = override?.files;
    const overridePreviews = override?.previews;

    const effectiveMessage = overrideText !== undefined ? overrideText : currentMessage;
    const effectiveFiles = overrideFiles !== undefined ? overrideFiles : selectedImages;
    const effectivePreviews = overridePreviews !== undefined ? overridePreviews : imagePreviews;

    console.log('[Chat] 当前消息内容:', effectiveMessage);
    console.log('[Chat] 当前会话:', currentSession);

    if (!effectiveMessage.trim() && effectiveFiles.length === 0) {
      console.log('[Chat] 消息为空且无图片，终止发送');
      return;
    }

    if (isProcessing) {
      console.log('[Chat] 正在处理中，终止发送');
      return;
    }
    
    // 🆕 群聊模式：使用群聊 WebSocket 发送
    if (currentSession?.session_type === 'group' && currentGroupId) {
      console.log('[Chat] 群聊模式发送消息');
      
      // 🔥 提取@提及的成员ID
      const mentions: string[] = [];
      const mentionRegex = /@([^\s@]+)/g;
      let match;
      
      // 获取当前群组的所有成员
      const currentGroup = groups.find(g => g.group_id === currentGroupId);
      if (currentGroup?.members) {
        while ((match = mentionRegex.exec(effectiveMessage)) !== null) {
          const mentionedName = match[1];
          // 查找匹配的成员（通过昵称）
          const member = currentGroup.members.find(m => 
            m.nickname === mentionedName
          );
          if (member && !mentions.includes(member.member_id)) {
            mentions.push(member.member_id);
          }
        }
      }
      
      console.log('[Chat] 检测到@提及:', mentions);
      sendGroupMessage(effectiveMessage, effectiveFiles.map(f => f.name), mentions);
      setCurrentMessage('');
      setSentFlag(false);  // 重置发送标记
      setSelectedImages([]);
      setImagePreviews([]);
      return;
    }
    
    // 🎙️ 清空音频队列（发送新消息时停止当前播放）
    clearQueue();
    
    // 发送前确保上下文（URL/会话ID）已与当前选择对齐，避免切换后使用旧连接
    try {
      // 使用当前页面的 host 和 protocol，通过 Vite 代理连接后端
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      if (!currentSession?.session_id) {
        message.warning('未选择会话');
        return;
      }
      const wsUrl = `${protocol}//${host}/api/chat/ws/chat/${currentSession.session_id}`;
      chatWSManager.updateSessionContext({ url: wsUrl, sessionId: currentSession.session_id });
    } catch {}

    // 确保连接与鉴权（复用全局连接，不重复构建）
    const authorized = await chatWSManager.ensureAuthorized(8000);
    if (!authorized) {
      message.error('连接未就绪，已取消发送，请稍后重试');
      return;
    }

    try {
      setIsProcessing(true);
      setIsImageUploading(true);

      // 准备消息内容
      let messageContent = effectiveMessage;
      let imagesBase64: string[] = [];

      // 如果有图片，转换为base64
      if (effectiveFiles.length > 0) {
        try {
          imagesBase64 = await convertImagesToBase64(effectiveFiles);
          console.log(`[Chat] ${effectiveFiles.length} 张图片已转换为base64`);
        } catch (error) {
          console.error('[Chat] 图片转换失败:', error);
          message.error('图片处理失败，请重试');
          setIsProcessing(false);
          setIsImageUploading(false);
          return;
        }
      }

      // 添加用户消息到显示列表
      const userMessage: ChatMessage = {
        role: 'user',
        content: effectiveMessage || (effectiveFiles.length > 0 ? `[${effectiveFiles.length}张图片]` : ''),
        timestamp: new Date().toISOString(),
        images: effectiveFiles.length > 0 ? effectivePreviews : undefined
      };
      
      // 立即添加用户消息，确保头像和内容立即显示
      setMessages(prev => [...prev, userMessage]);
      // 重置消息数量更新标志
      setMessageCountUpdated(false);
      
      // 用户发送消息后，启用自动滚动并重置用户滚动标志
      isUserScrollingRef.current = false;
      setShouldAutoScroll(true);
      
      // 用户消息已添加，等待DOM更新后滚动到底部
      setTimeout(() => {
        const container = messageListRef.current;
        if (container) {
          // 瞬间跳转到底部，确保用户看到自己发送的消息
          container.scrollTop = container.scrollHeight;
        }
      }, 0);

      // 发送消息
      const messageData: any = {
        message: messageContent,
        images: imagesBase64,
        session_id: currentSession?.session_id,
        model_settings: currentSession?.model_settings,
        enable_voice: enableVoice,
        enable_text_cleaning: enableTextCleaning,
        text_cleaning_patterns: textCleaningPatterns, // 正则表达式（换行分隔）
        preserve_quotes: preserveQuotes, // 是否保留引号内容
        kb_settings: (currentSession as any)?.kb_settings, // 添加知识库配置
        referenced_docs: referencedDocs.length > 0 ? referencedDocs.map(doc => ({
          doc_id: doc.docId,
          filename: doc.filename
        })) : undefined // 🆕 引用的文档列表
      };
      
      // 安全日志：不打印包含API密钥的模型配置和消息数据
      const modelService = currentSession?.model_settings?.modelService || '未知';
      const modelName = currentSession?.model_settings?.modelName || '未知';
      console.log('[Chat] 发送消息 - 模型:', modelService, '/', modelName);
      console.log('[Chat] 语音开关状态:', enableVoice);
      console.log('[Chat] 是否包含图片:', imagesBase64.length > 0);
      console.log('[Chat] 图片数量:', imagesBase64.length);
      chatWSManager.send(messageData);
      console.log('[Chat] 消息已通过WebSocket发送');

      setCurrentMessage('');
      setSelectedImages([]);
      setImagePreviews([]);
      // 注意：不自动清空引用文档，让用户自己决定何时删除
      setSentFlag(false); // 发送消息后重置发送标记
      
      // 延迟设置模型正在输入状态，确保用户消息先显示
      setTimeout(() => {
        setIsModelTyping(true);
        setTypingText('正在输入中...'); // 🎯 重置为默认提示
      }, 100);
      
      // 延迟更新当前会话的消息数量，避免干扰消息显示
      setTimeout(() => {
        if (!messageCountUpdated && currentSession) {
          // 更新会话消息数量
          setMessages(prevMessages => {
            const newMessageCount = prevMessages.length;
            const sessionMessageCount = currentSession.message_count || 0;
            if (sessionMessageCount !== newMessageCount) {
              console.log('[Chat] 发送消息后更新会话消息数量:', newMessageCount);
              updateSessionMessageCount(currentSession.session_id, newMessageCount);
              setMessageCountUpdated(true);
            }
            return prevMessages;
          });
        }
      }, 100);
    } catch (error) {
      console.error('[Chat] 发送消息失败:', error);
      message.error('发送消息失败，请重试');
    } finally {
      setIsProcessing(false);
      setIsImageUploading(false);
    }
  };

  // 显示错误消息
  useEffect(() => {
    if (error) {
      console.log('[Chat] 显示错误消息:', error);
      message.error(error);
    }
  }, [error]);



  // 处理会话删除
  const handleDelete = async (session: ChatSession) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个会话吗？此操作不可恢复。',
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { 
        className: styles.deleteButton
      },
      onOk: async () => {
        try {
          await deleteSession(session.session_id);
          message.success('会话删除成功');
          if (currentSession?.session_id === session.session_id) {
            handleSessionChange(null);
          }
        } catch (error) {
          message.error('删除失败，请重试');
        }
      }
    });
  };

  // 修改会话操作菜单
  const getSessionMenu = (session: ChatSession) => ({
    items: [
      {
        key: 'roleInfo',
        icon: <EditOutlined />,
        label: '角色信息',
      },
      {
        key: 'config',
        icon: <ApiOutlined />,
        label: '模型配置',
      },
      {
        key: 'kbConfig',
        icon: <DatabaseOutlined />,
        label: '配置知识库',
      },
      {
        key: 'ttsConfig',
        icon: <SoundOutlined />,
        label: '语音生成',
      },
      {
        key: 'moments',
        icon: <HeartOutlined />,
        label: '朋友圈',
      },
      {
        key: 'export',
        icon: <FileTextOutlined />,
        label: '导出对话数据',
      },
      {
        key: 'clear',
        icon: <DeleteOutlined />,
        label: '清空对话',
      },
      {
        key: 'delete',
        icon: <DeleteOutlined />,
        label: '删除会话',
        style: { color: '#ff4d4f' },
        className: styles.deleteMenuItem,
      },
    ],
    onClick: ({ key, domEvent }: any) => {
        domEvent.stopPropagation();
        if (key === 'roleInfo') {
          setEditingSession(session);
          setNewSessionName(session.name);
          setRoleAvatar(session.role_avatar_url || '');
          setRoleInfoModalVisible(true);
        } else if (key === 'delete') {
          handleDelete(session);
        } else if (key === 'config') {
          // 从会话中获取配置
          const sessionConfig = {
            session_id: session.session_id,
            modelSettings: { ...session.model_settings },
            systemPrompt: session.system_prompt || '', // 直接使用会话的system_prompt
            contextCount: session.context_count !== undefined ? session.context_count : 20 // 从数据库获取实际值，如果不存在则默认20
          };
          console.log('[Chat] 加载会话配置，context_count:', session.context_count, '最终使用:', sessionConfig.contextCount);

          console.log('[Chat] 加载会话配置:', sessionConfig);
          setEditingConfig(sessionConfig);
          setConfigModalVisible(true);
        } else if (key === 'kbConfig') {
          // 仅设置会话与打开模态框，初始化由 useEffect 统一处理，避免多处覆盖导致渲染错乱
          setKbEditingSession(session);
          setKbConfigModalVisible(true);
          
          // 🆕 打开模态框时加载知识库列表
          (async () => {
            setKbListLoading(true);
            const kbList = await fetchKnowledgeBaseList();
            setAvailableKnowledgeBases(kbList);
            setKbListLoading(false);
          })();
        } else if (key === 'ttsConfig') {
          // TTS配置处理
          console.log('[TTS] 点击语音生成按钮 - 会话ID:', session.session_id);
          setEditingSession(session);
          handleTtsConfigClick(session);
        } else if (key === 'moments') {
          // 朋友圈功能
          console.log('[Moments] 打开朋友圈 - 会话ID:', session.session_id);
          navigate(`/moments/${session.session_id}`);
        } else if (key === 'export') {
          handleExportChat(session);
        } else if (key === 'clear') {
          handleClearChat(session);
        }
    },
  });

  // 群聊操作菜单
  const getGroupMenu = (group: Group) => ({
    items: [
      {
        key: 'manage',
        icon: <SettingOutlined />,
        label: '群组管理',
      },
    ],
    onClick: ({ key, domEvent }: any) => {
      domEvent.stopPropagation();
      if (key === 'manage') {
        // 打开管理群组模态框
        setManagingGroup(group);
        setManageGroupModalVisible(true);
      }
    },
  });

  // 添加System Prompt设置模态框
  const renderSystemPromptModal = () => (
    <Modal
      title="设置System Prompt"
      open={systemPromptModalVisible}
      onOk={handleSystemPromptSave}
      onCancel={() => setSystemPromptModalVisible(false)}
      width={600}
    >
      <Input.TextArea
        value={systemPrompt}
        onChange={e => setSystemPrompt(e.target.value)}
        placeholder="请输入System Prompt，留空则使用默认值"
        rows={6}
      />
    </Modal>
  );

  // 文本清洗配置模态框
  const renderCleaningPatternsModal = () => {
    const [tempPatterns, setTempPatterns] = useState(textCleaningPatterns);
    const [tempPreserveQuotes, setTempPreserveQuotes] = useState(preserveQuotes);

    return (
      <Modal
        title="文本清洗配置"
        open={cleaningPatternsModalVisible}
        onOk={() => {
          setTextCleaningPatterns(tempPatterns);
          setPreserveQuotes(tempPreserveQuotes);
          setCleaningPatternsModalVisible(false);
          message.success('清洗配置已保存');
        }}
        onCancel={() => {
          setTempPatterns(textCleaningPatterns);
          setTempPreserveQuotes(preserveQuotes);
          setCleaningPatternsModalVisible(false);
        }}
        width={700}
        zIndex={1100}
        footer={[
          <Button 
            key="reset" 
            onClick={() => {
              setTempPatterns(defaultCleaningPatterns);
              setTempPreserveQuotes(true);
              message.info('已恢复默认配置');
            }}
          >
            恢复默认
          </Button>,
          <Button key="cancel" onClick={() => {
            setTempPatterns(textCleaningPatterns);
            setTempPreserveQuotes(preserveQuotes);
            setCleaningPatternsModalVisible(false);
          }}>
            取消
          </Button>,
          <Button 
            key="ok" 
            type="primary" 
            onClick={() => {
              setTextCleaningPatterns(tempPatterns);
              setPreserveQuotes(tempPreserveQuotes);
              setCleaningPatternsModalVisible(false);
              message.success('清洗配置已保存');
            }}
          >
            保存
          </Button>
        ]}
      >
        <div style={{ marginBottom: '16px' }}>
          <Alert
            message="配置说明"
            description="使用正则表达式定义文本清洗规则，用于在生成语音时清洗 AI 回复内容。每行一个正则表达式，支持使用 # 开头添加注释。"
            type="info"
            showIcon
          />
        </div>
        
        <div style={{ marginBottom: '16px' }}>
          <div style={{ marginBottom: '8px', fontWeight: 500 }}>
            <Checkbox 
              checked={tempPreserveQuotes}
              onChange={(e) => setTempPreserveQuotes(e.target.checked)}
            >
              保留引号内容
            </Checkbox>
            <div style={{ fontSize: '12px', color: '#666', marginLeft: '24px', marginTop: '4px' }}>
              勾选后，双引号 "" 内的文本将被保护，不受清洗规则影响
            </div>
          </div>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <div style={{ marginBottom: '8px', fontWeight: 500 }}>正则表达式（每行一个）</div>
          <Input.TextArea
            value={tempPatterns}
            onChange={(e) => setTempPatterns(e.target.value)}
            placeholder={'示例：\n\\([^)]*\\)\n（[^）]*）\n\\[[^\\]]*\\]'}
            rows={8}
            style={{ fontFamily: 'monospace' }}
          />
          <div style={{ fontSize: '12px', color: '#666', marginTop: '8px' }}>
            每行一个正则表达式，匹配的内容将被移除。支持注释（以 # 开头的行）。
          </div>
        </div>

        <div style={{ marginTop: '16px' }}>
          <Alert
            message="常用正则示例"
            description={
              <div style={{ fontSize: '12px' }}>
                <div>• <code>\([^)]*\)</code> - 移除英文圆括号及内容</div>
                <div>• <code>（[^）]*）</code> - 移除中文圆括号及内容</div>
                <div>• <code>\[[^\]]*\]</code> - 移除英文方括号及内容</div>
                <div>• <code>【[^】]*】</code> - 移除中文方括号及内容</div>
                <div>• <code>\{'{'}[^{'}'}]*\{'}'}</code> - 移除花括号及内容</div>
                <div>• <code>&lt;[^&gt;]*&gt;</code> - 移除尖括号及内容</div>
                <div>• <code>\*[^*]*\*</code> - 移除星号包围的内容</div>
              </div>
            }
            type="warning"
            showIcon
          />
        </div>

        <div style={{ marginTop: '16px' }}>
          <Alert
            message="效果示例"
            description={
              <div>
                <div><strong>原文：</strong>你好啊（微笑），我今天【开心】*挥手*想说"Hello"</div>
                <div style={{ marginTop: '8px', color: '#52c41a' }}>
                  <strong>清洗后：</strong>你好啊，我今天想说"Hello"
                </div>
              </div>
            }
            type="success"
            showIcon
          />
        </div>
      </Modal>
    );
  };

  // TTS服务商选择模态框
  const renderTtsProviderModal = () => (
    <Modal
      title="选择语音生成服务"
      open={ttsProviderModalVisible}
      onCancel={() => setTtsProviderModalVisible(false)}
      footer={null}
      width={600}
      className={styles.ttsProviderModal}
    >
      <div className={styles.ttsProviderGrid}>
        {/* 讯飞云TTS */}
        <div 
          className={`${styles.ttsProviderCard} ${selectedTtsProvider === 'xfyun' ? styles.selected : ''}`}
          onClick={() => {
            // 检查用户是否已配置该服务商
            if (!userGlobalTtsConfigs['xfyun']) {
              message.warning('请先在"模型配置"页面配置讯飞云TTS服务');
              return;
            }
            
            setSelectedTtsProvider('xfyun');
            setTtsConfig({
              provider: 'xfyun',
              config: {},  // 不再需要在这里设置密钥
              voiceSettings: {
                voiceType: userGlobalTtsConfigs['xfyun']?.voice || 'x4_xiaoyan' // 使用用户配置的默认音色
              }
            });
            setTtsProviderModalVisible(false);
            setTtsConfigModalVisible(true);
          }}
        >
          <div className={styles.ttsProviderIcon}>
            <img src="/src/static/logo/xfyun.png" alt="讯飞云" />
          </div>
          <div className={styles.ttsProviderInfo}>
            <h3>讯飞云TTS</h3>
            <p>科大讯飞语音合成服务</p>
            <div className={styles.ttsProviderFeatures}>
              <span>高质量语音</span>
              <span>多种音色</span>
              <span>稳定可靠</span>
            </div>
          </div>
        </div>

        {/* 字节跳动TTS */}
        <div 
          className={`${styles.ttsProviderCard} ${selectedTtsProvider === 'bytedance' ? styles.selected : ''}`}
          onClick={() => {
            // 检查用户是否已配置该服务商
            if (!userGlobalTtsConfigs['bytedance']) {
              message.warning('请先在"模型配置"页面配置字节跳动TTS服务');
              return;
            }
            
            setSelectedTtsProvider('bytedance');
            setTtsConfig({
              provider: 'bytedance',
              config: {},  // 不再需要在这里设置密钥
              voiceSettings: {
                voiceType: userGlobalTtsConfigs['bytedance']?.voice || 'zh_female_wanwanxiaohe_moon_bigtts' // 使用用户配置的默认音色
              }
            });
            setTtsProviderModalVisible(false);
            setTtsConfigModalVisible(true);
          }}
        >
          <div className={styles.ttsProviderIcon}>
            <img src="/src/static/logo/huoshan.png" alt="字节跳动" />
          </div>
          <div className={styles.ttsProviderInfo}>
            <h3>字节跳动TTS</h3>
            <p>火山引擎语音合成服务</p>
            <div className={styles.ttsProviderFeatures}>
              <span>自然语音</span>
              <span>低延迟</span>
              <span>企业级</span>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );

  // 讯飞云TTS音色数据（从JSON文件导入）
  const xfyunVoices = xfyunVoicesData;

  // 字节跳动TTS音色数据（从JSON文件导入）
  const bytedanceVoices = bytedanceVoicesData;

  // 筛选音色的函数
  const filterVoices = (voices: any[], genderFilter: string, searchQuery: string) => {
    return voices.filter(voice => {
      // 性别筛选
      const genderMatch = genderFilter === 'all' || voice.gender === genderFilter;
      
      // 搜索筛选
      const searchMatch = !searchQuery || 
        voice.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        voice.category.toLowerCase().includes(searchQuery.toLowerCase()) ||
        voice.language.toLowerCase().includes(searchQuery.toLowerCase());
      
      return genderMatch && searchMatch;
    });
  };

  // 获取音色名称的辅助函数
  const getVoiceName = (voiceType: string, provider: string) => {
    if (provider === 'xfyun') {
      // 讯飞云的音色映射
      const voice = xfyunVoices.find(v => v.id === voiceType);
      return voice ? `${voice.name}（${voice.category}）` : voiceType;
    } else if (provider === 'bytedance') {
      // 字节跳动的音色映射
      const voice = bytedanceVoices.find(v => v.id === voiceType);
      return voice ? `${voice.name}（${voice.category}）` : voiceType;
    }
    return voiceType;
  };

  // TTS配置模态框
  const renderTtsConfigModal = () => {
    // 处理修改TTS服务按钮点击
    const handleChangeTtsService = () => {
      console.log('[TTS] 点击修改TTS服务按钮');
      // 关闭当前配置模态框
      setTtsConfigModalVisible(false);
      // 重置选择状态
      setSelectedTtsProvider('');
      setTtsConfig({
        provider: '',
        config: {},
        voiceSettings: {}
      });
      // 打开服务商选择模态框
      setTtsProviderModalVisible(true);
    };

    const handleTtsConfigSave = async () => {
      if (!editingSession) return;

      try {
        // 检查用户是否配置了该服务商的全局配置
        const globalConfig = userGlobalTtsConfigs[ttsConfig.provider];
        if (!globalConfig) {
          message.error(`请先在"模型配置"页面配置${ttsConfig.provider === 'xfyun' ? '讯飞云' : '字节跳动'}TTS服务`);
          return;
        }

        // 验证音色是否选择
        if (!ttsConfig.voiceSettings?.voiceType) {
          message.error('请选择音色');
          return;
        }

        // 保存TTS配置到会话（只保存音色设置，密钥从全局配置读取）
        const updateData = {
          tts_settings: {
            provider: ttsConfig.provider,
            voice_settings: ttsConfig.voiceSettings
          }
        } as Partial<ChatSession>;

        await updateSession(editingSession.session_id, updateData);
        message.success('TTS配置保存成功');
        setTtsConfigModalVisible(false);
        setTtsConfig({
          provider: '',
          config: {},
          voiceSettings: {}
        });
        setEditingSession(null);

        // 重新获取会话列表
        await fetchSessions();

      } catch (error) {
        console.error('保存TTS配置失败:', error);
        message.error('保存TTS配置失败，请重试');
      }
    };

    return (
      <Modal
        title={`配置${ttsConfig.provider === 'xfyun' ? '讯飞云' : '字节跳动'}TTS`}
        open={ttsConfigModalVisible}
        onOk={handleTtsConfigSave}
        onCancel={() => {
          setTtsConfigModalVisible(false);
          setTtsConfig({
            provider: '',
            config: {},
            voiceSettings: {}
          });
        }}
        width={800}
        okText="保存配置"
        cancelText="取消"
      >
        <div className={styles.ttsConfigForm}>
          {/* 修改TTS服务按钮 */}
          <div className={styles.changeTtsServiceSection}>
            <span className={styles.changeTtsServiceHint}>
              当前服务：{ttsConfig.provider === 'xfyun' ? '讯飞云' : '字节跳动'}
            </span>
            <Button 
              type="default" 
              onClick={handleChangeTtsService}
              className={styles.changeTtsServiceBtn}
            >
              修改TTS服务
            </Button>
          </div>

          {/* TTS配置信息提示 */}
          <div className={styles.configSection}>
            <Alert
              message="TTS服务配置"
              description={`将使用您在"模型配置"页面设置的${ttsConfig.provider === 'xfyun' ? '讯飞云' : '字节跳动'}TTS全局配置。如需修改密钥等信息，请前往模型配置页面。`}
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
          </div>

          {/* 音色设置 */}
          <div className={styles.configSection}>
            <h4>
              音色设置
              <span className={styles.currentVoice}>
                （当前：{getVoiceName(ttsConfig.voiceSettings?.voiceType || 
                (ttsConfig.provider === 'xfyun' ? 'x4_xiaoyan' : 'zh_female_wanwanxiaohe_moon_bigtts'), 
                ttsConfig.provider)}）
              </span>
            </h4>
            {ttsConfig.provider === 'xfyun' ? (
              <div className={styles.voiceSelection}>
                {/* 性别筛选标签和搜索按钮 */}
                <div className={styles.voiceFilterContainer}>
                  <div className={styles.voiceFilterTabs}>
                    <div 
                      className={`${styles.filterTab} ${voiceGenderFilter === 'all' ? styles.activeTab : ''}`}
                      onClick={() => setVoiceGenderFilter('all')}
                    >
                      全部
                    </div>
                    <div 
                      className={`${styles.filterTab} ${voiceGenderFilter === 'female' ? styles.activeTab : ''}`}
                      onClick={() => setVoiceGenderFilter('female')}
                    >
                      女声
                    </div>
                    <div 
                      className={`${styles.filterTab} ${voiceGenderFilter === 'male' ? styles.activeTab : ''}`}
                      onClick={() => setVoiceGenderFilter('male')}
                    >
                      男声
                    </div>
                  </div>
                  <Button
                    icon={<SearchOutlined />}
                    onClick={() => setShowVoiceSearch(!showVoiceSearch)}
                    className={styles.voiceSearchButton}
                    type={showVoiceSearch ? "primary" : "default"}
                    size="small"
                  />
                </div>

                {/* 搜索框 */}
                {showVoiceSearch && (
                  <div className={styles.voiceSearchContainer}>
                    <Input.Search
                      placeholder="搜索音色名称、类别或语言..."
                      value={voiceSearchQuery}
                      onChange={(e) => setVoiceSearchQuery(e.target.value)}
                      allowClear
                      className={styles.voiceSearchInput}
                    />
                  </div>
                )}

                {/* 音色网格 */}
                <div className={styles.voiceGridSquare}>
                  {filterVoices(xfyunVoices, voiceGenderFilter, voiceSearchQuery)
                    .map((voice) => (
                    <div
                      key={voice.id}
                      className={`${styles.voiceCardSquare} ${
                        ttsConfig.voiceSettings?.voiceType === voice.id ? styles.selectedVoiceSquare : ''
                      }`}
                      onClick={() => {
                        setTtsConfig(prev => ({
                          ...prev,
                          voiceSettings: { ...prev.voiceSettings, voiceType: voice.id }
                        }));
                      }}
                    >
                      <div className={styles.voiceNameSquare}>{voice.name}</div>
                      <div className={styles.voiceTagsSquare}>
                        <span className={styles.voiceCategoryTag}>{voice.category}</span>
                        <span className={styles.voiceLanguageTag}>{voice.language}</span>
                        <span className={`${styles.voiceGenderTag} ${styles[voice.gender]}`}>
                          {voice.gender === 'male' ? '男声' : '女声'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className={styles.voiceSelection}>
                {/* 性别筛选标签和搜索按钮 */}
                <div className={styles.voiceFilterContainer}>
                  <div className={styles.voiceFilterTabs}>
                    <div 
                      className={`${styles.filterTab} ${voiceGenderFilter === 'all' ? styles.activeTab : ''}`}
                      onClick={() => setVoiceGenderFilter('all')}
                    >
                      全部
                    </div>
                    <div 
                      className={`${styles.filterTab} ${voiceGenderFilter === 'female' ? styles.activeTab : ''}`}
                      onClick={() => setVoiceGenderFilter('female')}
                    >
                      女声
                    </div>
                    <div 
                      className={`${styles.filterTab} ${voiceGenderFilter === 'male' ? styles.activeTab : ''}`}
                      onClick={() => setVoiceGenderFilter('male')}
                    >
                      男声
                    </div>
                  </div>
                  <Button
                    icon={<SearchOutlined />}
                    onClick={() => setShowVoiceSearch(!showVoiceSearch)}
                    className={styles.voiceSearchButton}
                    type={showVoiceSearch ? "primary" : "default"}
                    size="small"
                  />
                </div>

                {/* 搜索框 */}
                {showVoiceSearch && (
                  <div className={styles.voiceSearchContainer}>
                    <Input.Search
                      placeholder="搜索音色名称、类别或语言..."
                      value={voiceSearchQuery}
                      onChange={(e) => setVoiceSearchQuery(e.target.value)}
                      allowClear
                      className={styles.voiceSearchInput}
                    />
                  </div>
                )}

                {/* 音色网格 */}
                <div className={styles.voiceGridSquare}>
                  {filterVoices(bytedanceVoices, voiceGenderFilter, voiceSearchQuery)
                    .map((voice) => (
                    <div
                      key={voice.id}
                      className={`${styles.voiceCardSquare} ${
                        ttsConfig.voiceSettings?.voiceType === voice.id ? styles.selectedVoiceSquare : ''
                      }`}
                      onClick={() => {
                        setTtsConfig(prev => ({
                          ...prev,
                          voiceSettings: {
                            ...prev.voiceSettings,
                            voiceType: voice.id
                          }
                        }));
                      }}
                    >
                      <div className={styles.voiceNameSquare}>{voice.name}</div>
                      <div className={styles.voiceTagsSquare}>
                        <span className={styles.voiceCategoryTag}>{voice.category}</span>
                        <span className={styles.voiceLanguageTag}>{voice.language}</span>
                        <span className={`${styles.voiceGenderTag} ${styles[voice.gender]}`}>
                          {voice.gender === 'male' ? '男声' : '女声'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>


        </div>
      </Modal>
    );
  };

  // 修改配置修改模态框
  const renderConfigModal = () => (
    <Modal
      title="修改会话配置"
      open={configModalVisible}
      onOk={() => {
        const session = sessions.find(s => s.session_id === editingConfig?.session_id);
        if (session && editingConfig) {
          handleConfigEdit(session);
        }
      }}
      onCancel={() => {
        setConfigModalVisible(false);
        setEditingConfig(null);
      }}
      width={600}
    >
      {editingConfig && (
        <div className={styles.configForm}>
          <div className={styles.formItem}>
            <div className={styles.formLabel}>
              <RobotOutlined /> 选择模型服务商
            </div>
            <Select 
              value={editingConfig.modelSettings.modelService}
              optionLabelProp="label"
              className={styles.modelSelectWrapper}
              onChange={async (value) => {
                console.log('会话配置中选择模型服务:', value);
                
                // 如果选择的是相同的模型服务，不做任何操作
                if (value === editingConfig.modelSettings.modelService) {
                  return;
                }
                
                // 从已启用的服务商列表中获取配置
                const provider = enabledProviders.find(p => p.id === value);
                
                if (!provider) {
                  message.warning('请先在模型配置页面配置并启用该服务商');
                  return;
                }
                
                // 使用从ModelConfig获取的配置
                const newModelName = provider.models[0] || '';
                const defaultParams = getModelDefaultParams(value, newModelName);
                
                setEditingConfig({
                  ...editingConfig,
                  modelSettings: { 
                    ...editingConfig.modelSettings, 
                    modelService: value,
                    baseUrl: provider.baseUrl,
                    apiKey: provider.apiKey,
                    modelName: newModelName,
                    modelParams: defaultParams
                  },
                  contextCount: editingConfig.contextCount
                });
              }}
              style={{ width: '100%' }}
            >
              {enabledProviders.map(provider => {
                const modelService = MODEL_SERVICES.find(s => s.value === provider.id);
                return (
                  <Option key={provider.id} value={provider.id} label={
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {modelService && (
                    <img 
                          src={modelService.logo} 
                          alt={provider.name} 
                      style={{ width: '16px', height: '16px', objectFit: 'contain' }}
                    />
                      )}
                      <span>{provider.name}</span>
                  </div>
                }>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {modelService && (
                    <img 
                          src={modelService.logo} 
                          alt={provider.name} 
                      style={{ width: '20px', height: '20px', objectFit: 'contain' }}
                    />
                      )}
                      <span>{provider.name}</span>
                  </div>
                </Option>
                );
              })}
            </Select>
          </div>

          <div className={styles.formItem}>
            <div className={styles.formLabel}>
              <GlobalOutlined /> 模型名称
            </div>
            <Select 
              value={editingConfig.modelSettings.modelName}
              onChange={(value) => {
                // 如果选择的是相同的模型名称，不做任何操作
                if (value === editingConfig.modelSettings.modelName) {
                  return;
                }
                
                const defaultParams = getModelDefaultParams(editingConfig.modelSettings.modelService, value);
                setEditingConfig({
                  ...editingConfig,
                  modelSettings: { 
                    ...editingConfig.modelSettings, 
                    modelName: value,
                    modelParams: defaultParams
                  }
                });
              }}
              style={{ width: '100%' }}
            >
              {(() => {
                const provider = enabledProviders.find(p => p.id === editingConfig.modelSettings.modelService);
                if (!provider) return null;
                
                return provider.models.map(modelValue => {
                  // 首先检查是否是自定义模型
                  const customModel = provider.customModels?.find(cm => cm.id === modelValue);
                  
                  if (customModel) {
                    // 渲染自定义模型
                    return (
                      <Option key={modelValue} value={modelValue}>
                        <span className={styles.modelOption}>
                          {customModel.supportsImage && (
                            <span className={styles.modelImageLabel}>🖼️</span>
                          )}
                          {!customModel.supportsImage && (
                            <span className={styles.modelImageLabel}>📝</span>
                          )}
                          {customModel.displayName} <Tag color="blue" style={{marginLeft: '4px'}}>自定义</Tag>
                        </span>
                      </Option>
                    );
                  }
                  
                  // 从配置文件中查找模型信息以获取标签和图标
                  const modelInfo = getModelInfoFromConfig(editingConfig.modelSettings.modelService, modelValue);
                  
                  return (
                    <Option key={modelValue} value={modelValue}>
                    <span className={styles.modelOption}>
                        {modelInfo?.imageLabel && (
                          <span className={styles.modelImageLabel}>{modelInfo.imageLabel}</span>
                      )}
                        {modelInfo?.label || modelValue}
                    </span>
                  </Option>
                  );
                });
              })()}
            </Select>
          </div>

          <div className={styles.formItem}>
            <div className={styles.formLabel}>
              <FileTextOutlined /> System Prompt
            </div>
            <Input.TextArea
              value={editingConfig.systemPrompt}
              onChange={(e) => setEditingConfig({
                ...editingConfig,
                systemPrompt: e.target.value
              })}
              placeholder="输入System Prompt，留空则使用默认值"
              rows={4}
            />
          </div>

          <div className={styles.formItem}>
            <div className={styles.formLabel}>
              <MessageOutlined /> 上下文数量
            </div>
            <Input
              type="number"
              value={editingConfig.contextCount === null ? '' : String(editingConfig.contextCount)}
              onChange={(e) => {
                const value = e.target.value;
                if (value === '') {
                  // 如果输入框为空，设置为null（不限制上下文）
                  setEditingConfig({
                    ...editingConfig,
                    contextCount: null
                  });
                } else {
                  // 如果有输入，解析数字
                  const numValue = parseInt(value);
                  setEditingConfig({
                    ...editingConfig,
                    contextCount: isNaN(numValue) ? null : numValue
                  });
                }
              }}
              placeholder="输入上下文数量（留空表示不限制上下文，默认20）"
              min={0}
              max={100}
            />
          </div>

          {/* 模型参数设置（可选） */}
          <Collapse ghost>
            <Panel header="模型参数（可选）" key="model-params">
              {(() => {
                const service = editingConfig.modelSettings.modelService;
                const modelId = editingConfig.modelSettings.modelName;
                // 使用新的配置获取函数
                const schema = getModelParamsSchema(service, modelId);
                const currentParams = editingConfig.modelSettings.modelParams || {};
                return (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    {schema.map((item: any) => {
                      const value = currentParams[item.key] ?? item.default;
                      const onParamChange = (v: number | null) => {
                        const nv = v === null ? undefined : v;
                        setEditingConfig(prev => prev ? {
                          ...prev,
                          modelSettings: {
                            ...prev.modelSettings,
                            modelParams: {
                              ...(prev.modelSettings.modelParams || {}),
                              [item.key]: nv
                            }
                          }
                        } : prev);
                      };
                      return (
                        <div key={item.key} className={styles.formItem}>
                          <div className={styles.formLabel}>
                            {item.label}
                            {item.description ? (
                              <Tooltip title={item.description} placement="top">
                                <QuestionCircleOutlined style={{ marginLeft: 6, color: 'var(--text-secondary, #999)' }} />
                              </Tooltip>
                            ) : null}
                          </div>
                          {item.key === 'max_tokens' ? (
                            <InputNumber
                              className={styles.maxTokensInput}
                              min={item.min}
                              max={item.max}
                              step={item.step}
                              style={{ width: '100%' }}
                              value={value}
                              onChange={onParamChange}
                            />
                          ) : (
                            <div style={{ padding: '0 8px' }}>
                              <Slider
                                min={item.min}
                                max={item.max}
                                step={item.step}
                                tooltip={{ open: false }}
                                value={typeof value === 'number' ? value : item.default}
                                onChange={(v: number) => onParamChange(v)}
                              />
                              <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--text-secondary, #999)' }}>
                                {typeof value === 'number' ? value : item.default}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </Panel>
          </Collapse>
        </div>
      )}
    </Modal>
  );

  // 检查模型配置是否有变化
  const normalizeParams = (params?: Record<string, any>) => {
    const p = { ...(params || {}) } as Record<string, any>;
    Object.keys(p).forEach(k => {
      if (p[k] === undefined) delete p[k];
    });
    return p;
  };

  const shallowEqual = (a: Record<string, any>, b: Record<string, any>) => {
    const ak = Object.keys(a);
    const bk = Object.keys(b);
    if (ak.length !== bk.length) return false;
    for (const k of ak) {
      if (a[k] !== b[k]) return false;
    }
    return true;
  };

  const hasModelConfigChanged = (original: ModelSettings, current: ModelSettings): boolean => {
    const basicChanged = (
      original.modelService !== current.modelService ||
      original.baseUrl !== current.baseUrl ||
      original.apiKey !== current.apiKey ||
      original.modelName !== current.modelName
    );
    
    // 检查模型参数是否有变化（不修改任何数据，只做比较）
    const origParams = normalizeParams(original.modelParams);
    const currParams = normalizeParams(current.modelParams);
    const paramsChanged = !shallowEqual(origParams, currParams);
    
    return basicChanged || paramsChanged;
  };

  // 检查是否有任何配置变化
  const hasAnyConfigChanged = (session: ChatSession): boolean => {
    if (!editingConfig) return false;
    
    const modelChanged = hasModelConfigChanged(session.model_settings, editingConfig?.modelSettings || session.model_settings);
    const systemPromptChanged = session.system_prompt !== editingConfig.systemPrompt;
    const contextCountChanged = session.context_count !== editingConfig.contextCount;
    
    return modelChanged || systemPromptChanged || contextCountChanged;
  };

  // 修改配置更新函数
  const handleConfigEdit = async (session: ChatSession) => {
    try {
      // 如果没有任何变化则不提交
      if (!hasAnyConfigChanged(session)) {
        message.info('未检测到配置变化');
        setConfigModalVisible(false);
        setEditingConfig(null);
        return;
      }

      // 更新会话配置
      const updateData = {
        model_settings: editingConfig?.modelSettings,
        system_prompt: editingConfig?.systemPrompt,
        context_count: editingConfig?.contextCount
      };

      await updateSession(session.session_id, updateData as any);

      message.success('配置修改成功');
      setConfigModalVisible(false);
      setEditingConfig(null);

      // 重新获取会话列表以更新配置
      await useChatStore.getState().fetchSessions();

      // 如果是当前会话且不是群聊，重新建立连接
      if (currentSession?.session_id === session.session_id && currentSession?.session_type !== 'group') {
        cleanupWebSocket();
        setTimeout(() => {
          establishConnection();
        }, 100);
      }
    } catch (e) {
      console.error(e);
      message.error('保存失败');
    }
  };

  // 修改工具按钮菜单
  const toolsMenu = {
    items: [
      {
        key: 'call',
        icon: <PhoneOutlined />,
        label: '打电话',
      },
      {
        key: 'mcp',
        icon: <ApiOutlined />,
        label: 'MCP管理',
      },
    ],
    onClick: ({ key, domEvent }: any) => {
      domEvent?.stopPropagation();
      if (key === 'call') {
        navigate('/call', { 
          state: { 
            sessionId: currentSession?.session_id 
          } 
        });
      } else if (key === 'mcp') {
        setToolConfigModalVisible(true);
      }
    },
  };

  // 监听输入框变化
  const handleMessageChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    const cursorPosition = e.target.selectionStart;
    
    setCurrentMessage(value);
    setSentFlag(value.trim().length > 0);
    
    // 🆕 @功能：支持@成员（仅群聊）和@知识库（所有会话）
    // 查找光标前最近的@符号
    const textBeforeCursor = value.substring(0, cursorPosition);
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');
    
    // 检查@符号后是否有空格（如果有空格则不显示菜单）
    if (lastAtIndex !== -1) {
      const textAfterAt = textBeforeCursor.substring(lastAtIndex + 1);
      
      // 如果@后面没有空格，显示菜单
      if (!textAfterAt.includes(' ') && !textAfterAt.includes('\n')) {
        setMentionAtPosition(lastAtIndex);
        setMentionSearchText(textAfterAt);
        setMentionCursorPosition(cursorPosition);
        setMentionSelectedIndex(0); // 重置选中索引
        // 如果菜单之前是关闭的，现在打开时重置计数器
        if (!mentionMenuVisible) {
          setMentionSelectCount(0);
        }
        setMentionMenuVisible(true);
      } else {
        setMentionMenuVisible(false);
        setMentionSelectCount(0); // 关闭菜单时重置计数
      }
    } else {
      setMentionMenuVisible(false);
      setMentionSelectCount(0); // 关闭菜单时重置计数
    }
  };

  // 处理选择@成员或@知识库
  const handleSelectMention = (memberNickname: string) => {
    // 🆕 特殊处理：选择"知识库"
    if (memberNickname === '知识库') {
      // 添加到引用区域，而不是输入框
      setReferencedDocs(prev => {
        // 避免重复添加
        if (prev.some(doc => doc.filename === '知识库')) {
          return prev;
        }
        return [...prev, { filename: '知识库', docId: 'knowledge-base', kbId: 'knowledge-base' }];
      });
      
      setMentionMenuVisible(false);
      setMentionSelectCount(0);
      
      // 移除输入框中的 @ 和搜索文本
      const beforeAt = currentMessage.substring(0, mentionAtPosition);
      const afterCursor = currentMessage.substring(mentionCursorPosition);
      const newMessage = beforeAt + afterCursor;
      setCurrentMessage(newMessage);
      setSentFlag(newMessage.trim().length > 0);
      
      // 将光标移到@符号原来的位置
      setTimeout(() => {
        if (inputRef.current?.resizableTextArea?.textArea) {
          inputRef.current.resizableTextArea.textArea.setSelectionRange(mentionAtPosition, mentionAtPosition);
          inputRef.current.focus();
        }
      }, 0);
      return;
    }
    
    // 原有@成员逻辑
    let newMessage: string;
    let newCursorPosition: number;
    
    if (mentionSelectCount === 0) {
      // 第一次选择：替换 @xxx 为 @成员名 空格
      const beforeAt = currentMessage.substring(0, mentionAtPosition);
      const afterCursor = currentMessage.substring(mentionCursorPosition);
      newMessage = `${beforeAt}@${memberNickname} ${afterCursor}`;
      newCursorPosition = mentionAtPosition + memberNickname.length + 2; // +2 for @ and space
    } else {
      // 第二次及以后：在当前光标位置插入 @成员名 空格
      const currentCursorPos = inputRef.current?.resizableTextArea?.textArea?.selectionStart || mentionCursorPosition;
      const beforeCursor = currentMessage.substring(0, currentCursorPos);
      const afterCursor = currentMessage.substring(currentCursorPos);
      newMessage = `${beforeCursor}@${memberNickname} ${afterCursor}`;
      newCursorPosition = currentCursorPos + memberNickname.length + 2; // +2 for @ and space
    }
    
    setCurrentMessage(newMessage);
    setSentFlag(newMessage.trim().length > 0);
    
    // 增加选择计数
    setMentionSelectCount(mentionSelectCount + 1);
    
    // 不关闭菜单，让用户可以继续@其他成员
    // setMentionMenuVisible(false); // 已注释掉
    
    // 将光标移到插入的文本后面
    setTimeout(() => {
      if (inputRef.current?.resizableTextArea?.textArea) {
        inputRef.current.resizableTextArea.textArea.setSelectionRange(newCursorPosition, newCursorPosition);
        inputRef.current.focus();
      }
    }, 0);
  };

  // 处理音频识别（共用逻辑）
  const transcribeAudio = async (audioBlob: Blob, keepRecording: boolean = false) => {
    console.log('[Chat] 📥 收到转录请求:', {
      audioSize: audioBlob.size,
      keepRecording,
      currentTranscribing: isTranscribing
    });

    // 🔥 如果正在转录中，直接忽略（防止并发）
    if (isTranscribing) {
      console.log('[Chat] ⏳ 正在转录中，忽略新请求');
      message.warning('正在处理中，请稍候...');
      return;
    }

    try {
      setIsTranscribing(true);
      setVadStatus('transcribing');

      // 上传音频到后端进行识别
      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.wav');

      // ✅ 不要手动设置 Content-Type，让浏览器自动添加 boundary
      // ✅ authAxios 拦截器会自动添加 Authorization header
      const response = await authAxios.post('/api/asr/transcribe', formData);

      if (response.data.success) {
        const transcribedText = response.data.text;
        if (transcribedText && transcribedText.trim()) {
          // 将识别结果插入到输入框
          setCurrentMessage((prev) => {
            const newText = prev ? `${prev} ${transcribedText}` : transcribedText;
            return newText;
          });
          setSentFlag(true);
          message.success('语音识别成功');
        } else {
          message.warning('未识别到语音内容');
        }
      } else {
        message.error('语音识别失败');
      }
    } catch (error: any) {
      console.error('语音识别失败:', error);
      if (error.response?.data?.detail) {
        message.error(error.response.data.detail);
      } else {
        message.error('语音识别失败，请重试');
      }
    } finally {
      setIsTranscribing(false);
      // 🔥 如果还在继续录音，回到 recording 状态（等待下一次语音），否则回到 idle
      setVadStatus(keepRecording ? 'recording' : 'idle');
      console.log('[Chat] ✅ 转录处理完成');
    }
  };

  // 处理语音输入按钮点击（智能 VAD 模式）
  const handleVoiceInputClick = async () => {
    console.log('╔' + '═'.repeat(78) + '╗');
    console.log('║ [Chat] 🎤 语音输入按钮点击                                                   ║');
    console.log('╚' + '═'.repeat(78) + '╝');
    console.log('[Chat] 🎤 ========== 语音输入按钮点击 ==========');
    console.log('[Chat] 当前状态:', {
      isRecording,
      isSpeaking,
      isTranscribing,
      vadStatus
    });

    if (isRecording) {
      // 用户手动停止录音，立即停止 VAD 和录音
      console.log('[Chat] 👆 用户手动停止录音');
      const audioBlob = await stopRecording();
      
      if (!audioBlob) {
        message.error('录音失败，请重试');
        setVadStatus('idle');
        return;
      }

      await transcribeAudio(audioBlob);
    } else {
      // 开始录音 + VAD 自动检测
      try {
        console.log('[Chat] 🎙️ 开始录音并注册 VAD 自动停止回调');
        setVadStatus('recording');
        await startRecording(async (audioBlob) => {
          // VAD 检测到静音 - 发送音频片段但继续录音
          console.log('[Chat] 🤖 VAD 检测到静音，发送音频片段:', audioBlob ? `${audioBlob.size} bytes` : 'null');
          await transcribeAudio(audioBlob, true); // keepRecording = true，继续录音
        });
        console.log('[Chat] ✅ startRecording 调用完成，当前状态:', {
          isRecording,
          isSpeaking
        });
      } catch (error) {
        // 错误已经在 hook 中处理
        console.error('[Chat] ❌ startRecording 出错:', error);
        setVadStatus('idle');
      }
    }
  };

  // 处理取消录音（从 VAD 状态组件的取消按钮触发）
  const handleCancelRecording = () => {
    console.log('[Chat] 🚫 用户点击取消按钮，取消录音');
    cancelRecording(); // 调用 hook 提供的取消方法
    setVadStatus('idle');
    message.info('已取消录音');
  };

  // 处理剪贴板粘贴事件 - 支持图片粘贴
  const handlePaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    // 检查当前模型是否支持图片
    if (!currentSessionSupportsImage) {
      return; // 如果不支持图片，就让默认的文本粘贴行为继续
    }

    const clipboardData = e.clipboardData;
    if (!clipboardData) return;

    // 检查剪贴板中是否有图片文件
    const items = Array.from(clipboardData.items);
    const imageItems = items.filter(item => item.type.startsWith('image/'));

    if (imageItems.length > 0) {
      // 阻止默认的粘贴行为（避免粘贴图片的文件路径或其他文本）
      e.preventDefault();

      const processedImages: File[] = [];

      for (const item of imageItems) {
        const file = item.getAsFile();
        if (!file) continue;

        // 检查文件类型（虽然我们已经过滤了，但为了一致性再检查一次）
        if (!file.type.startsWith('image/')) {
          message.error(`粘贴的文件不是图片格式`);
          continue;
        }

        // 检查文件大小 (限制为10MB)
        if (file.size > 10 * 1024 * 1024) {
          message.error(`粘贴的图片大小不能超过10MB`);
          continue;
        }

        try {
          // 检查是否需要格式转换
          let processedFile = file;
          
          // 剪贴板图片经常是非标准格式，为了确保API兼容性，都转换为PNG
          // 这样可以避免WebP、BMP等格式的兼容性问题
          console.log(`剪贴板图片格式: ${file.type}，转换为PNG以确保兼容性`);
          processedFile = await convertImageToPNG(file);
          
          processedImages.push(processedFile);

          // 创建预览
          const reader = new FileReader();
          reader.onload = (event) => {
            const preview = event.target?.result as string;
            setImagePreviews(prev => [...prev, preview]);
          };
          reader.readAsDataURL(processedFile);
        } catch (error) {
          console.error('剪贴板图片处理失败:', error);
          message.error(`图片处理失败，请重试`);
          continue;
        }
      }

      if (processedImages.length > 0) {
        setSelectedImages(prev => [...prev, ...processedImages]);
        message.success(`成功粘贴 ${processedImages.length} 张图片`);
      }
    }
    // 如果没有图片，就让默认的文本粘贴行为继续
  };

  // 检测内容是否为JSON
  const isJSON = (str: string) => {
    try {
      JSON.parse(str);
      return true;
    } catch (e) {
      return false;
    }
  };

  // 检测内容是否为代码块
  const isCodeBlock = (str: string) => {
    return str.startsWith('```') && str.endsWith('```');
  };

  // 提取代码块的语言和内容
  const extractCodeBlock = (str: string) => {
    const lines = str.split('\n');
    const firstLine = lines[0].slice(3).trim();
    const language = firstLine || 'plaintext';
    
    // 提取代码内容，移除首尾的空行
    let codeLines = lines.slice(1, -1); // 移除第一行（```语言）和最后一行（```）
    
    // 如果第一行有语言标识，再移除一行
    if (firstLine) {
      codeLines = codeLines.slice(1);
    }
    
    // 移除开头和结尾的空行
    while (codeLines.length > 0 && codeLines[0].trim() === '') {
      codeLines.shift();
    }
    while (codeLines.length > 0 && codeLines[codeLines.length - 1].trim() === '') {
      codeLines.pop();
    }
    
    // 连接时不在末尾添加换行符
    const code = codeLines.join('\n');
    return { language, code };
  };

  // 复制代码到剪贴板
  const copyToClipboard = (text: string, e: React.MouseEvent) => {
    e.stopPropagation();  // 阻止事件冒泡
    if (!text) return;
    
    try {
      // 使用异步函数包装
      const copyText = async () => {
        try {
          await navigator.clipboard.writeText(text);
          message.success('复制成功');
        } catch (err) {
          // 降级方案：使用传统的复制方法
          const textArea = document.createElement('textarea');
          textArea.value = text;
          document.body.appendChild(textArea);
          textArea.select();
          try {
            document.execCommand('copy');
            message.success('复制成功');
          } catch (e) {
            message.error('复制失败，请手动复制');
          }
          document.body.removeChild(textArea);
        }
      };
      copyText();
    } catch (error) {
      message.error('复制失败，请手动复制');
    }
  };

  // 删除消息函数
  const handleDeleteMessage = (index: number, content: string) => {
    setMessageToDelete({ index, content });
    setDeleteMessageModalVisible(true);
  };

  const confirmDeleteMessage = async () => {
    if (!messageToDelete || !currentSession) {
      return;
    }

    try {
      const apiUrl = getFullUrl('/api/chat/sessions');
      
      // 获取当前消息的时间戳用于精确定位
      const targetMsg = messages[messageToDelete.index];
      const targetTimestamp = targetMsg?.timestamp;
      
      // 调试：打印要删除的消息信息
      console.log('🔍 准备删除的消息:', {
        index: messageToDelete.index,
        targetMsg,
        timestamp: targetTimestamp,
        allMessages: messages
      });
      
      const response = await fetch(`${apiUrl}/${currentSession.session_id}/messages/${messageToDelete.index}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${useAuthStore.getState().token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          timestamp: targetTimestamp  // 添加时间戳用于精确定位
        })
      });

      if (response.ok) {
        // 从本地状态中移除消息
        setMessages(prevMessages => 
          prevMessages.filter((_, i) => i !== messageToDelete.index)
        );
        
        // 更新会话列表中的消息数量
        const newMessageCount = (currentSession.message_count || 0) - 1;
        updateSessionMessageCount(currentSession.session_id, newMessageCount);
        
        message.success('消息已删除');
      } else {
        const errorData = await response.json();
        message.error(`删除失败: ${errorData.detail || '未知错误'}`);
      }
    } catch (error) {
      console.error('删除消息失败:', error);
      message.error('删除消息失败');
    } finally {
      setDeleteMessageModalVisible(false);
      setMessageToDelete(null);
    }
  };

  // 修改消息函数
  const handleEditMessage = (index: number, content: string, images?: string[]) => {
    setMessageToEdit({ index, content, images: images || [] });
    setEditedContent(content);
    setEditedImages(images || []);
    setEditMessageModalVisible(true);
  };

  const confirmEditMessage = async () => {
    if (!messageToEdit || !currentSession) {
      return;
    }

    try {
      const apiUrl = getFullUrl('/api/chat/sessions');
      
      // 获取当前消息的时间戳用于精确定位
      const targetMsg = messages[messageToEdit.index];
      const targetTimestamp = targetMsg?.timestamp;
      
      const response = await fetch(`${apiUrl}/${currentSession.session_id}/messages/${messageToEdit.index}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${useAuthStore.getState().token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          timestamp: targetTimestamp,  // 添加时间戳用于精确定位
          content: editedContent,
          images: editedImages,
          images_to_delete: (messageToEdit.images || []).filter(img => !editedImages.includes(img))
        })
      });

      if (response.ok) {
        // 更新本地消息状态
        setMessages(prevMessages => 
          prevMessages.map((msg, i) => 
            i === messageToEdit.index 
              ? { ...msg, content: editedContent, images: editedImages }
              : msg
          )
        );
        
        message.success('消息已修改');
      } else {
        const errorData = await response.json();
        message.error(`修改失败: ${errorData.detail || '未知错误'}`);
      }
    } catch (error) {
      console.error('修改消息失败:', error);
      message.error('修改消息失败');
    } finally {
      setEditMessageModalVisible(false);
      setMessageToEdit(null);
      setEditedContent('');
      setEditedImages([]);
    }
  };
  
  // 将远程图片 URL 转为 File（以便复用 sendMessage 里现有的本地图片->base64 上传流程）
  const fetchUrlAsFile = async (url: string, filename?: string): Promise<File> => {
      // 对受保护的后端图片接口补充鉴权；并校验响应类型
      const headers: Record<string, string> = {};
      try {
        const origin = window.location.origin;
        const target = new URL(url, origin);
        if (target.origin === origin && target.pathname.startsWith('/api/')) {
          // 优先使用内存中的 token，避免 localStorage 尚未同步导致 401
          let token = '';
          try {
            token = useAuthStore.getState().token || '';
          } catch {}
          if (!token) {
            const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
            token = authState.state?.token || '';
          }
          headers['Authorization'] = `Bearer ${token}`;
        }
      } catch {}

      const response = await fetch(url, { headers });
      if (!response.ok) {
        throw new Error(`获取图片失败: ${response.status} ${response.statusText}`);
      }

      const blob = await response.blob();
      // 若后端返回的是JSON（通常是未授权或错误），直接报错，避免把错误JSON当作图片编码
      if (blob.type && blob.type.includes('application/json')) {
        try {
          const text = await blob.text();
          console.error('[Chat] 获取图片返回JSON而非二进制：', text);
        } catch {}
        throw new Error('获取图片失败：可能未登录或没有权限');
      }

      const name = filename || url.split('/').pop() || `image_${Date.now()}.png`;
      const mime = blob.type && blob.type !== '' ? blob.type : 'image/png';
      return new File([blob], name, { type: mime });
    };
  
  // 新增：带容错的下载方法，部分失败不影响其他图片
  const urlsToFilesSafe = async (urls: string[]): Promise<{ files: File[]; previews: string[]; failed: string[] }> => {
    const httpUrls = urls.map(u => convertMinioUrlToHttp(u));
    const results = await Promise.allSettled(
      httpUrls.map((u, i) => fetchUrlAsFile(u, `image_${i + 1}.png`))
    );
    const files: File[] = [];
    const previews: string[] = [];
    const failed: string[] = [];
    for (let i = 0; i < results.length; i++) {
      const r = results[i];
      if (r.status === 'fulfilled') {
        files.push(r.value);
        previews.push(httpUrls[i]);
      } else {
        console.error('[Chat] 图片准备失败:', httpUrls[i], r.reason);
        failed.push(httpUrls[i]);
      }
    }
    return { files, previews, failed };
  };
  
      // 从当前消息"重新发送"
  const handleResendFromMessage = async () => {
    if (!messageToEdit || !currentSession) return;
    const editingMsg = messages[messageToEdit.index];
    if (!editingMsg || editingMsg.role !== 'user') return;

    Modal.confirm({
      title: '确认重新发送？',
      content: '将删除本条消息及其之后的所有历史消息（包含图片文件），然后以前端当前编辑内容直接重新发送。不会修改数据库中的原消息。',
      okText: '确定',
      cancelText: '取消',
      async onOk() {
        try {
          if (isProcessing) {
            message.warning('当前仍在处理上一条消息，请稍后再试');
            return Promise.reject();
          }

          const finalContent = editedContent ?? messageToEdit.content ?? '';
          const finalImages = editedImages ?? messageToEdit.images ?? [];

          // 1) 先把需要重发的图片下载为本地 File，避免删除历史后取不到
          let files: File[] = [];
          let previewUrls: string[] = [];
          if (finalImages.length > 0) {
            try {
              const { files: okFiles, previews, failed } = await urlsToFilesSafe(finalImages);
              files = okFiles;
              previewUrls = previews;
              if (failed.length > 0) {
                message.warning(`部分图片处理失败（${failed.length}/${finalImages.length}），将仅发送成功部分`);
              }
            } catch (e) {
              console.error('图片准备失败:', e);
              message.warning('部分图片处理失败，将仅重新发送文本内容');
              files = [];
              previewUrls = [];
            }
          }

          // 1.1) 为即时渲染生成本地 dataURL 预览，避免使用可能已被删除的后端URL
          let localDataPreviews: string[] = [];
          if (files.length > 0) {
            try {
              localDataPreviews = await Promise.all(
                files.map(file => new Promise<string>((resolve, reject) => {
                  const reader = new FileReader();
                  reader.onload = (e) => resolve(e.target?.result as string);
                  reader.onerror = reject;
                  reader.readAsDataURL(file);
                }))
              );
            } catch (e) {
              console.error('生成本地预览失败，将回退到后端URL预览:', e);
              localDataPreviews = previewUrls; // 回退
            }
          }

          const hasText = (finalContent || '').trim().length > 0;
          const hasAnyImage = files.length > 0;
          if (!hasText && !hasAnyImage) {
            message.warning('没有可发送的内容');
            return Promise.reject();
          }

          // 2) 再删除历史（包含当前这条）
          const apiUrl = getFullUrl('/api/chat/sessions');
          
          // 如果当前是第一条消息（index=0），使用 -1 清空所有消息
          // 否则，获取前一条消息的时间戳，删除其之后的所有消息
          let deleteUrl = '';
          let needsBody = false;
          let targetTimestamp = null;
          
          if (messageToEdit.index === 0) {
            // 重新发送第一条消息，清空所有消息
            deleteUrl = `${apiUrl}/${currentSession.session_id}/messages/-1/after`;
            needsBody = false;
          } else {
            // 重新发送非第一条消息，删除前一条消息之后的所有消息
            const prevMsgIndex = messageToEdit.index - 1;
            if (prevMsgIndex >= 0 && messages[prevMsgIndex]) {
              targetTimestamp = messages[prevMsgIndex].timestamp;
            }
            
            if (!targetTimestamp) {
              message.error('无法定位消息，请刷新后重试');
              return Promise.reject();
            }
            
            deleteUrl = `${apiUrl}/${currentSession.session_id}/messages/0/after`;
            needsBody = true;
          }
          
          const deleteOptions: RequestInit = {
            method: 'DELETE',
            headers: {
              'Authorization': `Bearer ${useAuthStore.getState().token}`,
              'Content-Type': 'application/json'
            }
          };
          
          if (needsBody) {
            deleteOptions.body = JSON.stringify({ timestamp: targetTimestamp });
          }
          
          const resp = await fetch(deleteUrl, deleteOptions);
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            message.error(`删除历史失败：${err.detail || '未知错误'}`);
            return Promise.reject();
          }

          // 3) 本地也同步截断
          setMessages(prev => prev.slice(0, messageToEdit.index));
          updateSessionMessageCount(currentSession.session_id, messageToEdit.index);

          // 4) 关闭编辑态并同步输入区显示
          setEditMessageModalVisible(false);
          setMessageToEdit(null);
          setEditedContent('');
          setEditedImages([]);
          setCurrentMessage(finalContent);
          setSentFlag((finalContent || '').trim().length > 0);
          setSelectedImages(files);
          setImagePreviews(localDataPreviews);

          // 5) 发送（显式传参，避免状态竞争）
          await sendMessage({ text: finalContent, files, previews: localDataPreviews });
          message.success('已重新发送该消息');
          return Promise.resolve();
        } catch (e) {
          console.error(e);
          return Promise.reject(e);
        }
      }
    });
  };


  const handleRemoveImageFromEdit = (imageUrl: string) => {
    setEditedImages(prev => prev.filter(img => img !== imageUrl));
  };

  // 导出对话数据函数
  const handleExportChat = (session: ChatSession) => {
    setExportingSession(session);
    setExportFileName(session.name);
    setExportChatModalVisible(true);
  };

  // 清空对话（删除该会话的所有历史消息，并由后端清理其中的 MinIO 图片）
  const handleClearChat = (session: ChatSession) => {
    Modal.confirm({
      title: '确认清空',
      content: '将删除该会话的所有历史消息（包含消息中的图片文件）。此操作不可恢复，确定继续吗？',
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { className: styles.deleteButton },
      async onOk() {
        try {
          const apiUrl = getFullUrl('/api/chat/sessions');
          // 传 -1 表示删除全部历史，后端会同时清理 MinIO 图片
          const resp = await fetch(`${apiUrl}/${session.session_id}/messages/-1/after`, {
            method: 'DELETE',
            headers: {
              'Authorization': `Bearer ${useAuthStore.getState().token}`
            }
          });
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            message.error(`清空对话失败：${err.detail || '未知错误'}`);
            return Promise.reject();
          }

          // 本地状态同步清空
          setMessages([]);
          updateSessionMessageCount(session.session_id, 0);
          message.success('对话已清空');
        } catch (e) {
          console.error('[Chat] 清空对话失败:', e);
          message.error('清空对话失败，请重试');
        }
      }
    });
  };

  const confirmExportChat = async () => {
    if (!exportingSession || !exportFileName.trim()) {
      message.error('请输入文件名');
      return;
    }

    try {
      const apiBase = getFullUrl('/api/chat/sessions');

      if (exportFormat === 'txt') {
        const response = await fetch(`${apiBase}/${exportingSession.session_id}/export`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${useAuthStore.getState().token}`,
            'Content-Type': 'application/json'
          }
        });

        if (response.ok) {
          const data = await response.json();
          const blob = new Blob([data.data.conversation_text], { type: 'text/plain;charset=utf-8' });
          const url = window.URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = `${exportFileName.trim()}.txt`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          window.URL.revokeObjectURL(url);
          message.success('对话数据导出成功');
        } else {
          const errorData = await response.json();
          message.error(`导出失败: ${errorData.detail || '未知错误'}`);
        }
        return;
      }

      // JSON 导出
      const msgResp = await fetch(`${apiBase}/${exportingSession.session_id}/messages`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${useAuthStore.getState().token}`,
          'Content-Type': 'application/json'
        }
      });
      if (!msgResp.ok) {
        const err = await msgResp.json().catch(() => ({}));
        message.error(`获取会话消息失败: ${err.detail || '未知错误'}`);
        return;
      }
      const history = await msgResp.json();

      const originalPrompt = exportingSession.system_prompt || '';
      const kbPrompt = (exportingSession as any)?.kb_settings?.kb_prompt_template || '';

      const toLocalOffsetISOString = (input: any): string | undefined => {
        if (input === undefined || input === null || input === '') return undefined;

        let d: Date;
        if (typeof input === 'number') {
          d = new Date(input);
        } else if (typeof input === 'string') {
          const hasTz = /([Zz]|[+\-]\d{2}:?\d{2})$/.test(input);
          const isoLike = /\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}/.test(input);
          if (isoLike && !hasTz) {
            d = new Date(input.replace(' ', 'T') + 'Z');
          } else {
            d = new Date(input);
          }
        } else if (input instanceof Date) {
          d = input as Date;
        } else {
          d = new Date(input);
        }

        if (isNaN(d.getTime())) return undefined;

        const pad = (n: number) => String(n).padStart(2, '0');
        const year = d.getFullYear();
        const month = pad(d.getMonth() + 1);
        const day = pad(d.getDate());
        const hours = pad(d.getHours());
        const minutes = pad(d.getMinutes());
        const seconds = pad(d.getSeconds());
        const offsetMin = -d.getTimezoneOffset();
        const sign = offsetMin >= 0 ? '+' : '-';
        const absMin = Math.abs(offsetMin);
        const offH = pad(Math.floor(absMin / 60));
        const offM = pad(absMin % 60);
        return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}${sign}${offH}:${offM}`;
      };

      const exportJson: any = {};
      exportJson.session_name = exportingSession.name;

      if (exportIncludeSystemPrompts) {
        const sys: any = {};
        if (originalPrompt) sys.original_prompt = originalPrompt;
        if (kbPrompt) sys.knowledge_base_prompt = kbPrompt;
        if (Object.keys(sys).length > 0) {
          exportJson.system = sys;
        }
      }

      exportJson.messages = [] as any[];
      const cleaned = Array.isArray(history) ? history : [];
      for (const msg of cleaned) {
        if (msg?.role !== 'user' && msg?.role !== 'assistant') continue;
        const item: any = {
          role: msg.role,
          content: msg.content ?? ''
        };
        if (exportIncludeTimestamps) {
          const ts = msg.timestamp || msg.create_time || msg.created_at;
          const localTs = toLocalOffsetISOString(ts);
          if (localTs) item.timestamp = localTs;
        }
        exportJson.messages.push(item);
      }

      const jsonStr = JSON.stringify(exportJson, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${exportFileName.trim()}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      message.success('对话数据导出成功');
    } catch (error) {
      console.error('导出对话数据失败:', error);
      message.error('导出对话数据失败');
    } finally {
      setExportChatModalVisible(false);
      setExportingSession(null);
      setExportFileName('');
      setExportFormat('txt');
      setExportIncludeTimestamps(true);
      setExportIncludeSystemPrompts(true);
    }
  };

  // 代码块滚动控制函数 - 滚动页面到代码的不同位置
  const scrollToCodeTop = (e: React.MouseEvent, codeElement: HTMLElement) => {
    e.stopPropagation();
    // 找到代码块的标题栏进行定位
    const codeBlock = codeElement.closest(`.${styles.codeBlock}`);
    const codeHeader = codeBlock?.querySelector(`.${styles.codeHeader}`);
    const targetElement = codeHeader || codeElement;
    
    targetElement.scrollIntoView({
      behavior: 'auto', // 使用瞬间滚动，速度更快
      block: 'start',
      inline: 'nearest'
    });
  };

  const scrollToCodeBottom = (e: React.MouseEvent, codeElement: HTMLElement) => {
    e.stopPropagation();
    codeElement.scrollIntoView({
      behavior: 'auto', // 使用瞬间滚动，速度更快
      block: 'end',
      inline: 'nearest'
    });
  };

  // 渲染代码块
  const renderCodeBlock = (code: string, language: string) => {
    // 如果代码为空，返回简单提示
    if (!code || code.trim() === '') {
      return <div className={styles.codeBlock} style={{ padding: '12px', color: '#888' }}>空代码块</div>;
    }
    
    // 去除代码首尾的换行符，防止产生多余的空行
    const cleanCode = code.replace(/^\n+|\n+$/g, '');
    const codeLines = cleanCode ? cleanCode.split('\n') : [''];
    const lineCount = codeLines.length;
    const shouldShowScrollButtons = lineCount > 30; // 超过30行才显示滚动按钮
    const hasLanguage = language && language.trim() && language !== 'plaintext'; // 检查是否有有效语言
    
    // 移除基于代码长度的样式判断，所有代码块使用统一样式
    
    try {
      // 整块高亮一次，然后按行包裹并添加行号
      const highlightedBlock = getHighlightedHtml(cleanCode, language || 'plaintext');
      const highlightedLines = highlightedBlock.split('\n');
      const linesWithNumbers = highlightedLines.map((lineHtml, index) => {
        const lineNumber = index + 1;
        return `<div class="${styles.codeLine}"><span class="${styles.lineNumber}">${lineNumber}</span><span class="${styles.lineContent}">${lineHtml}</span></div>`;
      }).join('');
      
      return (
        <div className={`${styles.codeBlock} ${shouldShowScrollButtons ? styles.hasScrollButtons : ''}`}>
          {/* 只有当有语言信息时才显示头部栏 */}
          {hasLanguage ? (
            <div className={styles.codeHeader}>
              <span className={styles.codeLanguage}>{language}</span> {/* 保持原始大小写 */}
              <div className={styles.codeHeaderButtons}>
                {shouldShowScrollButtons && (
                  <Button 
                    className={styles.codeHeaderButton}
                    icon={<DownOutlined />}
                    onClick={(e) => {
                      const wrapper = e.currentTarget.closest(`.${styles.codeBlock}`)?.querySelector(`.${styles.codeWrapper}`) as HTMLElement;
                      if (wrapper) scrollToCodeBottom(e, wrapper);
                    }}
                    type="text"
                    size="small"
                    title="滚动到代码底部"
                  />
                )}
                <Button 
                  className={styles.codeHeaderButton}
                  icon={<CopyOutlined />}
                  onClick={(e) => copyToClipboard(code, e)}
                  type="text"
                  size="small"
                  title="复制代码"
                />
              </div>
            </div>
          ) : (
            /* 没有语言信息时，只显示一个复制按钮 */
          <Button 
            className={styles.copyButton}
            icon={<CopyOutlined />}
            onClick={(e) => copyToClipboard(code, e)}
            type="text"
            size="small"
              title="复制代码"
          />
          )}
          
          <div className={styles.codeWrapper}>
            <div className={styles.codeWithLineNumbers}>
              <pre className={styles.codeContentWithLineNumbers}>
                <code dangerouslySetInnerHTML={{ __html: linesWithNumbers }} />
            </pre>
          </div>
          </div>
          
          {/* 底部按钮 */}
          {shouldShowScrollButtons && (
            <>
              <Button 
                className={styles.codeScrollToTop}
                icon={<UpOutlined />}
                onClick={(e) => {
                  const wrapper = e.currentTarget.parentElement?.querySelector(`.${styles.codeWrapper}`) as HTMLElement;
                  if (wrapper) scrollToCodeTop(e, wrapper);
                }}
                type="text"
                size="small"
                title="滚动到代码顶部"
              />
              <Button 
                className={styles.codeBottomCopyButton}
                icon={<CopyOutlined />}
                onClick={(e) => copyToClipboard(code, e)}
                type="text"
                size="small"
                title="复制代码"
              />
            </>
          )}
        </div>
      );
    } catch (e) {
      // 对于无法高亮的代码，也添加行号（整块转义后再分行）
      const escapedBlock = cleanCode
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      const escapedLines = escapedBlock.split('\n');
      const linesWithNumbers = escapedLines.map((lineHtml, index) => {
        const lineNumber = index + 1;
        return `<div class="${styles.codeLine}"><span class="${styles.lineNumber}">${lineNumber}</span><span class="${styles.lineContent}">${lineHtml}</span></div>`;
      }).join('');
      
      return (
        <div className={`${styles.codeBlock} ${shouldShowScrollButtons ? styles.hasScrollButtons : ''}`}>
          {/* 只有当有语言信息时才显示头部栏 */}
          {hasLanguage ? (
            <div className={styles.codeHeader}>
              <span className={styles.codeLanguage}>{language}</span> {/* 保持原始大小写 */}
              <div className={styles.codeHeaderButtons}>
                {shouldShowScrollButtons && (
                  <Button 
                    className={styles.codeHeaderButton}
                    icon={<DownOutlined />}
                    onClick={(e) => {
                      const wrapper = e.currentTarget.closest(`.${styles.codeBlock}`)?.querySelector(`.${styles.codeWrapper}`) as HTMLElement;
                      if (wrapper) scrollToCodeBottom(e, wrapper);
                    }}
                    type="text"
                    size="small"
                    title="滚动到代码底部"
                  />
                )}
                <Button 
                  className={styles.codeHeaderButton}
                  icon={<CopyOutlined />}
                  onClick={(e) => copyToClipboard(code, e)}
                  type="text"
                  size="small"
                  title="复制代码"
                />
              </div>
            </div>
          ) : (
            /* 没有语言信息时，只显示一个复制按钮 */
          <Button 
            className={styles.copyButton}
            icon={<CopyOutlined />}
            onClick={(e) => copyToClipboard(code, e)}
            type="text"
            size="small"
              title="复制代码"
          />
          )}
          
          <div className={styles.codeWrapper}>
            <div className={styles.codeWithLineNumbers}>
              <pre className={styles.codeContentWithLineNumbers}>
                <code dangerouslySetInnerHTML={{ __html: linesWithNumbers }} />
              </pre>
          </div>
          </div>
          
          {/* 底部按钮 */}
          {shouldShowScrollButtons && (
            <>
              <Button 
                className={styles.codeScrollToTop}
                icon={<UpOutlined />}
                onClick={(e) => {
                  const wrapper = e.currentTarget.parentElement?.querySelector(`.${styles.codeWrapper}`) as HTMLElement;
                  if (wrapper) scrollToCodeTop(e, wrapper);
                }}
                type="text"
                size="small"
                title="滚动到代码顶部"
              />
              <Button 
                className={styles.codeBottomCopyButton}
                icon={<CopyOutlined />}
                onClick={(e) => copyToClipboard(code, e)}
                type="text"
                size="small"
                title="复制代码"
              />
            </>
          )}
        </div>
      );
    }
  };

  // 解析深度思考内容（支持未完成的think标签）
  const parseThinkingContent = (content: string) => {
    const parts = [];
    let lastIndex = 0;
    
    // 首先处理完整的 <think>...</think> 标签对
    const completeThinkRegex = /<think>([\s\S]*?)<\/think>/g;
    let match;
    
    while ((match = completeThinkRegex.exec(content)) !== null) {
      // 添加think标签前的内容
      if (match.index > lastIndex) {
        const beforeThink = content.slice(lastIndex, match.index);
        if (beforeThink.trim()) {
          parts.push({ type: 'normal', content: beforeThink });
        }
      }
      
      // 添加完整的think标签内容
      parts.push({ type: 'thinking', content: match[1], isComplete: true });
      lastIndex = match.index + match[0].length;
    }

    // 检查是否有未完成的 <think> 标签（没有对应的 </think>）
    const remainingContent = content.slice(lastIndex);
    const incompleteThinkMatch = remainingContent.match(/<think>([\s\S]*)$/);
    
    if (incompleteThinkMatch) {
      // 有未完成的think标签
      const beforeIncompleteThink = remainingContent.slice(0, incompleteThinkMatch.index);
      if (beforeIncompleteThink.trim()) {
        parts.push({ type: 'normal', content: beforeIncompleteThink });
      }
      
      // 添加未完成的think内容
      parts.push({ 
        type: 'thinking', 
        content: incompleteThinkMatch[1], 
        isComplete: false 
      });
    } else if (remainingContent.trim()) {
      // 没有未完成的think标签，添加剩余的普通内容
      parts.push({ type: 'normal', content: remainingContent });
    }

    return parts.length > 0 ? parts : [{ type: 'normal', content }];
  };

  // 深度思考组件
  const ThinkingSection: React.FC<{ 
    content: string; 
    messageIndex: number; 
    thinkingIndex: number;
    messageTimestamp?: string;
    isComplete?: boolean;
    onToggle: (stateKey: string) => void;
    isExpanded: boolean;
  }> = React.memo(({ content, messageIndex, thinkingIndex, messageTimestamp, isComplete = true, onToggle, isExpanded }) => {
    // 使用消息时间戳作为稳定标识符，如果没有则使用索引
    const messageId = messageTimestamp || `msg-${messageIndex}`;
    const stateKey = `${messageId}-think-${thinkingIndex}`;
    
    const handleToggle = useCallback(() => {
      onToggle(stateKey);
    }, [onToggle, stateKey]);
    
    return (
      <div className={`${styles.thinkingSection} ${!isComplete ? styles.thinkingSectionInProgress : ''}`}>
        <div 
          className={styles.thinkingHeader}
          onClick={handleToggle}
        >
          <span className={styles.thinkingIcon}>
            {isExpanded ? '▼' : '▶'}
          </span>
          <span className={styles.thinkingLabel}>
            深度思考{!isComplete && ' (进行中...)'}
          </span>
          <span className={styles.thinkingToggle}>
            {isExpanded ? '收起' : '展开'}
          </span>
        </div>
        {isExpanded && (
          <div className={styles.thinkingContent}>
            {isComplete ? (
              <ReactMarkdown
                components={{
                  code({ className, children }) {
                    const language = className?.replace('language-', '') || 'plaintext';
                    return renderCodeBlock(String(children), language);
                  },
                  p: ({ children }) => <span style={{ whiteSpace: 'normal', display: 'inline' }}>{children}</span>,
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  )
                }}
                remarkPlugins={[remarkGfm]}
              >
                {content}
              </ReactMarkdown>
            ) : (
              // 对于未完成的内容，使用简单的文本渲染避免频繁的Markdown解析
              <div style={{ whiteSpace: 'normal', margin: 0, lineHeight: 1.5 }}>
                {content}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }, (prevProps, nextProps) => {
    // 自定义比较函数，只有内容真正变化时才重新渲染
    return (
      prevProps.content === nextProps.content &&
      prevProps.messageIndex === nextProps.messageIndex &&
      prevProps.thinkingIndex === nextProps.thinkingIndex &&
      prevProps.messageTimestamp === nextProps.messageTimestamp &&
      prevProps.isComplete === nextProps.isComplete &&
      prevProps.isExpanded === nextProps.isExpanded &&
      prevProps.onToggle === nextProps.onToggle
    );
  });

  // 渲染消息内容
  const renderMessageContent = useCallback((content: string, messageIndex: number, messageTimestamp?: string, references?: any[]) => {
    // 检查是否包含深度思考标签
    if (content.includes('<think>')) {
      const parts = parseThinkingContent(content);
      return (
        <div>
          {parts.map((part, index) => {
            if (part.type === 'thinking') {
              const messageId = messageTimestamp || `msg-${messageIndex}`;
              const stateKey = `${messageId}-think-${index}`;
              const isExpanded = thinkingSectionStates[stateKey] ?? false;
              
              return (
                <ThinkingSection 
                  key={`thinking-${messageIndex}-${index}`} 
                  content={part.content} 
                  messageIndex={messageIndex}
                  thinkingIndex={index}
                  messageTimestamp={messageTimestamp}
                  isComplete={part.isComplete}
                  onToggle={toggleThinkingSection}
                  isExpanded={isExpanded}
                />
              );
            } else {
              // 渲染普通内容
              return (
                <div key={`normal-${messageIndex}-${index}`}>
                  {renderNormalContent(part.content, references)}
                </div>
              );
            }
          })}
        </div>
      );
    }

    return renderNormalContent(content, references);
  }, [thinkingSectionStates, toggleThinkingSection]);

  // 仅在代码块外部将 \\n 转换为换行，避免破坏三引号代码块内容
  const decodeOutsideCodeBlocks = (text: string) => {
    const blocks: string[] = [];
    const masked = text.replace(/```[\s\S]*?```/g, (m) => {
      blocks.push(m);
      return `§CODE_BLOCK_${blocks.length - 1}§`;
    });
    const decoded = masked
      .replace(/\r\n/g, '\n')
      .replace(/\\n/g, '\n');
    return decoded.replace(/§CODE_BLOCK_(\d+)§/g, (_, i) => blocks[Number(i)]);
  };

  // 渲染普通内容（原来的逻辑）
  const renderNormalContent = (content: string, references?: any[]) => {
    // 统一规范 references 为数组
    let normalizedRefs: any[] = [];
    if (Array.isArray(references)) {
      normalizedRefs = references;
    } else if (references && typeof references === 'object') {
      // 兼容 {chunks:[...]} 或 {0:ref0,1:ref1}
      // 优先使用 chunks
      // @ts-ignore
      normalizedRefs = Array.isArray(references.chunks)
        // @ts-ignore
        ? references.chunks
        : Object.values(references);
    }

    // 检查是否为JSON字符串
    if (isJSON(content)) {
      try {
        const jsonData = JSON.parse(content);
        // 如果是空对象或空数组，直接显示原始文本
        if (Object.keys(jsonData).length === 0 || 
           (Array.isArray(jsonData) && jsonData.length === 0)) {
          return <pre>{content}</pre>;
        }
        return (
          <div className={styles.jsonViewer}>
            <JsonViewer.default 
              value={jsonData}
              style={{ backgroundColor: 'transparent' }}
              displayDataTypes={false}
              enableClipboard={true}
            />
          </div>
        );
      } catch (e) {
        return <pre>{content}</pre>;
      }
    }

    // 检查是否为代码块
    if (isCodeBlock(content)) {
      const { language, code } = extractCodeBlock(content);
      return renderCodeBlock(code, language);
    }

    // 如果不是JSON也不是代码块，使用ReactMarkdown渲染
    const decodedMarkdownText = decodeOutsideCodeBlocks(content);

    return (
      <ReactMarkdown
        components={{
                    code({ className, children }: any) {
            const codeContent = String(children).replace(/\n+$/, ''); // 移除末尾换行符
            const isInline = !className && !codeContent.includes('\n');
            
            // 只有多行代码块才使用代码块渲染器（有className或包含换行符）
            if (!isInline && (className || codeContent.includes('\n'))) {
            const language = className?.replace('language-', '') || 'plaintext';
              return renderCodeBlock(codeContent, language);
            }
            
            // 内联代码使用简单的code标签
            return (
              <code 
                style={{
                  backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  padding: '2px 4px',
                  borderRadius: '3px',
                  fontFamily: 'Monaco, Menlo, Ubuntu Mono, monospace',
                  fontSize: '0.9em'
                }}
              >
                {children}
              </code>
            );
          },
          // 列表与段落：去除默认外边距，保持紧凑换行
                      p: ({ children }) => <p style={{ whiteSpace: 'normal' }}>{children}</p>,
            ol: ({ children }) => <ol style={{ paddingLeft: '1.25em' }}>{children}</ol>,
            ul: ({ children }) => <ul style={{ paddingLeft: '1.25em' }}>{children}</ul>,
            li: ({ children }) => <li style={{ margin: 0 }}>{children}</li>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          )
        }}
        remarkPlugins={[remarkGfm, remarkBreaks]}
      >
        {decodedMarkdownText}
      </ReactMarkdown>
    );
  };

  // 判断是否需要显示时间分隔符
  const shouldShowTimestamp = (currentMsg: ChatMessage, previousMsg: ChatMessage | null): { show: boolean; format: 'time' | 'datetime' } | null => {
    if (!currentMsg.timestamp) {
      return null;
    }

    // 第一条消息，直接显示日期+时间
    if (!previousMsg?.timestamp) {
      return { show: true, format: 'datetime' };
    }

    const currentTime = dayjs(currentMsg.timestamp);
    const previousTime = dayjs(previousMsg.timestamp);

    // 计算时间差（分钟）
    const diffInMinutes = currentTime.diff(previousTime, 'minute');
    
    // 检查是否跨天（通过比较日期字符串）
    const currentDay = currentTime.format('YYYY-MM-DD');
    const previousDay = previousTime.format('YYYY-MM-DD');
    const isDifferentDay = currentDay !== previousDay;

    if (isDifferentDay) {
      // 跨天显示日期+时间
      return { show: true, format: 'datetime' };
    } else if (diffInMinutes >= 30) {
      // 同一天但间隔超过30分钟，显示时分秒
      return { show: true, format: 'time' };
    }

    return null;
  };

  // 格式化时间显示
  const formatTimestamp = (timestamp: string, format: 'time' | 'datetime'): string => {
    const time = dayjs(timestamp);
    if (format === 'datetime') {
      // 显示日期+时间，例如：10月18日 14:30:25
      return time.format('M月D日 HH:mm:ss');
    } else {
      // 只显示时分秒，例如：14:30:25
      return time.format('HH:mm:ss');
    }
  };


  // 查看文档原文
  const viewDocumentContent = async (docInfo: any) => {
    const { docId, kbId, title } = docInfo;
    
    if (!docId || !kbId) {
      message.info('此文档暂不支持查看原文');
      return;
    }
    
    // 显示加载提示
    const loadingMsg = message.loading('正在加载文档原文...', 0);
    
    try {
      // 🔧 正确获取 token（从 auth-storage 中解析）
      let token = '';
      const authData = localStorage.getItem('auth-storage');
      if (authData) {
        try {
          const { state } = JSON.parse(authData);
          token = state.token || '';
        } catch (error) {
          console.error('解析认证数据失败:', error);
        }
      }
      
      const response = await fetch(
        `/api/kb/${kbId}/documents/${docId}/content`,
        {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        }
      );
      
      if (!response.ok) {
        throw new Error('获取文档失败');
      }
      
      const data = await response.json();
      loadingMsg();
      
      // 检查是否为群聊（群聊中隐藏引用按钮）
      const isGroupChat = currentSession?.session_type === 'group';
      
      // 显示文档原文
      Modal.info({
        title: (
          <div className={styles.documentModalTitle}>
            <FileTextOutlined />
            <span>{title}</span>
          </div>
        ),
        width: 900,
        content: (
          <div>
            {/* 文档信息卡片 */}
            <div className={styles.documentInfoCard}>
              <div className={styles.documentInfoRow}>
                <span><strong>文件名：</strong>{data.document.filename}</span>
                <span><strong>文件类型：</strong>{data.document.file_type}</span>
              </div>
              <div className={styles.documentInfoRow}>
                <span><strong>分片数：</strong>{data.document.chunk_count}</span>
                <span><strong>文件大小：</strong>{(data.document.file_size / 1024).toFixed(2)} KB</span>
              </div>
            </div>
            {/* 文档内容区域 */}
            <div className={styles.documentContentArea}>
              {data.document.content}
            </div>
          </div>
        ),
        okText: '关闭',
        okCancel: !isGroupChat, // 群聊中不显示取消按钮（引用按钮）
        cancelText: '引用',
        okButtonProps: { style: { marginLeft: 8 } },
        onCancel: () => {
          // 点击"引用"按钮 - 添加到引用列表（仅在非群聊时可用）
          const newRef = {
            filename: data.document.filename,
            docId: docId,
            kbId: kbId
          };
          // 检查是否已经引用过此文档
          if (!referencedDocs.find(doc => doc.docId === newRef.docId)) {
            setReferencedDocs([...referencedDocs, newRef]);
            message.success(`已引用文档: @${data.document.filename}`);
          } else {
            message.info(`文档 @${data.document.filename} 已在引用列表中`);
          }
        },
        onOk() {}
      });
      
    } catch (error) {
      loadingMsg();
      console.error('获取文档原文失败:', error);
      message.error('获取文档原文失败，请稍后重试');
    }
  };

  // 🆕 知识图谱折叠组件
  const GraphMetadataCollapsible: React.FC<{ graphMetadata: GraphMetadata[] }> = ({ graphMetadata }) => {
    const [collapsed, setCollapsed] = React.useState(true);
    
    return (
      <div style={{ marginTop: '12px' }}>
        <div 
          style={{ 
            fontSize: '12px', 
            color: 'var(--text-secondary)', 
            marginBottom: collapsed ? '0' : '8px',
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            userSelect: 'none'
          }}
          onClick={() => setCollapsed(!collapsed)}
        >
          <NodeIndexOutlined style={{ marginRight: '4px' }} />
          知识图谱（{graphMetadata.length}）
          <span style={{ marginLeft: '6px', fontSize: '10px' }}>
            {collapsed ? '▶' : '▼'}
          </span>
        </div>
        {!collapsed && (
          <div style={{ marginTop: '8px' }}>
            {graphMetadata.map((graph, index) => (
              <div 
                key={graph.graph_id}
                className={styles.graphMetadataItem}
                onClick={() => {
                  setSelectedGraphData([graph]);
                  setGraphViewerVisible(true);
                }}
              >
                <NodeIndexOutlined style={{ color: '#52c41a', marginRight: '8px' }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: '13px', color: 'var(--text-primary)' }}>
                    {graph.tool_name || '知识图谱'}
                  </div>
                  <div style={{ fontSize: '11px', opacity: 0.7, color: 'var(--text-secondary)' }}>
                    {graph.node_count} 个节点 • {graph.edge_count} 条关系 • {graph.query}
                  </div>
                </div>
                <Button
                  size="small"
                  type="text"
                  style={{ marginLeft: '4px', color: '#52c41a' }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedGraphData([graph]);
                    setGraphViewerVisible(true);
                  }}
                >
                  查看图谱
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // 文档引用折叠组件
  const DocumentReferencesCollapsible: React.FC<{ references: any[] }> = ({ references }) => {
    const [collapsed, setCollapsed] = React.useState(true);
    
    return (
      <div style={{ marginTop: '12px' }}>
        <div 
          style={{ 
            fontSize: '12px', 
            color: 'var(--text-secondary)', 
            marginBottom: collapsed ? '0' : '8px',
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            userSelect: 'none'
          }}
          onClick={() => setCollapsed(!collapsed)}
        >
          <DatabaseOutlined style={{ marginRight: '4px' }} />
          引用来源（{references.length}）
          <span style={{ marginLeft: '6px', fontSize: '10px' }}>
            {collapsed ? '▶' : '▼'}
          </span>
        </div>
        {!collapsed && renderDocumentReferences(references)}
      </div>
    );
  };

     // 渲染文档引用列表
   const renderDocumentReferences = (references: any[]) => {
     if (!references || references.length === 0) return null;

     // 按文档分组引用，并提取文档标题
     const groupedRefs = references.reduce((acc: any, ref: any) => {
       // 优先使用 filename（本地RAG）
       let docName = ref.filename || 'Unknown Document';
       let docTitle = docName;
       
       // 🆕 获取文档ID和知识库ID（本地RAG）
       const docId = ref.doc_id || ref.document_id;
       const kbId = ref.kb_id || ref.dataset_id;
       
       // 尝试从content中提取文档标题
       try {
         if (ref.content && typeof ref.content === 'string') {
           const jsonContent = JSON.parse(ref.content);
           if (jsonContent && jsonContent['0'] && jsonContent['0'].Title) {
             docTitle = jsonContent['0'].Title;
           }
         }
       } catch {
         // 如果解析失败，使用原始文档名
       }
       
       if (!acc[docName]) {
         acc[docName] = {
           title: docTitle,
           filename: docName,
           docId: docId,  // 🆕 存储文档ID
           kbId: kbId,    // 🆕 存储知识库ID
           refs: []
         };
       }
       acc[docName].refs.push(ref);
       return acc;
     }, {});

    return (
      <div className={styles.documentReferences}>
        {Object.entries(groupedRefs).map(([docName, docInfo]: [string, any]) => (
         <div 
           key={docName} 
           className={styles.documentReferenceItem}
           style={{ cursor: docInfo.docId && docInfo.kbId ? 'pointer' : 'default' }}
           onClick={() => {
             // 点击卡片本身查看原文
             if (docInfo.docId && docInfo.kbId) {
               viewDocumentContent(docInfo);
             } else {
               console.log('文档信息缺失:', { docId: docInfo.docId, kbId: docInfo.kbId, docInfo });
               message.warning('此文档缺少必要信息，无法查看原文');
             }
           }}
         >
           <FileTextOutlined className={styles.documentReferenceIcon} />
           <div className={styles.documentReferenceContent}>
             <div className={styles.documentReferenceTitle}>
               {docInfo.title}
             </div>
             <div className={styles.documentReferenceInfo}>
               {docInfo.refs.length} 个引用片段 • {docInfo.filename}
             </div>
           </div>
            {/* 🆕 查看引用片段按钮 */}
            <Button
              size="small"
              type="text"
              className={styles.documentReferenceButton}
              onClick={(e) => {
                e.stopPropagation();
                // 显示引用片段
                Modal.info({
                  title: '文档引用详情',
                  width: 800,
                  content: (
                    <div>
                      <p><strong>文档标题:</strong> {docInfo.title}</p>
                      <p><strong>文件名:</strong> {docInfo.filename}</p>
                      <p><strong>引用片段数:</strong> {docInfo.refs.length}</p>
                      <div className={styles.referenceDetailContainer}>
                        <strong>引用片段:</strong>
                         {(() => {
                           const ReferenceList: React.FC<{ refs: any[] }> = ({ refs }) => {
                             const [expanded, setExpanded] = React.useState(false);
                             const visibleRefs = expanded ? refs : refs.slice(0, 3);
                             return (
                               <div>
                                 {visibleRefs.map((ref: any, index: number) => (
                                   <div key={index} className={styles.referenceChunkItem}>
                                     <div className={styles.referenceChunkMeta}>
                                       {(() => {
                                         const sim = Number(ref?.similarity ?? ref?.score ?? ref?.relevance ?? 0);
                                         return `相似度: ${ (sim * 100).toFixed(1) }%`;
                                       })()}
                                     </div>
                                     <div className={styles.referenceChunkContent}>
                                       {(() => {
                                         try {
                                           if (typeof ref.content === 'string') {
                                             const jsonContent = JSON.parse(ref.content);
                                             if (jsonContent['0'] && jsonContent['0'].Abstract) {
                                               return jsonContent['0'].Abstract.replace(/<[^>]*>/g, '').substring(0, 300) + '...';
                                             }
                                           }
                                           return typeof ref.content === 'string' 
                                             ? ref.content.substring(0, 300) + '...'
                                             : JSON.stringify(ref.content).substring(0, 300) + '...';
                                         } catch {
                                           try {
                                             return String(ref?.content ?? '');
                                           } catch {
                                             return '无法显示引用内容';
                                           }
                                         }
                                       })()}
                                     </div>
                                   </div>
                                 ))}
                                 {refs.length > 3 && (
                                   <div 
                                     className={styles.referenceExpandButton}
                                     onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
                                   >
                                     {expanded ? '收起' : `展开剩余 ${refs.length - 3} 条`}
                                   </div>
                                 )}
                               </div>
                             );
                           };
                           return <ReferenceList refs={docInfo.refs} />;
                         })()}
                      </div>
                    </div>
                  ),
                  onOk() {}
                });
              }}
            >
              查看引用
            </Button>
          </div>
         ))}
       </div>
     );
   };

  // 会话切换时加载对应背景
  useEffect(() => {
    (async () => {
      const fetchStartedAt = Date.now();
      backgroundFetchSeqRef.current = fetchStartedAt;
      try {
        // 优先使用内存中的 token，避免 localStorage 尚未同步导致 401
        let token = '';
        try { token = useAuthStore.getState().token || ''; } catch {}
        if (!token) {
          const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
          token = authState.state?.token || '';
        }
        if (!token) { if (backgroundManuallySetAtRef.current <= fetchStartedAt) setBackgroundImageUrl(''); return; }

        if (currentSession?.session_type === 'group' && currentGroupId) {
          const resp = await fetch(`/api/auth/group-background/${encodeURIComponent(currentGroupId)}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          if (resp.ok) {
            const data = await resp.json();
            const url = convertMinioUrlToHttp(data.data_url || data.background_url || '');
            if (backgroundManuallySetAtRef.current <= fetchStartedAt && backgroundFetchSeqRef.current === fetchStartedAt) {
              await setSafeBackgroundImage(url);
            }
          } else {
            if (backgroundManuallySetAtRef.current <= fetchStartedAt && backgroundFetchSeqRef.current === fetchStartedAt) {
              setBackgroundImageUrl('');
            }
          }
        } else if (currentSession?.session_id && currentSession?.session_type !== 'group') {
          const resp = await fetch(`/api/auth/role-background/${encodeURIComponent(currentSession.session_id)}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          if (resp.ok) {
            const data = await resp.json();
            const url = convertMinioUrlToHttp(data.data_url || data.background_url || '');
            if (backgroundManuallySetAtRef.current <= fetchStartedAt && backgroundFetchSeqRef.current === fetchStartedAt) {
              await setSafeBackgroundImage(url);
            }
          } else {
            if (backgroundManuallySetAtRef.current <= fetchStartedAt && backgroundFetchSeqRef.current === fetchStartedAt) {
              setBackgroundImageUrl('');
            }
          }
        } else {
          if (backgroundManuallySetAtRef.current <= fetchStartedAt && backgroundFetchSeqRef.current === fetchStartedAt) {
            setBackgroundImageUrl('');
          }
        }
      } catch (e) {
        if (backgroundManuallySetAtRef.current <= fetchStartedAt && backgroundFetchSeqRef.current === fetchStartedAt) {
          setBackgroundImageUrl('');
        }
      }
    })();
  }, [currentSession?.session_id, currentGroupId]);

  // 监听群聊背景刷新事件
  useEffect(() => {
    const handleRefreshGroupBackground = async (event: Event) => {
      const customEvent = event as CustomEvent<{ groupId: string }>;
      const { groupId } = customEvent.detail;
      
      // 刷新背景图片
      backgroundManuallySetAtRef.current = Date.now();
      await setSafeBackgroundImage(`/api/auth/group-background/${encodeURIComponent(groupId)}?t=${Date.now()}`);
    };

    window.addEventListener('refreshGroupBackground', handleRefreshGroupBackground);
    return () => {
      window.removeEventListener('refreshGroupBackground', handleRefreshGroupBackground);
    };
  }, []);

  // Safely set background image: if the URL is a protected API path, fetch with token and convert to blob URL
  const setSafeBackgroundImage = async (rawUrl: string) => {
    try {
      if (!rawUrl) {
        if (backgroundObjectUrlRef.current) {
          URL.revokeObjectURL(backgroundObjectUrlRef.current);
          backgroundObjectUrlRef.current = null;
        }
        setBackgroundImageUrl('');
        return;
      }

      const isDataUrl = rawUrl.startsWith('data:');
      const isAbsolute = /^https?:\/\//i.test(rawUrl);
      const origin = getFullUrl('');
      const isApiPath = rawUrl.includes('/api/auth/');

      // Only need authorized fetch for our protected API paths
      if (!isDataUrl && isApiPath) {
        // 优先使用内存中的 token，避免 localStorage 尚未同步导致 401
        let token = '';
        try {
          token = useAuthStore.getState().token || '';
        } catch {}
        if (!token) {
          const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
          token = authState.state?.token || '';
        }
        // Build absolute URL if needed
        const absoluteUrl = isAbsolute ? rawUrl : `${origin}${rawUrl.startsWith('/') ? '' : '/'}${rawUrl}`;
        const resp = await fetch(absoluteUrl, token ? { headers: { Authorization: `Bearer ${token}` } } : undefined);
        if (!resp.ok) throw new Error(`背景图片获取失败: ${resp.status}`);

        // 若返回JSON（/api/auth/role-background 返回 { data_url })，解析后直接设置
        const contentType = resp.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const json = await resp.json();
          const extracted = json?.data_url || json?.background_url || '';
          if (!extracted) throw new Error('响应中缺少 data_url/background_url');
          // 递归利用本函数设置，兼容 data: 或 其他可直接访问的 URL
          await setSafeBackgroundImage(extracted);
          return;
        }

        const blob = await resp.blob();
        // 容错：如果意外拿到JSON Blob，再次解析
        if (blob.type && blob.type.includes('application/json')) {
          try {
            const text = await blob.text();
            const json = JSON.parse(text);
            const extracted = json?.data_url || json?.background_url || '';
            if (extracted) {
              await setSafeBackgroundImage(extracted);
              return;
            }
          } catch {}
          throw new Error('获取到JSON而非图片数据');
        }

        const objectUrl = URL.createObjectURL(blob);
        if (backgroundObjectUrlRef.current) {
          URL.revokeObjectURL(backgroundObjectUrlRef.current);
        }
        backgroundObjectUrlRef.current = objectUrl;
        setBackgroundImageUrl(objectUrl);
        return;
      }

      // For data URLs or public URLs, set directly
      if (backgroundObjectUrlRef.current) {
        URL.revokeObjectURL(backgroundObjectUrlRef.current);
        backgroundObjectUrlRef.current = null;
      }
      setBackgroundImageUrl(rawUrl);
    } catch (err) {
      console.error('设置背景图片失败:', err);
      // Fallback: clear background
      if (backgroundObjectUrlRef.current) {
        URL.revokeObjectURL(backgroundObjectUrlRef.current);
        backgroundObjectUrlRef.current = null;
      }
      setBackgroundImageUrl('');
    }
  };

  // 代码高亮缓存，按 code+language 进行结果缓存，避免重复高亮计算
  const highlightCacheRef = useRef<Map<string, string>>(new Map());

  const getHighlightedHtml = useCallback((codeText: string, lang: string) => {
    const cacheKey = `${lang}__SEP__${codeText}`;
    const cached = highlightCacheRef.current.get(cacheKey);
    if (cached) return cached;
    try {
      const { value } = hljs.highlight(codeText, { language: lang || 'plaintext' });
      highlightCacheRef.current.set(cacheKey, value);
      return value;
    } catch {
      // 回退到转义文本
      const escaped = codeText
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
      highlightCacheRef.current.set(cacheKey, escaped);
      return escaped;
    }
  }, []);

  // 渲染消息列表
  return (
    <Layout className={styles.chatLayout}>
      {/* 隐藏的背景图片选择器 */}
      <input
        ref={hiddenBgInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={async (e) => {
          const file = e.target.files && e.target.files[0];
          if (!file) return;
          try {
            const reader = new FileReader();
            reader.onload = async (ev) => {
              const dataUrl = ev.target?.result as string;
              try {
                const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
                const token = authState.state?.token;
                if (!token) throw new Error('未登录');
                const base64 = dataUrl.startsWith('data:image') ? dataUrl.split(',')[1] : dataUrl;

                // 根据预先记录的"上传目标"决定上传到哪个会话
                const target = backgroundUploadTarget;
                if (target && target.type === 'group') {
                  const resp = await fetch('/api/auth/upload-group-background', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ avatar: base64, group_id: target.groupId })
                  });
                  if (!resp.ok) throw new Error(await resp.text());
                  await resp.json();
                  // 仅当目标正是当前群聊时，才立刻渲染
                  if (currentSession?.session_type === 'group' && currentGroupId === target.groupId) {
                    backgroundManuallySetAtRef.current = Date.now();
                    await setSafeBackgroundImage(`/api/auth/group-background/${encodeURIComponent(target.groupId)}`);
                  }
                } else if (currentSession?.session_type === 'group' && currentGroupId) {
                  // 回退：未记录目标但当前是群聊，按当前群聊上传
                  const resp = await fetch('/api/auth/upload-group-background', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ avatar: base64, group_id: currentGroupId })
                  });
                  if (!resp.ok) throw new Error(await resp.text());
                  await resp.json();
                  backgroundManuallySetAtRef.current = Date.now();
                  await setSafeBackgroundImage(`/api/auth/group-background/${encodeURIComponent(currentGroupId)}`);
                } else if (currentSession && currentSession.session_type !== 'group') {
                  // 回退：未记录目标但当前是传统会话，按当前传统会话上传
                  const resp = await fetch('/api/auth/upload-role-background', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ avatar: base64, session_id: currentSession.session_id })
                  });
                  if (!resp.ok) throw new Error(await resp.text());
                  await resp.json();
                  backgroundManuallySetAtRef.current = Date.now();
                  await setSafeBackgroundImage(`/api/auth/role-background/${encodeURIComponent(currentSession.session_id)}`);
                } else {
                  // 未选择任何会话的情况：仅本地预览
                  backgroundManuallySetAtRef.current = Date.now();
                  setBackgroundImageUrl(dataUrl);
                }
              } catch (e) {
                console.error(e);
                backgroundManuallySetAtRef.current = Date.now();
                setBackgroundImageUrl(dataUrl);
              } finally {
                // 上传完成后清理目标
                setBackgroundUploadTarget(null);
              }
            };
            reader.readAsDataURL(file);
          } catch (err) {
            message.error('背景图片设置失败');
          } finally {
            if (hiddenBgInputRef.current) {
              (hiddenBgInputRef.current as any).value = '';
            }
          }
        }}
      />

      {/* 新增：批量删除传统会话模态框 */}
      <Modal
        title="批量删除传统会话"
        open={traditionalBatchModalVisible}
        onCancel={() => { setTraditionalBatchModalVisible(false); setSelectedTraditionalSessionIds([]); }}
        footer={[
          <Button key="cancel" onClick={() => { setTraditionalBatchModalVisible(false); setSelectedTraditionalSessionIds([]); }}>
            取消
          </Button>,
          <Button
            key="toggleSelect"
            onClick={() => {
              const allIds = sessions.map(s => s.session_id);
              const allSelected = allIds.length > 0 && allIds.every(id => selectedTraditionalSessionIds.includes(id));
              setSelectedTraditionalSessionIds(allSelected ? [] : allIds);
            }}
          >
            {(() => {
              const allIds = sessions.map(s => s.session_id);
              const allSelected = allIds.length > 0 && allIds.every(id => selectedTraditionalSessionIds.includes(id));
              return allSelected ? '取消全选' : '全选';
            })()}
          </Button>,
          <Button key="delete" className={styles.deleteButton} type="primary" onClick={handleBatchDeleteTraditionalSessions} disabled={selectedTraditionalSessionIds.length === 0}>
            删除所选
          </Button>
        ]}
      >
        <div style={{ maxHeight: 300, overflow: 'auto' }}>
          {sessions.map(s => (
            <div key={s.session_id} style={{ display: 'flex', alignItems: 'center', padding: '6px 0' }}>
              <Checkbox
                checked={selectedTraditionalSessionIds.includes(s.session_id)}
                onChange={(e) => {
                  setSelectedTraditionalSessionIds(prev => e.target.checked ? [...prev, s.session_id] : prev.filter(id => id !== s.session_id));
                }}
              >
                {s.name || '新对话'}
              </Checkbox>
              <span style={{ marginLeft: 'auto', color: 'var(--text-tertiary)' }}>{(s.message_count || 0)} 条消息</span>
            </div>
          ))}
        </div>
      </Modal>

      {renderOverlay()}
      {/* 移动端菜单按钮：只在移动端且侧边栏折叠时显示 */}
      {isMobile && !siderVisible && (
        <Button
          className={styles.mobileMenuButton}
          icon={<MenuOutlined />}
          onClick={toggleMobileSider}
        />
      )}

      {/* 左侧边栏 */}
      <Sider 
        width={300} 
        collapsedWidth={0}
        collapsed={isMobile ? !siderVisible : desktopSiderCollapsed}
        className={`${styles.sider} ${isMobile ? (siderVisible ? styles.siderVisible : '') : ''}`}
        theme="light"
      >
        <div className={styles.siderContent}>
          <Button 
            type="default"
            className={styles.newSessionButton}
            onClick={handleCreateSession} 
            style={{ marginBottom: 16, width: '100%' }}
            loading={isLoading}
          >
            新建会话
          </Button>
          
          <Collapse defaultActiveKey={['sessions']}>

              {/* 会话管理面板 */}
              <Panel 
                header={
                  <div className={styles.panelHeader}>
                    <FileTextOutlined />
                    <span>角色列表</span>
                    <span 
                      style={{ 
                        marginLeft: '8px',
                        color: '#999',
                        fontSize: '14px',
                        fontWeight: 'normal'
                      }}
                    >
                      {sessions.length}
                    </span>
                  </div>
                }
                extra={
                  <div onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center' }}>
                    <Dropdown menu={getTraditionalHeaderMenu()} trigger={["click"]} placement="bottomRight">
                      <Button
                        type="text"
                        icon={<MoreOutlined />}
                        size="small"
                        className={`${styles.headerButton} ${styles.traditionalHeaderButton}`}
                        title="更多操作"
                      />
                    </Dropdown>
                  </div>
                }
                key="sessions"
              >
                <div className={styles.sessionList}>
                  <div style={{ marginBottom: 16 }}>
                    {sessions.map((session) => (
                      <div
                        key={session.session_id}
                        className={`${styles.sessionItem} ${currentSession?.session_id === session.session_id ? styles.activeSession : ''}`}
                        onClick={() => handleSessionChange(session)}
                      >
                        <img 
                          src={session.role_avatar_url ? convertMinioUrlToHttp(session.role_avatar_url) : defaultModelAvatar} 
                          alt="角色头像" 
                          style={{ 
                            width: '32px', 
                            height: '32px', 
                            borderRadius: '50%',
                            objectFit: 'cover',
                            marginRight: 8
                          }} 
                        />
                        <div className={styles.sessionInfo}>
                                                     <Tooltip title={session.name} placement="top" mouseEnterDelay={1.5}>
                            <span className={styles.sessionName}>{session.name}</span>
                          </Tooltip>
                          <span className={styles.messageCount}>
                            {session.message_count || 0} 条消息
                          </span>
                        </div>
                        <Dropdown 
                          menu={getSessionMenu(session)}
                          trigger={['click']}
                          placement="bottomRight"
                        >
                          <Button
                            type="text"
                            icon={<MoreOutlined />}
                            className={styles.sessionMenuButton}
                            onClick={(e) => {
                              e.stopPropagation();
                            }}
                          />
                        </Dropdown>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>
              
              {/* 群聊列表面板 */}
              <Panel 
                header={
                  <div className={styles.panelHeader}>
                    <TeamOutlined />
                    <span>群聊列表</span>
                    <span 
                      style={{ 
                        marginLeft: '8px',
                        color: '#999',
                        fontSize: '14px',
                        fontWeight: 'normal'
                      }}
                    >
                      {groups.length}
                    </span>
                  </div>
                }
                extra={
                  <div onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center' }} className={styles.groupPanelExtra}>
                    <Button
                      type="text"
                      icon={<PlusOutlined />}
                      size="small"
                      className={`${styles.headerButton}`}
                      title="创建群聊"
                      onClick={() => setCreateGroupModalVisible(true)}
                    />
                  </div>
                }
                key="groups"
              >
                <div className={styles.sessionList}>
                  {groups.length === 0 ? (
                    <div style={{ 
                      textAlign: 'center', 
                      padding: '20px', 
                      color: '#999',
                      fontSize: '14px'
                    }}>
                      <TeamOutlined style={{ fontSize: '32px', marginBottom: '8px', opacity: 0.3 }} />
                      <div>暂无群聊</div>
                      <Button 
                        type="link" 
                        size="small" 
                        onClick={() => setCreateGroupModalVisible(true)}
                        style={{ marginTop: '8px' }}
                      >
                        去创建群聊
                      </Button>
                    </div>
                  ) : (
                    <div style={{ marginBottom: 16 }}>
                      {groups.map((group) => (
                        <div
                          key={group.group_id}
                          className={`${styles.sessionItem} ${
                            currentSession?.session_type === 'group' && currentSession?.group_id === group.group_id 
                              ? styles.activeSession 
                              : ''
                          }`}
                          onClick={() => handleGroupSelect(group)}
                        >
                          <img 
                            src={group.avatar ? convertMinioUrlToHttp(group.avatar) : defaultModelAvatar} 
                            alt="群聊头像" 
                            style={{ 
                              width: '32px', 
                              height: '32px', 
                              borderRadius: '50%',
                              objectFit: 'cover',
                              marginRight: 8
                            }} 
                          />
                          <div className={styles.sessionInfo}>
                            <Tooltip title={group.name} placement="top" mouseEnterDelay={1.5}>
                              <span className={styles.sessionName}>{group.name}</span>
                            </Tooltip>
                            <span className={styles.messageCount}>
                              {group.members.length} 成员
                            </span>
                          </div>
                          <Dropdown 
                            menu={getGroupMenu(group)}
                            trigger={['click']}
                            placement="bottomRight"
                          >
                            <Button
                              type="text"
                              icon={<MoreOutlined />}
                              className={styles.sessionMenuButton}
                              onClick={(e) => {
                                e.stopPropagation();
                              }}
                            />
                          </Dropdown>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Panel>
            </Collapse>
        </div>
      </Sider>

      {/* 主内容区域 */}
      <Layout className={styles.mainLayout} style={{ position: 'relative' }}>
        {enableChatBackground && backgroundImageUrl && (
                     <div
             style={{
               position: 'absolute',
               inset: 0,
               backgroundImage: `url(${backgroundImageUrl})`,
               backgroundSize: 'cover',
               backgroundPosition: 'center',
              //  filter: 'blur(1px) saturate(1.05) brightness(0.95)',
               filter: 'saturate(1.05) brightness(0.95)',
               // 轻微粉色甜系蒙版
               mixBlendMode: 'normal',
               zIndex: 0,
               pointerEvents: 'none'
             }}
           >
            <div
              style={{
                position: 'absolute',
                inset: 0,
                background: 'rgba(255, 182, 193, 0)' // LightPink 透明蒙层
              }}
            />
          </div>
        )}
        {/* 添加电脑端折叠按钮 */}
        {!isMobile && (
          <Button
            type="text"
            icon={desktopSiderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={toggleDesktopSider}
            className={styles.desktopSiderToggle}
          />
        )}
        
        {/* 标题栏 */}
        <div 
          className={styles.header}
          style={{
            '--message-opacity': messageOpacity / 100
          } as React.CSSProperties}
        >
           <h1 className={styles.headerTitle}>
             {currentSession 
                 ? currentSession.name 
                 : '🐋Fish Eternal'
             }
           </h1>
           <div className={styles.headerActions}>
             <Button
               type="text"
               icon={<SettingOutlined />}
               onClick={() => setSettingsModalVisible(true)}
               title="设置"
             />
           </div>
         </div>

        {/* 对话区域容器：包含消息区域和右侧成员面板 */}
        <Layout style={{ background: 'transparent' }}>
          <div className={`${styles.chatContent} ${(enableChatBackground && backgroundImageUrl) ? styles.hasBg : ''}`} style={{ position: 'relative', zIndex: 1 }}>
            {/* 消息列表 */}
          <div 
            className={styles.messageList} 
            ref={messageListRef}
            style={{
              opacity: isMessagesVisible ? 1 : 0,
              transition: isMessagesVisible ? 'opacity 0.15s ease-in' : 'none'
            }}
          >
            {/* 懒加载提示 - 企业级优化版 */}
            {hasMore && (
              <div style={{ 
                textAlign: 'center', 
                padding: '12px 16px', 
                color: '#999',
                fontSize: '13px',
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}>
                {isLoadingMore ? (
                  <>
                    <span style={{ 
                      display: 'inline-block',
                      width: '14px',
                      height: '14px',
                      border: '2px solid #e0e0e0',
                      borderTopColor: '#1890ff',
                      borderRadius: '50%',
                      animation: 'spin 0.8s linear infinite'
                    }} />
                    <span>正在加载历史消息...</span>
                  </>
                ) : (
                  <span style={{ opacity: 0.7 }}>↑ 向上滚动加载更多历史消息</span>
                )}
              </div>
            )}
            
            {messages.map((msg: ChatMessage, index) => {
              // 在群聊模式和普通对话模式下显示时间分隔符
              const previousMsg = index > 0 ? messages[index - 1] : null;
              // 群聊模式 或 (非助手模式 且 个人对话模式)
              const isGroupChat = currentSession?.session_type === 'group';
              const isPersonalChat = currentSession?.session_type === 'personal';
              const shouldShowTime = isGroupChat || isPersonalChat;
              
              // 调试：打印消息的时间戳信息
              if (index === 0) {
                console.log('🔍 第一条消息时间戳调试:', {
                  isGroupChat,
                  isPersonalChat,
                  shouldShowTime,
                  sessionType: currentSession?.session_type,
                  currentSession,
                  msg,
                  timestamp: msg.timestamp,
                  hasTimestamp: !!msg.timestamp,
                  previousMsg
                });
              }
              
              const timestampInfo = shouldShowTime ? shouldShowTimestamp(msg, previousMsg) : null;
              
              return (
                <React.Fragment key={msg.id || (msg.timestamp ? `${msg.timestamp}-${msg.role}` : `idx-${index}-${msg.role}`)}>
                  {/* 时间分隔符 */}
                  {timestampInfo?.show && msg.timestamp && (
                    <div className={styles.timestampDivider}>
                      <span className={styles.timestampText}>
                        {formatTimestamp(msg.timestamp, timestampInfo.format)}
                      </span>
                    </div>
                  )}
                  
                  <div
                className={`${styles.messageContainer} ${
                  msg.role === 'user' ? styles.userMessageContainer : styles.assistantMessageContainer
                }`}
              >
                {/* 用户消息：优先渲染，不受isModelTyping状态影响 */}
                {msg.role === 'user' && (
                  <>
                    <div className={styles.messageAvatar}>
                      <img 
                        src={
                          // 群聊模式：根据 sender_id 从成员列表查找头像（与右侧 Sider 使用相同数据源）
                          // 非群聊模式：使用当前用户头像
                          (() => {
                            if (isGroupChat && (msg.sender_id || msg.sender_name)) {
                              const currentGroup = groups.find(g => g.group_id === currentGroupId);
                              
                              // 🔥 修复：优先用sender_name匹配，因为sender_id可能有问题
                              let sender = null;
                              if (msg.sender_name) {
                                // 先尝试用sender_name匹配（更可靠）
                                sender = currentGroup?.members.find(m => m.nickname === msg.sender_name);
                              }
                              if (!sender && msg.sender_id) {
                                // 如果sender_name匹配失败，再用sender_id匹配
                                sender = currentGroup?.members.find(m => m.member_id === msg.sender_id);
                              }
                              
                              if (sender) {
                                // 🔥 使用与右侧 Sider 完全相同的头像处理逻辑
                                const isCurrentUserMsg = sender.member_id === user?.id;
                                const avatarUrl = isCurrentUserMsg && user?.avatar_url 
                                  ? convertMinioUrlToHttp(user.avatar_url)
                                  : (sender.avatar ? convertMinioUrlToHttp(sender.avatar) : defaultAvatar);
                                
                                return avatarUrl;
                              }
                            }
                            // 默认使用当前用户头像
                            return (user?.avatar_url || userAvatar) ? convertMinioUrlToHttp(user?.avatar_url || userAvatar) : defaultAvatar;
                          })()
                        }
                        alt="用户头像" 
                        className={styles.avatarImage}
                        style={{ 
                          opacity: 1, // 确保头像立即显示
                          transition: 'opacity 0.1s ease-in-out' // 添加平滑过渡
                        }}
                      />
                    </div>
                    <div className={styles.messageWrapper}>
                      <div 
                        className={`${styles.message} ${styles.userMessage}`}
                        style={{
                          '--message-opacity': messageOpacity / 100
                        } as React.CSSProperties}
                      >
                        <div className={styles.messageContent}>
                          {/* 图片预览 */}
                          {msg.images && msg.images.length > 0 && (
                            <div className={styles.messageImagePreview}>
                              {msg.images.map((imageUrl: string, imgIndex: number) => {
                                // 在传统模式下将MinIO URL转换为HTTP API URL，在助手模式下直接使用URL
                                const httpImageUrl = convertMinioUrlToHttp(imageUrl);
                                return (
                                  <div 
                                    key={imgIndex} 
                                    className={styles.messageImageThumbnail}
                                    onClick={() => handleImageClick(httpImageUrl)}
                                  >
                                    <img src={httpImageUrl} alt={`图片 ${imgIndex + 1}`} />
                                  </div>
                                );
                              })}
                            </div>
                          )}
                          
                          <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                        </div>
                        <div className={styles.messageButtons}>
                          <Button 
                            className={styles.messageCopyButton}
                            icon={<CopyOutlined />}
                            onClick={(e) => copyToClipboard(msg.content, e)}
                            type="text"
                            size="small"
                          />
                          {/* 群聊模式下不显示编辑和删除按钮 */}
                          {currentSession?.session_type !== 'group' && (
                            <>
                              <Button 
                                className={styles.messageEditButton}
                                icon={<EditOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleEditMessage(index, msg.content, msg.images);
                                }}
                                type="text"
                                size="small"
                              />
                              <Button 
                                className={styles.messageDeleteButton}
                                icon={<DeleteOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteMessage(index, msg.content);
                                }}
                                type="text"
                                size="small"
                                danger
                              />
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </>
                )}

                {/* 助手消息：正常渲染 */}
                {msg.role === 'assistant' && (
                  <>
                    <div className={styles.messageAvatar}>
                      <img 
                        src={
                          currentSession?.session_type === 'group'
                            ? (() => {
                                // 🔥 修复：在群聊模式下，正确区分AI成员和用户消息
                                const currentGroup = groups.find(g => g.group_id === currentGroupId);
                                const sender = currentGroup?.members.find(m => m.member_id === msg.sender_id);
                                
                                if (sender?.member_type === 'ai') {
                                  // AI成员消息：使用AI头像
                                  console.log('🤖 AI消息头像调试:', {
                                    message_sender_id: msg.sender_id,
                                    message_role: msg.role,
                                    found_ai_member: sender,
                                    ai_member_avatar: sender?.avatar,
                                    all_ai_members: currentGroup?.members.filter(m => m.member_type === 'ai')
                                  });
                                  
                                  return sender?.avatar 
                                    ? convertMinioUrlToHttp(sender.avatar) 
                                    : defaultModelAvatar;
                                } else {
                                  // 用户消息：使用用户头像（与右侧Sider相同逻辑）
                                  console.log('👤 用户消息头像调试:', {
                                    message_sender_id: msg.sender_id,
                                    message_sender_name: msg.sender_name,
                                    found_user_member: sender,
                                    user_member_avatar: sender?.avatar
                                  });
                                  
                                  if (sender?.avatar) {
                                    return convertMinioUrlToHttp(sender.avatar);
                                  }
                                  
                                  // 备用逻辑：通过sender_name查找
                                  if (msg.sender_name) {
                                    const memberByName = currentGroup?.members.find(m => 
                                      m.nickname === msg.sender_name && m.member_type === 'user'
                                    );
                                    if (memberByName?.avatar) {
                                      return convertMinioUrlToHttp(memberByName.avatar);
                                    }
                                  }
                                  
                                  return defaultAvatar;
                                }
                              })()
                            : (currentSession?.role_avatar_url 
                                  ? convertMinioUrlToHttp(currentSession.role_avatar_url)
                                  : defaultModelAvatar)
                        } 
                        alt="模型头像" 
                        className={styles.avatarImage}
                      />
                    </div>
                    <div className={styles.messageWrapper}>
                      {/* 群聊模式下显示AI昵称 */}
                      {currentSession?.session_type === 'group' && (msg as any).sender_name && (
                        <div style={{ 
                          fontSize: '12px', 
                          color: theme === 'dark' ? 'rgba(255, 255, 255, 0.65)' : 'rgba(0, 0, 0, 0.65)', 
                          marginBottom: '0px',
                          paddingLeft: '8px'
                        }}>
                          {(msg as any).sender_name}
                        </div>
                      )}
                      <div 
                        className={`${styles.message} ${styles.assistantMessage}`}
                        style={{
                          '--message-opacity': messageOpacity / 100
                        } as React.CSSProperties}
                      >
                        <div className={styles.messageContent}>
                          {/* 图片预览 */}
                          {msg.images && msg.images.length > 0 && (
                            <div className={styles.messageImagePreview}>
                              {msg.images.map((imageUrl: string, imgIndex: number) => {
                                // 在传统模式下将MinIO URL转换为HTTP API URL，在助手模式下直接使用URL
                                const httpImageUrl = convertMinioUrlToHttp(imageUrl);
                                return (
                                  <div 
                                    key={imgIndex} 
                                    className={styles.messageImageThumbnail}
                                    onClick={() => handleImageClick(httpImageUrl)}
                                  >
                                    <img src={httpImageUrl} alt={`图片 ${imgIndex + 1}`} loading="lazy" />
                                  </div>
                                );
                              })}
                            </div>
                          )}
                          
                          {/* 消息内容 */}
                          {renderMessageContent(msg.content, index, msg.timestamp, msg.reference)}
                          
                          {/* 🆕 知识图谱可视化入口 */}
                          {msg.graph_metadata && msg.graph_metadata.length > 0 && (
                            <GraphMetadataCollapsible graphMetadata={msg.graph_metadata} />
                          )}
                          
                          {/* 文档引用列表 */}
                          {msg.reference && msg.reference.length > 0 && (
                            <DocumentReferencesCollapsible references={msg.reference} />
                          )}
                        </div>
                        <div className={styles.messageButtons}>
                          <Button 
                            className={styles.messageCopyButton}
                            icon={<CopyOutlined />}
                            onClick={(e) => copyToClipboard(msg.content, e)}
                            type="text"
                            size="small"
                          />
                          {/* 群聊模式下不显示编辑和删除按钮 */}
                          {currentSession?.session_type !== 'group' && (
                            <>
                              <Button 
                                className={styles.messageEditButton}
                                icon={<EditOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleEditMessage(index, msg.content, msg.images);
                                }}
                                type="text"
                                size="small"
                              />
                              <Button 
                                className={styles.messageDeleteButton}
                                icon={<DeleteOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteMessage(index, msg.content);
                                }}
                                type="text"
                                size="small"
                                danger
                              />
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
                </React.Fragment>
              );
            })}
            
            {/* 模型输入指示器 */}
            {isModelTyping && (
              <div className={`${styles.messageContainer} ${styles.assistantMessageContainer}`}>
                <div className={styles.messageAvatar}>
                  <img 
                    src={
                      (currentSession?.role_avatar_url 
                            ? convertMinioUrlToHttp(currentSession.role_avatar_url)
                            : defaultModelAvatar)
                    } 
                    alt="模型头像" 
                    className={styles.avatarImage}
                  />
                </div>
                <div className={styles.messageWrapper}>
              <div 
                className={`${styles.message} ${styles.assistantMessage} ${styles.typingIndicator}`}
                style={{
                  '--message-opacity': messageOpacity / 100
                } as React.CSSProperties}
              >
                <div className={styles.messageContent}>
                  <div className={styles.typingAnimation}>
                    <span className={styles.typingDot}></span>
                    <span className={styles.typingDot}></span>
                    <span className={styles.typingDot}></span>
                  </div>
                  <span className={styles.typingText}>{typingText}</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} style={{ height: '1px' }} />
          </div>

          {/* 输入区域 */}
          <div className={styles.inputArea}>
            {/* 图片预览 */}
            {imagePreviews.length > 0 && (
              <div className={styles.imagePreviewWrapper}>
                <div 
                  className={styles.imagePreviewContainer}
                  onWheel={handleImagePreviewWheel}
                >
                  {imagePreviews.map((preview, index) => (
                    <div key={index} className={styles.imagePreview}>
                      <img 
                        src={preview} 
                        alt={`预览 ${index + 1}`}
                        onClick={() => handleImageClick(preview, true)}
                        style={{ cursor: 'pointer' }}
                        title="点击查看大图"
                      />
                      <button
                        className={styles.imageRemoveButton}
                        onClick={() => handleImageRemove(index)}
                        title="删除图片"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
                <button
                  className={styles.imageRemoveAllButton}
                  onClick={handleImageRemoveAll}
                  title="删除所有图片"
                >
                  删除全部
                </button>
              </div>
            )}
            
            <div 
              className={styles.inputContainer}
              onClick={handleInputContainerClick}
              style={{ 
                position: 'relative',
                '--message-opacity': messageOpacity / 100
              } as React.CSSProperties}
            >
              {/* VAD 状态指示器 */}
              <VADStatus 
                status={vadStatus} 
                visible={isRecording || isTranscribing}
                onCancel={handleCancelRecording}
                currentVolume={currentVolume}
                recordingDuration={recordingDuration}
              />
              
              {/* @ 成员/知识库选择菜单 */}
              {mentionMenuVisible && (() => {
                // 🆕 构建菜单项列表
                const menuItems: Array<{
                  type: 'member' | 'knowledgebase';
                  id: string;
                  nickname: string;
                  avatar?: string;
                  member_id?: string;
                  member_type?: string;
                  is_current_user?: boolean;
                }> = [];
                
                // 🆕 添加"知识库"选项（始终显示在第一位）
                if ('知识库'.toLowerCase().includes(mentionSearchText.toLowerCase())) {
                  menuItems.push({
                    type: 'knowledgebase',
                    id: 'knowledgebase',
                    nickname: '知识库',
                  });
                }
                
                // 添加群成员选项（仅在群聊中）
                if (currentGroupId) {
                  const members = groups
                    .find(g => g.group_id === currentGroupId)
                    ?.members.filter(member => 
                      member.nickname.toLowerCase().includes(mentionSearchText.toLowerCase())
                    ) || [];
                  
                  members.forEach(member => {
                    const isCurrentUser = member.member_id === user?.id;
                    const avatarUrl = isCurrentUser && user?.avatar_url 
                      ? convertMinioUrlToHttp(user.avatar_url)
                      : (member.avatar ? convertMinioUrlToHttp(member.avatar) : defaultAvatar);
                    
                    menuItems.push({
                      type: 'member',
                      id: member.member_id,
                      nickname: member.nickname,
                      avatar: avatarUrl,
                      member_id: member.member_id,
                      member_type: member.member_type,
                      is_current_user: isCurrentUser,
                    });
                  });
                }
                
                // 如果没有匹配项，不显示菜单
                if (menuItems.length === 0) return null;
                
                return (
                  <div
                    data-mention-menu="true"
                    style={{
                      position: 'absolute',
                      bottom: '100%',
                      left: 0,
                      right: 0,
                      marginBottom: '8px',
                      maxHeight: '200px',
                      overflowY: 'auto',
                      background: theme === 'dark' ? '#1f1f1f' : '#ffffff',
                      border: `1px solid ${theme === 'dark' ? '#434343' : '#d9d9d9'}`,
                      borderRadius: '8px',
                      boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
                      zIndex: 1000,
                      // 隐藏滚动条，但保持滚动功能
                      scrollbarWidth: 'none', // Firefox
                      msOverflowStyle: 'none', // IE and Edge
                    } as React.CSSProperties & { scrollbarWidth?: string; msOverflowStyle?: string }}
                    className="mention-menu-scrollbar-hidden"
                  >
                    {menuItems.map((item, index) => {
                      const isSelected = index === mentionSelectedIndex;
                      
                      // 🆕 知识库选项
                      if (item.type === 'knowledgebase') {
                        // 检查当前会话是否启用了知识库
                        const kbEnabled = !!(currentSession as any)?.kb_settings?.enabled;
                        
                        return (
                          <div
                            key={item.id}
                            data-mention-item={index}
                            onClick={() => {
                              if (kbEnabled) {
                                handleSelectMention('知识库');
                              } else {
                                message.warning('当前会话未启用知识库，请先在会话配置中启用');
                              }
                            }}
                            onMouseEnter={() => setMentionSelectedIndex(index)}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              padding: '8px 12px',
                              cursor: kbEnabled ? 'pointer' : 'not-allowed',
                              background: isSelected 
                                ? (theme === 'dark' ? '#2a2a2a' : '#f5f5f5')
                                : (theme === 'dark' ? '#1f1f1f' : '#ffffff'),
                              transition: 'background 0.2s',
                              gap: '8px',
                              opacity: kbEnabled ? 1 : 0.5,
                            }}
                          >
                            <div style={{
                              width: '32px',
                              height: '32px',
                              borderRadius: '50%',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              background: theme === 'dark' ? '#1890ff' : '#e6f7ff',
                              color: '#1890ff',
                            }}>
                              <DatabaseOutlined style={{ fontSize: '18px' }} />
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ 
                                display: 'flex', 
                                alignItems: 'center',
                                gap: '6px',
                              }}>
                                <span style={{ 
                                  fontWeight: 500,
                                  fontSize: '14px',
                                  color: theme === 'dark' ? '#ffffff' : '#000000',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}>
                                  知识库
                                </span>
                                <Tag color={kbEnabled ? "cyan" : "default"} style={{ margin: 0, fontSize: '11px', padding: '0 4px', lineHeight: '16px' }}>
                                  {kbEnabled ? 'KB' : '未启用'}
                                </Tag>
                              </div>
                            </div>
                          </div>
                        );
                      }
                      
                      // 成员选项
                      return (
                        <div
                          key={item.id}
                          data-mention-item={index}
                          onClick={() => handleSelectMention(item.nickname)}
                          onMouseEnter={() => setMentionSelectedIndex(index)}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            padding: '8px 12px',
                            cursor: 'pointer',
                            background: isSelected 
                              ? (theme === 'dark' ? '#2a2a2a' : '#f5f5f5')
                              : (theme === 'dark' ? '#1f1f1f' : '#ffffff'),
                            transition: 'background 0.2s',
                            gap: '8px',
                          }}
                        >
                          <img
                            src={item.avatar || defaultAvatar}
                            alt={item.nickname}
                            style={{
                              width: '32px',
                              height: '32px',
                              borderRadius: '50%',
                              objectFit: 'cover',
                            }}
                          />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ 
                              display: 'flex', 
                              alignItems: 'center',
                              gap: '6px',
                            }}>
                              <span style={{ 
                                fontWeight: 500,
                                fontSize: '14px',
                                color: theme === 'dark' ? '#ffffff' : '#000000',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}>
                                {item.nickname}
                              </span>
                              {item.member_type === 'ai' && (
                                <Tag color="blue" style={{ margin: 0, fontSize: '11px', padding: '0 4px', lineHeight: '16px' }}>
                                  AI
                                </Tag>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
              
              {/* 引用文档列表 */}
              {referencedDocs.length > 0 && (
                <div className={styles.referencedDocsContainer}>
                  {referencedDocs.map((doc, index) => (
                    <span key={`${doc.docId}-${index}`} className={styles.referencedDocItem}>
                      @{doc.filename}
                      <CloseOutlined 
                        className={styles.referencedDocClose}
                        onClick={() => {
                          setReferencedDocs(referencedDocs.filter((_, i) => i !== index));
                        }}
                      />
                    </span>
                  ))}
                </div>
              )}

              <Input.TextArea
                ref={inputRef}
                value={currentMessage}
                onChange={handleMessageChange}
                onPaste={handlePaste}
                placeholder="输入消息..."
                autoSize={{ minRows: isDesktop ? 2 : 1, maxRows: 8 }}
                onPressEnter={(e) => {
                  // 如果@菜单打开，回车选择当前高亮的项
                  if (mentionMenuVisible && !e.shiftKey) {
                    e.preventDefault();
                    
                    // 🆕 构建菜单项列表（与渲染逻辑一致）
                    const menuItems: Array<{ nickname: string }> = [];
                    
                    if ('知识库'.toLowerCase().includes(mentionSearchText.toLowerCase())) {
                      menuItems.push({ nickname: '知识库' });
                    }
                    
                    if (currentGroupId) {
                      const members = groups
                        .find(g => g.group_id === currentGroupId)
                        ?.members.filter(member => 
                          member.nickname.toLowerCase().includes(mentionSearchText.toLowerCase())
                        ) || [];
                      members.forEach(member => {
                        menuItems.push({ nickname: member.nickname });
                      });
                    }
                    
                    if (menuItems.length > 0 && mentionSelectedIndex < menuItems.length) {
                      handleSelectMention(menuItems[mentionSelectedIndex].nickname);
                    }
                  } else if (!e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
                onKeyDown={(e) => {
                  // @菜单键盘导航
                  if (mentionMenuVisible) {
                    // 🆕 构建菜单项列表（与渲染逻辑一致）
                    let menuItemsCount = 0;
                    
                    if ('知识库'.toLowerCase().includes(mentionSearchText.toLowerCase())) {
                      menuItemsCount++;
                    }
                    
                    if (currentGroupId) {
                      const members = groups
                        .find(g => g.group_id === currentGroupId)
                        ?.members.filter(member => 
                          member.nickname.toLowerCase().includes(mentionSearchText.toLowerCase())
                        ) || [];
                      menuItemsCount += members.length;
                    }
                    
                    if (e.key === 'ArrowDown') {
                      e.preventDefault();
                      setMentionSelectedIndex(prev => 
                        prev < menuItemsCount - 1 ? prev + 1 : 0
                      );
                    } else if (e.key === 'ArrowUp') {
                      e.preventDefault();
                      setMentionSelectedIndex(prev => 
                        prev > 0 ? prev - 1 : menuItemsCount - 1
                      );
                    } else if (e.key === 'Escape') {
                      e.preventDefault();
                      setMentionMenuVisible(false);
                      setMentionSelectCount(0); // 重置选择计数
                    }
                  }
                }}
              />
              
              <div className={styles.inputButtons}>
                {/* 图片上传按钮 - 仅对支持图片的模型显示 */}
                {currentSessionSupportsImage && (
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    onChange={handleImageSelect}
                    style={{ display: 'none' }}
                    id="image-upload"
                  />
                )}
                

                
                {currentSessionSupportsImage && (
                  <Button
                    type="text"
                    icon={<PictureOutlined />}
                    onClick={() => document.getElementById('image-upload')?.click()}
                    title="上传图片"
                    loading={isImageUploading}
                  />
                )}
                
                {/* 语音输入按钮（智能 VAD） */}
                  <Button
                    type="text"
                    icon={<AudioOutlined />}
                    onClick={handleVoiceInputClick}
                    loading={isTranscribing}
                    style={{
                      color: isRecording ? '#ff4d4f' : undefined,
                    }}
                    className={isRecording ? 'recording-button' : ''}
                  />
                {sent_flag ? (
                  <Button 
                    type="primary" 
                    icon={<SendOutlined />}
                    onClick={() => sendMessage()}
                    loading={isProcessing}
                  >
                    发送
                  </Button>
                ) : (
                  <Dropdown 
                    menu={toolsMenu} 
                    trigger={['click']}
                    placement="topRight"
                  >
                    <Button 
                      type="primary" 
                      icon={<AppstoreOutlined />}
                    >
                      功能
                    </Button>
                  </Dropdown>
                )}
              </div>
            </div>
          </div>
          </div>
          
          {/* 群成员面板（仅群聊时显示，响应式隐藏） */}
          {currentSession?.session_type === 'group' && currentGroupId && showGroupMemberPanel && (
            <Sider 
              width={280} 
              theme="light"
              style={{
                background: 'rgba(0, 0, 0, 0)',
                // borderLeft: theme === 'dark' 
                //   ? '1px solid rgba(255, 255, 255, 0.06)' 
                //   : '1px solid rgba(0, 0, 0, 0.06)',
                overflow: 'auto',
                flexShrink: 0  // 防止被挤压
              }}
            >
              <div style={{ padding: '16px' }}>
                <div style={{ 
                  fontSize: '16px', 
                  fontWeight: 600, 
                  marginBottom: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  color: theme === 'dark' ? '#ffffff' : '#000000'
                }}>
                  <span>
                    <TeamOutlined style={{ marginRight: '8px' }} />
                    群成员 ({groups.find(g => g.group_id === currentGroupId)?.members.length || 0})
                  </span>
                </div>
                
                {/* 成员列表 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {groups.find(g => g.group_id === currentGroupId)?.members.map((member) => {
                    const isCurrentUser = member.member_id === user?.id;
                    const avatarUrl = isCurrentUser && user?.avatar_url 
                      ? convertMinioUrlToHttp(user.avatar_url)
                      : (member.avatar ? convertMinioUrlToHttp(member.avatar) : defaultAvatar);
                    
                    console.log('🔍 右侧Sider头像调试:', {
                      member_id: member.member_id,
                      member_name: member.nickname,
                      member_avatar: member.avatar,
                      member_type: member.member_type,
                      isCurrentUser,
                      final_avatarUrl: avatarUrl
                    });
                    
                    // 🔥 对比：检查这个成员是否能在消息头像逻辑中被找到
                    const testMessage = { sender_id: member.member_id };
                    const foundInMessageLogic = groups.find(g => g.group_id === currentGroupId)?.members.find(m => m.member_id === testMessage.sender_id);
                    console.log('🔍 消息头像逻辑测试:', {
                      member_id: member.member_id,
                      can_be_found_in_message_logic: !!foundInMessageLogic,
                      found_member: foundInMessageLogic
                    });
                    
                    return (
                    <div
                      key={member.member_id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        padding: '12px',
                        background: token.colorFillQuaternary,
                        borderRadius: '8px',
                        gap: '12px'
                      }}
                    >
                      <img
                        src={avatarUrl}
                        alt={member.nickname}
                        style={{
                          width: '40px',
                          height: '40px',
                          borderRadius: '50%',
                          objectFit: 'cover'
                        }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ 
                          display: 'flex', 
                          alignItems: 'center',
                          gap: '6px',
                          marginBottom: '4px'
                        }}>
                          <span style={{ 
                            fontWeight: 500,
                            fontSize: '14px',
                            color: theme === 'dark' ? '#ffffff' : '#000000',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'
                          }}>
                            {member.nickname}
                          </span>
                          {member.member_type === 'ai' && (
                            <Tag color="blue" style={{ margin: 0, fontSize: '11px', padding: '0 4px', lineHeight: '16px' }}>
                              AI
                            </Tag>
                          )}
                          {member.role === 'owner' && (
                            <Tag color="gold" style={{ margin: 0, fontSize: '11px', padding: '0 4px', lineHeight: '16px' }}>
                              群主
                            </Tag>
                          )}
                          {member.role === 'admin' && (
                            <Tag color="blue" style={{ margin: 0, fontSize: '11px', padding: '0 4px', lineHeight: '16px' }}>
                              管理员
                            </Tag>
                          )}
                        </div>
                        <div style={{ 
                          fontSize: '12px', 
                          color: theme === 'dark' ? '#ffffff' : '#000000',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}>
                          <span 
                            style={{ 
                              display: 'inline-block',
                              width: '6px',
                              height: '6px',
                              borderRadius: '50%',
                              background: member.status === 'online' 
                                ? '#52c41a' 
                                : member.status === 'busy'
                                  ? '#faad14'
                                  : '#d9d9d9'
                            }}
                          />
                          {member.status === 'online' ? '在线' : member.status === 'busy' ? '忙碌' : '离线'}
                        </div>
                      </div>
                    </div>
                    );
                  })}
                </div>
              </div>
            </Sider>
          )}
        </Layout>
      </Layout>

      {/* 设置模态框：承载原左侧四个面板 */}
      <Modal
        title="设置"
        open={settingsModalVisible}
        onCancel={() => setSettingsModalVisible(false)}
        footer={null}
        width={720}
        destroyOnHidden
      >
        <Collapse defaultActiveKey={[]}>
          {/* 用户信息面板 */}
          <div className={styles.userInfo}>
            <div 
              className={styles.userAvatarSection}
              onClick={handleUserAvatarClick}
              style={{ cursor: 'pointer' }}
            >
              <img 
                src={(user?.avatar_url || userAvatar) ? convertMinioUrlToHttp(user?.avatar_url || userAvatar) : defaultAvatar} 
                alt="用户头像" 
                className={styles.userAvatar}
              />
              <span className={styles.userName}>
                {user?.full_name || user?.account || '未登录'}
              </span>
            </div>
          </div>

          {/* 系统设置面板 */}
          <div className={styles.systemSettingsPanel}>
            {/* 主题切换 */}
            <div className={styles.settingGroup}>
              <div className={styles.settingGroupTitle}>
                <BgColorsOutlined />
                <span>外观设置</span>
              </div>
              <div className={styles.settingCard}>
                <ThemeToggle />
              </div>
              <div className={styles.settingCard}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <PictureOutlined className={styles.settingIcon} />
                    <span>会话背景</span>
                  </div>
                  <Switch
                    checked={enableChatBackground}
                    onChange={setEnableChatBackground}
                  />
                </div>
              </div>
              <div className={styles.settingCard}>
                <div className={styles.settingRow} style={{ flexDirection: 'column', alignItems: 'stretch', gap: '12px' }}>
                  <div className={styles.settingInfo} style={{ marginBottom: '4px' }}>
                    <CompressOutlined className={styles.settingIcon} />
                    <div className={styles.settingContent}>
                      <div className={styles.settingTitle}>消息透明度</div>
                      <div className={styles.settingDesc}>调整消息气泡和输入框的背景透明度</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <Slider
                      min={0}
                      max={100}
                      value={messageOpacity}
                      onChange={(value) => setMessageOpacity(value)}
                      style={{ flex: 1 }}
                      tooltip={{ formatter: (value) => `${value}%` }}
                    />
                    <span style={{ minWidth: '45px', textAlign: 'right', fontSize: '14px', color: 'var(--text-secondary)' }}>
                      {messageOpacity}%
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* 功能设置 */}
            <div className={styles.settingGroup}>
              <div className={styles.settingGroupTitle}>
                <SettingOutlined />
                <span>功能设置</span>
              </div>
              <div className={styles.settingCard}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <ApiOutlined className={styles.settingIcon} />
                    <div className={styles.settingContent}>
                      <div className={styles.settingTitle}>模型配置</div>
                      <div className={styles.settingDesc}>配置可用模型</div>
                    </div>
                  </div>
                  <Button 
                    type="primary" 
                    size="small"
                    icon={<SettingOutlined />}
                    onClick={() => navigate('/model-config')}
                  >
                    配置
                  </Button>
                </div>
              </div>
              {/* 独立知识库管理 */}
              <div className={styles.settingCard}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <ThunderboltOutlined className={styles.settingIcon} style={{ color: '#1890ff' }} />
                    <div className={styles.settingContent}>
                      <div className={styles.settingTitle}>独立知识库</div>
                      <div className={styles.settingDesc}>本地RAG引擎 · 高性能</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                  <Button 
                      type="default" 
                      size="small"
                      icon={<GlobalOutlined />}
                      onClick={() => navigate('/kb-marketplace')}
                    >
                      广场
                    </Button>
                    <Button 
                      type="primary" 
                      size="small"
                      icon={<DatabaseOutlined />}
                      onClick={() => navigate('/knowledge-base')}
                    >
                      管理
                    </Button>
                  </div>
                </div>
              </div>
              {/* 工具配置 */}
              <div className={styles.settingCard}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <AppstoreOutlined className={styles.settingIcon} />
                    <div className={styles.settingContent}>
                      <div className={styles.settingTitle}>MCP工具配置</div>
                      <div className={styles.settingDesc}>管理AI可用的工具</div>
                    </div>
                  </div>
                  <Button 
                    type="default" 
                    size="small"
                    icon={<SettingOutlined />}
                    onClick={() => setToolConfigModalVisible(true)}
                  >
                    配置
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* 语音设置 */}
          <div className={styles.systemSettingsPanel}>
            <div className={styles.settingGroup}>
              <div className={styles.settingGroupTitle}>
                <AudioOutlined />
                <span>语音设置</span>
              </div>
              
              <div className={styles.settingCard}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <SoundOutlined className={styles.settingIcon} />
                    <div className={styles.settingContent}>
                      <div className={styles.settingTitle}>语音播放</div>
                      <div className={styles.settingDesc}>开启后自动播放AI回复</div>
                    </div>
                  </div>
                  <Switch 
                    checked={enableVoice}
                    onChange={async (checked) => {
                      if (checked) {
                        // 检查是否有默认TTS配置
                        try {
                          const response = await authAxios.get('/api/tts-config/default');
                          const defaultProvider = response.data?.provider_id;
                          
                          if (!defaultProvider) {
                            Modal.warning({
                              title: '未配置默认TTS服务',
                              content: '您还没有配置默认的TTS服务。请先前往"模型配置"页面设置默认TTS服务后再使用语音播放功能。',
                              okText: '去配置',
                              cancelText: '取消',
                              maskClosable: true,
                              onOk: () => {
                                navigate('/model-config');
                              }
                            });
                            return;
                          }
                          
                          // 检查默认TTS是否有配置
                          const configResponse = await authAxios.get('/api/tts-config/user');
                          const configs = configResponse.data?.configs || {};
                          
                          if (!configs[defaultProvider] || !configs[defaultProvider].enabled) {
                            Modal.warning({
                              title: 'TTS服务未完整配置',
                              content: '您选择的默认TTS服务配置不完整或未启用。请前往"模型配置"页面完善配置。',
                              okText: '去配置',
                              cancelText: '取消',
                              maskClosable: true,
                              onOk: () => {
                                navigate('/model-config');
                              }
                            });
                            return;
                          }
                          
                          // 配置完整，可以开启语音播放
                          setEnableVoice(true);
                          message.success('语音播放已开启');
                        } catch (error) {
                          console.error('[TTS] 检查默认TTS配置失败:', error);
                          Modal.error({
                            title: '检查TTS配置失败',
                            content: '无法检查TTS配置，请稍后重试或前往"模型配置"页面检查配置。',
                            maskClosable: true
                          });
                        }
                      } else {
                        setEnableVoice(false);
                      }
                    }}
                  />
                </div>
              </div>

              <div className={styles.settingCard}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <EditOutlined className={styles.settingIcon} />
                    <div className={styles.settingContent}>
                      <div className={styles.settingTitle}>
                        文本清洗
                        <Tooltip title="清洗掉括号内容、特殊标记等，但保留引号内容">
                          <QuestionCircleOutlined style={{ marginLeft: 4, fontSize: 12, color: '#999' }} />
                        </Tooltip>
                      </div>
                      <div className={styles.settingDesc}>配置播放前的文本清洗规则</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Button 
                      size="small" 
                      icon={<SettingOutlined />}
                      onClick={() => setCleaningPatternsModalVisible(true)}
                    >
                      配置规则
                    </Button>
                    <Switch 
                      checked={enableTextCleaning}
                      onChange={setEnableTextCleaning}
                    />
                  </div>
                </div>
              </div>

            </div>
          </div>
        </Collapse>
      </Modal>

      {/* System Prompt设置模态框 */}
      {renderSystemPromptModal()}

      {/* 文本清洗配置模态框 */}
      {renderCleaningPatternsModal()}

      {/* 角色信息模态框 */}
      <Modal
        title="角色信息设置"
        open={roleInfoModalVisible}
        onCancel={() => {
          setRoleInfoModalVisible(false);
          setNewSessionName('');
          setEditingSession(null);
          setRoleAvatar('');
        }}
        footer={[
          <Button key="cancel" onClick={() => {
            setRoleInfoModalVisible(false);
            setNewSessionName('');
            setEditingSession(null);
            setRoleAvatar('');
          }}>
            取消
          </Button>,
          <Button 
            key="save" 
            type="primary" 
            onClick={handleRoleInfoSave}
            loading={isUploadingRoleAvatar}
          >
            保存
          </Button>
        ]}
        width={500}
        centered
        destroyOnHidden
      >
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <div style={{ marginBottom: '20px' }}>
            <Upload
              name="roleAvatar"
              listType="picture-card"
              className="avatar-uploader"
              showUploadList={false}
              beforeUpload={handleRoleAvatarUpload}
              accept="image/*"
            >
              <img 
                src={roleAvatar ? convertMinioUrlToHttp(roleAvatar) : defaultModelAvatar} 
                alt="角色头像" 
                style={{ 
                  width: '100px', 
                  height: '100px', 
                  borderRadius: '50%', 
                  objectFit: 'cover', 
                  cursor: 'pointer'
                }} 
              />
            </Upload>
          </div>
          <div style={{ marginBottom: '20px' }}>
        <Input
          value={newSessionName}
          onChange={(e) => setNewSessionName(e.target.value)}
              placeholder="请输入会话名称"
              style={{ marginTop: 16 }}
        />
          </div>
          <div style={{ textAlign: 'center', marginBottom: '12px' }}>
            <Button
              icon={<PictureOutlined />}
              onClick={() => hiddenBgInputRef.current?.click()}
            >
              修改背景图片
            </Button>
          </div>
          <p style={{ color: '#666', fontSize: '14px' }}>
            点击头像上传，支持 JPG、PNG 格式，文件大小不超过 5MB
          </p>
        </div>
      </Modal>
      {renderConfigModal()} {/* 添加配置修改模态框 */}
      {renderTtsProviderModal()} {/* TTS服务商选择模态框 */}
      {renderTtsConfigModal()} {/* TTS配置模态框 */}

      {/* 知识库配置模态框 */}
      <Modal
        title="配置知识库"
        open={kbConfigModalVisible}
        onOk={handleSaveKbConfig}
        onCancel={() => { 
          setKbConfigModalVisible(false); 
          setKbEditingSession(null); 
          setKbConfigActiveTab('knowledge'); // 关闭时重置标签页
        }}
        okText="保存"
        cancelText="取消"
        width={800}
        destroyOnHidden
      >
        <Tabs 
          activeKey={kbConfigActiveTab} 
          onChange={(key) => setKbConfigActiveTab(key)}
          items={[
            {
              key: 'knowledge',
              label: '知识库配置',
              children: (
                <div className={styles.configForm}>
                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      启用知识库
                    </div>
                    <Switch
                      checked={!!kbConfig.enabled}
                      onChange={(v) => setKbConfig((prev: any) => ({ ...prev, enabled: v }))}
                    />
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>知识库提示词（使用 {`{knowledge}`} 占位符）</div>
                    <Input.TextArea
                      value={kbConfig.kb_prompt_template}
                      onChange={(e) => setKbConfig((prev: any) => ({ ...prev, kb_prompt_template: e.target.value }))}
                      rows={6}
                      placeholder={`在此编写完整提示词，包含 {knowledge} 以插入检索内容。\n首次默认填入当前会话的原始提示词，您可以在合适位置加入 {knowledge}。`}
                    />
                  </div>

                  {/* 🆕 知识库选择器（支持单选或多选）*/}
                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      选择知识库
                      <Tooltip title="可选择1个或多个知识库。选择多个时会并行检索并合并结果。">
                        <QuestionCircleOutlined style={{ marginLeft: 4, color: token.colorTextSecondary }} />
                      </Tooltip>
                    </div>
                    <Select
                      mode="multiple"
                      value={kbConfig.kb_ids || []}
                      onChange={(values) => setKbConfig((prev: any) => ({ ...prev, kb_ids: values }))}
                      placeholder="请选择知识库（可多选）"
                      style={{ width: '100%' }}
                      loading={kbListLoading}
                      maxTagCount="responsive"
                      showSearch
                      filterOption={(input, option) =>
                        (option?.label?.toString() ?? '').toLowerCase().includes(input.toLowerCase())
                      }
                      optionLabelProp="label"
                    >
                      {availableKnowledgeBases.map(kb => (
                        <Option 
                          key={kb.id} 
                          value={kb.id}
                          label={kb.name}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>{kb.name}</span>
                            <Tag color="blue" style={{ marginLeft: 8, fontSize: '11px' }}>
                              {kb.document_count || 0} 文档
                            </Tag>
                          </div>
                        </Option>
                      ))}
                    </Select>
                    <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                      {(kbConfig.kb_ids || []).length === 0 && '未选择知识库'}
                      {(kbConfig.kb_ids || []).length === 1 && '已选择 1 个知识库（单库检索）'}
                      {(kbConfig.kb_ids || []).length > 1 && `已选择 ${(kbConfig.kb_ids || []).length} 个知识库（多库并行检索）`}
                    </div>
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      返回分片数量
                      <Tooltip title="设置知识库检索时返回的最大分片数量。数量越多，提供的上下文越丰富，但也会增加 token 消耗。建议值：3-6。">
                        <QuestionCircleOutlined style={{ marginLeft: 4, color: token.colorTextSecondary }} />
                      </Tooltip>
                    </div>
                    <InputNumber 
                      min={1} 
                      max={12} 
                      step={1} 
                      style={{ width: '100%' }} 
                      value={kbConfig.top_k ?? 3} 
                      onChange={(v) => setKbConfig((prev: any) => ({ ...prev, top_k: v }))}
                      placeholder="3"
                    />
                    <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                      当前值：{kbConfig.top_k ?? 3} 个分片（范围：1-12）
                    </div>
                  </div>
                </div>
              )
            },
            {
              key: 'memory',
              label: '角色记忆',
              children: (
                <div className={styles.configForm}>
                  <div style={{ marginBottom: 8 }}>
                    {!!kbEditingSession && (kbEditingSession as any).kb_parsed ? (
                      <Tag color="green">已解析：{(kbEditingSession as any).kb_settings?.collection_name || '已解析'}</Tag>
                    ) : (
                      <Tag color="default">未解析</Tag>
                    )}
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      启用知识库
                    </div>
                    <Switch
                      checked={!!kbConfig.enabled}
                      onChange={(v) => setKbConfig((prev: any) => ({ ...prev, enabled: v }))}
                    />
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>选择向量数据库</div>
                    <Select
                      value={kbConfig.vector_db}
                      onChange={(v) => setKbConfig((prev: any) => ({ ...prev, vector_db: v }))}
                      style={{ width: '100%' }}
                      optionLabelProp="label"
                    >
                      <Option 
                        value="chroma"
                        label={
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <img 
                              src={chromaLogo} 
                              alt="ChromaDB" 
                              style={{ width: '16px', height: '16px', objectFit: 'contain' }}
                            />
                            <span>ChromaDB</span>
                          </div>
                        }
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <img 
                            src={chromaLogo} 
                            alt="ChromaDB" 
                            style={{ width: '16px', height: '16px', objectFit: 'contain' }}
                          />
                          <span>ChromaDB</span>
                        </div>
                      </Option>
                    </Select>
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>知识库名称</div>
                    <Input
                      value={kbConfig.collection_name}
                      onChange={(e) => setKbConfig((prev: any) => ({ ...prev, collection_name: e.target.value }))}
                      placeholder="请输入知识库名称（collection）"
                    />
                  </div>

                  {/* 多知识库高级配置 */}
                  {(kbConfig.kb_ids || []).length > 1 && (
                    <>
                      <div className={styles.formItem}>
                        <div className={styles.formLabel}>
                          每库返回结果数
                          <Tooltip title="每个知识库返回的最大结果数。例如选择3个库,每库返回3条,最多可获得9条结果(去重后可能更少)。">
                            <QuestionCircleOutlined style={{ marginLeft: 4, color: token.colorTextSecondary }} />
                          </Tooltip>
                        </div>
                        <InputNumber 
                          min={1} 
                          max={10} 
                          step={1} 
                          style={{ width: '100%' }} 
                          value={kbConfig.top_k_per_kb ?? 3} 
                          onChange={(v) => setKbConfig((prev: any) => ({ ...prev, top_k_per_kb: v }))}
                        />
                        <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                          当前值：每个知识库返回 {kbConfig.top_k_per_kb ?? 3} 条结果
                        </div>
                      </div>

                      <div className={styles.formItem}>
                        <div className={styles.formLabel}>
                          最终返回总数
                          <Tooltip title="合并所有知识库结果后,最终返回的结果总数。">
                            <QuestionCircleOutlined style={{ marginLeft: 4, color: token.colorTextSecondary }} />
                          </Tooltip>
                        </div>
                        <InputNumber 
                          min={1} 
                          max={50} 
                          step={1} 
                          style={{ width: '100%' }} 
                          value={kbConfig.final_top_k ?? 10} 
                          onChange={(v) => setKbConfig((prev: any) => ({ ...prev, final_top_k: v }))}
                        />
                        <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                          当前值：最终返回 {kbConfig.final_top_k ?? 10} 条结果
                        </div>
                      </div>

                      <div className={styles.formItem}>
                        <div className={styles.formLabel}>
                          结果合并策略
                          <Tooltip title="加权分数:按相似度得分排序(推荐) | 简单拼接:按知识库顺序拼接 | 交错:轮流取各库结果">
                            <QuestionCircleOutlined style={{ marginLeft: 4, color: token.colorTextSecondary }} />
                          </Tooltip>
                        </div>
                        <Select
                          value={kbConfig.merge_strategy || 'weighted_score'}
                          onChange={(v) => setKbConfig((prev: any) => ({ ...prev, merge_strategy: v }))}
                          style={{ width: '100%' }}
                        >
                          <Option value="weighted_score">
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <ThunderboltOutlined style={{ color: '#1890ff' }} />
                              <span>加权分数排序</span>
                              <Tag color="blue" style={{ fontSize: '10px', marginLeft: 'auto' }}>推荐</Tag>
                            </div>
                          </Option>
                          <Option value="simple_concat">
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <AppstoreOutlined />
                              <span>简单拼接</span>
                            </div>
                          </Option>
                          <Option value="interleave">
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <SwapOutlined />
                              <span>交错合并</span>
                            </div>
                          </Option>
                        </Select>
                      </div>
                    </>
                  )}

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      <DatabaseOutlined /> 嵌入模型服务商
                    </div>
                    <Select
                      value={kbConfig.embeddings?.provider}
                      optionLabelProp="label"
                      onClick={() => {
                        // 点击时检查是否有可用的服务商
                        if (enabledEmbeddingProviders.length === 0) {
                          message.warning('请先在模型配置页面配置并启用至少一个嵌入模型服务商');
                        }
                      }}
                      onChange={(value) => {
                        // 从已启用的嵌入服务商列表中获取配置
                        const provider = enabledEmbeddingProviders.find(p => p.id === value);
                        
                        if (!provider) {
                          message.warning('请先在模型配置页面配置并启用该嵌入服务商');
                          return;
                        }
                        
                        // 更新配置，使用服务商的默认模型和已配置的信息
                        setKbConfig((prev: any) => ({
                          ...prev,
                          embeddings: {
                            provider: value,
                            model: provider.defaultModel,
                            base_url: provider.baseUrl,
                            api_key: provider.apiKey
                          }
                        }));
                      }}
                      style={{ width: '100%' }}
                    >
                      {enabledEmbeddingProviders.length === 0 ? (
                        <Option disabled value="" label="暂无已启用的嵌入模型">
                          <span style={{ color: 'var(--text-secondary)' }}>
                            暂无已启用的嵌入模型，请先在模型配置页面配置
                          </span>
                        </Option>
                      ) : (
                        enabledEmbeddingProviders.map(provider => {
                          const embeddingService = EMBEDDING_SERVICES.find(s => s.value === provider.id);
                          return (
                            <Option 
                              key={provider.id} 
                              value={provider.id}
                              label={
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  {embeddingService && (
                                    <img 
                                      src={embeddingService.logo} 
                                      alt={provider.name} 
                                      style={{ width: '16px', height: '16px', objectFit: 'contain' }}
                                    />
                                  )}
                                  <span>{provider.name}</span>
                                </div>
                              }
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                {embeddingService && (
                                  <img 
                                    src={embeddingService.logo} 
                                    alt={provider.name} 
                                    style={{ width: '20px', height: '20px', objectFit: 'contain' }}
                                  />
                                )}
                                <span>{provider.name}</span>
                                {provider.id === defaultEmbeddingProviderId && (
                                  <Tag color="blue" style={{ fontSize: '11px', padding: '0 4px' }}>默认</Tag>
                                )}
                              </div>
                            </Option>
                          );
                        })
                      )}
                    </Select>
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      <GlobalOutlined /> 嵌入模型
                    </div>
                    <Select 
                      value={kbConfig.embeddings?.model}
                      onClick={() => {
                        // 点击时检查是否选择了服务商
                        if (!kbConfig.embeddings?.provider) {
                          message.warning('请先选择嵌入模型服务商');
                          return;
                        }
                        // 检查是否有可用的模型
                        const provider = enabledEmbeddingProviders.find(p => p.id === kbConfig.embeddings?.provider);
                        if (!provider || provider.models.length === 0) {
                          message.warning('当前服务商没有可用的模型，请先在模型配置页面配置');
                        }
                      }}
                      onChange={(value) => {
                        setKbConfig((prev: any) => ({
                          ...prev,
                          embeddings: {
                            ...prev.embeddings,
                            model: value
                          }
                        }));
                      }}
                      style={{ width: '100%' }}
                    >
                      {(() => {
                        const provider = enabledEmbeddingProviders.find(p => p.id === kbConfig.embeddings?.provider);
                        if (!provider) return null;
                        
                        return provider.models.map(modelValue => (
                          <Option key={modelValue} value={modelValue}>
                            {modelValue}
                          </Option>
                        ));
                      })()}
                    </Select>
                  </div>

                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>
                      相似度阈值
                      <Tooltip title="设置检索结果的最大距离阈值。ChromaDB默认使用L2距离，值越小表示越相似。只有距离小于此阈值的文档才会被返回。建议值：5-15。设为0则不过滤。如果检索不到结果，请在后端日志查看实际距离分数并调整此值。">
                        <QuestionCircleOutlined style={{ marginLeft: 4, color: token.colorTextSecondary }} />
                      </Tooltip>
                    </div>
                    <InputNumber 
                      min={0} 
                      max={50} 
                      step={0.5} 
                      style={{ width: '100%' }} 
                      value={kbConfig.similarity_threshold ?? 10} 
                      onChange={(v) => setKbConfig((prev: any) => ({ ...prev, similarity_threshold: v }))}
                      placeholder="0.8"
                    />
                    <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                      当前值：{kbConfig.similarity_threshold ?? 10}（L2距离，0=完全相同，越大越不相似。0表示不过滤）
                    </div>
                  </div>

                  <Collapse ghost>
                    <Panel header="分片设置（可选）" key="split-params">
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                        <div className={styles.formItem}>
                          <div className={styles.formLabel}>chunk_size</div>
                          <InputNumber min={100} max={4000} step={50} style={{ width: '100%' }} value={kbConfig.split_params?.chunk_size} onChange={(v) => setKbConfig((prev: any) => ({ ...prev, split_params: { ...prev.split_params, chunk_size: v } }))} />
                        </div>
                        <div className={styles.formItem}>
                          <div className={styles.formLabel}>chunk_overlap</div>
                          <InputNumber min={0} max={2000} step={10} style={{ width: '100%' }} value={kbConfig.split_params?.chunk_overlap} onChange={(v) => setKbConfig((prev: any) => ({ ...prev, split_params: { ...prev.split_params, chunk_overlap: v } }))} />
                        </div>
                        <div className={styles.formItem} style={{ gridColumn: '1 / span 2' }}>
                          <div className={styles.formLabel}>分隔符（逗号分隔）</div>
                          <Input
                            value={(kbConfig.split_params?.separators || []).join(',')}
                            onChange={(e) => setKbConfig((prev: any) => ({ ...prev, split_params: { ...prev.split_params, separators: e.target.value.split(',').map(s => s) } }))}
                            placeholder="例如：\n\n,\n,。,！,？,，, ,"
                          />
                        </div>
                      </div>
                    </Panel>
                  </Collapse>

                  {/* 文件上传与解析 */}
                  <div className={styles.formItem}>
                    <div className={styles.formLabel}>文档文件</div>
                    <div>
                      <input type="file" style={{ display: 'none' }} ref={kbFileInputRef} onChange={handleKbFileChange} />
                      <Button onClick={() => kbFileInputRef.current?.click()}>选择文件</Button>
                      <span style={{ marginLeft: 8 }}>{kbSelectedFile?.name}</span>
                      <Button type="primary" style={{ marginLeft: 12 }} loading={kbParsing} onClick={handleKbParseFile}>解析并入库</Button>
                    </div>
                  </div>
                </div>
              )
            }
          ]}
        />
      </Modal>
      
      {/* 用户头像模态框 */}
      <Modal
        title="用户账号设置"
        open={userAvatarModalVisible}
        onCancel={handleUserAvatarModalClose}
        footer={[
          <Button key="cancel" onClick={handleUserAvatarModalClose}>
            取消
          </Button>,
          <Button key="logout" danger onClick={handleLogout}>
            退出登录
          </Button>,
          <Button key="delete-account" danger type="primary" onClick={handleDeleteAccount} loading={deletingAccount}>
            注销账号
          </Button>,
          <Button 
            key="save" 
            type="primary" 
            onClick={handleAvatarSave}
            loading={isSavingProfile || isUploadingAvatar}
          >
            保存
          </Button>
        ]}
        width={600}
        centered
        destroyOnHidden
      >
        <div style={{ padding: '20px 0' }}>
          {/* 头像部分 */}
          <div style={{ textAlign: 'center', marginBottom: '30px', paddingBottom: '30px', borderBottom: '1px solid #f0f0f0' }}>
            <div style={{ marginBottom: '15px' }}>
              <Upload
                name="avatar"
                listType="picture-card"
                className="avatar-uploader"
                showUploadList={false}
                beforeUpload={handleAvatarUpload}
                accept="image/*"
              >
                <img 
                  src={(user?.avatar_url || userAvatar) ? convertMinioUrlToHttp(user?.avatar_url || userAvatar) : defaultAvatar} 
                  alt="当前头像" 
                  style={{ 
                    width: '100px', 
                    height: '100px', 
                    borderRadius: '50%', 
                    objectFit: 'cover', 
                    cursor: 'pointer'
                  }} 
                />
              </Upload>
            </div>
            <p style={{ color: '#666', fontSize: '14px', margin: 0 }}>
              点击头像上传，支持 JPG、PNG 格式，文件大小不超过 5MB
            </p>
          </div>

          {/* 个性化信息表单 */}
          <div style={{ maxWidth: '450px', margin: '0 auto' }}>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500, color: '#333' }}>
                昵称
              </label>
              <Input
                placeholder="请输入您的名称"
                value={userFullName}
                onChange={(e) => setUserFullName(e.target.value)}
                maxLength={50}
                showCount
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500, color: '#333' }}>
                性别
              </label>
              <Select
                placeholder="请选择性别"
                value={userGender || undefined}
                onChange={(value) => setUserGender(value || '')}
                style={{ width: '100%' }}
                allowClear
              >
                <Select.Option value="男">男</Select.Option>
                <Select.Option value="女">女</Select.Option>
                <Select.Option value="保密">保密</Select.Option>
              </Select>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500, color: '#333' }}>
                出生日期 {user?.age !== undefined && user.age !== null && (
                  <span style={{ fontSize: '12px', color: '#999', fontWeight: 'normal' }}>
                    （年龄：{user.age}岁）
                  </span>
                )}
              </label>
              <DatePicker
                placeholder="请选择出生日期"
                value={userBirthDate ? dayjs(userBirthDate) : null}
                onChange={(date) => setUserBirthDate(date ? date.format('YYYY-MM-DD') : '')}
                style={{ width: '100%' }}
                format="YYYY-MM-DD"
                disabledDate={(current) => {
                  // 不能选择未来的日期
                  return current && current > dayjs().endOf('day');
                }}
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500, color: '#333' }}>
                个性签名
              </label>
              <Input.TextArea
                placeholder="写下你的个性签名吧..."
                value={userSignature}
                onChange={(e) => setUserSignature(e.target.value)}
                maxLength={200}
                showCount
                rows={4}
                style={{ resize: 'none' }}
              />
            </div>
          </div>
        </div>
      </Modal>
      
      {/* 注销账号确认与逻辑 */}
      
      {/* 增强的图片预览模态框 */}
      <Modal
        open={imageModalVisible}
        onCancel={handleImageModalClose}
        footer={null}
        width="80%"
        centered
        destroyOnHidden
        closable={false}
        styles={{
          body: { padding: 0 },
          content: { 
            padding: 0, 
            background: 'rgba(0, 0, 0, 0.95)',
            border: 'none',
            borderRadius: 8,
            overflow: 'hidden'
          }
        }}
      >
        <div className={styles.enhancedImageModal}>
          {/* 顶部工具栏 */}
          <div className={styles.imageModalToolbar}>
            <div className={styles.imageModalTitle}>
              <span className={styles.buttonTextDesktop}>
                图片预览 {imageScale !== initialFitScale && `(${Math.round((imageScale / initialFitScale) * 100)}%)`}
              </span>
              <span className={styles.buttonTextMobile}>
                预览 {imageScale !== initialFitScale && `${Math.round((imageScale / initialFitScale) * 100)}%`}
              </span>
            </div>
            <div className={styles.imageModalControls}>
              <Button 
                type="text" 
                icon={<ZoomOutOutlined />} 
                onClick={handleImageZoomOut}
                className={styles.imageModalButton}
                title="缩小"
              />
              <Button 
                type="text" 
                icon={<ZoomInOutlined />} 
                onClick={handleImageZoomIn}
                className={styles.imageModalButton}
                title="放大"
              />
              <Button 
                type="text" 
                onClick={handleImageFitToWindow}
                className={styles.imageModalButton}
                title="适合窗口"
              >
                <span className={styles.buttonTextDesktop}>适配</span>
                <span className={styles.buttonTextMobile}>适配</span>
              </Button>
              {isViewingPendingImage && (
                <Button 
                  type="text" 
                  icon={<CompressOutlined />} 
                  onClick={handleImageCompress}
                  className={styles.imageModalButton}
                  title="压缩图片"
                >
                  <span className={styles.buttonTextDesktop}>压缩</span>
                  <span className={styles.buttonTextMobile}>压缩</span>
                </Button>
              )}
              <Button 
                type="text" 
                icon={<DownloadOutlined />} 
                onClick={handleImageDownload}
                className={styles.imageModalButton}
                title="下载图片"
              />
              <Button 
                type="text" 
                icon={<CloseOutlined />} 
                onClick={handleImageModalClose}
                className={styles.imageModalButton}
                title="关闭"
              />
            </div>
          </div>

          {/* 图片容器 */}
          <div 
            className={styles.imageModalContainer}
            onMouseMove={handleImageMouseMove}
            onMouseUp={handleImageMouseUp}
            onMouseLeave={handleImageMouseUp}
            onWheel={handleImageWheel}
          >
                      <img 
              src={selectedImage} 
              alt="预览图片" 
              className={styles.imageModalImage}
              style={{
                transform: `scale(${imageScale}) translate(${imagePosition.x}px, ${imagePosition.y}px)`,
                cursor: imageScale > initialFitScale ? (isDragging ? 'grabbing' : 'grab') : 'default',
                visibility: imageNaturalSize.width > 0 ? 'visible' : 'hidden'
              }}
              onMouseDown={handleImageMouseDown}
              onLoad={handleImageLoad}
              onError={(e) => {
                console.error('图片加载失败:', e);
                message.error('图片加载失败');
              }}
              draggable={false}
            />
          </div>

          {/* 底部提示 */}
          <div className={styles.imageModalHint}>
            <span>鼠标滚轮缩放 • 拖拽移动 • ESC键关闭</span>
          </div>
        </div>
      </Modal>

      {/* 删除消息确认对话框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
            <span>删除消息</span>
          </div>
        }
        open={deleteMessageModalVisible}
        onOk={confirmDeleteMessage}
        onCancel={() => {
          setDeleteMessageModalVisible(false);
          setMessageToDelete(null);
        }}
        okText="确定删除"
        cancelText="取消"
        okButtonProps={{ className: styles.deleteButton }}
      >
        <p>确定要删除这条消息吗？</p>
        {messageToDelete && (
          <div className={styles.modalPreviewArea}>
            <p className={styles.modalPreviewText}>
              {messageToDelete.content.length > 100 
                ? `${messageToDelete.content.substring(0, 100)}...` 
                : messageToDelete.content
              }
            </p>
          </div>
        )}
        <p className={styles.modalWarningText}>
          删除后无法恢复，请谨慎操作。
        </p>
      </Modal>

      {/* 修改消息对话框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <EditOutlined style={{ color: '#1890ff' }} />
            <span>修改消息</span>
          </div>
        }
        open={editMessageModalVisible}
        onOk={confirmEditMessage}
        onCancel={() => {
          setEditMessageModalVisible(false);
          setMessageToEdit(null);
          setEditedContent('');
          setEditedImages([]);
        }}
        okText="确定修改"
        cancelText="取消"
        width={isMobile ? '95vw' : 800}
        styles={{
          body: {
          maxHeight: isMobile ? '70vh' : '80vh',
          overflowY: 'auto',
          padding: isMobile ? '16px 12px' : '24px'
          }
        }}
        footer={[
          <Button
            key="cancel"
            onClick={() => {
              setEditMessageModalVisible(false);
              setMessageToEdit(null);
              setEditedContent('');
              setEditedImages([]);
            }}
          >
            取消
          </Button>,
          (messageToEdit && messages[messageToEdit.index] && messages[messageToEdit.index].role === 'user') ? (
            <Button key="resend" type="dashed" danger onClick={handleResendFromMessage}>
              重新发送
            </Button>
          ) : null,
          <Button key="ok" type="primary" onClick={confirmEditMessage}>
            确定修改
          </Button>
        ]}
      >
        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold' }}>
            消息内容：
          </label>
          <Input.TextArea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            placeholder="请输入消息内容..."
            autoSize={{
              minRows: isMobile ? 4 : 6,
              maxRows: isMobile ? 15 : 20
            }}
            maxLength={10000}
            showCount
            style={{
              fontSize: isMobile ? '16px' : '14px',
              lineHeight: '1.6',
              borderRadius: '8px',
              resize: 'none'
            }}
          />
        </div>

        {editedImages.length > 0 && (
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold' }}>
              消息图片：
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {editedImages.map((imageUrl, index) => {
                const httpImageUrl = convertMinioUrlToHttp(imageUrl);
                return (
                  <div
                    key={index}
                    style={{
                      position: 'relative',
                      width: '80px',
                      height: '80px',
                      border: '1px solid #d9d9d9',
                      borderRadius: '6px',
                      overflow: 'hidden'
                    }}
                  >
                    <img
                      src={httpImageUrl}
                      alt={`图片 ${index + 1}`}
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover'
                      }}
                    />
                    <Button
                      type="text"
                      danger
                      size="small"
                      icon={<CloseOutlined />}
                      onClick={() => handleRemoveImageFromEdit(imageUrl)}
                      style={{
                        position: 'absolute',
                        top: '2px',
                        right: '2px',
                        width: '20px',
                        height: '20px',
                        padding: '0',
                        backgroundColor: 'rgba(0, 0, 0, 0.5)',
                        color: 'white',
                        border: 'none'
                      }}
                    />
                  </div>
                );
              })}
            </div>
            <p style={{ color: '#666', fontSize: '12px', marginTop: '8px' }}>
              点击图片右上角的 × 可以删除图片
            </p>
          </div>
        )}
      </Modal>

      {/* 导出对话数据确认对话框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FileTextOutlined style={{ color: '#1890ff' }} />
            <span>导出对话数据</span>
          </div>
        }
        open={exportChatModalVisible}
        onOk={confirmExportChat}
        onCancel={() => {
          setExportChatModalVisible(false);
          setExportingSession(null);
          setExportFileName('');
          setExportFormat('txt');
          setExportIncludeTimestamps(true);
          setExportIncludeSystemPrompts(true);
        }}
        okText="确定导出"
        cancelText="取消"
        okButtonProps={{ type: 'primary' }}
      >
        <p>确定要导出这个会话的对话数据吗？</p>
        {exportingSession && (
          <div className={styles.modalPreviewArea}>
            <p className={styles.modalPreviewText}>
              会话名称: {exportingSession.name}
            </p>
            <p className={styles.modalPreviewText}>
              消息数量: {exportingSession.message_count || 0}
            </p>
          </div>
        )}
        <div style={{ marginTop: '15px' }}>
          <p style={{ marginBottom: '8px', fontSize: '14px' }}>文件名:</p>
          <Input
            value={exportFileName}
            onChange={(e) => setExportFileName(e.target.value)}
            placeholder="请输入文件名（不包含扩展名）"
            style={{ width: '100%' }}
          />
        </div>
        <div style={{ marginTop: '15px' }}>
          <p style={{ marginBottom: '8px', fontSize: '14px' }}>导出格式:</p>
          <Select
            value={exportFormat}
            onChange={(v) => setExportFormat(v as 'txt' | 'json')}
            style={{ width: '100%' }}
            options={[
              { label: '纯文本（.txt）', value: 'txt' },
              { label: '结构化 JSON（.json）', value: 'json' }
            ]}
          />
        </div>
        {exportFormat === 'json' && (
          <div style={{ marginTop: '15px' }}>
            <Checkbox
              checked={exportIncludeTimestamps}
              onChange={(e) => setExportIncludeTimestamps(e.target.checked)}
              style={{ display: 'block', marginBottom: '8px' }}
            >
              包含对话时间字段（将转换为您的本地时区）
            </Checkbox>
            <Checkbox
              checked={exportIncludeSystemPrompts}
              onChange={(e) => setExportIncludeSystemPrompts(e.target.checked)}
              style={{ display: 'block' }}
            >
              包含系统提示词（原始 SYSTEM_PROMPT 与当前知识库提示词）
            </Checkbox>
          </div>
        )}
        <p style={{ color: '#999', fontSize: '12px', marginTop: '10px' }}>
          导出的文件将包含完整的对话历史记录。
        </p>
      </Modal>

      {/* 用户头像裁剪组件 */}
      <AvatarCropper
        visible={userAvatarCropperVisible}
        imageUrl={tempAvatarUrl}
        onCancel={handleUserAvatarCropCancel}
        onConfirm={handleUserAvatarCropConfirm}
      />

      {/* 角色头像裁剪组件 */}
      <AvatarCropper
        visible={roleAvatarCropperVisible}
        imageUrl={tempAvatarUrl}
        onCancel={handleRoleAvatarCropCancel}
        onConfirm={handleRoleAvatarCropConfirm}
      />

      {/* 图片压缩组件 */}
      <ImageCompressor
        visible={compressorModalVisible}
        images={selectedImages}
        imagePreviews={imagePreviews}
        onCancel={handleCompressorCancel}
        onConfirm={handleCompressorConfirm}
      />

      {/* 工具配置模态框 */}
      <ToolConfigPanel 
        visible={toolConfigModalVisible}
        onClose={() => setToolConfigModalVisible(false)}
      />

      {/* 创建群组模态框 */}
      <CreateGroupModalInline
        visible={createGroupModalVisible}
        onClose={() => setCreateGroupModalVisible(false)}
        onSuccess={() => {
          setCreateGroupModalVisible(false);
          fetchGroups();
        }}
      />

      {/* 管理群组模态框 */}
      {managingGroup && (
        <ManageGroupModalInline
          visible={manageGroupModalVisible}
          group={managingGroup}
          onClose={() => {
            setManageGroupModalVisible(false);
            setManagingGroup(null);
          }}
          onSuccess={() => {
            setManageGroupModalVisible(false);
            setManagingGroup(null);
            fetchGroups();
          }}
        />
      )}


    </Layout>
  );
};

// 内联创建群组模态框组件
const CreateGroupModalInline: React.FC<{
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ visible, onClose, onSuccess }) => {
  const [form] = Form.useForm();
  const createGroup = useGroupChatStore((state) => state.createGroup);
  const selectGroup = useGroupChatStore((state) => state.selectGroup);
  const [loading, setLoading] = useState(false);
  
  // 获取会话列表
  const sessions = useChatStore((state) => state.sessions) || [];
  const fetchSessions = useChatStore((state) => state.fetchSessions);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  
  // 加载会话列表
  useEffect(() => {
    if (visible && sessions.length === 0) {
      setSessionsLoading(true);
      fetchSessions().finally(() => setSessionsLoading(false));
    }
  }, [visible, sessions.length, fetchSessions]);
  
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      
      // 将选中的会话ID作为AI成员添加到群组
      const sessionIds = values.memberIds || [];
      
      const groupId = await createGroup(
        values.name,
        values.description,
        sessionIds
      );
      
      message.success('创建群组成功！');
      form.resetFields();
      onSuccess();
      
      // 创建成功后自动选中该群组
      if (groupId) {
        selectGroup(groupId);
      }
    } catch (error: any) {
      if (error.errorFields) {
        // 表单验证错误
        return;
      }
      message.error(error.message || '创建群组失败');
    } finally {
      setLoading(false);
    }
  };
  
  const handleCancel = () => {
    form.resetFields();
    onClose();
  };
  
  return (
    <Modal
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <UsergroupAddOutlined />
          <span>创建群组</span>
        </div>
      }
      open={visible}
      onCancel={handleCancel}
      footer={[
        <Button key="cancel" onClick={handleCancel}>
          取消
        </Button>,
        <Button key="submit" type="primary" loading={loading} onClick={handleSubmit}>
          创建
        </Button>
      ]}
      width={500}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 20 }}
      >
        <Form.Item
          label="群组名称"
          name="name"
          rules={[
            { required: true, message: '请输入群组名称' },
            { min: 2, max: 50, message: '群组名称长度为 2-50 个字符' }
          ]}
        >
          <Input placeholder="例如：技术交流群" maxLength={50} />
        </Form.Item>
        
        <Form.Item
          label="群组简介"
          name="description"
          rules={[
            { max: 200, message: '群组简介不能超过 200 个字符' }
          ]}
        >
          <Input.TextArea 
            placeholder="介绍一下这个群组吧..." 
            rows={3}
            maxLength={200}
            showCount
          />
        </Form.Item>
        
        <Form.Item
          label="邀请AI成员（可选）"
          name="memberIds"
          extra="选择您的AI会话加入群聊，创建后也可在群组管理中添加"
        >
          <Select
            mode="multiple"
            placeholder={sessionsLoading ? "加载会话列表中..." : "选择要加入的AI会话"}
            style={{ width: '100%' }}
            optionFilterProp="children"
            loading={sessionsLoading}
            notFoundContent={sessionsLoading ? <Spin size="small" /> : "暂无AI会话"}
            maxTagCount="responsive"
          >
            {sessions.map(session => {
              const avatarUrl = session.role_avatar_url 
                ? convertMinioUrlToHttp(session.role_avatar_url)
                : undefined;
              
              return (
                <Select.Option key={session.session_id} value={session.session_id}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Avatar 
                      size="small" 
                      src={avatarUrl}
                      icon={!avatarUrl && <RobotOutlined />}
                    />
                    <span>{session.name}</span>
                  </div>
                </Select.Option>
              );
            })}
          </Select>
        </Form.Item>
      </Form>
    </Modal>
  );
};

// 内联管理群组模态框组件
const ManageGroupModalInline: React.FC<{
  visible: boolean;
  group: Group;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ visible, group: initialGroup, onClose, onSuccess }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('info');
  
  // 从 store 中实时获取最新的群组数据
  const groups = useGroupChatStore((state) => state.groups);
  const group = groups.find(g => g.group_id === initialGroup.group_id) || initialGroup;
  
  // 打印调试信息，检查成员列表是否更新
  useEffect(() => {
    console.log('🔍 群组成员列表:', group.members?.map(m => ({ id: m.member_id, type: m.member_type })));
  }, [group.members]);
  
  const updateGroup = useGroupChatStore((state) => state.updateGroup);
  const deleteGroup = useGroupChatStore((state) => state.deleteGroup);
  const addMember = useGroupChatStore((state) => state.addMember);
  const removeMember = useGroupChatStore((state) => state.removeMember);
  const setMemberAdmin = useGroupChatStore((state) => state.setMemberAdmin);
  const removeMemberAdmin = useGroupChatStore((state) => state.removeMemberAdmin);
  const aiGoOnline = useGroupChatStore((state) => state.aiGoOnline);
  const aiGoOffline = useGroupChatStore((state) => state.aiGoOffline);
  const batchAiGoOnline = useGroupChatStore((state) => state.batchAiGoOnline);
  const batchAiGoOffline = useGroupChatStore((state) => state.batchAiGoOffline);
  const { user } = useAuthStore(); // 获取当前用户信息
  
  // 判断当前用户是否是群主
  const isOwner = group.members?.some(m => m.member_id === user?.id && m.role === 'owner') || false;
  
  // 添加成员表单状态
  const [memberType, setMemberType] = useState<'user' | 'ai'>('ai');
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([]); // 改为数组支持多选
  const [memberId, setMemberId] = useState(''); // 用于添加用户
  const [memberNickname, setMemberNickname] = useState('');
  
  // 头像上传状态
  const [avatarFile, setAvatarFile] = useState<string>('');
  const [cropperVisible, setCropperVisible] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  
  // 策略配置对话框状态
  const [strategyConfigVisible, setStrategyConfigVisible] = useState(false);
  
  // 群聊系统提示词状态
  const [groupSystemPrompt, setGroupSystemPrompt] = useState<string>('');
  const [loadingSystemPrompt, setLoadingSystemPrompt] = useState(false);
  const [savingSystemPrompt, setSavingSystemPrompt] = useState(false);
  
  // 获取会话列表（用于AI成员选择）
  const sessions = useChatStore((state) => state.sessions) || [];
  const fetchSessions = useChatStore((state) => state.fetchSessions);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  
  // 加载会话列表
  useEffect(() => {
    if (visible && sessions.length === 0) {
      setSessionsLoading(true);
      fetchSessions().finally(() => setSessionsLoading(false));
    }
  }, [visible, sessions.length, fetchSessions]);
  
  // 加载群聊系统提示词
  useEffect(() => {
    if (visible && activeTab === 'advanced') {
      loadSystemPrompt();
    }
  }, [visible, activeTab, group.group_id]);
  
  // 过滤已入群的AI会话
  // 注意：后端存储的AI成员ID格式为 "ai_{session_id}"，需要匹配
  const availableSessions = sessions.filter(session => {
    const isAlreadyMember = (group.members || []).some(
      member => member.member_id === `ai_${session.session_id}` || member.member_id === session.session_id
    );
    return !isAlreadyMember;
  });
  
  // 打印可用会话列表
  useEffect(() => {
    console.log('🔍 可用AI会话数量:', availableSessions.length, '/', sessions.length);
    console.log('🔍 群组成员ID列表:', group.members?.map(m => m.member_id));
  }, [availableSessions.length, sessions.length, group.members]);
  
  // 加载群聊系统提示词
  const loadSystemPrompt = async () => {
    try {
      setLoadingSystemPrompt(true);
      const response = await api.get(
        `/api/group-chat/groups/${group.group_id}/system-prompt`
      );
      setGroupSystemPrompt(response.data.system_prompt || '');
    } catch (error: any) {
      console.error('加载群聊系统提示词失败:', error);
      message.error('加载系统提示词失败');
    } finally {
      setLoadingSystemPrompt(false);
    }
  };
  
  // 保存群聊系统提示词
  const handleSaveSystemPrompt = async () => {
    try {
      setSavingSystemPrompt(true);
      await api.put(
        `/api/group-chat/groups/${group.group_id}/system-prompt`,
        { system_prompt: groupSystemPrompt }
      );
      message.success('系统提示词更新成功！');
    } catch (error: any) {
      console.error('保存群聊系统提示词失败:', error);
      message.error(error.response?.data?.detail || '保存失败');
    } finally {
      setSavingSystemPrompt(false);
    }
  };
  
  // 更新群组信息
  const handleUpdateInfo = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      
      await updateGroup(group.group_id, {
        name: values.name,
        description: values.description
      });
      
      message.success('更新成功！');
      onSuccess();
    } catch (error: any) {
      if (error.errorFields) return;
      message.error(error.message || '更新失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 添加成员（支持批量添加AI）
  const handleAddMember = async () => {
    // AI成员：检查是否选择了会话
    if (memberType === 'ai') {
      if (selectedSessionIds.length === 0) {
        message.warning('请至少选择一个AI会话');
        return;
      }
      
      // 批量添加AI成员
      try {
        setLoading(true);
        let successCount = 0;
        let failedCount = 0;
        
        for (const sessionId of selectedSessionIds) {
          try {
            await addMember(group.group_id, 'ai', sessionId, memberNickname.trim() || undefined);
            successCount++;
          } catch (error) {
            console.error(`添加会话 ${sessionId} 失败:`, error);
            failedCount++;
          }
        }
        
        if (successCount > 0) {
          message.success(`成功添加 ${successCount} 个AI成员${failedCount > 0 ? `，${failedCount} 个失败` : ''}！`);
          // 清空选择，避免重复添加
          setSelectedSessionIds([]);
          setMemberNickname('');
          // 不关闭模态框，只刷新数据 - 这会触发 group 更新和 availableSessions 重新计算
          await useGroupChatStore.getState().fetchGroups();
        } else {
          message.error('添加AI成员全部失败');
        }
      } catch (error: any) {
        message.error(error.message || '添加成员失败');
      } finally {
        setLoading(false);
      }
    } else {
      // 用户成员：检查是否输入了ID
      if (!memberId.trim()) {
        message.warning('请输入用户ID');
        return;
      }
      
      try {
        setLoading(true);
        await addMember(group.group_id, 'user', memberId.trim(), memberNickname.trim() || undefined);
        message.success('添加用户成功！');
        setMemberId('');
        setMemberNickname('');
        // 不关闭模态框，只刷新数据
        await useGroupChatStore.getState().fetchGroups();
      } catch (error: any) {
        message.error(error.message || '添加用户失败');
      } finally {
        setLoading(false);
      }
    }
  };
  
  // 移除成员
  const handleRemoveMember = async (memberId: string) => {
    try {
      setLoading(true);
      await removeMember(group.group_id, memberId);
      message.success('移除成员成功！');
      // 不关闭模态框，只刷新数据
      await useGroupChatStore.getState().fetchGroups();
    } catch (error: any) {
      message.error(error.message || '移除成员失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 设置管理员
  const handleSetAdmin = async (memberId: string) => {
    try {
      setLoading(true);
      await setMemberAdmin(group.group_id, memberId);
      message.success('设置管理员成功！');
      // 不关闭模态框，只刷新数据
      await useGroupChatStore.getState().fetchGroups();
    } catch (error: any) {
      message.error(error.message || '设置管理员失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 取消管理员
  const handleRemoveAdmin = async (memberId: string) => {
    try {
      setLoading(true);
      await removeMemberAdmin(group.group_id, memberId);
      message.success('已取消管理员身份！');
      // 不关闭模态框，只刷新数据
      await useGroupChatStore.getState().fetchGroups();
    } catch (error: any) {
      message.error(error.message || '取消管理员失败');
    } finally {
      setLoading(false);
    }
  };
  
  // AI上下线控制
  const handleAIStatusToggle = async (memberId: string, currentStatus: string) => {
    try {
      setLoading(true);
      if (currentStatus === 'online') {
        await aiGoOffline(group.group_id, memberId);
        message.success('AI已下线');
      } else {
        await aiGoOnline(group.group_id, memberId);
        message.success('AI已上线');
      }
      // 不关闭模态框，只刷新数据
      await useGroupChatStore.getState().fetchGroups();
    } catch (error: any) {
      message.error(error.message || '操作失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 批量AI上线
  const handleBatchAIOnline = async () => {
    try {
      setLoading(true);
      const result = await batchAiGoOnline(group.group_id);
      message.success(result?.message || '批量上线成功');
      // 不关闭模态框，只刷新数据
      await useGroupChatStore.getState().fetchGroups();
    } catch (error: any) {
      message.error(error.message || '批量上线失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 批量AI下线
  const handleBatchAIOffline = async () => {
    try {
      setLoading(true);
      const result = await batchAiGoOffline(group.group_id);
      message.success(result?.message || '批量下线成功');
      // 不关闭模态框，只刷新数据
      await useGroupChatStore.getState().fetchGroups();
    } catch (error: any) {
      message.error(error.message || '批量下线失败');
    } finally {
      setLoading(false);
    }
  };
  
  // 处理头像文件选择
  const handleAvatarFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    // 检查文件类型
    if (!file.type.startsWith('image/')) {
      message.error('请选择图片文件');
      return;
    }
    
    // 检查文件大小（限制10MB）
    if (file.size > 10 * 1024 * 1024) {
      message.error('图片大小不能超过10MB');
      return;
    }
    
    // 读取文件并显示裁剪器
    const reader = new FileReader();
    reader.onload = (e) => {
      setAvatarFile(e.target?.result as string);
      setCropperVisible(true);
    };
    reader.readAsDataURL(file);
  };
  
  // 确认裁剪并上传头像
  const handleAvatarCropConfirm = async (croppedImageUrl: string) => {
    try {
      setUploadingAvatar(true);
      setCropperVisible(false);
      
      // 将 blob URL 转换为 base64
      const response = await fetch(croppedImageUrl);
      const blob = await response.blob();
      const reader = new FileReader();
      
      reader.onloadend = async () => {
        const base64data = reader.result as string;
        
        try {
          // 调用上传头像API
          const uploadResponse = await api.post(
            `/api/group-chat/groups/${group.group_id}/avatar`,
            { avatar_data: base64data },
            {
              headers: { 'Content-Type': 'application/json' }
            }
          );
          
          message.success('头像上传成功！');
          
          // ⚠️ 不要调用 updateGroup，因为：
          // 1. 后端的上传API已经更新了数据库（存储为 minio:// 格式）
          // 2. 如果调用 updateGroup 传入 HTTP URL，会覆盖 minio:// URL
          // 3. 不关闭模态框，只刷新群组列表
          
          await useGroupChatStore.getState().fetchGroups();
        } catch (error: any) {
          message.error(error.response?.data?.detail || '上传头像失败');
        } finally {
          setUploadingAvatar(false);
        }
      };
      
      reader.readAsDataURL(blob);
    } catch (error: any) {
      message.error('处理图片失败');
      setUploadingAvatar(false);
    }
  };
  
  // 删除群组
  const handleDeleteGroup = async () => {
    try {
      setLoading(true);
      await deleteGroup(group.group_id);
      message.success('群组已解散');
      onClose(); // 关闭模态框
    } catch (error: any) {
      message.error(error.message || '解散群组失败');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <>
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <SettingOutlined />
            <span>群组管理</span>
          </div>
        }
        open={visible}
        onCancel={onClose}
        footer={null}
        width={700}
        destroyOnClose
      >
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        {/* 基本信息标签页 */}
        <Tabs.TabPane tab="基本信息" key="info">
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              name: group.name,
              description: group.description
            }}
            style={{ marginTop: 20 }}
          >
            {/* 群组头像 */}
            <Form.Item label="群组头像">
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <Avatar 
                  size={80} 
                  src={group.avatar ? convertMinioUrlToHttp(group.avatar) : undefined}
                  icon={!group.avatar && <TeamOutlined />}
                  style={{ backgroundColor: '#1890ff', cursor: 'pointer' }}
                  onClick={() => document.getElementById('group-avatar-upload')?.click()}
                />
                <div>
                  <input
                    type="file"
                    accept="image/*"
                    style={{ display: 'none' }}
                    id="group-avatar-upload"
                    onChange={handleAvatarFileChange}
                  />
                  <input
                    type="file"
                    accept="image/*"
                    style={{ display: 'none' }}
                    id="group-background-upload"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        try {
                          // 压缩图片
                          const compressedFile = await new Promise<Blob>((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onload = (event) => {
                              const img = new Image();
                              img.onload = () => {
                                const canvas = document.createElement('canvas');
                                const ctx = canvas.getContext('2d');
                                if (!ctx) {
                                  reject(new Error('无法获取 canvas 上下文'));
                                  return;
                                }
                                
                                const maxWidth = 1920;
                                const maxHeight = 1080;
                                let width = img.width;
                                let height = img.height;
                                
                                if (width > maxWidth || height > maxHeight) {
                                  const ratio = Math.min(maxWidth / width, maxHeight / height);
                                  width *= ratio;
                                  height *= ratio;
                                }
                                
                                canvas.width = width;
                                canvas.height = height;
                                ctx.drawImage(img, 0, 0, width, height);
                                
                                canvas.toBlob((blob) => {
                                  if (blob) resolve(blob);
                                  else reject(new Error('压缩失败'));
                                }, 'image/jpeg', 0.8);
                              };
                              img.onerror = () => reject(new Error('图片加载失败'));
                              img.src = event.target?.result as string;
                            };
                            reader.onerror = () => reject(new Error('文件读取失败'));
                            reader.readAsDataURL(file);
                          });
                          
                          // 转换为 base64
                          const reader = new FileReader();
                          reader.onload = async (event) => {
                            const dataUrl = event.target?.result as string;
                            const base64 = dataUrl.startsWith('data:image') ? dataUrl.split(',')[1] : dataUrl;
                            
                            try {
                              const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
                              const token = authState.state?.token;
                              if (!token) throw new Error('未登录');
                              
                              const resp = await fetch('/api/auth/upload-group-background', {
                                method: 'POST',
                                headers: { 
                                  'Authorization': `Bearer ${token}`, 
                                  'Content-Type': 'application/json' 
                                },
                                body: JSON.stringify({ avatar: base64, group_id: group.group_id })
                              });
                              
                              if (!resp.ok) throw new Error(await resp.text());
                              await resp.json();
                              
                              message.success('背景图上传成功！');
                              
                              // 如果上传的是当前群聊的背景，通过事件通知主组件刷新背景
                              const store = useChatStore.getState();
                              const groupStore = useGroupChatStore.getState();
                              if (store.currentSession?.session_type === 'group' && groupStore.currentGroupId === group.group_id) {
                                // 触发自定义事件，通知主组件刷新背景
                                window.dispatchEvent(new CustomEvent('refreshGroupBackground', { 
                                  detail: { groupId: group.group_id } 
                                }));
                              }
                            } catch (error: any) {
                              message.error(error.message || '背景图上传失败');
                            }
                          };
                          reader.readAsDataURL(compressedFile as Blob);
                        } catch (error: any) {
                          message.error(error.message || '图片处理失败');
                        }
                      }
                      e.target.value = '';
                    }}
                  />
                  <Button 
                    icon={<UploadOutlined />} 
                    onClick={() => document.getElementById('group-background-upload')?.click()}
                  >
                    {group.avatar ? '更换背景' : '上传背景'}
                  </Button>
                  <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                    点击头像可更换群组头像，点击按钮可更换背景图
                  </div>
                </div>
              </div>
            </Form.Item>
            
            <Form.Item
              label="群组名称"
              name="name"
              rules={[
                { required: true, message: '请输入群组名称' },
                { min: 2, max: 50, message: '群组名称长度为 2-50 个字符' }
              ]}
            >
              <Input placeholder="群组名称" maxLength={50} />
            </Form.Item>
            
            <Form.Item
              label="群组简介"
              name="description"
              rules={[
                { max: 200, message: '群组简介不能超过 200 个字符' }
              ]}
            >
              <Input.TextArea 
                placeholder="群组简介" 
                rows={3}
                maxLength={200}
                showCount
              />
            </Form.Item>
            
            <Form.Item>
              <Button type="primary" onClick={handleUpdateInfo} loading={loading}>
                保存更改
              </Button>
            </Form.Item>
          </Form>
        </Tabs.TabPane>
        
        {/* 成员管理标签页 */}
        <Tabs.TabPane tab={`成员管理 (${(group.members || []).length})`} key="members">
          <div style={{ marginTop: 20 }}>
            {/* 添加成员表单 */}
            <div style={{ 
              padding: 16, 
              background: 'var(--bg-secondary)', 
              borderRadius: 8, 
              marginBottom: 20 
            }}>
              <div style={{ marginBottom: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                <PlusOutlined style={{ marginRight: 8 }} />
                添加新成员
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <Select
                  value={memberType}
                  onChange={(value) => {
                    setMemberType(value);
                    setMemberId(''); // 切换类型时清空用户ID
                    setSelectedSessionIds([]); // 切换类型时清空已选择的AI会话
                  }}
                  style={{ width: 120 }}
                >
                  <Select.Option value="ai">
                    <RobotOutlined style={{ marginRight: 6 }} />
                    AI助手
                  </Select.Option>
                  <Select.Option value="user">
                    <UserOutlined style={{ marginRight: 6 }} />
                    用户
                  </Select.Option>
                </Select>
                
                {memberType === 'user' && (
                  <Input
                    value={memberId}
                    onChange={e => setMemberId(e.target.value)}
                    placeholder="输入用户ID"
                    style={{ flex: 1, minWidth: 200 }}
                  />
                )}
                
                <Input
                  value={memberNickname}
                  onChange={e => setMemberNickname(e.target.value)}
                  placeholder="昵称（可选）"
                  style={{ width: 150 }}
                />
                <Button 
                  type="primary" 
                  icon={<PlusOutlined />} 
                  onClick={handleAddMember} 
                  loading={loading}
                  disabled={memberType === 'ai' && availableSessions.length === 0}
                >
                  添加
                </Button>
              </div>
              
              {/* AI会话复选框列表 */}
              {memberType === 'ai' && (
                <div style={{ marginTop: 16 }}>
                  {sessionsLoading ? (
                    <div style={{ textAlign: 'center', padding: '20px 0' }}>
                      <Spin tip="加载会话列表中..." />
                    </div>
                  ) : availableSessions.length === 0 ? (
                    <div style={{ 
                      textAlign: 'center', 
                      padding: '20px 0', 
                      color: 'var(--text-secondary)',
                      background: 'rgba(0,0,0,0.02)',
                      borderRadius: 4
                    }}>
                      {sessions.length === 0 ? '暂无AI会话，请先创建会话' : '所有AI会话都已加入群聊'}
                    </div>
                  ) : (
                    <>
                      <div style={{ 
                        marginBottom: 12, 
                        display: 'flex', 
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}>
                        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                          可用AI会话（已选 {selectedSessionIds.length} 个）
                        </span>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <Button 
                            size="small" 
                            type="link"
                            onClick={() => setSelectedSessionIds(availableSessions.map(s => s.session_id))}
                          >
                            全选
                          </Button>
                          <Button 
                            size="small" 
                            type="link"
                            onClick={() => setSelectedSessionIds([])}
                          >
                            清空
                          </Button>
                        </div>
                      </div>
                      <div style={{ 
                        maxHeight: 300, 
                        overflowY: 'auto',
                        border: '1px solid var(--border-color)',
                        borderRadius: 4,
                        padding: 8
                      }}>
                        <Checkbox.Group 
                          value={selectedSessionIds} 
                          onChange={(checkedValues) => setSelectedSessionIds(checkedValues as string[])}
                          style={{ width: '100%' }}
                        >
                          {availableSessions.map(session => {
                            const avatarUrl = session.role_avatar_url 
                              ? convertMinioUrlToHttp(session.role_avatar_url)
                              : undefined;
                            
                            return (
                              <div 
                                key={session.session_id}
                                style={{ 
                                  padding: '8px 12px',
                                  borderRadius: 4,
                                  marginBottom: 4,
                                  cursor: 'pointer',
                                  transition: 'background 0.2s',
                                  background: selectedSessionIds.includes(session.session_id) 
                                    ? 'rgba(24, 144, 255, 0.1)' 
                                    : 'transparent'
                                }}
                                onClick={() => {
                                  const isSelected = selectedSessionIds.includes(session.session_id);
                                  if (isSelected) {
                                    setSelectedSessionIds(selectedSessionIds.filter(id => id !== session.session_id));
                                  } else {
                                    setSelectedSessionIds([...selectedSessionIds, session.session_id]);
                                  }
                                }}
                              >
                                <Checkbox value={session.session_id} style={{ width: '100%' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Avatar 
                                      size="small" 
                                      src={avatarUrl}
                                      icon={!avatarUrl && <RobotOutlined />}
                                    />
                                    <span>{session.name}</span>
                                  </div>
                                </Checkbox>
                              </div>
                            );
                          })}
                        </Checkbox.Group>
                      </div>
                    </>
                  )}
                </div>
              )}
              
              {memberType === 'ai' && availableSessions.length > 0 && (
                <div style={{ 
                  marginTop: 12, 
                  padding: 8, 
                  background: 'rgba(24, 144, 255, 0.1)', 
                  borderRadius: 4,
                  fontSize: 12,
                  color: 'var(--text-secondary)'
                }}>
                  <ThunderboltOutlined style={{ color: '#1890ff', marginRight: 6 }} />
                  提示：AI助手添加后会自主决定是否上线参与群聊。你也可以手动控制AI的上下线状态。
                </div>
              )}
            </div>
            
            {/* AI批量操作区域 */}
            {group.members?.some(m => m.member_type === 'ai') && (
              <div style={{ 
                padding: 16, 
                background: 'rgba(24, 144, 255, 0.05)', 
                borderRadius: 8, 
                marginBottom: 20,
                border: '1px solid rgba(24, 144, 255, 0.2)'
              }}>
                <div style={{ 
                  marginBottom: 12, 
                  fontWeight: 600, 
                  color: 'var(--text-primary)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8
                }}>
                  <RobotOutlined style={{ color: '#1890ff' }} />
                  AI批量操作
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    onClick={handleBatchAIOnline}
                    loading={loading}
                  >
                    上线全部AI
                  </Button>
                  <Button
                    icon={<CloseCircleOutlined />}
                    onClick={handleBatchAIOffline}
                    loading={loading}
                  >
                    下线全部AI
                  </Button>
                </div>
                <div style={{ 
                  marginTop: 12, 
                  fontSize: 12, 
                  color: 'var(--text-secondary)' 
                }}>
                  💡 所有群成员都可以批量控制AI的上下线状态
                </div>
              </div>
            )}
            
            {/* 成员列表 */}
            <div style={{ display: 'grid', gap: 12 }}>
              {(group.members || []).map((member) => {
                const isAI = member.member_type === 'ai';
                const isOnline = member.status === 'online';
                const isCurrentUser = member.member_id === user?.id;
                
                // 使用与右侧 Sider 相同的头像处理逻辑
                const avatarUrl = isCurrentUser && user?.avatar_url 
                  ? convertMinioUrlToHttp(user.avatar_url)
                  : (member.avatar ? convertMinioUrlToHttp(member.avatar) : defaultAvatar);
                
                // 当前用户是否是群主
                const isOwner = group.members.find(m => m.member_id === user?.id)?.role === 'owner';
                
                return (
                  <div 
                    key={member.member_id}
                    style={{
                      padding: '12px',
                      background: 'var(--bg-secondary)',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)',
                      transition: 'all 0.2s',
                    }}
                  >
                    {/* 上半部分：头像 + 基本信息 */}
                    <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
                      {/* 头像 */}
                      <Avatar 
                        size={48}
                        src={avatarUrl}
                        icon={isAI ? <RobotOutlined /> : <UserOutlined />}
                        style={{ 
                          backgroundColor: isAI ? '#1890ff' : '#87d068',
                          flexShrink: 0
                        }}
                      />
                      
                      {/* 成员信息 */}
                      <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
                        {/* 名称和标签行 */}
                        <div style={{ 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: 6, 
                          marginBottom: 6,
                          flexWrap: 'wrap'
                        }}>
                          <span style={{ 
                            fontSize: '15px', 
                            fontWeight: 600,
                            color: 'var(--text-primary)',
                            wordBreak: 'break-word'
                          }}>
                            {member.nickname}
                          </span>
                          {isAI && (
                            <Tag color="blue" icon={<RobotOutlined />} style={{ margin: 0, fontSize: '11px' }}>
                              AI
                            </Tag>
                          )}
                          <Tag 
                            color={
                              member.role === 'owner' ? 'gold' : 
                              member.role === 'admin' ? 'blue' : 
                              'default'
                            }
                            style={{ margin: 0, fontSize: '11px' }}
                          >
                            {member.role === 'owner' ? '群主' : member.role === 'admin' ? '管理员' : '成员'}
                          </Tag>
                          <Tag 
                            color={isOnline ? 'success' : 'default'}
                            style={{ margin: 0, fontSize: '11px' }}
                          >
                            {member.status === 'online' ? '在线' : member.status === 'busy' ? '忙碌' : '离线'}
                          </Tag>
                        </div>
                        
                        {/* 加入时间（移到这里，简化显示） */}
                        <div style={{ 
                          fontSize: '11px', 
                          color: 'var(--text-secondary)'
                        }}>
                          {new Date(member.joined_at).toLocaleDateString()}
                        </div>
                      </div>
                    </div>
                    
                    {/* 下半部分：操作按钮区 */}
                    <div style={{ 
                      display: 'flex', 
                      gap: 6, 
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      flexWrap: 'wrap',
                      paddingTop: '8px',
                      borderTop: '1px solid var(--border-color)'
                    }}>
                      {isAI && (
                        <Switch
                          checked={isOnline}
                          checkedChildren="在线"
                          unCheckedChildren="离线"
                          loading={loading}
                          onChange={() => handleAIStatusToggle(member.member_id, member.status)}
                          size="small"
                        />
                      )}
                      
                      {/* 只有群主可以设置/取消管理员，且不能对群主操作 */}
                      {isOwner && member.role !== 'owner' && (
                        member.role === 'admin' ? (
                          <Popconfirm
                            title="确定要取消该成员的管理员身份吗？"
                            onConfirm={() => handleRemoveAdmin(member.member_id)}
                            okText="确定"
                            cancelText="取消"
                          >
                            <Button 
                              size="small"
                              icon={<UserOutlined />}
                              loading={loading}
                            >
                              取消管理员
                            </Button>
                          </Popconfirm>
                        ) : (
                          <Popconfirm
                            title="确定要将该成员设置为管理员吗？"
                            description="管理员可以删除普通成员，但不能删除群主或其他管理员"
                            onConfirm={() => handleSetAdmin(member.member_id)}
                            okText="确定"
                            cancelText="取消"
                          >
                            <Button 
                              size="small"
                              icon={<CrownOutlined />}
                              loading={loading}
                            >
                              设为管理员
                            </Button>
                          </Popconfirm>
                        )
                      )}
                      
                      {member.role !== 'owner' && (
                        <Popconfirm
                          title="确定要移除该成员吗？"
                          onConfirm={() => handleRemoveMember(member.member_id)}
                          okText="确定"
                          cancelText="取消"
                        >
                          <Button 
                            size="small"
                            danger 
                            icon={<DeleteOutlined />}
                            loading={loading}
                          >
                            移除
                          </Button>
                        </Popconfirm>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </Tabs.TabPane>
        
        {/* 高级设置标签页 */}
        <Tabs.TabPane tab="高级设置" key="advanced">
          <div style={{ marginTop: 20 }}>
            {/* 群聊系统提示词 */}
            <div style={{ marginBottom: 24 }}>
              <Alert
                message="群聊系统提示词"
                description={
                  <div>
                    <p style={{ margin: 0 }}>为这个群聊设置专属的系统提示词，定义群聊场景、角色设定或对话规则。</p>
                    <p style={{ margin: '8px 0 0 0', fontSize: '12px', color: '#888' }}>
                      💡 最终系统提示词 = AI原本的系统提示词 + 群聊系统提示词 + 动态群聊信息（成员列表等）
                    </p>
                  </div>
                }
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
              />
              <Input.TextArea
                value={groupSystemPrompt}
                onChange={(e) => setGroupSystemPrompt(e.target.value)}
                placeholder="例如：这是一个**友好**的交流群"
                rows={6}
                maxLength={2000}
                showCount
                disabled={!isOwner || loadingSystemPrompt}
                style={{ marginBottom: 12 }}
              />
              <Button
                type="primary"
                onClick={handleSaveSystemPrompt}
                loading={savingSystemPrompt}
                disabled={!isOwner || loadingSystemPrompt}
                block
              >
                {isOwner ? '保存系统提示词' : '仅群主可编辑'}
              </Button>
            </div>
            
            {/* 策略配置入口 */}
            <div style={{ marginBottom: 24 }}>
              <Alert
                message="群聊策略配置"
                description="控制AI回复的各种限流策略，包括频率控制、并发限制、延迟管理等。只有群主可以修改配置。"
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
              />
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={() => setStrategyConfigVisible(true)}
                block
              >
                {isOwner ? '配置群聊策略' : '查看群聊策略'}
              </Button>
            </div>
            
            {/* 清空历史消息 */}
            <div style={{ 
              padding: 16, 
              background: 'rgba(250, 173, 20, 0.1)', 
              borderRadius: 8,
              border: '1px solid rgba(250, 173, 20, 0.3)',
              marginBottom: 16
            }}>
              <div style={{ marginBottom: 12, fontWeight: 600, color: '#faad14' }}>
                <ExclamationCircleOutlined style={{ marginRight: 8 }} />
                清空历史消息
              </div>
              <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
                清空所有历史消息后，群聊中的所有消息记录和文件将被永久删除。群组本身和成员信息将保留。此操作不可恢复，请谨慎操作！
              </p>
              <Popconfirm
                title="确定要清空所有历史消息吗？"
                description={
                  <div>
                    <p style={{ marginBottom: 8 }}>清空后将删除：</p>
                    <ul style={{ paddingLeft: 20, margin: 0 }}>
                      <li>所有群聊消息记录</li>
                      <li>消息中的图片、语音等文件</li>
                    </ul>
                    <p style={{ marginTop: 8 }}>保留：</p>
                    <ul style={{ paddingLeft: 20, margin: 0 }}>
                      <li>群组信息和设置</li>
                      <li>成员列表</li>
                    </ul>
                    <p style={{ marginTop: 8, color: '#faad14', fontWeight: 600 }}>
                      此操作不可恢复！
                    </p>
                  </div>
                }
                onConfirm={async () => {
                  try {
                    setLoading(true);
                    const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
                    const token = authState.state?.token;
                    if (!token) throw new Error('未登录');
                    
                    const response = await fetch(`/api/group-chat/groups/${group.group_id}/messages`, {
                      method: 'DELETE',
                      headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                      }
                    });
                    
                    if (!response.ok) {
                      const error = await response.json();
                      throw new Error(error.detail || '清空失败');
                    }
                    
                    const result = await response.json();
                    message.success(`已清空 ${result.deleted.messages} 条消息和 ${result.deleted.files} 个文件`);
                    
                    // 立即清空本地消息列表（不等待 WebSocket）
                    useGroupChatStore.setState(state => ({
                      messages: {
                        ...state.messages,
                        [group.group_id]: []
                      },
                      messageMetadata: {
                        ...state.messageMetadata,
                        [group.group_id]: {
                          total: 0,
                          loaded: 0,
                          hasMore: false,
                          isLoading: false,
                          oldestTimestamp: undefined
                        }
                      }
                    }));
                    
                    // 不关闭模态框，只刷新群组信息
                    await useGroupChatStore.getState().fetchGroups();
                  } catch (error: any) {
                    message.error(error.message || '清空历史消息失败');
                  } finally {
                    setLoading(false);
                  }
                }}
                okText="确定清空"
                cancelText="取消"
                okButtonProps={{ loading }}
              >
                <Button 
                  icon={<DeleteOutlined />} 
                  loading={loading}
                  style={{ borderColor: '#faad14', color: '#faad14' }}
                >
                  清空所有历史消息
                </Button>
              </Popconfirm>
            </div>
            
            {/* 解散群组 */}
            <div style={{ 
              padding: 16, 
              background: 'rgba(255, 77, 79, 0.1)', 
              borderRadius: 8,
              border: '1px solid rgba(255, 77, 79, 0.3)'
            }}>
              <div style={{ marginBottom: 12, fontWeight: 600, color: 'var(--error-color)' }}>
                <DeleteOutlined style={{ marginRight: 8 }} />
                解散群组
              </div>
              <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
                解散群组后，所有消息和成员信息将被永久清除，群组文件也将被删除。此操作不可恢复，请谨慎操作！
              </p>
              <Popconfirm
                title="确定要解散该群组吗？"
                description={
                  <div>
                    <p style={{ marginBottom: 8 }}>解散后将删除：</p>
                    <ul style={{ paddingLeft: 20, margin: 0 }}>
                      <li>所有群聊消息</li>
                      <li>成员信息</li>
                      <li>群组文件和头像</li>
                    </ul>
                    <p style={{ marginTop: 8, color: '#ff4d4f', fontWeight: 600 }}>
                      此操作不可恢复！
                    </p>
                  </div>
                }
                onConfirm={handleDeleteGroup}
                okText="确定解散"
                cancelText="取消"
                okButtonProps={{ danger: true, loading }}
              >
                <Button danger icon={<DeleteOutlined />} loading={loading}>
                  解散群组
                </Button>
              </Popconfirm>
            </div>
          </div>
        </Tabs.TabPane>
      </Tabs>
      
      {/* 头像裁剪器 */}
      {cropperVisible && (
        <AvatarCropper
          visible={cropperVisible}
          imageUrl={avatarFile}
          onCancel={() => setCropperVisible(false)}
          onConfirm={handleAvatarCropConfirm}
        />
      )}
      </Modal>
      
      {/* 群聊策略配置对话框 */}
      <GroupStrategyConfigModal
        visible={strategyConfigVisible}
        groupId={group.group_id}
        isOwner={isOwner}
        onClose={() => setStrategyConfigVisible(false)}
        onSuccess={() => {
          message.success('策略配置已更新');
          setStrategyConfigVisible(false);
        }}
      />
    </>
  );
};

export default Chat;