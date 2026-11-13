import os
import sys
import types

os.environ.setdefault("DATABASE_URL", "sqlite:///test_db.sqlite3")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret")

# fcntl só existe em Linux/macOS. Nos testes rodando no Windows, usamos um stub.
if sys.platform == "win32" and "fcntl" not in sys.modules:
    fcntl_stub = types.ModuleType("fcntl")
    fcntl_stub.LOCK_EX = 2
    fcntl_stub.LOCK_SH = 1
    fcntl_stub.LOCK_UN = 8
    fcntl_stub.LOCK_NB = 4
    fcntl_stub.flock = lambda *args, **kwargs: None
    fcntl_stub.lockf = lambda *args, **kwargs: None
    sys.modules["fcntl"] = fcntl_stub