"""Create or update the OffBall Real-Time Dashboard in Fabric (Platform PL-18).

Finds the workspace's Eventhouse KQL database, makes sure the tables exist (broadcast/fabric.py
SCHEMA), and writes the dashboard definition: a match picker and tiles for tactics, the stream,
triggers, ingestion clean-up and engine step time. Every tile is a KQL query over numbers the
engine computed. Keyless: uses your az login. Re-running updates the same dashboard.

    python scripts/fabric_dashboard.py --workspace OffBall
"""

import argparse
import base64
import json
import time
import urllib.request
import uuid

from azure.identity import DefaultAzureCredential

from broadcast.fabric import DATABASE, SCHEMA

API = "https://api.fabric.microsoft.com/v1"
TITLE = "OffBall live match"
# Stable ids so a re-run updates tiles in place (uuid5 of a readable name)
NS = uuid.UUID("6f1d9a52-6c1e-4f43-9d0b-0ff0ba11c0de")


def uid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


M = "where match_id == _match"
LINE = {"multipleYAxes": {"base": {"id": "-1", "label": "", "columns": [],
                                   "yAxisMaximumValue": None, "yAxisMinimumValue": None,
                                   "yAxisScale": "linear", "horizontalLines": []},
                          "additional": [], "showMultiplePanels": False},
        "hideLegend": False, "legendLocation": "bottom", "xColumnTitle": "Match minute",
        "xColumn": None, "yColumns": None, "seriesColumns": None, "xAxisScale": "linear",
        "verticalLine": "", "crossFilterDisabled": False, "drillthroughDisabled": False,
        "crossFilter": [], "drillthrough": [], "selectedDataOnLoad": {"all": True, "limit": 10},
        "dataPointsTooltip": {"all": False, "limit": 1}}


def line(series_col: str | None, y: list[str] | None = None) -> dict:
    return LINE | {"xColumn": "minute", "yColumns": y or ["value"],
                   "seriesColumns": [series_col] if series_col else None}


CARD = {"multiStat__textSize": "auto", "multiStat__valueColumn": None,
        "colorRulesDisabled": False, "colorRules": []}


def series(key: str, scale: str = "") -> str:
    return (f"Stats | {M} and message == 'series'\n"
            f"| project minute, team_id, value = todouble(data.{key}){scale}\n"
            f"| where isnotnull(value) | order by minute asc")


# (name, title, visual, layout x y w h, KQL, visual options)
TILES = [
    ("messages", "Messages streamed", "card", (0, 0, 6, 4),
     f"union Stats, Cues, Triggers | {M} | count", CARD),
    ("goals", "Score (engine)", "card", (6, 0, 6, 4),
     f"Stats | {M} and message == 'shot' and tostring(data.outcome) == 'goal'\n"
     "| summarize goals = count() by team_id", CARD),
    ("cues", "Cues on air / withdrawn", "card", (12, 0, 6, 4),
     f"Cues | {M} | summarize arg_max(cue_version, status) by cue_id\n"
     "| summarize on_air = countif(status == 'on_air'), withdrawn = countif(status == 'withdrawn')",
     CARD),
    ("latency", "Engine step time p95 (ms)", "table", (18, 0, 6, 4),
     f"Latency | {M} | summarize p50 = round(percentile(ms, 50), 2),"
     " p95 = round(percentile(ms, 95), 2) by step", {}),
    ("line", "Defensive line height (m)", "line", (0, 4, 12, 7), series("line_height_m"),
     line("team_id")),
    ("press", "Pressing actions per minute", "line", (12, 4, 12, 7), series("pressing_per_min"),
     line("team_id")),
    ("control", "Control share (%)", "line", (0, 11, 12, 7),
     series("control_share", " * 100"), line("team_id")),
    ("xg", "xG race", "line", (12, 11, 12, 7),
     f"let shots = Stats | {M} and message == 'shot'"
     " | project minute, team_id, value = todouble(data.xg);\n"
     "shots | distinct team_id | extend minute = 0.0, value = 0.0 | union shots\n"
     "| order by team_id asc, minute asc\n"
     "| extend value = round(row_cumsum(value, team_id != prev(team_id)), 2)",
     line("team_id")),
    ("stream", "Stream per match minute, by message", "column", (0, 18, 12, 7),
     f"union (Stats | {M} | project minute, message),\n"
     f"      (Cues | {M} | project minute, message = strcat('cue.', cue_kind)),\n"
     f"      (Triggers | {M} | project minute, message = strcat('trigger.', type))\n"
     "| summarize n = count() by minute = bin(minute, 1), message | order by minute asc", {}),
    ("trigger_types", "Triggers sent to the agents, by type", "pie", (12, 18, 12, 7),
     f"Triggers | {M} | summarize n = count() by type", {}),
    ("ingest", "Ingestion clean-up (running totals)", "line", (0, 25, 12, 7),
     f"Ingest | {M} | order by minute asc\n"
     "| project minute, duplicates = coalesce(toint(counts.duplicates), 0),"
     " corrections = coalesce(toint(counts.corrections), 0),"
     " deletions = coalesce(toint(counts.deletions), 0), gaps = coalesce(toint(counts.gaps), 0),"
     " rejects = coalesce(toint(counts.rejects), 0)",
     line(None, ["duplicates", "corrections", "deletions", "gaps", "rejects"])),
    ("trigger_log", "Trigger log", "table", (12, 25, 12, 7),
     f"Triggers | {M} | order by clock_ms asc\n"
     "| project minute = round(minute, 1), type, reason, team_id,"
     " importance = round(importance, 2)",
     {}),
    ("players", "Players: distance and passing (latest)", "table", (0, 32, 24, 8),
     f"Stats | {M} and message == 'player_totals' | top 1 by clock_ms desc\n"
     "| mv-expand kind = array p = data.players | project player_id = tostring(p[0]), v = p[1]\n"
     "| project player_id, distance_m = todouble(v.distance_m), top_speed_ms = todouble("
     "v.top_speed_ms), sprints = toint(v.sprints), passes = toint(v.passes),"
     " pass_accuracy = round(todouble(v.pass_accuracy) * 100, 1), xg = todouble(v.xg)\n"
     "| where distance_m > 0 | order by distance_m desc", {}),
]


