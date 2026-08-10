import hashlib
import hmac
import os
from dotenv import load_dotenv

from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db, engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI()

load_dotenv()

WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {e}"
        )


@app.post("/github/webhook")
async def github_webhook(request: Request):
    # raw request body
    body = await request.body()

    # github sig
    signature = request.headers.get("X-Hub-Signature-256")

    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook signature"
        )

    expected_signature = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    payload = await request.json()

    print(payload)

    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=8000)