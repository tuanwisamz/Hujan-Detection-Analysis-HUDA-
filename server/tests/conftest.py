import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests never touch real services.
for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN"):
    os.environ[key] = ""
os.environ.setdefault("CRON_SECRET", "test-cron-secret")
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")
os.environ.setdefault("MODEL_PATH", str(Path(__file__).parent / "no-model.txt"))
