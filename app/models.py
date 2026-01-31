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

    # You can keep these if you want, but once we switch to FoundNote history
    # they won’t be needed anymore. (We can remove later safely.)
    found_at = db.Column(db.DateTime, nullable=True)
    found_note = db.Column(db.Text, nullable=True)

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    def is_claimed(self) -> bool:
        return self.claimed_at is not None


class FoundNote(db.Model):
    __tablename__ = "found_notes"

    id = db.Column(db.Integer, primary_key=True)

    lighter_id = db.Column(
        db.Integer,
        db.ForeignKey("lighters.id"),
        nullable=False
    )

    message = db.Column(db.Text, nullable=False)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    # Allows: lighter.found_notes (list of notes)
    lighter = db.relationship("Lighter", backref="found_notes")
