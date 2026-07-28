from fastapi import FastAPI
from app.routers.health import router as health_router
from app.routers.user import router as user_router
import uvicorn

app = FastAPI(
    title="Backend server"
)

app.include_router(health_router)
app.include_router(user_router,tags=["Users"])

if __name__== "__main__":
    uvicorn.run(
        "app.main:app",
        host = "0.0.0.0",
        port = 8080,
        reload=True
        )