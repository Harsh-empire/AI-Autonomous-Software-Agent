import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default_dev_secret_key_override_in_env')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(200), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    tasks = Task.query.filter_by(user_id=session['user_id']).all()
    return render_template('tasks.html', tasks=tasks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
        else:
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/create_task', methods=['GET', 'POST'])
def create_task():
    if request.method == 'POST':
        content = request.form['content']
        new_task = Task(content=content, user_id=session['user_id'])
        db.session.add(new_task)
        db.session.commit()
        flash('Task created successfully', 'success')
        return redirect(url_for('index'))
    return render_template('create_task.html')

@app.route('/mark_task/<int:task_id>', methods=['POST'])
def mark_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id == session['user_id']:
        task.completed = not task.completed
        db.session.commit()
        flash('Task marked as completed', 'success')
    return redirect(url_for('index'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id == session['user_id']:
        db.session.delete(task)
        db.session.commit()
        flash('Task deleted successfully', 'success')
    return redirect(url_for('index'))

@app.before_request
def create_tables():
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    app.run(debug=True)