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

# --- Pull raw data into a DataFrame ---
df = pd.read_sql("SELECT * FROM staging_orders", connection)

# --- Trim whitespace on text columns ---
text_cols = ["transaction_id", "customer_id", "channel", "product"]
for col in text_cols:
    df[col] = df[col].astype(str).str.strip()

# --- Standardize channel casing (Title Case, e.g. "facebook" -> "Facebook") ---
df["channel"] = df["channel"].str.title()

# --- Convert order_timestamp to real datetime ---
df["order_timestamp_clean"] = pd.to_datetime(df["order_timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")

# Flag rows where conversion failed (bad/unparseable dates)
bad_dates = df[df["order_timestamp_clean"].isna()]
for _, row in bad_dates.iterrows():
    flagged_issues.append({
        "check": "standardization",
        "issue": f"transaction_id {row['transaction_id']}: unparseable order_timestamp '{row['order_timestamp']}'"
    })

# --- Convert revenue to numeric ---
df["revenue_clean"] = pd.to_numeric(
    df["revenue"].str.replace(r"[^\d.\-]", "", regex=True),
    errors="coerce"
)

# Flag rows where revenue couldn't convert
bad_revenue = df[df["revenue_clean"].isna()]
for _, row in bad_revenue.iterrows():
    flagged_issues.append({
        "check": "standardization",
        "issue": f"transaction_id {row['transaction_id']}: unparseable revenue '{row['revenue']}'"
    })

# --- Flag negative or zero revenue (likely bad data) ---
bad_values = df[(df["revenue_clean"] <= 0) & (df["revenue_clean"].notna())]
for _, row in bad_values.iterrows():
    flagged_issues.append({
        "check": "standardization",
        "issue": f"transaction_id {row['transaction_id']}: non-positive revenue {row['revenue_clean']}"
    })

# --- Flag duplicates again here (carried over, now on clean data) ---
dupes = df[df.duplicated(subset="transaction_id", keep=False)]
for txn_id in dupes["transaction_id"].unique():
    flagged_issues.append({
        "check": "standardization",
        "issue": f"Duplicate transaction_id '{txn_id}' in cleaned data"
    })

# --- Print results ---
print(f"\n--- Stage 2: Standardization — {len(flagged_issues)} issue(s) found ---\n")
for issue in flagged_issues:
    print(f"[{issue['check']}] {issue['issue']}")

print(f"\nCleaned dataset shape: {df.shape}")
print(df[["transaction_id", "order_timestamp_clean", "revenue_clean", "channel"]].head())

connection.close()

df["order_timestamp_clean"] = pd.to_datetime(df["order_timestamp"], format="%d/%m/%Y %H:%M", errors="coerce")

print(df["order_timestamp"].head(10).tolist())

# Separate whitelist — not a column in the database, just our reference list to check against
valid_channels = ["Email", "Google Ads", "Meta Ads"]

# Compare each row's actual "channel" column value to the whitelist above
invalid_channels = df[~df["channel"].isin(valid_channels)]
for _, row in invalid_channels.iterrows():
    flagged_issues.append({
        "check": "validation",
        "issue": f"transaction_id {row['transaction_id']}: unexpected channel '{row['channel']}'"
    })