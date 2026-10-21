from fastapi import FastAPI

from app.routers import auth, groups, profiles, reviews

app = FastAPI(title="AnkiHelper")
app.include_router(auth.router)
app.include_router(reviews.router)
app.include_router(profiles.router)
app.include_router(groups.router)


@app.get("/health")
def health():
    return {"status": "ok"}
