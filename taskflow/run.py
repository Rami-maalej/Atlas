"""TaskFlow application entry point.

Run with: python run.py
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("TASKFLOW_HOST", "127.0.0.1"),
        port=int(os.getenv("TASKFLOW_PORT", "8000")),
        reload=os.getenv("TASKFLOW_RELOAD", "0") == "1",
    )
