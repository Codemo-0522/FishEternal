export interface Live2DConfig {
  enabled: boolean;
  models: {
    [key: string]: string;
  };
  display: {
    position: 'left' | 'right';
    width: number;
    height: number;
    hOffset: number;
    vOffset: number;
  };
  mobile: {
    show: boolean;
    scale: number;
  };
  react: {
    opacity: number;
    opacityDefault: number;
    opacityOnHover: number;
  };
}

export const live2dConfig: Live2DConfig = {
  enabled: true,
  models: {
    light: 'https://unpkg.com/live2d-widget-model-hijiki@1.0.5/assets/hijiki.model.json',
    dark: 'https://unpkg.com/live2d-widget-model-koharu@1.0.5/assets/koharu.model.json',
    romantic: 'https://unpkg.com/live2d-widget-model-shizuku@1.0.5/assets/shizuku.model.json',
  },
  display: {
    position: 'right',
    width: 150,
    height: 300,
    hOffset: 0,
    vOffset: 0
  },
  mobile: {
    show: true,
    scale: 1.0
  },
  react: {
    opacity: 0.85,
    opacityDefault: 0.85,
    opacityOnHover: 0.2
  }
};
