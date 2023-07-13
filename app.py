from flask import Flask, send_file, render_template, request, flash, redirect, url_for, abort, session
from datetime import datetime
from flask_migrate import Migrate
from random import choice
import string 
import base64
import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
import phonenumbers
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Column, Integer, String
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import qrcode
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
import re



cache = Cache()


app = Flask(__name__)
cache.init_app(app, config={'CACHE_TYPE': 'simple'})
limiter = Limiter(app, default_limits=["10/day"])
app.secret_key = "5df3c2b8576617decbf7"

# Flask-Login configuration
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database configuration
base_dir = os.path.dirname(os.path.realpath(__file__))
app.config["SQLALCHEMY_DATABASE_URI"]='sqlite:///' + os.path.join(base_dir, 'snipit.db') 
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# db.init_app(app)
db = SQLAlchemy(app)


class ShortUrls(db.Model):
    __tablename__ = 'shorturls'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    original_url = db.Column(db.String(2048), nullable=False)
    short_id = db.Column(db.String(16), nullable=False, unique=True)
    short_url = db.Column(db.String(100))
    click_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    clicks = db.relationship('Click', backref='shorturls', lazy=True)
    shorturls_user = db.relationship('User', backref='shorturls')

    def __init__(self, user_id, original_url, short_id, short_url, click_count, created_at):
        self.user_id = user_id
        self.original_url = original_url
        self.short_id = short_id
        self.short_url = short_url
        self.click_count = click_count
        self.created_at = datetime.now()


class Click(db.Model):
    __tablename__ = 'clicks'
    id = db.Column(db.Integer, primary_key=True)
    short_url_id = db.Column(db.Integer, db.ForeignKey('shorturls.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(255))
    referral_source = db.Column(db.String(2048))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, short_url_id, ip_address, user_agent, referral_source):
        self.short_url_id = short_url_id
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.referral_source = referral_source
        self.created_at = datetime.now()


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    company_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    country = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(150))
    created_at = db.Column(db.DateTime(), default=datetime.now(), nullable=False)

    short_urls = db.relationship('ShortUrls', backref='users')


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Custom filter for base64 encoding
@app.template_filter('b64encode')
def base64_encode(value):
    return base64.b64encode(value).decode('utf-8')


def generate_short_id(num_of_chars: int):
    """Function to generate short_id of specified number of characters"""
    return ''.join(choice(string.ascii_letters + string.digits) for _ in range(num_of_chars))


@app.route('/', methods=['GET', 'POST'])
@cache.cached(timeout=60)
def index():
    qr_image_data = b'My QR Code Data'
    return render_template('index.html')

@app.route('/about')
@cache.cached(timeout=60)
def about():
    return render_template('about.html')


@app.route('/shortenit')
@cache.cached(timeout=60)
def shortenit():
    return render_template('shortenit.html')


@app.route('/shortenedURL')
@cache.cached(timeout=60)
def shortenedURL():
    return render_template('shortenedURL.html')


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        
        # Create a new contact instance
        new_contact = Contact(name=name, email=email, message=message)
        
        # Save the contact to the database
        db.session.add(new_contact)
        db.session.commit()
        
        # Redirect or render a success page
        return render_template('index.html')
    
    return render_template('contact.html')


@app.route('/analytics')
def analytics():
    total_urls = ShortUrls.query.count()
    return render_template('analytics.html', total_urls=total_urls)


# The URL shortening route and function...
@app.route('/shorten', methods=['GET', 'POST'])
@limiter.limit("10/day", key_func=get_remote_address)
@cache.cached(timeout=60)
@login_required
def shorten():
    qr_image_data = b''
    short_url = ''  # Initialize the variable with a default value
    if request.method == 'POST':
        url = request.form['url']
        short_id = request.form['custom_id']

        # Get the authenticated user's ID
        user_id = current_user.id

        if short_id and ShortUrls.query.filter_by(short_id=short_id).first():
            flash('Please enter a different custom ID!')
            return redirect(url_for('shortenit'))

        if not url:
            flash('The URL is required!')
            return redirect(url_for('shortenit'))

        if not short_id:
            short_id = generate_short_id(8)

        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=5, border=4)
        qr.add_data(url)
        qr.make(fit=True)

        qr_stream = BytesIO()
        qr.make_image(fill_color='black', back_color='white').save(qr_stream, 'PNG')
        qr_stream.seek(0)

        new_link = ShortUrls(
            user_id=user_id,
            original_url=url,
            short_id=short_id,
            short_url=short_url,
            click_count=0,
            created_at=datetime.now()
        )
        db.session.add(new_link)
        db.session.commit()

        short_url = request.host_url + short_id
        if qr_image_data is not None:
            return render_template('shortenedURL.html', short_url=short_url, qr_image_data=qr_stream.getvalue())
        else:
            flash('No image generated')
    return render_template('shortenedURL.html', qr_image_data=qr_image_data)


