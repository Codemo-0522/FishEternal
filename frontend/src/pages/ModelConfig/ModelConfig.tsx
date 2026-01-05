import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Button,
  Input,
  Form,
  Select,
  Switch,
  message,
  Modal,
  Space,
  Typography,
  Row,
  Col,
  Tag,
  Spin,
  Alert,
  Tabs,
  Tooltip,
  Collapse,
  Image
} from 'antd';
import {
  ExperimentOutlined,
  SaveOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  SettingOutlined,
  MessageOutlined,
  SoundOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  ArrowLeftOutlined,
  DatabaseOutlined,
  PlusOutlined,
  FileImageOutlined
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import styles from './ModelConfig.module.css';
import bytedanceVoicesData from '../Chat/byteDance_tts.json';
import xfyunVoicesData from '../Chat/xfyun_tts.json';
import { useThemeStore } from '../../stores/themeStore';
import modelsConfigData from './models_config.json';

const { Paragraph } = Typography;
const { Option } = Select;
const { TabPane } = Tabs;

// 从JSON配置中提取模型名称列表
const getModelNamesFromConfig = (providerId: string): Array<{ value: string; label: string }> => {
  const providerConfig = (modelsConfigData as any).providers[providerId];
  if (!providerConfig || !providerConfig.models) {
    return [];
  }
  return providerConfig.models.map((m: any) => ({
    value: m.value,
    label: m.label
  }));
};

// 根据主题获取 logo 路径的辅助函数
const getLogoPath = (providerId: string, theme: 'light' | 'dark' | 'romantic'): string => {
  const providerConfig = (modelsConfigData as any).providers[providerId];

  // 优先处理有深色主题logo的情况
  if (providerConfig && providerConfig.logoDark) {
    // 深色主题使用logoDark，浅色和romantic主题使用默认logo
    if (theme === 'dark') {
      return providerConfig.logoDark;
    } else {
      return providerConfig.logo;
    }
  }

  // 如果没有深色主题logo，所有主题都使用默认logo
  if (providerConfig && providerConfig.logo) {
    return providerConfig.logo;
  }

  // 针对特定服务商的硬编码logo（作为后备）
  const logoMap: Record<string, string> = {
    ark: '/src/static/logo/huoshan.png',
    local: '/src/static/logo/locals.png',
  };

  return logoMap[providerId] || '/src/static/logo/localmodel.png';
};

// 模型服务商配置接口
// 自定义模型配置（用户输入的模型ID和显示名称）
interface CustomModel {
  id: string;        // OpenAI 库所需的模型ID
  displayName: string; // 前端友好显示的名称
  supportsImage: boolean; // 是否支持图片输入
}

interface ModelProvider {
  id: string;
  name: string;
  logo: string;
  description: string;
  baseUrl: string;
  apiKey: string;
  defaultModel: string;
  enabled: boolean;
  models: string[];
  testStatus?: 'idle' | 'testing' | 'success' | 'error';
  testMessage?: string;
  officialWebsite?: string;
  supportsCustomModels?: boolean; // 是否支持用户自定义模型（使用OpenAI库的提供商）
  customModels?: CustomModel[];   // 用户自定义的模型列表
}

// TTS服务商配置接口
interface TtsProvider {
  id: string;
  name: string;
  logo: string;
  description: string;
  features: string[];
  config: {
    appId: string;
    apiKey?: string;
    apiSecret?: string;
    token?: string;
    cluster?: string;
  };
  voiceSettings: {
    voiceType: string;
  };
  enabled: boolean;
  testStatus?: 'idle' | 'testing' | 'success' | 'error';
  testMessage?: string;
  officialWebsite?: string;
}

// Embedding服务商配置接口
interface EmbeddingProvider {
  id: string;
  name: string;
  logo: string;
  description: string;
  baseUrl?: string;
  apiKey?: string;
  defaultModel: string;
  enabled: boolean;
  models: string[];
  testStatus?: 'idle' | 'testing' | 'success' | 'error';
  testMessage?: string;
  officialWebsite?: string;
}

// ASR服务商配置接口
interface AsrProvider {
  id: string;
  name: string;
  logo: string;
  description: string;
  baseUrl: string;
  apiKey: string;
  defaultModel: string;
  enabled: boolean;
  models: string[];
  testStatus?: 'idle' | 'testing' | 'success' | 'error';
  testMessage?: string;
  officialWebsite?: string;
}

// 图片生成服务商配置接口
interface ImageGenerationProvider {
  id: string;
  name: string;
  logo: string;
  description: string;
  apiKey: string;
  enabled: boolean;
  defaultModel: string;
  models: Array<{ value: string; label: string }>;
  supportsCustomModels?: boolean;
  customModels?: CustomModel[];
  testStatus?: 'idle' | 'testing' | 'success' | 'error';
  testMessage?: string;
  officialWebsite?: string;
}

// 从JSON配置生成默认模型提供商配置
const generateDefaultProviders = (): ModelProvider[] => {
  const providers = (modelsConfigData as any).providers;
  return Object.keys(providers).map(providerId => {
    const config = providers[providerId];
    return {
      id: config.id,
      name: config.name,
      logo: config.logo,
      description: config.description,
      baseUrl: config.baseUrl,
      apiKey: providerId === 'ollama' ? 'ollama' : '',
      defaultModel: config.defaultModel,
      enabled: false,
      models: config.models.map((m: any) => m.value),
      testStatus: 'idle' as const,
      officialWebsite: config.officialWebsite,
      supportsCustomModels: config.supportsCustomModels,
      customModels: []
    };
  });
};

// 默认模型配置
const defaultProviders: ModelProvider[] = generateDefaultProviders();

// 默认TTS配置
const defaultTtsProviders: TtsProvider[] = [
  {
    id: 'xfyun',
    name: '讯飞云TTS',
    logo: '/src/static/logo/xfyun.png',
    description: '科大讯飞语音合成服务',
    features: ['高质量语音', '多种音色', '稳定可靠'],
    config: {
      appId: '',
      apiKey: '',
      apiSecret: ''
    },
    voiceSettings: {
      voiceType: 'x4_xiaoyan'
    },
    enabled: false,
    testStatus: 'idle',
    officialWebsite:'https://console.xfyun.cn/services/tts/'
  },
  {
    id: 'bytedance',
    name: '字节跳动TTS',
    logo: '/src/static/logo/huoshan.png',
    description: '火山引擎语音合成服务',
    features: ['自然语音', '低延迟', '企业级'],
    config: {
      appId: '',
      token: '',
      cluster: ''
    },
    voiceSettings: {
      voiceType: 'zh_female_wanqudashu_moon_bigtts'
    },
    enabled: false,
    testStatus: 'idle',
    officialWebsite:'https://console.volcengine.com/ark/'
  }
];

// 默认 Embedding 配置
const defaultEmbeddingProviders: EmbeddingProvider[] = [
  {
    id: 'ark',
    name: '火山引擎（豆包）',
    logo: '/src/static/logo/huoshan.png',
    description: '字节跳动火山引擎 Embedding 模型',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    apiKey: '',
    defaultModel: 'doubao-embedding-large-text-250515',
    enabled: false,
    models: [
      'doubao-embedding-large-text-250515',
    ],
    testStatus: 'idle'
  },
  {
    id: 'ollama',
    name: 'Ollama',
    logo: '/src/static/logo/ollama.png',
    description: '本地部署的开源 Embedding 模型',
    baseUrl: 'http://localhost:11434',
    apiKey: '',
    defaultModel: '',
    enabled: false,
    models: [],
    testStatus: 'idle'
  },
  {
    id: 'local',
    name: '本地模型',
    logo: '/src/static/logo/locals.png',
    description: '本地推理的开源 Embedding 模型',
    baseUrl: '',
    apiKey: '',
    defaultModel: 'all-MiniLM-L6-v2',
    enabled: false,
    models: ['all-MiniLM-L6-v2'],
    testStatus: 'idle'
  }
];

// 默认 ASR 配置
const defaultAsrProviders: AsrProvider[] = [
  {
    id: 'siliconflow',
    name: '硅基流动 ASR',
    logo: '/src/static/logo/siliconflow.png',
    description: '硅基流动语音识别服务 - 支持多种ASR模型',
    baseUrl: 'https://api.siliconflow.cn/v1/audio/transcriptions',
    apiKey: '',
    defaultModel: 'FunAudioLLM/SenseVoiceSmall',
    enabled: false,
    models: [
      'FunAudioLLM/SenseVoiceSmall',
      'TeleAI/TeleSpeechASR'
    ],
    testStatus: 'idle',
    officialWebsite: 'https://cloud.siliconflow.cn/'
  }
];

// 默认图片生成配置
const defaultImageGenerationProviders: ImageGenerationProvider[] = [
  {
    id: 'modelscope',
    name: '魔塔社区（通义）',
    logo: '/src/static/logo/modelscope.png',
    description: 'ModelScope（通义万相）图片生成服务',
    apiKey: '',
    enabled: false,
    defaultModel: 'Qwen/Qwen-Image-2512',
    models: [
      { value: 'Qwen/Qwen-Image-2512', label: 'Qwen-Image-2512' }
    ],
    supportsCustomModels: true,
    customModels: [],
    testStatus: 'idle',
    officialWebsite: 'https://www.modelscope.cn/models/Qwen/Qwen-Image-2512/summary'
  }
];

// 默认选择器组件接口
interface DefaultSelectorProps<T extends { id: string; name: string; logo: string; enabled: boolean }> {
  title: string;
  items: T[];
  selectedId: string;
  onSelect: (id: string) => void;
  isItemValid: (item: T) => boolean;
  isMobile: boolean;
}

// 通用默认选择器组件
function DefaultSelector<T extends { id: string; name: string; logo: string; enabled: boolean }>({
  title,
  items,
  selectedId,
  onSelect,
  isItemValid,
  isMobile
}: DefaultSelectorProps<T>) {
  return (
    <Card 
      style={{ 
        marginBottom: isMobile ? 8 : 16, 
        background: 'var(--bg-card)', 
        borderColor: 'var(--border-light)' 
      }}
      bodyStyle={{ 
        padding: isMobile ? '8px 12px' : undefined 
      }}
    >
      <div style={{ marginBottom: isMobile ? 6 : 8, color: 'var(--text-primary)', fontSize: isMobile ? '13px' : undefined }}>
        <strong>{title}</strong>
      </div>
      
      {/* 移动端：使用下拉框 */}
      {isMobile ? (
        <Select
          value={selectedId}
          onChange={(value) => onSelect(value)}
          placeholder={`请选择${title.replace(/新建会话时使用的默认模型：|默认语音合成服务：/g, '').trim()}`}
          style={{ width: '100%' }}
          size="middle"
        >
          {items.map(item => (
            <Option 
              key={item.id} 
              value={item.id}
              disabled={!isItemValid(item)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <img 
                  src={item.logo}
                  alt={item.name}
                  style={{ 
                    width: 24, 
                    height: 24, 
                    objectFit: 'contain',
                    filter: 'var(--logo-filter)'
                  }}
                />
                <span>{item.name}</span>
                {!isItemValid(item) && (
                  <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>(未配置)</span>
                )}
              </div>
            </Option>
          ))}
        </Select>
      ) : (
        /* 桌面端：使用单选框 */
        <Space direction="horizontal" size="large">
          {items.map(item => (
            <div 
              key={item.id}
              onClick={() => {
                if (isItemValid(item)) {
                  onSelect(item.id);
                } else {
                  message.warning(`请先配置并启用 ${item.name}`);
                }
              }}
              style={{ 
                cursor: isItemValid(item) ? 'pointer' : 'not-allowed',
                opacity: isItemValid(item) ? 1 : 0.5,
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                color: 'var(--text-primary)'
              }}
            >
              <input
                type="radio"
                checked={selectedId === item.id}
                onChange={() => {}}
                disabled={!isItemValid(item)}
                style={{ cursor: isItemValid(item) ? 'pointer' : 'not-allowed' }}
              />
              <img 
                src={item.logo} 
                alt={item.name}
                style={{ 
                  width: '20px', 
                  height: '20px', 
                  objectFit: 'contain',
                  filter: 'var(--logo-filter)'
                }}
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
              <span style={{ flex: 1 }}>{item.name}</span>
              {selectedId === item.id && (
                <Tag color="blue">当前默认</Tag>
              )}
            </div>
          ))}
        </Space>
      )}
    </Card>
  );
}

const ModelConfig: React.FC = () => {
  const navigate = useNavigate();
  const { theme } = useThemeStore();
  
  // 检测移动设备
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  
  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  
  // 标签页状态
  const [activeTab, setActiveTab] = useState<string>('model');

  // 模型配置状态 - 使用主题动态生成 logo 路径
  const [providers, setProviders] = useState<ModelProvider[]>(
    defaultProviders.map(p => ({
      ...p,
      logo: getLogoPath(p.id, theme)
    }))
  );
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [currentProvider, setCurrentProvider] = useState<ModelProvider | null>(null);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const [defaultProviderId, setDefaultProviderId] = useState<string>('');
  const [form] = Form.useForm();
  
  // Ollama 相关状态
  const [ollamaModels, setOllamaModels] = useState<Array<{ value: string; label: string }>>([]);
  const [isLoadingOllamaModels, setIsLoadingOllamaModels] = useState(false);
  const [ollamaModelsLoadedForBaseUrl, setOllamaModelsLoadedForBaseUrl] = useState<string>('');
  const [selectedOllamaModels, setSelectedOllamaModels] = useState<string[]>([]); // 用户选择的 Ollama 对话模型
  const [selectedOllamaEmbeddingModels, setSelectedOllamaEmbeddingModels] = useState<string[]>([]); // 用户选择的 Ollama 嵌入模型
  const [ollamaEmbeddingModels, setOllamaEmbeddingModels] = useState<Array<{ value: string; label: string }>>([]);
  const [isLoadingOllamaEmbeddingModels, setIsLoadingOllamaEmbeddingModels] = useState(false);
  
  // 自定义模型相关状态
  const [customModels, setCustomModels] = useState<CustomModel[]>([]);
  const [customModelId, setCustomModelId] = useState('');
  const [customModelDisplayName, setCustomModelDisplayName] = useState('');
  const [customModelSupportsImage, setCustomModelSupportsImage] = useState(false);
  
  // 密码验证相关状态
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [verifyingPassword, setVerifyingPassword] = useState(false);
  const [passwordForm] = Form.useForm();

  // TTS配置状态
  const [ttsProviders, setTtsProviders] = useState<TtsProvider[]>(defaultTtsProviders);
  const [ttsModalVisible, setTtsModalVisible] = useState(false);
  const [currentTtsProvider, setCurrentTtsProvider] = useState<TtsProvider | null>(null);
  const [testingTtsProvider, setTestingTtsProvider] = useState<string | null>(null);
  
  // Embedding配置状态
  const [embeddingProviders, setEmbeddingProviders] = useState<EmbeddingProvider[]>(
    defaultEmbeddingProviders.map(p => ({
      ...p,
      logo: getLogoPath(p.id, theme)
    }))
  );
  const [embeddingModalVisible, setEmbeddingModalVisible] = useState(false);
  const [currentEmbeddingProvider, setCurrentEmbeddingProvider] = useState<EmbeddingProvider | null>(null);
  const [testingEmbeddingProvider, setTestingEmbeddingProvider] = useState<string | null>(null);
  const [defaultEmbeddingProviderId, setDefaultEmbeddingProviderId] = useState<string>('');
  const [embeddingForm] = Form.useForm();
  const [ttsForm] = Form.useForm();
  const [voiceGenderFilter, setVoiceGenderFilter] = useState<string>('all');
  const [voiceSearchQuery, setVoiceSearchQuery] = useState<string>('');
  const [showVoiceSearch, setShowVoiceSearch] = useState<boolean>(false);
  const [defaultTtsProviderId, setDefaultTtsProviderId] = useState<string>('');
  const [showTtsApiKey, setShowTtsApiKey] = useState(false); // TTS API密钥显示状态
  const [showEmbeddingApiKey, setShowEmbeddingApiKey] = useState(false); // Embedding API密钥显示状态

  // ASR配置状态
  const [asrProviders, setAsrProviders] = useState<AsrProvider[]>(defaultAsrProviders);
  const [asrModalVisible, setAsrModalVisible] = useState(false);
  const [currentAsrProvider, setCurrentAsrProvider] = useState<AsrProvider | null>(null);
  const [testingAsrProvider, setTestingAsrProvider] = useState<string | null>(null);
  const [defaultAsrProviderId, setDefaultAsrProviderId] = useState<string>('');
  const [asrForm] = Form.useForm();
  const [showAsrApiKey, setShowAsrApiKey] = useState(false); // ASR API密钥显示状态

  // 图片生成配置状态
  const [imageGenerationProviders, setImageGenerationProviders] = useState<ImageGenerationProvider[]>(defaultImageGenerationProviders);
  const [imageGenerationModalVisible, setImageGenerationModalVisible] = useState(false);
  const [currentImageGenerationProvider, setCurrentImageGenerationProvider] = useState<ImageGenerationProvider | null>(null);
  const [testingImageGenerationProvider, setTestingImageGenerationProvider] = useState<string | null>(null);
  const [defaultImageGenerationProviderId, setDefaultImageGenerationProviderId] = useState<string>('');
  const [imageGenerationForm] = Form.useForm();
  const [showImageGenerationApiKey, setShowImageGenerationApiKey] = useState(false);
  const [customImageModels, setCustomImageModels] = useState<CustomModel[]>([]);
  const [customImageModelId, setCustomImageModelId] = useState('');
  const [customImageModelDisplayName, setCustomImageModelDisplayName] = useState('');
  const [imageTestPromptModalVisible, setImageTestPromptModalVisible] = useState(false);
  const [testImagePrompt, setTestImagePrompt] = useState('a fish'); // 默认提示词
  const [testImageData, setTestImageData] = useState<string | null>(null);

  // 确保 URL 有 http 协议
  const ensureHttpProtocol = useCallback((url: string): string => {
    const trimmed = url.trim();
    if (!trimmed) return '';
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) return trimmed;
    return `http://${trimmed}`;
  }, []);

  // 动态获取 Ollama 模型列表（复用 Chat.tsx 的逻辑）
  const fetchOllamaModels = useCallback(async (baseUrl: string) => {
    const normalizedBaseUrl = ensureHttpProtocol(baseUrl);
    if (!normalizedBaseUrl) return;
    if (ollamaModelsLoadedForBaseUrl === normalizedBaseUrl && ollamaModels.length > 0) return;
    
    setIsLoadingOllamaModels(true);
    try {
      // 先尝试直接访问
      const directResp = await fetch(`${normalizedBaseUrl.replace(/\/$/, '')}/api/tags`, { method: 'GET' });
      if (!directResp.ok) {
        throw new Error(`direct ${directResp.status}`);
      }
      const data = await directResp.json();
      const models = (data.models || []).map((m: any) => ({ value: m.name, label: m.name }));
      setOllamaModels(models);
      setOllamaModelsLoadedForBaseUrl(normalizedBaseUrl);
      if (models.length === 0) message.warning('Ollama 未找到可用模型，请先执行 ollama pull');
    } catch (_err) {
      try {
        // 通过后端代理访问
        const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
        const token = authState.state?.token;
        const resp = await fetch(`/api/chat/ollama/tags?base_url=${encodeURIComponent(normalizedBaseUrl)}`, {
          headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text);
        }
        const data = await resp.json();
        const models = (data.models || []).map((m: any) => ({ value: m.name, label: m.name }));
        setOllamaModels(models);
        setOllamaModelsLoadedForBaseUrl(normalizedBaseUrl);
        if (models.length === 0) message.warning('Ollama 未找到可用模型，请先执行 ollama pull');
      } catch (err) {
        console.error('[ModelConfig] 获取 Ollama 模型列表失败:', err);
        message.error('获取 Ollama 模型列表失败，请检查服务地址或网络');
      }
    } finally {
      setIsLoadingOllamaModels(false);
    }
  }, [ensureHttpProtocol, ollamaModelsLoadedForBaseUrl, ollamaModels.length]);

  // 获取 Ollama 嵌入模型列表
  const fetchOllamaEmbeddingModels = useCallback(async (baseUrl: string) => {
    const normalizedBaseUrl = ensureHttpProtocol(baseUrl);
    if (!normalizedBaseUrl) return;
    
    setIsLoadingOllamaEmbeddingModels(true);
    try {
      // 先尝试直接访问
      const directResp = await fetch(`${normalizedBaseUrl.replace(/\/$/, '')}/api/tags`, { method: 'GET' });
      if (!directResp.ok) {
        throw new Error(`direct ${directResp.status}`);
      }
      const data = await directResp.json();
      const models = (data.models || []).map((m: any) => ({ value: m.name, label: m.name }));
      setOllamaEmbeddingModels(models);
      if (models.length === 0) message.warning('Ollama 未找到可用嵌入模型，请先执行 ollama pull');
    } catch (_err) {
      try {
        // 通过后端代理访问
        const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
        const token = authState.state?.token;
        const resp = await fetch(`/api/chat/ollama/tags?base_url=${encodeURIComponent(normalizedBaseUrl)}`, {
          headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text);
        }
        const data = await resp.json();
        const models = (data.models || []).map((m: any) => ({ value: m.name, label: m.name }));
        setOllamaEmbeddingModels(models);
        if (models.length === 0) message.warning('Ollama 未找到可用嵌入模型，请先执行 ollama pull');
      } catch (err) {
        console.error('[ModelConfig] 获取 Ollama 嵌入模型列表失败:', err);
        message.error('获取 Ollama 嵌入模型列表失败，请检查服务地址或网络');
      }
    } finally {
      setIsLoadingOllamaEmbeddingModels(false);
    }
  }, [ensureHttpProtocol]);

  // 主题变化时更新 logo
  useEffect(() => {
    setProviders(prev => prev.map(p => ({
      ...p,
      logo: getLogoPath(p.id, theme)
    })));
    setEmbeddingProviders(prev => prev.map(p => ({
      ...p,
      logo: getLogoPath(p.id, theme)
    })));
  }, [theme]);

  // 加载配置
  useEffect(() => {
    loadConfigs();
    loadDefaultModel();
    loadTtsConfigs();
    loadDefaultTts();
    loadEmbeddingConfigs();
    loadDefaultEmbedding();
    loadAsrConfigs();
    loadDefaultAsr();
    loadImageGenerationConfigs();
    loadDefaultImageGeneration();
  }, []);

  const loadConfigs = async () => {
    setLoading(true);
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/model-config/user', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();

      if (result.success && result.configs) {
        const updatedProviders = defaultProviders.map(provider => {
          const userConfig = result.configs[provider.id];
          if (userConfig) {
            return {
              ...provider,
              logo: getLogoPath(provider.id, theme),
              baseUrl: userConfig.base_url || provider.baseUrl,
              apiKey: userConfig.api_key || provider.apiKey,
              defaultModel: userConfig.default_model || provider.defaultModel,
              enabled: userConfig.enabled !== undefined ? userConfig.enabled : provider.enabled,
              models: userConfig.models || provider.models,
              customModels: userConfig.custom_models || provider.customModels || []
            };
          }
          return {
            ...provider,
            logo: getLogoPath(provider.id, theme)
          };
        });
        setProviders(updatedProviders);
      }
    } catch (error) {
      console.error('加载配置失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 加载默认模型
  const loadDefaultModel = async () => {
    try {
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
      if (result.success && result.provider_id) {
        setDefaultProviderId(result.provider_id);
      }
    } catch (error) {
      console.error('加载默认模型失败:', error);
    }
  };

  // 设置默认模型
  const setDefaultModel = async (providerId: string) => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/model-config/default?provider_id=' + providerId, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success) {
        message.success('默认模型设置成功');
        setDefaultProviderId(providerId);
      } else {
        message.error('设置默认模型失败: ' + result.message);
      }
    } catch (error) {
      console.error('设置默认模型失败:', error);
      message.error('设置默认模型失败');
    }
  };

  // 加载TTS配置
  const loadTtsConfigs = async () => {
    setLoading(true);
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/tts-config/user', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();

      if (result.success && result.configs) {
        const updatedTtsProviders = defaultTtsProviders.map(provider => {
          const userConfig = result.configs[provider.id];
          if (userConfig) {
            return {
              ...provider,
              config: userConfig.config || provider.config,
              voiceSettings: userConfig.voice_settings || provider.voiceSettings,
              enabled: userConfig.enabled !== undefined ? userConfig.enabled : provider.enabled
            };
          }
          return provider;
        });
        setTtsProviders(updatedTtsProviders);
      }
    } catch (error) {
      console.error('加载TTS配置失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 加载默认TTS
  const loadDefaultTts = async () => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/tts-config/default', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success && result.provider_id) {
        setDefaultTtsProviderId(result.provider_id);
      }
    } catch (error) {
      console.error('加载默认TTS失败:', error);
    }
  };

  // 设置默认TTS
  const setDefaultTts = async (providerId: string) => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/tts-config/default?provider_id=' + providerId, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success) {
        message.success('默认TTS服务设置成功');
        setDefaultTtsProviderId(providerId);
      } else {
        message.error('设置默认TTS服务失败: ' + result.message);
      }
    } catch (error) {
      console.error('设置默认TTS服务失败:', error);
      message.error('设置默认TTS服务失败');
    }
  };

  // 加载Embedding配置
  const loadEmbeddingConfigs = async () => {
    setLoading(true);
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/embedding-config/user', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();

      if (result.success && result.configs) {
        const updatedEmbeddingProviders = defaultEmbeddingProviders.map(provider => {
          const userConfig = result.configs[provider.id];
          if (userConfig) {
            return {
              ...provider,
              logo: getLogoPath(provider.id, theme),
              baseUrl: userConfig.base_url || provider.baseUrl,
              apiKey: userConfig.api_key || provider.apiKey,
              defaultModel: userConfig.default_model || provider.defaultModel,
              enabled: userConfig.enabled !== undefined ? userConfig.enabled : provider.enabled,
              models: userConfig.models || provider.models
            };
          }
          return {
            ...provider,
            logo: getLogoPath(provider.id, theme)
          };
        });
        setEmbeddingProviders(updatedEmbeddingProviders);
      }
    } catch (error) {
      console.error('加载Embedding配置失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 加载默认Embedding
  const loadDefaultEmbedding = async () => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/embedding-config/default', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success && result.provider_id) {
        setDefaultEmbeddingProviderId(result.provider_id);
      }
    } catch (error) {
      console.error('加载默认Embedding失败:', error);
    }
  };

  // 设置默认Embedding
  const setDefaultEmbedding = async (providerId: string) => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/embedding-config/default?provider_id=' + providerId, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success) {
        message.success('默认Embedding模型设置成功');
        setDefaultEmbeddingProviderId(providerId);
      } else {
        message.error('设置默认Embedding模型失败: ' + result.message);
      }
    } catch (error) {
      console.error('设置默认Embedding模型失败:', error);
      message.error('设置默认Embedding模型失败');
    }
  };

  // 验证用户密码
  const verifyPassword = async (password: string): Promise<boolean> => {
    try {
      const authData = localStorage.getItem('auth-storage');
      if (!authData) {
        message.error('未登录');
        return false;
      }

      const { state } = JSON.parse(authData);
      if (!state.token) {
        message.error('未登录');
        return false;
      }

      const response = await fetch('/api/auth/verify-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${state.token}`
        },
        body: JSON.stringify({ password })
      });

      const result = await response.json();
      return result.verified === true;
    } catch (error) {
      console.error('密码验证失败:', error);
      return false;
    }
  };

  // 处理显示 API 密钥（对话模型）
  const handleShowApiKey = () => {
    if (showApiKey) {
      // 如果当前是显示状态，直接隐藏
      setShowApiKey(false);
    } else {
      // 如果当前是隐藏状态，需要验证密码
      setPasswordModalVisible(true);
    }
  };

  // 处理显示 TTS API 密钥
  const handleShowTtsApiKey = () => {
    if (showTtsApiKey) {
      // 如果当前是显示状态，直接隐藏
      setShowTtsApiKey(false);
    } else {
      // 如果当前是隐藏状态，需要验证密码
      setPasswordModalVisible(true);
    }
  };

  // 处理显示 Embedding API 密钥
  const handleShowEmbeddingApiKey = () => {
    if (showEmbeddingApiKey) {
      // 如果当前是显示状态，直接隐藏
      setShowEmbeddingApiKey(false);
    } else {
      // 如果当前是隐藏状态，需要验证密码
      setPasswordModalVisible(true);
    }
  };

  // 处理显示 ASR API 密钥
  const handleShowAsrApiKey = () => {
    if (showAsrApiKey) {
      // 如果当前是显示状态，直接隐藏
      setShowAsrApiKey(false);
    } else {
      // 如果当前是隐藏状态，需要验证密码
      setPasswordModalVisible(true);
    }
  };

  // 处理密码验证提交
  const handlePasswordSubmit = async () => {
    try {
      const values = await passwordForm.validateFields();
      setVerifyingPassword(true);

      const isValid = await verifyPassword(values.password);
      
      if (isValid) {
        message.success('验证成功');
        // 根据当前标签页设置对应的显示状态
        if (activeTab === 'model') {
          setShowApiKey(true);
        } else if (activeTab === 'tts') {
          setShowTtsApiKey(true);
        } else if (activeTab === 'embedding') {
          setShowEmbeddingApiKey(true);
        } else if (activeTab === 'asr') {
          setShowAsrApiKey(true);
        } else if (activeTab === 'imageGeneration') {
          setShowImageGenerationApiKey(true);
        }
        setPasswordModalVisible(false);
        passwordForm.resetFields();
      } else {
        message.error('密码错误，请重试');
      }
    } catch (error) {
      console.error('密码验证失败:', error);
    } finally {
      setVerifyingPassword(false);
    }
  };

  // 打开配置模态框
  const openConfigModal = (provider: ModelProvider) => {
    setCurrentProvider(provider);
    form.setFieldsValue({
      baseUrl: provider.baseUrl,
      apiKey: provider.apiKey,
      defaultModel: provider.defaultModel,
      enabled: provider.enabled
    });
    setModalVisible(true);
    setShowApiKey(false);
    
    // 如果是 Ollama，自动获取模型列表并设置已选择的模型
    if (provider.id === 'ollama') {
      if (provider.baseUrl) {
        fetchOllamaModels(provider.baseUrl);
      }
      // 设置已保存的模型列表
      setSelectedOllamaModels(provider.models || []);
    }
    
    // 如果支持自定义模型，加载自定义模型列表
    if (provider.supportsCustomModels) {
      setCustomModels(provider.customModels || []);
    } else {
      setCustomModels([]);
    }
    
    // 重置自定义模型输入框
    setCustomModelId('');
    setCustomModelDisplayName('');
  };

  // 添加自定义模型
  const addCustomModel = () => {
    if (!customModelId.trim() || !customModelDisplayName.trim()) {
      message.warning('请输入模型ID和显示名称');
      return;
    }
    
    // 检查是否已存在相同的模型ID
    if (customModels.some(m => m.id === customModelId.trim())) {
      message.warning('该模型ID已存在');
      return;
    }
    
    const newModel: CustomModel = {
      id: customModelId.trim(),
      displayName: customModelDisplayName.trim(),
      supportsImage: customModelSupportsImage
    };
    
    setCustomModels([...customModels, newModel]);
    setCustomModelId('');
    setCustomModelDisplayName('');
    setCustomModelSupportsImage(false);
    message.success('添加成功');
  };
  
  // 删除自定义模型
  const deleteCustomModel = (modelId: string) => {
    setCustomModels(customModels.filter(m => m.id !== modelId));
    
    // 如果删除的模型是当前的默认模型，清除默认模型选择
    const currentDefaultModel = form.getFieldValue('defaultModel');
    if (currentDefaultModel === modelId) {
      form.setFieldsValue({ defaultModel: '' });
    }
    
    message.success('删除成功');
  };

  // 关闭模态框
  const closeModal = () => {
    setModalVisible(false);
    // 清除测试状态
    if (currentProvider) {
      setProviders(prev => prev.map(p => 
        p.id === currentProvider.id 
          ? { ...p, testStatus: 'idle', testMessage: undefined }
          : p
      ));
    }
    setCurrentProvider(null);
    form.resetFields();
    setShowApiKey(false);
    setSelectedOllamaModels([]); // 清除选择的 Ollama 模型
    setCustomModels([]); // 清除自定义模型
  };

  // 测试配置
  const testProvider = async () => {
    if (!currentProvider) return;

    // 清除之前的测试结果
    setCurrentProvider(prev => prev ? { ...prev, testStatus: 'testing', testMessage: undefined } : null);
    setTestingProvider(currentProvider.id);
    
    try {
      const values = await form.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      // 根据提供商类型获取模型列表
      let models: string[] = [];
      if (currentProvider.id === 'ollama') {
        models = ollamaModels.map(m => m.value);
      } else {
        models = getModelNamesFromConfig(currentProvider.id).map(m => m.value);
      }

      const testConfig = {
        id: currentProvider.id,
        name: currentProvider.name,
        base_url: values.baseUrl,
        api_key: values.apiKey,
        default_model: values.defaultModel,
        enabled: values.enabled,
        models: models
      };

      const response = await fetch(`/api/model-config/test/${currentProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(testConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        message.success(`${currentProvider.name}配置测试成功`);
        // 同时更新 providers 和 currentProvider
        const updatedStatus = { testStatus: 'success' as const, testMessage: result.message };
        setProviders(prev => prev.map(p => 
          p.id === currentProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      } else {
        message.error(`${currentProvider.name}配置测试失败`);
        // 同时更新 providers 和 currentProvider
        const updatedStatus = { testStatus: 'error' as const, testMessage: result.message };
        setProviders(prev => prev.map(p => 
          p.id === currentProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`${currentProvider.name}配置测试失败`);
      // 同时更新 providers 和 currentProvider
      const updatedStatus = { testStatus: 'error' as const, testMessage: `测试失败: ${errorMessage}` };
      setProviders(prev => prev.map(p => 
        p.id === currentProvider.id 
          ? { ...p, ...updatedStatus }
          : p
      ));
      setCurrentProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
    } finally {
      setTestingProvider(null);
    }
  };

  // 自动保存配置（Switch切换时触发）
  const autoSaveProvider = () => {
    // 等待下一个事件循环，确保Switch值已更新到表单
    setTimeout(() => {
      saveProvider();
    }, 0);
  };

  // 获取完整的模型列表（配置文件模型 + 自定义模型）
  const getFullModelList = (providerId: string): Array<{ value: string; label: string }> => {
    // Ollama 使用动态获取的模型列表
    if (providerId === 'ollama') {
      return ollamaModels;
    }
    
    // 从配置文件获取模型列表
    const configModels = getModelNamesFromConfig(providerId);
    
    // 合并自定义模型
    const customModelOptions = customModels.map(cm => ({
      value: cm.id,
      label: `${cm.displayName} (自定义)`
    }));
    
    return [...configModels, ...customModelOptions];
  };

  // 保存配置
  const saveProvider = async () => {
    if (!currentProvider) return;

    try {
      const values = await form.validateFields();
      
      // Ollama 需要验证是否选择了模型
      if (currentProvider.id === 'ollama') {
        if (selectedOllamaModels.length === 0) {
          message.warning('请至少选择一个对话模型');
          return;
        }
        // 验证默认模型是否在选择的模型列表中
        if (!selectedOllamaModels.includes(values.defaultModel)) {
          message.error('默认模型必须在选择的模型列表中，请重新选择');
          return;
        }
      }
      
      // 实际执行保存的函数
      const performSave = async () => {
        const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
        const token = authState.state?.token;

        // 根据提供商类型获取模型列表
        let models: string[] = [];
        if (currentProvider.id === 'ollama') {
          // Ollama 使用用户选择的模型，而不是全部模型
          models = selectedOllamaModels;
        } else {
          // 其他提供商使用配置文件中的模型列表
          models = getModelNamesFromConfig(currentProvider.id).map(m => m.value);
        }

        const configData = {
          id: currentProvider.id,
          name: currentProvider.name,
          base_url: values.baseUrl,
          api_key: values.apiKey,
          default_model: values.defaultModel,
          enabled: values.enabled,
          models: models,
          custom_models: currentProvider.supportsCustomModels ? customModels : undefined
        };

        const response = await fetch(`/api/model-config/user/${currentProvider.id}`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(configData)
        });

        const result = await response.json();

        if (result.success) {
          message.success(`${currentProvider.name}配置已保存`);
          
          // 更新本地状态
          setProviders(prev => prev.map(p => 
            p.id === currentProvider.id 
              ? {
                  ...p,
                  baseUrl: values.baseUrl,
                  apiKey: values.apiKey,
                  defaultModel: values.defaultModel,
                  enabled: values.enabled,
                  models: models,
                  customModels: currentProvider.supportsCustomModels ? customModels : undefined
                }
              : p
          ));
          
          closeModal();
        } else {
          message.error(`保存配置失败: ${result.message}`);
        }
      };
      
      // 检查是否正在关闭默认模型提供商
      if (!values.enabled && defaultProviderId === currentProvider.id) {
        Modal.confirm({
          title: '⚠️ 关闭默认模型提示',
          content: (
            <div>
              <p>您正在关闭 <strong>{currentProvider.name}</strong>，但它是当前的默认模型提供商。</p>
              <p>关闭后，您将无法创建新的会话。</p>
              <p>请在关闭后先切换到其他已启用的模型提供商作为默认模型。</p>
            </div>
          ),
          okText: '确认关闭',
          cancelText: '取消',
          okButtonProps: { danger: true },
          onOk: async () => {
            // 用户确认后，继续执行保存逻辑
            await performSave();
          }
        });
        return;
      }
      
      // 如果不是关闭默认模型，直接保存
      await performSave();
      
    } catch (error) {
      console.error('保存配置失败:', error);
      message.error('保存配置失败');
    }
  };

  // 打开TTS配置模态框
  const openTtsConfigModal = (provider: TtsProvider) => {
    setCurrentTtsProvider(provider);
    ttsForm.setFieldsValue({
      enabled: provider.enabled,
      ...provider.config,
      voiceType: provider.voiceSettings.voiceType
    });
    setTtsModalVisible(true);
    setVoiceGenderFilter('all');
    setVoiceSearchQuery('');
    setShowVoiceSearch(false);
    setShowTtsApiKey(false); // 重置TTS API密钥显示状态
  };

  // 关闭TTS模态框
  const closeTtsModal = () => {
    setTtsModalVisible(false);
    if (currentTtsProvider) {
      setTtsProviders(prev => prev.map(p => 
        p.id === currentTtsProvider.id 
          ? { ...p, testStatus: 'idle', testMessage: undefined }
          : p
      ));
    }
    setCurrentTtsProvider(null);
    ttsForm.resetFields();
    setVoiceGenderFilter('all');
    setVoiceSearchQuery('');
    setShowVoiceSearch(false);
    setShowTtsApiKey(false); // 重置TTS API密钥显示状态
  };

  // 测试TTS配置
  const testTtsProvider = async () => {
    if (!currentTtsProvider) return;

    setCurrentTtsProvider(prev => prev ? { ...prev, testStatus: 'testing', testMessage: undefined } : null);
    setTestingTtsProvider(currentTtsProvider.id);
    
    try {
      const values = await ttsForm.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const testConfig = {
        id: currentTtsProvider.id,
        name: currentTtsProvider.name,
        config: currentTtsProvider.id === 'xfyun' ? {
          appId: values.appId,
          apiKey: values.apiKey,
          apiSecret: values.apiSecret
        } : {
          appId: values.appId,
          token: values.token,
          cluster: values.cluster
        },
        voice_settings: {
          voiceType: values.voiceType
        },
        enabled: values.enabled
      };

      const response = await fetch(`/api/tts-config/test/${currentTtsProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(testConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        message.success(`${currentTtsProvider.name}配置测试成功`);
        const updatedStatus = { testStatus: 'success' as const, testMessage: result.message };
        setTtsProviders(prev => prev.map(p => 
          p.id === currentTtsProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentTtsProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      } else {
        message.error(`${currentTtsProvider.name}配置测试失败`);
        const updatedStatus = { testStatus: 'error' as const, testMessage: result.message };
        setTtsProviders(prev => prev.map(p => 
          p.id === currentTtsProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentTtsProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`${currentTtsProvider.name}配置测试失败`);
      const updatedStatus = { testStatus: 'error' as const, testMessage: `测试失败: ${errorMessage}` };
      setTtsProviders(prev => prev.map(p => 
        p.id === currentTtsProvider.id 
          ? { ...p, ...updatedStatus }
          : p
      ));
      setCurrentTtsProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
    } finally {
      setTestingTtsProvider(null);
    }
  };

  // 自动保存TTS配置（Switch切换时触发）
  const autoSaveTtsProvider = () => {
    // 等待下一个事件循环，确保Switch值已更新到表单
    setTimeout(() => {
      saveTtsProvider();
    }, 0);
  };

  // 保存TTS配置
  const saveTtsProvider = async () => {
    if (!currentTtsProvider) return;

    try {
      const values = await ttsForm.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const configData = {
        id: currentTtsProvider.id,
        name: currentTtsProvider.name,
        config: currentTtsProvider.id === 'xfyun' ? {
          appId: values.appId,
          apiKey: values.apiKey,
          apiSecret: values.apiSecret
        } : {
          appId: values.appId,
          token: values.token,
          cluster: values.cluster
        },
        voice_settings: {
          voiceType: values.voiceType
        },
        enabled: values.enabled
      };

      const response = await fetch(`/api/tts-config/user/${currentTtsProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(configData)
      });

      const result = await response.json();

      if (result.success) {
        message.success(`${currentTtsProvider.name}配置已保存`);
        
        // 更新本地状态
        setTtsProviders(prev => prev.map(p => 
          p.id === currentTtsProvider.id 
            ? {
                ...p,
                config: configData.config,
                voiceSettings: configData.voice_settings,
                enabled: values.enabled
              }
            : p
        ));
        
        closeTtsModal();
      } else {
        message.error(`保存配置失败: ${result.message}`);
      }
    } catch (error) {
      console.error('保存TTS配置失败:', error);
      message.error('保存TTS配置失败');
    }
  };

  // 打开Embedding配置模态框
  const openEmbeddingConfigModal = (provider: EmbeddingProvider) => {
    setCurrentEmbeddingProvider(provider);
    embeddingForm.setFieldsValue({
      enabled: provider.enabled,
      baseUrl: provider.baseUrl,
      apiKey: provider.apiKey,
      defaultModel: provider.defaultModel
    });
    setEmbeddingModalVisible(true);
    
    // 如果是 Ollama，自动拉取模型列表并设置已选择的模型
    if (provider.id === 'ollama') {
      if (provider.baseUrl) {
        fetchOllamaEmbeddingModels(provider.baseUrl);
      }
      // 设置已保存的嵌入模型列表
      setSelectedOllamaEmbeddingModels(provider.models || []);
    }
  };

  // 关闭Embedding模态框
  const closeEmbeddingModal = () => {
    setEmbeddingModalVisible(false);
    if (currentEmbeddingProvider) {
      setEmbeddingProviders(prev => prev.map(p => 
        p.id === currentEmbeddingProvider.id 
          ? { ...p, testStatus: 'idle', testMessage: undefined }
          : p
      ));
    }
    setCurrentEmbeddingProvider(null);
    embeddingForm.resetFields();
  };

  // 测试Embedding配置
  const testEmbeddingProvider = async () => {
    if (!currentEmbeddingProvider) return;

    setCurrentEmbeddingProvider(prev => prev ? { ...prev, testStatus: 'testing', testMessage: undefined } : null);
    setTestingEmbeddingProvider(currentEmbeddingProvider.id);
    
    try {
      const values = await embeddingForm.validateFields();
      
      // Ollama 需要验证
      if (currentEmbeddingProvider.id === 'ollama') {
        if (selectedOllamaEmbeddingModels.length === 0) {
          message.warning('请至少选择一个嵌入模型');
          setCurrentEmbeddingProvider(prev => prev ? { ...prev, testStatus: 'idle' } : null);
          setTestingEmbeddingProvider(null);
          return;
        }
        if (!selectedOllamaEmbeddingModels.includes(values.defaultModel)) {
          message.error('默认模型必须在选择的模型列表中');
          setCurrentEmbeddingProvider(prev => prev ? { ...prev, testStatus: 'idle' } : null);
          setTestingEmbeddingProvider(null);
          return;
        }
      }
      
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      // 对于 Ollama，使用用户选择的嵌入模型列表
      let models = currentEmbeddingProvider.models;
      if (currentEmbeddingProvider.id === 'ollama') {
        models = selectedOllamaEmbeddingModels;
      }

      const testConfig = {
        id: currentEmbeddingProvider.id,
        name: currentEmbeddingProvider.name,
        base_url: values.baseUrl,
        api_key: values.apiKey,
        default_model: values.defaultModel,
        enabled: values.enabled,
        models: models
      };

      const response = await fetch(`/api/embedding-config/test/${currentEmbeddingProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(testConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        message.success(`${currentEmbeddingProvider.name}配置测试成功`);
        const updatedStatus = { testStatus: 'success' as const, testMessage: result.message };
        setEmbeddingProviders(prev => prev.map(p => 
          p.id === currentEmbeddingProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentEmbeddingProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      } else {
        message.error(`${currentEmbeddingProvider.name}配置测试失败`);
        const updatedStatus = { testStatus: 'error' as const, testMessage: result.message };
        setEmbeddingProviders(prev => prev.map(p => 
          p.id === currentEmbeddingProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentEmbeddingProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`${currentEmbeddingProvider.name}配置测试失败`);
      const updatedStatus = { testStatus: 'error' as const, testMessage: `测试失败: ${errorMessage}` };
      setEmbeddingProviders(prev => prev.map(p => 
        p.id === currentEmbeddingProvider.id 
          ? { ...p, ...updatedStatus }
          : p
      ));
      setCurrentEmbeddingProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
    } finally {
      setTestingEmbeddingProvider(null);
    }
  };

  // 自动保存Embedding配置（Switch切换时触发）
  const autoSaveEmbeddingProvider = () => {
    setTimeout(() => {
      saveEmbeddingProvider();
    }, 0);
  };

  // 保存Embedding配置
  const saveEmbeddingProvider = async () => {
    if (!currentEmbeddingProvider) return;

    try {
      const values = await embeddingForm.validateFields();
      
      // Ollama 需要验证是否选择了模型
      if (currentEmbeddingProvider.id === 'ollama') {
        if (selectedOllamaEmbeddingModels.length === 0) {
          message.warning('请至少选择一个嵌入模型');
          return;
        }
        // 验证默认模型是否在选择的模型列表中
        if (!selectedOllamaEmbeddingModels.includes(values.defaultModel)) {
          message.error('默认模型必须在选择的模型列表中，请重新选择');
          return;
        }
      }
      
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      // 对于 Ollama，使用用户选择的嵌入模型列表
      let models = currentEmbeddingProvider.models;
      if (currentEmbeddingProvider.id === 'ollama') {
        models = selectedOllamaEmbeddingModels;
      }

      const configData = {
        id: currentEmbeddingProvider.id,
        name: currentEmbeddingProvider.name,
        base_url: values.baseUrl || '',
        api_key: values.apiKey || '',
        default_model: values.defaultModel,
        enabled: values.enabled,
        models: models
      };

      const response = await fetch(`/api/embedding-config/user/${currentEmbeddingProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(configData)
      });

      const result = await response.json();

      if (result.success) {
        message.success(`${currentEmbeddingProvider.name}配置已保存`);
        
        // 更新本地状态
        setEmbeddingProviders(prev => prev.map(p => 
          p.id === currentEmbeddingProvider.id 
            ? {
                ...p,
                baseUrl: configData.base_url,
                apiKey: configData.api_key,
                defaultModel: configData.default_model,
                enabled: values.enabled
              }
            : p
        ));
        
        closeEmbeddingModal();
      } else {
        message.error(`保存配置失败: ${result.message}`);
      }
    } catch (error) {
      console.error('保存Embedding配置失败:', error);
      message.error('保存Embedding配置失败');
    }
  };

  // 加载ASR配置
  const loadAsrConfigs = async () => {
    setLoading(true);
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/asr-config/user', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();

      if (result.success && result.configs) {
        const updatedAsrProviders = defaultAsrProviders.map(provider => {
          const userConfig = result.configs[provider.id];
          if (userConfig) {
            return {
              ...provider,
              baseUrl: userConfig.base_url || provider.baseUrl,
              apiKey: userConfig.api_key || provider.apiKey,
              defaultModel: userConfig.default_model || provider.defaultModel,
              enabled: userConfig.enabled !== undefined ? userConfig.enabled : provider.enabled,
              models: userConfig.models || provider.models
            };
          }
          return provider;
        });
        setAsrProviders(updatedAsrProviders);
      }
    } catch (error) {
      console.error('加载ASR配置失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 加载默认ASR
  const loadDefaultAsr = async () => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/asr-config/default', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success && result.provider_id) {
        setDefaultAsrProviderId(result.provider_id);
      }
    } catch (error) {
      console.error('加载默认ASR失败:', error);
    }
  };

  // 设置默认ASR
  const setDefaultAsr = async (providerId: string) => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/asr-config/default?provider_id=' + providerId, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success) {
        message.success('默认ASR服务设置成功');
        setDefaultAsrProviderId(providerId);
      } else {
        message.error('设置默认ASR服务失败: ' + result.message);
      }
    } catch (error) {
      console.error('设置默认ASR服务失败:', error);
      message.error('设置默认ASR服务失败');
    }
  };

  // 加载图片生成配置
  const handleShowImageGenerationApiKey = () => {
    if (showImageGenerationApiKey) {
      setShowImageGenerationApiKey(false);
    } else {
      setPasswordModalVisible(true);
    }
  };

  const loadImageGenerationConfigs = async () => {
    setLoading(true);
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/image-generation-config/user', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();

      if (result.success && result.configs) {
        const updatedProviders = defaultImageGenerationProviders.map(provider => {
          const userConfig = result.configs[provider.id];
          if (userConfig) {
            return {
              ...provider,
              apiKey: userConfig.api_key || provider.apiKey,
              enabled: userConfig.enabled !== undefined ? userConfig.enabled : provider.enabled,
              defaultModel: userConfig.default_model || provider.defaultModel,
              customModels: userConfig.custom_models || provider.customModels,
            };
          }
          return provider;
        });
        setImageGenerationProviders(updatedProviders);
      }
    } catch (error) {
      console.error('加载图片生成配置失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 加载默认图片生成服务
  const loadDefaultImageGeneration = async () => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/image-generation-config/default', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success && result.provider_id) {
        setDefaultImageGenerationProviderId(result.provider_id);
      }
    } catch (error) {
      console.error('加载默认图片生成服务失败:', error);
    }
  };

  // 设置默认图片生成服务
  const setDefaultImageGeneration = async (providerId: string) => {
    try {
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const response = await fetch('/api/image-generation-config/default?provider_id=' + providerId, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const result = await response.json();
      if (result.success) {
        message.success('默认图片生成服务设置成功');
        setDefaultImageGenerationProviderId(providerId);
      } else {
        message.error('设置默认图片生成服务失败: ' + result.message);
      }
    } catch (error) {
      console.error('设置默认图片生成服务失败:', error);
      message.error('设置默认图片生成服务失败');
    }
  };

  // 打开ASR配置模态框
  const openAsrConfigModal = (provider: AsrProvider) => {
    setCurrentAsrProvider(provider);
    asrForm.setFieldsValue({
      baseUrl: provider.baseUrl,
      apiKey: provider.apiKey,
      defaultModel: provider.defaultModel,
      enabled: provider.enabled
    });
    setAsrModalVisible(true);
    setShowAsrApiKey(false);
  };

  // 关闭ASR模态框
  const closeAsrModal = () => {
    setAsrModalVisible(false);
    if (currentAsrProvider) {
      setAsrProviders(prev => prev.map(p => 
        p.id === currentAsrProvider.id 
          ? { ...p, testStatus: 'idle', testMessage: undefined }
          : p
      ));
    }
    setCurrentAsrProvider(null);
    asrForm.resetFields();
    setShowAsrApiKey(false);
  };

  // 测试ASR配置
  const testAsrProvider = async () => {
    if (!currentAsrProvider) return;

    setCurrentAsrProvider(prev => prev ? { ...prev, testStatus: 'testing', testMessage: undefined } : null);
    setTestingAsrProvider(currentAsrProvider.id);
    
    try {
      const values = await asrForm.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const testConfig = {
        id: currentAsrProvider.id,
        name: currentAsrProvider.name,
        base_url: values.baseUrl,
        api_key: values.apiKey,
        default_model: values.defaultModel,
        enabled: values.enabled,
        models: currentAsrProvider.models
      };

      const response = await fetch(`/api/asr-config/test/${currentAsrProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(testConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        message.success(`${currentAsrProvider.name}配置测试成功`);
        const updatedStatus = { testStatus: 'success' as const, testMessage: result.message };
        setAsrProviders(prev => prev.map(p => 
          p.id === currentAsrProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentAsrProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      } else {
        message.error(`${currentAsrProvider.name}配置测试失败`);
        const updatedStatus = { testStatus: 'error' as const, testMessage: result.message };
        setAsrProviders(prev => prev.map(p => 
          p.id === currentAsrProvider.id 
            ? { ...p, ...updatedStatus }
            : p
        ));
        setCurrentAsrProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`${currentAsrProvider.name}配置测试失败`);
      const updatedStatus = { testStatus: 'error' as const, testMessage: `测试失败: ${errorMessage}` };
      setAsrProviders(prev => prev.map(p => 
        p.id === currentAsrProvider.id 
          ? { ...p, ...updatedStatus }
          : p
      ));
      setCurrentAsrProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
    } finally {
      setTestingAsrProvider(null);
    }
  };

  // 自动保存ASR配置（Switch切换时触发）
  const autoSaveAsrProvider = () => {
    setTimeout(() => {
      saveAsrProvider();
    }, 0);
  };

  // 保存ASR配置
  const saveAsrProvider = async () => {
    if (!currentAsrProvider) return;

    try {
      const values = await asrForm.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const configData = {
        id: currentAsrProvider.id,
        name: currentAsrProvider.name,
        base_url: values.baseUrl,
        api_key: values.apiKey,
        default_model: values.defaultModel,
        enabled: values.enabled,
        models: currentAsrProvider.models
      };

      const response = await fetch(`/api/asr-config/user/${currentAsrProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(configData)
      });

      const result = await response.json();

      if (result.success) {
        message.success(`${currentAsrProvider.name}配置已保存`);
        
        // 更新本地状态
        setAsrProviders(prev => prev.map(p => 
          p.id === currentAsrProvider.id 
            ? {
                ...p,
                baseUrl: values.baseUrl,
                apiKey: values.apiKey,
                defaultModel: values.defaultModel,
                enabled: values.enabled
              }
            : p
        ));
        
        closeAsrModal();
      } else {
        message.error(`保存配置失败: ${result.message}`);
      }
    } catch (error) {
      console.error('保存ASR配置失败:', error);
      message.error('保存ASR配置失败');
    }
  };

  // 打开图片生成配置模态框
  const openImageGenerationConfigModal = (provider: ImageGenerationProvider) => {
    setCurrentImageGenerationProvider(provider);
    imageGenerationForm.setFieldsValue({
      apiKey: provider.apiKey,
      enabled: provider.enabled,
      defaultModel: provider.defaultModel
    });
    if (provider.supportsCustomModels) {
      setCustomImageModels(provider.customModels || []);
    } else {
      setCustomImageModels([]);
    }
    setCustomImageModelId('');
    setCustomImageModelDisplayName('');
    setImageGenerationModalVisible(true);
    setShowImageGenerationApiKey(false);
  };

  // 关闭图片生成模态框
  const closeImageGenerationModal = () => {
    setImageGenerationModalVisible(false);
    if (currentImageGenerationProvider) {
      setImageGenerationProviders(prev => prev.map(p => 
        p.id === currentImageGenerationProvider.id 
          ? { ...p, testStatus: 'idle', testMessage: undefined }
          : p
      ));
    }
    setCurrentImageGenerationProvider(null);
    imageGenerationForm.resetFields();
    setShowImageGenerationApiKey(false);
    setCustomImageModels([]);
    setTestImageData(null); // 关闭时清空图片
  };

  // 打开图片生成测试的提示词输入框
  const openImageGenerationTestModal = async () => {
    try {
      // 先验证表单，确保拿到最新配置
      await imageGenerationForm.validateFields();
      setImageTestPromptModalVisible(true);
      setTestImageData(null); // 打开时清空旧图片
    } catch (error) {
      message.warning('请先完成配置项');
    }
  };

  // 执行图片生成测试
  const handleImageGenerationTest = async () => {
    if (!currentImageGenerationProvider || !testImagePrompt) return;

    setImageTestPromptModalVisible(false);
    setTestingImageGenerationProvider(currentImageGenerationProvider.id);
    setCurrentImageGenerationProvider(prev => prev ? { ...prev, testStatus: 'testing', testMessage: '正在生成图片...' } : null);

    try {
      const values = await imageGenerationForm.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const payload = {
        config: {
          id: currentImageGenerationProvider.id,
          api_key: values.apiKey,
          enabled: values.enabled,
          default_model: values.defaultModel,
          models: getFullImageModelList(currentImageGenerationProvider).map(m => m.value),
          custom_models: customImageModels
        },
        prompt: testImagePrompt
      };

      const response = await fetch(`/api/image-generation-config/test/${currentImageGenerationProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      const result = await response.json();

      if (response.ok && result.success) {
        message.success('图片生成测试成功');
        const updatedStatus = { testStatus: 'success' as const, testMessage: result.message };
        setCurrentImageGenerationProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
        setTestImageData(result.image_data);
      } else {
        const errorMessage = result.detail || '图片生成失败';
        message.error(errorMessage);
        const updatedStatus = { testStatus: 'error' as const, testMessage: errorMessage };
        setCurrentImageGenerationProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
        setTestImageData(null);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`测试请求失败: ${errorMessage}`);
      const updatedStatus = { testStatus: 'error' as const, testMessage: `请求失败: ${errorMessage}` };
      setCurrentImageGenerationProvider(prev => prev ? { ...prev, ...updatedStatus } : null);
      setTestImageData(null);
    } finally {
      setTestingImageGenerationProvider(null);
    }
  };

  // 自动保存图片生成配置（Switch切换时触发）
  const autoSaveImageGenerationProvider = () => {
    setTimeout(() => {
      saveImageGenerationProvider();
    }, 0);
  };

  // 保存图片生成配置
  const saveImageGenerationProvider = async () => {
    if (!currentImageGenerationProvider) return;

    try {
      const values = await imageGenerationForm.validateFields();
      const authState = JSON.parse(localStorage.getItem('auth-storage') || '{}');
      const token = authState.state?.token;

      const configData = {
        id: currentImageGenerationProvider.id,
        api_key: values.apiKey,
        enabled: values.enabled,
        default_model: values.defaultModel,
        models: currentImageGenerationProvider.models.map(m => m.value),
        custom_models: currentImageGenerationProvider.supportsCustomModels ? customImageModels : undefined
      };

      const response = await fetch(`/api/image-generation-config/user/${currentImageGenerationProvider.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(configData)
      });

      const result = await response.json();

      if (result.success) {
        message.success(`${currentImageGenerationProvider.name}配置已保存`);
        
        setImageGenerationProviders(prev => prev.map(p => 
          p.id === currentImageGenerationProvider.id 
            ? { 
                ...p, 
                apiKey: values.apiKey,
                enabled: values.enabled,
                defaultModel: values.defaultModel,
                customModels: currentImageGenerationProvider.supportsCustomModels ? customImageModels : undefined
              }
            : p
        ));
        
        closeImageGenerationModal();
      } else {
        message.error(`保存配置失败: ${result.message}`);
      }
    } catch (error) {
      console.error('保存图片生成配置失败:', error);
      message.error('保存图片生成配置失败');
    }
  };

  // 添加自定义图片生成模型
  const addCustomImageModel = () => {
    if (!customImageModelId.trim() || !customImageModelDisplayName.trim()) {
      message.warning('请输入模型ID和显示名称');
      return;
    }
    if (customImageModels.some(m => m.id === customImageModelId.trim())) {
      message.warning('该模型ID已存在');
      return;
    }
    const newModel: CustomModel = {
      id: customImageModelId.trim(),
      displayName: customImageModelDisplayName.trim(),
      supportsImage: false // 图片生成模型此项无意义，设为false
    };
    setCustomImageModels([...customImageModels, newModel]);
    setCustomImageModelId('');
    setCustomImageModelDisplayName('');
    message.success('添加成功');
  };

  // 删除自定义图片生成模型
  const deleteCustomImageModel = (modelId: string) => {
    setCustomImageModels(customImageModels.filter(m => m.id !== modelId));
    const currentDefaultModel = imageGenerationForm.getFieldValue('defaultModel');
    if (currentDefaultModel === modelId) {
      imageGenerationForm.setFieldsValue({ defaultModel: '' });
    }
    message.success('删除成功');
  };

  // 获取完整图片生成模型列表
  const getFullImageModelList = (provider: ImageGenerationProvider): Array<{ value: string; label: string }> => {
    if (!provider) return [];
    const configModels = provider.models || [];
    const customModelOptions = (customImageModels || []).map(cm => ({
      value: cm.id,
      label: `${cm.displayName} (自定义)`
    }));
    return [...configModels, ...customModelOptions];
  };

  // 筛选音色
  const filterVoices = (voices: any[], genderFilter: string, searchQuery: string) => {
    return voices.filter(voice => {
      const genderMatch = genderFilter === 'all' || voice.gender === genderFilter;
      const searchMatch = !searchQuery || 
        voice.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        voice.category.toLowerCase().includes(searchQuery.toLowerCase()) ||
        voice.language.toLowerCase().includes(searchQuery.toLowerCase());
      return genderMatch && searchMatch;
    });
  };

  // 渲染提供商卡片
  const renderProviderCard = (provider: ModelProvider) => {
    const isConfigured = provider.apiKey && provider.apiKey !== 'ollama';
    const statusIcon = provider.testStatus === 'success' 
      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
      : provider.testStatus === 'error'
      ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      : null;

    return (
      <Col xs={12} sm={12} md={8} lg={6} key={provider.id}>
        <Card
          hoverable
          className={styles.providerCard}
          onClick={() => openConfigModal(provider)}
          cover={
            <div className={styles.logoContainer}>
              {provider.enabled && (
                <Tag color="green" className={styles.enabledTag}>已启用</Tag>
              )}
              <img 
                alt={provider.name} 
                src={provider.logo} 
                className={styles.providerLogo}
                onError={(e) => {
                  (e.target as HTMLImageElement).src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23f0f0f0" width="100" height="100"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="40" fill="%23999"%3E%3F%3C/text%3E%3C/svg%3E';
                }}
              />
            </div>
          }
        >
          <Card.Meta
            title={
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap', flexWrap: 'nowrap' }}>
                <span>{provider.name}</span>
                {isConfigured && (
                  <span className={styles.configuredBadge}>
                    <CheckCircleOutlined /> 已配置
                  </span>
                )}
                {statusIcon}
              </div>
            }
            description={
              <Paragraph ellipsis={{ rows: 1 }} style={{ marginBottom: 8 }}>
                {provider.description}
              </Paragraph>
            }
          />
        </Card>
      </Col>
    );
  };

  // 渲染TTS提供商卡片
  const renderTtsProviderCard = (provider: TtsProvider) => {
    const isConfigured = provider.config.appId && (
      (provider.id === 'xfyun' && provider.config.apiKey && provider.config.apiSecret) ||
      (provider.id === 'bytedance' && provider.config.token && provider.config.cluster)
    );
    const statusIcon = provider.testStatus === 'success' 
      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
      : provider.testStatus === 'error'
      ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      : null;

    return (
      <Col xs={12} sm={12} md={8} lg={6} key={provider.id}>
        <Card
          hoverable
          className={styles.providerCard}
          onClick={() => openTtsConfigModal(provider)}
          cover={
            <div className={styles.logoContainer}>
              {provider.enabled && (
                <Tag color="green" className={styles.enabledTag}>已启用</Tag>
              )}
              <img 
                alt={provider.name} 
                src={provider.logo} 
                className={styles.providerLogo}
                onError={(e) => {
                  (e.target as HTMLImageElement).src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23f0f0f0" width="100" height="100"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="40" fill="%23999"%3E%3F%3C/text%3E%3C/svg%3E';
                }}
              />
            </div>
          }
        >
          <Card.Meta
            title={
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap', flexWrap: 'nowrap' }}>
                <span>{provider.name}</span>
                {isConfigured && (
                  <span className={styles.configuredBadge}>
                    <CheckCircleOutlined /> 已配置
                  </span>
                )}
                {statusIcon}
              </div>
            }
            description={
              <Paragraph ellipsis={{ rows: 1 }} style={{ marginBottom: 8 }}>
                {provider.description}
              </Paragraph>
            }
          />
        </Card>
      </Col>
    );
  };

  // 渲染Embedding提供商卡片
  const renderEmbeddingProviderCard = (provider: EmbeddingProvider) => {
    const isConfigured = 
      (provider.id === 'ark' && provider.apiKey && provider.baseUrl) ||
      (provider.id === 'ollama' && provider.baseUrl) ||
      (provider.id === 'local');
    
    const statusIcon = provider.testStatus === 'success' 
      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
      : provider.testStatus === 'error'
      ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      : null;

    return (
      <Col xs={12} sm={12} md={8} lg={6} key={provider.id}>
        <Card
          hoverable
          className={styles.providerCard}
          onClick={() => openEmbeddingConfigModal(provider)}
          cover={
            <div className={styles.logoContainer}>
              {provider.enabled && (
                <Tag color="green" className={styles.enabledTag}>已启用</Tag>
              )}
              <img 
                alt={provider.name} 
                src={provider.logo} 
                className={styles.providerLogo}
                onError={(e) => {
                  (e.target as HTMLImageElement).src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23f0f0f0" width="100" height="100"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="40" fill="%23999"%3E%3F%3C/text%3E%3C/svg%3E';
                }}
              />
            </div>
          }
        >
          <Card.Meta
            title={
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap', flexWrap: 'nowrap' }}>
                <span>{provider.name}</span>
                {isConfigured && (
                  <span className={styles.configuredBadge}>
                    <CheckCircleOutlined /> 已配置
                  </span>
                )}
                {statusIcon}
              </div>
            }
            description={
              <Paragraph ellipsis={{ rows: 1 }} style={{ marginBottom: 8 }}>
                {provider.description}
              </Paragraph>
            }
          />
        </Card>
      </Col>
    );
  };

  // 渲染图片生成提供商卡片
  const renderImageGenerationProviderCard = (provider: ImageGenerationProvider) => {
    const isConfigured = provider.apiKey;
    const statusIcon = provider.testStatus === 'success' 
      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
      : provider.testStatus === 'error'
      ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      : null;

    return (
      <Col xs={12} sm={12} md={8} lg={6} key={provider.id}>
        <Card
          hoverable
          className={styles.providerCard}
          onClick={() => openImageGenerationConfigModal(provider)}
          cover={
            <div className={styles.logoContainer}>
              {provider.enabled && (
                <Tag color="green" className={styles.enabledTag}>已启用</Tag>
              )}
              <img 
                alt={provider.name} 
                src={provider.logo} 
                className={styles.providerLogo}
                onError={(e) => {
                  (e.target as HTMLImageElement).src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23f0f0f0" width="100" height="100"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="40" fill="%23999"%3E%3F%3C/text%3E%3C/svg%3E';
                }}
              />
            </div>
          }
        >
          <Card.Meta
            title={
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap', flexWrap: 'nowrap' }}>
                <span>{provider.name}</span>
                {isConfigured && (
                  <span className={styles.configuredBadge}>
                    <CheckCircleOutlined /> 已配置
                  </span>
                )}
                {statusIcon}
              </div>
            }
            description={
              <Paragraph ellipsis={{ rows: 1 }} style={{ marginBottom: 8 }}>
                {provider.description}
              </Paragraph>
            }
          />
        </Card>
      </Col>
    );
  };

  // 渲染ASR提供商卡片
  const renderAsrProviderCard = (provider: AsrProvider) => {
    const isConfigured = provider.apiKey && provider.baseUrl;
    const statusIcon = provider.testStatus === 'success' 
      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
      : provider.testStatus === 'error'
      ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      : null;

    return (
      <Col xs={12} sm={12} md={8} lg={6} key={provider.id}>
        <Card
          hoverable
          className={styles.providerCard}
          onClick={() => openAsrConfigModal(provider)}
          cover={
            <div className={styles.logoContainer}>
              {provider.enabled && (
                <Tag color="green" className={styles.enabledTag}>已启用</Tag>
              )}
              <img 
                alt={provider.name} 
                src={provider.logo} 
                className={styles.providerLogo}
                onError={(e) => {
                  (e.target as HTMLImageElement).src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23f0f0f0" width="100" height="100"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="40" fill="%23999"%3E%3F%3C/text%3E%3C/svg%3E';
                }}
              />
            </div>
          }
        >
          <Card.Meta
            title={
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', whiteSpace: 'nowrap', flexWrap: 'nowrap' }}>
                <span>{provider.name}</span>
                {isConfigured && (
                  <span className={styles.configuredBadge}>
                    <CheckCircleOutlined /> 已配置
                  </span>
                )}
                {statusIcon}
              </div>
            }
            description={
              <Paragraph ellipsis={{ rows: 1 }} style={{ marginBottom: 8 }}>
                {provider.description}
              </Paragraph>
            }
          />
        </Card>
      </Col>
    );
  };

  // 处理返回
  const handleBack = () => {
    navigate('/chat');
  };

  return (
    <div className={styles.container}>
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={handleBack}
        className={styles.backButton}
        size={isMobile ? "middle" : "large"}
      >
        返回聊天
      </Button>
      {/* 标签页导航 */}
      <Tabs 
        activeKey={activeTab} 
        onChange={setActiveTab} 
        size={isMobile ? "middle" : "large"} 
        style={{ marginBottom: isMobile ? 8 : 16 }}
        animated={{ inkBar: true, tabPane: false }}
      >
        <TabPane 
          tab={
            <span>
              <MessageOutlined />
              <span style={{ marginLeft: 8 }}>对话模型（NLP）</span>
            </span>
          } 
          key="model"
        />
        <TabPane 
          tab={
            <span>
              <SoundOutlined />
              <span style={{ marginLeft: 8 }}>语音合成（TTS）</span>
            </span>
          } 
          key="tts"
        />
        <TabPane 
          tab={
            <span>
              <SoundOutlined />
              <span style={{ marginLeft: 8 }}>语音识别（ASR）</span>
            </span>
          } 
          key="asr"
        />
        <TabPane 
          tab={
            <span>
              <DatabaseOutlined />
              <span style={{ marginLeft: 8 }}>向量模型（Embedding）</span>
            </span>
          } 
          key="embedding"
        />
        <TabPane 
          tab={
            <span>
              <FileImageOutlined />
              <span style={{ marginLeft: 8 }}>图片生成（Text2Image）</span>
            </span>
          } 
          key="imageGeneration"
        />
      </Tabs>


      {/* 对话模型配置 */}
      {activeTab === 'model' && (
        <div className={styles.tabContent}>
          {/* 默认模型选择 */}
          <DefaultSelector
            title="新建会话时使用的默认模型："
            items={providers}
            selectedId={defaultProviderId}
            onSelect={setDefaultModel}
            isItemValid={(item) => item.enabled && !!item.apiKey}
            isMobile={isMobile}
          />

          <Spin spinning={loading} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className={styles.modelCardsContainer}>
              <Row gutter={[12, 12]}>
                {providers.map(provider => renderProviderCard(provider))}
              </Row>
            </div>
          </Spin>
        </div>
      )}

      {/* 语音模型配置 */}
      {activeTab === 'tts' && (
        <div className={styles.tabContent}>
          {/* 默认TTS选择 */}
          <DefaultSelector
            title="默认语音合成服务："
            items={ttsProviders}
            selectedId={defaultTtsProviderId}
            onSelect={setDefaultTts}
            isItemValid={(item) => item.enabled && !!item.config.appId}
            isMobile={isMobile}
          />

          <Spin spinning={loading} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className={styles.ttsCardsContainer}>
              <Row gutter={[12, 12]}>
                {ttsProviders.map(provider => renderTtsProviderCard(provider))}
              </Row>
            </div>
          </Spin>
        </div>
      )}

      {/* Embedding模型配置 */}
      {activeTab === 'embedding' && (
        <div className={styles.tabContent}>
          {/* 默认Embedding选择 */}
          <DefaultSelector
            title="默认向量模型服务："
            items={embeddingProviders}
            selectedId={defaultEmbeddingProviderId}
            onSelect={setDefaultEmbedding}
            isItemValid={(item) => {
              if (!item.enabled) return false;
              if (item.id === 'ark') return !!(item.apiKey && item.baseUrl);
              if (item.id === 'ollama') return !!item.baseUrl;
              if (item.id === 'local') return !!item.defaultModel;
              return false;
            }}
            isMobile={isMobile}
          />

          <Spin spinning={loading} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className={styles.embeddingCardsContainer}>
              <Row gutter={[12, 12]}>
                {embeddingProviders.map(provider => renderEmbeddingProviderCard(provider))}
              </Row>
            </div>
          </Spin>
        </div>
      )}

      {/* 图片生成测试的提示词输入框 */}
      <Modal
        title="图片生成测试"
        visible={imageTestPromptModalVisible}
        onOk={handleImageGenerationTest}
        onCancel={() => setImageTestPromptModalVisible(false)}
        confirmLoading={testingImageGenerationProvider !== null}
        okText="开始生成"
        cancelText="取消"
        zIndex={1050}
      >
        <p>请输入用于测试的提示词：</p>
        <Input.TextArea
          rows={4}
          value={testImagePrompt}
          onChange={(e) => setTestImagePrompt(e.target.value)}
          placeholder="例如：一条可爱的鱼"
        />
      </Modal>

      {/* ASR语音识别配置 */}
      {/* 图片生成配置 */}
      {activeTab === 'imageGeneration' && (
        <div className={styles.tabContent}>
          <DefaultSelector
            title="默认图片生成服务："
            items={imageGenerationProviders}
            selectedId={defaultImageGenerationProviderId}
            onSelect={setDefaultImageGeneration}
            isItemValid={(item) => item.enabled && !!item.apiKey}
            isMobile={isMobile}
          />

          <Spin spinning={loading} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className={styles.asrCardsContainer}> {/* 可以复用asr的样式 */}
              <Row gutter={[12, 12]}>
                {imageGenerationProviders.map(provider => renderImageGenerationProviderCard(provider))}
              </Row>
            </div>
          </Spin>
        </div>
      )}

      {activeTab === 'asr' && (
        <div className={styles.tabContent}>
          {/* 默认ASR选择 */}
          <DefaultSelector
            title="默认语音识别服务："
            items={asrProviders}
            selectedId={defaultAsrProviderId}
            onSelect={setDefaultAsr}
            isItemValid={(item) => item.enabled && !!item.apiKey && !!item.baseUrl}
            isMobile={isMobile}
          />

          <Spin spinning={loading} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className={styles.asrCardsContainer}>
              <Row gutter={[12, 12]}>
                {asrProviders.map(provider => renderAsrProviderCard(provider))}
              </Row>
            </div>
          </Spin>
        </div>
      )}

      {/* 配置模态框 */}
      <Modal
        title={
          <Space>
            <SettingOutlined />
            <span>配置 {currentProvider?.name}</span>
          </Space>
        }
        open={modalVisible}
        onCancel={closeModal}
        width={700}
        centered
        destroyOnClose
        footer={[
          <Button key="test" icon={<ExperimentOutlined />} onClick={testProvider} loading={testingProvider !== null}>
            测试连接
          </Button>,
          <Button key="cancel" onClick={closeModal}>
            取消
          </Button>,
          <Button key="save" type="primary" icon={<SaveOutlined />} onClick={saveProvider}>
            保存配置
          </Button>
        ]}
      >
        {currentProvider && (
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              baseUrl: currentProvider.baseUrl,
              apiKey: currentProvider.apiKey,
              defaultModel: currentProvider.defaultModel,
              enabled: currentProvider.enabled
            }}
          >
            <Form.Item
              label="启用此提供商"
              name="enabled"
              valuePropName="checked"
            >
              <Switch onChange={autoSaveProvider} />
            </Form.Item>

            <Form.Item
              label="API地址"
              name="baseUrl"
              rules={[{ required: true, message: '请输入API地址' }]}
              extra={currentProvider.id === 'bailian' && (
                <div style={{ marginTop: 8 }}>
                  <span style={{ marginRight: 8 }}>快速选择地域：</span>
                  <Button 
                    size="small" 
                    type="link"
                    onClick={() => {
                      form.setFieldsValue({ baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' });
                    }}
                  >
                    北京
                  </Button>
                  <Button 
                    size="small" 
                    type="link"
                    onClick={() => {
                      form.setFieldsValue({ baseUrl: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1' });
                    }}
                  >
                    新加坡
                  </Button>
                </div>
              )}
            >
              <Input 
                placeholder={currentProvider.id === 'bailian' 
                  ? 'https://dashscope.aliyuncs.com/compatible-mode/v1' 
                  : 'https://api.example.com'
                } 
                onBlur={(e) => {
                  // 如果是 Ollama，当 baseUrl 改变时重新获取模型列表
                  if (currentProvider.id === 'ollama' && e.target.value) {
                    fetchOllamaModels(e.target.value);
                  }
                }}
              />
            </Form.Item>

            <Form.Item
              labelCol={{ span: 24 }}
              label={
                <Space>
                  <div className={styles.goToGetApiKey}>
                    <div>
                      <span>API密钥</span>
                      <Button
                        type="link"
                        size="small"
                        icon={showApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowApiKey}
                      >
                        {showApiKey ? '隐藏' : '显示'}
                      </Button>
                    </div>
                    <a target="_blank" href={currentProvider?.officialWebsite}>
                      {currentProvider.id === 'ollama' ? '没有Ollama？去安装' : '没有API_Key?去创建'}
                    </a>
                  </div>
                </Space>
              }
              name="apiKey"
              rules={[{ required: currentProvider.id !== 'ollama', message: '请输入API密钥' }]}
            >
              {showApiKey ? (
                <Input placeholder="sk-..." />
              ) : (
                <Input.Password placeholder="sk-..." visibilityToggle={false} />
              )}
            </Form.Item>

            {currentProvider.id === 'ollama' && (
              <>
                <Form.Item
                  label={
                    <Space>
                      <span>选择要保存的对话模型</span>
                      <Tooltip title="从已获取的模型列表中选择要保存到配置的【对话模型】。请先选择模型列表，然后再从中选择默认模型。">
                        <QuestionCircleOutlined style={{ color: '#999' }} />
                      </Tooltip>
                    </Space>
                  }
                  required
                  rules={[{ required: true, message: '请至少选择一个模型' }]}
                >
                  <Select
                    mode="multiple"
                    placeholder="请选择要保存的对话模型（必选）"
                    value={selectedOllamaModels}
                    onChange={(value) => {
                      setSelectedOllamaModels(value);
                      // 如果当前选择的默认模型不在新选择的列表中，清除默认模型
                      const currentDefault = form.getFieldValue('defaultModel');
                      if (currentDefault && !value.includes(currentDefault)) {
                        form.setFieldsValue({ defaultModel: undefined });
                      }
                    }}
                    loading={isLoadingOllamaModels}
                    disabled={isLoadingOllamaModels || ollamaModels.length === 0}
                    allowClear
                    maxTagCount="responsive"
                    style={{ width: '100%' }}
                  >
                    {ollamaModels.map((model) => (
                      <Option key={model.value} value={model.value}>
                        {model.label}
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
                
              </>
            )}

            <Form.Item
              label="默认模型"
              name="defaultModel"
              rules={[{ required: true, message: '请选择默认模型' }]}
            >
              <Select 
                placeholder={currentProvider.id === 'ollama' ? '请先选择要保存的模型列表，然后选择默认模型' : '选择默认模型'}
                loading={currentProvider.id === 'ollama' && isLoadingOllamaModels}
                notFoundContent={
                  currentProvider.id === 'ollama' && isLoadingOllamaModels 
                    ? <Spin size="small" /> 
                    : currentProvider.id === 'ollama' && selectedOllamaModels.length === 0
                      ? '请先选择要保存的模型列表'
                      : '暂无可用模型'
                }
                disabled={currentProvider.id === 'ollama' && selectedOllamaModels.length === 0}
              >
                {currentProvider.id === 'ollama' 
                  ? ollamaModels
                      .filter(model => selectedOllamaModels.includes(model.value))
                      .map((model) => (
                        <Option key={model.value} value={model.value}>{model.label}</Option>
                      ))
                  : getFullModelList(currentProvider.id).map((model) => (
                      <Option key={model.value} value={model.value}>{model.label}</Option>
                    ))
                }
              </Select>
            </Form.Item>
            
            {/* 只在 Ollama 提供商时显示模型列表提示 */}
            {currentProvider.id === 'ollama' && (
              <Alert
                message="Ollama 模型列表"
                description={
                  isLoadingOllamaModels 
                    ? '正在获取模型列表...' 
                    : ollamaModels.length > 0 
                      ? `已找到 ${ollamaModels.length} 个模型，已选择 ${selectedOllamaModels.length} 个`
                      : '未找到模型，请确保 Ollama 服务正在运行并已下载模型'
                }
                type={ollamaModels.length > 0 ? 'success' : 'info'}
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}

            {/* 自定义模型管理 */}
            {currentProvider.supportsCustomModels && (
              <>
                <Form.Item label="自定义模型">
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {/* 已添加的自定义模型列表 */}
                    {customModels.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        {customModels.map((model) => (
                          <Tag 
                            key={model.id}
                            closable
                            onClose={() => deleteCustomModel(model.id)}
                            color="blue"
                            style={{ marginBottom: 4 }}
                          >
                            {model.displayName} ({model.id}) {model.supportsImage && '🖼️'}
                          </Tag>
                        ))}
                      </div>
                    )}
                    
                    {/* 添加自定义模型表单 - 使用折叠面板 */}
                    <Collapse
                      ghost
                      items={[
                        {
                          key: '1',
                          label: '添加自定义模型',
                          children: (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
                              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                <Input 
                                  placeholder="模型ID（如：gpt-4）"
                                  value={customModelId}
                                  onChange={(e) => setCustomModelId(e.target.value)}
                                  style={{ flex: '1 1 200px', minWidth: '150px' }}
                                />
                                <Input 
                                  placeholder="显示名称（如：GPT-4）"
                                  value={customModelDisplayName}
                                  onChange={(e) => setCustomModelDisplayName(e.target.value)}
                                  style={{ flex: '1 1 200px', minWidth: '150px' }}
                                />
                              </div>
                              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                <Select
                                  placeholder="纯文本"
                                  value={customModelSupportsImage}
                                  onChange={setCustomModelSupportsImage}
                                  style={{ flex: '1 1 150px', minWidth: '120px' }}
                                >
                                  <Option value={false}>纯文本</Option>
                                  <Option value={true}>支持图片</Option>
                                </Select>
                                <Button 
                                  type="primary"
                                  icon={<PlusOutlined />}
                                  onClick={addCustomModel}
                                  style={{ flex: '0 0 auto', minWidth: '80px' }}
                                >
                                  添加
                                </Button>
                              </div>
                              <div style={{ fontSize: '12px', color: '#999' }}>
                                添加自定义模型以支持当前提供商的其他模型
                              </div>
                            </div>
                          )
                        }
                      ]}
                    />
                  </Space>
                </Form.Item>
              </>
            )}

            {currentProvider.testStatus !== 'idle' && currentProvider.testStatus !== 'testing' && (
              <Alert
                message={
                  <span style={{ fontWeight: 'bold' }}>
                    {currentProvider.testStatus === 'success' ? '✅ 连接测试成功' : '❌ 连接测试失败'}
                  </span>
                }
                description={
                  <div style={{ 
                    whiteSpace: 'pre-wrap', 
                    wordBreak: 'break-word',
                    maxHeight: '200px',
                    overflowY: 'auto',
                    fontSize: '13px',
                    lineHeight: '1.6'
                  }}>
                    {currentProvider.testMessage}
                  </div>
                }
                type={currentProvider.testStatus === 'success' ? 'success' : 'error'}
                showIcon
                closable
                style={{ marginTop: 16 }}
                onClose={() => {
                  setCurrentProvider(prev => prev ? { ...prev, testStatus: 'idle', testMessage: undefined } : null);
                }}
              />
            )}
          </Form>
        )}
      </Modal>

      {/* TTS配置模态框 */}
      <Modal
        title={
          <Space>
            <SettingOutlined />
            <span>配置 {currentTtsProvider?.name}</span>
            <a target="_blank" href={currentTtsProvider?.officialWebsite}>没有?去创建</a>
          </Space>
        }
        open={ttsModalVisible}
        onCancel={closeTtsModal}
        width={800}
        centered
        destroyOnClose
        footer={[
          <Button key="test" icon={<ExperimentOutlined />} onClick={testTtsProvider} loading={testingTtsProvider !== null}>
            测试连接
          </Button>,
          <Button key="cancel" onClick={closeTtsModal}>
            取消
          </Button>,
          <Button key="save" type="primary" icon={<SaveOutlined />} onClick={saveTtsProvider}>
            保存配置
          </Button>
        ]}
      >
        {currentTtsProvider && (
          <Form
            form={ttsForm}
            layout="vertical"
          >
            <Form.Item
              label="启用此提供商"
              name="enabled"
              valuePropName="checked"
            >
              <Switch onChange={autoSaveTtsProvider} />
            </Form.Item>

            {/* 基础配置 */}
            {currentTtsProvider.id === 'xfyun' ? (
              <>
                <Form.Item
                  label={
                    <Space>
                      <span>
                        App ID <span style={{ color: 'red' }}>*</span>
                        <Tooltip title="在讯飞开放平台创建应用后获得的应用标识">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                      <Button
                        type="link"
                        size="small"
                        icon={showTtsApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowTtsApiKey}
                      >
                        {showTtsApiKey ? '隐藏' : '显示'}
                      </Button>
                    </Space>
                  }
                  name="appId"
                  rules={[{ required: true, message: '请输入App ID' }]}
                >
                  {showTtsApiKey ? (
                    <Input placeholder="请输入讯飞云App ID" />
                  ) : (
                    <Input.Password placeholder="请输入讯飞云App ID" visibilityToggle={false} />
                  )}
                </Form.Item>
                <Form.Item
                  label={
                    <Space>
                      <span>
                        API Key <span style={{ color: 'red' }}>*</span>
                        <Tooltip title="应用的接口密钥，用于API调用身份验证">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                      <Button
                        type="link"
                        size="small"
                        icon={showTtsApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowTtsApiKey}
                      >
                        {showTtsApiKey ? '隐藏' : '显示'}
                      </Button>
                    </Space>
                  }
                  name="apiKey"
                  rules={[{ required: true, message: '请输入API Key' }]}
                >
                  {showTtsApiKey ? (
                    <Input placeholder="请输入讯飞云API Key" />
                  ) : (
                    <Input.Password placeholder="请输入讯飞云API Key" visibilityToggle={false} />
                  )}
                </Form.Item>
                <Form.Item
                  label={
                    <Space>
                      <span>
                        API Secret <span style={{ color: 'red' }}>*</span>
                        <Tooltip title="应用的接口密码，用于签名验证">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                      <Button
                        type="link"
                        size="small"
                        icon={showTtsApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowTtsApiKey}
                      >
                        {showTtsApiKey ? '隐藏' : '显示'}
                      </Button>
                    </Space>
                  }
                  name="apiSecret"
                  rules={[{ required: true, message: '请输入API Secret' }]}
                >
                  {showTtsApiKey ? (
                    <Input placeholder="请输入讯飞云API Secret" />
                  ) : (
                    <Input.Password placeholder="请输入讯飞云API Secret" visibilityToggle={false} />
                  )}
                </Form.Item>
              </>
            ) : (
              <>
                <Form.Item
                  label={
                    <Space>
                      <span>
                        App ID <span style={{ color: 'red' }}>*</span>
                        <Tooltip title="在火山引擎控制台创建应用后获得的应用标识">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                      <Button
                        type="link"
                        size="small"
                        icon={showTtsApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowTtsApiKey}
                      >
                        {showTtsApiKey ? '隐藏' : '显示'}
                      </Button>
                    </Space>
                  }
                  name="appId"
                  rules={[{ required: true, message: '请输入App ID' }]}
                >
                  {showTtsApiKey ? (
                    <Input placeholder="请输入字节跳动App ID" />
                  ) : (
                    <Input.Password placeholder="请输入字节跳动App ID" visibilityToggle={false} />
                  )}
                </Form.Item>
                <Form.Item
                  label={
                    <Space>
                      <span>
                        Token <span style={{ color: 'red' }}>*</span>
                        <Tooltip title="访问令牌，用于身份验证">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                      <Button
                        type="link"
                        size="small"
                        icon={showTtsApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowTtsApiKey}
                      >
                        {showTtsApiKey ? '隐藏' : '显示'}
                      </Button>
                    </Space>
                  }
                  name="token"
                  rules={[{ required: true, message: '请输入Token' }]}
                >
                  {showTtsApiKey ? (
                    <Input placeholder="请输入字节跳动Token" />
                  ) : (
                    <Input.Password placeholder="请输入字节跳动Token" visibilityToggle={false} />
                  )}
                </Form.Item>
                <Form.Item
                  label={
                    <Space>
                      <span>
                        Cluster <span style={{ color: 'red' }}>*</span>
                        <Tooltip title="集群信息，指定服务区域">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                      <Button
                        type="link"
                        size="small"
                        icon={showTtsApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowTtsApiKey}
                      >
                        {showTtsApiKey ? '隐藏' : '显示'}
                      </Button>
                    </Space>
                  }
                  name="cluster"
                  rules={[{ required: true, message: '请输入Cluster' }]}
                >
                  {showTtsApiKey ? (
                    <Input placeholder="请输入集群信息" />
                  ) : (
                    <Input.Password placeholder="请输入集群信息" visibilityToggle={false} />
                  )}
                </Form.Item>
              </>
            )}

            {/* 音色设置 */}
            <Form.Item
              label="默认音色"
              name="voiceType"
              rules={[{ required: true, message: '请选择默认音色' }]}
            >
              <Input type="hidden" />
            </Form.Item>
            
            {/* 音色选择界面（使用 shouldUpdate 实现响应式更新） */}
            <Form.Item noStyle shouldUpdate={(prevValues, currentValues) => prevValues.voiceType !== currentValues.voiceType}>
              {({ getFieldValue }) => {
                const currentVoice = getFieldValue('voiceType');
                return (
                  <div style={{ marginTop: -24 }}>
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
                    <div className={styles.voiceGrid}>
                      {filterVoices(
                        currentTtsProvider.id === 'xfyun' ? xfyunVoicesData : bytedanceVoicesData,
                        voiceGenderFilter,
                        voiceSearchQuery
                      ).map((voice: any) => {
                        return (
                          <div
                            key={voice.id}
                            className={`${styles.voiceCard} ${
                              currentVoice === voice.id ? styles.selectedVoice : ''
                            }`}
                            onClick={() => {
                              ttsForm.setFieldsValue({ voiceType: voice.id });
                            }}
                          >
                            <div className={styles.voiceName}>{voice.name}</div>
                            <div className={styles.voiceTags}>
                              <span className={styles.voiceCategoryTag}>{voice.category}</span>
                              <span className={styles.voiceLanguageTag}>{voice.language}</span>
                              <span className={`${styles.voiceGenderTag} ${styles[voice.gender]}`}>
                                {voice.gender === 'male' ? '男声' : '女声'}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              }}
            </Form.Item>

            {currentTtsProvider.testStatus !== 'idle' && currentTtsProvider.testStatus !== 'testing' && (
              <Alert
                message={
                  <span style={{ fontWeight: 'bold' }}>
                    {currentTtsProvider.testStatus === 'success' ? '✅ 连接测试成功' : '❌ 连接测试失败'}
                  </span>
                }
                description={currentTtsProvider.testMessage}
                type={currentTtsProvider.testStatus === 'success' ? 'success' : 'error'}
                showIcon
                closable
                style={{ marginTop: 16 }}
                onClose={() => {
                  setCurrentTtsProvider(prev => prev ? { ...prev, testStatus: 'idle', testMessage: undefined } : null);
                }}
              />
            )}
          </Form>
        )}
      </Modal>

      {/* Embedding配置模态框 */}
      <Modal
        title={
          <Space>
            <SettingOutlined />
            <span>配置 {currentEmbeddingProvider?.name}</span>
          </Space>
        }
        open={embeddingModalVisible}
        onCancel={closeEmbeddingModal}
        width={700}
        centered
        destroyOnClose
        footer={[
          <Button key="test" icon={<ExperimentOutlined />} onClick={testEmbeddingProvider} loading={testingEmbeddingProvider !== null}>
            测试连接
          </Button>,
          <Button key="cancel" onClick={closeEmbeddingModal}>
            取消
          </Button>,
          <Button key="save" type="primary" icon={<SaveOutlined />} onClick={saveEmbeddingProvider}>
            保存配置
          </Button>
        ]}
      >
        {currentEmbeddingProvider && (
          <Form
            form={embeddingForm}
            layout="vertical"
            initialValues={{
              enabled: currentEmbeddingProvider.enabled,
              baseUrl: currentEmbeddingProvider.baseUrl,
              apiKey: currentEmbeddingProvider.apiKey,
              defaultModel: currentEmbeddingProvider.defaultModel
            }}
          >
            <Form.Item
              label="启用此提供商"
              name="enabled"
              valuePropName="checked"
            >
              <Switch onChange={autoSaveEmbeddingProvider} />
            </Form.Item>

            {/* 火山引擎配置 */}
            {currentEmbeddingProvider.id === 'ark' && (
              <>
                <Form.Item
                  label="API地址"
                  name="baseUrl"
                  rules={[{ required: true, message: '请输入API地址' }]}
                >
                  <Input placeholder="https://ark.cn-beijing.volces.com/api/v3" />
                </Form.Item>

                <Form.Item
                  labelCol={{ span: 24 }}
                  label={
                    <Space>
                      <div className={styles.goToGetApiKey}>
                        <div>
                          <span>API密钥</span>
                          <Button
                            type="link"
                            size="small"
                            icon={showEmbeddingApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                            onClick={handleShowEmbeddingApiKey}
                          >
                            {showEmbeddingApiKey ? '隐藏' : '显示'}
                          </Button>
                        </div>
                        <a target="_blank" href={currentEmbeddingProvider?.officialWebsite || 'https://console.volcengine.com/ark'}>没有API_Key?去创建</a>
                      </div>
                    </Space>
                  }
                  name="apiKey"
                  rules={[{ required: true, message: '请输入API密钥' }]}
                >
                  {showEmbeddingApiKey ? (
                    <Input placeholder="sk-..." />
                  ) : (
                    <Input.Password placeholder="sk-..." visibilityToggle={false} />
                  )}
                </Form.Item>

                <Form.Item
                  label="默认模型"
                  name="defaultModel"
                  rules={[{ required: true, message: '请选择默认模型' }]}
                >
                  <Select placeholder="选择默认模型">
                    {currentEmbeddingProvider.models.map((model) => (
                      <Option key={model} value={model}>{model}</Option>
                    ))}
                  </Select>
                </Form.Item>
              </>
            )}

            {/* Ollama 配置 */}
            {currentEmbeddingProvider.id === 'ollama' && (
              <>
                <Form.Item
                  label="API地址"
                  name="baseUrl"
                  rules={[{ required: true, message: '请输入Ollama服务地址' }]}
                >
                  <Input 
                    placeholder="http://localhost:11434"
                    onBlur={(e) => {
                      if (currentEmbeddingProvider.id === 'ollama' && e.target.value) {
                        fetchOllamaEmbeddingModels(e.target.value);
                      }
                    }}
                  />
                </Form.Item>
                <Form.Item
                  label={
                    <Space>
                      <span>选择要保存的嵌入模型</span>
                      <Tooltip title="从已获取的模型列表中选择要保存到配置的【嵌入模型】。请先选择模型列表，然后再从中选择默认模型。">
                        <QuestionCircleOutlined style={{ color: '#999' }} />
                      </Tooltip>
                    </Space>
                  }
                  required
                  rules={[{ required: true, message: '请至少选择一个模型' }]}
                >
                  <Select
                    mode="multiple"
                    placeholder="请选择要保存的嵌入模型（必选）"
                    value={selectedOllamaEmbeddingModels}
                    onChange={(value) => {
                      setSelectedOllamaEmbeddingModels(value);
                      // 如果当前选择的默认模型不在新选择的列表中，清除默认模型
                      const currentDefault = embeddingForm.getFieldValue('defaultModel');
                      if (currentDefault && !value.includes(currentDefault)) {
                        embeddingForm.setFieldsValue({ defaultModel: undefined });
                      }
                    }}
                    loading={isLoadingOllamaEmbeddingModels}
                    disabled={isLoadingOllamaEmbeddingModels || ollamaEmbeddingModels.length === 0}
                    allowClear
                    maxTagCount="responsive"
                    style={{ width: '100%' }}
                  >
                    {ollamaEmbeddingModels.map((model) => (
                      <Option key={model.value} value={model.value}>
                        {model.label}
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
                
                <Form.Item
                  label="默认模型"
                  name="defaultModel"
                  rules={[{ required: true, message: '请选择默认模型' }]}
                >
                  <Select 
                    placeholder="请先选择要保存的模型列表，然后选择默认模型"
                    loading={isLoadingOllamaEmbeddingModels}
                    notFoundContent={
                      isLoadingOllamaEmbeddingModels 
                        ? <Spin size="small" /> 
                        : selectedOllamaEmbeddingModels.length === 0
                          ? '请先选择要保存的模型列表'
                          : '暂无可用模型'
                    }
                    disabled={selectedOllamaEmbeddingModels.length === 0}
                  >
                    {ollamaEmbeddingModels
                      .filter(model => selectedOllamaEmbeddingModels.includes(model.value))
                      .map((model) => (
                        <Option key={model.value} value={model.value}>{model.label}</Option>
                      ))
                    }
                  </Select>
                </Form.Item>
                <Alert
                  message="Ollama 嵌入模型列表"
                  description={
                    isLoadingOllamaEmbeddingModels 
                      ? '正在获取模型列表...' 
                      : ollamaEmbeddingModels.length > 0 
                        ? `已找到 ${ollamaEmbeddingModels.length} 个模型，已选择 ${selectedOllamaEmbeddingModels.length} 个`
                        : '未找到模型，请确保 Ollama 服务正在运行并已下载模型'
                  }
                  type={ollamaEmbeddingModels.length > 0 ? 'success' : 'info'}
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              </>
            )}

            {/* 本地模型配置 */}
            {currentEmbeddingProvider.id === 'local' && (
              <>
                <Alert
                  message="本地模型配置"
                  description="模型文件存放在项目目录：checkpoints/embeddings/{模型名称}"
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
                <Form.Item
                  label="模型名称"
                  name="defaultModel"
                  rules={[{ required: true, message: '请输入或选择模型名称' }]}
                >
                  <Select 
                    placeholder="输入或选择模型名称" 
                    mode="tags"
                    maxTagCount={1}
                    dropdownStyle={{ display: currentEmbeddingProvider.models.length > 0 ? 'block' : 'none' }}
                  >
                    {currentEmbeddingProvider.models.map((model) => (
                      <Option key={model} value={model}>{model}</Option>
                    ))}
                  </Select>
                </Form.Item>
              </>
            )}

            {currentEmbeddingProvider.testStatus !== 'idle' && currentEmbeddingProvider.testStatus !== 'testing' && (
              <Alert
                message={
                  <span style={{ fontWeight: 'bold' }}>
                    {currentEmbeddingProvider.testStatus === 'success' ? '✅ 连接测试成功' : '❌ 连接测试失败'}
                  </span>
                }
                description={
                  <div style={{ 
                    whiteSpace: 'pre-wrap', 
                    wordBreak: 'break-word',
                    maxHeight: '200px',
                    overflowY: 'auto',
                    fontSize: '13px',
                    lineHeight: '1.6'
                  }}>
                    {currentEmbeddingProvider.testMessage}
                  </div>
                }
                type={currentEmbeddingProvider.testStatus === 'success' ? 'success' : 'error'}
                showIcon
                closable
                style={{ marginTop: 16 }}
                onClose={() => {
                  setCurrentEmbeddingProvider(prev => prev ? { ...prev, testStatus: 'idle', testMessage: undefined } : null);
                }}
              />
            )}
          </Form>
        )}
      </Modal>

      {/* ASR配置模态框 */}
      <Modal
        title={
          <Space>
            <SettingOutlined />
            <span>配置 {currentAsrProvider?.name}</span>
          </Space>
        }
        open={asrModalVisible}
        onCancel={closeAsrModal}
        width={700}
        centered
        destroyOnClose
        footer={[
          <Button key="test" icon={<ExperimentOutlined />} onClick={testAsrProvider} loading={testingAsrProvider !== null}>
            测试连接
          </Button>,
          <Button key="cancel" onClick={closeAsrModal}>
            取消
          </Button>,
          <Button key="save" type="primary" icon={<SaveOutlined />} onClick={saveAsrProvider}>
            保存配置
          </Button>
        ]}
      >
        {currentAsrProvider && (
          <Form
            form={asrForm}
            layout="vertical"
            initialValues={{
              baseUrl: currentAsrProvider.baseUrl,
              apiKey: currentAsrProvider.apiKey,
              defaultModel: currentAsrProvider.defaultModel,
              enabled: currentAsrProvider.enabled
            }}
          >
            <Form.Item
              label="启用此提供商"
              name="enabled"
              valuePropName="checked"
            >
              <Switch onChange={autoSaveAsrProvider} />
            </Form.Item>

            <Form.Item
              label="API地址"
              name="baseUrl"
              rules={[{ required: true, message: '请输入API地址' }]}
            >
              <Input placeholder="https://api.siliconflow.cn/v1/audio/transcriptions" />
            </Form.Item>

            <Form.Item
              labelCol={{ span: 24 }}
              label={
                <Space>
                  <div className={styles.goToGetApiKey}>
                    <div>
                      <span>API密钥</span>
                      <Button
                        type="link"
                        size="small"
                        icon={showAsrApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowAsrApiKey}
                      >
                        {showAsrApiKey ? '隐藏' : '显示'}
                      </Button>
                    </div>
                    <a target="_blank" href={currentAsrProvider?.officialWebsite}>没有API_Key?去创建</a>
                  </div>
                </Space>
              }
              name="apiKey"
              rules={[{ required: true, message: '请输入API密钥' }]}
            >
              {showAsrApiKey ? (
                <Input placeholder="sk-..." />
              ) : (
                <Input.Password placeholder="sk-..." visibilityToggle={false} />
              )}
            </Form.Item>

            <Form.Item
              label="默认模型"
              name="defaultModel"
              rules={[{ required: true, message: '请选择默认模型' }]}
            >
              <Select placeholder="选择默认ASR模型">
                {currentAsrProvider.models.map((model) => (
                  <Option key={model} value={model}>{model}</Option>
                ))}
              </Select>
            </Form.Item>

            {currentAsrProvider.testStatus !== 'idle' && currentAsrProvider.testStatus !== 'testing' && (
              <Alert
                message={
                  <span style={{ fontWeight: 'bold' }}>
                    {currentAsrProvider.testStatus === 'success' ? '✅ 连接测试成功' : '❌ 连接测试失败'}
                  </span>
                }
                description={
                  <div style={{ 
                    whiteSpace: 'pre-wrap', 
                    wordBreak: 'break-word',
                    maxHeight: '200px',
                    overflowY: 'auto',
                    fontSize: '13px',
                    lineHeight: '1.6'
                  }}>
                    {currentAsrProvider.testMessage}
                  </div>
                }
                type={currentAsrProvider.testStatus === 'success' ? 'success' : 'error'}
                showIcon
                closable
                style={{ marginTop: 16 }}
                onClose={() => {
                  setCurrentAsrProvider(prev => prev ? { ...prev, testStatus: 'idle', testMessage: undefined } : null);
                }}
              />
            )}
          </Form>
        )}
      </Modal>

      {/* 密码验证弹窗 */}
      <Modal
        title="安全验证"
        open={passwordModalVisible}
        onOk={handlePasswordSubmit}
        onCancel={() => {
          setPasswordModalVisible(false);
          passwordForm.resetFields();
        }}
        confirmLoading={verifyingPassword}
        okText="验证"
        cancelText="取消"
        width={400}
        centered
        zIndex={2000}
        maskClosable={false}
        destroyOnClose
      >
        <Alert
          message="为了保护您的 API 密钥安全，请输入您的账号密码进行验证"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Form
          form={passwordForm}
          layout="vertical"
        >
          <Form.Item
            label="账号密码"
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password 
              placeholder="请输入您的账号密码"
              onPressEnter={handlePasswordSubmit}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 图片生成配置模态框 */}
      <Modal
        title={
          <Space>
            <SettingOutlined />
            <span>配置 {currentImageGenerationProvider?.name}</span>
          </Space>
        }
        open={imageGenerationModalVisible}
        onCancel={closeImageGenerationModal}
        width={700}
        centered
        destroyOnClose
        footer={[
          <Button
            key="test"
            icon={<ExperimentOutlined />}
            onClick={openImageGenerationTestModal}
            loading={testingImageGenerationProvider === currentImageGenerationProvider?.id}
          >
            测试连接
          </Button>,
          <Button key="cancel" onClick={closeImageGenerationModal}>
            取消
          </Button>,
          <Button key="save" type="primary" icon={<SaveOutlined />} onClick={saveImageGenerationProvider}>
            保存配置
          </Button>
        ]}
      >
        {currentImageGenerationProvider && (
          <Form
            form={imageGenerationForm}
            layout="vertical"
            initialValues={{
              apiKey: currentImageGenerationProvider.apiKey,
              enabled: currentImageGenerationProvider.enabled,
              defaultModel: currentImageGenerationProvider.defaultModel
            }}
          >
            <Form.Item
              label="启用此提供商"
              name="enabled"
              valuePropName="checked"
            >
              <Switch onChange={autoSaveImageGenerationProvider} />
            </Form.Item>

            <Form.Item
              labelCol={{ span: 24 }}
              label={
                <Space>
                  <div className={styles.goToGetApiKey}>
                    <div>
                      <span>API密钥</span>
                      <Button
                        type="link"
                        size="small"
                        icon={showImageGenerationApiKey ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={handleShowImageGenerationApiKey}
                      >
                        {showImageGenerationApiKey ? '隐藏' : '显示'}
                      </Button>
                    </div>
                    <a target="_blank" href={currentImageGenerationProvider?.officialWebsite}>没有API_Key?去创建</a>
                  </div>
                </Space>
              }
              name="apiKey"
              rules={[{ required: true, message: '请输入API密钥' }]}
            >
              {showImageGenerationApiKey ? (
                <Input placeholder="sk-..." />
              ) : (
                <Input.Password placeholder="sk-..." visibilityToggle={false} />
              )}
            </Form.Item>

            <Form.Item
              label="默认模型"
              name="defaultModel"
              rules={[{ required: true, message: '请选择默认模型' }]}
            >
              <Select placeholder="选择默认模型">
                {getFullImageModelList(currentImageGenerationProvider).map((model) => (
                  <Option key={model.value} value={model.value}>{model.label}</Option>
                ))}
              </Select>
            </Form.Item>

            {currentImageGenerationProvider.supportsCustomModels && (
              <Form.Item label="自定义模型">
                <Space direction="vertical" style={{ width: '100%' }}>
                  {customImageModels.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      {customImageModels.map((model) => (
                        <Tag 
                          key={model.id}
                          closable
                          onClose={() => deleteCustomImageModel(model.id)}
                          color="blue"
                          style={{ marginBottom: 4 }}
                        >
                          {model.displayName} ({model.id})
                        </Tag>
                      ))}
                    </div>
                  )}
                  <Collapse
                    ghost
                    items={[
                      {
                        key: '1',
                        label: '添加自定义模型',
                        children: (
                          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                            <Input 
                              placeholder="模型ID"
                              value={customImageModelId}
                              onChange={(e) => setCustomImageModelId(e.target.value)}
                              style={{ flex: '1 1 200px', minWidth: '150px' }}
                            />
                            <Input 
                              placeholder="显示名称"
                              value={customImageModelDisplayName}
                              onChange={(e) => setCustomImageModelDisplayName(e.target.value)}
                              style={{ flex: '1 1 200px', minWidth: '150px' }}
                            />
                            <Button 
                              type="primary"
                              icon={<PlusOutlined />}
                              onClick={addCustomImageModel}
                              style={{ flex: '0 0 auto', minWidth: '80px' }}
                            >
                              添加
                            </Button>
                          </div>
                        )
                      }
                    ]}
                  />
                </Space>
              </Form.Item>
            )}

            {currentImageGenerationProvider.testStatus !== 'idle' && currentImageGenerationProvider.testStatus !== 'testing' && (
              <Alert
                message={
                  <span style={{ fontWeight: 'bold' }}>
                    {currentImageGenerationProvider.testStatus === 'success' ? '✅ 连接测试成功' : '❌ 连接测试失败'}
                  </span>
                }
                description={
                  <div style={{ 
                    whiteSpace: 'pre-wrap', 
                    wordBreak: 'break-all',
                    maxHeight: '250px',
                    overflowY: 'auto'
                  }}>
                    {currentImageGenerationProvider.testMessage}
                    {currentImageGenerationProvider.testStatus === 'success' && testImageData && (
                      <div style={{ marginTop: 8 }}>
                        <Image width={200} src={testImageData} alt="Generated Image" />
                      </div>
                    )}
                  </div>
                }
                type={currentImageGenerationProvider.testStatus === 'success' ? 'success' : 'error'}
                style={{ marginTop: 16 }}
              />
            )}
          </Form>
        )}
      </Modal>
    </div>
  );
};

export default ModelConfig;