LABMARKET - BCA CAPSTONE PROJECT
Usage-Based Laboratory Equipment Marketplace with Predictive Availability

Implemented capstone modules:
1. Equipment catalogue with 8 real equipment images.
2. User registration/login and role-based admin access.
3. Rental cart, date-based booking calendar and payment selection.
4. Booking conflict/stock validation.
5.  check-in for rentals.
6. Current equipment status with simulated sensor telemetry.
7. Usage/audit logs.
8. Overdue rental alerts.
9. Utilization dashboard.
10. REST/OpenAPI-style JSON endpoints: /api/equipment, /api/equipment/<id>/status, /api/utilization.
11. Health/operational endpoint: /health.
12. Automated tests with pytest.
13. Dockerfile and docker-compose deployment.
14. GitHub Actions CI workflow.
15. SQLite database for demonstration; easy to replace with PostgreSQL later.

Run locally:
1. Open this folder in VS Code.
2. python -m venv venv
3. venv\Scripts\activate
4. pip install -r requirements.txt
5. python app.py
6. Open http://127.0.0.1:5000

Demo accounts:
Admin: admin@labmarket.com / admin123
Customer: student@labmarket.com / student123

The project is a realistic/simulated prototype: sensor values are simulated for demonstration and can later be replaced with ESP32/RFID/device APIs.

College requirement mapping:
- Equipment catalog -> /products
- Booking calendar -> /availability + date conflict validation in /checkout
-  check-in -> /qr/<rental_no> and /checkin/<rental_no>
- Current-status sensor -> simulated equipment_status telemetry
- Usage log -> Admin > Usage / Audit Log
- Overdue alert -> Admin > Overdue Alerts
- Utilization dashboard -> Admin > Avg Utilization + equipment utilization
- Predictive availability -> /api/predictive-availability
- Secure role-based operations -> admin-only status/return actions
- Automated tests -> tests/test_app.py
- Containerized deployment -> Dockerfile + docker-compose.yml
- Operational telemetry -> /health and equipment last-seen values
- Failure/robustness handling -> date conflict, stock validation, invalid login, missing equipment, cancelled/returned states


PAYMENT MODULE
- Online Payment (simulated)
- Debit Card (simulated)
- Credit Card (simulated)
- Cash on Delivery / Pay at Lab Desk
- Payment status is stored with each rental.
- For card payments, only the last 4 digits are stored; CVV and full card number are never stored.
- This is a demonstration payment flow for the college prototype, not a live payment gateway.

UPDATED VERSION: QR scanner removed. Checkout now collects customer name, contact number, address, and shows payment options with icons (UPI/Online, Cash on Delivery, Debit Card, Credit Card). Admin dashboard stores and displays customer details.
