from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime, timedelta
import math

app = Flask(__name__, static_folder='static', static_url_path='')
DB_NAME = "nailsalon.db"

# ==========================================
# DATABASE SETUP & INITIALIZATION
# ==========================================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            mobile_number TEXT UNIQUE NOT NULL,
            password TEXT,
            role TEXT DEFAULT 'client',
            last_appointment_date TEXT
        )
    ''')

    # 2. Stylists Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Stylists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES Users(id)
        )
    ''')

    # 3. Services Table (NEW!)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL
        )
    ''')

    # 4. Appointments Table (Now linked to Services)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stylist_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(user_id) REFERENCES Users(id),
            FOREIGN KEY(stylist_id) REFERENCES Stylists(id),
            FOREIGN KEY(service_id) REFERENCES Services(id)
        )
    ''')

    # 5. Blocked Slots Table (For stylists manual blocks)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Blocked_Slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stylist_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            FOREIGN KEY(stylist_id) REFERENCES Stylists(id)
        )
    ''')

    # --- PRE-POPULATE DATA ---

    # Pre-populate Services if empty
    cursor.execute("SELECT COUNT(*) FROM Services")
    if cursor.fetchone()[0] == 0:
        services = [
            ("Builder gel", 150),       # 2h 30m
            ("Toe gel", 30),            # 30m
            ("Acrylic nails", 150),     # 2h 30m
            ("Remove Acrylic nails", 50), # 50m (Will block two 30m slots)
            ("Refill", 105)             # 1h 45m (Will block four 30m slots)
        ]
        cursor.executemany("INSERT INTO Services (name, duration_minutes) VALUES (?, ?)", services)

    # Pre-populate Master Admin
    cursor.execute("SELECT COUNT(*) FROM Users WHERE role='admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO Users (full_name, mobile_number, password, role) VALUES (?, ?, ?, ?)", 
                       ("Admin Boss", "0000000000", "admin123", "admin"))

    # Pre-populate Stylists
    cursor.execute("SELECT COUNT(*) FROM Stylists")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO Users (full_name, mobile_number, password, role) VALUES (?, ?, ?, ?)", 
                       ("Sarah", "1111111111", "stylist123", "stylist"))
        cursor.execute("INSERT INTO Stylists (user_id, name, image_filename) VALUES (?, ?, ?)", 
                       (cursor.lastrowid, "Sarah", "sarah.jpg"))

        cursor.execute("INSERT INTO Users (full_name, mobile_number, password, role) VALUES (?, ?, ?, ?)", 
                       ("Jessica", "2222222222", "stylist123", "stylist"))
        cursor.execute("INSERT INTO Stylists (user_id, name, image_filename) VALUES (?, ?, ?)", 
                       (cursor.lastrowid, "Jessica", "jessica.jpg"))

    conn.commit()
    conn.close()

# Run initialization immediately
init_db()

# ==========================================
# TIME CALCULATION ENGINE (NEW!)
# ==========================================
def get_occupied_slots(start_time_str, duration_minutes):
    """
    Calculates how many 30-minute blocks a service takes.
    Example: 50 minutes -> math.ceil(50/30) = 2 blocks.
    Starts at 10:00 -> Returns ["10:00", "10:30"]
    """
    slots = []
    fmt = "%H:%M"
    start_time = datetime.strptime(start_time_str, fmt)
    blocks_needed = math.ceil(duration_minutes / 30.0)
    
    for i in range(blocks_needed):
        slot_time = start_time + timedelta(minutes=30 * i)
        slots.append(slot_time.strftime(fmt))
        
    return slots

# ==========================================
# API ROUTES
# ==========================================

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    mobile_number = data.get('mobile_number')
    password = data.get('password')

    conn = get_db()
    user = conn.execute("SELECT * FROM Users WHERE mobile_number = ?", (mobile_number,)).fetchone()
    
    if user:
        user_dict = dict(user)
        if user_dict['role'] in ['stylist', 'admin']:
            if password and password == user_dict.get('password'):
                if user_dict['role'] == 'stylist':
                    stylist = conn.execute("SELECT id FROM Stylists WHERE user_id = ?", (user_dict['id'],)).fetchone()
                    user_dict['stylist_profile_id'] = stylist['id'] if stylist else None
                conn.close()
                return jsonify({"status": "exists", "user": user_dict})
            else:
                conn.close()
                return jsonify({"status": "requires_password"})
        else:
            conn.close()
            return jsonify({"status": "exists", "user": user_dict})
    
    conn.close()
    return jsonify({"status": "not_found"})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO Users (full_name, mobile_number, role) VALUES (?, ?, 'client')", 
                   (data.get('full_name'), data.get('mobile_number')))
    conn.commit()
    user = conn.execute("SELECT * FROM Users WHERE mobile_number = ?", (data.get('mobile_number'),)).fetchone()
    conn.close()
    return jsonify({"status": "success", "user": dict(user)})

@app.route('/api/services', methods=['GET'])
def get_services():
    """Returns the list of all services with durations."""
    conn = get_db()
    services = conn.execute("SELECT * FROM Services").fetchall()
    conn.close()
    return jsonify([dict(s) for s in services])

@app.route('/api/stylists', methods=['GET'])
def get_stylists():
    conn = get_db()
    stylists = conn.execute("SELECT id, name, '/images/' || image_filename AS image_url FROM Stylists").fetchall()
    conn.close()
    return jsonify([dict(s) for s in stylists])

@app.route('/api/availability', methods=['GET'])
def get_availability():
    """
    Returns all dynamically blocked 30-min chunks. 
    It reads the service duration for each appointment and blocks subsequent slots.
    """
    stylist_id = request.args.get('stylist_id')
    date = request.args.get('date')
    
    conn = get_db()
    # 1. Get Client Appointments AND their Service Duration
    appts = conn.execute('''
        SELECT Appointments.time, Services.duration_minutes 
        FROM Appointments 
        JOIN Services ON Appointments.service_id = Services.id
        WHERE stylist_id = ? AND date = ?
    ''', (stylist_id, date)).fetchall()
    
    # 2. Get Stylist Manual Blocks (These are always exactly 30 mins)
    blocks = conn.execute("SELECT time FROM Blocked_Slots WHERE stylist_id = ? AND date = ?", (stylist_id, date)).fetchall()
    conn.close()

    # Calculate all occupied blocks
    client_occupied = []
    for a in appts:
        slots = get_occupied_slots(a['time'], a['duration_minutes'])
        client_occupied.extend(slots)
        
    manual_occupied = [b['time'] for b in blocks]
    
    return jsonify({
        "client_appointments": list(set(client_occupied)),
        "manual_blocks": list(set(manual_occupied))
    })

@app.route('/api/book', methods=['POST'])
def book_appointment():
    data = request.json
    today = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db()
    user = conn.execute("SELECT id FROM Users WHERE mobile_number = ?", (data.get('mobile_number'),)).fetchone()
    
    existing = conn.execute("SELECT id FROM Appointments WHERE user_id = ? AND date >= ?", (user['id'], today)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "You already have an upcoming appointment."}), 400

    conn.execute('''
        INSERT INTO Appointments (user_id, stylist_id, service_id, date, time, status) 
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (user['id'], data.get('stylist_id'), data.get('service_id'), data.get('date'), data.get('time')))
    
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/dashboard/<mobile_number>', methods=['GET'])
def get_dashboard(mobile_number):
    conn = get_db()
    user = conn.execute("SELECT * FROM Users WHERE mobile_number = ?", (mobile_number,)).fetchone()
    if not user: return jsonify({"error": "User not found"}), 404
    
    today = datetime.now().strftime("%Y-%m-%d")

    active_booking = conn.execute('''
        SELECT Appointments.id, Appointments.date, Appointments.time, Appointments.status, 
               Stylists.name as stylist_name, Services.name as service_name
        FROM Appointments 
        JOIN Stylists ON Appointments.stylist_id = Stylists.id
        JOIN Services ON Appointments.service_id = Services.id
        WHERE Appointments.user_id = ? AND date >= ?
    ''', (user['id'], today)).fetchone()

    conn.close()
    return jsonify({
        "user": dict(user),
        "has_active_booking": True if active_booking else False,
        "active_booking_details": dict(active_booking) if active_booking else None
    })

