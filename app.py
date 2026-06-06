import os, uuid, logging, io, base64
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
from PIL import Image
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bridge2026secret-change-in-prod")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
QR_DIR = os.path.join(BASE_DIR, "static", "qrcodes")
DB_PATH = os.path.join(BASE_DIR, "instance", "bridge.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

db = SQLAlchemy(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== MODÈLES ==========

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Attendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    linkedin = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    photo = db.Column(db.String(200), nullable=True)
    qr_code = db.Column(db.String(200), nullable=True)
    qr_base64 = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.relationship('User', backref='attendees')

class Masterclass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    speaker = db.Column(db.String(120), nullable=False)
    time_slot = db.Column(db.String(60), nullable=False)
    room = db.Column(db.String(60), nullable=True)
    description = db.Column(db.Text, nullable=False)
    takeaway = db.Column(db.String(300), nullable=True)
    video_url = db.Column(db.String(300), nullable=True)

# ========== DÉCORATEURS ==========

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Veuillez vous connecter pour accéder à cette page.", "warning")
            return redirect(url_for('signup'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Veuillez vous connecter.", "warning")
            return redirect(url_for('signup'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash("Accès non autorisé. Droits administrateur requis.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ========== FONCTIONS ==========

def compress_and_save_photo(file):
    try:
        if not file or file.filename == '':
            return None
        fname = f"{uuid.uuid4().hex}.jpg"
        dest_path = os.path.join(UPLOAD_DIR, fname)
        
        # Ouvrir l'image et la redimensionner
        img = Image.open(file)
        
        # Convertir en RGB si nécessaire
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Redimensionner pour mobile (max 400x400)
        img.thumbnail((400, 400), Image.Resampling.LANCZOS)
        
        # Sauvegarder avec compression élevée pour mobile
        img.save(dest_path, 'JPEG', quality=70, optimize=True)
        
        return f"uploads/{fname}"
    except Exception as e:
        logger.error(f"Photo error: {e}")
        return None

def generate_qr_file(linkedin_url, stem):
    try:
        os.makedirs(QR_DIR, exist_ok=True)
        qr = qrcode.QRCode(version=1, box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_H)
        qr.add_data(linkedin_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0A2540", back_color="white")
        dest = os.path.join(QR_DIR, f"{stem}.png")
        img.save(dest)
        return f"qrcodes/{stem}.png"
    except Exception as e:
        logger.error(f"QR error: {e}")
        return None

def generate_qr_base64(linkedin_url):
    try:
        qr = qrcode.QRCode(version=1, box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_H)
        qr.add_data(linkedin_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0A2540", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_base64}"
    except Exception as e:
        logger.error(f"QR base64 error: {e}")
        return None

def seed_masterclasses():
    # Toujours supprimer et réinsérer pour refléter les modifications de app.py
    Masterclass.query.delete()
    db.session.commit()
    sessions = [
        Masterclass(title="Crowdfunding dans le secteur OneHealth", speaker="Mr Mohamed ben hmida & Mr Arnaud Poisonnier", time_slot="16:00", description="Découvrez comment le financement participatif peut booster les projets OneHealth en Tunisie.", takeaway="Les clés pour lancer une campagne de crowdfunding réussie.", video_url="https://www.youtube.com/embed/dQw4w9WgXcQ"),
        Masterclass(title="One Health, Green Biotechnology & Nano Innovation", speaker="Ms Hedya Jemai & Ms Roua Ben Dassi & Ms Rim Chawachi", time_slot="16:00", description="Explorez l'intersection entre biotechnologie verte, nano-innovation et santé préventive.", takeaway="Comprendre comment les nouvelles technologies peuvent prévenir les crises sanitaires.", video_url="https://www.youtube.com/embed/dQw4w9WgXcQ"),
        Masterclass(title="The Missing Radiologist - AI, Imaging Biobanks", speaker="Ms Oumaima Laifa", time_slot="16:00", description="Comment l'IA peut combler le manque de radiologues en Afrique.", takeaway="Les opportunités de l'IA pour la radiologie en Afrique.", video_url="https://www.youtube.com/embed/dQw4w9WgXcQ"),
        Masterclass(title="Tunisian Startup Survival Roadmap", speaker="Mr Mohamed Amine Khiari", time_slot="16:00", description="Le parcours de survie des startups tunisiennes inspiré de la Silicon Valley.", takeaway="Une feuille de route claire pour réussir sa startup.", video_url="https://www.youtube.com/embed/dQw4w9WgXcQ"),
    ]
    db.session.add_all(sessions)
    db.session.commit()


def create_admin():
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", email="admin@bridge.com", is_admin=True)
        admin.set_password("admin")
        db.session.add(admin)
        db.session.commit()
        logger.info("Admin créé: username='admin', password='admin'")

# ========== ROUTES AUTH ==========

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash(f"Bienvenue {username} !", "success")
            return redirect(url_for('index'))
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
    
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        if not username or not email or not password:
            flash("Tous les champs sont obligatoires.", "danger")
            return redirect(url_for('signup'))
        
        if password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return redirect(url_for('signup'))
        
        if User.query.filter_by(username=username).first():
            flash("Ce nom d'utilisateur est déjà pris.", "danger")
            return redirect(url_for('signup'))
        
        if User.query.filter_by(email=email).first():
            flash("Cet email est déjà utilisé.", "danger")
            return redirect(url_for('signup'))
        
        user = User(username=username, email=email, is_admin=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash("Compte créé avec succès ! Connectez-vous maintenant.", "success")
        return redirect(url_for('login'))
    
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for('signup'))

@app.route("/profile")
@login_required
def profile():
    user = User.query.get(session['user_id'])
    if user.is_admin:
        return redirect(url_for('dashboard'))
    my_attendees = Attendee.query.filter_by(user_id=user.id).all()
    return render_template("profile.html", user=user, my_attendees=my_attendees)

@app.route("/dashboard")
@login_required
@admin_required
def dashboard():
    attendees = Attendee.query.order_by(Attendee.id.desc()).all()
    masterclasses = Masterclass.query.all()
    for attendee in attendees:
        if attendee.qr_code:
            attendee.display_qr = url_for('static', filename=attendee.qr_code)
        elif attendee.qr_base64:
            attendee.display_qr = attendee.qr_base64
        else:
            attendee.display_qr = None
    counts = {
        "total": Attendee.query.count(),
        "masterclass": Attendee.query.filter_by(category="masterclass").count(),
        "vip": Attendee.query.filter_by(category="vip").count(),
        "participant": Attendee.query.filter_by(category="participant").count(),
    }
    return render_template("dashboard.html", attendees=attendees, masterclasses=masterclasses, counts=counts, session=session)

# ========== ROUTES CRUD ==========

@app.route("/")
def index():
    if 'user_id' not in session:
        return redirect(url_for('signup'))
    attendees = Attendee.query.order_by(Attendee.id.desc()).all()
    masterclasses = Masterclass.query.all()
    for attendee in attendees:
        if attendee.qr_code:
            attendee.display_qr = url_for('static', filename=attendee.qr_code)
        elif attendee.qr_base64:
            attendee.display_qr = attendee.qr_base64
        else:
            attendee.display_qr = None
    counts = {
        "total": Attendee.query.count(),
        "masterclass": Attendee.query.filter_by(category="masterclass").count(),
        "vip": Attendee.query.filter_by(category="vip").count(),
        "participant": Attendee.query.filter_by(category="participant").count(),
    }
    return render_template("index.html", attendees=attendees, masterclasses=masterclasses, counts=counts, session=session)

@app.route("/add", methods=["POST"])
@login_required
def add_attendee():
    name = request.form.get("name", "").strip()
    linkedin = request.form.get("linkedin", "").strip()
    category = request.form.get("category", "participant").strip()
    
    if not name or not linkedin:
        flash("Le nom et l'URL LinkedIn sont obligatoires.", "error")
        return redirect(url_for("index"))
    
    if not linkedin.startswith("http"):
        linkedin = "https://" + linkedin
    
    photo_path = None
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename != '':
            photo_path = compress_and_save_photo(file)
    
    qr_path = generate_qr_file(linkedin, uuid.uuid4().hex)
    qr_base64 = None
    if not qr_path:
        qr_base64 = generate_qr_base64(linkedin)
    
    attendee = Attendee(
        name=name, 
        linkedin=linkedin, 
        category=category, 
        photo=photo_path, 
        qr_code=qr_path, 
        qr_base64=qr_base64,
        user_id=session['user_id']
    )
    db.session.add(attendee)
    db.session.commit()
    flash(f"{name} a été ajouté(e) au répertoire !", "success")
    return redirect(url_for("index"))

@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_attendee(id):
    attendee = Attendee.query.get_or_404(id)
    user = User.query.get(session['user_id'])

    if not user.is_admin and attendee.user_id != user.id:
        flash("Vous ne pouvez modifier que vos propres participants depuis votre profil.", "danger")
        return redirect(url_for('profile'))

    if request.method == "POST":
        attendee.name = request.form.get("name", "").strip()
        new_linkedin = request.form.get("linkedin", "").strip()
        attendee.category = request.form.get("category", "participant").strip()

        if not new_linkedin.startswith("http"):
            new_linkedin = "https://" + new_linkedin

        # Régénérer le QR code si le LinkedIn a changé
        if new_linkedin != attendee.linkedin:
            attendee.linkedin = new_linkedin
            # Supprimer l'ancien QR code fichier
            if attendee.qr_code:
                old_qr = os.path.join(BASE_DIR, "static", attendee.qr_code)
                if os.path.exists(old_qr):
                    os.remove(old_qr)
            # Générer le nouveau QR code pointant vers le nouveau LinkedIn
            qr_path = generate_qr_file(new_linkedin, uuid.uuid4().hex)
            if qr_path:
                attendee.qr_code = qr_path
                attendee.qr_base64 = None
            else:
                attendee.qr_code = None
                attendee.qr_base64 = generate_qr_base64(new_linkedin)
        else:
            attendee.linkedin = new_linkedin

        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '':
                if attendee.photo:
                    old_path = os.path.join(BASE_DIR, "static", attendee.photo)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                attendee.photo = compress_and_save_photo(file)

        db.session.commit()
        flash(f"{attendee.name} a été modifié !", "success")
        if user.is_admin:
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('profile'))

    return render_template("edit.html", attendee=attendee)

@app.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete_attendee(id):
    attendee = Attendee.query.get_or_404(id)
    user = User.query.get(session['user_id'])

    if not user.is_admin and attendee.user_id != user.id:
        flash("Vous ne pouvez supprimer que vos propres participants depuis votre profil.", "danger")
        return redirect(url_for('profile'))

    if attendee.photo:
        full = os.path.join(BASE_DIR, "static", attendee.photo)
        if os.path.exists(full):
            os.remove(full)
    if attendee.qr_code:
        full = os.path.join(BASE_DIR, "static", attendee.qr_code)
        if os.path.exists(full):
            os.remove(full)
    db.session.delete(attendee)
    db.session.commit()
    flash("Participant supprimé.", "info")
    if user.is_admin:
        return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('profile'))

@app.route("/masterclasses")
def masterclasses():
    sessions = Masterclass.query.all()
    return render_template("masterclasses.html", masterclasses=sessions)

# ========== ROUTE DE TEST ==========
@app.route("/test-simple")
def test_simple():
    return render_template("test_simple.html", date=datetime.now())

# ========== INIT ==========

with app.app_context():
    db.create_all()
    seed_masterclasses()
    create_admin()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)