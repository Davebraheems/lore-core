from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import stripe
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import traceback
load_dotenv()


app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'static')
)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
db_url = os.environ.get('DATABASE_URL', '')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Stripe configuration

STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET','')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# ─── Models ───────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    orders = db.relationship('Order', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(500))
    category = db.Column(db.String(100))
    stock = db.Column(db.Integer, default=100)
    stripe_price_id = db.Column(db.String(200))
    featured = db.Column(db.Boolean, default=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    stripe_session_id = db.Column(db.String(300), unique=True)
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True)
    customer_email = db.Column(db.String(150))


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── Cart Helpers ──────────────────────────────────────────────────────────────

def get_cart():
    return session.get('cart', {})

def save_cart(cart):
    session['cart'] = cart
    session.modified = True

def cart_count():
    cart = get_cart()
    return sum(item['quantity'] for item in cart.values())

def cart_total():
    cart = get_cart()
    return sum(item['price'] * item['quantity'] for item in cart.values())

app.jinja_env.globals['cart_count'] = cart_count
app.jinja_env.globals['cart_total'] = cart_total


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    featured = Product.query.filter_by(featured=True).all()
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    return render_template('index.html', featured=featured, categories=categories)


@app.route('/shop')
def shop():
    category = request.args.get('category')
    search = request.args.get('search', '')
    query = Product.query
    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))
    products = query.all()
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    return render_template('shop.html', products=products, categories=categories,
                           current_category=category, search=search)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    related = Product.query.filter_by(category=product.category).filter(Product.id != product.id).limit(4).all()
    return render_template('product_detail.html', product=product, related=related)


@app.route('/cart')
def cart():
    cart = get_cart()
    items = []
    for product_id, item in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            items.append({'product': product, 'quantity': item['quantity'],
                          'subtotal': product.price * item['quantity']})
    return render_template('cart.html', items=items, total=cart_total())


@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = int(request.form.get('quantity', 1))
    cart = get_cart()
    key = str(product_id)
    if key in cart:
        cart[key]['quantity'] += quantity
    else:
        cart[key] = {'name': product.name, 'price': product.price, 'quantity': quantity,
                     'image': product.image_url}
    save_cart(cart)
    flash(f'"{product.name}" added to cart!', 'success')
    return redirect(request.referrer or url_for('shop'))


@app.route('/cart/update', methods=['POST'])
def update_cart():
    product_id = str(request.form.get('product_id'))
    quantity = int(request.form.get('quantity', 0))
    cart = get_cart()
    if quantity <= 0:
        cart.pop(product_id, None)
    else:
        if product_id in cart:
            cart[product_id]['quantity'] = quantity
    save_cart(cart)
    return redirect(url_for('cart'))


@app.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(str(product_id), None)
    save_cart(cart)
    flash('Item removed from cart.', 'info')
    return redirect(url_for('cart'))


# ─── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not all([name, email, password]):
            flash('All fields are required.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
        else:
            user = User(name=name, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f'Welcome, {name}! Your account has been created.', 'success')
            return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=request.form.get('remember'))
            flash(f'Welcome back, {user.name}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/account')
@login_required
def account():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('account.html', orders=orders)


# ─── Stripe Checkout ──────────────────────────────────────────────────────────

@app.route('/checkout', methods=['POST'])
def checkout():
    # Set stripe key here instead of at module level
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    
    # Temporary debug check
    if not stripe.api_key:
        return f"Stripe key missing. Available env vars: {list(os.environ.keys())}", 500

    cart = get_cart()
    if not cart:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('cart'))

    line_items = []
    for product_id, item in cart.items():
        product = Product.query.get(int(product_id))
        if not product:
            continue
        line_items.append({
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': product.name,
                    'images': [product.image_url] if product.image_url and product.image_url.startswith('http') else [],
                },
                'unit_amount': int(product.price * 100),
            },
            'quantity': item['quantity'],
        })

    try:
        base_url = request.host_url.rstrip('/')

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=f"{base_url}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/cart",
            customer_email=current_user.email if current_user.is_authenticated else None,
            metadata={'user_id': current_user.id if current_user.is_authenticated else ''},
        )

        total = cart_total()
        order = Order(
            user_id=current_user.id if current_user.is_authenticated else None,
            stripe_session_id=checkout_session.id,
            total=total,
            status='pending',
            customer_email=current_user.email if current_user.is_authenticated else None,
        )
        db.session.add(order)
        db.session.flush()

        for product_id, item in cart.items():
            product = Product.query.get(int(product_id))
            if product:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item['quantity'],
                    price=product.price,
                )
                db.session.add(order_item)

        db.session.commit()
        return redirect(checkout_session.url, code=303)

    except stripe.error.StripeError as e:
        flash(f'Payment error: {str(e.user_message)}', 'danger')
        return redirect(url_for('cart'))

