from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection
from datetime import datetime, date
import random, string, os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'secret123')

# ─── HELPERS ────────────────────────────────────────────────
def db():
    return get_db_connection()

def require_login():
    return 'user' not in session

def require_admin():
    return session.get('user', {}).get('role') != 'Admin'

def txn_id():
    return 'TXN-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

@app.context_processor
def inject_user():
    return dict(current_user=session.get('user'))

# ─── HOME ────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ─── AUTH ────────────────────────────────────────────────────
@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        action = request.form.get('action')
        conn = db(); cursor = conn.cursor(dictionary=True)
        email = request.form.get('email')
        password = request.form.get('password')

        if action == 'register':
            name = request.form.get('name')
            role = request.form.get('role', 'Customer')
            cursor.execute("SELECT id FROM Users WHERE email=%s", (email,))
            if cursor.fetchone():
                flash('Email already registered.', 'danger')
            else:
                cursor.execute(
                    "INSERT INTO Users (name, email, password, role) VALUES (%s,%s,%s,%s)",
                    (name, email, generate_password_hash(password), role))
                conn.commit()
                flash('Registered successfully! Please login.', 'success')
        elif action == 'login':
            cursor.execute("SELECT * FROM Users WHERE email=%s", (email,))
            user = cursor.fetchone()
            if user and check_password_hash(user['password'], password):
                session['user'] = {'id': user['id'], 'name': user['name'], 'role': user['role']}
                flash(f"Welcome back, {user['name']}!", 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
        cursor.close(); conn.close()
    return render_template('auth.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ─── VEHICLES ────────────────────────────────────────────────
@app.route('/vehicles')
def vehicles():
    conn = db(); cursor = conn.cursor(dictionary=True)
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    q = "SELECT * FROM Vehicles WHERE 1=1"
    params = []
    if category:
        q += " AND category=%s"; params.append(category)
    if status:
        q += " AND status=%s"; params.append(status)
    cursor.execute(q, params)
    fleet = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('vehicles.html', vehicles=fleet, category=category, status=status)

@app.route('/vehicles/add', methods=['GET', 'POST'])
def add_vehicle():
    if require_admin(): return redirect(url_for('auth'))
    if request.method == 'POST':
        f = request.form
        conn = db(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Vehicles (make,model,year,category,price_per_day,registration_num,status)
                VALUES (%s,%s,%s,%s,%s,%s,'Available')""",
                (f['make'], f['model'], f['year'], f['category'], f['price_per_day'], f['registration_num']))
            conn.commit()
            flash('Vehicle added to database!', 'success')
            return redirect(url_for('admin_vehicles'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            cursor.close(); conn.close()
    return render_template('add_vehicle.html')

@app.route('/vehicles/edit/<int:vid>', methods=['GET', 'POST'])
def edit_vehicle(vid):
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        f = request.form
        try:
            cursor.execute("""UPDATE Vehicles SET make=%s,model=%s,year=%s,category=%s,
                price_per_day=%s,registration_num=%s,status=%s WHERE id=%s""",
                (f['make'], f['model'], f['year'], f['category'], f['price_per_day'],
                 f['registration_num'], f['status'], vid))
            conn.commit()
            flash('Vehicle updated!', 'success')
            return redirect(url_for('admin_vehicles'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    cursor.execute("SELECT * FROM Vehicles WHERE id=%s", (vid,))
    v = cursor.fetchone()
    cursor.close(); conn.close()
    return render_template('edit_vehicle.html', vehicle=v)

@app.route('/vehicles/delete/<int:vid>', methods=['POST'])
def delete_vehicle(vid):
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM Vehicles WHERE id=%s", (vid,))
    conn.commit()
    cursor.close(); conn.close()
    flash('Vehicle deleted.', 'success')
    return redirect(url_for('admin_vehicles'))

# ─── BOOKING ────────────────────────────────────────────────
@app.route('/book/<int:vehicle_id>', methods=['GET', 'POST'])
def book(vehicle_id):
    if require_login(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        payment_method = request.form.get('payment_method', 'Card')
        cursor.execute("""SELECT id FROM Bookings WHERE vehicle_id=%s AND status!='Cancelled'
            AND (start_date<=%s AND end_date>=%s)""", (vehicle_id, end_date, start_date))
        if cursor.fetchone():
            flash('Vehicle is already booked for those dates!', 'danger')
        else:
            cursor.execute("SELECT price_per_day FROM Vehicles WHERE id=%s", (vehicle_id,))
            vehicle = cursor.fetchone()
            d1 = datetime.strptime(start_date, "%Y-%m-%d")
            d2 = datetime.strptime(end_date, "%Y-%m-%d")
            days = abs((d2 - d1).days) + 1
            total_price = round(days * float(vehicle['price_per_day']), 2)
            cursor.execute("""INSERT INTO Bookings (user_id,vehicle_id,start_date,end_date,total_price)
                VALUES (%s,%s,%s,%s,%s)""",
                (session['user']['id'], vehicle_id, start_date, end_date, total_price))
            booking_id = cursor.lastrowid
            cursor.execute("""INSERT INTO Payments (booking_id,amount,payment_method,status,transaction_id)
                VALUES (%s,%s,%s,'Completed',%s)""",
                (booking_id, total_price, payment_method, txn_id()))
            conn.commit()
            flash(f'Booking confirmed! Total: ${total_price:.2f} | {days} day(s)', 'success')
            return redirect(url_for('my_bookings'))
    cursor.execute("SELECT * FROM Vehicles WHERE id=%s", (vehicle_id,))
    v = cursor.fetchone()
    cursor.close(); conn.close()
    return render_template('booking.html', vehicle=v)

@app.route('/my-bookings')
def my_bookings():
    if require_login(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT b.*, v.make, v.model, v.registration_num, v.category
        FROM Bookings b JOIN Vehicles v ON b.vehicle_id=v.id
        WHERE b.user_id=%s ORDER BY b.created_at DESC""", (session['user']['id'],))
    bookings = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/booking/cancel/<int:bid>', methods=['POST'])
def cancel_booking(bid):
    if require_login(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor()
    cursor.execute("UPDATE Bookings SET status='Cancelled' WHERE id=%s AND user_id=%s",
                   (bid, session['user']['id']))
    conn.commit()
    cursor.close(); conn.close()
    flash('Booking cancelled.', 'success')
    return redirect(url_for('my_bookings'))

# ─── RENTALS ────────────────────────────────────────────────
@app.route('/rental/start/<int:bid>', methods=['POST'])
def start_rental(bid):
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor()
    cursor.execute("UPDATE Bookings SET status='Confirmed' WHERE id=%s", (bid,))
    cursor.execute("INSERT INTO Rentals (booking_id,pickup_date,status) VALUES (%s,NOW(),'Ongoing')", (bid,))
    conn.commit()
    cursor.close(); conn.close()
    flash('Rental started!', 'success')
    return redirect(url_for('admin_rentals'))

@app.route('/rental/return/<int:rid>', methods=['POST'])
def return_rental(rid):
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT r.*, b.end_date, v.price_per_day, b.id as booking_id
        FROM Rentals r JOIN Bookings b ON r.booking_id=b.id
        JOIN Vehicles v ON b.vehicle_id=v.id WHERE r.id=%s""", (rid,))
    rental = cursor.fetchone()
    extra = 0.0
    if rental:
        expected = rental['end_date']
        if isinstance(expected, str):
            expected = datetime.strptime(expected, "%Y-%m-%d").date()
        today = date.today()
        if today > expected:
            extra_days = (today - expected).days
            extra = round(extra_days * float(rental['price_per_day']) * 1.5, 2)
        c2 = conn.cursor()
        c2.execute("UPDATE Rentals SET actual_return_date=NOW(),extra_charges=%s,status='Returned' WHERE id=%s",
                   (extra, rid))
        c2.execute("UPDATE Bookings SET status='Completed' WHERE id=%s", (rental['booking_id'],))
        conn.commit()
        c2.close()
        if extra > 0:
            flash(f'Vehicle returned! Late fee applied: ${extra:.2f}', 'warning')
        else:
            flash('Vehicle returned on time!', 'success')
    cursor.close(); conn.close()
    return redirect(url_for('admin_rentals'))

# ─── BILLING ────────────────────────────────────────────────
@app.route('/invoice/<int:bid>')
def invoice(bid):
    if require_login(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT b.*, u.name as customer_name, u.email,
        v.make, v.model, v.registration_num, v.category, v.price_per_day,
        p.amount, p.payment_method, p.transaction_id, p.created_at as paid_at
        FROM Bookings b JOIN Users u ON b.user_id=u.id
        JOIN Vehicles v ON b.vehicle_id=v.id
        LEFT JOIN Payments p ON p.booking_id=b.id
        WHERE b.id=%s""", (bid,))
    invoice_data = cursor.fetchone()
    # Extra charges from rental if any
    cursor.execute("SELECT extra_charges FROM Rentals WHERE booking_id=%s", (bid,))
    rental = cursor.fetchone()
    extra = rental['extra_charges'] if rental else 0
    cursor.close(); conn.close()
    return render_template('invoice.html', inv=invoice_data, extra=extra)

# ─── DASHBOARD ────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if require_login(): return redirect(url_for('auth'))
    user = session['user']
    conn = db(); cursor = conn.cursor(dictionary=True)
    if user['role'] == 'Admin':
        cursor.execute("SELECT COUNT(*) as c FROM Users WHERE role='Customer'"); customers = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM Vehicles"); total_v = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM Bookings"); total_b = cursor.fetchone()['c']
        cursor.execute("SELECT COALESCE(SUM(amount),0) as c FROM Payments WHERE status='Completed'"); revenue = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM Rentals WHERE status='Ongoing'"); active_r = cursor.fetchone()['c']
        # Recent activity
        cursor.execute("""SELECT b.id, b.status, u.name, v.make, v.model, b.created_at, b.total_price
            FROM Bookings b JOIN Users u ON b.user_id=u.id JOIN Vehicles v ON b.vehicle_id=v.id
            ORDER BY b.created_at DESC LIMIT 8""")
        activity = cursor.fetchall()
        stats = {'customers': customers, 'vehicles': total_v, 'bookings': total_b,
                 'revenue': float(revenue), 'active_rentals': active_r}
        cursor.close(); conn.close()
        return render_template('admin_dashboard.html', stats=stats, activity=activity)
    else:
        cursor.execute("""SELECT b.*, v.make, v.model FROM Bookings b
            JOIN Vehicles v ON b.vehicle_id=v.id WHERE b.user_id=%s
            ORDER BY b.created_at DESC LIMIT 5""", (user['id'],))
        recent = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) as c FROM Bookings WHERE user_id=%s", (user['id'],)); total = cursor.fetchone()['c']
        cursor.execute("SELECT COALESCE(SUM(total_price),0) as c FROM Bookings WHERE user_id=%s AND status!='Cancelled'", (user['id'],)); spent = cursor.fetchone()['c']
        cursor.close(); conn.close()
        return render_template('user_dashboard.html', recent=recent, total=total, spent=float(spent))

