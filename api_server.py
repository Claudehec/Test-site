#!/usr/bin/env python3
"""ONECCA Directory API Server — FastAPI on port 8000."""
import uvicorn
import json
import hashlib
import os
import secrets
import jwt
import uuid
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

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ONECCA2026")
DATA_PATH = os.path.join(os.path.dirname(__file__), "onecca_data.json")

# ===== DÉTECTION DU TYPE DE BASE DE DONNÉES =====
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # ===== MODE POSTGRESQL (Railway) =====
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    def get_db():
        """Connexion PostgreSQL"""
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    
    def init_db():
        """Initialiser PostgreSQL avec toutes les tables"""
        conn = get_db()
        cursor = conn.cursor()
        
        # Table des membres
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
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
            )
        """)
        
        # Table des paramètres
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Table des demandes de contact
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_requests (
                id SERIAL PRIMARY KEY,
                nom TEXT NOT NULL,
                entreprise TEXT DEFAULT '',
                email TEXT NOT NULL,
                telephone TEXT DEFAULT '',
                commentaire TEXT DEFAULT '',
                lu INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table des utilisateurs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                password_hash TEXT NOT NULL,
                reset_token TEXT,
                reset_token_expiry TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table des sessions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Table des demandes d'accès
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_access_requests (
                id SERIAL PRIMARY KEY,
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (approved_by) REFERENCES users(id)
            )
        """)
        
        # Table des paiements
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'XAF',
                method TEXT,
                reference TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                member_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Table des tarifs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pricing (
                id SERIAL PRIMARY KEY,
                item_type TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT DEFAULT 'XAF',
                description TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        conn.commit()
        
        # Insérer les données par défaut
        cursor.execute("SELECT COUNT(*) FROM pricing")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO pricing (item_type, price, description, is_active) VALUES 
                    ('single_contact', 5000, 'Accès aux coordonnées d''un membre pour 30 jours', 1),
                    ('monthly_subscription', 25000, 'Accès illimité à tous les membres pour 30 jours', 1),
                    ('yearly_subscription', 250000, 'Accès illimité à tous les membres pour 1 an', 1)
            """)
            print("✅ Tarifs par défaut insérés")
        
        cursor.execute("SELECT COUNT(*) FROM settings")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO settings (key, value) VALUES ('show_contacts', 'false')")
            print("✅ Paramètres par défaut insérés")
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Base de données PostgreSQL initialisée")
    
    def seed_data_from_json():
        """Importer les données depuis le fichier JSON"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM members")
        if cursor.fetchone()[0] == 0 and os.path.exists(DATA_PATH):
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for section, entries in data.items():
                for entry in entries:
                    cursor.execute("""
                        INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            conn.commit()
            print(f"✅ {sum(len(v) for v in data.values())} membres importés")
        
        cursor.close()
        conn.close()

else:
    # ===== MODE SQLITE (Local) =====
    import sqlite3
    
    DB_PATH = os.path.join(os.path.dirname(__file__), "onecca.db")
    
    def get_db():
        db = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db
    
    def init_db():
        db = get_db()
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

            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

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
        
        # Insérer les données par défaut
        cursor = db.execute("SELECT COUNT(*) FROM pricing")
        if cursor.fetchone()[0] == 0:
            db.executescript("""
                INSERT INTO pricing (item_type, price, description, is_active) VALUES 
                    ('single_contact', 5000, 'Accès aux coordonnées d''un membre pour 30 jours', 1),
                    ('monthly_subscription', 25000, 'Accès illimité à tous les membres pour 30 jours', 1),
                    ('yearly_subscription', 250000, 'Accès illimité à tous les membres pour 1 an', 1)
            """)
        
        cursor = db.execute("SELECT COUNT(*) FROM settings")
        if cursor.fetchone()[0] == 0:
            db.execute("INSERT INTO settings (key, value) VALUES ('show_contacts', 'false')")
        
        db.commit()
        db.close()
        print("✅ Base de données SQLite initialisée")
    
    def seed_data_from_json():
        """Importer les données depuis JSON pour SQLite"""
        db = get_db()
        cursor = db.execute("SELECT COUNT(*) FROM members")
        if cursor.fetchone()[0] == 0 and os.path.exists(DATA_PATH):
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
            db.commit()
            print(f"✅ {sum(len(v) for v in data.values())} membres importés")
        db.close()

# Initialisation
init_db()
seed_data_from_json()

# ===== LIFESPAN =====
@asynccontextmanager
async def lifespan(app):
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ===== HELPER FUNCTIONS =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return secrets.token_urlsafe(32)

def create_jwt_token(user_id: int, email: str) -> str:
    expiry = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    payload = {"user_id": user_id, "email": email, "exp": expiry, "iat": datetime.utcnow()}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def get_current_user(authorization: str = Header(default="")) -> Optional[dict]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    token = authorization.replace("Bearer ", "")
    payload = verify_jwt_token(token)
    
    if not payload:
        return None
    
    conn = get_db()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        cursor.execute("SELECT id, name, email, phone FROM users WHERE id = %s", (payload["user_id"],))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {"id": user[0], "name": user[1], "email": user[2], "phone": user[3]}
    else:
        cursor.execute("SELECT id, name, email, phone FROM users WHERE id = ?", (payload["user_id"],))
        user = cursor.fetchone()
        conn.close()
        if user:
            return dict(user)
    
    return None

def check_admin(auth: str):
    if auth != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Non autorisé")

def check_active_subscription(user_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        cursor.execute("""
            SELECT * FROM contact_access_requests 
            WHERE user_id = %s AND status = 'approved' 
            AND expires_at > NOW() AND member_id = 0
            LIMIT 1
        """, (user_id,))
    else:
        cursor.execute("""
            SELECT * FROM contact_access_requests 
            WHERE user_id = ? AND status = 'approved' 
            AND expires_at > datetime('now') AND member_id = 0
            LIMIT 1
        """, (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    return result is not None

# ===== PUBLIC ENDPOINTS =====

@app.get("/api/members")
def get_members():
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'show_contacts'")
        show_row = cursor.fetchone()
        show_contacts = show_row and show_row[0] == 'true'
        cursor.execute("SELECT * FROM members ORDER BY section, num")
        rows = cursor.fetchall()
        
        result = {}
        for r in rows:
            section = r[1]
            member = {
                "id": r[0], "num": r[2], "nom": r[3],
                "inscription_num": r[4], "inscription_date": r[5],
                "bp": r[6], "adresse": r[9], "ville": r[10],
            }
            if show_contacts:
                member["tel1"] = r[7]
                member["tel2"] = r[8]
                member["email"] = r[9]  # À ajuster selon votre structure
            if section not in result:
                result[section] = []
            result[section].append(member)
    else:
        show = conn.execute("SELECT value FROM settings WHERE key='show_contacts'").fetchone()
        show_contacts = show and show[0] == 'true'
        rows = conn.execute("SELECT * FROM members ORDER BY section, num").fetchall()
        
        result = {}
        for r in rows:
            section = r["section"]
            member = {
                "id": r["id"], "num": r["num"], "nom": r["nom"],
                "inscription_num": r["inscription_num"], "inscription_date": r["inscription_date"],
                "bp": r["bp"], "adresse": r["adresse"], "ville": r["ville"],
            }
            if show_contacts:
                member["tel1"] = r["tel1"]
                member["tel2"] = r["tel2"]
                member["email"] = r["email"]
            if section not in result:
                result[section] = []
            result[section].append(member)
    
    conn.close()
    return {"members": result, "show_contacts": show_contacts}

@app.get("/api/settings/show_contacts")
def get_show_contacts():
    conn = get_db()
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'show_contacts'")
        row = cursor.fetchone()
    else:
        row = conn.execute("SELECT value FROM settings WHERE key='show_contacts'").fetchone()
    conn.close()
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
    
    conn = get_db()
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO contact_requests (nom, entreprise, email, telephone, commentaire)
            VALUES (%s, %s, %s, %s, %s)
        """, (req.nom.strip(), req.entreprise.strip(), req.email.strip(), req.telephone.strip(), req.commentaire.strip()))
    else:
        conn.execute("""
            INSERT INTO contact_requests (nom, entreprise, email, telephone, commentaire)
            VALUES (?, ?, ?, ?, ?)
        """, (req.nom.strip(), req.entreprise.strip(), req.email.strip(), req.telephone.strip(), req.commentaire.strip()))
    
    conn.commit()
    conn.close()
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

