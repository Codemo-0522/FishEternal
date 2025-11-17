import React, { useState, useEffect } from 'react';
import {
  Modal,
  Form,
  Switch,
  InputNumber,
  Collapse,
  Button,
  message,
  Spin,
  Tooltip,
  Alert,
  Space,
  Divider,
  Tag,
  Card,
} from 'antd';
import {
  SettingOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  ThunderboltOutlined,
  TeamOutlined,
  ClockCircleOutlined,
  FilterOutlined,
  FireOutlined,
  SafetyOutlined,
  RocketOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import authAxios from '../utils/authAxios';

const { Panel } = Collapse;

// 配置模板接口
interface StrategyTemplate {
  name: string;
  description: string;
  icon: string;
  tags: string[];
  config: GroupStrategyConfig;
}

// 策略配置接口
interface GroupStrategyConfig {
  // 模板信息
  applied_template?: string | null;
  base_template?: string | null;  // 基础模板名称（即使被修改也保留）
  
  // 一键解除限流模式
  unrestricted_mode?: boolean;
  
  // 第1层：对话轮次限流
  max_ai_consecutive_replies: number;
  max_messages_per_round: number;
  max_tokens_per_round: number;
  cooldown_seconds: number;
  max_cooldown_recoveries: number;
  enable_ai_to_ai: boolean;
  ai_reply_probability: number;
  
  // 第2层：概率采样限流
  high_probability_threshold: number;
  high_probability_keep_rate: number;
  mid_probability_threshold: number;
  low_probability_keep_rate: number;
  min_ai_sample_count: number;
  
  // 第3层：智能并发控制
  cold_group_max_concurrent: number;
  cold_group_min_delay_gap: number;
  warm_group_max_concurrent: number;
  warm_group_min_delay_gap: number;
  hot_group_max_concurrent: number;
  hot_group_min_delay_gap: number;
  
  human_message_max_concurrent: number;
  ai_message_max_concurrent: number;
  at_mention_max_concurrent: number;
  
  ai_consecutive_0_multiplier: number;
  ai_consecutive_1_multiplier: number;
  ai_consecutive_2_multiplier: number;
  ai_consecutive_3_multiplier: number;
  
  dense_ai_multiplier: number;
  
  // 第4层：抢答控制
  max_concurrent_replies_per_message: number;
  
  // 第5层：相似度检测
  enable_similarity_detection: boolean;
  similarity_threshold: number;
  similarity_lookback: number;
  
  // 延迟控制
  mention_delay_min: number;
  mention_delay_max: number;
  high_interest_delay_min: number;
  high_interest_delay_max: number;
  normal_delay_min: number;
  normal_delay_max: number;
  ai_to_ai_delay_seconds: number;
}

interface GroupStrategyConfigProps {
  visible: boolean;
  groupId: string;
  isOwner: boolean;  // 是否是群主
  onClose: () => void;
  onSuccess?: () => void;
}

const GroupStrategyConfigModal: React.FC<GroupStrategyConfigProps> = ({
  visible,
  groupId,
  isOwner,
  onClose,
  onSuccess,
}) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [unrestrictedMode, setUnrestrictedMode] = useState(false);
  
  // 模板相关状态
  const [templates, setTemplates] = useState<StrategyTemplate[]>([]);
  const [appliedTemplateName, setAppliedTemplateName] = useState<string>('');
  const [formVersion, setFormVersion] = useState(0); // 🔄 强制重新渲染模板卡片

  // 加载配置模板
  const loadTemplates = async () => {
    try {
      // 读取模板索引
      const indexResponse = await fetch('/templates/group-strategies/index.json');
      const indexData = await indexResponse.json();
      
      // 加载所有模板
      const templatePromises = indexData.templates.map(async (filename: string) => {
        const response = await fetch(`/templates/group-strategies/${filename}`);
        return await response.json();
      });
      
      const loadedTemplates = await Promise.all(templatePromises);
      setTemplates(loadedTemplates);
    } catch (error) {
      console.error('加载配置模板失败:', error);
      message.warning('加载配置模板失败，模板功能不可用');
    }
  };
  
  // 应用模板
  const applyTemplate = async (template: StrategyTemplate) => {
    Modal.confirm({
      title: '应用配置模板',
      content: (
        <div>
          <p><strong>{template.icon} {template.name}</strong></p>
          <p>{template.description}</p>
          <p style={{ marginTop: 12 }}>
            {template.tags.map(tag => (
              <Tag key={tag} color="blue">{tag}</Tag>
            ))}
          </p>
          <Alert 
            message="应用后将覆盖当前所有配置并立即保存" 
            type="warning" 
            showIcon 
            style={{ marginTop: 12 }}
          />
        </div>
      ),
      onOk: async () => {
        try {
          console.log('📋 开始应用模板:', template.name);
          console.log('📋 模板配置:', template.config);
          
          setUnrestrictedMode(template.config.unrestricted_mode || false);
          form.setFieldsValue(template.config);
          
          // 🎯 立即保存到后端，包含 applied_template 和 base_template 字段
          const configToSave = {
            ...template.config,
            applied_template: template.name, // 标记应用的模板
            base_template: template.name,    // 保存基础模板（用于显示修改状态）
          };
          
          console.log('📋 即将保存的配置:', configToSave);
          
          setSaving(true);
          const response = await authAxios.put(
            `/api/group-chat/groups/${groupId}/strategy`,
            {
              strategy_config: configToSave,
            }
          );
          
          console.log('📋 后端返回的配置:', response.data.strategy_config);
          
          setAppliedTemplateName(template.name);
          message.success(`已应用【${template.name}】配置模板`);
          onSuccess?.();
        } catch (error: any) {
          console.error('❌ 应用模板失败:', error);
          message.error(error.response?.data?.detail || '应用模板失败');
        } finally {
          setSaving(false);
        }
      },
    });
  };

  // 加载策略配置
  const loadConfig = async () => {
    setLoading(true);
    try {
      const response = await authAxios.get(
        `/api/group-chat/groups/${groupId}/strategy`
      );
      
      const loadedConfig = response.data;
      setUnrestrictedMode(loadedConfig.unrestricted_mode || false);
      form.setFieldsValue(loadedConfig);
      
      // 🎯 优先从 base_template 加载（保留修改历史），其次从 applied_template
      const templateName = loadedConfig.base_template || loadedConfig.applied_template || '';
      setAppliedTemplateName(templateName);
      
      console.log('🔍 加载配置:', {
        base_template: loadedConfig.base_template,
        applied_template: loadedConfig.applied_template,
        使用模板: templateName
      });
    } catch (error: any) {
      message.error(error.response?.data?.detail || '加载策略配置失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible) {
      loadConfig(); // 会从后端加载 applied_template
      loadTemplates(); // 加载配置模板
    }
  }, [visible, groupId]);

  // 🎯 检查配置是否与模板一致
  const isConfigModified = (currentConfig: any): boolean => {
    if (!appliedTemplateName) {
      console.log('🔍 未应用模板，无法对比');
      return false; // 没有应用模板，无法对比
    }
    
    const template = templates.find(t => t.name === appliedTemplateName);
    if (!template) {
      console.log('🔍 模板不存在:', appliedTemplateName);
      return false; // 模板不存在
    }
    
    console.log('🔍 开始对比配置，模板:', appliedTemplateName);
    console.log('🔍 模板配置:', template.config);
    console.log('🔍 当前配置:', currentConfig);
    
    // 对比所有配置字段（排除 applied_template）
    const templateConfig = { ...template.config };
    delete templateConfig.applied_template;
    
    const currentConfigCopy = { ...currentConfig };
    delete currentConfigCopy.applied_template;
    
    // 🔍 只对比模板中定义的字段（忽略后端添加的额外字段）
    for (const key in templateConfig) {
      const templateValue = (templateConfig as any)[key];
      const currentValue = (currentConfigCopy as any)[key];
      
      // 处理 undefined/null 的情况
      if (currentValue === undefined || currentValue === null) {
        console.log(`⚠️ 字段为空: ${key}, 模板=${templateValue}, 当前=${currentValue}`);
        return true;
      }
      
      // 数值类型转换后比较
      if (typeof templateValue === 'number') {
        const numCurrent = Number(currentValue);
        const numTemplate = Number(templateValue);
        if (isNaN(numCurrent) || numCurrent !== numTemplate) {
          console.log(`❌ 字段不匹配: ${key}, 模板=${numTemplate}, 当前=${numCurrent}`);
          return true;
        }
      } else if (templateValue !== currentValue) {
        console.log(`❌ 字段不匹配: ${key}, 模板=${JSON.stringify(templateValue)}, 当前=${JSON.stringify(currentValue)}`);
        return true;
      }
    }
    
    console.log('✅ 配置与模板完全一致');
    return false;
  };

  // 保存配置
  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const configToSave = {
        ...values,
        unrestricted_mode: unrestrictedMode,
      };
      
      // 🎯 智能判断：如果手动修改了配置，则清除 applied_template，但保留 base_template
      const isModified = isConfigModified(configToSave);
      if (isModified && appliedTemplateName) {
        // 配置被手动修改，清除 applied_template，但保留 base_template 用于显示
        configToSave.applied_template = null;
        configToSave.base_template = appliedTemplateName; // 🎯 保存基础模板名称
        console.log('📝 配置已被手动修改，清除 applied_template，保留 base_template:', appliedTemplateName);
      } else if (appliedTemplateName) {
        // 配置未修改，两个字段都保持一致
        configToSave.applied_template = appliedTemplateName;
        configToSave.base_template = appliedTemplateName;
        console.log('📝 配置未修改，保持模板标记:', appliedTemplateName);
      }

      await authAxios.put(
        `/api/group-chat/groups/${groupId}/strategy`,
        {
          strategy_config: configToSave,
        }
      );

      // 🔄 不要清除 appliedTemplateName，保持它用于显示边框
      // （刷新页面后会从 base_template 加载）

      message.success('策略配置已保存');
      onSuccess?.();
    } catch (error: any) {
      if (error.response) {
        message.error(error.response.data?.detail || '保存失败');
      }
    } finally {
      setSaving(false);
    }
  };

  // 重置为默认配置
  const handleReset = async () => {
    Modal.confirm({
      title: '确认重置',
      content: '确定要将所有策略配置重置为默认值吗？',
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        setResetting(true);
        try {
          const response = await authAxios.post(
            `/api/group-chat/groups/${groupId}/strategy/reset`,
            {}
          );

          const defaultConfig = response.data.strategy_config;
          setUnrestrictedMode(defaultConfig.unrestricted_mode || false);
          form.setFieldsValue(defaultConfig);
          setAppliedTemplateName(''); // 清除已应用模板标记
          message.success('已重置为默认配置');
        } catch (error: any) {
          message.error(error.response?.data?.detail || '重置失败');
        } finally {
          setResetting(false);
        }
      },
    });
  };

  return (
    <Modal
      title={
        <Space>
          <SettingOutlined />
          <span>群聊策略配置</span>
          {!isOwner && <Tag color="orange">仅查看</Tag>}
        </Space>
      }
      open={visible}
      onCancel={onClose}
      width={800}
      footer={
        isOwner ? [
          <Button
            key="reset"
            icon={<ReloadOutlined />}
            onClick={handleReset}
            loading={resetting}
          >
            重置为默认
          </Button>,
          <Button key="cancel" onClick={onClose}>
            取消
          </Button>,
          <Button
            key="save"
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
          >
            保存配置
          </Button>,
        ] : [
          <Button key="close" onClick={onClose}>
            关闭
          </Button>,
        ]
      }
    >
      {!isOwner && (
        <Alert
          message="你不是群主，无法修改策略配置"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Spin spinning={loading}>
        {/* 🎯 当前配置状态提示 */}
        {appliedTemplateName && (
          <Alert
            message={
              <Space>
                <span>
                  {(() => {
                    const currentValues = form.getFieldsValue(true); // 🔍 获取所有字段，包括未修改的
                    const currentConfig = { ...currentValues, unrestricted_mode: unrestrictedMode };
                    const isModified = isConfigModified(currentConfig);
                    
                    if (isModified) {
                      return (
                        <>
                          🔧 <strong>基于【{appliedTemplateName}】模板修改</strong> - 配置已被手动调整
                        </>
                      );
                    } else {
                      return (
                        <>
                          ✓ <strong>已应用【{appliedTemplateName}】模板</strong> - 配置与模板一致
                        </>
                      );
                    }
                  })()}
                </span>
              </Space>
            }
            type={(() => {
              const currentValues = form.getFieldsValue(true); // 🔍 获取所有字段
              const currentConfig = { ...currentValues, unrestricted_mode: unrestrictedMode };
              const isModified = isConfigModified(currentConfig);
              return isModified ? 'warning' : 'success';
            })()}
            showIcon
            closable
            onClose={() => setAppliedTemplateName('')}
            style={{ marginBottom: 16 }}
          />
        )}
        
        {/* 配置模板选择器 */}
        {isOwner && templates.length > 0 && (
          <Card
            title={
              <Space>
                <DownloadOutlined />
                <span>快速应用配置模板</span>
              </Space>
            }
            style={{ marginBottom: 16 }}
            size="small"
          >
            <Alert
              message="选择预设的配置模板，一键应用所有参数"
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
            />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              {templates.map((template, index) => {
                const isRecommended = template.tags.includes('推荐');
                const isApplied = appliedTemplateName === template.name;
                
                // 🎯 检查配置是否被修改过（使用 formVersion 强制更新）
                const currentValues = form.getFieldsValue(true); // 🔍 获取所有字段
                const currentConfig = { ...currentValues, unrestricted_mode: unrestrictedMode };
                const isModified = isApplied && isConfigModified(currentConfig);
                
                // 调试输出
                if (isApplied) {
                  console.log(`🎨 渲染模板卡片 [v${formVersion}]: ${template.name}`);
                  console.log('🎨 当前表单值:', currentValues);
                  console.log('🎨 当前完整配置:', currentConfig);
                  console.log('🎨 是否被修改:', isModified);
                }
                
                return (
                  <Card
                    key={index}
                    hoverable
                    size="small"
                    onClick={() => applyTemplate(template)}
                    style={{
                      position: 'relative',
                      borderColor: isApplied ? '#52c41a' : undefined,
                      borderWidth: isApplied ? 2 : 1,
                      background: isApplied ? '#f6ffed' : undefined,
                      boxShadow: isApplied ? '0 2px 8px rgba(82, 196, 26, 0.3)' : undefined,
                    }}
                  >
                    {/* 推荐角标 */}
                    {isRecommended && !isApplied && (
                      <div style={{
                        position: 'absolute',
                        top: -1,
                        right: -1,
                        background: 'linear-gradient(135deg, #ffa940 0%, #ff7a45 100%)',
                        color: 'white',
                        fontSize: 10,
                        padding: '2px 8px',
                        borderRadius: '0 4px 0 8px',
                        fontWeight: 'bold',
                      }}>
                        推荐
                      </div>
                    )}
                    
                    {/* 已应用标记（纯模板/已修改） */}
                    {isApplied && (
                      <div style={{
                        position: 'absolute',
                        top: -1,
                        right: -1,
                        background: isModified 
                          ? 'linear-gradient(135deg, #faad14 0%, #d48806 100%)'
                          : 'linear-gradient(135deg, #52c41a 0%, #389e0d 100%)',
                        color: 'white',
                        fontSize: 10,
                        padding: '2px 8px',
                        borderRadius: '0 4px 0 8px',
                        fontWeight: 'bold',
                      }}>
                        {isModified ? '🔧 已修改' : '✓ 已应用'}
                      </div>
                    )}
                    
                    <div style={{ textAlign: 'center', paddingTop: isRecommended || isApplied ? 8 : 0 }}>
                      <div style={{ fontSize: 32, marginBottom: 8 }}>{template.icon}</div>
                      <div style={{ fontWeight: 'bold', marginBottom: 4 }}>{template.name}</div>
                      <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
                        {template.description.substring(0, 40)}...
                      </div>
                      <div>
                        {template.tags.filter(tag => tag !== '推荐').map(tag => (
                          <Tag key={tag} color="blue" style={{ fontSize: 10, padding: '0 4px' }}>
                            {tag}
                          </Tag>
                        ))}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          </Card>
        )}
        
        {/* 一键解除限流 - 超大开关 */}
        <Card
          style={{
            marginBottom: 24,
            background: unrestrictedMode
              ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
              : 'linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)',
            border: 'none',
            transition: 'all 0.3s ease',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Space size={16}>
              <RocketOutlined
                style={{
                  fontSize: 40,
                  color: unrestrictedMode ? '#fff' : '#666',
                }}
              />
              <div>
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 'bold',
                    color: unrestrictedMode ? '#fff' : '#333',
                    marginBottom: 4,
                  }}
                >
                  {unrestrictedMode ? '🎉 自由对话模式' : '⚙️ 限流控制模式'}
                </div>
                <div
                  style={{
                    fontSize: 14,
                    color: unrestrictedMode ? 'rgba(255,255,255,0.9)' : '#666',
                  }}
                >
                  {unrestrictedMode
                    ? 'AI们将完全自由对话，没有任何限制'
                    : '使用下方的精细化配置来控制AI行为'}
                </div>
              </div>
            </Space>
            <div style={{ transform: 'scale(1.5)', marginRight: 20 }}>
              <Switch
                checked={unrestrictedMode}
                onChange={(checked) => {
                  setUnrestrictedMode(checked);
                  setFormVersion(prev => prev + 1); // 🔄 强制重新渲染模板卡片
                }}
                disabled={!isOwner}
              />
            </div>
          </div>
        </Card>

        {/* 提示信息 */}
        {unrestrictedMode && (
          <Alert
            message="自由对话模式已启用"
            description="所有限流策略已被忽略，AI可以无限制地对话。如果您想精细控制AI行为，请关闭此开关。"
            type="warning"
            showIcon
            icon={<RocketOutlined />}
            style={{ marginBottom: 16 }}
          />
        )}

        <Form
          form={form}
          layout="vertical"
          disabled={!isOwner || unrestrictedMode}
          onValuesChange={() => {
            // 🔄 表单值变化时，强制重新渲染模板卡片
            setFormVersion(prev => prev + 1);
          }}
        >
          <Collapse
            defaultActiveKey={[]}
            ghost
            style={{
              opacity: unrestrictedMode ? 0.5 : 1,
              transition: 'opacity 0.3s ease',
            }}
          >
            {/* 第1层：对话轮次限流 */}
            <Panel
              header={
                <Space>
                  <FireOutlined style={{ color: '#ff4d4f' }} />
                  <span>第1层：对话轮次限流</span>
                </Space>
              }
              key="layer1"
            >
              <Form.Item
                label={
                  <Space>
                    <span>AI最多连续回复次数</span>
                    <Tooltip title="AI连续回复超过此次数后会进入冷却期">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="max_ai_consecutive_replies"
              >
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 3-5" />
              </Form.Item>

              <Form.Item
                label={
                  <Space>
                    <span>每轮对话最多消息数</span>
                    <Tooltip title="单轮对话消息总数超过此值会触发冷却">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="max_messages_per_round"
              >
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 20-50" />
              </Form.Item>

              <Form.Item
                label={
                  <Space>
                    <span>每轮对话最多tokens</span>
                    <Tooltip title="控制成本，超过此值会触发冷却">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="max_tokens_per_round"
              >
                <InputNumber min={1000} step={1000} style={{ width: '100%' }} placeholder="建议值: 50000" />
              </Form.Item>

              <Form.Item
                label={
                  <Space>
                    <span>冷却期时长（秒）</span>
                    <Tooltip title="触发限制后的冷却时间">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="cooldown_seconds"
              >
                <InputNumber min={0} step={10} style={{ width: '100%' }} placeholder="建议值: 30-60" />
              </Form.Item>

              <Form.Item
                label={
                  <Space>
                    <span>最大冷却期恢复次数</span>
                    <Tooltip title="防止无限循环对话">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="max_cooldown_recoveries"
              >
                <InputNumber min={0} step={1} style={{ width: '100%' }} placeholder="建议值: 3-5" />
              </Form.Item>

              <Form.Item
                label="启用AI互相对话"
                name="enable_ai_to_ai"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>

              <Form.Item
                label={
                  <Space>
                    <span>AI对AI消息的回复概率</span>
                    <Tooltip title="降低此值可减少AI互相刷屏（0-1之间）">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="ai_reply_probability"
              >
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.3-0.6" />
              </Form.Item>
            </Panel>

            {/* 第2层：概率采样限流 */}
            <Panel
              header={
                <Space>
                  <FilterOutlined style={{ color: '#1890ff' }} />
                  <span>第2层：概率采样限流</span>
                </Space>
              }
              key="layer2"
            >
              <Form.Item
                label="AI数量≤此值时直接放行"
                name="min_ai_sample_count"
              >
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 3" />
              </Form.Item>

              <Divider>概率阈值</Divider>

              <Form.Item label="高概率阈值" name="high_probability_threshold">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.7" />
              </Form.Item>

              <Form.Item label="高概率保留率" name="high_probability_keep_rate">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.8" />
              </Form.Item>

              <Form.Item label="中概率阈值" name="mid_probability_threshold">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.3" />
              </Form.Item>

              <Form.Item label="低概率采样率" name="low_probability_keep_rate">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.3" />
              </Form.Item>
            </Panel>

            {/* 第3层：智能并发控制 */}
            <Panel
              header={
                <Space>
                  <TeamOutlined style={{ color: '#52c41a' }} />
                  <span>第3层：智能并发控制</span>
                </Space>
              }
              key="layer3"
            >
              <Divider>根据群组活跃度</Divider>

              <Form.Item label="冷清群最大并发AI数" name="cold_group_max_concurrent">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 2" />
              </Form.Item>

              <Form.Item label="冷清群最小延迟间隔（秒）" name="cold_group_min_delay_gap">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 5" />
              </Form.Item>

              <Form.Item label="温和群最大并发AI数" name="warm_group_max_concurrent">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 3" />
              </Form.Item>

              <Form.Item label="温和群最小延迟间隔（秒）" name="warm_group_min_delay_gap">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 3" />
              </Form.Item>

              <Form.Item label="热闹群最大并发AI数" name="hot_group_max_concurrent">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 5" />
              </Form.Item>

              <Form.Item label="热闹群最小延迟间隔（秒）" name="hot_group_min_delay_gap">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 2" />
              </Form.Item>

              <Divider>根据触发消息类型</Divider>

              <Form.Item label="人类消息最大并发AI数" name="human_message_max_concurrent">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 5" />
              </Form.Item>

              <Form.Item label="AI消息最大并发AI数" name="ai_message_max_concurrent">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 2" />
              </Form.Item>

              <Form.Item label="@消息最大并发AI数" name="at_mention_max_concurrent">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 2" />
              </Form.Item>

              <Divider>AI连续回复概率衰减</Divider>

              <Form.Item label="无AI连续时的概率倍数" name="ai_consecutive_0_multiplier">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 1.0" />
              </Form.Item>

              <Form.Item label="1次AI连续时的概率倍数" name="ai_consecutive_1_multiplier">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.8" />
              </Form.Item>

              <Form.Item label="2次AI连续时的概率倍数" name="ai_consecutive_2_multiplier">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.5" />
              </Form.Item>

              <Form.Item label="3次及以上AI连续时的概率倍数" name="ai_consecutive_3_multiplier">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.2" />
              </Form.Item>

              <Form.Item label="AI回复密集时的概率倍数" name="dense_ai_multiplier">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.5" />
              </Form.Item>
            </Panel>

            {/* 第4层：抢答控制限流 */}
            <Panel
              header={
                <Space>
                  <ThunderboltOutlined style={{ color: '#faad14' }} />
                  <span>第4层：抢答控制限流</span>
                </Space>
              }
              key="layer4"
            >
              <Form.Item
                label={
                  <Space>
                    <span>单条消息最大并发回复数</span>
                    <Tooltip title="同一条消息最多允许几个AI同时回复">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="max_concurrent_replies_per_message"
              >
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 3" />
              </Form.Item>
            </Panel>

            {/* 第5层：相似度检测 */}
            <Panel
              header={
                <Space>
                  <SafetyOutlined style={{ color: '#722ed1' }} />
                  <span>第5层：相似度检测</span>
                </Space>
              }
              key="layer5"
            >
              <Form.Item
                label="启用相似度检测"
                name="enable_similarity_detection"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>

              <Form.Item
                label={
                  <Space>
                    <span>相似度阈值</span>
                    <Tooltip title="超过此阈值认为内容相似，AI会跳过回复">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="similarity_threshold"
              >
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} placeholder="建议值: 0.8" />
              </Form.Item>

              <Form.Item label="相似度检测回溯消息数" name="similarity_lookback">
                <InputNumber min={1} step={1} style={{ width: '100%' }} placeholder="建议值: 3" />
              </Form.Item>
            </Panel>

            {/* 延迟控制 */}
            <Panel
              header={
                <Space>
                  <ClockCircleOutlined style={{ color: '#13c2c2' }} />
                  <span>延迟控制</span>
                </Space>
              }
              key="delay"
            >
              <Divider>被@时延迟</Divider>

              <Form.Item label="最小延迟（秒）" name="mention_delay_min">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 0.5" />
              </Form.Item>

              <Form.Item label="最大延迟（秒）" name="mention_delay_max">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 2" />
              </Form.Item>

              <Divider>高兴趣消息延迟</Divider>

              <Form.Item label="最小延迟（秒）" name="high_interest_delay_min">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 1" />
              </Form.Item>

              <Form.Item label="最大延迟（秒）" name="high_interest_delay_max">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 5" />
              </Form.Item>

              <Divider>普通消息延迟</Divider>

              <Form.Item label="最小延迟（秒）" name="normal_delay_min">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 2" />
              </Form.Item>

              <Form.Item label="最大延迟（秒）" name="normal_delay_max">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 10" />
              </Form.Item>

              <Divider>AI-to-AI触发延迟</Divider>

              <Form.Item 
                label="AI回复后延迟（秒）" 
                name="ai_to_ai_delay_seconds"
                tooltip="AI回复完成后，等待多久再触发新的AI决策流程。如果期间有真人发言，会取消此延迟。"
              >
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="建议值: 7" />
              </Form.Item>
            </Panel>
          </Collapse>
        </Form>
      </Spin>
    </Modal>
  );
};

export default GroupStrategyConfigModal;

