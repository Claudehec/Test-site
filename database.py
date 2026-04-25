# database.py
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "onecca.db")

def get_db():
    """Obtenir une connexion à la base de données"""
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_database():
    """Initialiser toutes les tables de la base de données"""
    db = get_db()
    
    # 1. Table des membres (experts-comptables)
    db.execute("""
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
        )
    """)
    
    # 2. Table des paramètres
    db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # 3. Table des demandes de contact
    db.execute("""
        CREATE TABLE IF NOT EXISTS contact_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            entreprise TEXT DEFAULT '',
            email TEXT NOT NULL,
            telephone TEXT DEFAULT '',
            commentaire TEXT DEFAULT '',
            lu INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 4. Table des utilisateurs
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            reset_token TEXT,
            reset_token_expiry TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 5. Table des sessions utilisateur (tokens JWT)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # 6. Table des demandes d'accès aux coordonnées
    db.execute("""
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
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )
    """)
    
    # 7. Table des paiements
    db.execute("""
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
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # 8. Table des tarifs
    db.execute("""
        CREATE TABLE IF NOT EXISTS pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT DEFAULT 'XAF',
            description TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    db.commit()
    db.close()
    print("✅ Base de données initialisée avec succès")

def seed_default_data():
    """Insérer les données par défaut"""
    db = get_db()
    
    # Vérifier si les tarifs existent déjà
    cursor = db.execute("SELECT COUNT(*) FROM pricing")
    count = cursor.fetchone()[0]
    
    if count == 0:
        # Insérer les tarifs par défaut
        db.executescript("""
            INSERT INTO pricing (item_type, price, description, is_active) VALUES 
                ('single_contact', 5000, 'Accès aux coordonnées d''un membre pour 30 jours', 1),
                ('monthly_subscription', 25000, 'Accès illimité à tous les membres pour 30 jours', 1),
                ('yearly_subscription', 250000, 'Accès illimité à tous les membres pour 1 an', 1)
        """)
        print("✅ Tarifs par défaut insérés")
    
    # Vérifier si les paramètres existent
    cursor = db.execute("SELECT COUNT(*) FROM settings")
    count = cursor.fetchone()[0]
    
    if count == 0:
        # Insérer les paramètres par défaut
        db.execute("INSERT INTO settings (key, value) VALUES ('show_contacts', 'false')")
        print("✅ Paramètres par défaut insérés")
    
    db.commit()
    db.close()

# ===== FONCTIONS MEMBRES =====

def get_all_members(show_contacts: bool = False) -> Dict[str, List[Dict]]:
    """Récupérer tous les membres, avec ou sans coordonnées"""
    db = get_db()
    rows = db.execute("SELECT * FROM members ORDER BY section, num").fetchall()
    db.close()
    
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
        
        result[section].append(member)
    
    return result

def add_member(section: str, nom: str, **kwargs) -> int:
    """Ajouter un nouveau membre"""
    db = get_db()
    
    # Calculer le prochain numéro dans la section
    cursor = db.execute("SELECT MAX(num) FROM members WHERE section=?", (section,))
    max_num = cursor.fetchone()[0]
    new_num = (max_num or 0) + 1
    
    cursor = db.execute("""
        INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        section, new_num, nom,
        kwargs.get('inscription_num', ''),
        kwargs.get('inscription_date', ''),
        kwargs.get('bp', ''),
        kwargs.get('tel1', ''),
        kwargs.get('tel2', ''),
        kwargs.get('email', ''),
        kwargs.get('adresse', ''),
        kwargs.get('ville', 'Autre')
    ))
    
    member_id = cursor.lastrowid
    db.commit()
    db.close()
    return member_id

def update_member(member_id: int, **kwargs) -> bool:
    """Mettre à jour un membre"""
    db = get_db()
    
    fields = []
    values = []
    for key, value in kwargs.items():
        if key in ['section', 'nom', 'inscription_num', 'inscription_date', 'bp', 'tel1', 'tel2', 'email', 'adresse', 'ville']:
            fields.append(f"{key}=?")
            values.append(value)
    
    if not fields:
        db.close()
        return False
    
    values.append(datetime.now().isoformat())
    values.append(member_id)
    
    query = f"UPDATE members SET {', '.join(fields)}, updated_at=? WHERE id=?"
    db.execute(query, values)
    db.commit()
    db.close()
    return True

