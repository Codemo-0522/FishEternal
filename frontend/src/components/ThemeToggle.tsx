import React, { useState } from 'react';
import { Button, Tooltip } from 'antd';
import { SunOutlined, MoonOutlined, HeartOutlined } from '@ant-design/icons';
import { useThemeStore } from '../stores/themeStore';

const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme } = useThemeStore();
  const [tooltipOpen, setTooltipOpen] = useState(false);

  const getThemeIcon = () => {
    switch (theme) {
      case 'light':
        return <SunOutlined />;
      case 'dark':
        return <MoonOutlined />;
      case 'romantic':
        return <HeartOutlined />;
      default:
        return <SunOutlined />;
    }
  };

  const getThemeTitle = () => {
    switch (theme) {
      case 'light':
        return '切换到深色主题';
      case 'dark':
        return '切换到恋爱系主题';
      case 'romantic':
        return '切换到浅色主题';
      default:
        return '切换主题';
    }
  };

  return (
    <Tooltip 
      title={getThemeTitle()}
      trigger={["hover"]}
      open={tooltipOpen}
      onOpenChange={setTooltipOpen}
      mouseEnterDelay={0.2}
      mouseLeaveDelay={0.05}
      destroyTooltipOnHide
      getPopupContainer={() => document.body}
    >
      <Button
        type="text"
        icon={getThemeIcon()}
        onClick={() => { toggleTheme(); setTooltipOpen(false); }}
        style={{
          color: 'var(--text-primary)',
          border: 'none',
          padding: '4px 8px',
        }}
      />
    </Tooltip>
  );
};

export default ThemeToggle;