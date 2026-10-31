"""Private local B14 management entrypoint; address is fixed to loopback."""
from app.com2_admin_runtime import create_admin_app

app = create_admin_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8781, proxy_headers=False, access_log=False, log_level="warning")
