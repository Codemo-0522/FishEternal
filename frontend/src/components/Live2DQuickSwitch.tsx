import React from 'react';
import { Tooltip } from 'antd';
import { useLive2DStore, availableModels } from '../stores/live2dStore';

const Live2DQuickSwitch: React.FC = () => {
  const { currentModel, setModel } = useLive2DStore();

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: '50px',
        backgroundColor: 'var(--bg-card)',
        borderBottom: '1px solid var(--border-primary)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: '8px',
        overflowX: 'auto',
        overflowY: 'hidden',
        zIndex: 1000,
        boxShadow: 'var(--shadow-light)',
      }}
    >
      <span
        style={{
          fontSize: '14px',
          fontWeight: 'bold',
          color: 'var(--text-primary)',
          marginRight: '8px',
          whiteSpace: 'nowrap',
        }}
      >
        Live2D:
      </span>
      {availableModels.map((model) => (
        <Tooltip key={model.id} title={model.description}>
          <div
            onClick={() => setModel(model.id)}
            style={{
              padding: '6px 12px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '13px',
              whiteSpace: 'nowrap',
              backgroundColor:
                currentModel === model.id
                  ? 'var(--primary-color)'
                  : 'var(--bg-secondary)',
              color:
                currentModel === model.id
                  ? '#fff'
                  : 'var(--text-primary)',
              border: `1px solid ${
                currentModel === model.id
                  ? 'var(--primary-color)'
                  : 'var(--border-secondary)'
              }`,
              transition: 'all 0.3s ease',
              fontWeight: currentModel === model.id ? 'bold' : 'normal',
            }}
            onMouseEnter={(e) => {
              if (currentModel !== model.id) {
                e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)';
              }
            }}
            onMouseLeave={(e) => {
              if (currentModel !== model.id) {
                e.currentTarget.style.backgroundColor = 'var(--bg-secondary)';
              }
            }}
          >
            {model.name}
          </div>
        </Tooltip>
      ))}
    </div>
  );
};

export default Live2DQuickSwitch;