def delete_member(member_id: int) -> bool:
    """Supprimer un membre"""
    db = get_db()
    db.execute("DELETE FROM members WHERE id=?", (member_id,))
    db.commit()
    db.close()
    return True

# ===== FONCTIONS UTILISATEURS =====

import hashlib
import secrets
from datetime import datetime, timedelta

def hash_password(password: str) -> str:
    """Hacher un mot de passe"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(name: str, email: str, password: str, phone: str = "") -> Optional[int]:
    """Créer un nouvel utilisateur"""
    db = get_db()
    
    # Vérifier si l'email existe déjà
    cursor = db.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        db.close()
        return None
    
    password_hash = hash_password(password)
    cursor = db.execute("""
        INSERT INTO users (name, email, phone, password_hash)
        VALUES (?, ?, ?, ?)
    """, (name, email, phone, password_hash))
    
    user_id = cursor.lastrowid
    db.commit()
    db.close()
    return user_id

def authenticate_user(email: str, password: str) -> Optional[Dict]:
    """Authentifier un utilisateur"""
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    db.close()
    
    if user and user["password_hash"] == hash_password(password):
        return dict(user)
    return None

def create_session(user_id: int, duration_hours: int = 168) -> str:
    """Créer une session utilisateur (token JWT simplifié)"""
    import jwt
    
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=duration_hours)
    
    db = get_db()
    db.execute("""
        INSERT INTO user_sessions (user_id, token, expires_at)
        VALUES (?, ?, ?)
    """, (user_id, token, expires_at.isoformat()))
    db.commit()
    db.close()
    
    return token

def get_user_by_token(token: str) -> Optional[Dict]:
    """Récupérer un utilisateur par son token"""
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT u.* FROM users u
        JOIN user_sessions s ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > datetime('now')
    """, (token,))
    user = cursor.fetchone()
    db.close()
    
    return dict(user) if user else None

def delete_session(token: str) -> bool:
    """Supprimer une session (déconnexion)"""
    db = get_db()
    db.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    db.commit()
    db.close()
    return True

# ===== FONCTIONS DEMANDES D'ACCÈS =====

def create_access_request(user_id: int, member_id: int, member_name: str) -> int:
    """Créer une demande d'accès aux coordonnées"""
    db = get_db()
    cursor = db.execute("""
        INSERT INTO contact_access_requests (user_id, member_id, member_name, status)
        VALUES (?, ?, ?, 'pending')
    """, (user_id, member_id, member_name))
    request_id = cursor.lastrowid
    db.commit()
    db.close()
    return request_id

def get_pending_access_requests() -> List[Dict]:
    """Récupérer toutes les demandes d'accès en attente"""
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT r.*, u.name as user_name, u.email as user_email
        FROM contact_access_requests r
        JOIN users u ON r.user_id = u.id
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
    """)
    
    requests = [dict(row) for row in cursor.fetchall()]
    db.close()
    return requests

def approve_access_request(request_id: int, admin_id: int = None) -> bool:
    """Approuver une demande d'accès"""
    db = get_db()
    expires_at = datetime.now() + timedelta(days=30)
    
    db.execute("""
        UPDATE contact_access_requests 
        SET status = 'approved', 
            approved_by = ?,
            approved_at = datetime('now'),
            expires_at = ?
        WHERE id = ?
    """, (admin_id, expires_at.isoformat(), request_id))
    
    db.commit()
    db.close()
    return True

def reject_access_request(request_id: int) -> bool:
    """Rejeter une demande d'accès"""
    db = get_db()
    db.execute("UPDATE contact_access_requests SET status = 'rejected' WHERE id = ?", (request_id,))
    db.commit()
    db.close()
    return True

def check_user_access(user_id: int, member_id: int) -> bool:
    """Vérifier si un utilisateur a accès aux coordonnées d'un membre"""
    db = get_db()
    cursor = db.execute("""
        SELECT id FROM contact_access_requests 
        WHERE user_id = ? AND member_id = ? 
        AND status = 'approved' 
        AND expires_at > datetime('now')
        LIMIT 1
    """, (user_id, member_id))
    result = cursor.fetchone()
    db.close()
    return result is not None

