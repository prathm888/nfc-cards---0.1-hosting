import io
import os
import hashlib
import string
import random
from datetime import datetime, date, timedelta
from functools import wraps

import qrcode
import pandas as pd
from flask import (Flask, render_template, redirect, url_for, request,
                   flash, jsonify, send_file, abort, make_response)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from user_agents import parse as ua_parse
from werkzeug.utils import secure_filename

from config import Config
from models import db, User, NFCCard, TapAnalytics, Lead, DailyGoal, Notification

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_slug(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth_login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'error'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    with app.app_context():
        try:
            db.create_all()
            if not User.query.filter_by(is_admin=True).first():
                admin = User(username='admin', email='admin@nfcplatform.com',
                             business_name='NFC Platform', subscription='enterprise', is_admin=True)
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()
        except Exception as e:
            import logging
            logging.critical(f"Database initialization failed: {e}")
            raise  # Fail fast so Render knows the deployment failed if the DB is unreachable


    # ── Index ─────────────────────────────────────────────────────────────────
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('admin_index') if current_user.is_admin else url_for('dashboard_index'))
        return redirect(url_for('auth_login'))

    # ── Auth ──────────────────────────────────────────────────────────────────
    @app.route('/auth/login', methods=['GET', 'POST'])
    def auth_login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                if user.is_suspended:
                    flash('Your account has been suspended. Contact support.', 'error')
                    return redirect(url_for('auth_login'))
                login_user(user, remember=bool(request.form.get('remember')))
                return redirect(url_for('admin_index') if user.is_admin else url_for('dashboard_index'))
            flash('Invalid username or password.', 'error')
        return render_template('auth/login.html')

    @app.route('/auth/register', methods=['GET', 'POST'])
    def auth_register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            business_name = request.form.get('business_name', '').strip()
            if User.query.filter_by(username=username).first():
                flash('Username already taken.', 'error')
                return redirect(url_for('auth_register'))
            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'error')
                return redirect(url_for('auth_register'))
            if len(password) < 8:
                flash('Password must be at least 8 characters.', 'error')
                return redirect(url_for('auth_register'))
            user = User(username=username, email=email, business_name=business_name)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Welcome! Your account has been created.', 'success')
            return redirect(url_for('dashboard_index'))
        return render_template('auth/register.html')

    @app.route('/auth/logout')
    @login_required
    def auth_logout():
        logout_user()
        return redirect(url_for('auth_login'))

    # ── Tracking Route (SRS §3.2: status enforcement + unique tap dedup) ─────
    @app.route('/t/<slug>')
    def track_redirect(slug):
        """NFC tap redirection middleware.

        Enforcement order (strict):
        1. Slug not found            → 404
        2. status == suspended       → 302 to samartha.in/inactive  (NO analytics)
        3. status == terminated      → 302 to samartha.in/inactive  (NO analytics)
        4. status == active          → log tap, award points, 302 to target_url
        """
        card = NFCCard.query.filter_by(unique_id=slug).first()

        # Step 1: card must exist
        if not card:
            abort(404)

        # Step 2 & 3: blocked statuses — silent redirect, zero analytics written
        if card.status in ('suspended', 'terminated'):
            return redirect('https://samartha.in/inactive', code=302)

        # Step 4: active card — parse UA and compute IP fingerprint
        ua_string = request.headers.get('User-Agent', '')
        ua = ua_parse(ua_string)
        if ua.is_mobile:
            device_type = 'mobile'
        elif ua.is_tablet:
            device_type = 'tablet'
        else:
            device_type = 'desktop'

        # Use X-Forwarded-For header for real client IP (proxy / load-balancer aware)
        forwarded_for = request.headers.get('X-Forwarded-For', '')
        raw_ip = forwarded_for.split(',')[0].strip() if forwarded_for else (request.remote_addr or '')
        ip_hash = hashlib.sha256(raw_ip.encode()).hexdigest()[:16]

        # SRS: unique-tap deduplication — one unique tap per IP per card per day
        today_start = datetime.combine(date.today(), datetime.min.time())
        existing_tap = TapAnalytics.query.filter(
            TapAnalytics.card_id == card.id,
            TapAnalytics.ip_address == ip_hash,
            TapAnalytics.timestamp >= today_start
        ).first()
        is_unique = (existing_tap is None)

        tap = TapAnalytics(
            card_id=card.id,
            device_type=device_type,
            browser=ua.browser.family,
            ip_address=ip_hash,
            referrer=request.referrer or '',
            is_unique=is_unique
        )
        db.session.add(tap)

        # SRS: Award 1 gamification point to card owner per unique tap
        if is_unique and card.owner:
            card.owner.total_points = (card.owner.total_points or 0) + 1

        db.session.commit()
        target = card.target_url or url_for('public_card', slug=slug, _external=True)
        return redirect(target, code=302)

    # ── Dashboard ─────────────────────────────────────────────────────────────
    @app.route('/dashboard/')
    @login_required
    def dashboard_index():
        cards = NFCCard.query.filter_by(user_id=current_user.id).all()
        total_taps = sum(c.tap_count for c in cards)
        total_leads = sum(len(c.leads) for c in cards)
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent_taps = TapAnalytics.query.join(NFCCard).filter(
            NFCCard.user_id == current_user.id,
            TapAnalytics.timestamp >= cutoff).count()
        return render_template('dashboard/index.html', cards=cards,
                               total_taps=total_taps, total_leads=total_leads,
                               recent_taps=recent_taps)

    @app.route('/dashboard/cards')
    @login_required
    def dashboard_cards():
        cards = NFCCard.query.filter_by(user_id=current_user.id).all()
        return render_template('dashboard/cards.html', cards=cards,
                               base_url=app.config['BASE_URL'])

    @app.route('/dashboard/cards/<int:card_id>/update', methods=['POST'])
    @login_required
    def dashboard_update_card(card_id):
        card = NFCCard.query.filter_by(id=card_id, user_id=current_user.id).first_or_404()
        target_url = request.form.get('target_url', '').strip()
        label = request.form.get('label', '').strip()
        if target_url:
            card.target_url = target_url
        if label:
            card.label = label
        db.session.commit()
        flash('Card updated successfully!', 'success')
        return redirect(url_for('dashboard_cards'))

    @app.route('/dashboard/analytics')
    @login_required
    def dashboard_analytics():
        cards = NFCCard.query.filter_by(user_id=current_user.id).all()
        return render_template('dashboard/analytics.html', cards=cards)

    @app.route('/dashboard/analytics/data')
    @login_required
    def dashboard_analytics_data():
        days = int(request.args.get('days', 30))
        card_id = request.args.get('card_id', 'all')
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = TapAnalytics.query.join(NFCCard).filter(
            NFCCard.user_id == current_user.id,
            TapAnalytics.timestamp >= cutoff)
        if card_id != 'all':
            query = query.filter(TapAnalytics.card_id == int(card_id))
        taps = query.all()
        date_counts = {}
        for t in taps:
            k = t.timestamp.strftime('%Y-%m-%d')
            date_counts[k] = date_counts.get(k, 0) + 1
        labels, values = [], []
        for i in range(days):
            d = (datetime.utcnow() - timedelta(days=days - 1 - i)).strftime('%Y-%m-%d')
            labels.append(d)
            values.append(date_counts.get(d, 0))
        device_counts = {'mobile': 0, 'tablet': 0, 'desktop': 0}
        browser_counts = {}
        for t in taps:
            dt = t.device_type or 'desktop'
            device_counts[dt] = device_counts.get(dt, 0) + 1
            b = t.browser or 'Unknown'
            browser_counts[b] = browser_counts.get(b, 0) + 1
        browser_counts = dict(sorted(browser_counts.items(), key=lambda x: x[1], reverse=True)[:5])
        return jsonify({'labels': labels, 'values': values,
                        'devices': device_counts, 'browsers': browser_counts})

    @app.route('/dashboard/profile', methods=['GET', 'POST'])
    @login_required
    def dashboard_profile():
        if request.method == 'POST':
            current_user.name = request.form.get('name', '').strip()
            current_user.designation = request.form.get('designation', '').strip() or 'Publicity Officer'
            current_user.business_name = request.form.get('business_name', '').strip()
            current_user.bio = request.form.get('bio', '').strip()
            current_user.phone = request.form.get('phone', '').strip()
            current_user.address = request.form.get('address', '').strip()
            current_user.website = request.form.get('website', '').strip()
            current_user.linkedin = request.form.get('linkedin', '').strip()
            current_user.twitter = request.form.get('twitter', '').strip()
            current_user.instagram = request.form.get('instagram', '').strip()
            current_user.card_theme = request.form.get('card_theme', 'nexus')
            if 'logo' in request.files:
                f = request.files['logo']
                if f and f.filename and allowed_file(f.filename):
                    fname = secure_filename(f'logo_{current_user.id}_{f.filename}')
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                    current_user.logo_filename = fname
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('dashboard_profile'))
        return render_template('dashboard/profile.html')

    @app.route('/dashboard/qr/<int:card_id>')
    @login_required
    def dashboard_qr(card_id):
        card = NFCCard.query.filter_by(id=card_id, user_id=current_user.id).first_or_404()
        tracking_url = f"{app.config['BASE_URL']}/t/{card.unique_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(tracking_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='#7C3AED', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png',
                         download_name=f'qr_{card.unique_id}.png')

    # ── SRS: Daily Goals (Employee) ───────────────────────────────────────────
    @app.route('/dashboard/goals')
    @login_required
    def dashboard_goals():
        today = date.today()
        goal = DailyGoal.query.filter_by(date=today).first()
        taps_today = current_user.unique_taps_today()
        progress_pct = 0
        if goal and goal.target_scans > 0:
            progress_pct = min(100, int((taps_today / goal.target_scans) * 100))
        return render_template('dashboard/goals.html',
                               goal=goal, taps_today=taps_today,
                               progress_pct=progress_pct, today=today)

    # ── SRS: Weekly Leaderboard (Employee) ────────────────────────────────────
    @app.route('/dashboard/leaderboard')
    @login_required
    def dashboard_leaderboard():
        employees = User.query.filter_by(is_admin=False, is_suspended=False).all()
        ranked = sorted(employees, key=lambda u: u.unique_taps_this_week(), reverse=True)
        leaderboard = []
        for rank, emp in enumerate(ranked, start=1):
            leaderboard.append({
                'rank': rank,
                'user': emp,
                'weekly_taps': emp.unique_taps_this_week(),
                'total_points': emp.total_points or 0,
                'is_me': emp.id == current_user.id
            })
        return render_template('dashboard/leaderboard.html', leaderboard=leaderboard)

    # ── SRS: Inbox / Notifications (Employee) ─────────────────────────────────
    @app.route('/dashboard/inbox')
    @login_required
    def dashboard_inbox():
        notices = Notification.query.filter(
            (Notification.target_emp_id == 'ALL') |
            (Notification.target_emp_id == current_user.emp_id)
        ).order_by(Notification.timestamp.desc()).all()
        return render_template('dashboard/inbox.html', notices=notices)

    # ── SRS: Digital Employee ID Card ─────────────────────────────────────────
    @app.route('/dashboard/id-card')
    @login_required
    def dashboard_id_card():
        cards = NFCCard.query.filter_by(user_id=current_user.id, status='active').all()
        primary_card = cards[0] if cards else None
        return render_template('dashboard/id_card.html',
                               user=current_user, primary_card=primary_card,
                               base_url=app.config['BASE_URL'])

    # ── Public Card Page ──────────────────────────────────────────────────────
    @app.route('/c/<slug>')
    def public_card(slug):
        card = NFCCard.query.filter_by(unique_id=slug).first_or_404()
        if card.status != 'active':
            abort(404)
        user = card.owner
        return render_template('public/card.html', card=card, user=user)

    @app.route('/c/<slug>/lead', methods=['POST'])
    def public_lead(slug):
        card = NFCCard.query.filter_by(unique_id=slug).first_or_404()
        lead = Lead(
            card_id=card.id,
            name=request.form.get('name', ''),
            email=request.form.get('email', ''),
            phone=request.form.get('phone', ''),
            message=request.form.get('message', ''))
        db.session.add(lead)
        db.session.commit()
        flash('Thanks! Your message has been received.', 'success')
        return redirect(url_for('public_card', slug=slug))

    @app.route('/c/<slug>/vcf')
    def public_vcf(slug):
        card = NFCCard.query.filter_by(unique_id=slug).first_or_404()
        u = card.owner
        vcf = f"""BEGIN:VCARD
VERSION:3.0
FN:{u.name or u.business_name or u.username}
ORG:{u.business_name or ''}
TEL:{u.phone or ''}
EMAIL:{u.email}
URL:{u.website or ''}
ADR:;;{u.address or ''};;;;
NOTE:{u.bio or ''}
END:VCARD"""
        response = make_response(vcf)
        response.headers['Content-Type'] = 'text/vcard'
        response.headers['Content-Disposition'] = f'attachment; filename="{u.username}.vcf"'
        return response

    # ── Admin Panel ───────────────────────────────────────────────────────────
    @app.route('/admin/')
    @login_required
    @admin_required
    def admin_index():
        total_users = User.query.filter_by(is_admin=False).count()
        total_cards = NFCCard.query.count()
        total_taps = TapAnalytics.query.count()
        total_leads = Lead.query.count()
        active_cards = NFCCard.query.filter_by(status='active').count()
        today = datetime.utcnow().date()
        new_users_today = User.query.filter(db.func.date(User.created_at) == today).count()
        return render_template('admin/index.html', total_users=total_users,
                               total_cards=total_cards, total_taps=total_taps,
                               total_leads=total_leads, active_cards=active_cards,
                               new_users_today=new_users_today)

    @app.route('/admin/heatmap')
    @login_required
    @admin_required
    def admin_heatmap():
        cutoff = datetime.utcnow() - timedelta(hours=24)
        hot_cards = db.session.query(
            NFCCard, db.func.count(TapAnalytics.id).label('tap_count')
        ).join(TapAnalytics).filter(
            TapAnalytics.timestamp >= cutoff
        ).group_by(NFCCard.id).order_by(db.desc('tap_count')).limit(20).all()
        return render_template('admin/heatmap.html', hot_cards=hot_cards)

    @app.route('/admin/users')
    @login_required
    @admin_required
    def admin_users():
        users = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).all()
        return render_template('admin/users.html', users=users)

    @app.route('/admin/users/create-card', methods=['POST'])
    @login_required
    @admin_required
    def admin_create_card():
        user_id = request.form.get('user_id')
        label = request.form.get('label', 'New Card').strip()
        custom_slug = request.form.get('custom_slug', '').strip().lower().replace(' ', '-')
        slug = custom_slug or generate_slug()
        while NFCCard.query.filter_by(unique_id=slug).first():
            slug = generate_slug()
        card = NFCCard(unique_id=slug,
                       user_id=int(user_id) if user_id else None,
                       label=label)
        db.session.add(card)
        db.session.commit()
        flash(f'Card "{slug}" created successfully!', 'success')
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/suspend', methods=['POST'])
    @login_required
    @admin_required
    def admin_suspend_user(user_id):
        user = User.query.get_or_404(user_id)
        user.is_suspended = not user.is_suspended
        db.session.commit()
        status = 'suspended' if user.is_suspended else 'reactivated'
        flash(f'User {user.username} has been {status}.', 'success')
        return redirect(url_for('admin_users'))

    # ── SRS: Admin — Card Status Control (Active/Suspended/Terminated) ─────────
    @app.route('/admin/cards/<int:card_id>/status', methods=['POST'])
    @login_required
    @admin_required
    def admin_card_status(card_id):
        card = NFCCard.query.get_or_404(card_id)
        new_status = request.form.get('status', 'active')
        if new_status not in ('active', 'suspended', 'terminated'):
            flash('Invalid status value.', 'error')
            return redirect(url_for('admin_users'))
        card.status = new_status
        db.session.commit()
        flash(f'Card "{card.unique_id}" status set to {new_status.capitalize()}.', 'success')
        return redirect(request.referrer or url_for('admin_users'))

    # ── Admin — Assign Card (Provisioning) ────────────────────────────────────
    @app.route('/admin/assign-card', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_assign_card():
        """Provisioning tool: bind a physical NFC slug to an employee.

        POST body fields:
            card_id       – NFCCard.id of the selected unassigned card
            employee_id   – User.id of the target employee
            target_url    – Custom redirect URL (empty → global company ad)
        """
        GLOBAL_AD_URL = 'https://samartha.in'

        if request.method == 'POST':
            card_id      = request.form.get('card_id', type=int)
            employee_id  = request.form.get('employee_id', type=int)
            custom_url   = request.form.get('target_url', '').strip()

            card = NFCCard.query.get(card_id)
            employee = User.query.get(employee_id)

            if not card:
                flash('Selected card not found.', 'error')
                return redirect(url_for('admin_assign_card'))
            if not employee:
                flash('Selected employee not found.', 'error')
                return redirect(url_for('admin_assign_card'))
            if card.user_id is not None:
                flash(f'Card "{card.unique_id}" is already assigned. Suspend it first to re-assign.', 'error')
                return redirect(url_for('admin_assign_card'))

            card.user_id    = employee.id
            card.target_url = custom_url if custom_url else GLOBAL_AD_URL
            card.status     = 'active'
            db.session.commit()

            flash(
                f'Card "{card.unique_id}" successfully assigned to '
                f'{employee.name or employee.username} '
                f'(→ {card.target_url}).',
                'success'
            )
            return redirect(url_for('admin_assign_card'))

        # GET: fetch unassigned cards and all non-admin employees
        unassigned_cards = NFCCard.query.filter_by(user_id=None).order_by(NFCCard.created_at.desc()).all()
        employees = User.query.filter_by(is_admin=False, is_suspended=False).order_by(User.name).all()
        recently_assigned = (
            db.session.query(NFCCard, User)
            .join(User, NFCCard.user_id == User.id)
            .order_by(NFCCard.created_at.desc())
            .limit(10)
            .all()
        )
        return render_template(
            'admin/assign_card.html',
            unassigned_cards=unassigned_cards,
            employees=employees,
            recently_assigned=recently_assigned,
            global_ad_url=GLOBAL_AD_URL
        )

    # ── SRS: Admin — Daily Goals ───────────────────────────────────────────────
    @app.route('/admin/goals', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_goals():
        if request.method == 'POST':
            goal_date_str = request.form.get('goal_date', '')
            target_scans = int(request.form.get('target_scans', 10))
            reward_desc = request.form.get('reward_desc', '').strip()
            try:
                goal_date = datetime.strptime(goal_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format.', 'error')
                return redirect(url_for('admin_goals'))
            existing = DailyGoal.query.filter_by(date=goal_date).first()
            if existing:
                existing.target_scans = target_scans
                existing.reward_desc = reward_desc
                flash(f'Goal for {goal_date} updated!', 'success')
            else:
                goal = DailyGoal(date=goal_date, target_scans=target_scans,
                                 reward_desc=reward_desc, created_by=current_user.id)
                db.session.add(goal)
                flash(f'Goal for {goal_date} created!', 'success')
            db.session.commit()
            return redirect(url_for('admin_goals'))

        goals = DailyGoal.query.order_by(DailyGoal.date.desc()).limit(30).all()
        return render_template('admin/goals.html', goals=goals, today=date.today())

    # ── SRS: Admin — Notice Board ─────────────────────────────────────────────
    @app.route('/admin/notifications', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_notifications():
        if request.method == 'POST':
            target = request.form.get('target_emp_id', 'ALL').strip() or 'ALL'
            message = request.form.get('message', '').strip()
            if not message:
                flash('Message cannot be empty.', 'error')
                return redirect(url_for('admin_notifications'))
            notice = Notification(target_emp_id=target, message=message,
                                  created_by=current_user.id)
            db.session.add(notice)
            db.session.commit()
            flash('Notification sent!', 'success')
            return redirect(url_for('admin_notifications'))

        notices = Notification.query.order_by(Notification.timestamp.desc()).all()
        employees = User.query.filter_by(is_admin=False).all()
        return render_template('admin/notifications.html', notices=notices, employees=employees)

    # ── SRS: Admin — Export Data (Excel) ──────────────────────────────────────
    @app.route('/admin/export')
    @login_required
    @admin_required
    def admin_export():
        export_type = request.args.get('type', 'preview')

        # Build tap log data
        taps = db.session.query(TapAnalytics, NFCCard, User).join(
            NFCCard, TapAnalytics.card_id == NFCCard.id
        ).outerjoin(User, NFCCard.user_id == User.id).all()

        tap_rows = []
        for tap, card, user in taps:
            tap_rows.append({
                'Tap ID': tap.id,
                'Card ID': card.unique_id,
                'Employee': user.username if user else 'Unassigned',
                'Emp ID': user.emp_id if user else '',
                'Timestamp': tap.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'Device': tap.device_type,
                'Browser': tap.browser,
                'Unique': 'Yes' if tap.is_unique else 'No',
            })

        # Build employee metrics
        employees = User.query.filter_by(is_admin=False).all()
        emp_rows = []
        for emp in employees:
            emp_rows.append({
                'Emp ID': emp.emp_id or '',
                'Username': emp.username,
                'Full Name': emp.name or '',
                'Email': emp.email,
                'Total Points': emp.total_points or 0,
                'Total Taps': emp.total_taps,
                'Unique Taps Today': emp.unique_taps_today(),
                'Weekly Taps': emp.unique_taps_this_week(),
                'Status': 'Suspended' if emp.is_suspended else 'Active',
                'Joined': emp.created_at.strftime('%Y-%m-%d'),
            })

        if export_type == 'excel':
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                pd.DataFrame(tap_rows).to_excel(writer, sheet_name='Tap Logs', index=False)
                pd.DataFrame(emp_rows).to_excel(writer, sheet_name='Employee Metrics', index=False)
            buf.seek(0)
            filename = f"nfc_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
            return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             download_name=filename, as_attachment=True)

        if export_type == 'csv':
            df = pd.DataFrame(tap_rows)
            csv_data = df.to_csv(index=False)
            response = make_response(csv_data)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename=tap_logs.csv'
            return response

        # Preview page
        return render_template('admin/export.html',
                               tap_count=len(tap_rows),
                               emp_count=len(emp_rows))

    # ── Error Handlers ────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
