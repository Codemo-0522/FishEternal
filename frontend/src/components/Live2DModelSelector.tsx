import React, { useState } from 'react';
import { Button, Drawer, List, Avatar, message } from 'antd';
import { AppstoreOutlined, WomanOutlined, ManOutlined, SmileOutlined } from '@ant-design/icons';
import { useLive2DStore, availableModels } from '../stores/live2dStore';

type CategoryType = 'female' | 'male' | 'animal';

const Live2DModelSelector: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<CategoryType>('female');
  const { currentModel, setModel } = useLive2DStore();

  const handleModelChange = (modelId: string) => {
    setModel(modelId);
    message.success('模型切换成功，正在加载...');
    setOpen(false);
  };

  return (
    <>
      <Button
        type="text"
        icon={<AppstoreOutlined />}
        onClick={() => setOpen(true)}
        style={{
          color: 'var(--text-primary)',
          border: 'none',
          padding: '4px 8px',
        }}
        title="切换Live2D模型"
      />
      
      <Drawer
        title="选择Live2D模型"
        placement="right"
        onClose={() => setOpen(false)}
        open={open}
        width={360}
        styles={{
          body: {
            padding: 0,
            backgroundColor: 'var(--bg-primary)',
          },
          header: {
            backgroundColor: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
            borderBottom: '1px solid var(--border-primary)',
          },
        }}
      >
        {/* 顶部分类标签 */}
        <div style={{
          display: 'flex',
          gap: '8px',
          padding: '12px 16px',
          backgroundColor: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-primary)',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}>
          <Button
            type={selectedCategory === 'female' ? 'primary' : 'default'}
            icon={<WomanOutlined />}
            onClick={() => setSelectedCategory('female')}
            style={{ flex: 1 }}
          >
            女性
          </Button>
          <Button
            type={selectedCategory === 'male' ? 'primary' : 'default'}
            icon={<ManOutlined />}
            onClick={() => setSelectedCategory('male')}
            style={{ flex: 1 }}
          >
            男性
          </Button>
          <Button
            type={selectedCategory === 'animal' ? 'primary' : 'default'}
            icon={<SmileOutlined />}
            onClick={() => setSelectedCategory('animal')}
            style={{ flex: 1 }}
          >
            动物
          </Button>
        </div>

        {/* 模型列表 */}
        <div style={{ padding: '16px' }}>
          <List
            dataSource={availableModels.filter(m => m.category === selectedCategory)}
          renderItem={(model) => (
            <List.Item
              onClick={() => handleModelChange(model.id)}
              style={{
                cursor: 'pointer',
                padding: '12px',
                borderRadius: '8px',
                marginBottom: '8px',
                backgroundColor: currentModel === model.id ? 'var(--primary-color)' : 'var(--bg-card)',
                border: `1px solid ${currentModel === model.id ? 'var(--primary-color)' : 'var(--border-secondary)'}`,
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                if (currentModel !== model.id) {
                  e.currentTarget.style.backgroundColor = 'var(--bg-secondary)';
                }
              }}
              onMouseLeave={(e) => {
                if (currentModel !== model.id) {
                  e.currentTarget.style.backgroundColor = 'var(--bg-card)';
                }
              }}
            >
              <List.Item.Meta
                avatar={
                  <Avatar
                    style={{
                      backgroundColor: currentModel === model.id ? '#fff' : 'var(--primary-color)',
                      color: currentModel === model.id ? 'var(--primary-color)' : '#fff',
                    }}
                  >
                    {model.name.charAt(0)}
                  </Avatar>
                }
                title={
                  <span
                    style={{
                      color: currentModel === model.id ? '#fff' : 'var(--text-primary)',
                      fontWeight: currentModel === model.id ? 'bold' : 'normal',
                    }}
                  >
                    {model.name}
                  </span>
                }
                description={
                  <span style={{ 
                    color: currentModel === model.id ? 'rgba(255, 255, 255, 0.9)' : 'var(--text-tertiary)', 
                    fontSize: '12px' 
                  }}>
                    {currentModel === model.id ? '✓ 当前使用' : model.description}
                  </span>
                }
              />
            </List.Item>
          )}
          />
        </div>
      </Drawer>
    </>
  );
};

export default Live2DModelSelector;
