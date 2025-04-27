import os
DB_USERNAME = "admin"
DB_PASSWORD = "SpartanPT2001!"
DB_HOST = "my-rds-instance1.cxgqwwgcmm8d.us-west-1.rds.amazonaws.com"
DB_PORT = "3306"
DB_NAME = "stock_trading_users"
SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False