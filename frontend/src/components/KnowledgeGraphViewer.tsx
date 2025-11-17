import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Modal, Button, Select, Card, Tooltip, message, Input, Badge } from 'antd';
import { 
  NodeIndexOutlined, 
  BranchesOutlined, 
  ZoomInOutlined, 
  ZoomOutOutlined,
  FullscreenOutlined,
  DownloadOutlined
} from '@ant-design/icons';
import type { GraphMetadata } from '../pages/Chat/Chat';
import './KnowledgeGraphViewer.css';

interface KnowledgeGraphViewerProps {
  visible: boolean;
  graphDataList: GraphMetadata[];
  onClose: () => void;
}

interface Node {
  id: string;
  label: string;
  properties: {
    type: string;
    [key: string]: any;
  };
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface Edge {
  source: string;
  target: string;
  relation: string;
  properties: {
    type: string;
    [key: string]: any;
  };
}

// 节点类型配置
const NODE_STYLES = {
  author: {
    color: '#9254de',
    gradient: ['#d3adf7', '#9254de', '#531dab'],
    icon: '👤',
    label: '作者'
  },
  paper: {
    color: '#1890ff',
    gradient: ['#91d5ff', '#1890ff', '#0050b3'],
    icon: '📄',
    label: '论文'
  },
  field: {
    color: '#52c41a',
    gradient: ['#95de64', '#52c41a', '#237804'],
    icon: '🏷️',
    label: '领域'
  },
  venue: {
    color: '#fa8c16',
    gradient: ['#ffc53d', '#fa8c16', '#ad4e00'],
    icon: '📚',
    label: '期刊'
  },
  reference: {
    color: '#bfbfbf',
    gradient: ['#f0f0f0', '#bfbfbf', '#8c8c8c'],
    icon: '🔗',
    label: '引用'
  }
} as const;

const KnowledgeGraphViewer: React.FC<KnowledgeGraphViewerProps> = ({
  visible,
  graphDataList,
  onClose
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  
  // 使用 ref 存储拖动状态，避免鼠标按下时触发重渲染导致闪烁
  const draggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  
  const [currentGraphIndex, setCurrentGraphIndex] = useState(0);
  const [searchNode, setSearchNode] = useState('');
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [hoveredNode, setHoveredNode] = useState<Node | null>(null);
  const [canvasSize] = useState({ width: 1200, height: 700 });
  const [connectedNodeIds, setConnectedNodeIds] = useState<Set<string>>(new Set());

  const currentGraph = graphDataList[currentGraphIndex];

  // 获取节点样式
  const getNodeStyle = (type: string) => {
    return NODE_STYLES[type as keyof typeof NODE_STYLES] || {
      color: '#8c8c8c',
      gradient: ['#d9d9d9', '#8c8c8c', '#595959'],
      icon: '⚪',
      label: '未知'
    };
  };

  // 力导向布局算法（优化版 - 避免重叠）
  const calculateLayout = useCallback((graphData: GraphMetadata) => {
    const width = canvasSize.width;
    const height = canvasSize.height;
    const centerX = width / 2;
    const centerY = height / 2;

    // 使用确定性随机（基于节点ID），避免每次打开位置不同
    const seededRandom = (seed: string) => {
      let hash = 0;
      for (let i = 0; i < seed.length; i++) {
        hash = ((hash << 5) - hash) + seed.charCodeAt(i);
        hash = hash & hash;
      }
      return (Math.abs(hash) % 1000) / 1000;
    };

    // 🔥 优化：使用随机分布初始化，避免圆形排列
    const layoutNodes: Node[] = graphData.nodes.map((node) => {
      const random1 = seededRandom(node.id + '_x');
      const random2 = seededRandom(node.id + '_y');
      
      // 在画布内随机分布，但避开中心区域（给主要节点留空间）
      const spreadRadius = Math.min(width, height) * 0.35;
      const angle = random1 * 2 * Math.PI;
      const radius = spreadRadius * (0.3 + random2 * 0.7); // 不要太集中在中心
      
      const newNode: Node = {
        ...node,
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        properties: {
          type: node.properties?.type || 'unknown',
          ...node.properties
        }
      };
      
      return newNode;
    });

    // 🔥 优化的力导向布局参数 - 根据节点类型设置不同的物理属性
    const iterations = 600; // 增加迭代次数以达到更稳定的布局
    
    // 🎯 根据节点类型定义不同的物理属性
    const getNodeProperties = (node: Node) => {
      const type = node.properties?.type || 'unknown';
      switch (type) {
        case 'Paper':
          return {
            mass: 5.0,           // 论文质量最大，不易被推动
            repulsion: 8.0,      // 论文之间的排斥力最强
            minDistance: 200,    // 论文之间的最小距离
            radius: 45           // 论文节点视觉半径
          };
        case 'Author':
          return {
            mass: 2.0,
            repulsion: 3.0,
            minDistance: 120,
            radius: 40
          };
        case 'Keyword':
          return {
            mass: 1.5,
            repulsion: 2.5,
            minDistance: 100,
            radius: 35
          };
        case 'Reference':
          return {
            mass: 1.2,
            repulsion: 2.0,
            minDistance: 90,
            radius: 30
          };
        default:
          return {
            mass: 1.0,
            repulsion: 1.5,
            minDistance: 80,
            radius: 30
          };
      }
    };
    
    for (let iteration = 0; iteration < iterations; iteration++) {
      // 非线性冷却曲线，前期快速移动，后期精细调整
      const progress = iteration / iterations;
      const coolingFactor = Math.pow(1 - progress, 1.5);

      // 1. 🔥 基于节点类型的分层排斥力（库仑力模型）
      for (let i = 0; i < layoutNodes.length; i++) {
        for (let j = i + 1; j < layoutNodes.length; j++) {
          const node1 = layoutNodes[i];
          const node2 = layoutNodes[j];
          
          const props1 = getNodeProperties(node1);
          const props2 = getNodeProperties(node2);
          
          const dx = node2.x - node1.x;
          const dy = node2.y - node1.y;
          const distSq = dx * dx + dy * dy;
          const distance = Math.sqrt(distSq) || 0.1;
          
          // 计算两个节点之间应该保持的最小距离（取较大值）
          const requiredMinDistance = Math.max(props1.minDistance, props2.minDistance);
          
          // 计算综合排斥力系数（论文之间排斥力最强）
          const repulsionStrength = Math.sqrt(props1.repulsion * props2.repulsion);
          
          // 使用距离平方的反比力，更真实的排斥效果
          let force = 0;
          if (distance < requiredMinDistance) {
            // 非常近时施加强力，力度与节点类型相关
            const overlapRatio = (requiredMinDistance - distance) / requiredMinDistance;
            force = repulsionStrength * Math.pow(overlapRatio, 2) * 15;
          } else if (distance < requiredMinDistance * 1.5) {
            // 中等距离施加温和排斥
            force = repulsionStrength * (requiredMinDistance / distance) * 2 * coolingFactor;
          } else if (distance < requiredMinDistance * 2.5) {
            // 远距离弱排斥
            force = repulsionStrength * (requiredMinDistance / distance) * 0.5 * coolingFactor;
          }
          
          if (force > 0) {
            const fx = (dx / distance) * force;
            const fy = (dy / distance) * force;
            
            // 根据质量分配力的影响（质量大的节点不易被推动）
            const mass1 = props1.mass;
            const mass2 = props2.mass;
            const totalMass = mass1 + mass2;
            
            node1.vx -= fx * (mass2 / totalMass);
            node1.vy -= fy * (mass2 / totalMass);
            node2.vx += fx * (mass1 / totalMass);
            node2.vy += fy * (mass1 / totalMass);
          }
        }
      }

      // 2. 🔥 优化的边吸引力（弹簧力模型）- 考虑节点类型
      graphData.edges.forEach(edge => {
        const source = layoutNodes.find(n => n.id === edge.source);
        const target = layoutNodes.find(n => n.id === edge.target);
        if (source && target) {
          const propsSource = getNodeProperties(source);
          const propsTarget = getNodeProperties(target);
          
          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const distance = Math.sqrt(dx * dx + dy * dy) || 0.1;
          
          // 根据节点类型动态计算理想边长
          const idealDistance = (propsSource.minDistance + propsTarget.minDistance) / 2;
          
          // 胡克定律：力与位移成正比
          const displacement = distance - idealDistance;
          const springStrength = 0.08; // 降低弹簧系数，让布局更松散
          const force = displacement * springStrength * coolingFactor;
          
          const fx = (dx / distance) * force;
          const fy = (dy / distance) * force;
          
          // 根据质量分配力的影响
          const massSource = propsSource.mass;
          const massTarget = propsTarget.mass;
          const totalMass = massSource + massTarget;
          
          source.vx += fx * (massTarget / totalMass);
          source.vy += fy * (massTarget / totalMass);
          target.vx -= fx * (massSource / totalMass);
          target.vy -= fy * (massSource / totalMass);
        }
      });

      // 3. 🔥 自适应中心引力（边缘节点施加更强的力）- 论文节点优先居中
      layoutNodes.forEach(node => {
        const props = getNodeProperties(node);
        const dx = centerX - node.x;
        const dy = centerY - node.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        if (distance > 0) {
          // 距离中心越远，引力越强
          const maxRadius = Math.min(width, height) * 0.42;
          const distanceRatio = Math.max(0, (distance - maxRadius) / maxRadius);
          
          // 论文节点受到更强的中心引力，保持在中心区域
          const centerGravity = props.mass > 3 ? 0.005 : 0.003;
          const force = distance * centerGravity * (1 + distanceRatio * 2) * coolingFactor;
          
          node.vx += (dx / distance) * force;
          node.vy += (dy / distance) * force;
        }
      });

      // 4. 🔥 添加网格对齐避免（防止节点排成直线）
      if (iteration % 10 === 0) {
        for (let i = 0; i < layoutNodes.length; i++) {
          for (let j = i + 1; j < layoutNodes.length; j++) {
            const props1 = getNodeProperties(layoutNodes[i]);
            const props2 = getNodeProperties(layoutNodes[j]);
            const avgMinDistance = (props1.minDistance + props2.minDistance) / 2;
            
            const dx = Math.abs(layoutNodes[j].x - layoutNodes[i].x);
            const dy = Math.abs(layoutNodes[j].y - layoutNodes[i].y);
            
            // 检测是否在同一水平线或垂直线上
            if (dx < avgMinDistance * 0.3 || dy < avgMinDistance * 0.3) {
              const repelStrength = 2 * coolingFactor;
              // 添加垂直于对齐方向的扰动
              if (dx < avgMinDistance * 0.3) {
                layoutNodes[j].vy += (seededRandom(layoutNodes[j].id + iteration) - 0.5) * repelStrength;
              }
              if (dy < avgMinDistance * 0.3) {
                layoutNodes[j].vx += (seededRandom(layoutNodes[j].id + iteration) - 0.5) * repelStrength;
              }
            }
          }
        }
      }

      // 5. 更新位置 - 根据节点质量调整运动
      layoutNodes.forEach(node => {
        const props = getNodeProperties(node);
        
        // 限制最大速度，避免振荡（质量大的节点移动更慢）
        const maxVelocity = (20 / props.mass) * coolingFactor;
        const velocitySq = node.vx * node.vx + node.vy * node.vy;
        if (velocitySq > maxVelocity * maxVelocity) {
          const velocity = Math.sqrt(velocitySq);
          node.vx = (node.vx / velocity) * maxVelocity;
          node.vy = (node.vy / velocity) * maxVelocity;
        }
        
        node.x += node.vx;
        node.y += node.vy;
        
        // 速度阻尼（模拟摩擦力）- 质量大的节点阻尼更大
        const damping = 0.85 - (props.mass * 0.02);
        node.vx *= damping;
        node.vy *= damping;

        // 软边界约束（在边界附近施加反向力）
        const margin = 100;
        const softMargin = 150;
        
        if (node.x < softMargin) {
          node.vx += (softMargin - node.x) * 0.05;
        } else if (node.x > width - softMargin) {
          node.vx -= (node.x - (width - softMargin)) * 0.05;
        }
        
        if (node.y < softMargin) {
          node.vy += (softMargin - node.y) * 0.05;
        } else if (node.y > height - softMargin) {
          node.vy -= (node.y - (height - softMargin)) * 0.05;
        }
        
        // 硬边界（不能超出）
        node.x = Math.max(margin, Math.min(width - margin, node.x));
        node.y = Math.max(margin, Math.min(height - margin, node.y));
      });
    }

    // 6. 🔥 最终碰撞检测和分离（多轮检测确保无重叠）- 考虑节点类型
    for (let round = 0; round < 8; round++) {
      let hasOverlap = false;
      for (let i = 0; i < layoutNodes.length; i++) {
        for (let j = i + 1; j < layoutNodes.length; j++) {
          const node1 = layoutNodes[i];
          const node2 = layoutNodes[j];
          
          const props1 = getNodeProperties(node1);
          const props2 = getNodeProperties(node2);
          
          const dx = node2.x - node1.x;
          const dy = node2.y - node1.y;
          const distance = Math.sqrt(dx * dx + dy * dy);
          
          // 使用节点类型定义的最小距离
          const requiredMinDist = Math.max(props1.minDistance, props2.minDistance) * 0.9;
          
          if (distance < requiredMinDist && distance > 0) {
            hasOverlap = true;
            // 沿连线方向分离，根据质量分配移动距离
            const angle = Math.atan2(dy, dx);
            const overlap = requiredMinDist - distance;
            
            // 质量大的节点移动距离小
            const mass1 = props1.mass;
            const mass2 = props2.mass;
            const totalMass = mass1 + mass2;
            
            const move1 = overlap * (mass2 / totalMass);
            const move2 = overlap * (mass1 / totalMass);
            
            node1.x -= Math.cos(angle) * move1;
            node1.y -= Math.sin(angle) * move1;
            node2.x += Math.cos(angle) * move2;
            node2.y += Math.sin(angle) * move2;
            
            // 确保不超出边界
            const margin = 100;
            node1.x = Math.max(margin, Math.min(width - margin, node1.x));
            node1.y = Math.max(margin, Math.min(height - margin, node1.y));
            node2.x = Math.max(margin, Math.min(width - margin, node2.x));
            node2.y = Math.max(margin, Math.min(height - margin, node2.y));
          }
        }
      }
      if (!hasOverlap) break;
    }

    return layoutNodes;
  }, [canvasSize]);

  // 绘制玻璃态节点
  const drawGlassmorphicNode = (
    ctx: CanvasRenderingContext2D,
    node: Node,
    isSelected: boolean,
    isHovered: boolean,
    isConnected: boolean
  ) => {
    const nodeStyle = getNodeStyle(node.properties.type);
    const nodeRadius = 35;
    const scaledRadius = nodeRadius / scale;

    // 外发光效果（选中、悬停或连接时）
    if (isSelected || isHovered || isConnected) {
      const glowRadius = scaledRadius * (isHovered ? 2.2 : 1.8);
      const gradient = ctx.createRadialGradient(node.x, node.y, scaledRadius, node.x, node.y, glowRadius);
      gradient.addColorStop(0, `${nodeStyle.color}${isHovered ? '60' : '40'}`);
      gradient.addColorStop(1, 'transparent');
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(node.x, node.y, glowRadius, 0, 2 * Math.PI);
      ctx.fill();
    }

    // 玻璃态背景
    const bgGradient = ctx.createRadialGradient(
      node.x - scaledRadius * 0.3,
      node.y - scaledRadius * 0.3,
      0,
      node.x,
      node.y,
      scaledRadius
    );
    
    // 根据主题调整透明度
    const isDarkTheme = document.documentElement.getAttribute('data-theme') === 'dark';
    const alpha = isDarkTheme ? 0.25 : 0.15;
    
    bgGradient.addColorStop(0, `${nodeStyle.gradient[0]}${Math.floor(alpha * 255).toString(16).padStart(2, '0')}`);
    bgGradient.addColorStop(0.5, `${nodeStyle.gradient[1]}${Math.floor(alpha * 255).toString(16).padStart(2, '0')}`);
    bgGradient.addColorStop(1, `${nodeStyle.gradient[2]}${Math.floor(alpha * 255).toString(16).padStart(2, '0')}`);
    
    ctx.fillStyle = bgGradient;
    ctx.beginPath();
    ctx.arc(node.x, node.y, scaledRadius, 0, 2 * Math.PI);
    ctx.fill();

    // 玻璃边框（连接节点也高亮）
    ctx.strokeStyle = nodeStyle.color + (isSelected ? 'ff' : isHovered ? 'ff' : isConnected ? 'cc' : '99');
    ctx.lineWidth = (isSelected ? 3 : isHovered ? 3 : isConnected ? 2.5 : 2) / scale;
    ctx.stroke();

    // 内部高光
    const highlightGradient = ctx.createRadialGradient(
      node.x - scaledRadius * 0.4,
      node.y - scaledRadius * 0.4,
      0,
      node.x,
      node.y,
      scaledRadius * 0.8
    );
    highlightGradient.addColorStop(0, 'rgba(255, 255, 255, 0.4)');
    highlightGradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
    
    ctx.fillStyle = highlightGradient;
    ctx.beginPath();
    ctx.arc(node.x, node.y, scaledRadius * 0.6, 0, 2 * Math.PI);
    ctx.fill();

    // 绘制图标
    ctx.font = `${24 / scale}px Arial`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(nodeStyle.icon, node.x, node.y);

    // 节点标签（带背景）- 悬停时显示完整名称
    const showFullLabel = isHovered;
    const label = showFullLabel ? node.label : (node.label.length > 15 ? node.label.substring(0, 15) + '...' : node.label);
    const labelY = node.y + scaledRadius + 20 / scale;
    
    ctx.font = `${13 / scale}px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    
    // 标签背景
    const textMetrics = ctx.measureText(label);
    const padding = 6 / scale;
    const labelBgX = node.x - textMetrics.width / 2 - padding;
    const labelBgY = labelY - padding;
    const labelBgWidth = textMetrics.width + padding * 2;
    const labelBgHeight = 13 / scale + padding * 2;
    
    ctx.fillStyle = isDarkTheme ? 'rgba(0, 0, 0, 0.7)' : 'rgba(255, 255, 255, 0.9)';
    ctx.beginPath();
    ctx.roundRect(labelBgX, labelBgY, labelBgWidth, labelBgHeight, 4 / scale);
    ctx.fill();
    
    ctx.strokeStyle = nodeStyle.color + (isHovered ? 'ff' : '80');
    ctx.lineWidth = (isHovered ? 1.5 : 1) / scale;
    ctx.stroke();
    
    // 标签文字
    ctx.fillStyle = isDarkTheme ? '#ffffff' : '#262626';
    ctx.fillText(label, node.x, labelY);
  };

  // 绘制动态边
  const drawAnimatedEdge = (
    ctx: CanvasRenderingContext2D,
    edge: Edge,
    source: Node,
    target: Node,
    time: number,
    isHighlighted: boolean
  ) => {
    const isDarkTheme = document.documentElement.getAttribute('data-theme') === 'dark';
    
    // 计算边的角度
    const angle = Math.atan2(target.y - source.y, target.x - source.x);
    
    // 绘制渐变边（高亮时更明显）
    const gradient = ctx.createLinearGradient(source.x, source.y, target.x, target.y);
    if (isHighlighted) {
      // 高亮边使用更鲜艳的颜色
      const highlightColor = isDarkTheme ? 'rgba(64, 169, 255, 0.8)' : 'rgba(24, 144, 255, 0.8)';
      gradient.addColorStop(0, highlightColor);
      gradient.addColorStop(0.5, isDarkTheme ? 'rgba(64, 169, 255, 1)' : 'rgba(24, 144, 255, 1)');
      gradient.addColorStop(1, highlightColor);
    } else {
      const baseColor = isDarkTheme ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.15)';
      gradient.addColorStop(0, baseColor);
      gradient.addColorStop(0.5, isDarkTheme ? 'rgba(255, 255, 255, 0.3)' : 'rgba(0, 0, 0, 0.25)');
      gradient.addColorStop(1, baseColor);
    }
    
    ctx.strokeStyle = gradient;
    ctx.lineWidth = (isHighlighted ? 3 : 2) / scale;
    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);
    ctx.stroke();

    // 动态流动粒子（高亮时更明显）
    if (isHighlighted) {
      const particleCount = 5;
      for (let i = 0; i < particleCount; i++) {
        const progress = ((time / 1500 + i / particleCount) % 1);
        const particleX = source.x + (target.x - source.x) * progress;
        const particleY = source.y + (target.y - source.y) * progress;
        
        const particleGradient = ctx.createRadialGradient(
          particleX, particleY, 0,
          particleX, particleY, 6 / scale
        );
        particleGradient.addColorStop(0, isDarkTheme ? 'rgba(64, 169, 255, 1)' : 'rgba(24, 144, 255, 1)');
        particleGradient.addColorStop(1, 'transparent');
        
        ctx.fillStyle = particleGradient;
        ctx.beginPath();
        ctx.arc(particleX, particleY, 6 / scale, 0, 2 * Math.PI);
        ctx.fill();
      }
    } else {
      const particleCount = 3;
      for (let i = 0; i < particleCount; i++) {
        const progress = ((time / 2000 + i / particleCount) % 1);
        const particleX = source.x + (target.x - source.x) * progress;
        const particleY = source.y + (target.y - source.y) * progress;
        
        const particleGradient = ctx.createRadialGradient(
          particleX, particleY, 0,
          particleX, particleY, 4 / scale
        );
        particleGradient.addColorStop(0, isDarkTheme ? 'rgba(64, 169, 255, 0.8)' : 'rgba(24, 144, 255, 0.8)');
        particleGradient.addColorStop(1, 'transparent');
        
        ctx.fillStyle = particleGradient;
        ctx.beginPath();
        ctx.arc(particleX, particleY, 4 / scale, 0, 2 * Math.PI);
        ctx.fill();
      }
    }

    // 箭头
    const arrowSize = 12 / scale;
    const arrowX = target.x - Math.cos(angle) * 35 / scale;
    const arrowY = target.y - Math.sin(angle) * 35 / scale;
    
    ctx.fillStyle = isDarkTheme ? 'rgba(255, 255, 255, 0.6)' : 'rgba(0, 0, 0, 0.5)';
    ctx.beginPath();
    ctx.moveTo(arrowX, arrowY);
    ctx.lineTo(
      arrowX - arrowSize * Math.cos(angle - Math.PI / 6),
      arrowY - arrowSize * Math.sin(angle - Math.PI / 6)
    );
    ctx.lineTo(
      arrowX - arrowSize * Math.cos(angle + Math.PI / 6),
      arrowY - arrowSize * Math.sin(angle + Math.PI / 6)
    );
    ctx.closePath();
    ctx.fill();

    // 边标签
    if (edge.relation) {
      const midX = (source.x + target.x) / 2;
      const midY = (source.y + target.y) / 2;
      
      ctx.font = `${11 / scale}px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      
      const labelMetrics = ctx.measureText(edge.relation);
      const padding = 4 / scale;
      
      // 标签背景
      ctx.fillStyle = isDarkTheme ? 'rgba(31, 31, 31, 0.9)' : 'rgba(255, 255, 255, 0.95)';
      ctx.beginPath();
      ctx.roundRect(
        midX - labelMetrics.width / 2 - padding,
        midY - 11 / (2 * scale) - padding,
        labelMetrics.width + padding * 2,
        11 / scale + padding * 2,
        3 / scale
      );
      ctx.fill();
      
      // 标签边框
      ctx.strokeStyle = isDarkTheme ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.15)';
      ctx.lineWidth = 1 / scale;
      ctx.stroke();
      
      // 标签文字
      ctx.fillStyle = isDarkTheme ? '#d9d9d9' : '#595959';
      ctx.fillText(edge.relation, midX, midY);
    }
  };

