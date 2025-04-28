from flask import Flask, render_template, request, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bootstrap import Bootstrap5
from flask_bcrypt import Bcrypt
from functools import wraps
import yfinance as yf
import datetime, time
import random



from config import SQLALCHEMY_DATABASE_URI

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = 'key'

db = SQLAlchemy(app)

bootstrap = Bootstrap5(app)


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

class MarketHours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.String(8), nullable=False, default='09:30')
    end_time = db.Column(db.String(8), nullable=False, default='16:00')

class MarketHoliday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    holiday_name = db.Column(db.String(100), nullable=False)
    holiday_date = db.Column(db.Date, nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f'<MarketHoliday {self.holiday_name} ({self.holiday_date})>'


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
    
    # Get market hours and check if market is open
    market_hours = MarketHours.query.first()
    if not market_hours:
        flash('Market hours not configured', 'error')
        return redirect(url_for('trade'))

    # Check if today is a holiday
    today = datetime.date.today()
    holiday = MarketHoliday.query.filter_by(holiday_date=today).first()

    # Check if market is open
    now = datetime.datetime.now().time()
    market_open = datetime.datetime.strptime(market_hours.start_time, '%H:%M').time()
    market_close = datetime.datetime.strptime(market_hours.end_time, '%H:%M').time()

    is_market_open = False
    if not holiday:  # Only check time if it's not a holiday
        # Handle overnight markets
        if market_close < market_open:  # Overnight market
            is_market_open = now >= market_open or now <= market_close
        else:
            is_market_open = market_open <= now <= market_close


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
            'is_admin_stock': True,
             'is_market_open': is_market_open
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
                'user_owns_quantity': user_owns_quantity,
                 'is_market_open': is_market_open
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

    # Get market hours
    market_hours = MarketHours.query.first()
    if not market_hours:
        flash('Market hours not configured', 'error')
        return redirect(url_for('portfolio'))

    # Check if today is a holiday
    today = datetime.date.today()
    holiday = MarketHoliday.query.filter_by(holiday_date=today).first()

    # Check if market is open
    now = datetime.datetime.now().time()
    market_open = datetime.datetime.strptime(market_hours.start_time, '%H:%M').time()
    market_close = datetime.datetime.strptime(market_hours.end_time, '%H:%M').time()

    is_market_open = False
    if not holiday:  # Only check time if it's not a holiday
        # Handle overnight markets
        if market_close < market_open:  # Overnight market
            is_market_open = now >= market_open or now <= market_close
        else:
            is_market_open = market_open <= now <= market_close

    # Check if this stock is managed by admin
    admin_stock = AvailableStock.query.filter_by(ticker=symbol, is_active=True).first()

    # Fetch stock name from yfinance if not an admin-managed stock
    if admin_stock:
        stock_name = admin_stock.company_name
    else:
        stock = yf.Ticker(symbol)
        stock_name = stock.info.get('longName', 'N/A')

    if order_type == 'market':
        if action == 'buy':
            total_cost = quantity * price

            # Check if user has enough funds
            if current_user.money < total_cost:
                flash('Insufficient funds', 'error')
                return redirect(url_for('portfolio'))

            # If this is an admin-managed stock, check volume availability
            if admin_stock:
                total_owned = db.session.query(db.func.sum(StocksOwned.quantity)).filter_by(
                    stock_owned=symbol).scalar() or 0
                available_shares = admin_stock.total_volume - total_owned

                if quantity > available_shares:
                    flash(f'Not enough shares available. Only {available_shares} shares of {symbol} available.', 'error')
                    return redirect(url_for('portfolio'))

            if is_market_open:
                # Market is open - process immediately
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
            else:
                # Market is closed - create pending transaction
                transaction = Transactions(
                    user_id=current_user.id,
                    transaction_type='buy',
                    symbol=symbol,
                    quantity=quantity,
                    price=price,
                    amount=total_cost,
                    status='pending'
                )
                db.session.add(transaction)
                db.session.commit()

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
                total_value = quantity * price

                if is_market_open:
                    # Market is open - process immediately
                    current_user.money += total_value

                    # Update or remove the stock from StocksOwned
                    if stock_owned.quantity == quantity:
                        db.session.delete(stock_owned)
                    else:
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
                else:
                    # Market is closed - create pending transaction
                    transaction = Transactions(
                        user_id=current_user.id,
                        transaction_type='sell',
                        symbol=symbol,
                        quantity=quantity,
                        price=price,
                        amount=total_value,
                        status='pending'
                    )
                    db.session.add(transaction)
                    db.session.commit()

    return redirect(url_for('portfolio'))

@app.route('/admin')
@login_required
@admin_required
def admin():
    stocks = AvailableStock.query.all()
    users = Users.query.all()
    market_hours = MarketHours.query.first()
    return render_template('admin.html', stocks=stocks, users=users, market_hours=market_hours)

@app.context_processor
def inject_market_hours():
    market_hours = MarketHours.query.first()
    return dict(market_hours=market_hours)

@app.context_processor
def inject_market_status():
    market_hours = MarketHours.query.first()

    # Check if today is a holiday
    today = datetime.date.today()
    holiday = MarketHoliday.query.filter_by(holiday_date=today).first()

    is_market_open = False
    market_status = "Closed"

    if holiday:
        market_status = f"Closed for {holiday.holiday_name}"
    elif market_hours:
        now = datetime.datetime.now().time()
        market_open = datetime.datetime.strptime(market_hours.start_time, '%H:%M').time()
        market_close = datetime.datetime.strptime(market_hours.end_time, '%H:%M').time()

        # Check if market is open
        if market_close < market_open:  # Overnight market
            is_market_open = now >= market_open or now <= market_close
        else:
            is_market_open = market_open <= now <= market_close

        market_status = "Open" if is_market_open else "Closed"

    return dict(
        market_hours=market_hours,
        is_market_open=is_market_open,
        market_status=market_status,
        today_holiday=holiday
    )

@app.route('/market_hours', methods=['GET', 'POST'])
@login_required
@admin_required
def set_market_hours():
    market_hours = MarketHours.query.first()

    if request.method == 'POST':
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')

        if not market_hours:
            market_hours = MarketHours(start_time=start_time, end_time=end_time)
            db.session.add(market_hours)
        else:
            market_hours.start_time = start_time
            market_hours.end_time = end_time

        db.session.commit()
        flash('Market hours updated successfully!', 'success')
        return redirect(url_for('admin'))

    return render_template('market_hours.html', market_hours=market_hours)

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

@app.route('/edit-stock/<string:ticker>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_stock(ticker):
    # Get the stock to edit
    stock = AvailableStock.query.filter_by(ticker=ticker).first_or_404()

    if request.method == 'POST':
        # Get form data
        company_name = request.form.get('company_name')
        initial_price = float(request.form.get('initial_price'))
        total_volume = int(request.form.get('volume'))

        # Validate data
        if not company_name or initial_price <= 0 or total_volume <= 0:
            flash('All fields are required and must be valid', 'danger')
            return redirect(url_for('edit_stock', ticker=ticker))

        # Check current owned volume before updating total volume
        current_owned = db.session.query(db.func.sum(StocksOwned.quantity)).filter_by(
            stock_owned=ticker).scalar() or 0

        if total_volume < current_owned:
            flash(f'Cannot set volume below current owned shares ({current_owned})', 'danger')
            return redirect(url_for('edit_stock', ticker=ticker))

        # Update stock data
        stock.company_name = company_name
        stock.initial_price = initial_price
        stock.total_volume = total_volume

        try:
            db.session.commit()
            flash(f'Stock {ticker} updated successfully', 'success')
            return redirect(url_for('admin'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating stock: {str(e)}', 'danger')
            return redirect(url_for('edit_stock', ticker=ticker))

    # GET request - show the edit form
    return render_template('edit_stock.html', stock=stock)

@app.route('/toggle-stock/<string:ticker>')
@login_required
@admin_required
def toggle_stock(ticker):
    stock = AvailableStock.query.filter_by(ticker=ticker).first_or_404()

    # Toggle the is_active status
    stock.is_active = not stock.is_active

    try:
        db.session.commit()
        status = "activated" if stock.is_active else "deactivated"
        flash(f'Stock {ticker} {status} successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error toggling stock status: {str(e)}', 'danger')

    return redirect(url_for('admin'))

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

def is_market_open():

    market_hours = MarketHours.query.first()
    if not market_hours:
        return False

    # Check if today is a holiday
    today = datetime.date.today()
    is_holiday = MarketHoliday.query.filter_by(holiday_date=today).first() is not None
    if is_holiday:
        return False

    now = datetime.datetime.now().time()
    try:
        market_open = datetime.datetime.strptime(market_hours.start_time, '%H:%M').time()
        market_close = datetime.datetime.strptime(market_hours.end_time, '%H:%M').time()

        # Handle overnight markets (if close time is earlier than open time)
        if market_close < market_open:
            return now >= market_open or now <= market_close
        return market_open <= now <= market_close
    except ValueError:
        return False

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = Users.query.filter_by(username=request.form.get("username")).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get("password")):
            login_user(user)

            # Process pending transactions if market is open
            if is_market_open():
                pending_transactions = Transactions.query.filter_by(
                    user_id=user.id,
                    status='pending'
                ).all()

                for transaction in pending_transactions:
                    if transaction.transaction_type == 'buy':
                        # Process buy transaction
                        if user.money >= transaction.amount:
                            user.money -= transaction.amount

                            # Update or create stock ownership
                            stock_owned = StocksOwned.query.filter_by(
                                id=user.id,
                                stock_owned=transaction.symbol
                            ).first()

                            if stock_owned:
                                # Calculate new average price
                                total_shares = stock_owned.quantity + transaction.quantity
                                total_cost = (stock_owned.price_purchased * stock_owned.quantity) + transaction.amount
                                new_avg_price = total_cost / total_shares

                                stock_owned.quantity = total_shares
                                stock_owned.price_purchased = new_avg_price
                            else:
                                new_stock = StocksOwned(
                                    id=user.id,
                                    stock_owned=transaction.symbol,
                                    name=transaction.symbol,
                                    quantity=transaction.quantity,
                                    price_purchased=transaction.price
                                )
                                db.session.add(new_stock)

                            transaction.status = 'completed'

                    elif transaction.transaction_type == 'sell':
                        # Process sell transaction
                        stock_owned = StocksOwned.query.filter_by(
                            id=user.id,
                            stock_owned=transaction.symbol
                        ).first()

                        if stock_owned and stock_owned.quantity >= transaction.quantity:
                            user.money += transaction.amount

                            if stock_owned.quantity == transaction.quantity:
                                db.session.delete(stock_owned)
                            else:
                                stock_owned.quantity -= transaction.quantity

                            transaction.status = 'completed'

                db.session.commit()

            return redirect(url_for("portfolio"))

    return render_template("login.html")

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route('/manage_holidays')
@login_required
@admin_required
def manage_holidays():
    holidays = MarketHoliday.query.order_by(MarketHoliday.holiday_date).all()
    return render_template('manage_holidays.html', holidays=holidays)

@app.route('/add_holiday', methods=['POST'])
@login_required
@admin_required
def add_holiday():
    holiday_name = request.form.get('holiday_name')
    holiday_date_str = request.form.get('holiday_date')

    try:
        holiday_date = datetime.datetime.strptime(holiday_date_str, '%Y-%m-%d').date()

        # Check if holiday already exists on this date
        existing_holiday = MarketHoliday.query.filter_by(holiday_date=holiday_date).first()
        if existing_holiday:
            flash(f'A holiday ({existing_holiday.holiday_name}) is already set for this date', 'warning')
            return redirect(url_for('manage_holidays'))

        new_holiday = MarketHoliday(
            holiday_name=holiday_name,
            holiday_date=holiday_date
        )

        db.session.add(new_holiday)
        db.session.commit()
        flash(f'Holiday "{holiday_name}" added successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding holiday: {str(e)}', 'danger')

    return redirect(url_for('manage_holidays'))

@app.route('/delete_holiday/<int:holiday_id>')
@login_required
@admin_required
def delete_holiday(holiday_id):
    holiday = MarketHoliday.query.get_or_404(holiday_id)

    try:
        db.session.delete(holiday)
        db.session.commit()
        flash(f'Holiday "{holiday.holiday_name}" deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting holiday: {str(e)}', 'danger')

    return redirect(url_for('manage_holidays'))

if __name__ == '__main__':
    app.run(debug=True)

     #.\venv\Scripts\activate To Start Virtual
    #flask --app app run --debug To run in debug mode

    # python -m venv venv to create virtual environment
