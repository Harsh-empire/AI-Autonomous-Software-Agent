"""
NOTE: AI-generated sample cafe website application.
Used as an example target for adversarial testing and demonstration.
"""

import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, FloatField, IntegerField
from wtforms.validators import DataRequired, Email, Length, EqualTo, NumberRange
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import stripe

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cafe_dev_secret_key_change_in_production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cafe.db'
app.config['STRIPE_PUBLIC_KEY'] = os.environ.get('STRIPE_PUBLIC_KEY', 'pk_test_sample_placeholder')
app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_sample_placeholder')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

stripe.api_key = app.config['STRIPE_SECRET_KEY']

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    cart = db.relationship('CartItem', backref='user', lazy=True)

class Coffee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=True)
    image = db.Column(db.String(100), nullable=True)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    coffee_id = db.Column(db.Integer, db.ForeignKey('coffee.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class OrderForm(FlaskForm):
    submit = SubmitField('Place Order')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/menu')
def menu():
    coffees = Coffee.query.all()
    return render_template('menu.html', coffees=coffees)

@app.route('/cart', methods=['GET', 'POST'])
@login_required
def cart():
    form = OrderForm()
    if form.validate_on_submit():
        # Process the order
        return redirect(url_for('checkout'))
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.coffee.price * item.quantity for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total=total, form=form)

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    form = OrderForm()
    if form.validate_on_submit():
        # Process the payment
        return redirect(url_for('index'))
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.coffee.price * item.quantity for item in cart_items)
    return render_template('checkout.html', cart_items=cart_items, total=total, form=form)

@app.route('/add_to_cart/<int:coffee_id>', methods=['POST'])
@login_required
def add_to_cart(coffee_id):
    coffee = Coffee.query.get_or_404(coffee_id)
    quantity = request.form.get('quantity', 1, type=int)
    cart_item = CartItem.query.filter_by(coffee_id=coffee_id, user_id=current_user.id).first()
    if cart_item:
        cart_item.quantity += quantity
    else:
        cart_item = CartItem(coffee_id=coffee_id, quantity=quantity, user_id=current_user.id)
        db.session.add(cart_item)
    db.session.commit()
    return redirect(url_for('menu'))

@app.route('/remove_from_cart/<int:item_id>', methods=['POST'])
@login_required
def remove_from_cart(item_id):
    cart_item = CartItem.query.get_or_404(item_id)
    if cart_item.user_id == current_user.id:
        db.session.delete(cart_item)
        db.session.commit()
    return redirect(url_for('cart'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, email=form.email.data, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)