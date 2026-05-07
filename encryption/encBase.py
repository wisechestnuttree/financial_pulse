import os
from dotenv import load_dotenv

# 상대 경로 지정
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.normpath(os.path.join(current_dir, "..", ".env"))
load_dotenv(env_path)

# 후추 및 api-key
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "fp-admin-secret-key-2000")
pepper= os.getenv("SECRET_PEPPER")