@app.post("/api/auth/register")
async def register(request: RegisterRequest):
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (request.email,))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
        
        password_hash = hash_password(request.password)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (request.name, request.email, request.phone, password_hash))
        user_id = cursor.fetchone()[0]
    else:
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
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (request.email,))
        user = cursor.fetchone()
        
        if not user or user[4] != hash_password(request.password):
            conn.close()
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        token = create_jwt_token(user[0], user[2])
        expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
        cursor.execute("""
            INSERT INTO user_sessions (user_id, token, expires_at)
            VALUES (%s, %s, %s)
        """, (user[0], token, expires_at.isoformat()))
        
        user_data = {"id": user[0], "name": user[1], "email": user[2], "phone": user[3]}
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (request.email,))
        user = cursor.fetchone()
        
        if not user or user["password_hash"] != hash_password(request.password):
            conn.close()
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        token = create_jwt_token(user["id"], user["email"])
        expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
        cursor.execute("""
            INSERT INTO user_sessions (user_id, token, expires_at)
            VALUES (?, ?, ?)
        """, (user["id"], token, expires_at.isoformat()))
        
        user_data = {"id": user["id"], "name": user["name"], "email": user["email"], "phone": user["phone"]}
    
    conn.commit()
    conn.close()
    return {"success": True, "token": token, "user": user_data}

