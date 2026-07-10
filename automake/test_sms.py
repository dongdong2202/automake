import os
import django
import sys

# 设置 Django 环境
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
django.setup()

from notifications.services import send_sms_notify

def run_test():
    phone_number = "13683155152"
    # 这里我们假设模板有一个名为 'code' 的变量，如果不一致，您可能需要修改模板参数
    template_param = '{"code": "1234"}'
    
    print(f"正在向 {phone_number} 发送测试短信...")
    
    result = send_sms_notify(
        phone_numbers=phone_number,
        template_param=template_param
    )
    
    print("短信发送结果:")
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run_test()
