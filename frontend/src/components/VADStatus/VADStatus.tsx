import React from 'react';
import { 
  AudioOutlined, 
  LoadingOutlined, 
  SoundOutlined, 
  CloseCircleOutlined,
  PauseCircleOutlined 
} from '@ant-design/icons';
import styles from './VADStatus.module.css';

export type VADStatusType = 'idle' | 'recording' | 'speaking' | 'silence' | 'transcribing';

interface VADStatusProps {
  status: VADStatusType;
  visible: boolean;
  onCancel?: () => void; // 中断按钮回调
  currentVolume?: number; // 当前音量 (0-1)
  recordingDuration?: number; // 录音时长 (毫秒)
}

const statusConfig = {
  idle: {
    icon: null,
    text: '',
    subText: '',
    className: '',
  },
  recording: {
    icon: <AudioOutlined />,
    text: 'VAD 检测中',
    subText: '等待语音输入...',
    className: 'recording',
  },
  speaking: {
    icon: <SoundOutlined />,
    text: '正在录制',
    subText: '检测到语音信号',
    className: 'speaking',
  },
  silence: {
    icon: <PauseCircleOutlined />,
    text: '静音中',
    subText: '1.5 秒后自动发送',
    className: 'silence',
  },
  transcribing: {
    icon: <LoadingOutlined spin />,
    text: '发送中',
    subText: '正在识别语音内容...',
    className: 'transcribing',
  },
};

export const VADStatus: React.FC<VADStatusProps> = ({ status, visible, onCancel, currentVolume = 0, recordingDuration = 0 }) => {
  if (!visible || status === 'idle') {
    return null;
  }

  const config = statusConfig[status];
  
  // 格式化录音时长
  const formatDuration = (ms: number) => {
    const seconds = (ms / 1000).toFixed(1);
    return `${seconds}s`;
  };
  
  // 格式化音量百分比
  const formatVolume = (volume: number) => {
    return `${(volume * 100).toFixed(1)}%`;
  };

  return (
    <div className={`${styles.vadStatus} ${styles[config.className]}`}>
      <div className={styles.mainContent}>
        <div className={styles.iconContainer}>
          <span className={styles.statusIcon}>{config.icon}</span>
        </div>
        
        <div className={styles.textContainer}>
          <div className={styles.statusText}>{config.text}</div>
          <div className={styles.subText}>{config.subText}</div>
          {/* 在录音、说话或静音状态下显示音量和时长 */}
          {(status === 'recording' || status === 'speaking' || status === 'silence') && (
            <div className={styles.statsInfo}>
              音量: {formatVolume(currentVolume)} | 时长: {formatDuration(recordingDuration)}
            </div>
          )}
        </div>

        {status === 'speaking' && (
          <div className={styles.waveform}>
            <div className={styles.wave}></div>
            <div className={styles.wave}></div>
            <div className={styles.wave}></div>
            <div className={styles.wave}></div>
            <div className={styles.wave}></div>
          </div>
        )}

        {/* 中断按钮 - 仅在录音和识别阶段显示 */}
        {(status === 'recording' || status === 'speaking' || status === 'silence') && onCancel && (
          <button 
            className={styles.cancelButton}
            onClick={onCancel}
            title="取消录音"
          >
            <CloseCircleOutlined />
          </button>
        )}
      </div>

      {/* 状态指示条 */}
      <div className={styles.statusBar}>
        <div className={`${styles.statusIndicator} ${styles[`indicator_${status}`]}`}></div>
      </div>
    </div>
  );
};

