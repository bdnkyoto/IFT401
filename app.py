from flask import Flask, render_template, request, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bootstrap import Bootstrap5
from flask_bcrypt import Bcrypt
from functools import wraps
import yfinance as yf


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:password@localhost/Stock_Trading_Users'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'

bootstrap = Bootstrap5(app)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)

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
    
    transactions = StocksOwned.query.filter_by(id=current_user.id).all()
    return render_template('portfolio.html', transactions=transactions)

@app.route('/trade')
@login_required
def trade():
    return render_template('trade.html')


@app.route('/stock_preview')
@login_required
def stock_preview():
    symbol = request.args.get('symbol')
    if not symbol:
        flash('No symbol provided', 'error')
        return redirect(url_for('trade'))

    try:
        stock = yf.Ticker(symbol)
        info = stock.info

        # Calculate increase/decrease and percent change
        current_price = info.get('currentPrice', info.get('regularMarketPrice'))
        previous_close = info.get('previousClose')
        increase_decrease = current_price - previous_close
        percent_change = (increase_decrease / previous_close) * 100

        user_owns = StocksOwned.query.filter_by(id=current_user.id, stock_owned=symbol).first()
        user_owns_quantity = user_owns.quantity if user_owns else 0

        stock_info = {
            'symbol': symbol.upper(),
            'name': info.get('longName', 'N/A'),
            'market': info.get('market', 'N/A'),
            'increaseDecrease': f"{increase_decrease:.2f}",
            'percentChange': f"{percent_change:.2f}%",
            'volume': info.get('volume', 'N/A'),
            'dayHigh': info.get('dayHigh', 'N/A'),
            'dayLow': info.get('dayLow', 'N/A'),
            'askPrice': info.get('ask', 'N/A'),
            'user_owns_quantity': user_owns_quantity
        }
        return render_template('stock_preview.html', stock_info=stock_info)
    except Exception as e:
        flash(f'Error fetching stock data: {str(e)}', 'error')
        return redirect(url_for('trade'))
    

@app.route('/purchase_stock', methods=['POST'])
@login_required
def purchase_stock():
    action = request.form.get('action')
    quantity = int(request.form.get('quantity'))
    symbol = request.form.get('symbol')
    price = float(request.form.get('price'))

    # Fetch stock name from yfinance
    stock = yf.Ticker(symbol)
    stock_name = stock.info.get('longName', 'N/A')

    if action == 'buy':
        total_cost = quantity * price

        if current_user.money < total_cost:
            flash('Insufficient funds', 'error')
        else:
            # Deduct funds from the user
            current_user.money -= total_cost

            # Create an entry in the StocksOwned table
            new_stock = StocksOwned(
                id=current_user.id,
                stock_owned=symbol,
                name=stock_name,
                quantity=quantity,
                price_purchased=price
            )
            db.session.add(new_stock)
            db.session.commit()
            flash('Purchase successful!', 'success')

    elif action == 'sell':
        # Check if the user owns the stock and has enough quantity
        stock_owned = StocksOwned.query.filter_by(id=current_user.id, stock_owned=symbol).first()

        if not stock_owned:
            flash('You do not own this stock', 'error')
        elif stock_owned.quantity < quantity:
            flash('You do not have enough shares to sell', 'error')
        else:
            # Calculate total value of the sale
            total_value = quantity * price

            # Add funds to the user
            current_user.money += total_value

            # Update or remove the stock from StocksOwned
            if stock_owned.quantity == quantity:
                # Remove the stock if the user sells all shares
                db.session.delete(stock_owned)
            else:
                # Reduce the quantity if the user sells some shares
                stock_owned.quantity -= quantity

            db.session.commit()
            flash('Sale successful!', 'success')

    return redirect(url_for('trade'))

@app.route('/admin')
@login_required
@admin_required

def admin():
    return render_template('admin.html')

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