@app.post("/api/auth/logout")
async def logout(authorization: str = Header(default="")):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        conn = get_db()
        if DATABASE_URL:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE token = %s", (token,))
        else:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
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
async def request_contact_access(request: AccessRequest, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, status FROM contact_access_requests 
            WHERE user_id = %s AND member_id = %s AND status IN ('pending', 'approved')
            AND (expires_at IS NULL OR expires_at > NOW())
        """, (current_user["id"], request.member_id))
        existing = cursor.fetchone()
        
        if existing:
            conn.close()
            return {"exists": True, "request_id": existing[0], "status": existing[1], "message": "Une demande existe déjà"}
        
        cursor.execute("""
            INSERT INTO contact_access_requests (user_id, member_id, member_name, status)
            VALUES (%s, %s, %s, 'pending') RETURNING id
        """, (current_user["id"], request.member_id, request.member_name))
        request_id = cursor.fetchone()[0]
    else:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, status FROM contact_access_requests 
            WHERE user_id = ? AND member_id = ? AND status IN ('pending', 'approved')
            AND (expires_at IS NULL OR expires_at > datetime('now'))
        """, (current_user["id"], request.member_id))
        existing = cursor.fetchone()
        
        if existing:
            conn.close()
            return {"exists": True, "request_id": existing[0], "status": existing[1], "message": "Une demande existe déjà"}
        
        cursor.execute("""
            INSERT INTO contact_access_requests (user_id, member_id, member_name, status)
            VALUES (?, ?, ?, 'pending')
        """, (current_user["id"], request.member_id, request.member_name))
        request_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return {"success": True, "request_id": request_id, "status": "pending", "message": "Demande envoyée à l'administrateur"}

@app.get("/api/access/my-requests")
async def get_my_access_requests(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contact_access_requests WHERE user_id = %s ORDER BY created_at DESC", (current_user["id"],))
        rows = cursor.fetchall()
        requests = [{"id": r[0], "member_id": r[2], "member_name": r[3], "status": r[4], "created_at": str(r[11])} for r in rows]
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contact_access_requests WHERE user_id = ? ORDER BY created_at DESC", (current_user["id"],))
        requests = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {"requests": requests}

@app.get("/api/access/check/{member_id}")
async def check_member_access(member_id: int, current_user: dict = Depends(get_current_user)):
    if not current_user:
        return {"has_access": False, "reason": "non_authentifie"}
    
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM contact_access_requests 
            WHERE user_id = %s AND member_id = %s 
            AND status = 'approved' AND expires_at > NOW()
            LIMIT 1
        """, (current_user["id"], member_id))
        access = cursor.fetchone()
        
        if access:
            conn.close()
            return {"has_access": True, "expires_at": str(access[8]), "type": "single"}
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM contact_access_requests 
            WHERE user_id = ? AND member_id = ? 
            AND status = 'approved' AND expires_at > datetime('now')
            LIMIT 1
        """, (current_user["id"], member_id))
        access = cursor.fetchone()
        
        if access:
            conn.close()
            return {"has_access": True, "expires_at": access["expires_at"], "type": "single"}
    
    has_subscription = check_active_subscription(current_user["id"])
    conn.close()
    
    if has_subscription:
        return {"has_access": True, "subscription": True, "type": "subscription"}
    
    return {"has_access": False, "reason": "non_paye"}

