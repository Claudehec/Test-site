#!/usr/bin/env python3
"""ONECCA Directory API Server — FastAPI on port 8000."""
import uvicorn
import sqlite3
import json
import hashlib
import os
import secrets
import jwt
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ===== CONFIGURATION =====
PORT = int(os.environ.get("PORT", 8000))
JWT_SECRET = os.environ.get("JWT_SECRET", "your-super-secret-jwt-key-change-this-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days

DB_PATH = os.path.join(os.path.dirname(__file__), "onecca.db")
DATA_PATH = os.path.join(os.path.dirname(__file__), "onecca_data.json")  # Fixed path

ADMIN_PASSWORD = "ONECCA2026"

# ===== DATABASE =====
def get_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_db(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT NOT NULL,
            num INTEGER,
            nom TEXT NOT NULL,
            inscription_num TEXT DEFAULT '',
            inscription_date TEXT DEFAULT '',
            bp TEXT DEFAULT '',
            tel1 TEXT DEFAULT '',
            tel2 TEXT DEFAULT '',
            email TEXT DEFAULT '',
            adresse TEXT DEFAULT '',
            ville TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS contact_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            entreprise TEXT DEFAULT '',
            email TEXT NOT NULL,
            telephone TEXT DEFAULT '',
            commentaire TEXT DEFAULT '',
            lu INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            reset_token TEXT,
            reset_token_expiry TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- User sessions for JWT tokens
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Access requests for member contact details
        CREATE TABLE IF NOT EXISTS contact_access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            member_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_method TEXT,
            payment_amount REAL,
            payment_reference TEXT,
            payment_date TIMESTAMP,
            approved_by INTEGER,
            approved_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (approved_by) REFERENCES users(id)
        );

        -- Payment records
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'XAF',
            method TEXT,
            reference TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            member_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Pricing configuration
        CREATE TABLE IF NOT EXISTS pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT DEFAULT 'XAF',
            description TEXT,
            is_active INTEGER DEFAULT 1
        );
    """)
    db.commit()

def seed_data(db):
    """Import initial data from JSON if members table is empty."""
    count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    if count > 0:
        return
    
    if not os.path.exists(DATA_PATH):
        return
    
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    for section, entries in data.items():
        for entry in entries:
            db.execute("""
                INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                section,
                entry.get("num", 0),
                entry.get("nom", ""),
                entry.get("inscription_num", ""),
                entry.get("inscription_date", ""),
                entry.get("bp", ""),
                entry.get("tel1", ""),
                entry.get("tel2", ""),
                entry.get("email", ""),
                entry.get("adresse", ""),
                entry.get("ville", "Autre"),
            ))
    
    # Set default: coordinates hidden
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('show_contacts', 'false')")
    
    # Set default pricing
    db.executescript("""
        INSERT OR IGNORE INTO pricing (item_type, price, description) VALUES 
            ('single_contact', 5000, 'Accès aux coordonnées d''un membre pour 30 jours'),
            ('monthly_subscription', 25000, 'Accès illimité à tous les membres pour 30 jours'),
            ('yearly_subscription', 250000, 'Accès illimité à tous les membres pour 1 an');
    """)
    db.commit()
    print(f"Seeded {sum(len(v) for v in data.values())} members")

db = get_db()
init_db(db)
seed_data(db)

# ===== LIFESPAN =====
@asynccontextmanager
async def lifespan(app):
    yield
    db.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ===== HELPER FUNCTIONS =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return secrets.token_urlsafe(32)