@app.route('/download_qr/<qr_image_data>')
def download_qr(qr_image_data):
    # Convert the base64-encoded QR code image data back to bytes
    qr_bytes = base64.b64decode(qr_image_data)

    if qr_bytes:
        qr_filename = 'qr_code.png'
        return send_file(BytesIO(qr_bytes), attachment_filename=qr_filename, as_attachment=True)
    else:
        flash('No image generated')
        return redirect(url_for('index'))


def get_current_user():
    # Using a session-based authentication system
    user_id = session.get('user_id')  # Retrieve the user ID from the session
    if user_id:
        # Querying of the User model
        user = User.query.get(user_id)  # Retrieve the user from the database based on the user ID
        return user

    # If user_id is not found in the session or the user doesn't exist, return None
    return None


def get_user_short_urls(user_id):
    user = User.query.get(user_id)
    if user:
        return ShortUrls.query.filter_by(user_id=user.id).all()
    else:
        return []   


@app.route('/dashboard')
def dashboard():
    # Retrieve the necessary data for the user dashboard
    user = get_current_user()  # Example function to get the current user
    short_urls = get_user_short_urls(user.id)  # Example function to get the user's short URLs

    # Fetch click analytics for each short URL
    click_analytics = {}
    for short_url in short_urls:
        click_analytics[short_url.id] = get_click_analytics(short_url.id)

    # Render the dashboard template and pass the necessary data
    return render_template('dashboard.html', user=user, short_urls=short_urls, click_analytics=click_analytics)


@app.route('/history')
def history():
    url_activities = ShortUrls.query.all()
    return render_template('history.html', url_activities=url_activities)

def get_click_analytics(short_url_id):
    clicks = Click.query.filter_by(short_url_id=short_url_id).all()
    return clicks


def populate_clicks(short_url_id, ip_address, user_agent, referral_source):
    click = Click(short_url_id=short_url_id, ip_address=ip_address, user_agent=user_agent, referral_source=referral_source)
    db.session.add(click)
    db.session.commit()


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        # Redirect to the homepage or another route
        return redirect(url_for('index'))

    else:
        if request.method == 'POST':
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            company_name = request.form.get('company_name')
            email = request.form.get('email')
            country = request.form.get('country')
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
    
    
            # Check if the user already exists in the database
            user = User.query.filter_by(email=email).first()
            if user:
                flash(f'Email address already registered.')
                return redirect(url_for('register'))
    
            # Check if the passwords match
            if password != confirm_password:
                flash(f'Passwords do not match.')
                return redirect(url_for('register'))
    
            # Create a new user
            new_user = User(
                first_name=first_name,
                last_name=last_name,
                company_name=company_name,
                email=email,
                country=country
            )
            new_user.set_password(password)
    
            # Save the new user to the database
            db.session.add(new_user)
            db.session.commit()
    
            flash(f'Registration successful. Please log in.')
            return redirect(url_for('login'))
    
        return render_template('register.html')
    

@app.route('/login', methods=['GET', 'POST'])
@cache.cached(timeout=60)
def login():
    if current_user.is_authenticated:
        # Redirect to the homepage or another route
        return redirect(url_for('shortenit'))
    
    else:  
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            
            # Find the user by email address
            user = User.query.filter_by(email=email).first()
            
            if user and user.check_password(password):
                # Log in the user
                login_user(user)

                # Store user ID in the session
                session['user_id'] = user.id
                
                # Redirect to the homepage or another route
                return redirect(url_for('shortenit'))
            else:
                flash('Invalid email or password.')
                return redirect(url_for('login'))
        
        return render_template('login.html')

# The redirection route and function
@app.route('/<short_id>')
@cache.cached(timeout=60)
@login_required
def redirect_url(short_id):
    link = ShortUrls.query.filter_by(short_id=short_id).first()

    if link:
        link.click_count += 1
        db.session.commit()
        return redirect(link.original_url)
    else:
        flash('Invalid URL')
        return redirect(url_for('shortenit'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
