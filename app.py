from flask import Flask, render_template, request, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bootstrap import Bootstrap5
from flask_bcrypt import Bcrypt
from functools import wraps
import yfinance as yf
import datetime
import random


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:password@localhost/Stock_Trading_Users'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'

bootstrap = Bootstrap5(app)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)


@app.template_filter('currency')
def currency_format(value):
    return "${:,.2f}".format(value)

app.jinja_env.filters['currency'] = currency_format

def get_random_modifier():
    return random.uniform(-0.05, 0.05)

class Users(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(250), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)
    money = db.Column(db.Float(10), nullable=False)
    role = db.Column(db.String(50), default="user", nullable=False)


class StocksOwned(db.Model):
    transaction_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    stock_owned = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(250), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_purchased = db.Column(db.Float(10), nullable=False)

    user = db.relationship('Users', backref=db.backref('stocks_owned', lazy=True))

class Transactions(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    symbol = db.Column(db.String(10), nullable=True)
    quantity = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Float(10), nullable=True)
    amount = db.Column(db.Float(10), nullable=False)
    status = db.Column(db.String(20), default="completed", nullable=False)  # 'pending', 'completed', 'cancelled'
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = db.relationship('Users', backref=db.backref('transactions', lazy=True))

class AvailableStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(250), nullable=False)
    ticker = db.Column(db.String(50), unique=True, nullable=False, index=True)
    total_volume = db.Column(db.Integer, nullable=False)
    initial_price = db.Column(db.Float(10), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False) # Admin can deactivate a stock

    def __repr__(self):
        return f'<AvailableStock {self.ticker}>'

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return Users.query.get(int(user_id))

bcrypt = Bcrypt(app)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/portfolio')
@login_required
def portfolio():
    stocks = StocksOwned.query.filter_by(id=current_user.id).all()

    # Get current prices and calculate profit/loss
    portfolio_data = []
    total_portfolio_value = current_user.money  # Start with cash balance

    for stock in stocks:
        try:
            ticker = yf.Ticker(stock.stock_owned)
            current_price = ticker.info.get('currentPrice', ticker.info.get('regularMarketPrice'))

            stock_data = {
                'symbol': stock.stock_owned,
                'name': stock.name,
                'quantity': stock.quantity,
                'price_purchased': stock.price_purchased,
                'current_price': current_price,
                'total_value': current_price * stock.quantity,
                'profit_loss': (current_price - stock.price_purchased) * stock.quantity,
                'profit_loss_percent': ((current_price - stock.price_purchased) / stock.price_purchased) * 100
            }

            portfolio_data.append(stock_data)
            total_portfolio_value += stock_data['total_value']

        except Exception as e:
            # If we can't get current price, use purchase price
            stock_data = {
                'symbol': stock.stock_owned,
                'name': stock.name,
                'quantity': stock.quantity,
                'price_purchased': stock.price_purchased,
                'current_price': stock.price_purchased,
                'total_value': stock.price_purchased * stock.quantity,
                'profit_loss': 0,
                'profit_loss_percent': 0
            }
            portfolio_data.append(stock_data)
            total_portfolio_value += stock_data['total_value']

    return render_template('portfolio.html',
                           portfolio=portfolio_data,
                           cash_balance=current_user.money,
                           total_portfolio_value=total_portfolio_value)

@app.route('/transaction-history')
@login_required
def transaction_history():
    transactions = Transactions.query.filter_by(user_id=current_user.id).order_by(Transactions.timestamp.desc()).all()
    return render_template('transaction_history.html', transactions=transactions)

@app.route('/pending-orders')
@login_required
def pending_orders():
    orders = PendingOrders.query.filter_by(user_id=current_user.id).order_by(PendingOrders.timestamp.desc()).all()
    return render_template('pending_orders.html', orders=orders)

