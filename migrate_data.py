# migrate_data.py
import json
import sqlite3
import os

DB_PATH = "onecca.db"
JSON_PATH = "onecca_data.json"

def migrate_members():
    """Importer les membres depuis le fichier JSON"""
    
    if not os.path.exists(JSON_PATH):
        print(f"❌ Fichier {JSON_PATH} non trouvé")
        return
    
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Vérifier si la table est vide
    cursor.execute("SELECT COUNT(*) FROM members")
    count = cursor.fetchone()[0]
    
    if count > 0:
        print(f"ℹ️ La table members contient déjà {count} entrées")
        response = input("Voulez-vous les remplacer ? (o/N): ")
        if response.lower() != 'o':
            print("❌ Migration annulée")
            conn.close()
            return
        cursor.execute("DELETE FROM members")
    
    total = 0
    for section, entries in data.items():
        for entry in entries:
            cursor.execute("""
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
            total += 1
    
    conn.commit()
    conn.close()
    
    print(f"✅ {total} membres importés avec succès")

def show_stats():
    """Afficher les statistiques de la base de données"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n" + "="*50)
    print("📊 STATISTIQUES DE LA BASE DE DONNÉES")
    print("="*50)
    
    tables = ['members', 'users', 'contact_requests', 'contact_access_requests', 'payments']
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  📋 {table}: {count} enregistrements")
    
    # Sections des membres
    cursor.execute("SELECT section, COUNT(*) FROM members GROUP BY section")
    sections = cursor.fetchall()
    print("\n  📂 Répartition par section:")
    for section, count in sections:
        print(f"     - {section}: {count}")
    
    conn.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--stats":
            show_stats()
        elif sys.argv[1] == "--migrate":
            migrate_members()
        else:
            print("Usage: python migrate_data.py [--stats | --migrate]")
    else:
        migrate_members()
        show_stats()
