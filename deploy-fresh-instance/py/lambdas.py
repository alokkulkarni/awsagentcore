"""Fix-ups to Lambdas the repo's deploy scripts make.

    injector-code   aria-session-injector-qconnect with the bank's sample data (scripts/build_injector_zip.sh):
                    its own deploy script zips the handler alone, so ARIA's greeting would have no products
    routing-queues  the routing table aria-routing-config is seeded with today's queue IDs: swap each for the new
                    queue with the same name, so escalations land in this instance's queues
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from common import ROOT, TEMPLATES, cli, fail, load_json, ok

LIVE = load_json(TEMPLATES / "live-map.json")
INJECTOR = "aria-session-injector-qconnect"
ROUTING_TABLE = "aria-routing-config"


def injector_code(ctx) -> None:
    lam = ctx.client("lambda")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "injector.zip"
        subprocess.run(["bash", str(ROOT / "scripts/build_injector_zip.sh"), str(zip_path)], check=True,
                       stdout=subprocess.DEVNULL)
        lam.update_function_code(FunctionName=INJECTOR, ZipFile=zip_path.read_bytes())
    lam.get_waiter("function_updated_v2").wait(FunctionName=INJECTOR)
    ok(f"{INJECTOR} now carries the sample bank data (products in ARIA's greeting)")


def routing_queues(ctx) -> None:
    ddb = ctx.client("dynamodb")
    new_by_name = json.loads(ctx.state.need("QUEUES_JSON"))
    name_by_old = {old: name for name, old in LIVE["queues"].items()}
    changed = 0
    for item in ddb.scan(TableName=ROUTING_TABLE).get("Items", []):      # a handful of rows: one page
        old = item.get("queueId", {}).get("S", "")
        if old not in name_by_old:
            continue
        new = new_by_name.get(name_by_old[old])
        if not new:
            fail(f"No new queue called {name_by_old[old]!r} (run the queues step).")
        ddb.update_item(TableName=ROUTING_TABLE, Key={"topicCategory": item["topicCategory"]},
                        UpdateExpression="SET queueId = :q", ExpressionAttributeValues={":q": {"S": new}})
        changed += 1
    ok(f"{changed} routing rows now point at this instance's queues")


if __name__ == "__main__":
    cli(__doc__, {"injector-code": injector_code, "routing-queues": routing_queues})
