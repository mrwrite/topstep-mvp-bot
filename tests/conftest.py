import os

# Test configuration is established before application modules are imported.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-suite-secret")
os.environ.setdefault("ALLOW_CREATE_ALL", "true")