@app.route('/checkout/success')
def checkout_success():
    session_id = request.args.get('session_id')
    order = None
    if session_id:
        order = Order.query.filter_by(stripe_session_id=session_id).first()
        if order and order.status == 'pending':
            order.status = 'paid'
            db.session.commit()
            session['cart'] = {}
    return render_template('checkout_success.html', order=order)


@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session_data = event['data']['object']
        order = Order.query.filter_by(stripe_session_id=session_data['id']).first()
        if order:
            order.status = 'paid'
            order.customer_email = session_data.get('customer_email', order.customer_email)
            db.session.commit()

    return jsonify({'status': 'ok'})


# ─── Seed Data ────────────────────────────────────────────────────────────────

def seed_products():
    if Product.query.count() > 0:
        return
    products = [
        Product(name='The Courage to Be Disliked', description='A philosophical dialogue on self-acceptance and freedom based on Adlerian psychology. One of the most transformative books on how to live freely.', price=18.99, category='Books', image_url='https://images.unsplash.com/photo-1544947950-fa07a98d237f?w=600&h=600&fit=crop', featured=True),
        Product(name='Thinking, Fast and Slow', description='Daniel Kahneman\'s seminal work on the two systems that shape our thinking—fast, intuitive System 1 and slow, deliberate System 2.', price=16.99, category='Books', image_url='https://images.unsplash.com/photo-1512820790803-83ca734da794?w=600&h=600&fit=crop', featured=True),
        Product(name='The Design of Everyday Things', description='Don Norman\'s classic on how design communicates—and why so many things are needlessly confusing.', price=21.99, category='Books', image_url='https://images.unsplash.com/photo-1543002588-bfa74002ed7e?w=600&h=600&fit=crop', featured=False),
        Product(name='Premium Hardcover Journal', description='200 pages of 120gsm acid-free paper with a beautiful linen cover. Perfect for deep thinking and daily reflection.', price=34.99, category='Stationery', image_url='https://images.unsplash.com/photo-1531346878377-a5be20888e57?w=600&h=600&fit=crop', featured=True),
        Product(name='Brass Mechanical Pencil', description='Precision-engineered 0.5mm mechanical pencil in solid brass. Gets better with age and use.', price=42.00, category='Stationery', image_url='https://images.unsplash.com/photo-1585336261022-680e295ce3fe?w=600&h=600&fit=crop', featured=False),
        Product(name='Washi Tape Set (12 rolls)', description='Curated set of Japanese washi tape in muted, sophisticated tones. Ideal for journaling and gift wrapping.', price=14.99, category='Stationery', image_url='https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&h=600&fit=crop', featured=False),
        Product(name='Ceramic Pour-Over Coffee Set', description='Handcrafted ceramic dripper with matching server. Makes exceptional single-origin coffee with minimal fuss.', price=68.00, category='Lifestyle', image_url='https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600&h=600&fit=crop', featured=True),
        Product(name='Beeswax Candle Trio', description='Three hand-poured 100% pure beeswax candles. Burns clean and slow with a gentle honey scent.', price=28.00, category='Lifestyle', image_url='https://images.unsplash.com/photo-1603006905003-be475563bc59?w=600&h=600&fit=crop', featured=False),
        Product(name='Linen Tote Bag', description='Heavyweight natural linen tote, hand-screen printed with a minimalist design. Holds a surprising amount.', price=22.00, category='Lifestyle', image_url='https://images.unsplash.com/photo-1622560480605-d83c853bc5c3?w=600&h=600&fit=crop', featured=False),
    ]
    for p in products:
        db.session.add(p)
    db.session.commit()
    print("✓ Seeded products")


with app.app_context():
    db.create_all()
    seed_products()


@app.errorhandler(500)
def internal_error(e):
    return f"<pre>{traceback.format_exc()}</pre>", 500

