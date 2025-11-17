import React, { useState, useEffect } from 'react';
import { Modal, Slider, Card, Progress, Button, Space, Typography, Switch, Row, Col, Divider, Checkbox, List } from 'antd';
import { CompressOutlined, FileImageOutlined, CheckOutlined, CloseOutlined, PictureOutlined } from '@ant-design/icons';
import styles from './ImageCompressor.module.css';

const { Title, Text } = Typography;

interface ImageCompressorProps {
  visible: boolean;
  images: File[];
  imagePreviews: string[];
  onCancel: () => void;
  onConfirm: (compressedImages: File[], compressedPreviews: string[]) => void;
}

interface CompressionSettings {
  maxWidth: number;
  quality: number;
  maintainAspectRatio: boolean;
}

interface CompressionProgress {
  current: number;
  total: number;
  percentage: number;
  processing: boolean;
}

const ImageCompressor: React.FC<ImageCompressorProps> = ({
  visible,
  images,
  imagePreviews,
  onCancel,
  onConfirm
}) => {
  const [settings, setSettings] = useState<CompressionSettings>({
    maxWidth: 1024,
    quality: 0.8,
    maintainAspectRatio: true
  });

  const [progress, setProgress] = useState<CompressionProgress>({
    current: 0,
    total: 0,
    percentage: 0,
    processing: false
  });

  const [compressedImages, setCompressedImages] = useState<File[]>([]);
  const [compressedPreviews, setCompressedPreviews] = useState<string[]>([]);
  const [originalSizes, setOriginalSizes] = useState<number[]>([]);
  const [compressedSizes, setCompressedSizes] = useState<number[]>([]);
  const [selectedImageIndexes, setSelectedImageIndexes] = useState<number[]>([]);

  // 重置状态
  const resetState = () => {
    setProgress({ current: 0, total: 0, percentage: 0, processing: false });
    setCompressedImages([]);
    setCompressedPreviews([]);
    setOriginalSizes([]);
    setCompressedSizes([]);
    setSelectedImageIndexes([]);
  };

  // 模态框关闭时重置状态
  useEffect(() => {
    if (!visible) {
      resetState();
    } else {
      // 计算原始文件大小
      const sizes = images.map(img => img.size);
      setOriginalSizes(sizes);
      // 默认选择所有图片
      setSelectedImageIndexes(images.map((_, index) => index));
    }
  }, [visible, images]);

  // 计算压缩后的尺寸
  const calculateSize = (originalWidth: number, originalHeight: number, maxWidth: number) => {
    if (!settings.maintainAspectRatio) {
      return { width: maxWidth, height: maxWidth };
    }

    if (originalWidth <= maxWidth && originalHeight <= maxWidth) {
      return { width: originalWidth, height: originalHeight };
    }

    const aspectRatio = originalWidth / originalHeight;
    
    if (originalWidth > originalHeight) {
      return {
        width: maxWidth,
        height: Math.round(maxWidth / aspectRatio)
      };
    } else {
      return {
        width: Math.round(maxWidth * aspectRatio),
        height: maxWidth
      };
    }
  };

  // 压缩单张图片
  const compressImage = (file: File, settings: CompressionSettings): Promise<{ file: File; preview: string; size: number }> => {
    return new Promise((resolve, reject) => {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      const img = new Image();

      img.onload = () => {
        try {
          const { width, height } = calculateSize(img.width, img.height, settings.maxWidth);
          
          canvas.width = width;
          canvas.height = height;

          // 绘制压缩图片
          if (ctx) {
            ctx.drawImage(img, 0, 0, width, height);
            
            // 转换为blob
            canvas.toBlob((blob) => {
              if (blob) {
                // 创建新的File对象
                const compressedFile = new File([blob], file.name, {
                  type: 'image/jpeg',
                  lastModified: Date.now()
                });

                // 创建预览URL
                const preview = URL.createObjectURL(blob);

                resolve({
                  file: compressedFile,
                  preview,
                  size: blob.size
                });
              } else {
                reject(new Error('压缩失败'));
              }
            }, 'image/jpeg', settings.quality);
          } else {
            reject(new Error('无法获取Canvas上下文'));
          }
        } catch (error) {
          reject(error);
        }
      };

      img.onerror = () => {
        reject(new Error('图片加载失败'));
      };

      img.src = URL.createObjectURL(file);
    });
  };

  // 批量压缩图片
  const handleCompress = async () => {
    if (selectedImageIndexes.length === 0) {
      return;
    }
    
    setProgress({ current: 0, total: selectedImageIndexes.length, percentage: 0, processing: true });
    
    // 创建结果数组，包含所有图片的位置，未选中的保持原样
    const compressed: File[] = [...images];
    const previews: string[] = [...imagePreviews];
    const sizes: number[] = [...originalSizes];

    try {
      for (let i = 0; i < selectedImageIndexes.length; i++) {
        const imageIndex = selectedImageIndexes[i];
        const result = await compressImage(images[imageIndex], settings);
        
        compressed[imageIndex] = result.file;
        previews[imageIndex] = result.preview;
        sizes[imageIndex] = result.size;

        const current = i + 1;
        const percentage = Math.round((current / selectedImageIndexes.length) * 100);
        
        setProgress({ current, total: selectedImageIndexes.length, percentage, processing: true });
      }

      setCompressedImages(compressed);
      setCompressedPreviews(previews);
      setCompressedSizes(sizes);
      setProgress(prev => ({ ...prev, processing: false }));
    } catch (error) {
      console.error('压缩失败:', error);
      setProgress(prev => ({ ...prev, processing: false }));
    }
  };

  // 确认压缩结果
  const handleConfirm = () => {
    onConfirm(compressedImages, compressedPreviews);
  };

  // 格式化文件大小
  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  // 计算总体压缩比例
  const getTotalCompressionRatio = () => {
    const totalOriginal = selectedImageIndexes.reduce((sum, index) => sum + originalSizes[index], 0);
    const totalCompressed = selectedImageIndexes.reduce((sum, index) => sum + compressedSizes[index], 0);
    
    if (totalOriginal === 0) return 0;
    return Math.round((1 - totalCompressed / totalOriginal) * 100);
  };

  // 处理图片选择
  const handleImageSelect = (index: number, checked: boolean) => {
    if (checked) {
      setSelectedImageIndexes(prev => [...prev, index].sort((a, b) => a - b));
    } else {
      setSelectedImageIndexes(prev => prev.filter(i => i !== index));
    }
  };

  // 全选/取消全选
  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedImageIndexes(images.map((_, index) => index));
    } else {
      setSelectedImageIndexes([]);
    }
  };

  return (
    <Modal
      title={
        <div className={styles.modalTitle}>
          <CompressOutlined />
          <span>图片压缩</span>
        </div>
      }
      open={visible}
      onCancel={onCancel}
      width={800}
      centered
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onCancel}>
          取消
        </Button>,
        <Button 
          key="compress" 
          type="primary" 
          onClick={handleCompress}
          disabled={progress.processing || selectedImageIndexes.length === 0}
          loading={progress.processing}
        >
          {progress.processing ? '压缩中...' : `压缩选中的图片 (${selectedImageIndexes.length})`}
        </Button>,
        <Button 
          key="confirm" 
          type="primary" 
          onClick={handleConfirm}
          disabled={compressedImages.length === 0}
          className={styles.confirmButton}
        >
          <CheckOutlined />
          确认使用压缩结果
        </Button>
      ]}
      className={styles.compressorModal}
    >
      <div className={styles.compressorContent}>
        {/* 图片选择 */}
        <Card 
          title={
            <div className={styles.selectionTitle}>
              <PictureOutlined />
              <span>选择要压缩的图片</span>
              <Checkbox
                checked={selectedImageIndexes.length === images.length}
                indeterminate={selectedImageIndexes.length > 0 && selectedImageIndexes.length < images.length}
                onChange={(e) => handleSelectAll(e.target.checked)}
                className={styles.selectAllCheckbox}
              >
                全选 ({selectedImageIndexes.length}/{images.length})
              </Checkbox>
            </div>
          }
          className={styles.selectionCard}
        >
          <div className={styles.imageSelectionGrid}>
            {images.map((image, index) => (
              <div 
                key={index} 
                className={`${styles.imageSelectionItem} ${
                  selectedImageIndexes.includes(index) ? styles.selected : ''
                }`}
                onClick={() => handleImageSelect(index, !selectedImageIndexes.includes(index))}
              >
                <Checkbox
                  checked={selectedImageIndexes.includes(index)}
                  onChange={(e) => {
                    e.stopPropagation();
                    handleImageSelect(index, e.target.checked);
                  }}
                  className={styles.imageCheckbox}
                />
                <div className={styles.imagePreview}>
                  <img src={imagePreviews[index]} alt={`图片 ${index + 1}`} />
                </div>
                <div className={styles.imageDetails}>
                  <Text className={styles.imageName}>{image.name}</Text>
                  <Text type="secondary" className={styles.imageSize}>
                    {formatFileSize(image.size)}
                  </Text>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* 压缩设置 */}
        <Card title="压缩设置" className={styles.settingsCard}>
          <Row gutter={[16, 16]}>
            <Col span={24}>
              <div className={styles.settingItem}>
                <Text strong>最大宽度：{settings.maxWidth}px</Text>
                <Slider
                  min={256}
                  max={2048}
                  step={64}
                  value={settings.maxWidth}
                  onChange={(value) => setSettings(prev => ({ ...prev, maxWidth: value }))}
                  marks={{
                    256: '256px',
                    512: '512px',
                    1024: '1024px',
                    1536: '1536px',
                    2048: '2048px'
                  }}
                  className={styles.slider}
                />
              </div>
            </Col>
            
            <Col span={24}>
              <div className={styles.settingItem}>
                <Text strong>图片质量：{Math.round(settings.quality * 100)}%</Text>
                <Slider
                  min={0.1}
                  max={1}
                  step={0.1}
                  value={settings.quality}
                  onChange={(value) => setSettings(prev => ({ ...prev, quality: value }))}
                  marks={{
                    0.1: '10%',
                    0.3: '30%',
                    0.5: '50%',
                    0.7: '70%',
                    0.8: '80%',
                    0.9: '90%',
                    1: '100%'
                  }}
                  className={styles.slider}
                />
              </div>
            </Col>

            <Col span={24}>
              <div className={styles.settingItem}>
                <Text strong>保持宽高比</Text>
                <Switch
                  checked={settings.maintainAspectRatio}
                  onChange={(checked) => setSettings(prev => ({ ...prev, maintainAspectRatio: checked }))}
                />
              </div>
            </Col>
          </Row>
        </Card>

        {/* 压缩进度 */}
        {progress.processing && (
          <Card title="压缩进度" className={styles.progressCard}>
            <Progress
              percent={progress.percentage}
              status={progress.processing ? 'active' : 'success'}
              format={(percent) => `${progress.current}/${progress.total} (${percent}%)`}
            />
          </Card>
        )}

        {/* 压缩结果 */}
        {compressedImages.length > 0 && (
          <Card 
            title={
              <div className={styles.resultTitle}>
                <FileImageOutlined />
                <span>压缩结果</span>
                <div className={styles.compressionSummary}>
                  压缩率：{getTotalCompressionRatio()}%
                </div>
              </div>
            } 
            className={styles.resultCard}
          >
            <div className={styles.resultSummary}>
              <Row gutter={[16, 8]}>
                <Col span={8}>
                  <Text strong>原始大小：</Text>
                  <Text>{formatFileSize(selectedImageIndexes.reduce((sum, index) => sum + originalSizes[index], 0))}</Text>
                </Col>
                <Col span={8}>
                  <Text strong>压缩后：</Text>
                  <Text>{formatFileSize(selectedImageIndexes.reduce((sum, index) => sum + compressedSizes[index], 0))}</Text>
                </Col>
                <Col span={8}>
                  <Text strong>节省空间：</Text>
                  <Text type="success">
                    {formatFileSize(selectedImageIndexes.reduce((sum, index) => sum + originalSizes[index], 0) - selectedImageIndexes.reduce((sum, index) => sum + compressedSizes[index], 0))}
                  </Text>
                </Col>
              </Row>
            </div>

            <Divider />

            <div className={styles.imageGrid}>
              {selectedImageIndexes.map((index) => (
                <div key={index} className={styles.imageComparison}>
                  <div className={styles.imageItem}>
                    <img src={imagePreviews[index]} alt={`原图 ${index + 1}`} />
                    <div className={styles.imageInfo}>
                      <Text>原图</Text>
                      <Text type="secondary">{formatFileSize(originalSizes[index])}</Text>
                    </div>
                  </div>
                  
                  <div className={styles.arrow}>→</div>
                  
                  <div className={styles.imageItem}>
                    <img src={compressedPreviews[index]} alt={`压缩 ${index + 1}`} />
                    <div className={styles.imageInfo}>
                      <Text>压缩后</Text>
                      <Text type="success">{formatFileSize(compressedSizes[index])}</Text>
                      <Text type="secondary">
                        ({Math.round((1 - compressedSizes[index] / originalSizes[index]) * 100)}%)
                      </Text>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </Modal>
  );
};

export default ImageCompressor; 