@app.route('/cancel-order/<int:order_id>')
@login_required
def cancel_order(order_id):
    order = PendingOrders.query.get_or_404(order_id)

    if order.user_id != current_user.id:
        flash('Unauthorized action', 'danger')
        return redirect(url_for('pending_orders'))

    # Create a transaction record for the cancelled order
    transaction = Transactions(
        user_id=current_user.id,
        transaction_type=f"{order.order_type}_cancelled",
        symbol=order.symbol,
        quantity=order.quantity,
        price=order.price,
        amount=order.quantity * order.price,
        status="cancelled"
    )

    db.session.add(transaction)
    db.session.delete(order)
    db.session.commit()

    flash(f'Order for {order.quantity} shares of {order.symbol} has been cancelled', 'success')
    return redirect(url_for('pending_orders'))

@app.route('/trade')
@login_required
def trade():
    # Get available stocks from database
    db_available_stocks = AvailableStock.query.filter_by(is_active=True).all()

    # Create list with available volume for each stock
    available_stocks = []
    for stock in db_available_stocks:
        # Calculate currently owned shares
        total_owned = db.session.query(db.func.sum(StocksOwned.quantity)).filter_by(
            stock_owned=stock.ticker).scalar() or 0


        available_volume = stock.total_volume - total_owned


        stock_info = {
            'ticker': stock.ticker,
            'company_name': stock.company_name,
            'initial_price': stock.initial_price,
            'total_volume': stock.total_volume,
            'available_volume': available_volume
        }

        available_stocks.append(stock_info)

    return render_template('trade.html', available_stocks=available_stocks)

@app.route('/stock_preview')
@login_required
def stock_preview():
    symbol = request.args.get('symbol')
    if not symbol:
        flash('No symbol provided', 'error')
        return redirect(url_for('trade'))


    admin_stock = AvailableStock.query.filter_by(ticker=symbol, is_active=True).first()


    user_owns = StocksOwned.query.filter_by(id=current_user.id, stock_owned=symbol).first()
    user_owns_quantity = user_owns.quantity if user_owns else 0

    if admin_stock:

        # Calculate currently available shares
        total_owned = db.session.query(db.func.sum(StocksOwned.quantity)).filter_by(
            stock_owned=symbol).scalar() or 0

        available_shares = admin_stock.total_volume - total_owned

        # Create stock_info dictionary with admin-provided data
        stock_info = {
            'symbol': symbol.upper(),
            'name': admin_stock.company_name,
            'market': 'Admin-managed',
            'increaseDecrease': '0.00',
            'percentChange': '0.00%',
            'volume': available_shares,  # Available shares for trading
            'totalVolume': admin_stock.total_volume,  # Total volume set by admin
            'dayHigh': admin_stock.initial_price * 1.02,  # Simulate slight variation
            'dayLow': admin_stock.initial_price * 0.98,   # Simulate slight variation
            'askPrice': admin_stock.initial_price,
            'currentPrice': admin_stock.initial_price,
            'user_owns_quantity': user_owns_quantity,
            'is_admin_stock': True
        }
        return render_template('stock_preview.html', stock_info=stock_info)
    else:
        # For regular yfinance stocks
        try:
            stock = yf.Ticker(symbol)
            info = stock.info

            # Calculate increase/decrease and percent change
            current_price = info.get('currentPrice', info.get('regularMarketPrice'))
            previous_close = info.get('previousClose')
            increase_decrease = current_price - previous_close
            percent_change = (increase_decrease / previous_close) * 100

            # Generate a random modifier for the ask price, day high, and day low
            random_modifier = get_random_modifier()

            # Apply the random modifier to the ask price, day high, and day low
            ask_price = info.get('ask', 'N/A')
            day_high = info.get('dayHigh', 'N/A')
            day_low = info.get('dayLow', 'N/A')

            if ask_price != 'N/A':
                ask_price *= (1 + random_modifier)  # Apply random modifier
            if day_high != 'N/A':
                day_high *= (1 + random_modifier)  # Apply random modifier
            if day_low != 'N/A':
                day_low *= (1 + random_modifier)  # Apply random modifier

            stock_info = {
                'symbol': symbol.upper(),
                'name': info.get('longName', 'N/A'),
                'market': info.get('market', 'N/A'),
                'increaseDecrease': f"{increase_decrease:.2f}",
                'percentChange': f"{percent_change:.2f}%",
                'volume': info.get('volume', 'N/A'),
                'dayHigh': day_high,
                'dayLow': day_low,
                'askPrice': ask_price,
                'user_owns_quantity': user_owns_quantity
            }
            return render_template('stock_preview.html', stock_info=stock_info)
        except Exception as e:
            flash(f'Error fetching stock data: {str(e)}', 'error')
            return redirect(url_for('trade'))

