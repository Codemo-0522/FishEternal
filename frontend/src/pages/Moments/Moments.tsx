/**
 * 朋友圈页面
 */

import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Layout,
  Card,
  Image,
  Button,
  Input,
  message,
  Spin,
  Empty,
  Tabs,
  Tag,
  Modal,
  Space,
} from 'antd';
import {
  HeartOutlined,
  HeartFilled,
  MessageOutlined,
  DeleteOutlined,
  ArrowLeftOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';
import {
  getMoments,
  getMomentQueue,
  likeMoment,
  commentMoment,
  deleteMoment,
  deleteComment,
  type Moment,
  type MomentQueue,
  type Comment,
  type LikeUser,
} from '../../services/moments';
import { useAuthStore } from '../../stores/authStore';
import ThemeToggle from '../../components/ThemeToggle';
import styles from './Moments.module.css';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Content } = Layout;
const { TextArea } = Input;
const { TabPane } = Tabs;

const Moments: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { user, initializeAuth } = useAuthStore();

  const [moments, setMoments] = useState<Moment[]>([]);
  const [queue, setQueue] = useState<{
    pending: MomentQueue[];
    published: MomentQueue[];
    error: MomentQueue[];
    cancelled: MomentQueue[];
  }>({
    pending: [],
    published: [],
    error: [],
    cancelled: [],
  });
  const [loading, setLoading] = useState(true);
  const [userLoading, setUserLoading] = useState(true);  // 新增：用户信息加载状态
  const [commentingMomentId, setCommentingMomentId] = useState<string | null>(null);
  const [commentContent, setCommentContent] = useState('');
  const [activeTab, setActiveTab] = useState('moments');
  const [likingMomentIds, setLikingMomentIds] = useState<Set<string>>(new Set());
  const [lastMomentsUpdate, setLastMomentsUpdate] = useState<string | null>(null);
  const [lastQueueUpdate, setLastQueueUpdate] = useState<string | null>(null);

  // 加载朋友圈列表
  const loadMoments = async (fullLoad = false) => {
    if (!sessionId) return;

    try {
      if (fullLoad) {
        setLoading(true);
      }
      const data = await getMoments(sessionId, 50, 0);
      console.log('📥 获取朋友圈数据:', data.moments.map(m => ({
        id: m._id,
        likes: m.likes,
        like_users: m.like_users
      })));
      setMoments(data.moments);
      // 记录最后更新时间（取最新朋友圈的时间）
      if (data.moments.length > 0) {
        setLastMomentsUpdate(data.moments[0].created_at);
      }
    } catch (error) {
      console.error('加载朋友圈失败:', error);
      message.error('加载朋友圈失败');
    } finally {
      if (fullLoad) {
        setLoading(false);
      }
    }
  };

  // 增量更新朋友圈（只获取新的）
  const updateMoments = async () => {
    if (!sessionId || !lastMomentsUpdate) {
      return loadMoments();
    }

    try {
      const data = await getMoments(sessionId, 50, 0, lastMomentsUpdate);
      if (data.has_updates && data.moments.length > 0) {
        // 合并新数据到现有列表顶部
        setMoments(prev => {
          const newMoments = [...data.moments, ...prev];
          // 去重
          const uniqueMoments = newMoments.filter(
            (m, index, self) => self.findIndex(t => t._id === m._id) === index
          );
          return uniqueMoments;
        });
        // 更新最后更新时间
        setLastMomentsUpdate(data.moments[0].created_at);
      }
    } catch (error) {
      console.error('更新朋友圈失败:', error);
    }
  };

  // 加载朋友圈队列
  const loadQueue = async (fullLoad = false) => {
    if (!sessionId) return;

    try {
      const data = await getMomentQueue(sessionId);
      setQueue(data);
      // 记录最后更新时间
      const allItems = [...data.pending, ...data.published, ...data.error, ...data.cancelled];
      if (allItems.length > 0) {
        const latestUpdate = allItems
          .map(item => item.created_at)
          .sort()
          .reverse()[0];
        setLastQueueUpdate(latestUpdate);
      }
    } catch (error) {
      console.error('加载朋友圈队列失败:', error);
      if (fullLoad) {
        message.error('加载朋友圈队列失败');
      }
    }
  };

  // 增量更新队列（只获取有变化的）
  const updateQueue = async () => {
    if (!sessionId || !lastQueueUpdate) {
      return loadQueue();
    }

    try {
      const data = await getMomentQueue(sessionId, lastQueueUpdate);
      if (data.has_updates) {
        // 合并更新的项目
        setQueue(prev => {
          const mergeItems = (oldItems: MomentQueue[], newItems: MomentQueue[]) => {
            const merged = [...oldItems];
            newItems.forEach(newItem => {
              const index = merged.findIndex(item => item._id === newItem._id);
              if (index !== -1) {
                merged[index] = newItem;
              } else {
                merged.push(newItem);
              }
            });
            return merged;
          };

          return {
            pending: mergeItems(prev.pending, data.pending),
            published: mergeItems(prev.published, data.published),
            error: mergeItems(prev.error, data.error),
            cancelled: mergeItems(prev.cancelled, data.cancelled),
          };
        });

        // 更新最后更新时间
        const allItems = [...data.pending, ...data.published, ...data.error, ...data.cancelled];
        if (allItems.length > 0) {
          const latestUpdate = allItems
            .map(item => item.created_at)
            .sort()
            .reverse()[0];
          setLastQueueUpdate(latestUpdate);
        }
      }
    } catch (error) {
      console.error('更新队列失败:', error);
    }
  };

  // 初始化认证
  useEffect(() => {
    const init = async () => {
      await initializeAuth();
      setUserLoading(false);  // 用户信息加载完成
    };
    init();
  }, [initializeAuth]);

  useEffect(() => {
    // 等待用户信息加载完成
    if (!user) return;

    // 首次加载
    loadMoments(true);
    loadQueue(true);

    // 每30秒增量更新（只获取变化的数据）
    const interval = setInterval(() => {
      updateQueue();
      if (activeTab === 'moments') {
        updateMoments();
      }
    }, 30000);

    return () => clearInterval(interval);
  }, [sessionId, activeTab, user]);

  // 点赞
  const handleLike = async (momentId: string) => {
    if (!sessionId) return;
    
    // 防止重复点击
    if (likingMomentIds.has(momentId)) {
      console.log('⚠️ 正在处理点赞，请勿重复点击');
      return;
    }

    try {
      // 标记为正在点赞
      setLikingMomentIds(prev => new Set(prev).add(momentId));
      
      await likeMoment(sessionId, momentId);
      // 更新本地状态
      setMoments(prev =>
        prev.map(m => {
          if (m._id === momentId) {
            const userId = String(user?.id || '');
            const liked = m.likes.map(id => String(id)).includes(userId);
            const newLikes = liked
              ? m.likes.filter(id => String(id) !== userId)
              : [...m.likes, userId];
            
            // 同时更新 like_users
            const newLikeUsers = liked
              ? (m.like_users || []).filter(lu => String(lu.user_id) !== userId)
              : [
                  ...(m.like_users || []),
                  {
                    user_id: userId,
                    user_name: user?.full_name || user?.account || '未知用户'
                  }
                ];
            
            return {
              ...m,
              likes: newLikes,
              like_users: newLikeUsers,
            };
          }
          return m;
        })
      );
    } catch (error) {
      console.error('点赞失败:', error);
      message.error('操作失败');
    } finally {
      // 移除点赞标记
      setLikingMomentIds(prev => {
        const next = new Set(prev);
        next.delete(momentId);
        return next;
      });
    }
  };

  // 评论
  const handleComment = async (momentId: string) => {
    if (!sessionId || !commentContent.trim()) {
      message.warning('请输入评论内容');
      return;
    }

    try {
      const result = await commentMoment(sessionId, momentId, commentContent.trim());
      if (result.success) {
        // 更新本地状态
        setMoments(prev =>
          prev.map(m => {
            if (m._id === momentId) {
              return {
                ...m,
                comments: [...m.comments, result.comment],
              };
            }
            return m;
          })
        );
        setCommentContent('');
        setCommentingMomentId(null);
        message.success('评论成功');
      }
    } catch (error) {
      console.error('评论失败:', error);
      message.error('评论失败');
    }
  };

  // 删除朋友圈
  const handleDelete = async (momentId: string) => {
    if (!sessionId) return;

    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这条朋友圈吗？',
      okText: '确定',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await deleteMoment(sessionId, momentId);
          setMoments(prev => prev.filter(m => m._id !== momentId));
          message.success('删除成功');
        } catch (error) {
          console.error('删除失败:', error);
          message.error('删除失败');
        }
      },
    });
  };

  // 删除评论
  const handleDeleteComment = async (momentId: string, commentId: string) => {
    if (!sessionId) return;

    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这条评论吗？',
      okText: '确定',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await deleteComment(sessionId, momentId, commentId);
          // 更新本地状态
          setMoments(prev =>
            prev.map(m => {
              if (m._id === momentId) {
                return {
                  ...m,
                  comments: m.comments.filter(c => c._id !== commentId),
                };
              }
              return m;
            })
          );
          message.success('删除成功');
        } catch (error: any) {
          console.error('删除评论失败:', error);
          // 显示具体错误信息
          if (error.response?.data?.detail) {
            message.error(error.response.data.detail);
          } else {
            message.error('删除失败');
          }
        }
      },
    });
  };

  // 渲染单条朋友圈
  const renderMoment = (moment: Moment) => {
    // 确保 ID 比较时都是字符串格式
    const userId = String(user?.id || '');
    const isLiked = moment.likes.map(id => String(id)).includes(userId);
    
    // 调试日志
    console.log(`🔍 渲染朋友圈 [${moment._id}]`, {
      userId,
      likes: moment.likes,
      isLiked,
      user: user
    });

    return (
      <Card
        key={moment._id}
        className={styles.momentCard}
        style={{ marginBottom: 16 }}
      >
        {/* 内容 */}
        <div className={styles.content}>{moment.content}</div>

        {/* 心情 */}
        {moment.mood && (
          <Tag color="blue" style={{ marginTop: 8 }}>
            {moment.mood}
          </Tag>
        )}

        {/* 图片 */}
        {moment.images && moment.images.length > 0 && (
          <div className={styles.images}>
            <Image.PreviewGroup>
              {moment.images.map((img, idx) => (
                <Image
                  key={idx}
                  src={img}
                  alt={`图片${idx + 1}`}
                  style={{
                    width: moment.images!.length === 1 ? 200 : 100,
                    height: moment.images!.length === 1 ? 200 : 100,
                    objectFit: 'cover',
                    marginRight: 8,
                    marginTop: 8,
                    borderRadius: 4,
                  }}
                />
              ))}
            </Image.PreviewGroup>
          </div>
        )}

        {/* 时间 */}
        <div className={styles.time}>
          {dayjs(moment.created_at).fromNow()}
        </div>

        {/* 操作栏 */}
        <div className={styles.actions}>
          <Button
            type="text"
            icon={isLiked ? <HeartFilled style={{ color: '#ff4d4f' }} /> : <HeartOutlined />}
            onClick={() => handleLike(moment._id)}
          >
            {moment.likes.length > 0 && moment.likes.length}
          </Button>
          <Button
            type="text"
            icon={<MessageOutlined />}
            onClick={() => setCommentingMomentId(moment._id)}
          >
            {moment.comments.length > 0 && moment.comments.length}
          </Button>
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(moment._id)}
          />
        </div>

        {/* 点赞列表 */}
        {moment.like_users && moment.like_users.length > 0 && (
          <div className={styles.likeSection}>
            <HeartFilled className={styles.likeIcon} />
            <span className={styles.likeUsers}>
              {moment.like_users.map((like, index) => (
                <span key={like.user_id}>
                  {like.user_name}
                  {index < moment.like_users!.length - 1 && ', '}
                </span>
              ))}
            </span>
          </div>
        )}

        {/* 评论列表 */}
        {moment.comments.length > 0 && (
          <div className={styles.comments}>
            {moment.comments.map(comment => {
              // 判断是否是当前用户的评论（排除 AI）
              const isOwnComment = !comment.is_ai && String(comment.user_id) === userId;
              
              return (
                <div 
                  key={comment._id} 
                  className={`${styles.comment} ${comment.is_ai ? styles.aiComment : ''}`}
                >
                  <div className={styles.commentContent}>
                    <span className={styles.commentUser}>
                      {comment.user_name}
                      {comment.is_ai && <span className={styles.aiTag}>AI</span>}:
                    </span>{' '}
                    {comment.content}
                    <span className={styles.commentTime}>
                      {dayjs(comment.created_at).fromNow()}
                    </span>
                  </div>
                  {isOwnComment && (
                    <DeleteOutlined
                      className={styles.deleteCommentBtn}
                      onClick={() => handleDeleteComment(moment._id, comment._id)}
                      title="删除评论"
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 评论输入框 */}
        {commentingMomentId === moment._id && (
          <div className={styles.commentInput}>
            <TextArea
              value={commentContent}
              onChange={e => setCommentContent(e.target.value)}
              placeholder="输入评论..."
              autoSize={{ minRows: 2, maxRows: 4 }}
              onPressEnter={e => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleComment(moment._id);
                }
              }}
            />
            <Space style={{ marginTop: 8 }}>
              <Button size="small" onClick={() => handleComment(moment._id)}>
                发送
              </Button>
              <Button size="small" onClick={() => setCommentingMomentId(null)}>
                取消
              </Button>
            </Space>
          </div>
        )}
      </Card>
    );
  };

  // 渲染队列项
  const renderQueueItem = (item: MomentQueue) => {
    const getStatusIcon = () => {
      switch (item.status) {
        case 'pending':
          return <ClockCircleOutlined style={{ color: '#1890ff' }} />;
        case 'published':
          return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
        case 'error':
          return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
        case 'cancelled':
          return <ExclamationCircleOutlined style={{ color: '#d9d9d9' }} />;
      }
    };

    const getStatusText = () => {
      switch (item.status) {
        case 'pending':
          return `将于 ${dayjs(item.publish_at).format('MM-DD HH:mm')} 发布`;
        case 'published':
          return `已于 ${dayjs(item.published_at).format('MM-DD HH:mm')} 发布`;
        case 'error':
          return `发布失败: ${item.error_message}`;
        case 'cancelled':
          return '已取消';
      }
    };

    return (
      <Card
        key={item._id}
        size="small"
        className={styles.queueCard}
        style={{ marginBottom: 12 }}
      >
        <div className={styles.queueContent}>
          <div className={styles.queueStatus}>
            {getStatusIcon()}
            <span style={{ marginLeft: 8 }}>{getStatusText()}</span>
          </div>
          <div className={styles.content} style={{ marginTop: 8 }}>
            {item.content}
          </div>
          {item.mood && (
            <Tag color="blue" style={{ marginTop: 8 }}>
              {item.mood}
            </Tag>
          )}
          {item.generated_images && item.generated_images.length > 0 && (
            <Tag color="green" style={{ marginTop: 8 }}>
              配图 {item.generated_images.length} 张
            </Tag>
          )}
        </div>
      </Card>
    );
  };

  return (
    <Layout className={styles.momentsLayout}>
      <Content className={styles.momentsContent}>
        {/* 头部 */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <div className={styles.headerLeft}>
              <Button
                icon={<ArrowLeftOutlined />}
                onClick={() => navigate(-1)}
                className={styles.backButton}
                type="text"
              >
                返回
              </Button>
            </div>
            <h1 className={styles.headerTitle}>朋友圈</h1>
            <div className={styles.headerRight}>
              <ThemeToggle />
            </div>
          </div>
        </div>

        {/* 标签页 */}
        <div className={styles.tabsContainer}>
          <Tabs 
            activeKey={activeTab} 
            onChange={setActiveTab}
            className={styles.momentsTabs}
          >
            <TabPane tab="朋友圈" key="moments">
              {(loading || userLoading) ? (
                <div className={styles.loadingContainer}>
                  <Spin size="large" />
                </div>
              ) : moments.length === 0 ? (
                <div className={styles.emptyContainer}>
                  <Empty description="还没有朋友圈" />
                </div>
              ) : (
                <div className={styles.scrollContainer}>
                  {moments.map(renderMoment)}
                </div>
              )}
            </TabPane>

            <TabPane
              tab={
                <span>
                  待发布
                  {queue.pending.length > 0 && (
                    <Tag color="blue" style={{ marginLeft: 8 }}>
                      {queue.pending.length}
                    </Tag>
                  )}
                </span>
              }
              key="pending"
            >
              {queue.pending.length === 0 ? (
                <div className={styles.emptyContainer}>
                  <Empty description="没有待发布的朋友圈" />
                </div>
              ) : (
                <div className={styles.scrollContainer}>
                  {queue.pending.map(renderQueueItem)}
                </div>
              )}
            </TabPane>

            <TabPane tab="已发布" key="published">
              {queue.published.length === 0 ? (
                <div className={styles.emptyContainer}>
                  <Empty description="没有已发布的记录" />
                </div>
              ) : (
                <div className={styles.scrollContainer}>
                  {queue.published.map(renderQueueItem)}
                </div>
              )}
            </TabPane>

            <TabPane tab="发布失败" key="error">
              {queue.error.length === 0 ? (
                <div className={styles.emptyContainer}>
                  <Empty description="没有失败的记录" />
                </div>
              ) : (
                <div className={styles.scrollContainer}>
                  {queue.error.map(renderQueueItem)}
                </div>
              )}
            </TabPane>
          </Tabs>
        </div>
      </Content>
    </Layout>
  );
};

export default Moments;

