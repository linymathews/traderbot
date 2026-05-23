import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.profile import profile_router
from app.api.company import company_router
from app.api.auth import auth_router, get_authenticated_user
from app.api.jobs import jobs_router, start_job_loop, stop_job_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)

app = FastAPI(
    title="TraderBot",
    description="Portfolio monitor with congressional trade signals and technical analysis",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(profile_router)
app.include_router(company_router)
app.include_router(auth_router)
app.include_router(jobs_router)


@app.on_event("startup")
async def startup_jobs_loop():
    start_job_loop()


@app.on_event("shutdown")
async def shutdown_jobs_loop():
    stop_job_loop()


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path

    # Protect API endpoints except auth/session checks and docs/health.
    if request.method != "OPTIONS" and path.startswith("/api"):
        public_api_paths = {
            "/api/auth/google",
            "/api/auth/login",
            "/api/auth/session",
            "/api/auth/logout",
        }
        if path not in public_api_paths:
            user = get_authenticated_user(request)
            if user is None:
                return JSONResponse(status_code=401, content={"detail": "Authentication required"})

    return await call_next(request)


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}

# Serve the frontend SPA from /frontend/dist if it exists
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
