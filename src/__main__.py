"""
エントリーポイント

使用方法:
  uv run python -m src
"""

import uvicorn


def main():
    """サーバー起動"""
    uvicorn.run(
        "src.server.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