def get_user_access_requests(user_id: int) -> List[Dict]:
    """Récupérer toutes les demandes d'accès d'un utilisateur"""
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT r.*, m.nom as member_nom
        FROM contact_access_requests r
        LEFT JOIN members m ON r.member_id = m.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
    """, (user_id,))
    
    requests = [dict(row) for row in cursor.fetchall()]
    db.close()
    return requests

# ===== FONCTIONS PAIEMENTS =====

def create_payment(user_id: int, amount: float, method: str, member_id: int = None) -> str:
    """Créer un paiement et retourner la référence"""
    import uuid
    reference = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    
    db = get_db()
    db.execute("""
        INSERT INTO payments (user_id, amount, method, reference, status, member_id)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (user_id, amount, method, reference, member_id))
    db.commit()
    db.close()
    return reference

def complete_payment(reference: str) -> bool:
    """Marquer un paiement comme complété"""
    db = get_db()
    db.execute("""
        UPDATE payments 
        SET status = 'completed', completed_at = datetime('now')
        WHERE reference = ?
    """, (reference,))
    db.commit()
    db.close()
    return True

def get_user_payments(user_id: int) -> List[Dict]:
    """Récupérer tous les paiements d'un utilisateur"""
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT * FROM payments 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    """, (user_id,))
    
    payments = [dict(row) for row in cursor.fetchall()]
    db.close()
    return payments

# ===== FONCTIONS PARAMÈTRES =====

def get_setting(key: str, default: str = None) -> str:
    """Récupérer un paramètre"""
    db = get_db()
    cursor = db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    db.close()
    return row[0] if row else default

def set_setting(key: str, value: str) -> bool:
    """Définir un paramètre"""
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()
    db.close()
    return True

# ===== FONCTIONS STATISTIQUES =====

def get_dashboard_stats(user_id: int) -> Dict:
    """Récupérer les statistiques pour le dashboard utilisateur"""
    requests = get_user_access_requests(user_id)
    payments = get_user_payments(user_id)
    
    # Vérifier l'abonnement actif
    db = get_db()
    cursor = db.execute("""
        SELECT * FROM contact_access_requests 
        WHERE user_id = ? AND status = 'approved' 
        AND expires_at > datetime('now') AND member_id = 0
        LIMIT 1
    """, (user_id,))
    active_subscription = cursor.fetchone()
    db.close()
    
    stats = {
        "total_requests": len(requests),
        "pending_requests": len([r for r in requests if r["status"] == "pending"]),
        "approved_requests": len([r for r in requests if r["status"] == "approved"]),
        "rejected_requests": len([r for r in requests if r["status"] == "rejected"]),
        "total_paid": sum([p["amount"] for p in payments if p["status"] == "completed"]),
        "has_active_subscription": active_subscription is not None,
        "subscription_expires_at": active_subscription["expires_at"] if active_subscription else None
    }
    
    return stats

# ===== FONCTIONS DE CONTACT =====

def add_contact_request(nom: str, email: str, entreprise: str = "", telephone: str = "", commentaire: str = "") -> int:
    """Ajouter une demande de contact"""
    db = get_db()
    cursor = db.execute("""
        INSERT INTO contact_requests (nom, entreprise, email, telephone, commentaire)
        VALUES (?, ?, ?, ?, ?)
    """, (nom, entreprise, email, telephone, commentaire))
    request_id = cursor.lastrowid
    db.commit()
    db.close()
    return request_id

def get_unread_contact_requests() -> List[Dict]:
    """Récupérer les demandes de contact non lues"""
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT * FROM contact_requests 
        WHERE lu = 0 
        ORDER BY created_at DESC
    """)
    
    requests = [dict(row) for row in cursor.fetchall()]
    db.close()
    return requests

def mark_contact_read(contact_id: int) -> bool:
    """Marquer une demande de contact comme lue"""
    db = get_db()
    db.execute("UPDATE contact_requests SET lu = 1 WHERE id = ?", (contact_id,))
    db.commit()
    db.close()
    return True

# ===== INITIALISATION =====

if __name__ == "__main__":
    # Test de la base de données
    init_database()
    seed_default_data()
    
    print("\n📊 Test des fonctions:")
    
    # Tester l'ajout d'un utilisateur
    user_id = create_user("Test User", "test@example.com", "123456")
    print(f"✅ Utilisateur créé: {user_id}")
    
    # Tester l'authentification
    user = authenticate_user("test@example.com", "123456")
    print(f"✅ Authentification: {user['name'] if user else 'Échec'}")
    
    print("\n✅ Base de données prête !")
