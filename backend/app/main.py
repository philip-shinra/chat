from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.health import router as health_router
from app.routers.user import router as user_router
from app.routers.spaces import router as space_router
from app.websockets.chat import router as chat_ws_router
import uvicorn

app = FastAPI(
    title="Backend server"
)

# the Vite dev server runs on a different origin, so the browser needs this
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(user_router,tags=["Users"])
app.include_router(space_router,tags=["Space"])
app.include_router(chat_ws_router)

if __name__== "__main__":
    uvicorn.run(
        "app.main:app",
        host = "0.0.0.0",
        port = 8080,
        reload=True
        )