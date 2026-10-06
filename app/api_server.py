import uvicorn
from .config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("app.api:app", host=s.api_bind, port=s.api_port, reload=False)
