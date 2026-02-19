import os
import secrets
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, session
)
from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .models import Lighter, LighterItem, FoundMessage

bp = Blueprint("main", __name__)


# ---------------- Admin lock helpers ----------------
def admin_authed() -> bool:
    admin_key = os.getenv("ADMIN_KEY", "")
    return bool(admin_key) and session.get("is_admin") is True


def require_admin():
    if not admin_authed():
        abort(404)


# ---------------- Helpers ----------------
def get_or_404(token: str) -> Lighter:
    lighter = Lighter.query.filter_by(token=token).first()
    if not lighter:
        abort(404)
    return lighter


def ensure_default_items(lighter: Lighter):
    """If owner hasn't set items yet, create defaults."""
    if lighter.items and len(lighter.items) > 0:
        return

    defaults = ["Keys", "Wallet", "Bag", "Lighter", "Other"]
    for label in defaults:
        db.session.add(LighterItem(lighter_id=lighter.id, label=label))
    db.session.commit()


# ---------------- Public pages ----------------
@bp.get("/")
def home():
    return render_template("home.html", hide_topbar=True)


@bp.get("/l/<token>")
def lighter_page(token):
    lighter = get_or_404(token)

    lighter.scan_count += 1
    lighter.updated_at = datetime.utcnow()
    db.session.commit()

    if lighter.is_claimed():
        ensure_default_items(lighter)

    return render_template("lighter.html", lighter=lighter)


