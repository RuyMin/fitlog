"""Operator commands, run inside the container:

    docker compose exec fitlog python -m app.admin invite --note "민수"
    docker compose exec fitlog python -m app.admin users
    docker compose exec fitlog python -m app.admin disable friend@example.com
    docker compose exec fitlog python -m app.admin delete-user friend@example.com --yes

There is deliberately no command to read another user's records.
"""
import argparse
import sys
from datetime import timedelta

from sqlalchemy import select

from app import config
from app.services import accounts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    invite = commands.add_parser("invite", help="create a one-time invite link")
    invite.add_argument("--note", help="who the link is for (shown only to the operator)")
    invite.add_argument("--days", type=int, default=7, choices=range(1, 31), metavar="1-30")
    invite.add_argument("--by", help="admin email, when there is more than one admin")
    commands.add_parser("users", help="list accounts")
    for name in ("disable", "enable"):
        commands.add_parser(name, help=f"{name} an account (disable also ends its sessions)").add_argument("email")
    remove = commands.add_parser("delete-user", help="delete a member and every record they own")
    remove.add_argument("email")
    remove.add_argument("--yes", action="store_true", help="confirm permanent deletion")
    speed = commands.add_parser("perf", help="request speed statistics (phone wait vs server time)")
    speed.add_argument("--days", type=int, default=1, choices=range(1, 15), metavar="1-14")
    args = parser.parse_args(argv)

    from app.database import SessionLocal, initialize_database
    from app.models import User
    initialize_database()
    with SessionLocal() as session:
        try:
            if args.command == "invite":
                admins = session.scalars(select(User).where(User.role == "admin", User.status == "active")).all()
                admin = accounts.find_user(session, args.by) if args.by else (admins[0] if len(admins) == 1 else None)
                if admin is None or admin.role != "admin":
                    print("Use --by with an active admin's email.", file=sys.stderr)
                    return 2
                token = accounts.create_invite(session, admin.id, args.note, timedelta(days=args.days))
                print(f"{config.PUBLIC_ORIGIN or ''}/invite/{token}")
                print(f"Single use, expires in {args.days} days. Send it privately; anyone holding it can join.", file=sys.stderr)
            elif args.command == "users":
                for user in session.scalars(select(User).order_by(User.id)):
                    linked = "linked" if user.google_sub else "unlinked"
                    print(f"{user.id}\t{user.email}\t{user.role}\t{user.status}\t{linked}\t{user.last_login_at or '-'}")
            elif args.command in ("disable", "enable"):
                user = accounts.find_user(session, args.email)
                if args.command == "disable" and user.role == "admin":
                    print("Admins cannot be disabled here.", file=sys.stderr)
                    return 2
                accounts.set_status(session, user.id, "disabled" if args.command == "disable" else "active")
                print(f"{user.email}: {args.command}d")
            elif args.command == "perf":
                from app.services import perf
                data = perf.summary(session, args.days)
                fmt = lambda s: f"{s['p50']}/{s['p90']}ms x{s['count']}" if s.get("count") else "-"
                print(f"since {data['since']}  phone {fmt(data['overall']['client'])}  server {fmt(data['overall']['server'])}  (median/p90)")
                print("pages:")
                for p in data["pages"]:
                    print(f"  {p['page']:<14} data {fmt(p['data']):<24} html {fmt(p['html']):<24} cached {p['cached_share']:.0%}")
                print("requests:")
                for r in data["routes"]:
                    net = "-" if r["network_p50"] is None else f"{r['network_p50']}ms"
                    print(f"  {r['method']:<6} {r['route']:<58} phone {fmt(r['client']):<22} server {fmt(r['server']):<20} network {net} errors {r['errors']}")
            else:
                if not args.yes:
                    print("Permanent. Re-run with --yes. Earlier backup files still contain this user's data.", file=sys.stderr)
                    return 2
                user = accounts.find_user(session, args.email)
                counts = accounts.delete_user(session, user.id)
                print(f"Deleted {args.email}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        except accounts.AccountError as error:
            print(f"Error: {error.code}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