  // 绘制图谱
  const drawGraph = useCallback((time: number = 0) => {
    if (!canvasRef.current || !nodes.length) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    // 清空画布
    const isDarkTheme = document.documentElement.getAttribute('data-theme') === 'dark';
    ctx.fillStyle = isDarkTheme ? '#141414' : '#fafafa';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    ctx.translate(offset.x, offset.y);
    ctx.scale(scale, scale);

    // 启用抗锯齿
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    // 绘制边
    edges.forEach(edge => {
      const source = nodes.find(n => n.id === edge.source);
      const target = nodes.find(n => n.id === edge.target);
      if (source && target) {
        // 判断边是否应该高亮（连接到悬停节点）
        const isHighlighted = hoveredNode && (edge.source === hoveredNode.id || edge.target === hoveredNode.id);
        drawAnimatedEdge(ctx, edge, source, target, time, !!isHighlighted);
      }
    });

    // 绘制节点
    nodes.forEach(node => {
      const isSelected = selectedNode?.id === node.id;
      const isHovered = hoveredNode?.id === node.id;
      const isConnected = hoveredNode && connectedNodeIds.has(node.id);
      drawGlassmorphicNode(ctx, node, isSelected, isHovered, !!isConnected);
    });

    ctx.restore();

    // 继续动画
    animationFrameRef.current = requestAnimationFrame(drawGraph);
  }, [nodes, edges, scale, offset, selectedNode, hoveredNode]);

