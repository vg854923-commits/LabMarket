from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import sqlite3, os, logging, random, re

app = Flask(__name__)
app.secret_key = os.environ.get("LABMARKET_SECRET", "labmarket-dev-secret-change-me")
app.config["JSON_SORT_KEYS"] = False
DB = os.path.join(os.path.dirname(__file__), "labmarket.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("labmarket")

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def column_names(c, table):
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}

def add_column(c, table, column, definition):
    if column not in column_names(c, table):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def setup():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,role TEXT DEFAULT 'customer',phone TEXT,address TEXT,created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,category TEXT,description TEXT,
        daily_rent REAL,stock INTEGER,image TEXT,status TEXT DEFAULT 'Available'
    );
    CREATE TABLE IF NOT EXISTS rentals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,rental_no TEXT UNIQUE,user_id INTEGER,total REAL,
        start_date TEXT,end_date TEXT,purpose TEXT,status TEXT DEFAULT 'Booked',customer_name TEXT,contact_number TEXT,address TEXT,created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS rental_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,rental_id INTEGER,product_id INTEGER,quantity INTEGER,rent REAL
    );
    CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,rating INTEGER,
        comment TEXT,created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS equipment_status(
        product_id INTEGER PRIMARY KEY,current_status TEXT DEFAULT 'Available',
        utilization REAL DEFAULT 0,last_seen TEXT,temperature REAL,usage_hours REAL
    );
    CREATE TABLE IF NOT EXISTS usage_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,rental_id INTEGER,product_id INTEGER,user_id INTEGER,
        action TEXT,notes TEXT,logged_at TEXT
    );
    """)
    # Backward-compatible additions for an existing database.
    add_column(c, "products", "location", "TEXT DEFAULT 'Lab Store'")
    add_column(c, "products", "sensor_enabled", "INTEGER DEFAULT 1")
    add_column(c, "users", "phone", "TEXT")
    add_column(c, "users", "address", "TEXT")
    add_column(c, "rentals", "customer_name", "TEXT")
    add_column(c, "rentals", "contact_number", "TEXT")
    add_column(c, "rentals", "address", "TEXT")
    add_column(c, "rentals", "payment_method", "TEXT DEFAULT 'Cash on Delivery'")
    add_column(c, "rentals", "payment_status", "TEXT DEFAULT 'Pending'")
    add_column(c, "rentals", "payment_reference", "TEXT")
    add_column(c, "rentals", "card_last4", "TEXT")

    now = datetime.now().isoformat(timespec="seconds")
    if c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] == 0:
        c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                  ("Admin","admin@labmarket.com",generate_password_hash("admin123"),"admin",now))
        c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                  ("Demo Student","student@labmarket.com",generate_password_hash("student123"),"customer",now))
    else:
        # Repair older bundled databases that stored the demo passwords as plain text.
        demo_accounts = [("admin@labmarket.com", "admin123"), ("student@labmarket.com", "student123")]
        for email, plain_password in demo_accounts:
            row = c.execute("SELECT id,password FROM users WHERE email=?", (email,)).fetchone()
            if row and not str(row["password"]).startswith(("scrypt:", "pbkdf2:", "argon2:")):
                c.execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(plain_password), row["id"]))

    products = [
        ("Digital Microscope","Microscopy","High-resolution microscope for slide observation and digital imaging.",500,3,"microscope.jpeg"),
        ("Laboratory Centrifuge","Sample Processing","Variable-speed centrifuge for safe sample separation.",700,2,"centrifuge.jpeg"),
        ("PCR Machine","Molecular Biology","Thermal cycling equipment for PCR experiments.",1200,1,"pcr.jpeg"),
        ("UV-Vis Spectrophotometer","Spectroscopy","Measures absorbance and concentration of samples.",900,1,"spectro.jpeg"),
        ("Analytical Balance","Measurement","Precision balance for accurate laboratory weighing.",350,2,"balance.jpeg"),
        ("Water Bath","Heating","Controlled-temperature water bath for sample preparation.",450,1,"waterbath.jpeg"),
        ("Laboratory Incubator","Cell Culture","Controlled temperature environment for biological samples.",800,2,"incubator.jpeg"),
        ("Digital pH Meter","Measurement","Digital measurement of acidity and alkalinity.",250,3,"ph.jpeg"),
        ("Laboratory Fume Hood","Safety Equipment","Ventilated enclosure for safely handling laboratory chemicals and fumes.",1500,1,"fume_hood.png"),
        ("Infrared Thermometer","Measurement","Non-contact infrared thermometer for quick temperature measurement.",200,4,"infrared_thermometer_user.png"),
        ("Hematology Analyzer","Clinical Laboratory","Automated analyzer for routine blood-cell testing and laboratory demonstrations.",1800,1,"hematology_analyzer.png"),
        ("Hot Plate Magnetic Stirrer","Heating & Mixing","Laboratory hot plate with magnetic stirring for controlled heating and mixing.",650,2,"hot_plate_stirrer.png"),
    ]
    # Add missing products and refresh details/images for existing products.
    for name,cat,desc,rent,stock,img in products:
        existing = c.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
        if existing:
            c.execute("""UPDATE products
                         SET image=?,category=?,description=?,daily_rent=?,stock=?,status='Available',location='Main Laboratory',sensor_enabled=1
                         WHERE id=?""",
                      (img,cat,desc,rent,stock,existing["id"]))
        else:
            c.execute("""INSERT INTO products
                (name,category,description,daily_rent,stock,image,status,location,sensor_enabled)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                      (name,cat,desc,rent,stock,img,"Available","Main Laboratory",1))

    for p in c.execute("SELECT id FROM products").fetchall():
        c.execute("""INSERT OR IGNORE INTO equipment_status(product_id,current_status,utilization,last_seen,temperature,usage_hours)
                     VALUES(?,?,?,?,?,?)""",
                  (p["id"],"Available",random.randint(15,65),now,round(random.uniform(22,30),1),round(random.uniform(5,60),1)))
    c.commit(); c.close()

