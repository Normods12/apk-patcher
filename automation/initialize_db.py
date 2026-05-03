import sqlite3

def initialize_database():
    conn = sqlite3.connect('automation/apps_fresh_20260217_171720.db')
    cursor = conn.cursor()

    # Create jobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Insert test data
    cursor.executemany('''
        INSERT INTO jobs (app_name, status) VALUES (?, ?)
    ''', [
        ('Test App 1', 'pending'),
        ('Test App 2', 'pending'),
        ('Test App 3', 'pending')
    ])

    conn.commit()
    conn.close()

if __name__ == '__main__':
    initialize_database()
    print("Database initialized successfully.")