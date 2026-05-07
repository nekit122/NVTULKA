from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'supersecretkey123')
database_url = os.environ.get('DATABASE_URL', 'sqlite:///social.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['AVATARS_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AVATARS_FOLDER'], exist_ok=True)

# ========== MODELS ==========

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='default.png')
    bio = db.Column(db.String(300), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    posts = db.relationship('Post', backref='author', lazy=True)
    stories = db.relationship('Story', backref='user', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_pinned = db.Column(db.Boolean, default=False)
    original_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    hashtags = db.Column(db.Text, default='')
    likes = db.relationship('Like', backref='post', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy=True, cascade='all, delete-orphan')
    images = db.relationship('PostImage', backref='post', lazy=True, cascade='all, delete-orphan')

class PostImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user = db.relationship('User', backref='comments')

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'))

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(30), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    from_user = db.relationship('User', foreign_keys=[from_user_id])

class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_video = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def extract_hashtags(text):
    return ','.join(re.findall(r'#(\w+)', text))

def save_file(file, folder):
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov', '.avi', '.webp', '.mp3', '.webm']:
            filename = f"{datetime.utcnow().timestamp():.0f}_{secure_filename(file.filename)}"
            file.save(os.path.join(folder, filename))
            return filename
    return None

def get_unread_count():
    if current_user.is_authenticated:
        notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        msgs = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
        return notifs + msgs
    return 0

# ========== ROUTES ==========

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('recommendations'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        if not username or not email or not password:
            return render_template('register.html', error='Все поля обязательны')
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Логин занят')
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error='Email используется')
        hashed_pw = generate_password_hash(password, method='scrypt')
        new_user = User(username=username, email=email, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('recommendations'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('recommendations'))
        return render_template('login.html', error='Неверный логин или пароль')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/recommendations')
@login_required
def recommendations():
    posts = Post.query.filter(Post.original_post_id == None).order_by(Post.created_at.desc()).all()
    cutoff = datetime.utcnow() - timedelta(hours=24)
    stories = Story.query.filter(Story.created_at > cutoff).order_by(Story.created_at.desc()).all()
    return render_template('recommendations.html', posts=posts, stories=stories, unread_count=get_unread_count())

@app.route('/feed')
@login_required
def feed():
    following_ids = [f.followed_id for f in Follow.query.filter_by(follower_id=current_user.id).all()]
    following_ids.append(current_user.id)
    posts = Post.query.filter(Post.user_id.in_(following_ids), Post.original_post_id == None).order_by(Post.created_at.desc()).all()
    return render_template('recommendations.html', posts=posts, unread_count=get_unread_count(), feed_mode=True)

@app.route('/friends')
@login_required
def friends():
    following_ids = {f.followed_id for f in Follow.query.filter_by(follower_id=current_user.id).all()}
    follower_ids = {f.follower_id for f in Follow.query.filter_by(followed_id=current_user.id).all()}
    mutual_ids = following_ids & follower_ids
    friends_list = User.query.filter(User.id.in_(mutual_ids)).all()
    return render_template('friends.html', friends=friends_list, unread_count=get_unread_count())

@app.route('/chat/<int:friend_id>')
@login_required
def chat(friend_id):
    friend = User.query.get_or_404(friend_id)
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()
    Message.query.filter_by(sender_id=friend_id, receiver_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('chat.html', friend=friend, messages=messages, unread_count=get_unread_count())

@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    data = request.get_json()
    content = data.get('content')
    if content:
        msg = Message(sender_id=current_user.id, receiver_id=receiver_id, content=content)
        db.session.add(msg)
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'}), 400

@app.route('/send_voice/<int:receiver_id>', methods=['POST'])
@login_required
def send_voice(receiver_id):
    audio = request.files.get('audio')
    if audio:
        filename = f"voice_{datetime.utcnow().timestamp():.0f}.webm"
        audio.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        msg = Message(sender_id=current_user.id, receiver_id=receiver_id, content=f"[VOICE]{filename}")
        db.session.add(msg)
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'}), 400

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    users = []
    posts = []
    if query:
        users = User.query.filter(User.username.contains(query)).all()
        posts = Post.query.filter(Post.content.contains(query)).order_by(Post.created_at.desc()).all()
    return render_template('search.html', query=query, users=users, posts=posts, unread_count=get_unread_count())

@app.route('/create_post', methods=['POST'])
@login_required
def create_post():
    content = request.form.get('content', '')
    images = request.files.getlist('images')
    hashtags = extract_hashtags(content)
    post = Post(content=content, user_id=current_user.id, hashtags=hashtags)
    db.session.add(post)
    db.session.flush()
    for img in images:
        filename = save_file(img, app.config['UPLOAD_FOLDER'])
        if filename:
            db.session.add(PostImage(post_id=post.id, filename=filename))
    db.session.commit()
    return redirect(url_for('recommendations'))

@app.route('/create_story', methods=['POST'])
@login_required
def create_story():
    file = request.files.get('story')
    if file:
        filename = save_file(file, app.config['UPLOAD_FOLDER'])
        if filename:
            is_video = filename.endswith('.mp4') or filename.endswith('.mov')
            story = Story(user_id=current_user.id, filename=filename, is_video=is_video)
            db.session.add(story)
            db.session.commit()
    return redirect(url_for('recommendations'))

@app.route('/delete_post/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id == current_user.id:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('recommendations'))

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def comment(post_id):
    content = request.form.get('content')
    if content:
        db.session.add(Comment(content=content, user_id=current_user.id, post_id=post_id))
        db.session.commit()
    return redirect(url_for('recommendations'))

@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Like(user_id=current_user.id, post_id=post_id))
    db.session.commit()
    return jsonify({'likes': Like.query.filter_by(post_id=post_id).count()})

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == current_user.id:
        return jsonify({'status': 'error'}), 400
    existing = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'status': 'unfollowed'})
    db.session.add(Follow(follower_id=current_user.id, followed_id=user_id))
    db.session.commit()
    return jsonify({'status': 'followed'})

@app.route('/user/<int:user_id>')
@login_required
def user_page(user_id):
    user = User.query.get_or_404(user_id)
    posts = Post.query.filter_by(user_id=user.id, original_post_id=None).order_by(Post.created_at.desc()).all()
    followers_count = Follow.query.filter_by(followed_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()
    is_following = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first() is not None
    return render_template('user_page.html', user=user, posts=posts, followers_count=followers_count, following_count=following_count, is_following=is_following, unread_count=get_unread_count())

@app.route('/profile')
@login_required
def profile():
    posts = Post.query.filter_by(user_id=current_user.id).order_by(Post.created_at.desc()).all()
    followers_count = Follow.query.filter_by(followed_id=current_user.id).count()
    following_count = Follow.query.filter_by(follower_id=current_user.id).count()
    return render_template('profile.html', user=current_user, posts=posts, followers_count=followers_count, following_count=following_count, unread_count=get_unread_count())

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    current_user.bio = request.form.get('bio', '')
    avatar = request.files.get('avatar')
    if avatar:
        filename = save_file(avatar, app.config['AVATARS_FOLDER'])
        if filename:
            current_user.avatar = filename
    db.session.commit()
    return redirect(url_for('profile'))

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return render_template('notifications_page.html', notifications=notifs, unread_count=get_unread_count())

@app.route('/notifications/unread-count')
@login_required
def unread_count():
    return jsonify({'count': get_unread_count()})

@app.route('/notifications/read', methods=['POST'])
@login_required
def mark_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/games')
@login_required
def games():
    return render_template('games.html', unread_count=get_unread_count())

@app.route('/music')
@login_required
def music():
    return render_template('music.html', music_files=[], unread_count=get_unread_count())

@app.route('/bookmarks')
@login_required
def bookmarks():
    return render_template('recommendations.html', posts=[], unread_count=get_unread_count())

@app.route('/trends')
@login_required
def trends():
    return render_template('trends.html', tags=[], unread_count=get_unread_count())

@app.route('/profile_views')
@login_required
def profile_views():
    return render_template('profile_views.html', views=[], unread_count=get_unread_count())

# ========== INIT ==========
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
