"""Loads the dummy data in seed.json into an empty database."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Category, Item, User

SEED_FILE = Path(__file__).resolve().parent.parent / "seed.json"


def load_seed() -> dict:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def seed(db: Session) -> None:
    if db.query(User).first():
        return
    data = load_seed()
    users = {}
    for u in data["users"]:
        user = User(name=u["name"], email=u["email"], password_hash=hash_password(u["password"]),
                    role=u.get("role", "user"), city=u.get("city", ""), phone=u.get("phone", ""),
                    member_since=u.get("member_since", datetime.now(timezone.utc).year))
        db.add(user)
        users[u["email"]] = user
    cats = {}
    for name in data["categories"]:
        cats[name] = Category(name=name)
        db.add(cats[name])
    db.flush()
    for it in data["items"]:
        db.add(Item(title=it["title"], description=it.get("description", ""), price=it.get("price", 0),
                    city=it.get("city", ""), image_url=it.get("image_url", ""),
                    category_id=cats[it["category"]].id, seller_id=users[it["seller"]].id,
                    status=it.get("status", "active"), featured=it.get("featured", False),
                    created_at=datetime.now(timezone.utc) - timedelta(hours=it.get("hours_ago", 0))))
    db.commit()
