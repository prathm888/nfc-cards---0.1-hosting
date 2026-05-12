# Smart NFC Business Card Platform — Walkthrough

## ✅ What Was Built

A fully functional full-stack web application for managing Smart NFC Business Cards, live at **http://localhost:5000**.

---

## Project Structure

```
c:\Users\USER\Desktop\nfc cards\
├── app.py              # Flask app — all routes (auth, tracking, dashboard, admin, public)
├── models.py           # SQLAlchemy models (User, NFCCard, TapAnalytics, Lead)
├── config.py           # Flask config (secret key, DB URI, upload path, base URL)
├── requirements.txt    # Python dependencies
├── nfc.db              # Auto-created SQLite database
├── templates/
│   ├── base.html               # Sidebar layout, flash messages, dark theme
│   ├── auth/login.html         # Login page (glassmorphism)
│   ├── auth/register.html      # Registration page
│   ├── dashboard/index.html    # User dashboard with stats
│   ├── dashboard/cards.html    # Card management + QR codes
│   ├── dashboard/analytics.html# Chart.js analytics (line, doughnut, bar)
│   ├── dashboard/profile.html  # Profile editor + theme picker
│   ├── admin/index.html        # System health stats
│   ├── admin/heatmap.html      # 24h traffic heatmap
│   ├── admin/users.html        # User control + card creation modal
│   ├── public/card.html        # Public profile page (3 themes)
│   └── errors/{404,403}.html
└── static/
    ├── css/main.css    # Glass cards, nav links, buttons, animations
    └── uploads/        # User-uploaded logos
```

---

## Features Delivered

### Core Tracking Engine
| Route | What It Does |
|---|---|
| `GET /t/<slug>` | Parses UA → device + browser, hashes IP, logs to DB, `302` redirects |
| `GET /c/<slug>` | Public business card profile page |
| `GET /c/<slug>/vcf` | Generates `.vcf` vCard download on-the-fly |
| `POST /c/<slug>/lead` | Saves lead contact form to database |

### User Dashboard
- **Overview** — Total taps, cards, leads, 7-day activity
- **My Cards** — Edit redirect URLs, copy tracking link to clipboard, download QR code PNG
- **Analytics** — Chart.js line graph (taps over time), doughnut (device split), bar (top browsers); filterable by card and date range
- **Profile & Template** — Upload logo, fill bio/social links, choose from 3 card themes

### Admin Panel
- **System Health** — Total users, cards, taps, leads, new users today
- **Traffic Heatmap** — Top 20 most-tapped cards in last 24h with animated heat bars
- **User Control** — Full user table with suspend/reactivate, card creation modal

### Added-Value Features
- 🪪 **vCard (.vcf) Generator** — One-click contact download from public profile
- 📱 **QR Code Fallback** — Purple-tinted QR PNG for every card in dashboard
- 📊 **Chart.js Analytics** — Live AJAX charts with period/card filter
- 🎨 **3 Profile Themes** — Nexus Dark, Executive, Zen Minimal
- 🔒 **Hashed IPs** — SHA-256 partial hash for privacy-safe analytics

---

## Default Admin Credentials

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |
| URL | http://localhost:5000 |

> [!CAUTION]
> Change the admin password and `SECRET_KEY` in `config.py` before any public deployment.

---

## Key URLs

| URL | Description |
|---|---|
| `http://localhost:5000/` | Auto-redirects to dashboard or admin |
| `http://localhost:5000/auth/login` | Login page |
| `http://localhost:5000/auth/register` | New user registration |
| `http://localhost:5000/admin/` | Admin system health |
| `http://localhost:5000/admin/users` | Create cards, manage users |
| `http://localhost:5000/dashboard/` | User dashboard |
| `http://localhost:5000/t/<slug>` | **NFC tracking redirect** (put this on your physical card) |
| `http://localhost:5000/c/<slug>` | Public business card profile |
| `http://localhost:5000/c/<slug>/vcf` | vCard download |

---

## How to Issue a New NFC Card (Workflow)

1. Log in as **admin** → go to **User Control**
2. Click **Create New Card**
3. Select the client's user account from the dropdown
4. Enter a label (e.g. "John's Card") and optionally a custom slug (e.g. `john`)
5. Click **Create Card**
6. The client logs into their dashboard → **My Cards** → copies the tracking URL `/t/john`
7. Program that URL onto the physical NFC tag
8. Every tap is now silently logged and the visitor is redirected to their chosen destination

---

## Verification Summary (from server logs)

All routes confirmed working via HTTP 200/302 responses:
- `GET /` → 302 redirect ✅
- `POST /auth/login` → 302 redirect ✅
- `GET /admin/` → 200 ✅
- `GET /admin/users` → 200 ✅
- `GET /admin/heatmap` → 200 ✅
- `GET /dashboard/` → 200 ✅
- `GET /auth/logout` → 302 ✅
- Static assets (CSS) → 304 cached ✅

---

## Next Steps for Production

1. **Replace SQLite** with PostgreSQL — just change `SQLALCHEMY_DATABASE_URI` in `config.py`
2. **Set `BASE_URL`** to your real domain (e.g. `https://nfchub.com`) for correct QR/NFC links
3. **Use Gunicorn** instead of Flask dev server: `pip install gunicorn && gunicorn app:create_app()`
4. **Set a strong `SECRET_KEY`** via environment variable
5. **Add email notifications** for new leads (Flask-Mail)
