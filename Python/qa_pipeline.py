import mysql.connector
import pandas as pd
import os
from datetime import datetime
from getpass import getpass

# =========================================================
# CONNECT
# =========================================================
connection = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password=getpass("Enter your MySQL password: "),
    database="bloomfield_growth_engine"
)

flagged_issues = []

# =========================================================
# STAGE 1: SCHEMA CHECK
# =========================================================
cursor = connection.cursor()

expected_schema = {
    "transaction_id": {"type": "varchar", "nullable": "NO"},
    "customer_id": {"type": "varchar", "nullable": "NO"},
    "order_timestamp": {"type": "datetime", "nullable": "NO"},
    "channel": {"type": "varchar", "nullable": "NO"},
    "revenue": {"type": "decimal", "nullable": "NO"},
    "product": {"type": "varchar", "nullable": "YES"},
}

cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'bloomfield_growth_engine'
    AND TABLE_NAME = 'staging_orders'
""")
actual_schema = {row[0]: {"type": row[1], "nullable": row[2]} for row in cursor.fetchall()}

for col, expected in expected_schema.items():
    if col not in actual_schema:
        flagged_issues.append({"stage": "schema", "issue": f"Missing column: {col}"})
        continue
    actual = actual_schema[col]
    if actual["type"] != expected["type"]:
        flagged_issues.append({"stage": "schema", "issue": f"{col}: expected type '{expected['type']}', found '{actual['type']}'"})
    if actual["nullable"] != expected["nullable"]:
        flagged_issues.append({"stage": "schema", "issue": f"{col}: expected nullable='{expected['nullable']}', found '{actual['nullable']}'"})

for col in actual_schema:
    if col not in expected_schema:
        flagged_issues.append({"stage": "schema", "issue": f"Unexpected column found: {col}"})

cursor.execute("""
    SELECT transaction_id, COUNT(*) 
    FROM staging_orders 
    GROUP BY transaction_id 
    HAVING COUNT(*) > 1
""")
for dup_id, count in cursor.fetchall():
    flagged_issues.append({"stage": "schema", "issue": f"Duplicate transaction_id '{dup_id}' appears {count} times"})

cursor.close()

# =========================================================
# STAGE 2: STANDARDIZATION
# =========================================================
df = pd.read_sql("SELECT * FROM staging_orders", connection)

text_cols = ["transaction_id", "customer_id", "channel", "product"]
for col in text_cols:
    df[col] = df[col].astype(str).str.strip()

df["channel"] = df["channel"].str.title()

df["order_timestamp_clean"] = pd.to_datetime(df["order_timestamp"], format="%d/%m/%Y %H:%M", errors="coerce")
bad_dates = df[df["order_timestamp_clean"].isna()]
for _, row in bad_dates.iterrows():
    flagged_issues.append({"stage": "standardization", "issue": f"transaction_id {row['transaction_id']}: unparseable order_timestamp '{row['order_timestamp']}'"})

df["revenue_clean"] = pd.to_numeric(df["revenue"].str.replace(r"[^\d.\-]", "", regex=True), errors="coerce")
bad_revenue = df[df["revenue_clean"].isna()]
for _, row in bad_revenue.iterrows():
    flagged_issues.append({"stage": "standardization", "issue": f"transaction_id {row['transaction_id']}: unparseable revenue '{row['revenue']}'"})

bad_values = df[(df["revenue_clean"] <= 0) & (df["revenue_clean"].notna())]
for _, row in bad_values.iterrows():
    flagged_issues.append({"stage": "standardization", "issue": f"transaction_id {row['transaction_id']}: non-positive revenue {row['revenue_clean']}"})

dupes = df[df.duplicated(subset="transaction_id", keep=False)]
for txn_id in dupes["transaction_id"].unique():
    flagged_issues.append({"stage": "standardization", "issue": f"Duplicate transaction_id '{txn_id}' in cleaned data"})

# =========================================================
# STAGE 3: VALIDATION
# =========================================================
valid_channels = ["Email", "Google Ads", "Meta Ads", "Organic"]

invalid_channels = df[~df["channel"].isin(valid_channels)]
for _, row in invalid_channels.iterrows():
    flagged_issues.append({"stage": "validation", "issue": f"transaction_id {row['transaction_id']}: unexpected channel '{row['channel']}'"})

future_orders = df[df["order_timestamp_clean"] > pd.Timestamp.now()]
for _, row in future_orders.iterrows():
    flagged_issues.append({"stage": "validation", "issue": f"transaction_id {row['transaction_id']}: future-dated order {row['order_timestamp_clean']}"})

mean_rev = df["revenue_clean"].mean()
std_rev = df["revenue_clean"].std()
outliers = df[df["revenue_clean"] > (mean_rev + 3 * std_rev)]
for _, row in outliers.iterrows():
    flagged_issues.append({"stage": "validation", "issue": f"transaction_id {row['transaction_id']}: revenue outlier {row['revenue_clean']} (mean={mean_rev:.2f}, std={std_rev:.2f})"})

critical_cols = ["customer_id", "channel", "revenue_clean"]
for col in critical_cols:
    missing = df[df[col].isna() | (df[col] == "")]
    for _, row in missing.iterrows():
        flagged_issues.append({"stage": "validation", "issue": f"transaction_id {row['transaction_id']}: missing {col}"})

connection.close()

# =========================================================
# STAGE 4: FLAGGED ISSUES REPORT
# =========================================================
report_df = pd.DataFrame(flagged_issues, columns=["stage", "issue"])

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
report_filename = f"flagged_issues_report_{timestamp}.csv"
report_df.to_csv(report_filename, index=False)

print(f"\n=== QA REPORT SUMMARY ===")
print(f"Total issues flagged: {len(report_df)}")
if not report_df.empty:
    print(report_df["stage"].value_counts().to_string())
print(f"\nFull report saved to: {os.path.abspath(report_filename)}")