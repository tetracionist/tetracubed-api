#!/usr/bin/env python
"""Manage the USERS_DB JSON used by main.py auth.

Reads from .env, mutates the JSON object, writes it back (single-quoted so the
$argon2id$ prefix isn't treated as a shell/dotenv variable). The final JSON is
printed to stdout so you can pipe it into `gh secret set USERS_DB --body -`,
or pass --push to do that automatically.

Usage:
    uv run python scripts/manage_users.py add alice --email a@example.com
    uv run python scripts/manage_users.py set-password alice
    uv run python scripts/manage_users.py remove alice
    uv run python scripts/manage_users.py list
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values
from pwdlib import PasswordHash


def load_db(env_path: Path) -> dict:
    if not env_path.exists():
        return {}
    raw = dotenv_values(env_path).get("USERS_DB") or "{}"
    return json.loads(raw)


def save_db(env_path: Path, db: dict) -> str:
    blob = json.dumps(db, separators=(",", ":"))
    line = f"USERS_DB='{blob}'\n"

    if not env_path.exists():
        env_path.write_text(line)
        return blob

    out, found = [], False
    for ln in env_path.read_text().splitlines(keepends=True):
        stripped = ln.lstrip()
        if stripped.startswith("USERS_DB=") or stripped.startswith("export USERS_DB="):
            if not found:
                out.append(line)
                found = True
            continue
        out.append(ln)
    if not found:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(line)
    env_path.write_text("".join(out))
    return blob


def prompt_password(prompt: str = "password: ") -> str:
    pw = getpass(prompt)
    if not pw:
        sys.exit("password cannot be empty")
    if getpass("confirm:  ") != pw:
        sys.exit("passwords don't match")
    return pw


def cmd_add(args, db):
    pw = prompt_password()
    user = {
        "username": args.username,
        "hashed_password": PasswordHash.recommended().hash(pw),
    }
    if args.email:
        user["email"] = args.email
    if args.full_name:
        user["full_name"] = args.full_name
    if args.disabled:
        user["disabled"] = True
    verb = "updated" if args.username in db else "added"
    db[args.username] = user
    print(f"{verb} user '{args.username}'", file=sys.stderr)


def cmd_set_password(args, db):
    if args.username not in db:
        sys.exit(f"user '{args.username}' not found")
    db[args.username]["hashed_password"] = PasswordHash.recommended().hash(prompt_password("new password: "))
    print(f"reset password for '{args.username}'", file=sys.stderr)


def cmd_remove(args, db):
    if args.username not in db:
        sys.exit(f"user '{args.username}' not found")
    del db[args.username]
    print(f"removed user '{args.username}'", file=sys.stderr)


def cmd_list(args, db):
    if not db:
        print("(no users)", file=sys.stderr)
        return
    for name in sorted(db):
        extras = {k: v for k, v in db[name].items() if k not in ("username", "hashed_password")}
        suffix = f"  {extras}" if extras else ""
        print(f"{name}{suffix}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", type=Path, default=Path(".env"), help="path to .env (default: ./.env)")
    parser.add_argument("--push", action="store_true", help="also `gh secret set USERS_DB`")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="add or replace a user")
    p.add_argument("username")
    p.add_argument("--email")
    p.add_argument("--full-name")
    p.add_argument("--disabled", action="store_true")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("set-password", help="reset a user's password")
    p.add_argument("username")
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("remove", help="remove a user")
    p.add_argument("username")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("list", help="list users (no hashes)")
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    db = load_db(args.env)
    args.func(args, db)

    if args.cmd == "list":
        return

    blob = save_db(args.env, db)
    print(blob)

    if args.push:
        subprocess.run(["gh", "secret", "set", "USERS_DB", "--body", blob], check=True)
        print("pushed to GitHub secret USERS_DB", file=sys.stderr)


if __name__ == "__main__":
    main()
