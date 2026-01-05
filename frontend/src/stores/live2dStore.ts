import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface Live2DModel {
  id: string;
  name: string;
  url: string;
  category: 'female' | 'male' | 'animal';
  description?: string;
}

export const availableModels: Live2DModel[] = [
  // 女性角色
  { id: 'shizuku', name: '雫（可爱女生）', url: 'https://unpkg.com/live2d-widget-model-shizuku@1.0.5/assets/shizuku.model.json', category: 'female', description: '粉色双马尾少女' },
  { id: 'miku', name: '初音未来', url: 'https://unpkg.com/live2d-widget-model-miku@1.0.5/assets/miku.model.json', category: 'female', description: '经典虚拟歌姬' },
  { id: 'koharu', name: '小春（黑发女生）', url: 'https://unpkg.com/live2d-widget-model-koharu@1.0.5/assets/koharu.model.json', category: 'female', description: '黑发短发少女' },
  { id: 'chitose', name: '千岁（温柔男生）', url: 'https://unpkg.com/live2d-widget-model-chitose@1.0.5/assets/chitose.model.json', category: 'male', description: '温柔男生' },
  { id: 'haru-01', name: '春·白衣', url: 'https://unpkg.com/live2d-widget-model-haru@1.0.5/01/assets/haru01.model.json', category: 'female', description: '白色连衣裙' },
  { id: 'haru-02', name: '春·黑衣', url: 'https://unpkg.com/live2d-widget-model-haru@1.0.5/02/assets/haru02.model.json', category: 'female', description: '黑色连衣裙' },
  { id: 'hibiki', name: '响（活力女孩）', url: 'https://unpkg.com/live2d-widget-model-hibiki@1.0.5/assets/hibiki.model.json', category: 'female', description: '活力少女' },
  { id: 'izumi', name: '泉（清纯女生）', url: 'https://unpkg.com/live2d-widget-model-izumi@1.0.5/assets/izumi.model.json', category: 'female', description: '清纯少女' },
  { id: 'nico', name: '妮可（双马尾）', url: 'https://unpkg.com/live2d-widget-model-nico@1.0.5/assets/nico.model.json', category: 'female', description: '双马尾少女' },
  { id: 'tsumiki', name: '积木（呆萌女孩）', url: 'https://unpkg.com/live2d-widget-model-tsumiki@1.0.5/assets/tsumiki.model.json', category: 'female', description: '呆萌可爱' },
  { id: 'unitychan', name: 'Unity酱', url: 'https://unpkg.com/live2d-widget-model-unitychan@1.0.5/assets/unitychan.model.json', category: 'female', description: 'Unity官方吉祥物' },
  { id: 'z16', name: 'Z16（舰娘）', url: 'https://unpkg.com/live2d-widget-model-z16@1.0.5/assets/z16.model.json', category: 'female', description: '战舰少女' },
  
  // 男性角色
  { id: 'haruto', name: '春斗（阳光男孩）', url: 'https://unpkg.com/live2d-widget-model-haruto@1.0.5/assets/haruto.model.json', category: 'male', description: '阳光少年' },
  { id: 'nito', name: '尼托（帅气男生）', url: 'https://unpkg.com/live2d-widget-model-nito@1.0.5/assets/nito.model.json', category: 'male', description: '帅气少年' },
  
  // 动物/其他
  { id: 'hijiki', name: '羊栖菜（猫娘）', url: 'https://unpkg.com/live2d-widget-model-hijiki@1.0.5/assets/hijiki.model.json', category: 'animal', description: '可爱猫娘' },
  { id: 'tororo', name: '萝卜（兔娘）', url: 'https://unpkg.com/live2d-widget-model-tororo@1.0.5/assets/tororo.model.json', category: 'animal', description: '可爱兔娘' },
  { id: 'wanko', name: '汪子（犬娘）', url: 'https://unpkg.com/live2d-widget-model-wanko@1.0.5/assets/wanko.model.json', category: 'animal', description: '可爱犬娘' },
  { id: 'ni-j', name: 'NI-J（机器人）', url: 'https://unpkg.com/live2d-widget-model-ni-j@1.0.5/assets/ni-j.model.json', category: 'animal', description: '机器人角色' },
  { id: 'nipsilon', name: 'Nipsilon（机械）', url: 'https://unpkg.com/live2d-widget-model-nipsilon@1.0.5/assets/nipsilon.model.json', category: 'animal', description: '机械角色' },
];

interface Live2DState {
  currentModel: string;
  setModel: (modelId: string) => void;
  getModelUrl: () => string;
}

export const useLive2DStore = create<Live2DState>()(
  persist(
    (set, get) => ({
      currentModel: 'shizuku',
      
      setModel: (modelId: string) => {
        set({ currentModel: modelId });
      },
      
      getModelUrl: () => {
        const { currentModel } = get();
        const model = availableModels.find(m => m.id === currentModel);
        return model?.url || availableModels[0].url;
      },
    }),
    {
      name: 'live2d-model-storage',
    }
  )
);
