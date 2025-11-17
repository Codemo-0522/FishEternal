import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Button, Input, Tag, message, Modal, InputNumber, Tabs, Table, Tooltip, Space } from 'antd';
import { 
  SearchOutlined, 
  DownloadOutlined, 
  InfoCircleOutlined,
  LeftOutlined,
  DatabaseOutlined,
  UserOutlined,
  FileTextOutlined,
  ThunderboltOutlined
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useThemeStore } from '../../stores/themeStore';
import { useAuthStore } from '../../stores/authStore';
import styles from './KBMarketplace.module.css';
import * as kbMarketplaceApi from '../../api/kbMarketplace';

const { TabPane } = Tabs;

interface SharedKnowledgeBase {
  id: string;
  original_kb_id: string;
  owner_id: string;
  owner_account: string;
  name: string;
  description?: string;
  collection_name: string;
  vector_db: string;
  embedding_provider: string;
  embedding_model: string;
  chunk_size: number;
  chunk_overlap: number;
  separators: string[];
  distance_metric: string;  // 距离度量方式
  similarity_threshold: number;
  top_k: number;
  document_count: number;
  chunk_count: number;
  pull_count: number;
  shared_at: string;
  updated_at: string;
  is_owner?: boolean;
}

interface PulledKnowledgeBase {
  id: string;
  user_id: string;
  shared_kb_id: string;
  original_kb_id: string;
  owner_id: string;
  owner_account: string;
  name: string;
  description?: string;
  collection_name: string;
  vector_db: string;
  embedding_config: any;
  split_params: any;
  distance_metric: string;  // 距离度量方式
  similarity_threshold: number;
  top_k: number;
  pulled_at: string;
  updated_at: string;
  enabled: boolean;
  document_count?: number;
  chunk_count?: number;
}

