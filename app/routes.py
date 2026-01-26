import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .models import Lighter

bp = Blueprint("main", __name__)


def get_or_404(token: str) -> Lighter:
    lighter = Lighter.query.filter_by(token=token).first()
    if not lighter:
        abort(404)
    return lighter


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/l/<token>")
def lighter_page(token):
    lighter = get_or_404(token)
    lighter.scan_count += 1
    lighter.updated_at = datetime.utcnow()
    db.session.commit()
    return render_template("lighter.html", lighter=lighter)


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

    lighter.public_message = public_message or "🔥 This lighter is owned. Please return it."
    lighter.private_message = private_message or "Thanks for finding this."
    lighter.owner_pin_hash = generate_password_hash(pin)
    lighter.claimed_at = datetime.utcnow()
    lighter.updated_at = datetime.utcnow()

    db.session.commit()
    flash("Claimed! Your message is now linked to this lighter.", "ok")
    return redirect(url_for("main.lighter_page", token=token))


@bp.post("/l/<token>/unlock")
def unlock_private(token):
    lighter = get_or_404(token)
    if not lighter.is_claimed():
        flash("This lighter hasn't been claimed yet.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    pin = (request.form.get("pin") or "").strip()
    if not pin or not lighter.owner_pin_hash or not check_password_hash(lighter.owner_pin_hash, pin):
        flash("Wrong PIN.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    flash("Unlocked.", "ok")
    return render_template("unlocked.html", lighter=lighter)
    
@bp.post("/l/<token>/found")
def found_lighter(token):
    lighter = get_or_404(token)

    note = (request.form.get("found_note") or "").strip()
    if not note:
        flash("Please add a short note (where you found it).", "err")
        return redirect(url_for("main.lighter_page", token=token))

    lighter.found_at = datetime.utcnow()
    lighter.found_note = note
    lighter.updated_at = datetime.utcnow()

    db.session.commit()
    flash("Thanks — your message has been saved for the owner.", "ok")
    return redirect(url_for("main.lighter_page", token=token))
    
@bp.post("/l/<token>/edit")
def edit_lighter(token):
    lighter = get_or_404(token)
    if not lighter.is_claimed():
        flash("Claim it first.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    pin = (request.form.get("pin") or "").strip()
    if not pin or not lighter.owner_pin_hash or not check_password_hash(lighter.owner_pin_hash, pin):
        flash("Wrong owner PIN.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    public_message = (request.form.get("public_message") or "").strip()
    private_message = (request.form.get("private_message") or "").strip()

    if public_message:
        lighter.public_message = public_message
    if private_message:
        lighter.private_message = private_message

    lighter.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Updated.", "ok")
    return redirect(url_for("main.lighter_page", token=token))

# --- Admin helpers (optional) ---

@bp.get("/admin")
def admin():
    return render_template("admin.html")


@bp.post("/admin/generate")
def admin_generate():
    admin_key = os.getenv("ADMIN_KEY", "")
    key = (request.form.get("admin_key") or "").strip()
    if not admin_key or key != admin_key:
        flash("Invalid admin key.", "err")
        return redirect(url_for("main.admin"))

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
    admin_key = os.getenv("ADMIN_KEY", "")
    key = (request.form.get("admin_key") or "").strip()
    if not admin_key or key != admin_key:
        flash("Invalid admin key.", "err")
        return redirect(url_for("main.admin"))

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

import qrcode
from io import BytesIO
from flask import send_file
from .models import FlameTag

@bp.get("/qr/<token>")
def qr_code(token):
    FlameTag.query.filter_by(token=token).first_or_404()
    url=f"https://flametag.app/1/{token}"
    qr=qrcode.QRCode(
    version=1,
    box_size=10,
    border=2
    )
    qr.add_data(url)
    qr.make(fit=true)
    img=qr.make_image(fill_color="white,back_color="black")
    buf=BytesIO()
    img.save(buf,format="PNG")
    buf.seek(0)
    return send_file(buf,mimetype="image/png")
                      
    
    