def create_jwt_token(user_id: int, email: str) -> str:
    """Create JWT token for user authentication"""
    expiry = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": expiry,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_current_user(authorization: str = Header(default="")) -> Optional[dict]:
    """Get current user from JWT token"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    token = authorization.replace("Bearer ", "")
    payload = verify_jwt_token(token)
    
    if not payload:
        return None
    
    # Verify user still exists
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, phone FROM users WHERE id = ?", (payload["user_id"],))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return None
    
    return dict(user)

def check_admin(auth: str):
    if auth != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Non autorisé")

def check_active_subscription(user_id: int) -> bool:
    """Check if user has an active subscription"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM contact_access_requests 
        WHERE user_id = ? AND status = 'approved' 
        AND expires_at > datetime('now')
        AND member_id = 0
        LIMIT 1
    """, (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# ===== PUBLIC ENDPOINTS =====

@app.get("/api/members")
def get_members():
    """Public: get all members. Contacts hidden based on settings."""
    show = db.execute("SELECT value FROM settings WHERE key='show_contacts'").fetchone()
    show_contacts = show and show[0] == 'true'
    
    rows = db.execute("SELECT * FROM members ORDER BY section, num").fetchall()
    result = {}
    for r in rows:
        section = r["section"]
        if section not in result:
            result[section] = []
        member = {
            "id": r["id"],
            "num": r["num"],
            "nom": r["nom"],
            "inscription_num": r["inscription_num"],
            "inscription_date": r["inscription_date"],
            "bp": r["bp"],
            "adresse": r["adresse"],
            "ville": r["ville"],
        }
        if show_contacts:
            member["tel1"] = r["tel1"]
            member["tel2"] = r["tel2"]
            member["email"] = r["email"]
        result[section] = result.get(section, [])
        result[section].append(member)
    
    return {"members": result, "show_contacts": show_contacts}

@app.get("/api/settings/show_contacts")
def get_show_contacts():
    row = db.execute("SELECT value FROM settings WHERE key='show_contacts'").fetchone()
    return {"show_contacts": row[0] == 'true' if row else False}

# ===== CONTACT FORM =====
class ContactRequest(BaseModel):
    nom: str
    entreprise: str = ""
    email: str
    telephone: str = ""
    commentaire: str = ""

@app.post("/api/contact", status_code=201)
def submit_contact(req: ContactRequest):
    if not req.nom.strip() or not req.email.strip():
        raise HTTPException(status_code=400, detail="Nom et email requis")
    db.execute("""
        INSERT INTO contact_requests (nom, entreprise, email, telephone, commentaire)
        VALUES (?, ?, ?, ?, ?)
    """, (req.nom.strip(), req.entreprise.strip(), req.email.strip(), req.telephone.strip(), req.commentaire.strip()))
    db.commit()
    return {"message": "Votre demande a bien été envoyée. Nous vous contacterons rapidement."}

# ===== AUTH ENDPOINTS =====

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

@app.post("/api/auth/register")
async def register(request: RegisterRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE email = ?", (request.email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
    
    password_hash = hash_password(request.password)
    cursor.execute("""
        INSERT INTO users (name, email, phone, password_hash)
        VALUES (?, ?, ?, ?)
    """, (request.name, request.email, request.phone, password_hash))
    
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {"success": True, "user_id": user_id}

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE email = ?", (request.email,))
    user = cursor.fetchone()
    
    if not user or user["password_hash"] != hash_password(request.password):
        conn.close()
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    # Create JWT token
    token = create_jwt_token(user["id"], user["email"])
    
    # Store session
    expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    cursor.execute("""
        INSERT INTO user_sessions (user_id, token, expires_at)
        VALUES (?, ?, ?)
    """, (user["id"], token, expires_at.isoformat()))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "phone": user["phone"]
        }
    }

@app.post("/api/auth/logout")
async def logout(authorization: str = Header(default="")):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return {"success": True}

@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return {"user": current_user}

# ===== ACCESS & PAYMENT ENDPOINTS =====

class AccessRequest(BaseModel):
    member_id: int
    member_name: str

class PaymentInitRequest(BaseModel):
    amount: float
    method: str
    phone_number: Optional[str] = None
    member_id: int

@app.post("/api/access/request")
async def request_contact_access(
    request: AccessRequest,
    current_user: dict = Depends(get_current_user)
):
    """Request access to a member's contact details"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if request already exists
    cursor.execute("""
        SELECT id, status FROM contact_access_requests 
        WHERE user_id = ? AND member_id = ? AND status IN ('pending', 'approved')
        AND (expires_at IS NULL OR expires_at > datetime('now'))
    """, (current_user["id"], request.member_id))
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        return {
            "exists": True,
            "request_id": existing["id"],
            "status": existing["status"],
            "message": "Une demande existe déjà"
        }
    
    # Create new request
    cursor.execute("""
        INSERT INTO contact_access_requests (user_id, member_id, member_name, status)
        VALUES (?, ?, ?, 'pending')
    """, (current_user["id"], request.member_id, request.member_name))
    
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "request_id": request_id,
        "status": "pending",
        "message": "Demande envoyée à l'administrateur"
    }

