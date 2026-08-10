import logging
import os
import threading
import time

import httpx
from fastapi import FastAPI, Request, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("teams-bot")

app = FastAPI()

ORCHESTRATOR_URL     = os.environ["ORCHESTRATOR_URL"]
BOT_APP_ID           = os.environ["BOT_APP_ID"]
BOT_APP_PASSWORD     = os.environ["BOT_APP_PASSWORD"]
ORCHESTRATOR_TIMEOUT = int(os.environ.get("ORCHESTRATOR_TIMEOUT", "180"))
DEFAULT_MODE         = os.environ.get("ORCHESTRATOR_MODE", "smart")

_TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"


def _get_bot_token() -> str:
    r = httpx.post(_TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     BOT_APP_ID,
        "client_secret": BOT_APP_PASSWORD,
        "scope":         "https://api.botframework.com/.default",
    }, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@app.post("/api/messages")
async def messages(request: Request):
    try:
        body = await request.json()
    except Exception:
        log.warning("Bad request — could not parse JSON")
        return Response(status_code=400)

    activity_type = body.get("type", "unknown")
    user = (body.get("from") or {}).get("name", "unknown")

    if activity_type != "message" or not (body.get("text") or "").strip():
        log.info("Ignored activity | type=%s user=%s", activity_type, user)
        return Response(status_code=200)

    question = body["text"].strip()
    log.info(">>> RECEIVED | user=%s | question=%s", user, question)
    threading.Thread(target=_handle, args=(body,), daemon=True).start()
    return Response(status_code=202)


@app.get("/health")
def health():
    return {"status": "ok"}


def _handle(body: dict) -> None:
    question = body["text"].strip()
    user     = (body.get("from") or {}).get("name", "unknown")
    t0       = time.time()

    log.info("--- CALLING ORCHESTRATOR | user=%s | mode=%s | question=%s",
             user, DEFAULT_MODE, question)
    try:
        resp = httpx.post(
            ORCHESTRATOR_URL,
            json={"question": question, "mode": DEFAULT_MODE},
            timeout=ORCHESTRATOR_TIMEOUT,
        )
        resp.raise_for_status()
        data   = resp.json()
        answer = data.get("answer", "(sin respuesta)")
        intent = data.get("macro_intent", "?")
        elapsed = round(time.time() - t0, 1)
        log.info("--- ORCHESTRATOR OK | user=%s | intent=%s | elapsed=%ss | answer_len=%d",
                 user, intent, elapsed, len(answer))
    except Exception as exc:
        elapsed = round(time.time() - t0, 1)
        log.error("--- ORCHESTRATOR ERROR | user=%s | elapsed=%ss | error=%s",
                  user, elapsed, exc)
        answer = f"⚠️ Error al procesar tu pregunta: {exc}"

    _send_proactive(body, answer)


def _send_proactive(body: dict, text: str) -> None:
    user = (body.get("from") or {}).get("name", "unknown")
    try:
        token       = _get_bot_token()
        service_url = body.get("serviceUrl", "").rstrip("/")
        conv_id     = body["conversation"]["id"]
        activity_id = body.get("id", "")
        reply = {
            "type":         "message",
            "conversation": body["conversation"],
            "from":         body.get("recipient", {}),
            "recipient":    body.get("from", {}),
            "replyToId":    activity_id,
            "text":         text,
        }
        url = f"{service_url}/v3/conversations/{conv_id}/activities/{activity_id}"
        r = httpx.post(url, json=reply,
                       headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        log.info("<<< REPLY SENT | user=%s | status=%s", user, r.status_code)
    except Exception as exc:
        log.error("<<< REPLY FAILED | user=%s | error=%s", user, exc)
