import React, { useState, useEffect } from 'react';
import { Modal, Checkbox, Button, message, Collapse, Space, Spin, Tooltip } from 'antd';
import { ReloadOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import type { CheckboxChangeEvent } from 'antd/es/checkbox';
import { getAvailableToolsConfig, updateToolConfig, resetToolConfig, ToolInfo } from '../../services/toolConfig';
import { useThemeStore } from '../../stores/themeStore';
import axios from 'axios';

const { Panel } = Collapse;

// 工具元数据类型
interface ToolMetadata {
  name: string;
  display_name: string;
  description: string;
}

interface ToolsByCategory {
  [category: string]: ToolInfo[];
}

interface ToolConfigPanelProps {
  visible: boolean;
  onClose: () => void;
}

const ToolConfigPanel: React.FC<ToolConfigPanelProps> = ({ visible, onClose }) => {
  const { theme } = useThemeStore(); // 获取主题
  const [tools, setTools] = useState<ToolsByCategory>({});
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toolsMetadata, setToolsMetadata] = useState<Record<string, ToolMetadata>>({});

  // 从后端加载工具元数据
  const loadToolsMetadata = async () => {
    try {
      const response = await axios.get('/api/tool-config/tools-metadata');
      if (response.data.success) {
        const metadataMap: Record<string, ToolMetadata> = {};
        response.data.tools.forEach((tool: ToolMetadata) => {
          metadataMap[tool.name] = tool;
        });
        setToolsMetadata(metadataMap);
      }
    } catch (error: any) {
      console.error('加载工具元数据失败:', error);
      // 不影响主流程，只是少了中文名和描述
    }
  };

  // 加载可用工具和用户配置
  const loadToolsAndConfig = async () => {
    setLoading(true);
    try {
      // 并行加载元数据和配置
      await Promise.all([
        loadToolsMetadata(),
        (async () => {
          const data = await getAvailableToolsConfig();

          // 按类别分组工具
          const groupedTools: ToolsByCategory = {};
          data.available_tools.forEach((tool: ToolInfo) => {
            const category = tool.category || '其他';
            if (!groupedTools[category]) {
              groupedTools[category] = [];
            }
            groupedTools[category].push(tool);
          });
          setTools(groupedTools);

          // 设置已选工具
          setSelectedTools(data.enabled_tools || []);
        })()
      ]);
    } catch (error: any) {
      console.error('加载工具配置失败:', error);
      message.error(error.response?.data?.detail || '加载工具配置失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible) {
      loadToolsAndConfig();
    }
  }, [visible]);

  // 处理单个工具的选择/取消
  const handleToolChange = (toolName: string) => (e: CheckboxChangeEvent) => {
    if (e.target.checked) {
      setSelectedTools([...selectedTools, toolName]);
    } else {
      setSelectedTools(selectedTools.filter(t => t !== toolName));
    }
  };

  // 处理类别全选/取消全选
  const handleCategoryCheckAll = (category: string) => (e: CheckboxChangeEvent) => {
    const categoryTools = tools[category].map(t => t.name);
    if (e.target.checked) {
      // 添加该类别的所有工具（去重）
      const newSelected = [...new Set([...selectedTools, ...categoryTools])];
      setSelectedTools(newSelected);
    } else {
      // 移除该类别的所有工具
      setSelectedTools(selectedTools.filter(t => !categoryTools.includes(t)));
    }
  };

  // 检查类别是否全选
  const isCategoryCheckAll = (category: string): boolean => {
    const categoryTools = tools[category].map(t => t.name);
    return categoryTools.every(t => selectedTools.includes(t));
  };

  // 检查类别是否部分选中
  const isCategoryIndeterminate = (category: string): boolean => {
    const categoryTools = tools[category].map(t => t.name);
    const selectedCount = categoryTools.filter(t => selectedTools.includes(t)).length;
    return selectedCount > 0 && selectedCount < categoryTools.length;
  };

  // 保存配置
  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await updateToolConfig(selectedTools);
      message.success(result.message || '工具配置已保存');
      onClose();
    } catch (error: any) {
      console.error('保存配置失败:', error);
      message.error(error.response?.data?.detail || '保存配置失败');
    } finally {
      setSaving(false);
    }
  };

  // 重置为全部启用
  const handleReset = async () => {
    try {
      const result = await resetToolConfig();
      message.success(result.message || '已重置为全部启用');
      await loadToolsAndConfig(); // 重新加载配置
    } catch (error: any) {
      console.error('重置失败:', error);
      message.error(error.response?.data?.detail || '重置失败');
    }
  };

  return (
    <Modal
      title="工具配置"
      open={visible}
      onCancel={onClose}
      width={700}
      zIndex={1200}
      footer={[
        <Button key="reset" icon={<ReloadOutlined />} onClick={handleReset}>
          重置为全部启用
        </Button>,
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="save" type="primary" onClick={handleSave} loading={saving}>
          保存
        </Button>
      ]}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
        </div>
      ) : (
        <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
          <div style={{ 
            marginBottom: 16, 
            color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
          }}>
            选择要在对话中启用的工具（已选 {selectedTools.length} 个）
          </div>
          
          <Collapse 
            defaultActiveKey={Object.keys(tools)} 
            ghost
            style={{ 
              color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
            }}
          >
            {Object.entries(tools).map(([category, categoryTools]) => (
              <Panel
                header={
                  <Checkbox
                    checked={isCategoryCheckAll(category)}
                    indeterminate={isCategoryIndeterminate(category)}
                    onChange={handleCategoryCheckAll(category)}
                    onClick={(e) => e.stopPropagation()}
                    style={{ 
                      color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
                    }}
                  >
                    <span style={{ 
                      color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
                    }}>
                      <strong>{category}</strong> ({categoryTools.length} 个工具)
                    </span>
                  </Checkbox>
                }
                key={category}
                style={{ 
                  color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
                }}
              >
                <Space direction="vertical" style={{ width: '100%', paddingLeft: 24 }}>
                  {categoryTools.map((tool) => {
                    const metadata = toolsMetadata[tool.name];
                    const displayName = metadata?.display_name || tool.name;
                    const description = metadata?.description || '';
                    
                    return (
                      <div key={tool.name} style={{ marginBottom: 8 }}>
                        <Checkbox
                          checked={selectedTools.includes(tool.name)}
                          onChange={handleToolChange(tool.name)}
                          style={{ 
                            color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
                          }}
                        >
                          <span style={{ 
                            color: theme === 'dark' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.85)' 
                          }}>
                            {displayName}
                          </span>
                          {description && (
                            <Tooltip title={description} placement="right">
                              <QuestionCircleOutlined 
                                style={{ 
                                  marginLeft: 6,
                                  color: theme === 'dark' ? 'rgba(255, 255, 255, 0.45)' : 'rgba(0, 0, 0, 0.45)',
                                  fontSize: 14
                                }} 
                              />
                            </Tooltip>
                          )}
                        </Checkbox>
                      </div>
                    );
                  })}
                </Space>
              </Panel>
            ))}
          </Collapse>
        </div>
      )}
    </Modal>
  );
};

export default ToolConfigPanel;
