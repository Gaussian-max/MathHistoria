import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
MODEL = os.getenv("MODEL", "gemini-3-flash-preview")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
