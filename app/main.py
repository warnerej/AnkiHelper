from fastapi import FastAPI

from app.routers import auth, profiles, reviews

app = FastAPI(title="AnkiHelper")
app.include_router(auth.router)
app.include_router(reviews.router)
app.include_router(profiles.router)


@app.get("/health")
def health():
    return {"status": "ok"}
