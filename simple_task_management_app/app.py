from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'aegis_dev_secret_key_override_in_env')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# =============================================================================
# DATABASE MODELS
# =============================================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    tasks = db.relationship('Task', backref='owner', lazy=True, cascade="all, delete-orphan")

    def __init__(self, username=None, password_hash=None, **kwargs):
        super().__init__(**kwargs)
        self.username = username
        self.password_hash = password_hash

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __init__(self, title=None, user_id=None, completed=False, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.user_id = user_id
        self.completed = completed

# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    tasks = Task.query.filter_by(user_id=user.id).all()
    return render_template('tasks.html', user=user, tasks=tasks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()

        if not username or not password:
            flash('Please enter both username and password.', 'error')
            return redirect(url_for('login'))

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password. Please verify your credentials or register a new account.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        confirm_password = (request.form.get('confirm_password') or '').strip()

        if not username:
            flash('Username is required.', 'error')
            return redirect(url_for('register'))

        if len(username) > 80:
            flash('Username is too long (maximum 80 characters).', 'error')
            return redirect(url_for('register'))

        if not password or not confirm_password:
            flash('Password and confirm password are required.', 'error')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match. Please try again.', 'error')
            return redirect(url_for('register'))

        # Check if username already exists in database
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash(f"The username '{username}' is already registered! Please choose a different username or log in.", 'error')
            return redirect(url_for('register'))

        try:
            hashed_password = generate_password_hash(password)
            new_user = User(username=username, password_hash=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            flash(f"Account created successfully! You can now log in as '{username}'.", 'success')
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            flash(f"The username '{username}' is already taken. Please pick another username.", 'error')
            return redirect(url_for('register'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/add_task', methods=['POST'])
def add_task():
    if 'user_id' not in session:
        flash('Please log in to add tasks.', 'error')
        return redirect(url_for('login'))

    raw_title = request.form.get('title') or request.form.get('task') or ''
    title = raw_title.strip()

    if not title:
        flash('Task description cannot be empty.', 'error')
        return redirect(url_for('index'))

    # Buffer limit check to defend against unicode floods
    if len(title) > 500:
        title = title[:500]

    try:
        new_task = Task(title=title, user_id=session['user_id'])
        db.session.add(new_task)
        db.session.commit()
        flash('Task added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Failed to save task.', 'error')

    return redirect(url_for('index'))

@app.route('/delete_task/<int:task_id>', methods=['GET', 'POST'])
def delete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    task = Task.query.get_or_404(task_id)
    if task.user_id == session.get('user_id'):
        db.session.delete(task)
        db.session.commit()
        flash('Task deleted.', 'info')

    return redirect(url_for('index'))

@app.route('/complete_task/<int:task_id>', methods=['GET', 'POST'])
def complete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    task = Task.query.get_or_404(task_id)
    if task.user_id == session.get('user_id'):
        task.completed = not task.completed
        db.session.commit()
        status_text = 'completed' if task.completed else 'marked pending'
        flash(f'Task {status_text}!', 'success')

    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(port=5000, debug=True)