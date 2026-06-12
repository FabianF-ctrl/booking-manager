#!/usr/bin/env python3
"""
manage_users.py — zarządzanie użytkownikami i hasłami.

Hasła są przechowywane jako bcrypt hashes w `data/users.json` (chmod 600).
Plik tworzy się automatycznie przy pierwszym wywołaniu `add`.

Użycie:
    python manage_users.py list
    python manage_users.py add admin "haslo" --role admin
    python manage_users.py passwd admin "nowe-haslo"
    python manage_users.py role pracownik1 admin
    python manage_users.py delete user1

Zmiany od razu działają — _USERS_CACHE w app.py jest reloadowany przy
każdym requeście (mtime check).
"""

import sys
import json
import argparse
from pathlib import Path

try:
    import bcrypt
except ImportError:
    print("BŁĄD: brak biblioteki bcrypt. Zainstaluj: pip install bcrypt")
    sys.exit(1)

USERS_FILE = Path(__file__).parent / "data" / "users.json"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def load(allow_missing: bool = False) -> dict:
    if not USERS_FILE.exists():
        if allow_missing:
            return {}
        print(f"❌ Plik {USERS_FILE} nie istnieje. Utwórz pierwszego usera komendą: add admin \"haslo\" --role admin")
        sys.exit(1)
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save(users: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    try:
        USERS_FILE.chmod(0o600)
    except Exception as e:
        print(f"⚠️  Nie ustawiono chmod 600: {e}")

def cmd_list(args):
    users = load()
    if not users:
        print("(brak userów)")
        return
    print(f"{'USERNAME':<20} {'ROLA':<10} {'HASH (skrócony)':<30}")
    print("-" * 60)
    for u, d in sorted(users.items()):
        short_hash = d.get("hash", "")[:25] + "..." if d.get("hash") else "(brak)"
        print(f"{u:<20} {d.get('role', '?'):<10} {short_hash}")

def cmd_add(args):
    users = load(allow_missing=True)
    if args.username in users:
        print(f"❌ User '{args.username}' już istnieje. Użyj 'passwd' lub 'delete' najpierw.")
        sys.exit(1)
    if args.role not in ("admin", "manager", "viewer", "worker", "worker_basic"):
        print(f"❌ Rola: admin | manager | viewer | worker | worker_basic (podałeś: {args.role})")
        sys.exit(1)
    users[args.username] = {"hash": hash_password(args.password), "role": args.role}
    save(users)
    print(f"✅ Dodano: {args.username} (rola: {args.role})")

def cmd_passwd(args):
    users = load()
    if args.username not in users:
        print(f"❌ User '{args.username}' nie istnieje. Użyj 'add'.")
        sys.exit(1)
    users[args.username]["hash"] = hash_password(args.password)
    save(users)
    print(f"✅ Zmieniono hasło: {args.username}")

def cmd_role(args):
    users = load()
    if args.username not in users:
        print(f"❌ User '{args.username}' nie istnieje.")
        sys.exit(1)
    if args.role not in ("admin", "manager", "viewer", "worker", "worker_basic"):
        print(f"❌ Rola: admin | manager | viewer | worker | worker_basic")
        sys.exit(1)
    users[args.username]["role"] = args.role
    save(users)
    print(f"✅ Zmieniono rolę {args.username} → {args.role}")

def cmd_delete(args):
    users = load()
    if args.username not in users:
        print(f"❌ User '{args.username}' nie istnieje.")
        sys.exit(1)
    if len([u for u, d in users.items() if d.get("role") == "admin"]) == 1 and users[args.username].get("role") == "admin":
        print(f"❌ Nie można usunąć ostatniego admina ({args.username}).")
        sys.exit(1)
    del users[args.username]
    save(users)
    print(f"🗑  Usunięto: {args.username}")

def main():
    parser = argparse.ArgumentParser(description="Zarządzanie userami booking-managera (bcrypt)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Lista userów").set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="Dodaj nowego usera")
    p_add.add_argument("username")
    p_add.add_argument("password")
    p_add.add_argument("--role", default="worker", choices=["admin", "manager", "viewer", "worker", "worker_basic"])
    p_add.set_defaults(func=cmd_add)

    p_pw = sub.add_parser("passwd", help="Zmień hasło istniejącego usera")
    p_pw.add_argument("username")
    p_pw.add_argument("password")
    p_pw.set_defaults(func=cmd_passwd)

    p_role = sub.add_parser("role", help="Zmień rolę usera")
    p_role.add_argument("username")
    p_role.add_argument("role", choices=["admin", "manager", "viewer", "worker", "worker_basic"])
    p_role.set_defaults(func=cmd_role)

    p_del = sub.add_parser("delete", help="Usuń usera")
    p_del.add_argument("username")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
