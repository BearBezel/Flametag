import os
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from io import BytesIO

import qrcode
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, session, make_response, current_app, send_file
)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .models import Lighter, LighterItem, FoundMessage

bp = Blueprint("main", __name__)


# ---------------- Email helpers ----------------
def _email_enabled() -> bool:
    return bool(
        os.getenv("SMTP_HOST")
        and os.getenv("SMTP_USER")
        and os.getenv("SMTP_PASS")
        and os.getenv("SMTP_FROM")
    )


def send_email(to_email: str, subject: str, body: str) -> bool:
    """
    Uses SMTP settings from env vars:
    SMTP_HOST, SMTP_PORT (optional), SMTP_USER, SMTP_PASS, SMTP_FROM
    """
    if not _email_enabled():
        return False

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASS")
    from_email = os.getenv("SMTP_FROM")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    try:
        server = smtplib.SMTP(host, port, timeout=15)
        server.starttls()
        server.login(user, pwd)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        return True
    except Exception:
        return False


def make_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="flametag-pin-reset",
    )


# ---------------- Tag generator ----------------
@bp.post("/generate")
def generate_tag():
    """
    Public: create ONE tag per browser session.
    If they've already generated one, send them back to it.
    """
    existing = session.get("generated_token")
    if existing and Lighter.query.filter_by(token=existing).first():
        return redirect(url_for("main.lighter_page", token=existing))

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(20):
        token = "".join(secrets.choice(alphabet) for _ in range(8))
        if not Lighter.query.filter_by(token=token).first():
            lighter = Lighter(token=token)
            db.session.add(lighter)
            db.session.commit()
            session["generated_token"] = token
            flash("Tag generated. Set your PIN to claim it.", "ok")
            return redirect(url_for("main.lighter_page", token=token))

    flash("Could not generate a tag right now. Please try again.", "err")
    return redirect(url_for("main.home"))


# ---------------- Language ----------------
@bp.get("/set-lang/<lang>")
def set_lang(lang):
    supported = {
        "en", "es", "fr", "de", "it", "pt", "nl",
        "ar", "hi", "ur", "ja", "ko", "sw", "yo", "ig", "zh",
    }
    if lang not in supported:
        lang = "en"

    resp = make_response(redirect(request.referrer or url_for("main.home")))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


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


