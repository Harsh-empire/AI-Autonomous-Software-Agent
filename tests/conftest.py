"""Shared pytest setup."""

import os

# ide_server adds TrustedHostMiddleware at import time. Starlette's TestClient uses the host name
# "testserver", so allow it for the test run only (production default is loopback only).
os.environ.setdefault("AEGIS_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