@app.route('/cash-management', methods=['GET', 'POST'])
@login_required
def cash_management():
    if request.method == 'POST':
        action = request.form.get('action')
        amount = float(request.form.get('amount'))

        if amount <= 0:
            flash('Amount must be greater than zero', 'danger')
            return redirect(url_for('cash_management'))

        if action == 'deposit':
            # Process deposit
            current_user.money += amount

            # Record transaction
            transaction = Transactions(
                user_id=current_user.id,
                transaction_type='deposit',
                amount=amount,
                status='completed'
            )

            db.session.add(transaction)
            db.session.commit()
            flash(f'Successfully deposited ${amount:.2f}', 'success')

        elif action == 'withdraw':
            # Check if user has enough funds
            if current_user.money < amount:
                flash('Insufficient funds for withdrawal', 'danger')
                return redirect(url_for('cash_management'))

            # Process withdrawal
            current_user.money -= amount

            # Record transaction
            transaction = Transactions(
                user_id=current_user.id,
                transaction_type='withdraw',
                amount=amount,
                status='completed'
            )

            db.session.add(transaction)
            db.session.commit()
            flash(f'Successfully withdrew ${amount:.2f}', 'success')

        return redirect(url_for('portfolio'))

    return render_template('cash_management.html')

@app.route('/purchase_stock', methods=['POST'])
@login_required
def purchase_stock():
    action = request.form.get('action')
    quantity = int(request.form.get('quantity'))
    symbol = request.form.get('symbol')
    price = float(request.form.get('price'))
    order_type = request.form.get('order_type', 'market')  # 'market' or 'limit'

    # Check if this stock is managed by admin
    admin_stock = AvailableStock.query.filter_by(ticker=symbol, is_active=True).first()

    # Fetch stock name from yfinance if not an admin-managed stock
    if admin_stock:
        stock_name = admin_stock.company_name
    else:
        stock = yf.Ticker(symbol)
        stock_name = stock.info.get('longName', 'N/A')

    if order_type == 'market':
        # Execute order immediately (market order)
        if action == 'buy':
            total_cost = quantity * price

            # Check if user has enough funds
            if current_user.money < total_cost:
                flash('Insufficient funds', 'error')
                return redirect(url_for('portfolio'))

            # If this is an admin-managed stock, check volume availability
            if admin_stock:
                # Calculate currently available shares
                total_owned = db.session.query(db.func.sum(StocksOwned.quantity)).filter_by(
                    stock_owned=symbol).scalar() or 0

                available_shares = admin_stock.total_volume - total_owned

                if quantity > available_shares:
                    flash(f'Not enough shares available. Only {available_shares} shares of {symbol} available.', 'error')
                    return redirect(url_for('portfolio'))

            # Proceed with purchase
            current_user.money -= total_cost

            # Check if user already owns this stock
            existing_stock = StocksOwned.query.filter_by(id=current_user.id, stock_owned=symbol).first()

            if existing_stock:
                # Calculate new average purchase price
                total_shares = existing_stock.quantity + quantity
                total_cost_basis = (existing_stock.quantity * existing_stock.price_purchased) + (quantity * price)
                new_avg_price = total_cost_basis / total_shares

                # Update existing record
                existing_stock.quantity = total_shares
                existing_stock.price_purchased = new_avg_price
            else:
                # Create a new entry
                new_stock = StocksOwned(
                    id=current_user.id,
                    stock_owned=symbol,
                    name=stock_name,
                    quantity=quantity,
                    price_purchased=price
                )
                db.session.add(new_stock)

            # Record transaction
            transaction = Transactions(
                user_id=current_user.id,
                transaction_type='buy',
                symbol=symbol,
                quantity=quantity,
                price=price,
                amount=total_cost,
                status='completed'
            )

            db.session.add(transaction)
            db.session.commit()
            flash('Purchase successful!', 'success')

        elif action == 'sell':
            # Check if the user owns the stock and has enough quantity
            stock_owned = StocksOwned.query.filter_by(id=current_user.id, stock_owned=symbol).first()

            if not stock_owned:
                flash('You do not own this stock', 'error')
                return redirect(url_for('portfolio'))
            elif stock_owned.quantity < quantity:
                flash('You do not have enough shares to sell', 'error')
                return redirect(url_for('portfolio'))
            else:
                # Calculate total value of the sale
                total_value = quantity * price

                # Add funds to user's cash account
                current_user.money += total_value

                # Update or remove the stock from StocksOwned
                if stock_owned.quantity == quantity:
                    # Remove the stock if the user sells all shares
                    db.session.delete(stock_owned)
                else:
                    # Reduce the quantity if the user sells some shares
                    stock_owned.quantity -= quantity

                # Record transaction
                transaction = Transactions(
                    user_id=current_user.id,
                    transaction_type='sell',
                    symbol=symbol,
                    quantity=quantity,
                    price=price,
                    amount=total_value,
                    status='completed'
                )

                db.session.add(transaction)
                db.session.commit()
                flash('Sale successful!', 'success')

    return redirect(url_for('portfolio'))

