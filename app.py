import os, uuid, logging, io, base64
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import qrcode
from PIL import Image

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bridge2026secret-change-in-prod")

# Use absolute paths — works both locally and on any hosting
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
QR_DIR = os.path.join(BASE_DIR, "static", "qrcodes")
DB_PATH = os.path.join(BASE_DIR, "instance", "bridge.db")

# Create folders if they don't exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB max upload

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

db = SQLAlchemy(app)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Models ────────────────────────────────────────────────────────────────────

class Attendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    linkedin = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    photo = db.Column(db.String(200), nullable=True)
    qr_code = db.Column(db.String(200), nullable=True)
    qr_base64 = db.Column(db.Text, nullable=True)

class Masterclass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    speaker = db.Column(db.String(120), nullable=False)
    time_slot = db.Column(db.String(60), nullable=False)
    room = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text, nullable=False)
    takeaway = db.Column(db.String(300), nullable=True)
    video_url = db.Column(db.String(300), nullable=True)

# ── Mobile-optimized photo handling ───────────────────────────────────────────

def compress_and_save_photo(file):
    """Compress and save mobile photos - optimized for phone uploads"""
    try:
        # Check if file exists
        if not file or file.filename == '':
            return None
            
        logger.info(f"Processing photo: {file.filename}")
        
        # Read the image
        img = Image.open(file)
        
        # Fix orientation for mobile photos
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except:
            # Manual orientation fix
            if hasattr(img, '_getexif') and img._getexif():
                exif = img._getexif()
                if exif:
                    orientation = exif.get(0x0112, 1)
                    if orientation == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation == 8:
                        img = img.rotate(90, expand=True)
        
        # Convert to RGB
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                rgb_img.paste(img, mask=img.split()[-1])
            else:
                rgb_img.paste(img)
            img = rgb_img
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize for mobile (max 1200px)
        max_dimension = 1200
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Compress to max 1MB
        quality = 85
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        size = buffer.tell()
        
        # Reduce quality if still too large
        max_size_bytes = 1 * 1024 * 1024  # 1MB max
        while size > max_size_bytes and quality > 30:
            quality -= 10
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            size = buffer.tell()
        
        # Generate filename and save
        fname = f"{uuid.uuid4().hex}.jpg"
        dest_path = os.path.join(UPLOAD_DIR, fname)
        
        with open(dest_path, 'wb') as f:
            f.write(buffer.getvalue())
        
        logger.info(f"Photo saved successfully: {fname}")
        return f"uploads/{fname}"
        
    except Exception as e:
        logger.error(f"Photo processing failed: {e}", exc_info=True)
        return None

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

# ── QR Code handling ─────────────────────────────────────────────────────────

def generate_qr_file(linkedin_url, stem):
    """Generate a QR code PNG and return its path relative to static/"""
    try:
        os.makedirs(QR_DIR, exist_ok=True)
        
        qr = qrcode.QRCode(
            version=1,
            box_size=8,
            border=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H
        )
        qr.add_data(linkedin_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0A2540", back_color="white")
        
        dest = os.path.join(QR_DIR, f"{stem}.png")
        img.save(dest)
        logger.info(f"QR saved to {dest}")
        return f"qrcodes/{stem}.png"
    except Exception as e:
        logger.error(f"QR file generation failed: {e}", exc_info=True)
        return None

def generate_qr_base64(linkedin_url):
    """Generate QR code as base64 string"""
    try:
        qr = qrcode.QRCode(
            version=1,
            box_size=8,
            border=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H
        )
        qr.add_data(linkedin_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0A2540", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_base64}"
        
    except Exception as e:
        logger.error(f"QR base64 generation failed: {e}", exc_info=True)
        return None

def seed_masterclasses():
    if Masterclass.query.count() == 0:
        sessions = [
            Masterclass(
                title="AI Diagnostics in Clinical Practice",
                speaker="Dr. Sana Rekik",
                time_slot="10:00 – 11:30",
                room="Salle Atlas",
                description="Discover how machine learning models are reshaping radiology and pathology workflows.",
                takeaway="Deploy AI tools that assist — not replace — the clinician.",
                video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
            ),
            Masterclass(
                title="Health Data Monetisation & Compliance",
                speaker="Me. Amine Hamdi",
                time_slot="13:00 – 14:30",
                room="Salle Médina",
                description="Learn the legal frameworks and technical architecture for healthcare data.",
                takeaway="Structure a compliant, investor-ready health data product.",
                video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
            ),
            Masterclass(
                title="Digital Therapeutics & Remote Patient Monitoring",
                speaker="Dr. Mohamed Ben Salah",
                time_slot="15:00 – 16:30",
                room="Salle Carthage",
                description="Explore the rapidly growing market of prescription digital therapeutics.",
                takeaway="Identify the top 3 digital therapeutic categories.",
                video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
            ),
        ]
        db.session.add_all(sessions)
        db.session.commit()
        logger.info("Masterclasses seeded.")

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    attendees = Attendee.query.order_by(Attendee.id.desc()).all()
    masterclasses = Masterclass.query.all()
    
    # Prepare QR code display for each attendee
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
    return render_template("index.html", attendees=attendees,
                           masterclasses=masterclasses, counts=counts)

@app.route("/add", methods=["POST"])
def add_attendee():
    name = request.form.get("name", "").strip()
    linkedin = request.form.get("linkedin", "").strip()
    category = request.form.get("category", "participant").strip()

    if not name or not linkedin:
        flash("Le nom et l'URL LinkedIn sont obligatoires.", "error")
        return redirect(url_for("index"))

    # Normalise LinkedIn URL
    if not linkedin.startswith("http"):
        linkedin = "https://" + linkedin

    # Handle photo upload with mobile support
    photo_path = None
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename != '':
            photo_path = compress_and_save_photo(file)
            if not photo_path:
                flash("La photo n'a pas pu être traitée. L'utilisateur a été ajouté sans photo.", "warning")

    # Generate QR code
    qr_path = generate_qr_file(linkedin, uuid.uuid4().hex)
    qr_base64 = None
    
    if not qr_path:
        qr_base64 = generate_qr_base64(linkedin)
        if not qr_base64:
            flash("QR code generation failed. Check server logs.", "error")
            return redirect(url_for("index"))

    attendee = Attendee(
        name=name, 
        linkedin=linkedin,
        category=category, 
        photo=photo_path, 
        qr_code=qr_path,
        qr_base64=qr_base64
    )
    db.session.add(attendee)
    db.session.commit()
    flash(f"{name} a été ajouté(e) au répertoire !", "success")
    return redirect(url_for("index"))

@app.route("/masterclasses")
def masterclasses():
    sessions = Masterclass.query.all()
    return render_template("masterclasses.html", masterclasses=sessions)

@app.route("/delete/<int:id>", methods=["POST"])
def delete_attendee(id):
    a = Attendee.query.get_or_404(id)
    if a.photo:
        full = os.path.join(BASE_DIR, "static", a.photo)
        if os.path.exists(full):
            os.remove(full)
    if a.qr_code:
        full = os.path.join(BASE_DIR, "static", a.qr_code)
        if os.path.exists(full):
            os.remove(full)
    db.session.delete(a)
    db.session.commit()
    flash("Participant supprimé.", "info")
    return redirect(url_for("index"))

# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(413)
def too_large(e):
    flash("Fichier trop volumineux. Maximum 20 MB.", "error")
    return redirect(url_for("index"))

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500 error: {e}")
    return "Internal server error. Check logs.", 500

# ── Init ──────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    seed_masterclasses()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)