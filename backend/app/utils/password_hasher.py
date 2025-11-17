"""
密码哈希模块 - 提供可配置的密码加密策略

支持的哈希算法：
- SHA256: 快速、无依赖，但安全性较低（不推荐用于生产环境）
- BCRYPT: 业界标准，安全性高，但有 72 字节限制
- ARGON2: 最新标准，抗 GPU 攻击，推荐用于生产环境

切换算法步骤：
1. 修改 HASH_ALGORITHM 配置
2. 重启服务
3. 新用户将使用新算法，老用户需要重置密码或自动迁移
"""

import hashlib
import secrets
import logging
from typing import Literal
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# ============================================
# 配置区域 - 在这里切换加密算法
# ============================================
HASH_ALGORITHM: Literal["sha256", "bcrypt", "argon2"] = "sha256"
# ============================================


class PasswordHasher(ABC):
    """密码哈希器抽象基类"""
    
    @abstractmethod
    def hash(self, password: str) -> str:
        """生成密码哈希"""
        pass
    
    @abstractmethod
    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        pass
    
    @abstractmethod
    def needs_rehash(self, hashed_password: str) -> bool:
        """检查是否需要重新哈希（用于算法升级）"""
        pass


class SHA256Hasher(PasswordHasher):
    """
    SHA-256 哈希器
    
    优点：
    - 快速，无外部依赖
    - 无密码长度限制
    - 跨平台兼容性好
    
    缺点：
    - 不是专门为密码设计的算法
    - 没有内置的 salt（本实现已添加）
    - 计算速度快，容易被暴力破解
    - 不推荐用于生产环境
    
    改进：使用 salt + 多次迭代增强安全性
    """
    
    ITERATIONS = 100000  # PBKDF2 迭代次数
    SALT_LENGTH = 32     # salt 长度（字节）
    
    def hash(self, password: str) -> str:
        """生成 SHA-256 哈希（带 salt 和迭代）"""
        # 生成随机 salt
        salt = secrets.token_hex(self.SALT_LENGTH)
        
        # 使用 PBKDF2 进行多次迭代
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            self.ITERATIONS
        ).hex()
        
        # 格式: algorithm$iterations$salt$hash
        return f"sha256${self.ITERATIONS}${salt}${password_hash}"
    
    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        try:
            # 兼容旧格式（纯 SHA-256，无 salt）
            if not hashed_password.startswith("sha256$"):
                # 旧格式：直接 SHA-256
                password_hash = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
                return password_hash == hashed_password
            
            # 新格式：解析 salt 和迭代次数
            parts = hashed_password.split('$')
            if len(parts) != 4:
                logger.error(f"无效的哈希格式: {hashed_password[:20]}...")
                return False
            
            algorithm, iterations, salt, stored_hash = parts
            iterations = int(iterations)
            
            # 重新计算哈希
            password_hash = hashlib.pbkdf2_hmac(
                'sha256',
                plain_password.encode('utf-8'),
                salt.encode('utf-8'),
                iterations
            ).hex()
            
            return password_hash == stored_hash
            
        except Exception as e:
            logger.error(f"SHA-256 密码验证失败: {str(e)}")
            return False
    
    def needs_rehash(self, hashed_password: str) -> bool:
        """检查是否需要重新哈希"""
        # 旧格式需要升级
        if not hashed_password.startswith("sha256$"):
            return True
        
        # 检查迭代次数是否过时
        try:
            parts = hashed_password.split('$')
            if len(parts) == 4:
                iterations = int(parts[1])
                return iterations < self.ITERATIONS
        except:
            pass
        
        return False


