import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routers import auth, groups, profiles, reviews

app = FastAPI(title="AnkiHelper")
app.include_router(auth.router)
app.include_router(reviews.router)
app.include_router(profiles.router)
app.include_router(groups.router)


@app.exception_handler(httpx.RequestError)
def upstream_unreachable(request: Request, exc: httpx.RequestError):
    # Supabase timed out or couldn't be reached: retryable, not a bug in this API.
    return JSONResponse({"detail": "Upstream service unavailable"}, status_code=502)


@app.get("/health")
def health():
    return {"status": "ok"}