@app.get("/api/access/my-requests")
async def get_my_access_requests(current_user: dict = Depends(get_current_user)):
    """Get all access requests for current user"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM contact_access_requests 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    """, (current_user["id"],))
    
    requests = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"requests": requests}

@app.get("/api/access/check/{member_id}")
async def check_member_access(
    member_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Check if user has access to a member's contact details"""
    if not current_user:
        return {"has_access": False, "reason": "non_authentifie"}
    
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check individual access
    cursor.execute("""
        SELECT * FROM contact_access_requests 
        WHERE user_id = ? AND member_id = ? 
        AND status = 'approved' 
        AND expires_at > datetime('now')
        LIMIT 1
    """, (current_user["id"], member_id))
    
    access = cursor.fetchone()
    
    if access:
        conn.close()
        return {"has_access": True, "expires_at": access["expires_at"], "type": "single"}
    
    # Check subscription
    has_subscription = check_active_subscription(current_user["id"])
    conn.close()
    
    if has_subscription:
        return {"has_access": True, "subscription": True, "type": "subscription"}
    
    return {"has_access": False, "reason": "non_paye"}

@app.post("/api/payment/initiate")
async def initiate_payment(
    payment: PaymentInitRequest,
    current_user: dict = Depends(get_current_user)
):
    """Initiate a payment for access"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    # Generate unique reference
    import uuid
    reference = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO payments (user_id, amount, method, reference, status, member_id)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (current_user["id"], payment.amount, payment.method, reference, payment.member_id))
    
    payment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # For demo, return instructions
    return {
        "success": True,
        "reference": reference,
        "payment_id": payment_id,
        "instructions": "Veuillez contacter l'administrateur pour finaliser votre paiement. Référence: " + reference
    }

# ===== ADMIN ENDPOINTS =====

@app.post("/api/admin/login")
def admin_login(password: str = ""):
    if password == ADMIN_PASSWORD:
        return {"success": True}
    raise HTTPException(status_code=401, detail="Mot de passe incorrect")

@app.post("/api/admin/toggle_contacts")
def toggle_contacts(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    current = db.execute("SELECT value FROM settings WHERE key='show_contacts'").fetchone()
    new_val = 'false' if (current and current[0] == 'true') else 'true'
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('show_contacts', ?)", (new_val,))
    db.commit()
    return {"show_contacts": new_val == 'true'}

class MemberCreate(BaseModel):
    section: str
    nom: str
    inscription_num: str = ""
    inscription_date: str = ""
    bp: str = ""
    tel1: str = ""
    tel2: str = ""
    email: str = ""
    adresse: str = ""
    ville: str = "Autre"

@app.post("/api/admin/members", status_code=201)
def add_member(member: MemberCreate, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    max_num = db.execute("SELECT MAX(num) FROM members WHERE section=?", (member.section,)).fetchone()[0]
    new_num = (max_num or 0) + 1
    
    cur = db.execute("""
        INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (member.section, new_num, member.nom, member.inscription_num, member.inscription_date,
          member.bp, member.tel1, member.tel2, member.email, member.adresse, member.ville))
    db.commit()
    return {"id": cur.lastrowid, "num": new_num}

