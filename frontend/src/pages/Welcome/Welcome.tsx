import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import { AxiosError } from 'axios';
import styles from './Welcome.module.css';
import React, { useState } from 'react';
import { Form, Input, Button, message, Row, Col, Modal } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined, SafetyOutlined } from '@ant-design/icons';
import { authAPI, verificationAPI } from '../../utils/api';
import ThemeToggle from '../../components/ThemeToggle';

// 接口定义
interface RegisterForm {
  account: string;
  email: string;
  password: string;
  confirmPassword: string;
  verificationCode?: string;
}

interface LoginForm {
  identifier: string;  // 可以是账号或邮箱
  password: string;
}

interface ErrorResponse {
  detail: string;
}

const Welcome: React.FC = () => {
  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);
  
  // 模态框状态管理
  const [isLoginModalVisible, setIsLoginModalVisible] = useState(false);
  const [isRegisterModalVisible, setIsRegisterModalVisible] = useState(false);
  
  // 注册相关状态
  const [registerForm] = Form.useForm();
  const [sendingCode, setSendingCode] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [useEmailVerification, setUseEmailVerification] = useState<boolean | null>(null);
  
  // 登录相关状态
  const [loginForm] = Form.useForm();

  React.useEffect(() => {
    const loadSettings = async () => {
      try {
        const res = await authAPI.getAppSettings();
        const flag = Boolean(res.data?.email_verification);
        setUseEmailVerification(flag);
      } catch (e) {
        // 获取失败时默认关闭邮箱验证，避免初次渲染闪烁；后端仍会进行最终校验
        setUseEmailVerification(false);
      }
    };
    loadSettings();
  }, []);

  // 发送验证码
  const sendVerificationCode = async () => {
    const email = registerForm.getFieldValue('email');
    if (!email) {
      message.error('请先输入邮箱！');
      return;
    }

    // 验证邮箱格式
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      message.error('请输入有效的邮箱地址！');
      return;
    }

    setSendingCode(true);
    try {
      const response = await verificationAPI.sendCode(email);
      if (response.data.success) {
        message.success('验证码已发送，请查收邮件！');
        // 开始倒计时
        setCountdown(300); // 5分钟倒计时
        const timer = setInterval(() => {
          setCountdown((prev) => {
            if (prev <= 1) {
              clearInterval(timer);
              return 0;
            }
            return prev - 1;
          });
        }, 1000);
      } else {
        message.error(response.data.message || '发送失败！');
      }
    } catch (error) {
      const axiosError = error as AxiosError<ErrorResponse>;
      if (axiosError.response?.data) {
        message.error(axiosError.response.data.detail || '发送失败，请稍后重试！');
      } else {
        message.error('发送失败，请稍后重试！');
      }
    } finally {
      setSendingCode(false);
    }
  };

  // 注册表单提交
  const onRegisterFinish = async (values: RegisterForm) => {
    if (values.password !== values.confirmPassword) {
      message.error('两次输入的密码不一致！');
      return;
    }

    try {
      if (useEmailVerification) {
        // 使用邮箱验证注册
        if (!values.verificationCode) {
          message.error('请输入验证码！');
          return;
        }
        
        await authAPI.registerWithEmail({
          account: values.account,
          email: values.email,
          password: values.password,
          verification_code: values.verificationCode
        });
        message.success('注册成功！请登录');
        setIsRegisterModalVisible(false);
        setIsLoginModalVisible(true);
      } else {
        // 普通注册（不需要邮箱验证）
        await authAPI.register({
          account: values.account,
          email: values.email,
          password: values.password
        });
        message.success('注册成功！请登录');
        setIsRegisterModalVisible(false);
        setIsLoginModalVisible(true);
      }
    } catch (error) {
      const axiosError = error as AxiosError<ErrorResponse>;
      if (axiosError.response?.data) {
        message.error(axiosError.response.data.detail || '注册失败，请稍后重试！');
      } else {
        message.error('注册失败，请稍后重试！');
      }
    }
  };
  // 登录表单提交
  const onLoginFinish = async (values: LoginForm) => {
    try {
      await login(values.identifier, values.password);
      message.success('登录成功！');
      setIsLoginModalVisible(false);
      navigate('/');
    } catch (error) {
      const axiosError = error as AxiosError<ErrorResponse>;
      if (axiosError.response?.data) {
        message.error(axiosError.response.data.detail || '登录失败，请检查账号/邮箱和密码！');
      } else {
        message.error('登录失败，请检查账号/邮箱和密码！');
      }
    }
  };

  // 验证输入是否为有效的邮箱或账号
  const validateIdentifier = (_: any, value: string) => {
    if (!value) {
      return Promise.reject(new Error('请输入账号或邮箱！'));
    }
    
    // 邮箱格式验证
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    // 账号格式验证（3-20位字母数字下划线）
    const accountRegex = /^[a-zA-Z0-9_]{3,20}$/;
    
    if (emailRegex.test(value) || accountRegex.test(value)) {
      return Promise.resolve();
    }
    
    return Promise.reject(new Error('请输入有效的账号（3-20位字母数字下划线）或邮箱地址！'));
  };

  return (
    <div className={styles.authContainer}>
      <div className={styles.signUp}>
        <Button
          type="primary"
          size="large"
          className={styles.welcomeButton}
          onClick={() => setIsLoginModalVisible(true)}
        >
          登录
        </Button>

        <Button
          size="large"
          className={styles.welcomeButton}
          onClick={() => setIsRegisterModalVisible(true)}
        >
          注册
        </Button>
        <div className={styles.settingCard}>
          <ThemeToggle />
        </div>
      </div>
      {/* 登录模态框 */}
      <Modal
        title="登录"
        open={isLoginModalVisible}
        onCancel={() => setIsLoginModalVisible(false)}
        footer={null}
        width={400}
        centered
      >
        <Form
          name="login"
          form={loginForm}
          onFinish={onLoginFinish}
          layout="vertical"
          size="large"
          onFinishFailed={({ errorFields }) => {
            if (errorFields && errorFields.length > 0) {
              const first = errorFields[0];
              const msg = (first.errors && first.errors[0]) || '请检查表单输入！';
              message.error(msg);
            }
          }}
        >
          <Form.Item
            name="identifier"
            rules={[{ validator: validateIdentifier }]}
            help={null}
            validateTrigger={[]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="账号或邮箱"
              className={styles.input}
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码！' }]}
            help={null}
            validateTrigger={[]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              className={styles.input}
            />
          </Form.Item>

          <Form.Item>
            <Button
              type="primary"
              block
              className={styles.button}
              onClick={async () => {
                try {
                  const values = await loginForm.validateFields();
                  await onLoginFinish(values);
                } catch (err: any) {
                  const first = err?.errorFields?.[0];
                  const msg = (first?.errors && first.errors[0]) || '请检查表单输入！';
                  message.error(msg);
                }
              }}
            >
              登录
            </Button>
          </Form.Item>
          <div className={styles.links}>
            <a onClick={() => {
              setIsLoginModalVisible(false);
              setIsRegisterModalVisible(true);
            }}>
              还没有账号？立即注册
            </a>
          </div>
        </Form>
      </Modal>

      {/* 注册模态框 */}
      <Modal
        title="注册"
        open={isRegisterModalVisible}
        onCancel={() => setIsRegisterModalVisible(false)}
        footer={null}
        width={400}
        centered
      >
        <Form
          name="register"
          form={registerForm}
          onFinish={onRegisterFinish}
          layout="vertical"
          size="large"
          onFinishFailed={({ errorFields }) => {
            if (errorFields && errorFields.length > 0) {
              const first = errorFields[0];
              const msg = (first.errors && first.errors[0]) || '请检查表单输入！';
              message.error(msg);
            }
          }}
        >
          <Form.Item
            name="account"
            rules={[
              { required: true, message: '请输入账号！' },
              { min: 3, message: '账号至少3个字符！' }
            ]}
            help={null}
            validateTrigger={[]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="账号"
              className={styles.input}
            />
          </Form.Item>

          <Form.Item
            name="email"
            rules={[
              { required: !!useEmailVerification, message: '请输入邮箱！' },
              { type: 'email', message: '请输入有效的邮箱地址！' }
            ]}
            help={null}
            validateTrigger={[]}
          >
            <Input
              prefix={<MailOutlined />}
              placeholder="邮箱"
              className={styles.input}
            />
          </Form.Item>

          {useEmailVerification === true && (
            <Form.Item
              name="verificationCode"
              rules={[
                { required: true, message: '请输入验证码！' },
                { len: 6, message: '验证码为6位数字！' }
              ]}
              help={null}
              validateTrigger={[]}
            >
              <Row gutter={8}>
                <Col span={16}>
                  <Input
                    prefix={<SafetyOutlined />}
                    placeholder="邮箱验证码"
                    className={styles.input}
                    maxLength={6}
                  />
                </Col>
                <Col span={8}>
                  <Button
                    onClick={sendVerificationCode}
                    loading={sendingCode}
                    disabled={countdown > 0}
                    block
                    style={{ height: '40px' }}
                  >
                    {countdown > 0 ? `${Math.floor(countdown / 60)}:${(countdown % 60).toString().padStart(2, '0')}` : '发送验证码'}
                  </Button>
                </Col>
              </Row>
            </Form.Item>
          )}

          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码！' },
              { min: 6, message: '密码至少6个字符！' }
            ]}
            help={null}
            validateTrigger={[]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              className={styles.input}
            />
          </Form.Item>

          <Form.Item
            name="confirmPassword"
            rules={[
              { required: true, message: '请确认密码！' },
              { min: 6, message: '密码至少6个字符！' }
            ]}
            help={null}
            validateTrigger={[]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="确认密码"
              className={styles.input}
            />
          </Form.Item>

          <Form.Item>
            <Button
              type="primary"
              block
              className={styles.button}
              onClick={async () => {
                try {
                  const values = await registerForm.validateFields();
                  await onRegisterFinish(values as any);
                } catch (err: any) {
                  const first = err?.errorFields?.[0];
                  const msg = (first?.errors && first.errors[0]) || '请检查表单输入！';
                  message.error(msg);
                }
              }}
            >
              注册
            </Button>
          </Form.Item>
          <div className={styles.links}>
            <a onClick={() => {
              setIsRegisterModalVisible(false);
              setIsLoginModalVisible(true);
            }}>
              已有账号？立即登录
            </a>
          </div>
        </Form>
      </Modal>
    </div>
  );
};

export default Welcome; 