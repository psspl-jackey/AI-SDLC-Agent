"""{{project_name}}: backend API (starter written by the AI SDLC Agent; tickets add features here)."""
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from .auth import admin_user, check_password, current_user, hash_password, make_token
from .db import Base, SessionLocal, engine, get_db
from .models import Category, Favourite, Item, User
from .seed import load_seed, seed


def _schema_changed() -> bool:
    """True when the demo database was made by an older version of the models."""
    found = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if found.has_table(table.name):
            have = {c["name"] for c in found.get_columns(table.name)}
            if not {c.name for c in table.columns} <= have:
                return True
    return False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if _schema_changed():  # demo data only; real environments use Alembic migrations
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="{{project_name}} API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(LoginIn):
    name: str
    city: str = ""


class ItemIn(BaseModel):
    title: str
    description: str = ""
    price: float = 0
    city: str = ""
    category_id: int
    image_url: str = ""


class ModerateIn(BaseModel):
    status: Optional[str] = None  # pending | active | removed
    featured: Optional[bool] = None


class StatusIn(BaseModel):
    status: str  # active | sold


class PaymentIn(BaseModel):
    amount: float
    purpose: str = ""
    simulate_failure: bool = False


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "city": u.city, "active": u.active,
            "member_since": u.member_since}


def masked(phone: str) -> str:
    digits = phone.replace(" ", "")
    return f"{digits[:3]} {'x' * 5} {digits[-2:]}" if len(digits) >= 6 else ""


def item_out(i: Item, db: Session) -> dict:
    cat = db.get(Category, i.category_id)
    seller = db.get(User, i.seller_id)
    return {"id": i.id, "title": i.title, "description": i.description, "price": i.price, "city": i.city,
            "image_url": i.image_url, "category_id": i.category_id, "category": cat.name if cat else "",
            "seller": {"id": seller.id, "name": seller.name, "member_since": seller.member_since,
                       "phone_masked": masked(seller.phone), "verified": bool(seller.phone)} if seller else None,
            "status": i.status,
            "featured": i.featured, "created_at": i.created_at.isoformat() if i.created_at else None}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def config():
    return load_seed()["config"]


@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if user is None or not check_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    if not user.active:
        raise HTTPException(403, "This account is blocked")
    return {"token": make_token(user.id), "user": user_out(user)}


@app.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already registered")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password), city=body.city)
    db.add(user)
    db.commit()
    return {"token": make_token(user.id), "user": user_out(user)}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@app.get("/categories")
def categories(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name} for c in db.query(Category).order_by(Category.name)]


@app.get("/items")
def items(q: str = "", category_id: Optional[int] = None, city: str = "", sort: str = "newest",
          db: Session = Depends(get_db)):
    query = db.query(Item).filter(Item.status == "active")
    if q:
        query = query.filter(or_(Item.title.ilike(f"%{q}%"), Item.description.ilike(f"%{q}%")))
    if category_id:
        query = query.filter(Item.category_id == category_id)
    if city:
        query = query.filter(Item.city == city)
    order = {"price_asc": [Item.price.asc()], "price_desc": [Item.price.desc()]}.get(
        sort, [Item.featured.desc(), Item.created_at.desc()])
    return [item_out(i, db) for i in query.order_by(*order)]


@app.get("/items/{item_id}")
def item(item_id: int, db: Session = Depends(get_db)):
    i = db.get(Item, item_id)
    if i is None or i.status == "removed":
        raise HTTPException(404, "Not found")
    return item_out(i, db)


