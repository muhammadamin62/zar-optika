import sqlite3

conn = sqlite3.connect('optics_crm.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("--- ПОСЛЕДНИЕ 5 ЗАПИСЕЙ В ФИНАНСАХ ---")
rows = cursor.execute("SELECT * FROM finance ORDER BY id DESC LIMIT 5").fetchall()
for row in rows:
    print(f"ID: {row['id']} | Тип: {row['type']} | Сумма: {row['amount']} | Описание: {row['description']}")

conn.close()