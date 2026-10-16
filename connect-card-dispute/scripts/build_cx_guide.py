#!/usr/bin/env python3
"""
build_cx_guide.py
=================
Writes two sections of acxd/disputes-assistant.md from acxd/data-requests.json:

    Part 2c   the seven Data requests, each with every step written out
    Part 3b   step 7, the seven tools on the Live Sync node, each written out

So the description, samples and inputs are the same in both places, and the
same as the dispute service expects (the unit tests check both). Edit the JSON,
never those two sections by hand, then run:

    python3 connect-card-dispute/scripts/build_cx_guide.py

Local files only; it never calls AWS.
"""

import json
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
GUIDE = FOLDER / "acxd" / "disputes-assistant.md"
DATA = FOLDER / "acxd" / "data-requests.json"

INTRO_2C = """### 2c. Data requests (7)

**What they are.** A Data request is one tool the assistant can use: a call to the dispute service.
Each has a **name**, a **description** the assistant reads to decide when to use it, and a
**request** and **response** shape. All seven call the same address; only the `operation` field and
the other fields differ.

Below are seven sections, one per Data request, each with every step and every value written out.
Do them in order. Each takes about five minutes. Already made them? Open each one and compare it
with its section: the description and both samples must match exactly. Where they differ, paste
the new ones and **Auto-generate** the models again.

Every reply has `ok`, `reason` and `message`. When `ok` is false, `message` tells the assistant what
to do, and it follows it. None of these takes a customer ID or a phone number: the service finds
both from the call or chat itself, and does nothing for a customer ARIA didn't verify. None can
confirm or submit a dispute.

If a test goes wrong:
- **`401`**: the `x-api-key` header isn't using the Secret chip (step 4.5).
- **The response sample comes back unchanged**: the Data request is Static; choose External.
- **Timeout or "could not connect"**: the endpoint URL is wrong; copy it again from the deploy output.

"""

INTRO_TOOLS = """7. **Tools.** Still in the `CardDisputeAssistant` node, find its **Tools** section. You add seven
   tools here, one for each Data request from Part 2c. The tool prompt is the same text as that Data
   request's description. Each tool below has every step written out. Already added them? Open
   each one and compare: the tool prompt and the inputs must match its section below.

   **The rule for inputs, the same in every tool:**
   - `operation` → **Explicit text**, typed exactly as shown.
   - `contactId` → **Variable** → the context variable `contactId`. ⚠️ Never Explicit text with a
     `{contactId}` chip inside it: the designer then sends the chip's placeholder instead of the
     real ID, and every tool answers `customer_not_identified`. The mortgage build hit exactly this.
   - Everything else → **LLM prompt**: the assistant fills it in from the conversation.

"""


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def data_request_section(number: int, d: dict) -> str:
    request, response = _compact(d["request"]), _compact(d["response"])
    test_values = "\n".join(f"      - `{k}`: `{v}`" for k, v in d["request"].items())
    numbers = [k for k, v in d["request"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    number_note = (f"\n   Check that {', '.join(f'`{n}`' for n in numbers)} came out as type **Number**, not Text."
                   if numbers else "")
    return f"""#### `{d["name"]}`

Data request {number} of 7. This one {d["purpose"]}.

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: `{d["name"]}`
3. **Description**: copy and paste this (the assistant reads it, so don't change it):
   ```text
   {d["description"]}
   ```
4. Open the **Implementation** tab and choose **External** (not Static).
   1. **Method**: `POST`.
   2. **Production** endpoint URL: the **Data request address** from the deploy script.
   3. **Development** endpoint URL: the same address.
   4. **Headers** → add a header: key `Content-Type`, value `application/json`.
   5. Add a second header: key `x-api-key`. Click in its value box, type `{{`, choose **Secrets**,
      then `card_dispute_api_key`. It becomes a chip.
5. **Request model** → **Auto-generate** (star icon) → paste this, then confirm:
   ```json
   {request}
   ```{number_note}
6. **Response model** → **Auto-generate** → paste this, then confirm:
   ```json
   {response}
   ```
7. **Save**.
8. **Test**: **Test** tab → environment **Development** → enter these values → **Run**:
{test_values}

   ✅ `"ok": false` and `"reason": "customer_not_identified"`. That's correct for a test (no real
   verified customer), and proves it reached the service. ❌ `401`: redo step 4.5.

The same two samples, for reference only (nothing more to do):

| Request sample | `{request}` |
|---|---|
| Response sample | `{response}` |

"""


def tool_section(number: int, d: dict, hints: dict) -> str:
    rows = [f"      | `operation` | **Explicit text** | type exactly: `{d['name']}` |",
            "      | `contactId` | **Variable** | pick the context variable `contactId` from the list |"]
    rows += [f"      | `{field}` | **LLM prompt** | if there's a description box: {hints[field]} |"
             for field in d["request"] if field not in ("operation", "contactId")]
    table = "\n".join(rows)
    return f"""   **Tool {number} of 7: `{d["name"]}`** ({d["purpose"]})

   1. In the **Tools** section, click **Add tool** (or **+**). Choose type **Data request**.
   2. Pick **`{d["name"]}`** from the list.
   3. **Tool prompt** (some screens say **Description** or **Instructions**): paste
      ```text
      {d["description"]}
      ```
   4. The tool lists its **inputs**, one for each field below. For each input, open its source
      drop-down and choose as shown:

      | Input | Source | Value |
      |-------|--------|-------|
{table}

   5. **Save** the tool (or close its panel), and check `{d["name"]}` now appears in the Tools list.

"""


def render(guide: str, data: dict) -> str:
    """The guide with Part 2c and Part 3b step 7 rewritten from the data."""
    requests, hints = data["dataRequests"], data["inputHints"]
    new_2c = INTRO_2C + "".join(data_request_section(i + 1, d) for i, d in enumerate(requests)) + \
        "✅ **Check before Part 3:** the Data requests list shows all seven new names, and each tested as above.\n\n---\n\n"
    guide = guide[:guide.index("### 2c. Data requests")] + new_2c + guide[guide.index("## Part 3"):]
    new_7 = INTRO_TOOLS + "".join(tool_section(i + 1, d, hints) for i, d in enumerate(requests)) + \
        "   ✅ The Tools list shows all seven: " + ", ".join(f"`{d['name']}`" for d in requests) + ".\n\n"
    return guide[:guide.index("7. **Tools.**")] + new_7 + guide[guide.index("8. **Data capture.**"):]


def main() -> None:
    GUIDE.write_text(render(GUIDE.read_text(), json.loads(DATA.read_text())))
    print(f"Wrote Part 2c and Part 3b step 7 of {GUIDE}")


if __name__ == "__main__":
    main()
