import os, uuid, logging
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import qrcode
#ed

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bridge2026secret-change-in-prod")

# Use absolute paths — works both locally and on any hosting
BASE_DIR    = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR  = os.path.join(BASE_DIR, "static", "uploads")
QR_DIR      = os.path.join(BASE_DIR, "static", "qrcodes")
DB_PATH     = os.path.join(BASE_DIR, "instance", "bridge.db")

# Create folders if they don't exist (important on first deploy)
os.makedirs(UPLOAD_DIR,  exist_ok=True)
os.makedirs(QR_DIR,      exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"]        = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"]             = 8 * 1024 * 1024   # 8 MB max upload

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

db = SQLAlchemy(app)

# Set up logging so errors show in hosting logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Models ────────────────────────────────────────────────────────────────────

class Attendee(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(120), nullable=False)
    linkedin = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(30),  nullable=False)
    photo    = db.Column(db.String(200), nullable=True)
    qr_code  = db.Column(db.String(200), nullable=True)

class Masterclass(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    speaker     = db.Column(db.String(120), nullable=False)
    time_slot   = db.Column(db.String(60),  nullable=False)
    room        = db.Column(db.String(60),  nullable=False)
    description = db.Column(db.Text,        nullable=False)
    takeaway    = db.Column(db.String(300), nullable=True)
    video_url   = db.Column(db.String(300), nullable=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def generate_qr(linkedin_url, stem):
    """Generate a QR code PNG and return its path relative to static/"""
    try:
        qr = qrcode.QRCode(
            version=1,
            box_size=8,
            border=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H
        )
        qr.add_data(linkedin_url)
        qr.make(fit=True)
        img  = qr.make_image(fill_color="#0A2540", back_color="white")
        # Save using absolute path
        dest = os.path.join(QR_DIR, f"{stem}.png")
        img.save(dest)
        logger.info(f"QR saved to {dest}")
        return f"qrcodes/{stem}.png"   # relative to static/ for url_for
    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        raise

def seed_masterclasses():
    if Masterclass.query.count() == 0:
        sessions = [
            Masterclass(
                title="AI Diagnostics in Clinical Practice",
                speaker="Dr. Sana Rekik",
                time_slot="10:00 – 11:30",
                room="Salle Atlas",
                description=(
                    "Discover how machine learning models are reshaping radiology and pathology workflows. "
                    "This session covers real-world deployments in MENA hospitals, model interpretability, "
                    "and the practical steps to integrate AI tools into existing clinical pipelines without "
                    "disrupting patient care."
                ),
                takeaway="Deploy AI tools that assist — not replace — the clinician, with measurable outcomes.",
                video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
            ),
            Masterclass(
                title="Health Data Monetisation & Compliance",
                speaker="Me. Amine Hamdi",
                time_slot="13:00 – 14:30",
                room="Salle Médina",
                description=(
                    "Learn the legal frameworks and technical architecture that allow healthcare startups to "
                    "commercialise patient data while fully meeting GDPR and Tunisian law requirements. "
                    "Includes a step-by-step blueprint for building a compliant data product from scratch."
                ),
                takeaway="Structure a compliant, investor-ready health data product in 3 actionable steps.",
                video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
            ),
            Masterclass(
                title="Digital Therapeutics & Remote Patient Monitoring",
                speaker="Dr. Mohamed Ben Salah",
                time_slot="15:00 – 16:30",
                room="Salle Carthage",
                description=(
                    "Explore the rapidly growing market of prescription digital therapeutics (PDTs) and "
                    "connected devices for remote monitoring. Learn which chronic disease areas show the "
                    "strongest ROI, and how Tunisian startups can position themselves in the EU and Gulf markets."
                ),
                takeaway="Identify the top 3 digital therapeutic categories with a validated path to reimbursement.",
                video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
            ),
        ]
        db.session.add_all(sessions)
        db.session.commit()
        logger.info("Masterclasses seeded.")

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    attendees     = Attendee.query.order_by(Attendee.id.desc()).all()
    masterclasses = Masterclass.query.all()
    counts = {
        "total":       Attendee.query.count(),
        "masterclass": Attendee.query.filter_by(category="masterclass").count(),
        "vip":         Attendee.query.filter_by(category="vip").count(),
        "participant": Attendee.query.filter_by(category="participant").count(),
    }
    return render_template("index.html", attendees=attendees,
                           masterclasses=masterclasses, counts=counts)

@app.route("/add", methods=["POST"])
def add_attendee():
    name     = request.form.get("name", "").strip()
    linkedin = request.form.get("linkedin", "").strip()
    category = request.form.get("category", "participant").strip()

    if not name or not linkedin:
        flash("Le nom et l'URL LinkedIn sont obligatoires.", "error")
        return redirect(url_for("index"))

    # Normalise LinkedIn URL
    if not linkedin.startswith("http"):
        linkedin = "https://" + linkedin

    # Photo upload — absolute path save
    photo_path = None
    file = request.files.get("photo")
    if file and file.filename and allowed_file(file.filename):
        try:
            ext   = secure_filename(file.filename).rsplit(".", 1)[1].lower()
            fname = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(UPLOAD_DIR, fname))   # ← absolute path
            photo_path = f"uploads/{fname}"
            logger.info(f"Photo saved: {fname}")
        except Exception as e:
            logger.error(f"Photo upload failed: {e}")
            flash("Photo upload failed — attendee added without photo.", "info")

    # QR code — absolute path save
    try:
        qr_path = generate_qr(linkedin, uuid.uuid4().hex)
    except Exception as e:
        logger.error(f"QR failed: {e}")
        flash("QR code generation failed. Check server logs.", "error")
        return redirect(url_for("index"))

    attendee = Attendee(name=name, linkedin=linkedin,
                        category=category, photo=photo_path, qr_code=qr_path)
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
    # Clean up files
    for rel_path in [a.photo, a.qr_code]:
        if rel_path:
            full = os.path.join(BASE_DIR, "static", rel_path)
            if os.path.exists(full):
                os.remove(full)
    db.session.delete(a)
    db.session.commit()
    flash("Participant supprimé.", "info")
    return redirect(url_for("index"))

# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(413)
def too_large(e):
    flash("Fichier trop volumineux. Maximum 8 MB.", "error")
    return redirect(url_for("index"))

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500 error: {e}")
    return render_template("500.html"), 500

# ── Init ──────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    seed_masterclasses()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
