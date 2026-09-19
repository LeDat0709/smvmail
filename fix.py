import re

with open('app.py', 'r') as f:
    text = f.read()

# Sửa lỗi API
text = text.replace("if response.get('email_user'):", "if response.get('email_addr'):")

# Tự sinh tên nếu để trống
block_find = """        if custom_user:
            response = api_call({'f': 'set_email_user', 'email_user': custom_user})"""
            
block_replace = """        import secrets
        if not custom_user:
            custom_user = f"user{secrets.token_hex(4)}"
        if custom_user:
            response = api_call({'f': 'set_email_user', 'email_user': custom_user})"""

text = text.replace(block_find, block_replace)

# Bắt buộc chỉ dùng rionfashion.com
import re
text = re.sub(r"AVAILABLE_DOMAINS\s*=\s*\[.*?\]", "AVAILABLE_DOMAINS = ['rionfashion.com']", text, flags=re.DOTALL)

with open('app.py', 'w') as f:
    f.write(text)