@app.context_processor
def ctx():
    cart = session.get("cart", {})
    return dict(logged_in="user_id" in session, user_name=session.get("user_name"),
                role=session.get("role"), cart_count=sum(cart.values()))

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def overlap_conflict(c, product_id, start_date, end_date, ignore_rental=None):
    # A rental conflicts when its dates overlap and it is not cancelled/returned.
    params=[product_id, end_date, start_date]
    q="""SELECT COALESCE(SUM(ri.quantity),0) qty
         FROM rental_items ri JOIN rentals r ON r.id=ri.rental_id
         WHERE ri.product_id=? AND r.status NOT IN ('Cancelled','Returned')
           AND r.start_date <= ? AND r.end_date >= ?"""
    if ignore_rental:
        q += " AND r.id != ?"
        params.append(ignore_rental)
    return c.execute(q, params).fetchone()["qty"]

def refresh_status(c):
    # Simulated sensor/status layer for the capstone demonstration.
    now=datetime.now().isoformat(timespec="seconds")
    rows=c.execute("SELECT id,stock FROM products").fetchall()
    for p in rows:
        active=c.execute("""SELECT COALESCE(SUM(ri.quantity),0) q FROM rental_items ri
                            JOIN rentals r ON r.id=ri.rental_id
                            WHERE ri.product_id=? AND r.status IN ('Booked','Checked In')
                            AND r.start_date<=date('now') AND r.end_date>=date('now')""",(p["id"],)).fetchone()["q"]
        if active >= p["stock"]:
            status="In Use"
        else:
            status="Available"
        c.execute("""UPDATE equipment_status SET current_status=?,last_seen=?,
                     temperature=?,usage_hours=? WHERE product_id=?""",
                  (status,now,round(random.uniform(22,30),1),
                   round(random.uniform(5,120),1),p["id"]))

