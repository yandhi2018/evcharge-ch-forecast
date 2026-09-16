import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

with open(ROOT / "config" / "config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

DATABASE_URL = (
    f"postgresql+psycopg2://{os.environ.get('POSTGRES_USER', 'evcharge')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', '')}"
    f"@{os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}"
    f"/{os.environ.get('POSTGRES_DB', 'evcharge')}"
)

RAW_DATA_DIR = ROOT / "data" / "raw"
