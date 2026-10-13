from fastapi import FastAPI

from app.routers import auth, reviews

app = FastAPI(title="AnkiHelper")
app.include_router(auth.router)
app.include_router(reviews.router)


@app.get("/health")
def health():
    return {"status": "ok"}
