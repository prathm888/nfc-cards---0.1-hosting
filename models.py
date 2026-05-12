from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))

    # --- SRS: Employee Digital ID fields ---
    emp_id = db.Column(db.String(20), unique=True, nullable=True)  # e.g. SA-001
    name = db.Column(db.String(200))  # Full legal name
    business_name = db.Column(db.String(200))
    bio = db.Column(db.Text)
    phone = db.Column(db.String(30))
    address = db.Column(db.Text)  # Residential or branch address
    website = db.Column(db.String(200))
    linkedin = db.Column(db.String(200))
    twitter = db.Column(db.String(200))
    instagram = db.Column(db.String(200))
    logo_filename = db.Column(db.String(200))  # photo_url equivalent
    designation = db.Column(db.String(100), default='Publicity Officer')  # SRS: Digital ID designation

    @property
    def photo_url(self):
        """Alias for logo_filename for template compatibility."""
        return self.logo_filename

    # --- SRS: Gamification ---
    total_points = db.Column(db.Integer, default=0)

    card_theme = db.Column(db.String(50), default='nexus')
    subscription = db.Column(db.String(20), default='free')
    is_admin = db.Column(db.Boolean, default=False)
    is_suspended = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cards = db.relationship('NFCCard', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def total_taps(self):
        return sum(c.tap_count for c in self.cards)

    @property
    def total_leads(self):
        return sum(len(c.leads) for c in self.cards)

    def unique_taps_today(self):
        """Count unique IP taps across all cards for today."""
        today_start = datetime.combine(date.today(), datetime.min.time())
        seen_ips = set()
        count = 0
        for card in self.cards:
            if card.status != 'active':
                continue
            for tap in card.taps:
                if tap.timestamp >= today_start and tap.ip_address not in seen_ips:
                    seen_ips.add(tap.ip_address)
                    count += 1
        return count

    def unique_taps_this_week(self):
        """Count unique IP taps across all cards for the current week (Mon-Sun)."""
        today = date.today()
        week_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
        seen_ips = set()
        count = 0
        for card in self.cards:
            if card.status != 'active':
                continue
            for tap in card.taps:
                if tap.timestamp >= week_start and tap.ip_address not in seen_ips:
                    seen_ips.add(tap.ip_address)
                    count += 1
        return count


class NFCCard(db.Model):
    __tablename__ = 'nfc_cards'

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(50), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    target_url = db.Column(db.String(500))
    label = db.Column(db.String(200))

    # --- SRS: Card status enum (Active / Suspended / Terminated) ---
    # suspended: card is blocked — no analytics, 302→inactive page
    # terminated: card is permanently decommissioned — same behaviour as suspended
    status = db.Column(db.String(20), default='active')  # active, suspended, terminated

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    taps = db.relationship('TapAnalytics', backref='card', lazy=True,
                           cascade='all, delete-orphan')
    leads = db.relationship('Lead', backref='card', lazy=True,
                            cascade='all, delete-orphan')

    @property
    def is_active(self):
        """Backwards compatibility."""
        return self.status == 'active'

    @property
    def tap_count(self):
        return len(self.taps)

    @property
    def recent_tap_count(self):
        cutoff = datetime.utcnow() - timedelta(hours=24)
        return sum(1 for t in self.taps if t.timestamp >= cutoff)


class TapAnalytics(db.Model):
    __tablename__ = 'tap_analytics'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('nfc_cards.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    device_type = db.Column(db.String(20))
    browser = db.Column(db.String(100))
    ip_address = db.Column(db.String(64))
    referrer = db.Column(db.String(500))
    is_unique = db.Column(db.Boolean, default=True)  # SRS: unique tap flag


class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('nfc_cards.id'), nullable=False)
    name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(30))
    message = db.Column(db.Text)
    captured_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- SRS Table 4: Daily_Goals ---
class DailyGoal(db.Model):
    __tablename__ = 'daily_goals'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    target_scans = db.Column(db.Integer, nullable=False, default=10)
    reward_desc = db.Column(db.String(300))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- SRS Table 5: Notifications ---
class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    target_emp_id = db.Column(db.String(20))  # "ALL" or specific emp_id
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
