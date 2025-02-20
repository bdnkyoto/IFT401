from flask import Flask, render_template
from flask_bootstrap import Bootstrap5

app = Flask(__name__)

bootstrap = Bootstrap5(app)

@app.route('/')

def home():
    return render_template('portfolio.html')

@app.route('/portfolio')

def portfolio():
    return render_template('portfolio.html')


@app.route('/trade')

def trade():
    return render_template('trade.html')

@app.route('/admin')

def admin():
    return render_template('admin.html')

if __name__ == '__main__':
    app.run(debug=True)

     #.\venv\Scripts\activate To Start Virtual
    #flask --app app run --debug To run in debug mode

    # python -m venv venv to create virtual environment
