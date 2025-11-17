import React, { useState } from 'react';
import { Button, Tooltip } from 'antd';
import { SunOutlined, MoonOutlined } from '@ant-design/icons';
import { useThemeStore } from '../stores/themeStore';

const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme } = useThemeStore();
  const [tooltipOpen, setTooltipOpen] = useState(false);

  return (
    <Tooltip 
      title={theme === 'light' ? '切换到深色主题' : '切换到浅色主题'}
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
        icon={theme === 'light' ? <MoonOutlined /> : <SunOutlined />}
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