class BcryptHasher(PasswordHasher):
    """
    Bcrypt 哈希器
    
    优点：
    - 业界标准，广泛使用
    - 自适应算法，可调整计算成本
    - 内置 salt
    
    缺点：
    - 密码长度限制 72 字节
    - 依赖 bcrypt 库
    - Windows 环境可能有兼容性问题
    """
    
    def __init__(self):
        try:
            from passlib.context import CryptContext
            self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        except ImportError:
            raise ImportError(
                "使用 bcrypt 需要安装 passlib 和 bcrypt 库：\n"
                "pip install passlib bcrypt"
            )
    
    def hash(self, password: str) -> str:
        """生成 bcrypt 哈希"""
        # 处理超长密码：先用 SHA-256 预哈希
        if len(password.encode('utf-8')) > 72:
            logger.warning(f"密码超过 72 字节，使用 SHA-256 预哈希")
            password = hashlib.sha256(password.encode('utf-8')).hexdigest()
        
        return self.pwd_context.hash(password)
    
    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        try:
            # 处理超长密码
            if len(plain_password.encode('utf-8')) > 72:
                plain_password = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
            
            return self.pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error(f"Bcrypt 密码验证失败: {str(e)}")
            return False
    
    def needs_rehash(self, hashed_password: str) -> bool:
        """检查是否需要重新哈希"""
        try:
            return self.pwd_context.needs_update(hashed_password)
        except:
            return False


class Argon2Hasher(PasswordHasher):
    """
    Argon2 哈希器
    
    优点：
    - 2015 年密码哈希竞赛冠军
    - 抗 GPU/ASIC 攻击
    - 无密码长度限制
    - 推荐用于生产环境
    
    缺点：
    - 需要额外依赖
    - 相对较新，部分旧系统可能不支持
    """
    
    def __init__(self):
        try:
            from passlib.context import CryptContext
            self.pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
        except ImportError:
            raise ImportError(
                "使用 argon2 需要安装 passlib 和 argon2-cffi 库：\n"
                "pip install passlib argon2-cffi"
            )
    
    def hash(self, password: str) -> str:
        """生成 argon2 哈希"""
        return self.pwd_context.hash(password)
    
    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        try:
            return self.pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error(f"Argon2 密码验证失败: {str(e)}")
            return False
    
    def needs_rehash(self, hashed_password: str) -> bool:
        """检查是否需要重新哈希"""
        try:
            return self.pwd_context.needs_update(hashed_password)
        except:
            return False


# ============================================
# 工厂函数 - 根据配置创建哈希器
# ============================================

def get_hasher() -> PasswordHasher:
    """获取当前配置的密码哈希器"""
    if HASH_ALGORITHM == "sha256":
        return SHA256Hasher()
    elif HASH_ALGORITHM == "bcrypt":
        return BcryptHasher()
    elif HASH_ALGORITHM == "argon2":
        return Argon2Hasher()
    else:
        raise ValueError(f"不支持的哈希算法: {HASH_ALGORITHM}")


# ============================================
# 公共 API - 供外部调用
# ============================================

_hasher = get_hasher()

def get_password_hash(password: str) -> str:
    """
    生成密码哈希
    
    Args:
        password: 明文密码
        
    Returns:
        密码哈希字符串
    """
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码
    
    Args:
        plain_password: 明文密码
        hashed_password: 存储的哈希值
        
    Returns:
        验证是否成功
    """
    return _hasher.verify(plain_password, hashed_password)


def needs_password_rehash(hashed_password: str) -> bool:
    """
    检查密码是否需要重新哈希
    
    用于算法升级时自动迁移旧密码
    
    Args:
        hashed_password: 存储的哈希值
        
    Returns:
        是否需要重新哈希
    """
    return _hasher.needs_rehash(hashed_password)


# ============================================
# 使用示例
# ============================================

if __name__ == "__main__":
    # 测试密码
    test_password = "MySecurePassword123!"
    
    print(f"当前使用算法: {HASH_ALGORITHM}")
    print(f"测试密码: {test_password}")
    print()
    
    # 生成哈希
    hashed = get_password_hash(test_password)
    print(f"哈希值: {hashed}")
    print()
    
    # 验证密码
    is_valid = verify_password(test_password, hashed)
    print(f"验证成功: {is_valid}")
    
    is_invalid = verify_password("WrongPassword", hashed)
    print(f"错误密码验证: {is_invalid}")
    print()
    
    # 检查是否需要重新哈希
    needs_rehash = needs_password_rehash(hashed)
    print(f"需要重新哈希: {needs_rehash}")
