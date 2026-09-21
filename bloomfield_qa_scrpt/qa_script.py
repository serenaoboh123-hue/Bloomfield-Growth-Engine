import mysql.connector
from getpass import getpass

connection = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password=getpass("Enter your MySQL password: "),
    database="bloomfield_growth_engine"  # Replace with your database name
)

if connection.is_connected():
    print("Successfully connected to MySQL!")

connection.close()
print("Connection closed.")


