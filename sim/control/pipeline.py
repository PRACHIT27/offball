"""Wake the live pipeline on Play and put it to sleep when nobody is playing.

The engine, insights service and cue manager are Container Apps that cost money while they wait.
Match control starts them when someone presses Play, waits until they are ready, and stops them
again after IDLE_MINUTES with no match. Container Apps REST API with match control's own
managed identity (id-sim), which may only read, start and stop those apps.

Off unless PIPELINE_APPS is set, so local and dry-run match control never touch Azure.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

ARM = "https://management.azure.com"
API = "2024-03-01"
WAKE_LIMIT_S = 180


class Arm:
    """The three calls Pipeline needs, against the Container Apps REST API."""

    def __init__(self, subscription: str, resource_group: str, credential=None) -> None:
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self.credential = credential
        self.base = (f"{ARM}/subscriptions/{subscription}/resourceGroups/{resource_group}"
                     f"/providers/Microsoft.App/containerApps")

    def _call(self, method: str, url: str) -> dict:
        token = self.credential.get_token(f"{ARM}/.default").token
        req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None,
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    def status(self, app: str) -> str:
        return self._call("GET", f"{self.base}/{app}?api-version={API}")["properties"].get(
            "runningStatus", "Unknown")

    def start(self, app: str) -> None:
        self._call("POST", f"{self.base}/{app}/start?api-version={API}")

    def stop(self, app: str) -> None:
        self._call("POST", f"{self.base}/{app}/stop?api-version={API}")


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class Pipeline:
    def __init__(self, apps: list[str], arm, health_urls: list[str], idle_minutes: float = 20,
                 healthy: Callable[[str], bool] = http_ok, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.apps, self.arm, self.health_urls = apps, arm, health_urls
        self.idle_s = idle_minutes * 60
        self.healthy, self.clock, self._sleep = healthy, clock, sleep
        self.last_active = clock()  # from boot: apps left running get turned off too
        self.playing = False
        self.state = "unknown"  # asleep / waking / awake / unknown
        self.lock = threading.Lock()

    # ---------- wake and sleep ----------

    def wake(self) -> None:
        """Start whatever isn't running and return once the pipeline can take a match."""
        with self.lock:
            self.playing = True
            self.state = "waking"
        deadline = self.clock() + WAKE_LIMIT_S
        while self.clock() < deadline:
            states = {a: self.arm.status(a) for a in self.apps}
            for app, s in states.items():
                if s == "Stopped":
                    try:
                        self.arm.start(app)
                    except urllib.error.HTTPError:  # still stopping: try again next round
                        pass
            if all(s == "Running" for s in states.values()) and \
                    all(self.healthy(u) for u in self.health_urls):
                self.state = "awake"
                return
            self._sleep(5)
        self.state = "unknown"
        raise TimeoutError(f"the pipeline did not wake within {WAKE_LIMIT_S // 60} minutes")

    def match_over(self) -> None:
        with self.lock:
            self.playing = False
            self.last_active = self.clock()

    def sleep_if_idle(self) -> bool:
        """Stop the apps after idle_s with no match. Returns True if it stopped them."""
        with self.lock:
            if self.playing or self.clock() - self.last_active < self.idle_s:
                return False
        running = [a for a in self.apps if self.arm.status(a) != "Stopped"]
        for app in running:
            self.arm.stop(app)
        self.state = "asleep"
        return bool(running)

    def watch(self, every_s: float = 60) -> None:
        """The idle thread: checks once a minute, forever. Errors never stop match control."""
        while True:
            try:
                self.sleep_if_idle()
            except Exception:  # an ARM hiccup: try again next minute
                pass
            self._sleep(every_s)


def from_env() -> Pipeline | None:
    apps = [a for a in os.environ.get("PIPELINE_APPS", "").split(",") if a]
    if not apps:
        return None
    arm = Arm(os.environ["AZ_SUBSCRIPTION"], os.environ["AZ_RESOURCE_GROUP"])
    urls = [u for u in os.environ.get("PIPELINE_HEALTH_URLS", "").split(",") if u]
    return Pipeline(apps, arm, urls, float(os.environ.get("IDLE_MINUTES", "20")))
