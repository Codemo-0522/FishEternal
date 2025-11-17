from OpenSSL import crypto
import os

def generate_self_signed_cert():
    """生成自签名证书"""
    # 生成密钥
    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 2048)

    # 创建证书
    cert = crypto.X509()
    cert.get_subject().CN = "localhost"
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365*24*60*60)  # 有效期一年
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(k)
    cert.sign(k, 'sha256')

    # 写入文件
    with open("cert.pem", "wb") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    with open("key.pem", "wb") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))

if __name__ == '__main__':
    generate_self_signed_cert()
    print("证书已生成：cert.pem 和 key.pem") 