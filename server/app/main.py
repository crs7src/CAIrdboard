from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from app import jira
from app.config import Settings, get_settings

app = FastAPI(title="AI Card Board")

SettingsDep = Annotated[Settings, Depends(get_settings)]


@app.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello, world!"}


@app.get("/api/jira/status")
async def jira_status(settings: SettingsDep) -> dict:
    if not settings.jira_configured:
        return {"configured": False, "connected": False, "user": None}
    try:
        user = await jira.fetch_current_user(settings)
    except jira.JiraError:
        return {"configured": True, "connected": False, "user": None}
    return {"configured": True, "connected": True, "user": user}


@app.get("/api/cards")
async def cards(settings: SettingsDep) -> list[jira.Card]:
    if not settings.jira_configured:
        raise HTTPException(
            503, "Jira is not configured. Set JIRA_* values in server/.env"
        )
    try:
        return await jira.fetch_assigned_cards(settings)
    except jira.JiraError as e:
        raise HTTPException(502, str(e)) from e
