import mysql.connector
from getpass import getpass

connection = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password=getpass("Enter your MySQL password: "),
    database="bloomfield_growth_engine"
)

cursor = connection.cursor()

# --- Expected schema definition ---
expected_schema = {
    "transaction_id": {"type": "varchar", "nullable": "NO"},
    "customer_id": {"type": "varchar", "nullable": "NO"},
    "order_timestamp": {"type": "datetime", "nullable": "NO"},
    "channel": {"type": "varchar", "nullable": "NO"},
    "revenue": {"type": "decimal", "nullable": "NO"},
    "product": {"type": "varchar", "nullable": "YES"},
}

flagged_issues = []

# --- Pull actual schema ---
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'bloomfield_growth_engine'
    AND TABLE_NAME = 'staging_orders'
""")
actual_schema = {row[0]: {"type": row[1], "nullable": row[2]} for row in cursor.fetchall()}

# --- Compare expected vs actual ---
for col, expected in expected_schema.items():
    if col not in actual_schema:
        flagged_issues.append({"check": "schema", "issue": f"Missing column: {col}"})
        continue

    actual = actual_schema[col]
    if actual["type"] != expected["type"]:
        flagged_issues.append({
            "check": "schema",
            "issue": f"{col}: expected type '{expected['type']}', found '{actual['type']}'"
        })
    if actual["nullable"] != expected["nullable"]:
        flagged_issues.append({
            "check": "schema",
            "issue": f"{col}: expected nullable='{expected['nullable']}', found '{actual['nullable']}'"
        })

# --- Check for unexpected extra columns ---
for col in actual_schema:
    if col not in expected_schema:
        flagged_issues.append({"check": "schema", "issue": f"Unexpected column found: {col}"})

# --- Check for duplicate transaction_id (since it should be unique) ---
cursor.execute("""
    SELECT transaction_id, COUNT(*) 
    FROM staging_orders 
    GROUP BY transaction_id 
    HAVING COUNT(*) > 1
""")
duplicates = cursor.fetchall()
for dup_id, count in duplicates:
    flagged_issues.append({"check": "schema", "issue": f"Duplicate transaction_id '{dup_id}' appears {count} times"})

# --- Print flagged issues ---
print(f"\n--- Stage 1: Schema Check — {len(flagged_issues)} issue(s) found ---\n")
for issue in flagged_issues:
    print(f"[{issue['check']}] {issue['issue']}")

cursor.close()
connection.close()