# Lore & Co. — Flask eCommerce Store

A full-featured eCommerce website built with Flask and Stripe.

## Features

- 🛍️ **Product catalogue** with categories, search, and filtering
- 🛒 **Shopping cart** (session-based, no login required)
- 💳 **Stripe Checkout** for real payments (card, Apple Pay, Google Pay)
- 🔐 **User auth** — register, login, logout with hashed passwords
- 📦 **Order history** in user account dashboard
- 📱 Responsive design

## Setup

### 1. Install dependencies

```bash
cd ecommerce
pip install -r requirements.txt
```

### 2. Get your Stripe API keys

1. Sign up at https://stripe.com (free)
2. Go to **Developers → API Keys** in your dashboard
3. Copy your **Publishable key** and **Secret key** (use test keys)

### 3. Set environment variables

```bash
# macOS/Linux
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_PUBLISHABLE_KEY="pk_test_..."
export SECRET_KEY="your-random-secret-key-here"

# Windows
set STRIPE_SECRET_KEY=sk_test_...
set STRIPE_PUBLISHABLE_KEY=pk_test_...
set SECRET_KEY=your-random-secret-key-here
```

### 4. Run the app

```bash
python app.py
```

Visit: http://localhost:5001

## Testing Payments

Use Stripe's test card numbers:
- ✅ Success: `4242 4242 4242 4242`
- ❌ Declined: `4000 0000 0000 0002`
- Any future expiry date and any 3-digit CVC

## Project Structure

```
ecommerce/
├── app.py              # Main Flask app, routes, models
├── requirements.txt
├── instance/
│   └── ecommerce.db    # SQLite database (auto-created)
└── templates/
    ├── base.html       # Navigation, footer, flash messages
    ├── index.html      # Homepage with hero + featured products
    ├── shop.html       # Product grid with filters
    ├── product_detail.html
    ├── cart.html
    ├── login.html
    ├── register.html
    ├── account.html    # Order history
    └── checkout_success.html
```

## Optional: Stripe Webhooks

For production, set up a webhook to reliably confirm payments:

```bash
stripe listen --forward-to localhost:5001/webhook
export STRIPE_WEBHOOK_SECRET="whsec_..."
```

Webhook endpoint: `POST /webhook`
