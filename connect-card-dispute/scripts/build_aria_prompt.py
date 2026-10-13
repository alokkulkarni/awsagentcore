#!/usr/bin/env python3
"""
build_aria_prompt.py
====================
Builds ARIA's orchestration prompt with the card dispute instructions added.

It starts from the prompt that is live in your Connect instance today, not from
a copy in this repository, so nothing you have changed in the console is lost.
It then inserts a dispute section straight after the </assurance_levels>
section and writes the whole prompt to a file for you to paste. Which section
depends on --mode:

    direct   ARIA drafts the dispute itself (prompts/card-disputes-block.txt)
    agents   ARIA hands it to the disputes agent or the Live Sync page
             (prompts/card-disputes-agents-block.txt)

It only READS from AWS (one `aws qconnect get-ai-prompt` call). It changes
nothing there. Run it again at any time: an existing dispute section is replaced,
never duplicated.

Usage:
    python3 connect-card-dispute/scripts/build_aria_prompt.py
    python3 connect-card-dispute/scripts/build_aria_prompt.py --mode agents
    python3 connect-card-dispute/scripts/build_aria_prompt.py --from-file my-export.yaml
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
# Which dispute section ARIA gets:
#   direct  ARIA drafts the dispute itself with the five tools (SPEC Part 1).
#   agents  ARIA hands the dispute to the disputes agent, or to the Live Sync
#           page when the customer has it open (SPEC Part 3). Much shorter.
BLOCK_FILES = {"direct": FOLDER / "prompts" / "card-disputes-block.txt",
               "agents": FOLDER / "prompts" / "card-disputes-agents-block.txt"}
OUTPUT_FILE = FOLDER / "prompts" / "aria-orchestration-prompt-with-disputes.yaml"

REGION = "eu-west-2"
ASSISTANT_ID = "e6991ed4-e11c-4194-8d20-13889a36bd15"
PROMPT_ID = "37cae8d9-1d2c-49d1-8b1a-771f22f6ab7c"      # ARIA-Banking-Ochestration-Prompt

ANCHOR = "  </assurance_levels>\n"
SYSTEM_LIMIT = 100_000          # "System length must not exceed 100000 characters"
VARIABLE_LIMIT = 19             # Connect rejected this prompt at 20 custom variables
EXISTING = re.compile(r"\n  <card_disputes>\n.*?\n  </card_disputes>\n", re.S)


def live_prompt(region: str, assistant_id: str, prompt_id: str) -> str:
    try:
        result = subprocess.run(
            ["aws", "qconnect", "get-ai-prompt", "--region", region, "--assistant-id", assistant_id,
             "--ai-prompt-id", prompt_id, "--output", "json"], capture_output=True, text=True, check=True)
    except FileNotFoundError:
        sys.exit("The AWS CLI was not found. Install it, or export the prompt and pass --from-file.")
    except subprocess.CalledProcessError as error:
        sys.exit(f"Could not read the prompt from AWS:\n{error.stderr.strip()}\n"
                 "Sign in with the AWS CLI, or export the prompt and pass --from-file.")
    prompt = json.loads(result.stdout)["aiPrompt"]
    print(f"Read '{prompt['name']}' from AWS (the latest saved version).")
    return prompt["templateConfiguration"]["textFullAIPromptEditTemplateConfiguration"]["text"]


def add_disputes(prompt: str, block: str) -> str:
    """The prompt with the dispute section after </assurance_levels>, indented like the rest of the system text."""
    prompt = EXISTING.sub("", prompt)      # the section and the blank line added before it
    if prompt.count(ANCHOR) != 1:
        raise ValueError("Expected exactly one '</assurance_levels>' line in the prompt, found "
                         f"{prompt.count(ANCHOR)}. The prompt's structure has changed; add the section by hand.")
    indented = "".join(f"  {line}\n" if line else "\n" for line in block.strip("\n").split("\n"))
    return prompt.replace(ANCHOR, f"{ANCHOR}\n{indented}", 1)


def check(prompt: str) -> list[str]:
    """Reasons Connect would reject the prompt, or an empty list."""
    problems = []
    lines = prompt.split("\n")
    if lines[0] != "system: |":
        problems.append("The first line must be exactly 'system: |'.")
    if "messages:" not in lines:
        problems.append("There is no 'messages:' line at the left edge.")
    else:
        system = "\n".join(line[2:] for line in lines[1:lines.index("messages:")])
        if len(system) >= SYSTEM_LIMIT:
            problems.append(f"The system text is {len(system):,} characters; the limit is {SYSTEM_LIMIT:,}.")
    variables = set(re.findall(r"\{\{\$\.Custom\.([A-Za-z]+)\}\}", prompt))
    if len(variables) > VARIABLE_LIMIT:
        problems.append(f"The prompt uses {len(variables)} custom variables; Connect accepts {VARIABLE_LIMIT}.")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Add the card dispute instructions to ARIA's live prompt.")
    parser.add_argument("--mode", choices=sorted(BLOCK_FILES), default="direct",
                        help="direct: ARIA drafts the dispute itself. agents: ARIA hands it to the disputes "
                             "agent or the Live Sync page (default: %(default)s)")
    parser.add_argument("--from-file", help="Use this exported prompt instead of reading from AWS")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--assistant-id", default=ASSISTANT_ID)
    parser.add_argument("--prompt-id", default=PROMPT_ID)
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    args = parser.parse_args()

    prompt = Path(args.from_file).read_text() if args.from_file \
        else live_prompt(args.region, args.assistant_id, args.prompt_id)
    try:
        built = add_disputes(prompt, BLOCK_FILES[args.mode].read_text())
    except ValueError as error:
        sys.exit(str(error))
    problems = check(built)
    if problems:
        sys.exit("The new prompt would be rejected by Connect:\n- " + "\n- ".join(problems))
    Path(args.output).write_text(built)
    print(f"Wrote {args.output} (mode: {args.mode})")
    print(f"  {len(built.splitlines())} lines, {len(built):,} characters. Paste the whole file into the AI prompt.")


if __name__ == "__main__":
    main()