@app.post("/items", status_code=201)
def create_item(body: ItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.get(Category, body.category_id) is None:
        raise HTTPException(422, "Unknown category")
    i = Item(**body.model_dump(), seller_id=user.id, status="pending")
    db.add(i)
    db.commit()
    return item_out(i, db)


@app.get("/items/{item_id}/contact")
def contact(item_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """The seller's phone number, only for logged-in users (dummy numbers in the demo data)."""
    i = db.get(Item, item_id)
    if i is None or i.status != "active":
        raise HTTPException(404, "Not found")
    seller = db.get(User, i.seller_id)
    return {"name": seller.name, "phone": seller.phone}


@app.patch("/my/items/{item_id}")
def set_my_item_status(item_id: int, body: StatusIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = db.get(Item, item_id)
    if i is None or i.seller_id != user.id:
        raise HTTPException(404, "Not found")
    if body.status not in ("active", "sold") or i.status in ("pending", "removed"):
        raise HTTPException(422, "Only live items can be marked as sold (and sold ones made live again)")
    i.status = body.status
    db.commit()
    return item_out(i, db)


@app.get("/my/items")
def my_items(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [item_out(i, db) for i in db.query(Item).filter(Item.seller_id == user.id).order_by(Item.created_at.desc())]


@app.get("/favourites")
def favourites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = [f.item_id for f in db.query(Favourite).filter(Favourite.user_id == user.id)]
    return [item_out(i, db) for i in db.query(Item).filter(Item.id.in_(ids), Item.status == "active")]


@app.post("/favourites/{item_id}")
def add_favourite(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.get(Item, item_id) is None:
        raise HTTPException(404, "Not found")
    if db.get(Favourite, (user.id, item_id)) is None:
        db.add(Favourite(user_id=user.id, item_id=item_id))
        db.commit()
    return {"ok": True}


@app.delete("/favourites/{item_id}")
def remove_favourite(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    fav = db.get(Favourite, (user.id, item_id))
    if fav is not None:
        db.delete(fav)
        db.commit()
    return {"ok": True}


@app.post("/payments/dummy")
def dummy_payment(body: PaymentIn, user: User = Depends(current_user)):
    """Dummy payment gateway: static responses so the flow can be demoed. No real payment provider."""
    if body.simulate_failure or body.amount <= 0:
        return {"status": "failed", "reference": None, "message": "Payment declined (dummy gateway)"}
    return {"status": "success", "reference": f"DUMMY-{uuid.uuid4().hex[:10].upper()}",
            "amount": body.amount, "purpose": body.purpose, "message": "Payment successful (dummy gateway)"}


# ---------- admin ----------


@app.get("/admin/stats")
def stats(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    count = lambda s: db.query(Item).filter(Item.status == s).count()  # noqa: E731
    return {"users": db.query(User).count(), "items_active": count("active"), "items_pending": count("pending"),
            "items_sold": count("sold"), "items_removed": count("removed"), "categories": db.query(Category).count()}


@app.get("/admin/items")
def admin_items(status: str = "", _: User = Depends(admin_user), db: Session = Depends(get_db)):
    query = db.query(Item)
    if status:
        query = query.filter(Item.status == status)
    return [item_out(i, db) for i in query.order_by(Item.created_at.desc())]


@app.patch("/admin/items/{item_id}")
def moderate(item_id: int, body: ModerateIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    i = db.get(Item, item_id)
    if i is None:
        raise HTTPException(404, "Not found")
    if body.status is not None:
        if body.status not in ("pending", "active", "sold", "removed"):
            raise HTTPException(422, "Unknown status")
        i.status = body.status
    if body.featured is not None:
        i.featured = body.featured
    db.commit()
    return item_out(i, db)


@app.get("/admin/users")
def admin_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.query(User).order_by(User.id)]


@app.patch("/admin/users/{user_id}")
def block_user(user_id: int, active: bool, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Not found")
    if u.id == admin.id:
        raise HTTPException(422, "You cannot block yourself")
    u.active = active
    db.commit()
    return user_out(u)


@app.post("/admin/categories", status_code=201)
def add_category(name: str, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if db.query(Category).filter(Category.name == name).first():
        raise HTTPException(409, "Category exists")
    c = Category(name=name)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name}
