import React, { useState, useRef, useCallback } from 'react';
import ReactCrop, { Crop, PixelCrop, centerCrop, makeAspectCrop } from 'react-image-crop';
import 'react-image-crop/dist/ReactCrop.css';
import { Button, Modal, Radio } from 'antd';
import styles from './AvatarCropper.module.css';

interface AvatarCropperProps {
  visible: boolean;
  imageUrl: string;
  onCancel: () => void;
  onConfirm: (croppedImage: string) => void;
}

const AvatarCropper: React.FC<AvatarCropperProps> = ({
  visible,
  imageUrl,
  onCancel,
  onConfirm
}) => {
  const [crop, setCrop] = useState<Crop>();
  const [completedCrop, setCompletedCrop] = useState<PixelCrop>();
  const [cropMode, setCropMode] = useState<'square' | 'circle'>('square');
  const imgRef = useRef<HTMLImageElement>(null);

  // 创建1:1的居中裁剪框
  const onImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const { width, height } = e.currentTarget;
    const crop = centerCrop(
      makeAspectCrop(
        {
          unit: '%',
          width: 80,
        },
        1,
        width,
        height
      ),
      width,
      height
    );
    setCrop(crop);
  }, []);

  // 裁剪图片
  const getCroppedImg = useCallback(() => {
    if (!imgRef.current || !completedCrop) return;

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    if (!ctx) return;

    const scaleX = imgRef.current.naturalWidth / imgRef.current.width;
    const scaleY = imgRef.current.naturalHeight / imgRef.current.height;

    canvas.width = completedCrop.width * scaleX;
    canvas.height = completedCrop.height * scaleY;

    ctx.drawImage(
      imgRef.current,
      completedCrop.x * scaleX,
      completedCrop.y * scaleY,
      completedCrop.width * scaleX,
      completedCrop.height * scaleY,
      0,
      0,
      completedCrop.width * scaleX,
      completedCrop.height * scaleY
    );

    return new Promise<string>((resolve) => {
      canvas.toBlob((blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          resolve(url);
        }
      }, 'image/jpeg', 0.9);
    });
  }, [completedCrop]);

  // 确认裁剪
  const handleConfirm = async () => {
    if (!completedCrop) return;
    
    const croppedImageUrl = await getCroppedImg();
    if (croppedImageUrl) {
      onConfirm(croppedImageUrl);
    }
  };

  return (
    <Modal
      title="头像裁剪"
      open={visible}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          取消
        </Button>,
        <Button 
          key="confirm" 
          type="primary" 
          onClick={handleConfirm}
          disabled={!completedCrop}
        >
          确认裁剪
        </Button>
      ]}
      width="90%"
      style={{ maxWidth: '600px' }}
      centered
      destroyOnClose
    >
      <div className={styles.modalContent}>
        {/* 裁剪模式选择 */}
        <div className={styles.cropModeSelection}>
          <Radio.Group 
            value={cropMode} 
            onChange={(e) => setCropMode(e.target.value)}
            style={{ marginBottom: '10px' }}
          >
            <Radio.Button value="square">方形裁剪</Radio.Button>
            <Radio.Button value="circle">圆形裁剪</Radio.Button>
          </Radio.Group>
          <div className={styles.cropModeDescription}>
            {cropMode === 'square' ? '选择方形区域，最终显示为圆形头像' : '直接使用圆形裁剪框'}
          </div>
        </div>

        {/* 裁剪区域 */}
        <div className={`${styles.cropArea} ${cropMode === 'circle' ? styles.circular : ''}`}>
          <ReactCrop
            crop={crop}
            onChange={(_, percentCrop) => setCrop(percentCrop)}
            onComplete={(c) => setCompletedCrop(c)}
            aspect={1}
            circularCrop={cropMode === 'circle'}
            minWidth={80}
            minHeight={80}
          >
            <img
              ref={imgRef}
              alt="裁剪图片"
              src={imageUrl}
              onLoad={onImageLoad}
              className={styles.cropImage}
            />
          </ReactCrop>
        </div>

        {/* 预览区域 */}
        {completedCrop && (
          <div className={styles.previewSection}>
            <div className={styles.previewTitle}>
              预览效果：
            </div>
            <div className={styles.previewContainer}>
              <canvas
                ref={(canvas) => {
                  if (canvas && completedCrop && imgRef.current) {
                    const ctx = canvas.getContext('2d');
                    if (ctx) {
                      canvas.width = 80;
                      canvas.height = 80;
                      
                      const scaleX = imgRef.current.naturalWidth / imgRef.current.width;
                      const scaleY = imgRef.current.naturalHeight / imgRef.current.height;
                      
                      ctx.drawImage(
                        imgRef.current,
                        completedCrop.x * scaleX,
                        completedCrop.y * scaleY,
                        completedCrop.width * scaleX,
                        completedCrop.height * scaleY,
                        0, 0, 80, 80
                      );
                    }
                  }
                }}
                className={styles.previewCanvas}
              />
            </div>
          </div>
        )}

        <p className={styles.instructions}>
          {cropMode === 'square' 
            ? '拖动和调整方形裁剪框，选择想要显示的区域，最终将显示为圆形头像'
            : '拖动和调整圆形裁剪框，确保头像显示最佳效果'
          }
        </p>
      </div>
    </Modal>
  );
};

export default AvatarCropper; 