# ─── ADMIN PANELS ────────────────────────────────────────────
@app.route('/admin/vehicles')
def admin_vehicles():
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Vehicles ORDER BY created_at DESC")
    vehicles = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('admin_vehicles.html', vehicles=vehicles)

@app.route('/admin/bookings')
def admin_bookings():
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT b.*, u.name as customer_name, v.make, v.model
        FROM Bookings b JOIN Users u ON b.user_id=u.id JOIN Vehicles v ON b.vehicle_id=v.id
        ORDER BY b.created_at DESC""")
    bookings = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('admin_bookings.html', bookings=bookings)

@app.route('/admin/rentals')
def admin_rentals():
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT r.*, b.start_date, b.end_date, b.total_price,
        u.name as customer_name, v.make, v.model, v.registration_num
        FROM Rentals r JOIN Bookings b ON r.booking_id=b.id
        JOIN Users u ON b.user_id=u.id JOIN Vehicles v ON b.vehicle_id=v.id
        ORDER BY r.pickup_date DESC""")
    rentals = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('admin_rentals.html', rentals=rentals)

@app.route('/admin/payments')
def admin_payments():
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT p.*, u.name as customer_name, v.make, v.model
        FROM Payments p JOIN Bookings b ON p.booking_id=b.id
        JOIN Users u ON b.user_id=u.id JOIN Vehicles v ON b.vehicle_id=v.id
        ORDER BY p.created_at DESC""")
    payments = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('admin_payments.html', payments=payments)

@app.route('/admin/users')
def admin_users():
    if require_admin(): return redirect(url_for('auth'))
    conn = db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, email, role, created_at FROM Users ORDER BY created_at DESC")
    users = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('admin_users.html', users=users)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