@app.post("/api/payment/initiate")
async def initiate_payment(payment: PaymentInitRequest, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    reference = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payments (user_id, amount, method, reference, status, member_id)
            VALUES (%s, %s, %s, %s, 'pending', %s) RETURNING id
        """, (current_user["id"], payment.amount, payment.method, reference, payment.member_id))
        payment_id = cursor.fetchone()[0]
    else:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payments (user_id, amount, method, reference, status, member_id)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (current_user["id"], payment.amount, payment.method, reference, payment.member_id))
        payment_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return {"success": True, "reference": reference, "payment_id": payment_id, "instructions": "Veuillez contacter l'administrateur pour finaliser votre paiement. Référence: " + reference}

# ===== ADMIN ENDPOINTS =====

@app.post("/api/admin/login")
async def admin_login(request: Request):
    try:
        body = await request.json()
        password = body.get("password", "")
    except:
        password = ""
    
    if password == ADMIN_PASSWORD:
        return {"success": True}
    raise HTTPException(status_code=401, detail="Mot de passe incorrect")

@app.post("/api/admin/toggle_contacts")
def toggle_contacts(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'show_contacts'")
        current = cursor.fetchone()
        new_val = 'false' if (current and current[0] == 'true') else 'true'
        cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ('show_contacts', new_val))
    else:
        current = conn.execute("SELECT value FROM settings WHERE key='show_contacts'").fetchone()
        new_val = 'false' if (current and current[0] == 'true') else 'true'
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('show_contacts', ?)", (new_val,))
    
    conn.commit()
    conn.close()
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
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(num) FROM members WHERE section = %s", (member.section,))
        max_num = cursor.fetchone()[0]
        new_num = (max_num or 0) + 1
        cursor.execute("""
            INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (member.section, new_num, member.nom, member.inscription_num, member.inscription_date,
              member.bp, member.tel1, member.tel2, member.email, member.adresse, member.ville))
        member_id = cursor.fetchone()[0]
    else:
        max_num = conn.execute("SELECT MAX(num) FROM members WHERE section=?", (member.section,)).fetchone()[0]
        new_num = (max_num or 0) + 1
        cursor = conn.execute("""
            INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (member.section, new_num, member.nom, member.inscription_num, member.inscription_date,
              member.bp, member.tel1, member.tel2, member.email, member.adresse, member.ville))
        member_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return {"id": member_id, "num": new_num}

@app.put("/api/admin/members/{member_id}")
def update_member(member_id: int, member: MemberCreate, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE members SET section=%s, nom=%s, inscription_num=%s, inscription_date=%s,
            bp=%s, tel1=%s, tel2=%s, email=%s, adresse=%s, ville=%s, updated_at=%s
            WHERE id=%s
        """, (member.section, member.nom, member.inscription_num, member.inscription_date,
              member.bp, member.tel1, member.tel2, member.email, member.adresse, member.ville,
              datetime.now().isoformat(), member_id))
    else:
        conn.execute("""
            UPDATE members SET section=?, nom=?, inscription_num=?, inscription_date=?,
            bp=?, tel1=?, tel2=?, email=?, adresse=?, ville=?, updated_at=?
            WHERE id=?
        """, (member.section, member.nom, member.inscription_num, member.inscription_date,
              member.bp, member.tel1, member.tel2, member.email, member.adresse, member.ville,
              datetime.now().isoformat(), member_id))
    
    conn.commit()
    conn.close()
    return {"updated": member_id}