@bp.get("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@bp.get("/l/<token>")
def lighter_page(token):
    lighter = get_or_404(token)
    return render_template("choice.html", lighter=lighter)
@bp.get("/l/<token>/finder")
def finder_page(token):
    lighter = get_or_404(token)

    lighter.scan_count += 1
    lighter.updated_at = datetime.utcnow()
    db.session.commit()

    unread_count = 0
    if lighter.is_claimed():
        ensure_default_items(lighter)
        unread_count = FoundMessage.query.filter_by(
            lighter_id=lighter.id,
            is_read=False
        ).count()

    return render_template(
        "finder.html",
        lighter=lighter,
        unread_count=unread_count
    )


@bp.get("/l/<token>/owner")
def owner_page(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        return redirect(url_for("main.finder_page", token=token))

    return render_template("owner_pin.html", lighter=lighter)


@bp.post("/l/<token>/owner")
def owner_unlock(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        return redirect(url_for("main.finder_page", token=token))

    pin = (request.form.get("pin") or "").strip()
    if not pin or not lighter.owner_pin_hash or not check_password_hash(lighter.owner_pin_hash, pin):
        flash("Wrong owner PIN.", "err")
        return redirect(url_for("main.owner_page", token=token))

    session[f"owner_ok_{token}"] = True
    flash("Owner dashboard unlocked.", "ok")
    return redirect(url_for("main.owner_dashboard", token=token))


@bp.get("/l/<token>/owner/dashboard")
def owner_dashboard(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        return redirect(url_for("main.finder_page", token=token))

    if not (session.get(f"edit_ok_{token}") or session.get(f"owner_ok_{token}")):
        flash("Owner PIN required.", "err")
        return redirect(url_for("main.owner_page", token=token))

    ensure_default_items(lighter)

    unread_count = FoundMessage.query.filter_by(
        lighter_id=lighter.id,
        is_read=False
    ).count()

    return render_template(
        "owner.html",
        lighter=lighter,
        unread_count=unread_count
    )

# ---------------- Claim / Edit ----------------
@bp.post("/l/<token>/claim")
def claim_lighter(token):
    lighter = get_or_404(token)

    if lighter.is_claimed():
        flash("This tag is already claimed.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    public_message = (request.form.get("public_message") or "").strip()
    private_message = (request.form.get("private_message") or "").strip()
    owner_phone = (request.form.get("owner_phone") or "").strip()
    pin = (request.form.get("pin") or "").strip()
    owner_email = (request.form.get("owner_email") or "").strip().lower()

    if len(pin) < 4:
        flash("Pick a PIN with at least 4 digits/characters.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    lighter.public_message = public_message or "🔥 This is owned. Please return it."
    lighter.private_message = private_message or "Thanks for finding this."
    lighter.owner_phone = owner_phone or None
    lighter.show_owner_phone = False
    lighter.owner_pin_hash = generate_password_hash(pin)
    lighter.claimed_at = datetime.utcnow()
    lighter.updated_at = datetime.utcnow()

    if owner_email:
        lighter.owner_email = owner_email

    db.session.commit()
    ensure_default_items(lighter)

    flash("Claimed! You can now download your QR in Edit.", "ok")
    return redirect(url_for("main.lighter_page", token=token))


@bp.post("/l/<token>/edit")
def edit_lighter(token):
    lighter = get_or_404(token)

    if not lighter.is_claimed():
        flash("Claim it first.", "err")
        return redirect(url_for("main.lighter_page", token=token))

    if not session.get(f"edit_ok_{token}"):
        flash("Owner PIN required to edit.", "err")
        return redirect(url_for("main.lighter_page", token=token) + "#tab-edit")

    public_message = (request.form.get("public_message") or "").strip()
    private_message = (request.form.get("private_message") or "").strip()
    owner_email = (request.form.get("owner_email") or "").strip().lower()
    owner_phone = (request.form.get("owner_phone") or "").strip()
    show_owner_phone = request.form.get("show_owner_phone") == "on"

    if public_message:
        lighter.public_message = public_message
    if private_message:
        lighter.private_message = private_message
    if owner_email:
        lighter.owner_email = owner_email

    lighter.owner_phone = owner_phone or None
    lighter.show_owner_phone = show_owner_phone

    items_text = (request.form.get("items") or "").strip()
    if items_text:
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


@bp.post("/l/<token>/delete")
def delete_lighter(token):
    lighter = get_or_404(token)

    # Owner session OR admin can delete
    if not (session.get(f"owner_ok_{token}") or session.get(f"edit_ok_{token}") or admin_authed()):
        flash("Owner PIN required to delete this tag.", "err")
        return redirect(url_for("main.owner_page", token=token))

    # delete related records first
    FoundMessage.query.filter_by(lighter_id=lighter.id).delete()
    LighterItem.query.filter_by(lighter_id=lighter.id).delete()

    db.session.delete(lighter)
    db.session.commit()

    # clear sessions
    session.pop(f"owner_ok_{token}", None)
    session.pop(f"edit_ok_{token}", None)

    # clear generated token if it matches
    if session.get("generated_token") == token:
        session.pop("generated_token", None)

    flash("Tag deleted successfully.", "ok")
    return redirect(url_for("main.home"))


# ---------------- Finder -> leave a message (EMAIL ALERT) ----------------
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

    lighter.found_at = datetime.utcnow()
    lighter.found_note = note
    lighter.updated_at = datetime.utcnow()
    db.session.commit()

    if lighter.has_owner_email() and _email_enabled():
        subject = f"FlameTag: Someone found your item ({lighter.token})"
        body = (
            f"Someone left a note for your FlameTag {lighter.token}.\n\n"
            f"Item: {item_label}\n"
            f"Note:\n{note}\n\n"
            f"Open your tag:\nhttps://flametag.app/l/{lighter.token}\n\n"
            f"To read all messages, unlock with your PIN."
        )
        send_email(lighter.owner_email, subject, body)

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

    found_messages = (
        FoundMessage.query
        .filter_by(lighter_id=lighter.id)
        .order_by(FoundMessage.created_at.desc())
        .all()
    )

    FoundMessage.query.filter_by(
        lighter_id=lighter.id,
        is_read=False,
    ).update({"is_read": True})
    db.session.commit()

    flash("Unlocked.", "ok")
    return render_template("unlocked.html", lighter=lighter, found_messages=found_messages)


# ---------------- PIN reset (EMAIL LINK) ----------------
@bp.get("/l/<token>/reset-pin")
def reset_pin_request(token):
    lighter = get_or_404(token)
    return render_template("reset_pin_request.html", lighter=lighter)


@bp.post("/l/<token>/reset-pin")
def reset_pin_send(token):
    lighter = get_or_404(token)
    email = (request.form.get("email") or "").strip().lower()

    if not email:
        flash("Enter the email you saved for this tag.", "err")
        return redirect(url_for("main.reset_pin_request", token=token))

    if not lighter.owner_email or lighter.owner_email.strip().lower() != email:
        flash("That email doesn't match this tag.", "err")
        return redirect(url_for("main.reset_pin_request", token=token))

    if not _email_enabled():
        flash("Email reset is not configured yet (SMTP).", "err")
        return redirect(url_for("main.reset_pin_request", token=token))

    s = make_serializer()
    signed = s.dumps({"token": token, "email": email})

    link = url_for("main.reset_pin_form", signed=signed, _external=True)

    subject = f"FlameTag: Reset PIN ({token})"
    body = (
        f"Use this link to reset your FlameTag PIN:\n\n{link}\n\n"
        f"This link expires in 30 minutes.\n"
        f"If you didn't request this, you can ignore this email."
    )

    ok = send_email(email, subject, body)
    if ok:
        flash("Reset link sent to your email.", "ok")
    else:
        flash("Could not send email. Try again.", "err")

    return redirect(url_for("main.lighter_page", token=token))


@bp.get("/reset-pin/<signed>")
def reset_pin_form(signed):
    s = make_serializer()
    try:
        data = s.loads(signed, max_age=60 * 30)
    except SignatureExpired:
        flash("Reset link expired. Request another.", "err")
        return redirect(url_for("main.home"))
    except BadSignature:
        flash("Invalid reset link.", "err")
        return redirect(url_for("main.home"))

    token = data.get("token")
    lighter = get_or_404(token)
    return render_template("reset_pin_form.html", lighter=lighter, signed=signed)


@bp.post("/reset-pin/<signed>")
def reset_pin_save(signed):
    s = make_serializer()
    try:
        data = s.loads(signed, max_age=60 * 30)
    except SignatureExpired:
        flash("Reset link expired. Request another.", "err")
        return redirect(url_for("main.home"))
    except BadSignature:
        flash("Invalid reset link.", "err")
        return redirect(url_for("main.home"))

    token = data.get("token")
    email = data.get("email")
    lighter = get_or_404(token)

    if not lighter.owner_email or lighter.owner_email.strip().lower() != (email or "").lower():
        flash("Email mismatch.", "err")
        return redirect(url_for("main.home"))

    new_pin = (request.form.get("pin") or "").strip()
    if len(new_pin) < 4:
        flash("PIN must be at least 4 characters.", "err")
        return redirect(url_for("main.reset_pin_form", signed=signed))

    lighter.owner_pin_hash = generate_password_hash(new_pin)
    lighter.updated_at = datetime.utcnow()
    db.session.commit()

    session.pop(f"edit_ok_{token}", None)

    flash("PIN reset successfully. Use your new PIN to unlock.", "ok")
    return redirect(url_for("main.lighter_page", token=token))


# ---------------- TEMP DB FIX ----------------
@bp.get("/admin/db-fix-owner-email")
def admin_db_fix_owner_email():
    require_admin()

    db.session.execute(text("""
        ALTER TABLE lighters
        ADD COLUMN IF NOT EXISTS owner_email VARCHAR(120);
    """))
    db.session.commit()

    flash("DB fixed: owner_email column added.", "ok")
    return redirect(url_for("main.admin"))


@bp.get("/admin/db-fix-owner-phone")
def admin_db_fix_owner_phone():
    require_admin()

    db.session.execute(text("""
        ALTER TABLE lighters
        ADD COLUMN IF NOT EXISTS owner_phone VARCHAR(40);
    """))
    db.session.execute(text("""
        ALTER TABLE lighters
        ADD COLUMN IF NOT EXISTS show_owner_phone BOOLEAN NOT NULL DEFAULT FALSE;
    """))
    db.session.commit()

    flash("DB fixed: owner_phone and show_owner_phone columns added.", "ok")
    return redirect(url_for("main.admin"))


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
        lighter = Lighter(token=token)
        db.session.add(lighter)
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


@bp.post("/admin/delete/<token>")
def admin_delete_tag(token):
    require_admin()

    lighter = get_or_404(token)

    FoundMessage.query.filter_by(lighter_id=lighter.id).delete()
    LighterItem.query.filter_by(lighter_id=lighter.id).delete()

    db.session.delete(lighter)
    db.session.commit()

    flash(f"Tag {token} deleted.", "ok")
    return redirect(url_for("main.admin"))


# ---------------- QR ----------------
@bp.get("/qr/<token>")
def qr_code(token):
    Lighter.query.filter_by(token=token).first_or_404()
    url = f"https://flametag.app/l/{token}"

    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="white", back_color="black")

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(buf, mimetype="image/png")
 
