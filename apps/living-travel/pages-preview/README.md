# Living Travel — Static Cloudflare Pages Preview

> **Synthetic Preview Only** — This directory contains a static HTML/CSS preview
> of the Living Travel UI for visual review. It does **not** include the FastAPI
> backend, SQLite database, or any real user data. All content is synthetic
> fixture data.

## What this is

A static preview that lets designers, operators, and stakeholders navigate the
Living Travel product flow in a real browser without running the backend. Every
screen, form, and button is rendered as static HTML. No FastAPI POST requests
are made — forms either navigate to another static page or display a
"no persistence" notice.

## Directory structure

```text
pages-preview/
├─ site/                    # Static output directory (deploy this)
│  ├─ index.html            # Preview entry — traveler/operator links
│  ├─ operator/
│  │  ├─ login.html         # Operator login
│  │  ├─ dashboard.html     # Operator dashboard, traveler list
│  │  ├─ traveler-detail.html  # Traveler detail, editions, tokens
│  │  └─ edition-preview.html  # Edition draft review, publish/reject
│  ├─ traveler/
│  │  ├─ enter.html         # Access token entry
│  │  ├─ dashboard.html     # Preferences, latest edition
│  │  ├─ edition.html       # Edition detail, sections, feedback
│  │  └─ history.html       # Edition history table
│  ├─ assets/
│  │  └─ style.css          # All styles (no external CSS)
│  ├─ _headers               # Cloudflare Pages security headers
│  └─ robots.txt             # Blocks all crawlers
├─ tests/
│  └─ test_static_preview.py # Static validation tests (stdlib only)
└─ README.md                # This file
```

## Local execution

```powershell
python -m http.server 8788 --directory apps/living-travel/pages-preview/site
```

Then open:

- <http://localhost:8788/> — Preview entry
- <http://localhost:8788/traveler/enter.html> — Traveler access
- <http://localhost:8788/operator/login.html> — Operator login

## Running tests

```powershell
python -m pytest apps/living-travel/pages-preview/tests -q
```

Tests use **only** the Python standard library (`html.parser`, `pathlib`,
`urllib.parse`, `re`, `unittest`). No external dependencies are required.

## Cloudflare Pages deployment

### Build command

This is a pre-built static site — no build step is needed:

```
echo "No build step required — static HTML/CSS output"
```

### Output directory

```
apps/living-travel/pages-preview/site
```

### Deploy command

```powershell
npx wrangler pages deploy apps/living-travel/pages-preview/site `
  --project-name living-travel-preview `
  --branch preview
```

### Project details

- **Project name:** `living-travel-preview`
- **Production branch:** `preview`
- **Output directory:** `apps/living-travel/pages-preview/site`
- **Build command:** (none — static output)

## Security and data principles

### Synthetic-only

All content is explicitly synthetic:

- Traveler name: `여행자 시범` (clearly synthetic, not a real person)
- Destination: `부산` (Busan) — a city name, not personal data
- Token: `lt_preview_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6` (clearly a preview token)
- No real emails, phone numbers, or API responses
- No real travel bookings or reservations

Every page displays a consistent notice:

> **Synthetic Preview**
> 이 화면은 제품 검토용 가상 데이터로 구성되며 실제 여행 정보나 사용자 데이터를 사용하지 않습니다.

### No backend

- The FastAPI backend is **not** included
- No SQLite database is deployed
- No POST requests are sent to any backend
- All forms use `action="#"` with `onsubmit="return false;"`
- Navigation buttons are `<a>` links to other static pages

### Security headers (`_headers`)

```
X-Robots-Tag: noindex, nofollow
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; script-src 'none'; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'
```

### robots.txt

```
User-agent: *
Disallow: /
```

## Navigation flow

### Traveler

1. **Enter** (`traveler/enter.html`) → click "Enter" → **Dashboard**
2. **Dashboard** (`traveler/dashboard.html`) → click "Read Edition" → **Edition**
3. **Dashboard** → click "Edition History" → **History**
4. **History** (`traveler/history.html`) → click "Read" → **Edition**

### Operator

1. **Login** (`operator/login.html`) → click "Login" → **Dashboard**
2. **Dashboard** (`operator/dashboard.html`) → click "View" → **Traveler Detail**
3. **Traveler Detail** → click "Preview" → **Edition Preview**

## Limitations

- This is a **static preview only** — no real authentication, persistence, or
  data generation
- Form submissions are disabled with "no persistence" notices
- The preview does not connect to any backend service
- Mobile layout is tested at 360px width
- All content is synthetic fixture data based on the Living Travel product contract
