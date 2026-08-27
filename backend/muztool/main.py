from __future__ import annotations

import uvicorn

from .config import HOST, PORT, ensure_dirs


def run() -> None:
    ensure_dirs()
    uvicorn.run("muztool.api:app", host=HOST, port=PORT, reload=False, server_header=False)


if __name__ == "__main__":
    run()