@app.route('/admin')
@login_required
@admin_required
def admin():
    # Get all stocks and users to display in admin dashboard
    stocks = AvailableStock.query.all()
    users = Users.query.all()
    return render_template('admin.html', stocks=stocks, users=users)

@app.route('/add-stock', methods=['GET', 'POST'])
@login_required
@admin_required
def add_stock():
    if request.method == 'POST':
        # Get form data
        company_name = request.form.get('company_name')
        ticker = request.form.get('ticker').upper()  # Convert to uppercase
        volume = int(request.form.get('volume'))
        initial_price = float(request.form.get('initial_price'))

        # Validate data
        if not company_name or not ticker or volume <= 0 or initial_price <= 0:
            flash('All fields are required and must be valid', 'danger')
            return redirect(url_for('add_stock'))

        # Check if stock with this ticker already exists
        existing_stock = AvailableStock.query.filter_by(ticker=ticker).first()
        if existing_stock:
            flash(f'Stock with ticker {ticker} already exists', 'danger')
            return redirect(url_for('add_stock'))

        # Create new stock
        new_stock = AvailableStock(
            company_name=company_name,
            ticker=ticker,
            total_volume=volume,
            initial_price=initial_price,
            is_active=True
        )

        try:
            db.session.add(new_stock)
            db.session.commit()
            flash(f'Stock {ticker} ({company_name}) has been added successfully', 'success')
            return redirect(url_for('admin'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding stock: {str(e)}', 'danger')
            return redirect(url_for('add_stock'))

    popular_stocks = []
    # List of common stock symbols
    stock_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM', 'V', 'WMT', 'PG', 'JNJ', 'NVDA']

    try:
        for symbol in stock_symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                if info:
                    popular_stocks.append({
                        'symbol': symbol,
                        'name': info.get('longName', 'Unknown'),
                        'price': info.get('currentPrice', info.get('regularMarketPrice', 0))
                    })
            except Exception:
                # Skip stocks that can't be fetched
                continue
    except Exception as e:
        flash(f'Error fetching stock data: {str(e)}', 'warning')

    # GET request - render the form with popular stocks
    return render_template('add_stock.html', popular_stocks=popular_stocks)

@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == "POST":
        hashed_password = bcrypt.generate_password_hash(request.form.get("password")).decode('utf-8')
        user = Users(
            username=request.form.get("username"),
            password=hashed_password,
            role="user",  # Default role is "user"
            money = 100000
        )
        db.session.add(user)
        db.session.commit()

        # Create initial deposit transaction
        transaction = Transactions(
            user_id=user.id,
            transaction_type='deposit',
            amount=100000,  # Initial balance
            status='completed'
        )
        db.session.add(transaction)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("sign_up.html")


@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = Users.query.filter_by(username=request.form.get("username")).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get("password")):
            login_user(user)
            return redirect(url_for("portfolio"))
    return render_template("login.html")

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for("home"))

if __name__ == '__main__':
    app.run(debug=True)

     #.\venv\Scripts\activate To Start Virtual
    #flask --app app run --debug To run in debug mode

    # python -m venv venv to create virtual environment
