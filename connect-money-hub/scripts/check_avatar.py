#!/usr/bin/env python3
"""
check_avatar.py
===============
Sets up and checks the face on Money Hub calls (Tavus), from the settings in
connect-money-hub/.env. Prints no key or token. Touches no AWS.

    python3 connect-money-hub/scripts/check_avatar.py               check the key, face and PAL (no minutes used)
    python3 connect-money-hub/scripts/check_avatar.py --faces       list Tavus's stock faces, to choose TAVUS_FACE_ID
    python3 connect-money-hub/scripts/check_avatar.py --create-pal  make the echo PAL and save TAVUS_PAL_ID in .env

The echo PAL makes the face repeat the call's audio and nothing else: it has no
language model, no speech recognition and no voice of its own.
"""

import argparse
import re
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(FOLDER), str(FOLDER / "scripts")]

from local_preview import read_env  # noqa: E402
from moneyhub import avatar  # noqa: E402

ENV_FILE = FOLDER / ".env"
HINTS = {"tavus http 401": "the key was refused", "tavus http 403": "the key was refused",
         "tavus http 404": "the face or PAL id wasn't found", "tavus http 402": "no minutes left on the account",
         "tavus http 400": "Tavus didn't accept the request (often a face or PAL id that doesn't exist, or the "
                           "concurrent conversation limit)"}


def fail(error: avatar.AvatarError) -> int:
    print(f"[FAIL] Tavus said no ({error}{': ' + HINTS[str(error)] if str(error) in HINTS else ''}).")
    return 1


def save_pal_id(pal_id: str) -> None:
    """Puts TAVUS_PAL_ID=<id> in .env (an id, not a secret), keeping everything else as it is."""
    text = ENV_FILE.read_text(encoding="utf-8")
    line = f"TAVUS_PAL_ID={pal_id}"
    text = re.sub(r"(?m)^TAVUS_PAL_ID=.*$", line, text) if re.search(r"(?m)^TAVUS_PAL_ID=", text) \
        else text.rstrip("\n") + f"\n{line}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up and check the face on Money Hub calls (Tavus).")
    parser.add_argument("--faces", action="store_true", help="list Tavus's stock faces")
    parser.add_argument("--create-pal", action="store_true", help="make the echo PAL and save its id in .env")
    args = parser.parse_args()
    settings = read_env(ENV_FILE)
    key, face, pal = (settings.get(k, "") for k in ("TAVUS_API_KEY", "TAVUS_FACE_ID", "TAVUS_PAL_ID"))
    if not key:
        print(f"[FAIL] Put TAVUS_API_KEY in {ENV_FILE} first.")
        return 1
    try:
        if args.faces:
            faces = avatar.stock_faces(key)
            print(f"Tavus stock faces ({len(faces)}). Watch them on platform.tavus.io, then put the one you want in "
                  f"{ENV_FILE.name} as TAVUS_FACE_ID:\n")
            for f in faces:
                print(f"  {f['face_id']:<16} {f['model_name'] or '':<12} {f['face_name'] or ''}")
            return 0
        if not face:
            print("[FAIL] Put TAVUS_FACE_ID in .env first (--faces lists the stock faces).")
            return 1
        if args.create_pal:
            pal_id = avatar.create_echo_pal(key, face)
            save_pal_id(pal_id)
            print(f"[ OK ] Made the echo PAL {pal_id} and saved it in {ENV_FILE.name} as TAVUS_PAL_ID.")
            print("       Next: python3 connect-money-hub/scripts/check_avatar.py")
            return 0
        if not pal:
            print("[FAIL] Put TAVUS_PAL_ID in .env first (--create-pal makes one and saves it).")
            return 1
        avatar.start(key, face, pal, test=True)
    except avatar.AvatarError as error:
        return fail(error)
    print(f"[ OK ] Tavus accepted the key, face {face} and PAL {pal} (a test conversation: no minutes used).")
    print("       Next: python3 connect-money-hub/scripts/local_preview.py --avatar-demo   (see the face speak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
