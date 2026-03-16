from fastapi import FastAPI

from app.routes import router as api_router


app = FastAPI(title="Threat Alerts Backend")

app.include_router(api_router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}