@app.route("/")
def home():
    c=db(); refresh_status(c)
    products=c.execute("SELECT * FROM products ORDER BY id").fetchall()
    stats=[
        c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"],
        c.execute("SELECT COUNT(*) n FROM users WHERE role='customer'").fetchone()["n"],
        c.execute("SELECT COUNT(*) n FROM rentals").fetchone()["n"],
        c.execute("SELECT COUNT(*) n FROM equipment_status WHERE current_status='In Use'").fetchone()["n"]
    ]
    c.commit(); c.close()
    return render_template("index.html",products=products,stats=stats)

@app.route("/products")
def products():
    q=request.args.get("q","").strip()
    category=request.args.get("category","").strip()
    c=db()
    sql="""SELECT p.*,es.current_status,es.utilization,es.last_seen,
                  COALESCE(AVG(f.rating),0) avg_rating, COUNT(f.id) review_count
           FROM products p LEFT JOIN equipment_status es ON es.product_id=p.id
           LEFT JOIN feedback f ON f.product_id=p.id
           WHERE (p.name LIKE ? OR p.category LIKE ?)"""
    params=[f"%{q}%",f"%{q}%"]
    if category:
        sql += " AND p.category=?"; params.append(category)
    sql += " GROUP BY p.id ORDER BY p.id"
    rows=c.execute(sql,params).fetchall()
    categories=c.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
    c.close()
    return render_template("products.html",products=rows,q=q,category=category,categories=categories)

