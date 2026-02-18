from datetime import datetime
from . import db


class Lighter(db.Model):
    __tablename__ = "lighters"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(32), unique=True, index=True, nullable=False)

    claimed_at = db.Column(db.DateTime, nullable=True)
    owner_pin_hash = db.Column(db.String(255), nullable=True)

    public_message = db.Column(db.Text, nullable=True)
    private_message = db.Column(db.Text, nullable=True)

    scan_count = db.Column(db.Integer, nullable=False, default=0)

    # (keep these if you want, but we won't rely on them anymore)
    found_at = db.Column(db.DateTime, nullable=True)
    found_note = db.Column(db.Text, nullable=True)

    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # NEW: items on this tag (keys/bag/etc)
    items = db.relationship(
        "LighterItem",
        backref="lighter",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="LighterItem.created_at.asc()",
    )

    def is_claimed(self) -> bool:
        return self.claimed_at is not None


class LighterItem(db.Model):
    __tablename__ = "lighter_items"

    id = db.Column(db.Integer, primary_key=True)

    lighter_id = db.Column(
        db.Integer,
        db.ForeignKey("lighters.id"),
        nullable=False,
        index=True,
    )

    label = db.Column(db.String(64), nullable=False)  # e.g. "Keys", "Bag"
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class FoundMessage(db.Model):
    """
    NEW table (so we don't need to alter the old found_notes table).
    All finder messages live here.
    """
    __tablename__ = "found_messages"

    id = db.Column(db.Integer, primary_key=True)

    lighter_id = db.Column(
        db.Integer,
        db.ForeignKey("lighters.id"),
        nullable=False,
        index=True,
    )

    item_label = db.Column(db.String(64), nullable=False, default="General")
    note = db.Column(db.Text, nullable=False)

    finder_name = db.Column(db.String(80), nullable=True)   # optional
    finder_contact = db.Column(db.String(120), nullable=True)  # optional

    is_read = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
