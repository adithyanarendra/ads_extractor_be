import os
from dotenv import load_dotenv

load_dotenv()

R2_BUCKET = os.getenv("R2_BUCKET")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
ACCOUNT_HASH = os.getenv("ACCOUNT_HASH")
FILES_SERVICE_API_KEY = os.getenv("FILES_SERVICE_API_KEY")
FILES_SERVICE_BASE_URL = os.getenv("FILES_SERVICE_BASE_URL")
