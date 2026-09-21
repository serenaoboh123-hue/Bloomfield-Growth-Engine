import mysql.connector
import pandas as pd
from getpass import getpass

connection = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password=getpass("Enter your MySQL password: "),
    database="bloomfield_growth_engine"
)

flagged_issues = []

# --- Pull raw data ---
df = pd.read_sql("SELECT * FROM staging_orders", connection)

# --- Standardization (needed before validation can run) ---
text_cols = ["transaction_id", "customer_id", "channel", "product"]
for col in text_cols:
    df[col] = df[col].astype(str).str.strip()

df["channel"] = df["channel"].str.title()

df["order_timestamp_clean"] = pd.to_datetime(df["order_timestamp"], format="%d/%m/%Y %H:%M", errors="coerce")

df["revenue_clean"] = pd.to_numeric(
    df["revenue"].str.replace(r"[^\d.\-]", "", regex=True),
    errors="coerce"
)

# --- Stage 3: Validation Queries ---

# Separate whitelist — not a database column, just our reference list to check against
valid_channels = ["Email", "Google Ads", "Meta Ads", "Organic"]

invalid_channels = df[~df["channel"].isin(valid_channels)]
for _, row in invalid_channels.iterrows():
    flagged_issues.append({
        "check": "validation",
        "issue": f"transaction_id {row['transaction_id']}: unexpected channel '{row['channel']}'"
    })

future_orders = df[df["order_timestamp_clean"] > pd.Timestamp.now()]
for _, row in future_orders.iterrows():
    flagged_issues.append({
        "check": "validation",
        "issue": f"transaction_id {row['transaction_id']}: future-dated order {row['order_timestamp_clean']}"
    })

mean_rev = df["revenue_clean"].mean()
std_rev = df["revenue_clean"].std()
outliers = df[df["revenue_clean"] > (mean_rev + 3 * std_rev)]
for _, row in outliers.iterrows():
    flagged_issues.append({
        "check": "validation",
        "issue": f"transaction_id {row['transaction_id']}: revenue outlier {row['revenue_clean']} (mean={mean_rev:.2f}, std={std_rev:.2f})"
    })

critical_cols = ["customer_id", "channel", "revenue_clean"]
for col in critical_cols:
    missing = df[df[col].isna() | (df[col] == "")]
    for _, row in missing.iterrows():
        flagged_issues.append({
            "check": "validation",
            "issue": f"transaction_id {row['transaction_id']}: missing {col}"
        })

# --- Print results ---
print(f"\n--- Stage 3: Validation — {len(flagged_issues)} issue(s) found ---\n")
for issue in flagged_issues:
    print(f"[{issue['check']}] {issue['issue']}")

connection.close()

