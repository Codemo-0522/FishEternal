import React from 'react';
import { Button, Tooltip } from 'antd';
import { EyeOutlined, EyeInvisibleOutlined } from '@ant-design/icons';
import { useLive2DPositionStore } from '../stores/live2dPositionStore';

const Live2DToggle: React.FC = () => {
  const { visible, setVisible } = useLive2DPositionStore();

  return (
    <Tooltip title={visible ? '隐藏宠物' : '显示宠物'}>
      <Button
        type="text"
        icon={visible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
        onClick={() => setVisible(!visible)}
        style={{
          color: 'var(--text-primary)',
          border: 'none',
          padding: '4px 8px',
        }}
      />
    </Tooltip>
  );
};

export default Live2DToggle;
