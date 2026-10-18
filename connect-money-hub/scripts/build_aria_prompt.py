#!/usr/bin/env python3
"""
build_aria_prompt.py
====================
Adds the Money Hub section (prompts/money-hub-aria-block.txt) to ARIA's live
orchestration prompt, straight after </assurance_levels>, and writes the whole
prompt to a file for you to paste (README step 6).

It only READS from AWS (one `aws qconnect get-ai-prompt` call). Running it again
replaces the section; it never duplicates it. Any other section already in the
live prompt (for example card disputes) is kept.

It also moves ARIA's hand-overs to the card dispute and mortgage assistants onto
her Complete tool (handovers.py), which is how they work while she has a
collaborator.

    python3 connect-money-hub/scripts/build_aria_prompt.py
    python3 connect-money-hub/scripts/build_aria_prompt.py --from-file my-export.yaml
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import handovers

FOLDER = Path(__file__).resolve().parents[1]
BLOCK_FILE = FOLDER / "prompts" / "money-hub-aria-block.txt"
OUTPUT_FILE = FOLDER / "prompts" / "aria-prompt-with-money-hub.yaml"
REGION = "eu-west-2"
ASSISTANT_ID = "e6991ed4-e11c-4194-8d20-13889a36bd15"
PROMPT_ID = "37cae8d9-1d2c-49d1-8b1a-771f22f6ab7c"      # ARIA-Banking-Ochestration-Prompt
ANCHOR = "  </assurance_levels>\n"
SYSTEM_LIMIT = 100_000
VARIABLE_LIMIT = 19
EXISTING = re.compile(r"\n  <money_hub>\n.*?\n  </money_hub>\n", re.S)


def live_prompt(region: str, assistant_id: str, prompt_id: str) -> str:
    try:
        result = subprocess.run(["aws", "qconnect", "get-ai-prompt", "--region", region, "--assistant-id", assistant_id,
                                 "--ai-prompt-id", prompt_id, "--output", "json"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        sys.exit(f"Could not read the prompt from AWS ({error}). Sign in, or export it and pass --from-file.")
    prompt = json.loads(result.stdout)["aiPrompt"]
    print(f"Read '{prompt['name']}' from AWS.")
    return prompt["templateConfiguration"]["textFullAIPromptEditTemplateConfiguration"]["text"]


def add_block(prompt: str, block: str) -> str:
    prompt = EXISTING.sub("", prompt)
    if prompt.count(ANCHOR) != 1:
        raise ValueError(f"Expected one '</assurance_levels>' line, found {prompt.count(ANCHOR)}; add the section by hand.")
    indented = "".join(f"  {line}\n" if line else "\n" for line in block.strip("\n").split("\n"))
    return prompt.replace(ANCHOR, f"{ANCHOR}\n{indented}", 1)


def problems(prompt: str) -> list[str]:
    found = []
    system = prompt.split("\nmessages:", 1)[0]
    if len(system) > SYSTEM_LIMIT:
        found.append(f"The system text is {len(system):,} characters; Connect accepts {SYSTEM_LIMIT:,}.")
    variables = set(re.findall(r"\{\{\$\.Custom\.(\w+)\}\}", prompt))
    if len(variables) > VARIABLE_LIMIT:
        found.append(f"The prompt uses {len(variables)} custom variables; Connect accepts {VARIABLE_LIMIT}.")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Add the Money Hub section to ARIA's live prompt.")
    parser.add_argument("--from-file", help="Use this exported prompt instead of reading from AWS")
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    args = parser.parse_args()
    prompt = Path(args.from_file).read_text() if args.from_file else live_prompt(REGION, ASSISTANT_ID, PROMPT_ID)
    built = handovers.fix_prompt(add_block(prompt, BLOCK_FILE.read_text()))
    issues = problems(built)
    if issues:
        sys.exit("Not written:\n  " + "\n  ".join(issues))
    Path(args.output).write_text(built)
    print(f"Wrote {args.output}\n  {len(built):,} characters. Paste the whole file into the AI prompt.")


if __name__ == "__main__":
    main()