# ---------------- Claim / Edit ----------------
@bp.post("/l/<token>/claim")
def claim_lighter(token):
    lighter = get_or_404(token)

    if lighter.is_claimed():
        flash("This lighter is already claimed.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    public_message = (request.form.get("public_message") or "").strip()
    private_message = (request.form.get("private_message") or "").strip()
    pin = (request.form.get("pin") or "").strip()

    if len(pin) < 4:
        flash("Pick a PIN with at least 4 digits/characters.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    lighter.public_message = public_message or "🔥 This is owned. Please return it."
    lighter.private_message = private_message or "Thanks for finding this."
    lighter.owner_pin_hash = generate_password_hash(pin)
    lighter.claimed_at = datetime.utcnow()
    lighter.updated_at = datetime.utcnow()

    db.session.commit()
    ensure_default_items(lighter)

    flash("Claimed! Your message is now linked to this tag.", "ok")
    return redirect(url_for("main.lighter_page", token=token))


@bp.post("/l/<token>/edit")
def edit_lighter(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        flash("Claim it first.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    # Must unlock edit first (via /l/<token>/edit/unlock)
    if not session.get(f"edit_ok_{token}"):
        flash("Owner PIN required to edit.", "err")
        return redirect(url_for("main.lighter_page", token=token) + "#tab-edit")    
    public_message = (request.form.get("public_message") or "").strip()
    private_message = (request.form.get("private_message") or "").strip()

    if public_message:
        lighter.public_message = public_message
    if private_message:
        lighter.private_message = private_message

    # NEW: items editor (one per line)
    items_text = (request.form.get("items") or "").strip()
    if items_text:
        # clear + re-add
        LighterItem.query.filter_by(lighter_id=lighter.id).delete()
        lines = [x.strip() for x in items_text.splitlines() if x.strip()]
        for label in lines[:20]:
            db.session.add(LighterItem(lighter_id=lighter.id, label=label))

    lighter.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Updated.", "ok")
    return redirect(url_for("main.lighter_page", token=token))

@bp.post("/l/<token>/edit/unlock")
def edit_unlock(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        flash("This tag hasn't been claimed yet.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    pin = (request.form.get("pin") or "").strip()
    if not pin or not lighter.owner_pin_hash or not check_password_hash(lighter.owner_pin_hash, pin):
        flash("Wrong owner PIN.", "err")
        return redirect(url_for("main.lighter_page", token=token) + "#tab-edit")

    session[f"edit_ok_{token}"] = True
    flash("Edit unlocked.", "ok")
    return redirect(url_for("main.lighter_page", token=token) + "#tab-edit")


# ---------------- Finder -> leave a private message ----------------
@bp.post("/l/<token>/found")
def found_lighter(token):
    lighter = get_or_404(token)

    note = (request.form.get("found_note") or "").strip()

    if not note:
        flash("Please add a short note (where you found it).", "err")
        return redirect(url_for("main.lighter_page", token=token))

    item_id = request.form.get("item_id")

    item_label = "General"

    if item_id:
        item = next((it for it in lighter.items if str(it.id) == item_id), None)
        if item:
            item_label = item.label

    finder_name = (request.form.get("finder_name") or "").strip()
    finder_contact = (request.form.get("finder_contact") or "").strip()

    db.session.add(
        FoundMessage(
            lighter_id=lighter.id,
            item_label=item_label or "General",
            note=note,
            finder_name=finder_name or None,
            finder_contact=finder_contact or None,
            is_read=False,
        )
    )

    # keep these updated (optional)
    lighter.found_at = datetime.utcnow()
    lighter.found_note = note
    lighter.updated_at = datetime.utcnow()

    db.session.commit()

    flash("Thanks — your message has been saved for the owner.", "ok")
    return redirect(url_for("main.lighter_page", token=token))


# ---------------- Owner -> unlock messages page ----------------
@bp.post("/l/<token>/unlock")
def unlock_private(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        flash("This tag hasn't been claimed yet.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    pin = (request.form.get("pin") or "").strip()
    if not pin or not lighter.owner_pin_hash or not check_password_hash(lighter.owner_pin_hash, pin):
        flash("Wrong PIN.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    # Fetch all messages (newest first)
    found_messages = (
        FoundMessage.query
        .filter_by(lighter_id=lighter.id)
        .order_by(FoundMessage.created_at.desc())
        .all()
    )

    # Mark as read when owner opens messages
    FoundMessage.query.filter_by(lighter_id=lighter.id, is_read=False).update({"is_read": True})
    db.session.commit()

    flash("Unlocked.", "ok")
    return render_template("unlocked.html", lighter=lighter, found_messages=found_messages)


# ---------------- Admin pages ----------------
@bp.get("/admin")
def admin():
    if not admin_authed():
        return render_template("admin_login.html")

    lighters = Lighter.query.order_by(Lighter.id.desc()).limit(50).all()
    return render_template("admin.html", lighters=lighters)


@bp.post("/admin/login")
def admin_login():
    admin_key = os.getenv("ADMIN_KEY", "")
    key = (request.form.get("admin_key") or "").strip()

    if not admin_key or key != admin_key:
        flash("Invalid admin key.", "err")
        return redirect(url_for("main.admin"))

    session["is_admin"] = True
    flash("Admin access granted.", "ok")
    return redirect(url_for("main.admin"))


@bp.post("/admin/generate")
def admin_generate():
    require_admin()

    how_many = int(request.form.get("how_many") or 0)
    how_many = max(0, min(how_many, 5000))

    created = []
    for _ in range(how_many):
        token = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        if Lighter.query.filter_by(token=token).first():
            continue
        l = Lighter(token=token)
        db.session.add(l)
        created.append(token)

    db.session.commit()
    flash(f"Created {len(created)} tokens.", "ok")
    return render_template("admin_created.html", created=created)


@bp.post("/admin/import")
def admin_import():
    require_admin()

    raw = (request.form.get("tokens") or "").strip()
    tokens = [t.strip().upper() for t in raw.replace(",", "\n").splitlines() if t.strip()]

    created = 0
    for token in tokens:
        if len(token) < 4 or len(token) > 32:
            continue
        if Lighter.query.filter_by(token=token).first():
            continue
        db.session.add(Lighter(token=token))
        created += 1

    db.session.commit()
    flash(f"Imported {created} tokens.", "ok")
    return redirect(url_for("main.admin"))


# ---------------- QR ----------------
import qrcode
from io import BytesIO
from flask import send_file


@bp.get("/qr/<token>")
def qr_code(token):
    lighter = Lighter.query.filter_by(token=token).first_or_404()

    url = f"https://flametag.app/l/{token}"

    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="white", back_color="black")

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(buf, mimetype="image/png")