def definition(query_uri: str, workspace_id: str, db_id: str) -> dict:
    ds, page = uid("datasource"), uid("page")
    queries = [{"id": uid("q-matches"), "dataSource": {"kind": "inline", "dataSourceId": ds},
                "text": "Matches | distinct match_id | order by match_id asc",
                "usedVariables": []}]
    tiles = []
    for name, title, visual, (x, y, w, h), text, opts in TILES:
        queries.append({"id": uid(f"q-{name}"), "dataSource": {"kind": "inline",
                                                               "dataSourceId": ds},
                        "text": text, "usedVariables": ["_match"]})
        tiles.append({"id": uid(f"t-{name}"), "title": title, "visualType": visual,
                      "pageId": page, "layout": {"x": x, "y": y, "width": w, "height": h},
                      "queryRef": {"kind": "query", "queryId": uid(f"q-{name}")},
                      "visualOptions": opts})
    return {
        # The Fabric viewer only migrates from versions it knows; 88 is what it asks for (Oct 2026)
        "$schema": "https://dataexplorer.azure.com/static/d/schema/88/dashboard.json",
        "schema_version": 88,
        "title": TITLE,
        "autoRefresh": {"enabled": True, "defaultInterval": "30s", "minInterval": "30s"},
        "baseQueries": [],
        "dataSources": [{"kind": "kusto-trident", "id": ds, "name": DATABASE,
                         "clusterUri": query_uri, "database": db_id,
                         "databaseArtifactId": db_id, "workspace": workspace_id}],
        "pages": [{"id": page, "name": "Live match"}],
        "parameters": [{
            "kind": "string", "id": uid("p-match"), "displayName": "Match",
            "description": "", "variableName": "_match", "selectionType": "scalar",
            "includeAllOption": False, "defaultValue": {"kind": "query-result"},
            "dataSource": {"kind": "query", "columns": {"value": "match_id"},
                           "queryRef": {"kind": "query", "queryId": uid("q-matches")}},
            "showOnPages": {"kind": "all"}}],
        "queries": queries,
        "tiles": tiles,
        "embeddedApps": [],
    }


class Fabric:
    def __init__(self) -> None:
        self.cred = DefaultAzureCredential()

    def call(self, method: str, path: str, body: dict | None = None,
             scope: str = "https://api.fabric.microsoft.com/.default") -> dict:
        url = path if path.startswith("https://") else f"{API}{path}"
        req = urllib.request.Request(url, method=method, headers={
            "Authorization": f"Bearer {self.cred.get_token(scope).token}",
            "Content-Type": "application/json"},
            data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req) as r:
            if r.status == 202 and r.headers.get("Location"):  # long-running operation
                return self.wait(r.headers["Location"], scope)
            raw = r.read()
            return json.loads(raw) if raw else {}

    def wait(self, url: str, scope: str) -> dict:
        for _ in range(60):
            time.sleep(2)
            op = self.call("GET", url, scope=scope)
            if op.get("status") in ("Succeeded", "Failed"):
                if op["status"] == "Failed":
                    raise RuntimeError(op)
                return op
        raise TimeoutError(url)

    def kusto(self, query_uri: str, csl: str) -> None:
        self.call("POST", f"{query_uri}/v1/rest/mgmt", {"db": DATABASE, "csl": csl},
                  scope=f"{query_uri}/.default")


def main() -> None:
    ap = argparse.ArgumentParser(description="Create or update the OffBall Real-Time Dashboard")
    ap.add_argument("--workspace", default="OffBall", help="Fabric workspace name")
    args = ap.parse_args()
    f = Fabric()
    ws = next(w for w in f.call("GET", "/workspaces")["value"]
              if w["displayName"] == args.workspace)
    db = next(d for d in f.call("GET", f"/workspaces/{ws['id']}/kqlDatabases")["value"]
              if d["displayName"] == DATABASE)
    query_uri = db["properties"]["queryServiceUri"]
    for table, columns in SCHEMA.items():
        f.kusto(query_uri, f".create-merge table {table} ({columns})")
    payload = base64.b64encode(json.dumps(definition(query_uri, ws["id"], db["id"]))
                               .encode()).decode()
    parts = {"definition": {"parts": [{"path": "RealTimeDashboard.json", "payload": payload,
                                       "payloadType": "InlineBase64"}]}}
    existing = next((d for d in f.call("GET", f"/workspaces/{ws['id']}/kqlDashboards")["value"]
                     if d["displayName"] == TITLE), None)
    if existing:
        f.call("POST", f"/workspaces/{ws['id']}/kqlDashboards/{existing['id']}/updateDefinition",
               parts)
        dash_id = existing["id"]
    else:
        f.call("POST", f"/workspaces/{ws['id']}/kqlDashboards",
               {"displayName": TITLE, **parts})
        dash_id = next(d["id"] for d in
                       f.call("GET", f"/workspaces/{ws['id']}/kqlDashboards")["value"]
                       if d["displayName"] == TITLE)
    print(f"dashboard: https://app.fabric.microsoft.com/groups/{ws['id']}/kustodashboards/"
          f"{dash_id}?experience=fabric-developer")
    print(f"eventhouse query uri: {query_uri}")


if __name__ == "__main__":
    main()
