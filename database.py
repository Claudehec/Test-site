# database.py
import sqlite3
import json
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

DB_PATH = "onecca.db"

def get_db():
    """Obtenir une connexion à la base de données"""
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_database():
    """Initialiser toutes les tables"""
    db = get_db()
    
    # Table des membres
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
    
    # Table des paramètres
    db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Table des demandes de contact
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
    
    # Table des utilisateurs
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
    
    # Table des sessions
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
    
    # Table des demandes d'accès
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
    
    # Table des paiements
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
    
    # Table des tarifs
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
    print("✅ Base de données initialisée")

def seed_default_data():
    """Insérer les données par défaut"""
    db = get_db()
    
    # Tarifs par défaut
    cursor = db.execute("SELECT COUNT(*) FROM pricing")
    if cursor.fetchone()[0] == 0:
        db.executescript("""
            INSERT INTO pricing (item_type, price, description, is_active) VALUES 
                ('single_contact', 5000, 'Accès aux coordonnées d''un membre pour 30 jours', 1),
                ('monthly_subscription', 25000, 'Accès illimité à tous les membres pour 30 jours', 1),
                ('yearly_subscription', 250000, 'Accès illimité à tous les membres pour 1 an', 1)
        """)
        print("✅ Tarifs par défaut insérés")
    
    # Paramètres par défaut
    cursor = db.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        db.execute("INSERT INTO settings (key, value) VALUES ('show_contacts', 'false')")
        print("✅ Paramètres par défaut insérés")
    
    db.commit()
    db.close()

def import_members_from_json(json_path: str):
    """Importer les membres depuis un fichier JSON"""
    import os
    if not os.path.exists(json_path):
        print(f"❌ Fichier {json_path} non trouvé")
        return 0
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    db = get_db()
    total = 0
    
    for section, entries in data.items():
        for entry in entries:
            # Calculer le prochain numéro
            cursor = db.execute("SELECT MAX(num) FROM members WHERE section=?", (section,))
            max_num = cursor.fetchone()[0]
            new_num = (max_num or 0) + 1
            
            db.execute("""
                INSERT INTO members (section, num, nom, inscription_num, inscription_date, bp, tel1, tel2, email, adresse, ville)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                section, new_num,
                entry.get("nom", ""),
                entry.get("inscription_num", ""),
                entry.get("inscription_date", ""),
                entry.get("bp", ""),
                entry.get("tel1", ""),
                entry.get("tel2", ""),
                entry.get("email", ""),
                entry.get("adresse", ""),
                entry.get("ville", "Autre")
            ))
            total += 1
    
    db.commit()
    db.close()
    print(f"✅ {total} membres importés")
    return total

# ===== FONCTIONS POUR LES MEMBRES =====

def get_all_members(show_contacts: bool = False) -> Dict[str, List[Dict]]:
    """Récupérer tous les membres"""
    db = get_db()
    rows = db.execute("SELECT * FROM members ORDER BY section, num").fetchall()
    db.close()
    
    result = {}
    for r in rows:
        section = r["section"]
        if section not in result:
            result[section] = []
        
        member = {
            "id": r["id"], "num": r["num"], "nom": r["nom"],
            "inscription_num": r["inscription_num"], "inscription_date": r["inscription_date"],
            "bp": r["bp"], "adresse": r["adresse"], "ville": r["ville"]
        }
        if show_contacts:
            member["tel1"] = r["tel1"]
            member["tel2"] = r["tel2"]
            member["email"] = r["email"]
        
        result[section].append(member)
    
    return result

def add_member(section: str, nom: str, **kwargs) -> int:
    """Ajouter un membre"""
    db = get_db()
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
    fields = [f"{k}=?" for k in kwargs.keys() if k in ['section', 'nom', 'inscription_num', 'inscription_date', 'bp', 'tel1', 'tel2', 'email', 'adresse', 'ville']]
    if not fields:
        db.close()
        return False
    
    values = [kwargs[k] for k in kwargs.keys() if k in ['section', 'nom', 'inscription_num', 'inscription_date', 'bp', 'tel1', 'tel2', 'email', 'adresse', 'ville']]
    values.append(datetime.now().isoformat())
    values.append(member_id)
    
    db.execute(f"UPDATE members SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
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

# ===== FONCTIONS POUR LES SESSIONS =====

def create_user_session(user_id: int, duration_hours: int = 168) -> str:
    """Créer une session utilisateur"""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=duration_hours)
    
    db = get_db()
    db.execute("INSERT INTO user_sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
               (user_id, token, expires_at.isoformat()))
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

def delete_user_session(token: str) -> bool:
    """Supprimer une session"""
    db = get_db()
    db.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    db.commit()
    db.close()
    return True

# ===== FONCTIONS POUR LES DEMANDES D'ACCÈS =====

def create_access_request(user_id: int, member_id: int, member_name: str) -> int:
    """Créer une demande d'accès"""
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
    """Récupérer les demandes en attente"""
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

def approve_access_request(request_id: int) -> bool:
    """Approuver une demande d'accès"""
    db = get_db()
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    db.execute("""
        UPDATE contact_access_requests 
        SET status = 'approved', approved_at = datetime('now'), expires_at = ?
        WHERE id = ?
    """, (expires_at, request_id))
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
    """Vérifier si l'utilisateur a accès à un membre"""
    db = get_db()
    cursor = db.execute("""
        SELECT id FROM contact_access_requests 
        WHERE user_id = ? AND member_id = ? 
        AND status = 'approved' AND expires_at > datetime('now')
        LIMIT 1
    """, (user_id, member_id))
    result = cursor.fetchone()
    db.close()
    return result is not None

def get_user_access_requests(user_id: int) -> List[Dict]:
    """Récupérer toutes les demandes d'un utilisateur"""
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

def get_user_dashboard_data(user_id: int) -> Dict:
    """Récupérer les données du dashboard utilisateur"""
    requests = get_user_access_requests(user_id)
    
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    
    # Paiements
    cursor.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    payments = [dict(row) for row in cursor.fetchall()]
    
    # Abonnement actif
    cursor.execute("""
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
    
    return {
        "stats": stats,
        "access_requests": requests,
        "payments": payments,
        "active_subscription": dict(active_subscription) if active_subscription else None
    }

# ===== FONCTIONS POUR LES PARAMÈTRES =====

def get_setting(key: str, default: str = None) -> str:
    db = get_db()
    cursor = db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    db.close()
    return row[0] if row else default

def set_setting(key: str, value: str) -> bool:
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()
    db.close()
    return True

# ===== INITIALISATION =====

if __name__ == "__main__":
    import sys
    
    init_database()
    seed_default_data()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--import":
        json_path = sys.argv[2] if len(sys.argv) > 2 else "onecca_data.json"
        import_members_from_json(json_path)
    
    print("\n✅ Base de données prête !")