@app.route("/product/<int:pid>")
def product(pid):
    c=db()
    p=c.execute("""SELECT p.*,es.current_status,es.utilization,es.last_seen,es.temperature,es.usage_hours,
                        COALESCE(AVG(f.rating),0) avg_rating, COUNT(f.id) review_count
                   FROM products p LEFT JOIN equipment_status es ON es.product_id=p.id
                   LEFT JOIN feedback f ON f.product_id=p.id WHERE p.id=? GROUP BY p.id""",(pid,)).fetchone()
    reviews=c.execute("""SELECT f.*,u.name FROM feedback f JOIN users u ON u.id=f.user_id
                        WHERE f.product_id=? ORDER BY f.id DESC LIMIT 10""",(pid,)).fetchall()
    c.close()
    if not p: abort(404)
    return render_template("product.html",p=p,reviews=reviews)

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        c=db()
        try:
            c.execute("INSERT INTO users(name,email,password,created_at) VALUES(?,?,?,?)",
                      (request.form["name"],request.form["email"].lower(),
                       generate_password_hash(request.form["password"]),
                       datetime.now().isoformat(timespec="seconds")))
            c.commit(); c.close(); flash("Account created successfully."); return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            c.close(); flash("Email already exists.")
    return render_template("register.html")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(request.form["email"].lower(),)).fetchone(); c.close()
        valid = False
        if u:
            try:
                valid = check_password_hash(u["password"], request.form["password"])
            except (ValueError, TypeError):
                valid = False
            # Support older bundled databases that used plain demo passwords,
            # then upgrade the password to a secure hash after successful login.
            if not valid and u["password"] == request.form["password"]:
                valid = True
                c2=db()
                c2.execute("UPDATE users SET password=? WHERE id=?",
                           (generate_password_hash(request.form["password"]), u["id"]))
                c2.commit(); c2.close()
        if valid:
            session.update(user_id=u["id"],user_name=u["name"],role=u["role"])
            return redirect(url_for("admin") if u["role"]=="admin" else url_for("home"))
        flash("Invalid login.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.post("/cart/add/<int:pid>")
def add(pid):
    c=db(); p=c.execute("SELECT id,status FROM products WHERE id=?",(pid,)).fetchone(); c.close()
    if not p: abort(404)
    cart=session.get("cart",{}); cart[str(pid)]=cart.get(str(pid),0)+1; session["cart"]=cart
    flash("Added to rental cart.")
    return redirect(request.referrer or url_for("products"))

@app.route("/cart")
def cart():
    c=db(); rows=[]; total=0
    for pid,q in session.get("cart",{}).items():
        p=c.execute("SELECT * FROM products WHERE id=?",(int(pid),)).fetchone()
        if p: rows.append((p,q)); total+=p["daily_rent"]*q
    c.close()
    return render_template("cart.html",rows=rows,total=total)

@app.post("/cart/remove/<int:pid>")
def remove(pid):
    x=session.get("cart",{}); x.pop(str(pid),None); session["cart"]=x
    return redirect(url_for("cart"))

@app.route("/availability")
@login_required
def availability():
    c=db(); products=c.execute("SELECT * FROM products ORDER BY name").fetchall()
    upcoming=c.execute("""SELECT r.*,p.name FROM rentals r
                          JOIN rental_items ri ON ri.rental_id=r.id
                          JOIN products p ON p.id=ri.product_id
                          WHERE r.status NOT IN ('Cancelled','Returned')
                          ORDER BY r.start_date LIMIT 100""").fetchall()
    c.close()
    return render_template("availability.html",products=products,upcoming=upcoming)

@app.route("/checkout",methods=["GET","POST"])
@login_required
def checkout():
    c=db(); rows=[]; total=0
    for pid,q in session.get("cart",{}).items():
        p=c.execute("SELECT * FROM products WHERE id=?",(int(pid),)).fetchone()
        if p:
            rows.append((p,q))
            total+=p["daily_rent"]*q
    if not rows:
        c.close(); flash("Your rental cart is empty."); return redirect(url_for("products"))

    if request.method=="POST":
        start=request.form["start_date"]
        end=request.form["end_date"]
        payment_method=request.form.get("payment_method","Cash on Delivery")
        customer_name=request.form.get("customer_name","").strip()
        contact_number=request.form.get("contact_number","").strip()
        address=request.form.get("address","").strip()
        if not customer_name or not contact_number or not address:
            c.close(); flash("Please enter customer name, contact number and address."); return redirect(url_for("checkout"))
        if not contact_number.isdigit() or len(contact_number) < 10 or len(contact_number) > 15:
            c.close(); flash("Please enter a valid contact number."); return redirect(url_for("checkout"))
        allowed_payments={"Online Payment","Cash on Delivery","Debit Card","Credit Card"}
        if payment_method not in allowed_payments:
            c.close(); flash("Please select a valid payment method."); return redirect(url_for("checkout"))

        if end < start:
            c.close(); flash("End date must be on or after start date."); return redirect(url_for("checkout"))
        try:
            start_obj=datetime.strptime(start,"%Y-%m-%d").date(); end_obj=datetime.strptime(end,"%Y-%m-%d").date()
            rental_days=(end_obj-start_obj).days + 1
        except ValueError:
            c.close(); flash("Please select valid rental dates."); return redirect(url_for("checkout"))
        if rental_days > 365:
            c.close(); flash("Rental period cannot exceed 365 days."); return redirect(url_for("checkout"))
        daily_total=total
        total=daily_total*rental_days

        for p,q in rows:
            used=overlap_conflict(c,p["id"],start,end)
            if used + q > p["stock"]:
                c.close(); flash(f"Booking conflict: {p['name']} is not available for those dates."); return redirect(url_for("checkout"))

        # Demo payment flow for the college prototype.
        # No real money is charged. Card details are never stored; only last 4 digits are kept.
        payment_status="Pending"
        payment_reference=""
        card_last4=""

        if payment_method in {"Online Payment","Debit Card","Credit Card"}:
            if payment_method in {"Debit Card","Credit Card"}:
                card_number=re.sub(r"\D","",request.form.get("card_number",""))
                card_name=request.form.get("card_name","").strip()
                expiry=request.form.get("expiry","").strip()
                cvv=request.form.get("cvv","").strip()
                if len(card_number) < 12 or len(card_number) > 19 or not card_name or not expiry or len(cvv) < 3:
                    c.close(); flash("Please enter valid demo card details."); return redirect(url_for("checkout"))
                card_last4=card_number[-4:]
            payment_status="Paid"
            payment_reference="PAY-"+datetime.now().strftime("%Y%m%d%H%M%S%f")
        else:
            payment_status="Pending"

        c.execute("UPDATE users SET phone=?, address=? WHERE id=?", (contact_number, address, session["user_id"]))

        no="LM-"+datetime.now().strftime("%Y%m%d%H%M%S%f")
        cur=c.execute("""INSERT INTO rentals
            (rental_no,user_id,total,start_date,end_date,purpose,status,customer_name,contact_number,address,created_at,
             payment_method,payment_status,payment_reference,card_last4)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (no,session["user_id"],total,start,end,request.form.get("purpose",""),
             "Booked",customer_name,contact_number,address,datetime.now().isoformat(timespec="seconds"),
             payment_method,payment_status,payment_reference,card_last4))
        rid=cur.lastrowid

        for p,q in rows:
            c.execute("INSERT INTO rental_items(rental_id,product_id,quantity,rent) VALUES(?,?,?,?)",
                      (rid,p["id"],q,p["daily_rent"]))
            c.execute("""INSERT INTO usage_logs(rental_id,product_id,user_id,action,notes,logged_at)
                         VALUES(?,?,?,?,?,?)""",
                      (rid,p["id"],session["user_id"],"BOOKED",
                       f"Booking created. Payment: {payment_method} ({payment_status})",
                       datetime.now().isoformat(timespec="seconds")))

        c.commit(); c.close(); session["cart"]={}
        flash(f"Rental booked successfully. Payment: {payment_status}.")
        return redirect(url_for("rentals"))

    c.close()
    return render_template("checkout.html",rows=rows,total=total,daily_total=total,rental_days=1)

@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    c = db()
    if request.method == "POST":
        product_id = request.form.get("product_id")
        rating = int(request.form.get("rating", 5))
        comment = request.form.get("comment", "").strip()
        if not product_id or not comment or rating not in {1,2,3,4,5}:
            c.close(); flash("Please select equipment, rating and enter a comment."); return redirect(url_for("feedback"))
        c.execute("INSERT INTO feedback(user_id,product_id,rating,comment,created_at) VALUES(?,?,?,?,?)",
                  (session["user_id"], int(product_id), rating, comment, datetime.now().isoformat(timespec="seconds")))
        c.commit(); c.close(); flash("Thank you for your feedback!"); return redirect(url_for("feedback"))
    products = c.execute("SELECT id,name FROM products ORDER BY name").fetchall()
    feedbacks = c.execute("""SELECT f.*,u.name,p.name product_name
                            FROM feedback f JOIN users u ON u.id=f.user_id
                            JOIN products p ON p.id=f.product_id
                            ORDER BY f.id DESC LIMIT 50""").fetchall()
    c.close()
    return render_template("feedback.html", products=products, feedbacks=feedbacks)

@app.route("/rentals")
@login_required
def rentals():
    c=db()
    rs=c.execute("SELECT * FROM rentals WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    items={}
    for r in rs:
        items[r["id"]]=c.execute("""SELECT ri.*,p.name FROM rental_items ri
                                    JOIN products p ON p.id=ri.product_id WHERE ri.rental_id=?""",(r["id"],)).fetchall()
    c.close()
    return render_template("rentals.html",rentals=rs,items=items)

@app.post("/rental/cancel/<int:rid>")
@login_required
def cancel(rid):
    c=db(); c.execute("UPDATE rentals SET status='Cancelled' WHERE id=? AND user_id=? AND status='Booked'",
                      (rid,session["user_id"]))
    c.execute("""INSERT INTO usage_logs(rental_id,user_id,action,notes,logged_at)
                 VALUES(?,?,?,?,?)""",(rid,session["user_id"],"CANCELLED","Customer cancelled booking",
                                        datetime.now().isoformat(timespec="seconds")))
    c.commit(); c.close()
    return redirect(url_for("rentals"))

@app.post("/rental/return/<int:rid>")
@admin_required
def return_rental(rid):
    c = db()
    rental = c.execute("SELECT * FROM rentals WHERE id=?", (rid,)).fetchone()
    if rental and rental["status"] in ("Booked", "Checked In"):
        c.execute("UPDATE rentals SET status='Returned' WHERE id=?", (rid,))
        c.execute("INSERT INTO usage_logs(rental_id,user_id,action,notes,logged_at) VALUES(?,?,?,?,?)",
                  (rid, session["user_id"], "RETURNED", "Admin marked rental as returned", datetime.now().isoformat(timespec="seconds")))
        c.commit(); flash("Rental marked as returned.")
    c.close()
    return redirect(url_for("admin"))

@app.route("/invoice/<int:rid>")
@login_required
def invoice(rid):
    c=db(); r=c.execute("SELECT r.*,u.email FROM rentals r JOIN users u ON u.id=r.user_id WHERE r.id=? AND r.user_id=?",(rid,session["user_id"])).fetchone()
    if not r: c.close(); abort(404)
    items=c.execute("SELECT p.name,ri.quantity,ri.rent FROM rental_items ri JOIN products p ON p.id=ri.product_id WHERE ri.rental_id=?",(rid,)).fetchall()
    c.close(); return render_template("invoice.html",r=r,items=items)

@app.route("/admin/report")
@admin_required
def admin_report():
    c=db()
    monthly=c.execute("""SELECT substr(created_at,1,7) month, COUNT(*) rentals, COALESCE(SUM(total),0) revenue
                         FROM rentals WHERE status!='Cancelled' GROUP BY substr(created_at,1,7) ORDER BY month DESC LIMIT 12""").fetchall()
    category=c.execute("""SELECT p.category, COUNT(DISTINCT r.id) rentals, COALESCE(SUM(ri.quantity),0) units
                         FROM rental_items ri JOIN products p ON p.id=ri.product_id JOIN rentals r ON r.id=ri.rental_id
                         WHERE r.status!='Cancelled' GROUP BY p.category ORDER BY units DESC""").fetchall()
    totals=c.execute("SELECT COUNT(*) rentals, COALESCE(SUM(total),0) revenue FROM rentals WHERE status!='Cancelled'").fetchone()
    c.close(); return render_template("report.html",monthly=monthly,category=category,totals=totals)

@app.route("/admin")
@admin_required
def admin():
    c=db(); refresh_status(c)
    users=c.execute("SELECT id,name,email,role,phone,address,created_at FROM users ORDER BY id DESC").fetchall()
    rs=c.execute("""SELECT r.*,u.name customer,u.email FROM rentals r
                    JOIN users u ON u.id=r.user_id ORDER BY r.id DESC""").fetchall()
    rental_items={}
    for r in rs:
        rental_items[r["id"]]=c.execute("""SELECT p.name,ri.quantity,ri.rent FROM rental_items ri
                                           JOIN products p ON p.id=ri.product_id WHERE ri.rental_id=?""",(r["id"],)).fetchall()
    ps=c.execute("""SELECT p.*,es.current_status,es.utilization,es.last_seen,es.temperature,es.usage_hours
                    FROM products p LEFT JOIN equipment_status es ON es.product_id=p.id""").fetchall()
    logs=c.execute("""SELECT ul.*,u.name customer,p.name equipment,r.rental_no
                      FROM usage_logs ul JOIN users u ON u.id=ul.user_id
                      LEFT JOIN products p ON p.id=ul.product_id
                      LEFT JOIN rentals r ON r.id=ul.rental_id ORDER BY ul.id DESC LIMIT 50""").fetchall()
    overdue=c.execute("""SELECT r.*,u.name customer FROM rentals r JOIN users u ON u.id=r.user_id
                         WHERE r.end_date < date('now') AND r.status NOT IN ('Cancelled','Returned')""").fetchall()
    utilization=round(c.execute("SELECT COALESCE(AVG(utilization),0) v FROM equipment_status").fetchone()["v"],1)
    c.commit(); c.close()
    return render_template("admin.html",users=users,rentals=rs,rental_items=rental_items,products=ps,
                           logs=logs,overdue=overdue,utilization=utilization)

@app.route("/admin/status/update/<int:pid>",methods=["POST"])
@admin_required
def update_status(pid):
    status=request.form.get("status","Available")
    allowed={"Available","In Use","Maintenance","Offline"}
    if status not in allowed: abort(400)
    c=db(); c.execute("""UPDATE equipment_status SET current_status=?,last_seen=? WHERE product_id=?""",
                      (status,datetime.now().isoformat(timespec="seconds"),pid)); c.commit(); c.close()
    return redirect(url_for("admin"))

# REST/OpenAPI-style endpoints required for the capstone.
@app.get("/api/equipment")
def api_equipment():
    c=db(); refresh_status(c)
    rows=c.execute("""SELECT p.id,p.name,p.category,p.stock,p.daily_rent,p.status,
                             es.current_status,es.utilization,es.last_seen,es.temperature
                      FROM products p LEFT JOIN equipment_status es ON es.product_id=p.id
                      ORDER BY p.id""").fetchall()
    c.commit(); c.close()
    return jsonify([dict(r) for r in rows])

@app.get("/api/equipment/<int:pid>/status")
def api_status(pid):
    c=db(); refresh_status(c)
    row=c.execute("""SELECT p.name,es.* FROM products p JOIN equipment_status es
                     ON es.product_id=p.id WHERE p.id=?""",(pid,)).fetchone()
    c.commit(); c.close()
    if not row: abort(404)
    return jsonify(dict(row))

@app.get("/api/utilization")
def api_utilization():
    c=db()
    rows=c.execute("""SELECT p.name,ROUND(es.utilization,1) utilization,es.current_status
                      FROM products p JOIN equipment_status es ON es.product_id=p.id
                      ORDER BY es.utilization DESC""").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.get("/api/predictive-availability")
def api_predictive_availability():
    """Rule-based predictive availability for the next 7 days using bookings + stock."""
    c=db()
    out=[]
    for p in c.execute("SELECT id,name,stock FROM products ORDER BY id").fetchall():
        days=[]
        for offset in range(7):
            d=(date.today()+timedelta(days=offset)).isoformat()
            used=c.execute("""SELECT COALESCE(SUM(ri.quantity),0) q
                              FROM rental_items ri JOIN rentals r ON r.id=ri.rental_id
                              WHERE ri.product_id=? AND r.status NOT IN ('Cancelled','Returned')
                              AND r.start_date<=? AND r.end_date>=?""",
                           (p["id"],d,d)).fetchone()["q"]
            available=max(0,p["stock"]-used)
            days.append({"date":d,"available_units":available,
                         "prediction":"Available" if available>0 else "Fully Booked"})
        out.append({"equipment":p["name"],"stock":p["stock"],"forecast":days})
    c.close()
    return jsonify(out)

@app.get("/health")
def health():
    c=db(); c.execute("SELECT 1"); c.close()
    return jsonify({"status":"ok","service":"LabMarket","time":datetime.now().isoformat(timespec="seconds")})

if __name__=="__main__":
    setup()
    app.run(debug=True,host="0.0.0.0",port=5000)