  // 初始化和更新图谱
  useEffect(() => {
    if (!visible || !currentGraph) return;

    // 计算布局
    const layoutNodes = calculateLayout(currentGraph);
    setNodes(layoutNodes);
    setEdges(currentGraph.edges as Edge[]);
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setSelectedNode(null);
    setHoveredNode(null);
  }, [visible, currentGraph, calculateLayout]);

  // 获取鼠标位置对应的节点（使用useCallback避免重复创建）
  const getNodeAtPosition = useCallback((x: number, y: number): Node | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;

    const canvasRect = canvas.getBoundingClientRect();
    
    // 计算鼠标相对于画布元素的位置（CSS像素坐标）
    const mouseX = x - canvasRect.left;
    const mouseY = y - canvasRect.top;
    
    // 考虑画布的物理像素和CSS像素比例
    const scaleX = canvas.width / canvasRect.width;
    const scaleY = canvas.height / canvasRect.height;
    
    // 转换为画布物理像素坐标
    const canvasPixelX = mouseX * scaleX;
    const canvasPixelY = mouseY * scaleY;
    
    // 转换为画布逻辑坐标系
    // 绘制时：screenPos = nodePos * scale + offset
    // 反向：nodePos = (screenPos - offset) / scale
    const canvasX = (canvasPixelX - offset.x) / scale;
    const canvasY = (canvasPixelY - offset.y) / scale;

    const nodeRadius = 35;
    return nodes.find(node => {
      const dx = node.x - canvasX;
      const dy = node.y - canvasY;
      return Math.sqrt(dx * dx + dy * dy) <= nodeRadius;
    }) || null;
  }, [nodes, scale, offset]);

  // 鼠标事件处理
  const handleMouseDown = useCallback((e: MouseEvent) => {
    const node = getNodeAtPosition(e.clientX, e.clientY);
    if (!node) {
      // 使用 ref 存储拖动状态，避免触发重渲染导致闪烁
      draggingRef.current = true;
      dragStartRef.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
    }
  }, [getNodeAtPosition, offset]);

  // 使用节流优化鼠标移动性能
  const lastMoveTimeRef = useRef<number>(0);
  const mouseMoveThrottle = 16; // 约60fps
  
  const handleMouseMove = useCallback((e: MouseEvent) => {
    const now = Date.now();
    
    // 从 ref 读取拖动状态，避免依赖 state
    if (draggingRef.current) {
      // 拖动时不需要节流
      setOffset({
        x: e.clientX - dragStartRef.current.x,
        y: e.clientY - dragStartRef.current.y
      });
      if (canvasRef.current) {
        canvasRef.current.style.cursor = 'grabbing';
      }
    } else {
      // hover检测使用节流
      if (now - lastMoveTimeRef.current < mouseMoveThrottle) {
        return;
      }
      lastMoveTimeRef.current = now;
      
      const node = getNodeAtPosition(e.clientX, e.clientY);
      setHoveredNode(prev => {
        // 只在节点变化时更新状态，避免无意义的重渲染
        if (prev?.id !== node?.id) {
          // 更新连接的节点集合
          if (node) {
            const connected = new Set<string>();
            edges.forEach(edge => {
              if (edge.source === node.id) {
                connected.add(edge.target);
              } else if (edge.target === node.id) {
                connected.add(edge.source);
              }
            });
            setConnectedNodeIds(connected);
          } else {
            setConnectedNodeIds(new Set());
          }
          return node;
        }
        return prev;
      });
      if (canvasRef.current) {
        canvasRef.current.style.cursor = node ? 'pointer' : 'grab';
      }
    }
  }, [getNodeAtPosition, edges]);

  const handleMouseUp = useCallback(() => {
    draggingRef.current = false;
  }, []);

  const handleMouseLeave = useCallback(() => {
    draggingRef.current = false;
    setHoveredNode(null);
    setConnectedNodeIds(new Set());
  }, []);

  const handleClick = useCallback((e: MouseEvent) => {
    const node = getNodeAtPosition(e.clientX, e.clientY);
    setSelectedNode(node);
  }, [getNodeAtPosition]);

  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    
    const canvas = canvasRef.current;
    if (!canvas) return;
    
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    // 考虑画布的物理像素和CSS像素比例
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    
    // 转换为画布物理像素坐标
    const canvasPixelX = mouseX * scaleX;
    const canvasPixelY = mouseY * scaleY;
    
    // 计算缩放前鼠标在画布逻辑坐标系中的位置
    const worldX = (canvasPixelX - offset.x) / scale;
    const worldY = (canvasPixelY - offset.y) / scale;
    
    // 缩放
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = scale * delta;
    
    // 调整偏移使缩放中心在鼠标位置
    const newOffset = {
      x: canvasPixelX - worldX * newScale,
      y: canvasPixelY - worldY * newScale
    };
    
    setScale(newScale);
    setOffset(newOffset);
  }, [scale, offset]);

  // 初始化 Canvas
  useEffect(() => {
    if (!visible || !containerRef.current) return;

    const canvas = document.createElement('canvas');
    canvas.width = canvasSize.width;
    canvas.height = canvasSize.height;
    canvas.className = 'knowledge-graph-canvas';
      
      containerRef.current.innerHTML = '';
      containerRef.current.appendChild(canvas);
      canvasRef.current = canvas;

      // 添加鼠标事件
      canvas.addEventListener('mousedown', handleMouseDown);
      canvas.addEventListener('mousemove', handleMouseMove);
      canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseLeave);
      canvas.addEventListener('wheel', handleWheel);
    canvas.addEventListener('click', handleClick);

    return () => {
      if (canvasRef.current) {
        canvasRef.current.removeEventListener('mousedown', handleMouseDown);
        canvasRef.current.removeEventListener('mousemove', handleMouseMove);
        canvasRef.current.removeEventListener('mouseup', handleMouseUp);
        canvasRef.current.removeEventListener('mouseleave', handleMouseLeave);
        canvasRef.current.removeEventListener('wheel', handleWheel);
        canvasRef.current.removeEventListener('click', handleClick);
      }
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [visible, canvasSize, handleMouseDown, handleMouseMove, handleMouseUp, handleMouseLeave, handleWheel, handleClick]);

  // 启动绘制动画
  useEffect(() => {
    if (nodes.length && canvasRef.current) {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      animationFrameRef.current = requestAnimationFrame(drawGraph);
    }

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [nodes, drawGraph]);

  // 缩放控制（移除限制）
  const handleZoomIn = () => {
    setScale(prev => prev * 1.2);
  };

  const handleZoomOut = () => {
    setScale(prev => prev / 1.2);
  };

  const handleFitView = () => {
    if (!nodes.length) return;
    
    // 计算节点边界
    const padding = 100;
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    
    nodes.forEach(node => {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x);
      minY = Math.min(minY, node.y);
      maxY = Math.max(maxY, node.y);
    });
    
    const graphWidth = maxX - minX + padding * 2;
    const graphHeight = maxY - minY + padding * 2;
    const graphCenterX = (minX + maxX) / 2;
    const graphCenterY = (minY + maxY) / 2;
    
    const scaleX = canvasSize.width / graphWidth;
    const scaleY = canvasSize.height / graphHeight;
    const newScale = Math.min(scaleX, scaleY, 1);
    
    const newOffset = {
      x: canvasSize.width / 2 - graphCenterX * newScale,
      y: canvasSize.height / 2 - graphCenterY * newScale
    };
    
    setScale(newScale);
    setOffset(newOffset);
  };

  // 搜索节点
  const handleSearchNode = () => {
    if (!searchNode.trim()) {
      message.warning('请输入节点名称');
      return;
    }

    const found = nodes.find(node => 
      node.label.toLowerCase().includes(searchNode.toLowerCase()) ||
      node.id.toLowerCase().includes(searchNode.toLowerCase())
    );

    if (found) {
      setSelectedNode(found);
      // 平滑移动到节点
      const targetOffset = {
        x: canvasSize.width / 2 - found.x * scale,
        y: canvasSize.height / 2 - found.y * scale
      };
      setOffset(targetOffset);
      message.success(`已定位到节点: ${found.label}`);
    } else {
      message.error('未找到匹配的节点');
    }
  };

  // 导出图片
  const handleExport = () => {
    if (!canvasRef.current) return;
    
    try {
      const dataURL = canvasRef.current.toDataURL('image/png');
      const link = document.createElement('a');
      link.download = `knowledge-graph-${currentGraph.tool_name}-${Date.now()}.png`;
      link.href = dataURL;
      link.click();
      message.success('图谱已导出');
    } catch (error) {
      message.error('导出失败');
    }
  };

  // 统计各类型节点数量
  const getNodeTypeStats = () => {
    const stats: { [key: string]: number } = {};
    nodes.forEach(node => {
      const type = node.properties.type;
      stats[type] = (stats[type] || 0) + 1;
    });
    return stats;
  };

  if (!currentGraph) return null;

  const nodeTypeStats = getNodeTypeStats();

  return (
    <Modal
      title={
        <div className="graph-modal-header">
          <NodeIndexOutlined className="graph-modal-icon" />
          <span>知识图谱可视化</span>
          <div className="entity-type-tags">
            {Object.entries(nodeTypeStats).map(([type, count]) => {
              const nodeStyle = getNodeStyle(type);
              const typeName = type === 'paper' ? '论文' : 
                               type === 'author' ? '作者' : 
                               type === 'venue' ? '期刊' : 
                               type === 'field' ? '领域' : 
                               type === 'reference' ? '引用' : 
                               type === 'unknown' ? '未知' : type;
              return (
                <span key={type} className="entity-type-tag">
                  <span className="entity-icon">{nodeStyle.icon}</span>
                  {typeName}:{count}
                </span>
              );
            })}
          </div>
        </div>
      }
      open={visible}
      onCancel={onClose}
      width="90vw"
      footer={null}
      className="knowledge-graph-modal"
      style={{ top: '20px', maxWidth: '1200px' }}
      destroyOnClose
      centered={false}
    >
      <div className="graph-modal-content">
      {/* 图谱选择器 */}
      {graphDataList.length > 1 && (
          <div style={{ marginBottom: '8px' }}>
          <Select
            value={currentGraphIndex}
            onChange={setCurrentGraphIndex}
            style={{ width: '100%' }}
              size="large"
            options={graphDataList.map((graph, index) => ({
              label: `图谱 ${index + 1}: ${graph.tool_name} (${graph.node_count}节点, ${graph.edge_count}边)`,
              value: index
            }))}
          />
        </div>
      )}

      {/* 工具栏 */}
        <div className="graph-toolbar">
          <Input.Search
            placeholder="搜索节点名称或ID..."
          value={searchNode}
          onChange={(e) => setSearchNode(e.target.value)}
            onSearch={handleSearchNode}
            className="search-input"
            size="large"
            allowClear
          />
          
          {/* 紧凑的统计信息 */}
          <div className="graph-stats-compact">
            <span className="stat-item">
              <NodeIndexOutlined style={{ color: '#1890ff' }} />
              <span>{currentGraph.node_count}</span>
            </span>
            <span className="stat-item">
              <BranchesOutlined style={{ color: '#52c41a' }} />
              <span>{currentGraph.edge_count}</span>
            </span>
            <span className="stat-item">
              <span>{(scale * 100).toFixed(0)}%</span>
            </span>
          </div>
          
          <div className="toolbar-buttons">
            <Tooltip title="放大 (滚轮向上)">
              <Button icon={<ZoomInOutlined />} onClick={handleZoomIn} size="large" />
        </Tooltip>
            <Tooltip title="缩小 (滚轮向下)">
              <Button icon={<ZoomOutOutlined />} onClick={handleZoomOut} size="large" />
        </Tooltip>
        <Tooltip title="适应画布">
              <Button icon={<FullscreenOutlined />} onClick={handleFitView} size="large" />
        </Tooltip>
        <Tooltip title="导出图片">
              <Button icon={<DownloadOutlined />} onClick={handleExport} size="large" type="primary" />
        </Tooltip>
          </div>
      </div>

      {/* 画布容器 */}
        <div className="canvas-container">
          <div ref={containerRef} className="canvas-wrapper" />
        </div>

      {/* 节点详情 */}
      {selectedNode && (
        <Card 
            title={
              <div className="node-detail-header">
                <span className="node-type-icon">{getNodeStyle(selectedNode.properties.type).icon}</span>
                <span>节点详情</span>
                <Badge 
                  color={getNodeStyle(selectedNode.properties.type).color}
                  text={getNodeStyle(selectedNode.properties.type).label}
                />
              </div>
            }
          size="small" 
            className="node-detail-card"
          extra={<Button type="link" onClick={() => setSelectedNode(null)}>关闭</Button>}
        >
            <div className="node-detail-content">
              <div className="detail-item">
                <span className="detail-label">ID:</span>
                <span className="detail-value">{selectedNode.id}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">标签:</span>
                <span className="detail-value">{selectedNode.label}</span>
              </div>
            {Object.entries(selectedNode.properties || {}).map(([key, value]) => (
                <div key={key} className="detail-item">
                  <span className="detail-label">{key}:</span>
                  <span className="detail-value">{value !== null && value !== undefined ? String(value) : 'N/A'}</span>
                </div>
            ))}
          </div>
        </Card>
      )}
      </div>
    </Modal>
  );
};

export default KnowledgeGraphViewer;