@app.delete("/api/admin/members/{member_id}")
def delete_member(member_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM members WHERE id = %s", (member_id,))
    else:
        conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    
    conn.commit()
    conn.close()
    return {"deleted": member_id}

@app.get("/api/admin/members")
def admin_get_members(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM members ORDER BY section, num")
        rows = cursor.fetchall()
        result = {}
        for r in rows:
            section = r[1]
            if section not in result:
                result[section] = []
            result[section].append(dict(zip(['id', 'section', 'num', 'nom', 'inscription_num', 'inscription_date', 'bp', 'tel1', 'tel2', 'email', 'adresse', 'ville', 'created_at', 'updated_at'], r)))
    else:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM members ORDER BY section, num").fetchall()
        result = {}
        for r in rows:
            section = r["section"]
            if section not in result:
                result[section] = []
            result[section].append(dict(r))
    
    conn.close()
    return {"members": result}

@app.get("/api/admin/contacts")
def admin_get_contacts(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contact_requests ORDER BY created_at DESC")
        rows = cursor.fetchall()
        contacts = [dict(zip(['id', 'nom', 'entreprise', 'email', 'telephone', 'commentaire', 'lu', 'created_at'], r)) for r in rows]
    else:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM contact_requests ORDER BY created_at DESC").fetchall()
        contacts = [dict(r) for r in rows]
    
    conn.close()
    return {"contacts": contacts}

@app.put("/api/admin/contacts/{contact_id}/read")
def mark_contact_read(contact_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("UPDATE contact_requests SET lu = 1 WHERE id = %s", (contact_id,))
    else:
        conn.execute("UPDATE contact_requests SET lu=1 WHERE id=?", (contact_id,))
    
    conn.commit()
    conn.close()
    return {"marked_read": contact_id}

@app.delete("/api/admin/contacts/{contact_id}")
def delete_contact(contact_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM contact_requests WHERE id = %s", (contact_id,))
    else:
        conn.execute("DELETE FROM contact_requests WHERE id=?", (contact_id,))
    
    conn.commit()
    conn.close()
    return {"deleted": contact_id}

@app.get("/api/admin/access-requests")
def get_access_requests(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, u.name as user_name, u.email as user_email
            FROM contact_access_requests r
            JOIN users u ON r.user_id = u.id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        """)
        rows = cursor.fetchall()
        columns = ['id', 'user_id', 'member_id', 'member_name', 'status', 'payment_method', 'payment_amount', 'payment_reference', 'payment_date', 'approved_by', 'approved_at', 'expires_at', 'created_at']
        requests = []
        for r in rows:
            req = dict(zip(columns, r[:13]))
            req['user_name'] = r[13]
            req['user_email'] = r[14]
            requests.append(req)
    else:
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
def approve_access_request(request_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE contact_access_requests 
            SET status = 'approved', approved_at = NOW(), expires_at = NOW() + INTERVAL '30 days'
            WHERE id = %s
        """, (request_id,))
    else:
        conn.execute("""
            UPDATE contact_access_requests 
            SET status = 'approved', approved_at = datetime('now'), expires_at = datetime('now', '+30 days')
            WHERE id = ?
        """, (request_id,))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": "Accès approuvé"}

@app.post("/api/admin/access-requests/{request_id}/reject")
def reject_access_request(request_id: int, x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("UPDATE contact_access_requests SET status = 'rejected' WHERE id = %s", (request_id,))
    else:
        conn.execute("UPDATE contact_access_requests SET status = 'rejected' WHERE id = ?", (request_id,))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": "Demande rejetée"}

@app.get("/api/admin/stats")
def admin_stats(x_admin_auth: str = Header(default="")):
    check_admin(x_admin_auth)
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM contact_access_requests WHERE status = 'pending'")
        pending_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM contact_access_requests WHERE status = 'approved'")
        approved_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM contact_requests WHERE lu = 0")
        unread_contacts = cursor.fetchone()[0]
    else:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pending_requests = conn.execute("SELECT COUNT(*) FROM contact_access_requests WHERE status = 'pending'").fetchone()[0]
        approved_requests = conn.execute("SELECT COUNT(*) FROM contact_access_requests WHERE status = 'approved'").fetchone()[0]
        unread_contacts = conn.execute("SELECT COUNT(*) FROM contact_requests WHERE lu = 0").fetchone()[0]
    
    conn.close()
    return {
        "total_users": users,
        "pending_access_requests": pending_requests,
        "approved_access_requests": approved_requests,
        "unread_contact_requests": unread_contacts
    }

# ===== USER DASHBOARD ENDPOINTS =====

@app.get("/api/user/dashboard")
async def get_user_dashboard(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, m.nom as member_nom, m.ville as member_ville
            FROM contact_access_requests r
            LEFT JOIN members m ON r.member_id = m.id
            WHERE r.user_id = %s
            ORDER BY r.created_at DESC
        """, (current_user["id"],))
        access_requests_rows = cursor.fetchall()
        access_requests = []
        for r in access_requests_rows:
            req = {
                "id": r[0], "user_id": r[1], "member_id": r[2], "member_name": r[3],
                "status": r[4], "expires_at": str(r[11]) if r[11] else None, "created_at": str(r[12]),
                "member_nom": r[13], "member_ville": r[14]
            }
            access_requests.append(req)
        
        cursor.execute("SELECT * FROM payments WHERE user_id = %s ORDER BY created_at DESC", (current_user["id"],))
        payments_rows = cursor.fetchall()
        payments = [{"id": r[0], "amount": r[2], "method": r[4], "reference": r[5], "status": r[6], "created_at": str(r[9])} for r in payments_rows]
        
        cursor.execute("""
            SELECT * FROM contact_access_requests 
            WHERE user_id = %s AND status = 'approved' AND expires_at > NOW() AND member_id = 0
            ORDER BY expires_at DESC LIMIT 1
        """, (current_user["id"],))
        active_subscription_row = cursor.fetchone()
        active_subscription = None
        if active_subscription_row:
            active_subscription = {"id": active_subscription_row[0], "expires_at": str(active_subscription_row[11])}
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, m.nom as member_nom, m.ville as member_ville
            FROM contact_access_requests r
            LEFT JOIN members m ON r.member_id = m.id
            WHERE r.user_id = ?
            ORDER BY r.created_at DESC
        """, (current_user["id"],))
        access_requests = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC", (current_user["id"],))
        payments = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT * FROM contact_access_requests 
            WHERE user_id = ? AND status = 'approved' AND expires_at > datetime('now') AND member_id = 0
            ORDER BY expires_at DESC LIMIT 1
        """, (current_user["id"],))
        active_subscription_row = cursor.fetchone()
        active_subscription = dict(active_subscription_row) if active_subscription_row else None
    
    stats = {
        "total_requests": len(access_requests),
        "pending_requests": len([r for r in access_requests if r["status"] == "pending"]),
        "approved_requests": len([r for r in access_requests if r["status"] == "approved"]),
        "rejected_requests": len([r for r in access_requests if r["status"] == "rejected"]),
        "total_paid": sum([p["amount"] for p in payments if p["status"] == "completed"]),
        "has_active_subscription": active_subscription is not None,
        "subscription_expires_at": active_subscription["expires_at"] if active_subscription else None
    }
    
    conn.close()
    return {
        "user": current_user,
        "stats": stats,
        "access_requests": access_requests,
        "payments": payments,
        "active_subscription": active_subscription
    }

@app.get("/api/user/access-requests")
async def get_user_access_requests(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, m.nom as member_nom
            FROM contact_access_requests r
            LEFT JOIN members m ON r.member_id = m.id
            WHERE r.user_id = %s
            ORDER BY r.created_at DESC
        """, (current_user["id"],))
        rows = cursor.fetchall()
        requests = []
        for r in rows:
            req = {"id": r[0], "member_id": r[2], "member_name": r[3], "status": r[4], "created_at": str(r[12]), "member_nom": r[13]}
            requests.append(req)
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, m.nom as member_nom
            FROM contact_access_requests r
            LEFT JOIN members m ON r.member_id = m.id
            WHERE r.user_id = ?
            ORDER BY r.created_at DESC
        """, (current_user["id"],))
        requests = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {"requests": requests}

@app.get("/api/user/payments")
async def get_user_payments(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    
    conn = get_db()
    
    if DATABASE_URL:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments WHERE user_id = %s ORDER BY created_at DESC", (current_user["id"],))
        rows = cursor.fetchall()
        payments = [{"id": r[0], "amount": r[2], "method": r[4], "reference": r[5], "status": r[6], "created_at": str(r[9])} for r in rows]
    else:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC", (current_user["id"],))
        payments = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {"payments": payments}

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
        return HTMLResponse(content="""<!DOCTYPE html><html><head><title>Authentification ONECCA</title></head><body><h2>🔐 ONECCA</h2><p>Page d'authentification en cours de chargement...</p><a href="/">← Retour</a></body></html>""")

@app.get("/admin_login.html", response_class=HTMLResponse)
async def serve_admin_login():
    try:
        with open("admin_login.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="""<!DOCTYPE html><html><head><title>Admin ONECCA</title><style>body{background:linear-gradient(135deg,#021e79,#0a2d99);display:flex;justify-content:center;align-items:center;min-height:100vh}.admin-card{background:white;border-radius:24px;padding:40px;max-width:400px;text-align:center}h1{color:#021e79}input{padding:14px;margin:10px 0;border:2px solid #e2e8f0;border-radius:12px;width:100%}button{padding:14px;background:#ffbf00;border:none;border-radius:12px;font-weight:bold;cursor:pointer}</style></head><body><div class=admin-card><h1>Accès Administrateur</h1><input type=password id=adminPassword placeholder="Mot de passe"><button onclick="fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('adminPassword').value})}).then(r=>r.json()).then(d=>{if(d.success)window.location.href='/?admin=ONECCA2026';else alert('Mot de passe incorrect')})">Accéder</button><a href="/">← Retour</a></div></body></html>""")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
