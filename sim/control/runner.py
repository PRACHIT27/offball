import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.local import messages
from sim.control.senders import Sender, make_sender
from sim.output import generate
from sim.storyline import BUILT_IN, load

CACHE = Path(os.environ.get("MATCH_CACHE", "/tmp/offball-matches"))
HALFTIME_S = float(os.environ.get("HALFTIME_S", "120"))


@dataclass
class Status:
    phase: str = "idle"
    storyline: str | None = None
    seed: int | None = None
    match_id: str | None = None
    speed: float = 10.0
    mess: str = "light"
    home: str | None = None
    away: str | None = None
    minute: float = 0.0
    period: int | None = None
    sent: dict = field(default_factory=lambda: {"A": 0, "B": 0})
    total: int = 0
    started_at: float | None = None
    elapsed_s: float = 0.0
    message: str = ""


def match_dir(storyline: str, seed: int | None, mess: str) -> Path:
    return CACHE / f"{storyline}-{seed if seed is not None else 'default'}-{mess}"


def prepare(storyline: str, seed: int | None, mess: str) -> tuple[Path, dict]:
    out = match_dir(storyline, seed, mess)
    meta_path = out / "match" / "match.json"
    if not meta_path.exists():
        generate(load(storyline, seed), out, mess, halftime_s=HALFTIME_S)
    return out / "feeds", json.loads(meta_path.read_text())


def plan(feeds_dir: Path, speed: float) -> list[tuple[float, str, str, dict]]:
    msgs = list(messages(feeds_dir))
    kickoff = next(m.wall_ms for m in msgs if m.feed == "B")
    return [(max(0.0, (m.wall_ms - kickoff) / 1000 / speed), m.feed, m.body, m.properties)
            for m in msgs]


def clock_of(body: str) -> tuple[int, float] | None:
    if '"msgType":"event"' not in body:
        return None
    msg = json.loads(body)
    return msg["periodId"], (45 if msg["periodId"] == 2 else 0) + msg["timeSec"] / 60


class Runner:
    def __init__(self, sender_factory=make_sender):
        self.status = Status()
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None
        self.sender_factory = sender_factory

    def snapshot(self) -> dict:
        with self.lock:
            s = asdict(self.status)
        if s["started_at"] and s["phase"] in ("preparing", "streaming", "half-time"):
            s["elapsed_s"] = round(time.time() - s["started_at"], 1)
        return s

    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def play(self, storyline: str, seed: int | None, speed: float, mess: str) -> dict:
        if storyline not in BUILT_IN and storyline != "random":
            raise ValueError(f"unknown storyline {storyline}")
        if not 1 <= speed <= 60:
            raise ValueError("speed must be between 1 and 60")
        if mess not in ("off", "light", "full"):
            raise ValueError("mess must be off, light or full")
        if self.busy():
            raise RuntimeError("a match is already playing")
        self.stop_flag.clear()
        with self.lock:
            self.status = Status(phase="preparing", storyline=storyline, seed=seed, speed=speed,
                                 mess=mess, started_at=time.time(),
                                 message="Preparing the match")
        self.thread = threading.Thread(target=self._run, args=(storyline, seed, speed, mess),
                                       daemon=True)
        self.thread.start()
        return self.snapshot()

    def stop(self) -> dict:
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=10)
        return self.snapshot()

    def _set(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self.status, k, v)

    def _run(self, storyline: str, seed: int | None, speed: float, mess: str) -> None:
        sender: Sender | None = None
        try:
            feeds, meta = prepare(storyline, seed, mess)
            schedule = plan(feeds, speed)
            self._set(match_id=meta["match_id"], home=meta["home"], away=meta["away"],
                      total=len(schedule), phase="streaming", message="Streaming to the pipeline")
            sender = self.sender_factory()
            start = time.monotonic()
            i, sent = 0, {"A": 0, "B": 0}
            while i < len(schedule):
                if self.stop_flag.is_set():
                    self._set(phase="stopped", message="Stopped", sent=dict(sent))
                    return
                wait = schedule[i][0] - (time.monotonic() - start)
                if wait > 0:
                    if wait > 2:
                        self._set(phase="half-time" if self.status.period == 1
                                  and self.status.minute > 44 else "streaming")
                    time.sleep(min(wait, 0.05))
                    continue
                due: dict[str, list] = {"A": [], "B": []}
                now = time.monotonic() - start
                while i < len(schedule) and schedule[i][0] <= now:
                    _, feed, body, props = schedule[i]
                    due[feed].append((body, props))
                    c = clock_of(body) if feed == "A" else None
                    if c:
                        self._set(period=c[0], minute=round(c[1], 1), phase="streaming")
                    i += 1
                for feed, items in due.items():
                    sender.send(feed, items)
                    sent[feed] += len(items)
                self._set(sent=dict(sent))
            self._set(phase="finished", message="Full time")
        except Exception as e:
            self._set(phase="error", message=f"{type(e).__name__}: {e}")
        finally:
            if sender:
                sender.close()