const KBMarketplace: React.FC = () => {
  const navigate = useNavigate();
  const { theme } = useThemeStore();
  const token = useAuthStore((state) => state.token);
  const [activeTab, setActiveTab] = useState<string>('marketplace');
  
  // 知识库广场状态
  const [sharedKBs, setSharedKBs] = useState<SharedKnowledgeBase[]>([]);
  const [filteredKBs, setFilteredKBs] = useState<SharedKnowledgeBase[]>([]);
  const [searchText, setSearchText] = useState('');
  const [loadingMarketplace, setLoadingMarketplace] = useState(false);
  
  // 已拉取知识库状态
  const [pulledKBs, setPulledKBs] = useState<PulledKnowledgeBase[]>([]);
  const [loadingPulled, setLoadingPulled] = useState(false);
  
  // 拉取配置弹窗
  const [pullModalVisible, setPullModalVisible] = useState(false);
  const [selectedKB, setSelectedKB] = useState<SharedKnowledgeBase | null>(null);
  const [pullConfig, setPullConfig] = useState({
    // ❌ 移除：拉取的知识库必须使用原知识库的 distance_metric
    // distance_metric: 'cosine',
    similarity_threshold: 0.5,
    top_k: 5
  });

  // 详情弹窗
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [detailKB, setDetailKB] = useState<SharedKnowledgeBase | PulledKnowledgeBase | null>(null);

  // 防抖更新的定时器引用
  const updateTimerRef = useRef<{ [key: string]: NodeJS.Timeout }>({});

  // 加载知识库广场
  const loadSharedKBs = async () => {
    if (!token) {
      message.error('未登录');
      return;
    }
    setLoadingMarketplace(true);
    try {
      const response = await kbMarketplaceApi.listSharedKnowledgeBases(token, 0, 100);
      console.log('知识库广场数据:', response);
      const data = response.items || [];
      setSharedKBs(data);
      setFilteredKBs(data);
    } catch (error: any) {
      console.error('加载知识库广场失败:', error);
      message.error(error.message || '加载知识库广场失败');
    } finally {
      setLoadingMarketplace(false);
    }
  };

  // 加载已拉取的知识库
  const loadPulledKBs = async () => {
    if (!token) {
      message.error('未登录');
      return;
    }
    setLoadingPulled(true);
    try {
      const response = await kbMarketplaceApi.listPulledKnowledgeBases(token, 0, 100);
      console.log('已拉取知识库数据:', response);
      const data = response.items || [];
      setPulledKBs(data);
    } catch (error: any) {
      console.error('加载已拉取知识库失败:', error);
      message.error(error.message || '加载已拉取知识库失败');
    } finally {
      setLoadingPulled(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'marketplace') {
      loadSharedKBs();
    } else if (activeTab === 'pulled') {
      loadPulledKBs();
    }
  }, [activeTab]);

  // 组件卸载时清理所有防抖定时器
  useEffect(() => {
    return () => {
      Object.values(updateTimerRef.current).forEach(timer => {
        clearTimeout(timer);
      });
    };
  }, []);

  // 搜索过滤
  const handleSearch = (value: string) => {
    setSearchText(value);
    if (!value.trim()) {
      setFilteredKBs(sharedKBs);
      return;
    }
    
    const filtered = sharedKBs.filter(kb => 
      kb.name.toLowerCase().includes(value.toLowerCase()) ||
      (kb.description && kb.description.toLowerCase().includes(value.toLowerCase())) ||
      kb.owner_account?.toLowerCase().includes(value.toLowerCase())
    );
    setFilteredKBs(filtered);
  };

  // 打开拉取配置弹窗
  const handlePullClick = (kb: SharedKnowledgeBase) => {
    setSelectedKB(kb);
    setPullConfig({
      // ❌ 移除：拉取的知识库必须使用原知识库的 distance_metric，不允许自定义
      similarity_threshold: kb.similarity_threshold,
      top_k: kb.top_k
    });
    setPullModalVisible(true);
  };

  // 执行拉取
  const handlePullConfirm = async () => {
    if (!selectedKB || !token) return;
    
    try {
      // 1. 获取用户的嵌入模型配置
      const embeddingResponse = await fetch('/api/embedding-config/user', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (!embeddingResponse.ok) {
        message.error('无法获取嵌入模型配置，请先配置嵌入模型');
        return;
      }

      const embeddingResult = await embeddingResponse.json();
      if (!embeddingResult.success || !embeddingResult.configs) {
        message.error('获取嵌入模型配置失败');
        return;
      }

      // 2. 检查是否有匹配的嵌入模型配置
      const requiredProvider = selectedKB.embedding_provider;
      const requiredModel = selectedKB.embedding_model;
      
      const userConfig = embeddingResult.configs[requiredProvider];
      if (!userConfig || !userConfig.enabled) {
        message.error(`您还没有配置 ${requiredProvider} 嵌入模型，请先在模型配置页面进行配置`);
        return;
      }

      // 检查模型是否可用
      if (!userConfig.models || !userConfig.models.includes(requiredModel)) {
        message.warning(`您的 ${requiredProvider} 配置中没有 ${requiredModel} 模型，将使用默认模型 ${userConfig.default_model}`);
      }

      // 3. 构造嵌入模型配置
      const embeddingConfig = {
        provider: requiredProvider,
        model: userConfig.models && userConfig.models.includes(requiredModel) ? requiredModel : userConfig.default_model,
        base_url: userConfig.base_url,
        api_key: userConfig.api_key
      };

      // 4. 执行拉取
      await kbMarketplaceApi.pullKnowledgeBase(
        token,
        selectedKB.id,
        embeddingConfig,
        'cosine',  // ⚠️ 此参数已废弃，后端会忽略并使用原知识库的 distance_metric
        pullConfig.similarity_threshold,
        pullConfig.top_k
      );
      
      message.success('拉取成功！');
      setPullModalVisible(false);
      setSelectedKB(null);
      // 刷新已拉取列表
      if (activeTab === 'pulled') {
        loadPulledKBs();
      }
    } catch (error: any) {
      console.error('拉取失败:', error);
      message.error(error.message || '拉取失败');
    }
  };

  // 更新已拉取知识库配置（带3秒防抖）
  const handleUpdatePulledKB = useCallback((id: string, updates: any) => {
    if (!token) return;
    
    // 清除该知识库之前的定时器
    if (updateTimerRef.current[id]) {
      clearTimeout(updateTimerRef.current[id]);
    }
    
    // 显示等待提示
    message.info('修改将在3秒后自动保存...', 1);
    
    // 设置新的定时器，3秒后执行更新
    updateTimerRef.current[id] = setTimeout(async () => {
      try {
        await kbMarketplaceApi.updatePulledKnowledgeBase(token, id, updates);
        message.success('更新成功');
        loadPulledKBs();
      } catch (error: any) {
        console.error('更新失败:', error);
        message.error(error.message || '更新失败');
      }
      
      // 清理已完成的定时器引用
      delete updateTimerRef.current[id];
    }, 3000); // 3秒防抖
  }, [token]);

  // 取消拉取（删除）
  const handleCancelPull = async (id: string) => {
    if (!token) return;
    Modal.confirm({
      title: '确认取消拉取',
      content: '取消后该知识库将从列表中移除',
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await kbMarketplaceApi.deletePulledKnowledgeBase(token, id);
          message.success('已取消拉取');
          loadPulledKBs();
        } catch (error: any) {
          console.error('操作失败:', error);
          message.error(error.message || '操作失败');
        }
      }
    });
  };

  // 显示详情
  const handleShowDetail = (kb: SharedKnowledgeBase | PulledKnowledgeBase) => {
    setDetailKB(kb);
    setDetailModalVisible(true);
  };

  // 知识库广场列的定义
  const marketplaceColumns = [
    {
      title: '知识库名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: SharedKnowledgeBase) => (
        <div>
          <div className={styles.kbName}>{text}</div>
          <div className={styles.kbDesc}>{record.description || '暂无描述'}</div>
        </div>
      )
    },
    {
      title: '创作者',
      dataIndex: 'owner_account',
      key: 'owner_account',
      width: 120,
      render: (text: string) => (
        <div className={styles.ownerCell}>
          <UserOutlined className={styles.ownerIcon} />
          <span>{text || '未知'}</span>
        </div>
      )
    },
    {
      title: '统计',
      key: 'stats',
      width: 150,
      render: (_: any, record: SharedKnowledgeBase) => (
        <div className={styles.statsCell}>
          <div className={styles.statItem}>
            <FileTextOutlined className={styles.statIcon} />
            <span>{record.document_count} 文档</span>
          </div>
          <div className={styles.statItem}>
            <ThunderboltOutlined className={styles.statIcon} />
            <span>{record.chunk_count} 分片</span>
          </div>
        </div>
      )
    },
    {
      title: '向量模型',
      key: 'embedding_model',
      width: 150,
      render: (_: any, record: SharedKnowledgeBase) => (
        <Tag color="blue">{record.embedding_provider}/{record.embedding_model}</Tag>
      )
    },
    {
      title: '分享时间',
      dataIndex: 'shared_at',
      key: 'shared_at',
      width: 100,
      render: (text: string) => new Date(text).toLocaleDateString()
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: any, record: SharedKnowledgeBase) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<InfoCircleOutlined />}
            onClick={() => handleShowDetail(record)}
          >
            详情
          </Button>
          <Button
            type="primary"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handlePullClick(record)}
          >
            拉取
          </Button>
        </Space>
      )
    }
  ];

  // 已拉取知识库列的定义
  const pulledColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: PulledKnowledgeBase) => (
        <div>
          <div className={styles.kbName}>{text}</div>
          <div className={styles.kbDesc}>{record.description || '暂无描述'}</div>
        </div>
      )
    },
    {
      title: '原作者',
      dataIndex: 'owner_account',
      key: 'owner_account',
      width: 120,
      render: (text: string) => (
        <div className={styles.ownerCell}>
          <UserOutlined className={styles.ownerIcon} />
          <span>{text || '未知'}</span>
        </div>
      )
    },
    {
      title: '相似度阈值',
      dataIndex: 'similarity_threshold',
      key: 'similarity_threshold',
      width: 150,
      render: (value: number, record: PulledKnowledgeBase) => {
        // 后端已统一转换为0-1的相似度分数（1=最相似）
        return (
          <InputNumber
            min={0}
            max={1}
            step={0.05}
            value={value}
            size="small"
            onChange={(newValue) => {
              if (newValue !== null) {
                handleUpdatePulledKB(record.id, { similarity_threshold: newValue });
              }
            }}
            className={styles.inputNumber}
          />
        );
      }
    },
    {
      title: 'Top K',
      dataIndex: 'top_k',
      key: 'top_k',
      width: 120,
      render: (value: number, record: PulledKnowledgeBase) => (
        <InputNumber
          min={1}
          max={20}
          value={value}
          size="small"
          onChange={(newValue) => {
            if (newValue !== null) {
              handleUpdatePulledKB(record.id, { top_k: newValue });
            }
          }}
          className={styles.inputNumber}
        />
      )
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (value: boolean) => (
        <Tag color={value ? 'green' : 'default'}>
          {value ? '启用' : '禁用'}
        </Tag>
      )
    },
    {
      title: '拉取时间',
      dataIndex: 'pulled_at',
      key: 'pulled_at',
      width: 100,
      render: (text: string) => new Date(text).toLocaleDateString()
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: any, record: PulledKnowledgeBase) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<InfoCircleOutlined />}
            onClick={() => handleShowDetail(record)}
          >
            详情
          </Button>
          <Button
            type="link"
            danger
            size="small"
            onClick={() => handleCancelPull(record.id)}
          >
            取消拉取
          </Button>
        </Space>
      )
    }
  ];

  return (
    <div className={`${styles.container} ${theme === 'dark' ? styles.dark : styles.light}`}>
      {/* 顶部栏 */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Button
            type="text"
            icon={<LeftOutlined />}
            onClick={() => navigate(-1)}
            className={styles.backButton}
          >
            返回
          </Button>
        </div>
        <div className={styles.headerTitle}>
          <DatabaseOutlined className={styles.titleIcon} />
          <span>知识库广场</span>
        </div>
        <div className={styles.headerRight}></div>
      </div>

      {/* Tab导航 */}
      <div className={styles.content}>
        <Tabs 
          activeKey={activeTab} 
          onChange={setActiveTab}
          className={styles.tabs}
        >
          <TabPane tab="知识库广场" key="marketplace">
            <div className={styles.tabContent}>
              {/* 搜索栏 */}
              <div className={styles.searchBar}>
                <Input
                  placeholder="搜索知识库名称、描述或作者..."
                  prefix={<SearchOutlined />}
                  value={searchText}
                  onChange={(e) => handleSearch(e.target.value)}
                  allowClear
                  size="large"
                  className={styles.searchInput}
                />
              </div>

              {/* 知识库列表 */}
              <Table
                columns={marketplaceColumns}
                dataSource={filteredKBs}
                rowKey="id"
                loading={loadingMarketplace}
                pagination={{
                  pageSize: 10,
                  showTotal: (total) => `共 ${total} 个知识库`
                }}
                className={styles.table}
              />
            </div>
          </TabPane>

          <TabPane tab="已拉取知识库" key="pulled">
            <div className={styles.tabContent}>
              <div className={styles.pullTip}>
                <InfoCircleOutlined />
                <span>管理从广场拉取的知识库，可以调整检索参数</span>
              </div>

              <Table
                columns={pulledColumns}
                dataSource={pulledKBs}
                rowKey="id"
                loading={loadingPulled}
                pagination={{
                  pageSize: 10,
                  showTotal: (total) => `共 ${total} 个已拉取知识库`
                }}
                className={styles.table}
              />
            </div>
          </TabPane>
        </Tabs>
      </div>

      {/* 拉取配置弹窗 */}
      <Modal
        title="配置拉取参数"
        open={pullModalVisible}
        onOk={handlePullConfirm}
        onCancel={() => {
          setPullModalVisible(false);
          setSelectedKB(null);
        }}
        okText="确认拉取"
        cancelText="取消"
        className={theme === 'dark' ? 'dark-modal' : ''}
      >
        {selectedKB && (
          <div className={styles.pullModal}>
            <div className={styles.modalSection}>
              <h4>{selectedKB.name}</h4>
              <p className={styles.modalDesc}>{selectedKB.description}</p>
            </div>

            {/* ✅ 说明：距离度量方式不可自定义 */}
            <div style={{ 
              padding: '12px', 
              background: '#e6f7ff', 
              border: '1px solid #91d5ff', 
              borderRadius: '4px',
              marginBottom: '16px'
            }}>
              <InfoCircleOutlined style={{ color: '#1890ff', marginRight: '8px' }} />
              <span style={{ color: '#0050b3' }}>
                拉取的知识库将使用原知识库的距离度量方式（
                {selectedKB?.distance_metric === 'cosine' ? '余弦距离-文本语义' : 
                 selectedKB?.distance_metric === 'l2' ? 'L2距离-图像精确' : 
                 '内积-归一化向量'}），因为向量索引已经用该度量方式构建。
              </span>
            </div>

            <div className={styles.modalSection}>
              <div className={styles.configItem}>
                <label>
                  相似度阈值
                  <Tooltip title="后端已统一转换为0-1的相似度分数（1=最相似）。数值越大=只要最相关的结果；数值越小=返回更多结果。推荐：0.3-0.7，宽松场景用0.5">
                    <InfoCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                  </Tooltip>
                </label>
                <InputNumber
                  min={0}
                  max={1}
                  step={0.05}
                  value={pullConfig.similarity_threshold}
                  onChange={(value) => {
                    setPullConfig({ 
                      ...pullConfig, 
                      similarity_threshold: value ?? 0.5
                    });
                  }}
                  style={{ width: '100%' }}
                />
              </div>

              <div className={styles.configItem}>
                <label>
                  Top K
                  <Tooltip title="返回最相关的K个文档片段">
                    <InfoCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                  </Tooltip>
                </label>
                <InputNumber
                  min={1}
                  max={20}
                  value={pullConfig.top_k}
                  onChange={(value) => setPullConfig({ ...pullConfig, top_k: value || 5 })}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* 详情弹窗 */}
      <Modal
        title="知识库详情"
        open={detailModalVisible}
        onCancel={() => {
          setDetailModalVisible(false);
          setDetailKB(null);
        }}
        footer={null}
        width={600}
        className={theme === 'dark' ? 'dark-modal' : ''}
      >
        {detailKB && (
          <div className={styles.detailModal}>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>知识库名称：</span>
              <span className={styles.detailValue}>{detailKB.name}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>描述：</span>
              <span className={styles.detailValue}>{detailKB.description || '暂无描述'}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>创作者：</span>
              <span className={styles.detailValue}>{detailKB.owner_account || '未知'}</span>
            </div>
            {'document_count' in detailKB && (
              <>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>文档数：</span>
                  <span className={styles.detailValue}>{detailKB.document_count}</span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>分片数：</span>
                  <span className={styles.detailValue}>{detailKB.chunk_count}</span>
                </div>
              </>
            )}
            {'embedding_provider' in detailKB && (
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>向量模型：</span>
                <span className={styles.detailValue}>
                  <Tag color="blue">{(detailKB as SharedKnowledgeBase).embedding_provider}/{(detailKB as SharedKnowledgeBase).embedding_model}</Tag>
                </span>
              </div>
            )}
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>分块大小：</span>
              <span className={styles.detailValue}>
                {'chunk_size' in detailKB ? detailKB.chunk_size : (detailKB as PulledKnowledgeBase).split_params?.chunk_size || '未知'}
              </span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>分块重叠：</span>
              <span className={styles.detailValue}>
                {'chunk_overlap' in detailKB ? detailKB.chunk_overlap : (detailKB as PulledKnowledgeBase).split_params?.chunk_overlap || '未知'}
              </span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>相似度阈值：</span>
              <span className={styles.detailValue}>{detailKB.similarity_threshold}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Top K：</span>
              <span className={styles.detailValue}>{detailKB.top_k}</span>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default KBMarketplace;
