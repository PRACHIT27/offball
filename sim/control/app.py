import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from sim.clubs import CLUBS
from sim.control.pipeline import from_env
from sim.control.runner import Runner, prepare
from sim.storyline import BUILT_IN

PAGE = Path(__file__).with_name("page.html")
TITLES = {
    "red_card": "The Red Card: a 70' sending-off changes everything",
    "comeback": "The Comeback: two goals down, three late goals",
    "switch": "The Switch: a half-time change of shape",
    "late_drama": "Late Drama: a red card and two goals after 85'",
    "press_fade": "Press Fade: a pressing side runs out of legs",
    "storm": "The Storm: rain, wind and a review stoppage",
    "random": "Random: a new match story for every seed",
}


@asynccontextmanager
async def lifespan(_app):
    if os.environ.get("WARM_STORYLINE"):
        threading.Thread(target=prepare, args=(os.environ["WARM_STORYLINE"], None, "light"),
                         daemon=True).start()
    if runner.pipeline:
        threading.Thread(target=runner.pipeline.watch, daemon=True).start()
    yield


app = FastAPI(title="OffBall match control", docs_url=None, redoc_url=None, lifespan=lifespan)
runner = Runner(pipeline=from_env())


class PlayRequest(BaseModel):
    storyline: str = "red_card"
    seed: int | None = Field(default=None, ge=0, le=999_999)
    speed: float = 10.0
    mess: str = "light"


def _check(key: str | None) -> None:
    expected = os.environ.get("CONTROL_PASSCODE")
    if expected and key != expected:
        raise HTTPException(status_code=401, detail="Wrong or missing passcode")


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/healthz")
def health() -> dict:
    return {"ok": True}


@app.get("/api/storylines")
def storylines() -> dict:
    items = []
    for name, story in BUILT_IN.items():
        items.append({"name": name, "title": TITLES.get(name, name), "match_id": story.match_id,
                      "home": CLUBS[story.home].name, "away": CLUBS[story.away].name})
    items.append({"name": "random", "title": TITLES["random"], "match_id": None,
                  "home": None, "away": None})
    return {"storylines": items, "passcode_required": bool(os.environ.get("CONTROL_PASSCODE"))}


@app.get("/api/status")
def status() -> dict:
    s = runner.snapshot()
    s["pipeline"] = runner.pipeline.state if runner.pipeline else "off"
    # Where the match is watched (the viewer screen); unset locally
    s["viewer_url"] = os.environ.get("VIEWER_URL", "").rstrip("/") or None
    for side in ("home", "away"):
        if s[side] in CLUBS:
            s[f"{side}_name"] = CLUBS[s[side]].name
    return s


@app.post("/api/play")
def play(req: PlayRequest, x_control_key: str | None = Header(default=None)) -> dict:
    _check(x_control_key)
    seed = req.seed if req.storyline == "random" or req.seed is not None else None
    if req.storyline == "random" and seed is None:
        seed = 1
    try:
        return runner.play(req.storyline, seed, req.speed, req.mess)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@app.post("/api/stop")
def stop(x_control_key: str | None = Header(default=None)) -> dict:
    _check(x_control_key)
    return runner.stop()