@app.put("/api/admin/members/{member_id}")
def update_member(member_id: int, member: MemberCreate, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    db.execute("""
        UPDATE members SET section=?, nom=?, inscription_num=?, inscription_date=?,
        bp=?, tel1=?, tel2=?, email=?, adresse=?, ville=?, updated_at=?
        WHERE id=?
    """, (member.section, member.nom, member.inscription_num, member.inscription_date,
          member.bp, member.tel1, member.tel2, member.email, member.adresse, member.ville,
          datetime.now().isoformat(), member_id))
    db.commit()
    return {"updated": member_id}

@app.delete("/api/admin/members/{member_id}")
def delete_member(member_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    db.execute("DELETE FROM members WHERE id=?", (member_id,))
    db.commit()
    return {"deleted": member_id}

@app.get("/api/admin/members")
def admin_get_members(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    rows = db.execute("SELECT * FROM members ORDER BY section, num").fetchall()
    result = {}
    for r in rows:
        section = r["section"]
        if section not in result:
            result[section] = []
        result[section].append(dict(r))
    return {"members": result}

@app.get("/api/admin/contacts")
def admin_get_contacts(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    rows = db.execute("SELECT * FROM contact_requests ORDER BY created_at DESC").fetchall()
    return {"contacts": [dict(r) for r in rows]}

@app.put("/api/admin/contacts/{contact_id}/read")
def mark_contact_read(contact_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    db.execute("UPDATE contact_requests SET lu=1 WHERE id=?", (contact_id,))
    db.commit()
    return {"marked_read": contact_id}

@app.delete("/api/admin/contacts/{contact_id}")
def delete_contact(contact_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    db.execute("DELETE FROM contact_requests WHERE id=?", (contact_id,))
    db.commit()
    return {"deleted": contact_id}

@app.get("/api/admin/access-requests")
def get_access_requests(x_admin_auth: str = Header(default="")):
    """Admin: get all pending access requests"""
    check_admin(x_admin_auth)
    
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT r.*, u.name as user_name, u.email as user_email
        FROM contact_access_requests r
        JOIN users u ON r.user_id = u.id
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
    """)
    
    requests = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"requests": requests}

@app.post("/api/admin/access-requests/{request_id}/approve")
def approve_access_request(
    request_id: int,
    x_admin_auth: str = Header(default="")
):
    """Admin: approve an access request"""
    check_admin(x_admin_auth)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get request to check if it's for a specific member or subscription
    cursor.execute("SELECT member_id FROM contact_access_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    
    # Set expiration (30 days for single, 30/365 for subscription)
    expires_at = "datetime('now', '+30 days')"
    
    cursor.execute(f"""
        UPDATE contact_access_requests 
        SET status = 'approved', 
            approved_at = datetime('now'),
            expires_at = {expires_at}
        WHERE id = ?
    """, (request_id,))
    
    conn.commit()
    conn.close()
    
    return {"success": True, "message": "Accès approuvé"}

@app.post("/api/admin/access-requests/{request_id}/reject")
def reject_access_request(
    request_id: int,
    x_admin_auth: str = Header(default="")
):
    """Admin: reject an access request"""
    check_admin(x_admin_auth)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE contact_access_requests 
        SET status = 'rejected' 
        WHERE id = ?
    """, (request_id,))
    conn.commit()
    conn.close()
    
    return {"success": True, "message": "Demande rejetée"}

@app.get("/api/admin/stats")
def admin_stats(x_admin_auth: str = Header(default="")):
    """Admin: get statistics"""
    check_admin(x_admin_auth)
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM users")
    users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) as total FROM contact_access_requests WHERE status = 'pending'")
    pending_requests = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) as total FROM contact_access_requests WHERE status = 'approved'")
    approved_requests = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) as total FROM contact_requests WHERE lu = 0")
    unread_contacts = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_users": users,
        "pending_access_requests": pending_requests,
        "approved_access_requests": approved_requests,
        "unread_contact_requests": unread_contacts
    }

# ===== STATIC FILES =====

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/index.html", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/auth.html", response_class=HTMLResponse)
async def serve_auth():
    try:
        with open("auth.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head><title>Authentification ONECCA</title><meta charset="UTF-8"></head>
        <body style="font-family:Arial;padding:20px">
        <h2>🔐 ONECCA - Authentification</h2>
        <p>Le fichier auth.html est en cours de préparation.</p>
        <p>Veuillez rafraîchir la page ou contacter l'administrateur.</p>
        <a href="/">← Retour à l'accueil</a>
        </body>
        </html>
        """)


# ===== STATIC FILES =====

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/index.html", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/auth.html", response_class=HTMLResponse)
async def serve_auth():
    try:
        with open("auth.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head><title>Authentification ONECCA</title><meta charset="UTF-8"></head>
        <body style="font-family:Arial;padding:20px;background:#021e79;display:flex;align-items:center;justify-content:center;min-height:100vh">
        <div style="background:white;padding:40px;border-radius:20px;text-align:center">
            <h2 style="color:#021e79">🔐 ONECCA</h2>
            <p>Page d'authentification en cours de chargement...</p>
            <a href="/" style="color:#ffbf00">← Retour</a>
        </div>
        </body>
        </html>
        """)

