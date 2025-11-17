import os
import uuid
import time
import json
import hashlib
import platform
import logging
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

class SecureFileManager:
    def __init__(self, app_key: str):
        self.app_key = app_key
        self.logger = logging.getLogger(__name__)
        
    def get_machine_id(self) -> str:
        """获取机器唯一标识"""
        try:
            if platform.system() == "Windows":
                # Windows下使用CPU ID和BIOS信息
                import wmi
                c = wmi.WMI()
                cpu = c.Win32_Processor()[0].ProcessorId.strip()
                bios = c.Win32_BIOS()[0].SerialNumber.strip()
                return hashlib.sha256(f"{cpu}:{bios}".encode()).hexdigest()
            else:
                # Linux/Mac下使用/etc/machine-id
                with open("/etc/machine-id", "r") as f:
                    return f.read().strip()
        except:
            # 如果无法获取机器ID，使用一个持久化的随机ID
            machine_id_file = os.path.join(os.path.expanduser("~"), ".machine_id")
            if os.path.exists(machine_id_file):
                with open(machine_id_file, "r") as f:
                    return f.read().strip()
            else:
                machine_id = str(uuid.uuid4())
                os.makedirs(os.path.dirname(machine_id_file), exist_ok=True)
                with open(machine_id_file, "w") as f:
                    f.write(machine_id)
                return machine_id

    def generate_key(self, salt: bytes) -> bytes:
        """生成加密密钥"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.app_key.encode()))
        return key

    def encrypt_data(self, data: Dict[str, Any], file_path: str) -> bool:
        """加密数据并保存到文件"""
        try:
            # 生成文件元数据
            file_id = str(uuid.uuid4())
            timestamp = str(int(time.time()))
            machine_id = self.get_machine_id()
            
            # 准备数据包
            data_package = {
                "metadata": {
                    "file_id": file_id,
                    "timestamp": timestamp,
                    "machine_id": machine_id,
                },
                "data": data
            }
            
            # 转换为JSON
            json_data = json.dumps(data_package).encode()
            
            # 生成校验和
            checksum = hashlib.sha256(json_data).hexdigest()
            data_package["metadata"]["checksum"] = checksum
            
            # 重新转换为JSON（现在包含校验和）
            final_json_data = json.dumps(data_package).encode()
            
            # 生成随机盐值
            salt = os.urandom(16)
            
            # 生成加密密钥
            key = self.generate_key(salt)
            fernet = Fernet(key)
            
            # 加密数据
            encrypted_data = fernet.encrypt(final_json_data)
            
            # 保存加密数据（盐值 + 加密数据）
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(salt + encrypted_data)
            
            return True
        except Exception as e:
            self.logger.error(f"加密数据失败: {str(e)}")
            return False

    def decrypt_data(self, file_path: str) -> Optional[Dict[str, Any]]:
        """解密文件数据"""
        try:
            if not os.path.exists(file_path):
                return None
                
            with open(file_path, 'rb') as f:
                # 读取盐值和加密数据
                file_content = f.read()
                salt = file_content[:16]
                encrypted_data = file_content[16:]
            
            # 生成解密密钥
            key = self.generate_key(salt)
            fernet = Fernet(key)
            
            # 解密数据
            decrypted_data = fernet.decrypt(encrypted_data)
            data_package = json.loads(decrypted_data)
            
            # 验证元数据
            metadata = data_package["metadata"]
            
            # 验证机器ID
            if metadata["machine_id"] != self.get_machine_id():
                self.logger.error("机器ID验证失败")
                return None
            
            # 验证校验和
            stored_checksum = metadata.pop("checksum")
            verification_data = {
                "metadata": metadata,
                "data": data_package["data"]
            }
            current_checksum = hashlib.sha256(json.dumps(verification_data).encode()).hexdigest()
            
            if stored_checksum != current_checksum:
                self.logger.error("数据完整性验证失败")
                return None
            
            return data_package["data"]
        except Exception as e:
            self.logger.error(f"解密数据失败: {str(e)}")
            return None

    def delete_file(self, file_path: str) -> bool:
        """安全删除文件"""
        try:
            if os.path.exists(file_path):
                # 首先用随机数据覆盖文件
                file_size = os.path.getsize(file_path)
                with open(file_path, 'wb') as f:
                    f.write(os.urandom(file_size))
                # 然后删除文件
                os.remove(file_path)
            return True
        except Exception as e:
            self.logger.error(f"删除文件失败: {str(e)}")
            return False 