# --- Management & Deletion Routes ---
@app.route('/api/appointment/<int:appt_id>', methods=['DELETE'])
def delete_appointment(appt_id):
    conn = get_db()
    conn.execute("DELETE FROM Appointments WHERE id = ?", (appt_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route('/api/appointment/<int:appt_id>/confirm', methods=['PUT'])
def confirm_appointment(appt_id):
    conn = get_db()
    conn.execute("UPDATE Appointments SET status = 'confirmed' WHERE id = ?", (appt_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "confirmed"})

@app.route('/api/stylist/slots/toggle', methods=['POST'])
def toggle_slot():
    data = request.json
    conn = get_db()
    user = conn.execute("SELECT id FROM Users WHERE mobile_number = ?", (data.get('mobile_number'),)).fetchone()
    stylist = conn.execute("SELECT id FROM Stylists WHERE user_id = ?", (user['id'],)).fetchone()
    
    existing = conn.execute("SELECT id FROM Blocked_Slots WHERE stylist_id = ? AND date = ? AND time = ?", 
                            (stylist['id'], data.get('date'), data.get('time'))).fetchone()
    
    if existing:
        conn.execute("DELETE FROM Blocked_Slots WHERE id = ?", (existing['id'],))
    else:
        conn.execute("INSERT INTO Blocked_Slots (stylist_id, date, time) VALUES (?, ?, ?)",
                     (stylist['id'], data.get('date'), data.get('time')))
    conn.commit()
    conn.close()
    return jsonify({"status": "toggled"})

@app.route('/api/stylist/slots/toggle_day', methods=['POST'])
def toggle_day():
    data = request.json
    action = data.get('action')
    conn = get_db()
    user = conn.execute("SELECT id FROM Users WHERE mobile_number = ?", (data.get('mobile_number'),)).fetchone()
    stylist = conn.execute("SELECT id FROM Stylists WHERE user_id = ?", (user['id'],)).fetchone()
    
    if action == 'unblock':
        conn.execute("DELETE FROM Blocked_Slots WHERE stylist_id = ? AND date = ?", (stylist['id'], data.get('date')))
    elif action == 'block':
        # Block all 10:00 to 19:30 slots (ignoring what is already booked/blocked to prevent errors)
        for h in range(10, 20):
            for m in ["00", "30"]:
                t = f"{h}:{m}"
                conn.execute("INSERT OR IGNORE INTO Blocked_Slots (stylist_id, date, time) VALUES (?, ?, ?)", 
                             (stylist['id'], data.get('date'), t))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/management/appointments', methods=['GET'])
def get_management_appointments():
    mobile_number = request.args.get('mobile_number')
    filter_type = request.args.get('filter', 'today')
    conn = get_db()
    user = conn.execute("SELECT id, role FROM Users WHERE mobile_number = ?", (mobile_number,)).fetchone()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    query = '''
        SELECT Appointments.id, Appointments.date, Appointments.time, Appointments.status,
               Users.full_name as client_name, Users.mobile_number as client_mobile,
               Stylists.name as stylist_name, Services.name as service_name
        FROM Appointments
        JOIN Users ON Appointments.user_id = Users.id
        JOIN Stylists ON Appointments.stylist_id = Stylists.id
        JOIN Services ON Appointments.service_id = Services.id
        WHERE 1=1
    '''
    params = []
    
    if user['role'] == 'stylist':
        stylist = conn.execute("SELECT id FROM Stylists WHERE user_id = ?", (user['id'],)).fetchone()
        query += " AND Appointments.stylist_id = ?"
        params.append(stylist['id'])
        
    if filter_type == 'today':
        query += " AND Appointments.date = ?"
        params.append(today_str)
    else:
        query += " AND Appointments.date >= ?"
        params.append(today_str)
        
    query += " ORDER BY Appointments.date ASC, Appointments.time ASC"
    appointments = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(a) for a in appointments])

@app.route('/')
def serve_frontend():
    return app.send_static_file('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)