# Route pour la page admin
@app.get("/admin_login.html", response_class=HTMLResponse)
async def serve_admin_login():
    try:
        with open("admin_login.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback intégré si le fichier n'existe pas
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Administration - ONECCA</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #021e79 0%, #0a2d99 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }
                .admin-card {
                    background: white;
                    border-radius: 24px;
                    padding: 40px;
                    max-width: 400px;
                    width: 100%;
                    text-align: center;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.2);
                }
                .admin-icon {
                    width: 70px;
                    height: 70px;
                    background: linear-gradient(135deg, #ffbf00, #ffd633);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 20px;
                    font-size: 32px;
                }
                h1 { color: #021e79; margin-bottom: 8px; font-size: 24px; }
                .subtitle { color: #64748b; font-size: 14px; margin-bottom: 30px; }
                input {
                    width: 100%;
                    padding: 14px;
                    margin: 10px 0;
                    border: 2px solid #e2e8f0;
                    border-radius: 12px;
                    font-size: 14px;
                    outline: none;
                }
                input:focus { border-color: #ffbf00; box-shadow: 0 0 0 3px rgba(255,191,0,0.1); }
                button {
                    width: 100%;
                    padding: 14px;
                    background: #ffbf00;
                    color: #021e79;
                    border: none;
                    border-radius: 12px;
                    font-weight: 700;
                    font-size: 16px;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    margin-top: 10px;
                }
                button:hover { background: #e6ac00; transform: translateY(-2px); }
                .error {
                    background: #fee2e2;
                    color: #dc2626;
                    padding: 12px;
                    border-radius: 10px;
                    font-size: 13px;
                    margin-top: 15px;
                    display: none;
                }
                .error.show { display: block; }
                .back-link {
                    margin-top: 20px;
                    display: inline-block;
                    color: #94a3b8;
                    text-decoration: none;
                    font-size: 13px;
                }
                .back-link:hover { color: #ffbf00; }
            </style>
        </head>
        <body>
            <div class="admin-card">
                <div class="admin-icon">🔒</div>
                <h1>Accès Administrateur</h1>
                <p class="subtitle">ONECCA - Tableau de l'Ordre National</p>
                <input type="password" id="adminPassword" placeholder="Mot de passe administrateur" autofocus>
                <button onclick="loginAdmin()">Accéder au panneau</button>
                <div id="errorMsg" class="error"></div>
                <a href="/" class="back-link">← Retour à l'annuaire</a>
            </div>
            <script>
                async function loginAdmin() {
                    const password = document.getElementById('adminPassword').value;
                    const errorDiv = document.getElementById('errorMsg');
                    if (!password) {
                        errorDiv.textContent = 'Veuillez entrer le mot de passe';
                        errorDiv.classList.add('show');
                        return;
                    }
                    try {
                        const response = await fetch('/api/admin/login', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ password: password })
                        });
                        const data = await response.json();
                        if (data.success === true) {
                            window.location.href = '/?admin=ONECCA2026';
                        } else {
                            errorDiv.textContent = 'Mot de passe incorrect';
                            errorDiv.classList.add('show');
                        }
                    } catch (err) {
                        errorDiv.textContent = 'Erreur de connexion au serveur';
                        errorDiv.classList.add('show');
                    }
                }
                document.getElementById('adminPassword').addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') loginAdmin();
                });
            </script>
        </body>
        </html>
        """)



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
