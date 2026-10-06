from flask_mysqldb import MySQL
from flask import (Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file,
                   send_from_directory, abort, Response)
from werkzeug.security import generate_password_hash, check_password_hash
import os
import uuid
from werkzeug.utils import secure_filename
import csv
from io import StringIO, BytesIO
import pandas as pd
import smtplib
import MySQLdb
from datetime import timedelta, date

# Load settings from a local .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# PDF export is optional: it needs the pdfkit package and the wkhtmltopdf program
try:
    import pdfkit
except ImportError:
    pdfkit = None


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Task priority levels, most important first
PRIORITIES = ['Urgent', 'High', 'Medium', 'Low']
DEFAULT_PRIORITY = 'Medium'
PRIORITY_COLORS = {'Urgent': 'danger', 'High': 'warning', 'Medium': 'primary', 'Low': 'secondary'}
PRIORITY_ORDER_SQL = "FIELD(tasks.priority, 'Urgent', 'High', 'Medium', 'Low')"


def clean_priority(value):
    return value if value in PRIORITIES else DEFAULT_PRIORITY


# Task statuses, in Kanban board column order
STATUSES = ['To Do', 'In Progress', 'In Review', 'Completed']
DEFAULT_STATUS = 'To Do'
STATUS_COLORS = {'To Do': 'secondary', 'In Progress': 'primary', 'In Review': 'info', 'Completed': 'success'}

# Function to switch language
@app.route('/switch_language/<language>')
def switch_language(language):
    session['lang'] = language
    return redirect(request.referrer or url_for('index'))

# Get the selected language or default to English
def get_language():
    return session.get('lang', 'en')



@app.context_processor
def inject_globals():
    return dict(lang=get_language(), priorities=PRIORITIES, priority_colors=PRIORITY_COLORS,
                statuses=STATUSES, status_colors=STATUS_COLORS)


# MySQL Configurations (set these in the environment or in a .env file)
app.config['MYSQL_HOST'] = os.environ.get('MYSQL_HOST', 'localhost')
app.config['MYSQL_PORT'] = int(os.environ.get('MYSQL_PORT', 3306))
app.config['MYSQL_USER'] = os.environ.get('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD', '')
app.config['MYSQL_DB'] = os.environ.get('MYSQL_DB', 'task_management')

mysql = MySQL(app)

# Uploaded files are saved in UPLOAD_DIR; the database stores them as "uploads/<name>"
UPLOAD_FOLDER = 'uploads/'
UPLOAD_DIR = os.path.join(app.root_path, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)


def is_admin():
    return 'user_id' in session and bool(session.get('is_admin'))


# SQL condition for tasks the logged-in user may see: created by them, assigned to them, or to one of their groups
TASK_VISIBLE_SQL = """(tasks.user_id = %s OR tasks.assigned_user_id = %s
    OR tasks.assigned_group_id IN (SELECT group_id FROM user_groups WHERE user_id = %s))"""


def visible_task_filter():
    """Returns (sql, params) restricting tasks to those the current user may see. Admins see all tasks."""
    if is_admin():
        return "1=1", []
    user_id = session['user_id']
    return TASK_VISIBLE_SQL, [user_id, user_id, user_id]


def can_access_task(cur, task_id):
    condition, params = visible_task_filter()
    cur.execute(f"SELECT 1 FROM tasks WHERE id = %s AND {condition}", [task_id] + params)
    return cur.fetchone() is not None


# Insert notification when assigning a task to a user
def notify_task_assignment(task_id, assigned_user_id, priority=DEFAULT_PRIORITY):
    message = f"You have been assigned a new {priority} priority task."
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO notifications (user_id, task_id, message) VALUES (%s, %s, %s)",
                (assigned_user_id, task_id, message))
    mysql.connection.commit()
    cur.close()


# Insert notifications when a task's status changes: to the assigned user, or to every member of the
# assigned group. The person who made the change is not notified.
def notify_task_status_change(task_id, new_status):
    cur = mysql.connection.cursor()
    cur.execute("SELECT assigned_user_id, assigned_group_id FROM tasks WHERE id = %s", [task_id])
    assigned_user_id, assigned_group_id = cur.fetchone()

    if assigned_user_id:
        recipients = [assigned_user_id]
        message = f"Your task (ID: {task_id}) has been marked as {new_status}."
    elif assigned_group_id:
        cur.execute("SELECT user_id FROM user_groups WHERE group_id = %s", [assigned_group_id])
        recipients = [row[0] for row in cur.fetchall()]
        message = f"Your group's task (ID: {task_id}) has been marked as {new_status}."
    else:
        recipients = []

    for user_id in recipients:
        if user_id != session.get('user_id'):
            cur.execute("INSERT INTO notifications (user_id, task_id, message) VALUES (%s, %s, %s)",
                        (user_id, task_id, message))
    mysql.connection.commit()
    cur.close()


# Route to configure database settings
@app.route('/settings/database', methods=['GET', 'POST'])
def database_settings():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()

    # If the form is submitted
    if request.method == 'POST':
        db_host = request.form.get('db_host')
        db_port = request.form.get('db_port')
        db_user = request.form.get('db_user')
        db_password = request.form.get('db_password')
        db_name = request.form.get('db_name')

        # Save settings to database
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('db_host', %s)", [db_host])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('db_port', %s)", [db_port])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('db_user', %s)", [db_user])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('db_password', %s)", [db_password])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('db_name', %s)", [db_name])
        mysql.connection.commit()

        flash("Database settings updated successfully!")

    # Fetch the current settings from the database
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'db_host'")
    db_host = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'db_port'")
    db_port = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'db_user'")
    db_user = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'db_password'")
    db_password = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'db_name'")
    db_name = cur.fetchone()[0] if cur.rowcount > 0 else ''

    cur.close()

    return render_template('database_settings.html', db_host=db_host, db_port=db_port, db_user=db_user, db_password=db_password, db_name=db_name)

# Route to test the database connection
@app.route('/settings/test_database', methods=['POST'])
def test_database():
    if not is_admin():
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    db_host = request.form.get('db_host')
    db_port = request.form.get('db_port')
    db_user = request.form.get('db_user')
    db_password = request.form.get('db_password')
    db_name = request.form.get('db_name')

    try:
        # Attempt to connect to the database
        connection = MySQLdb.connect(host=db_host, user=db_user, passwd=db_password, db=db_name, port=int(db_port))
        connection.close()
        flash("Database connection successful!")
    except Exception as e:
        flash(f"Error connecting to the database: {str(e)}")

    return redirect(url_for('database_settings'))

##Send Test Email
@app.route('/settings/test_email', methods=['POST'])
def test_email():
    if not is_admin():
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    smtp_server = request.form.get('smtp_server')
    smtp_port = request.form.get('smtp_port')
    smtp_user = request.form.get('smtp_user')
    smtp_password = request.form.get('smtp_password')
    use_tls = 'use_tls' in request.form
    test_email = request.form.get('test_email')

    try:
        # Step 1: Establish connection to the SMTP server
        server = smtplib.SMTP(smtp_server, int(smtp_port))

        # Step 2: Start TLS if required
        if use_tls:
            server.starttls()

        # Step 3: Login to the SMTP server
        server.login(smtp_user, smtp_password)

        # Step 4: Send the email
        message = "Subject: Test Email\n\nThis is a test email from the task manager."
        server.sendmail(smtp_user, test_email, message)

        # Step 5: Close the connection
        server.quit()

        flash("Test email sent successfully!")
    except Exception as e:
        flash(f"Error sending test email: {str(e)}")

    return redirect(url_for('email_settings'))


# Route to configure email settings
@app.route('/settings/email', methods=['GET', 'POST'])
def email_settings():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()

    # If the form is submitted
    if request.method == 'POST':
        smtp_server = request.form.get('smtp_server')
        smtp_port = request.form.get('smtp_port')
        smtp_user = request.form.get('smtp_user')
        smtp_password = request.form.get('smtp_password')
        use_tls = 'use_tls' in request.form

        # Save settings to database
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('smtp_server', %s)", [smtp_server])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('smtp_port', %s)", [smtp_port])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('smtp_user', %s)", [smtp_user])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('smtp_password', %s)", [smtp_password])
        cur.execute("REPLACE INTO system_settings (setting_name, setting_value) VALUES ('use_tls', %s)", [str(use_tls)])
        mysql.connection.commit()

        flash("Email settings updated successfully!")

    # Fetch the current settings from the database
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'smtp_server'")
    smtp_server = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'smtp_port'")
    smtp_port = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'smtp_user'")
    smtp_user = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'smtp_password'")
    smtp_password = cur.fetchone()[0] if cur.rowcount > 0 else ''
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_name = 'use_tls'")
    use_tls = cur.fetchone()[0] == 'True' if cur.rowcount > 0 else False

    cur.close()

    return render_template('email_settings.html', smtp_server=smtp_server, smtp_port=smtp_port, smtp_user=smtp_user, smtp_password=smtp_password, use_tls=use_tls)



#Notifications
@app.route('/fetch_notifications')
def fetch_notifications():
    if 'user_id' not in session:
        return jsonify([])

    user_id = session['user_id']
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, message, is_read, created_at FROM notifications
        WHERE user_id = %s AND is_read = 0
        ORDER BY created_at DESC
    """, (user_id,))
    notifications = cur.fetchall()
    cur.close()

    notifications_list = []
    for notification in notifications:
        notifications_list.append({
            'id': notification[0],
            'message': notification[1],
            'is_read': notification[2],
            'created_at': notification[3].strftime('%Y-%m-%d %H:%M:%S')
        })

    return jsonify(notifications_list)

#Notification as read
@app.route('/notifications/mark_read/<int:notification_id>', methods=['POST', 'GET'])
def mark_notification_as_read(notification_id):
    if 'user_id' not in session:
        flash("Please log in to view your notifications.")
        return redirect(url_for('login'))

    user_id = session['user_id']

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE notifications
        SET is_read = TRUE
        WHERE id = %s AND user_id = %s
    """, (notification_id, user_id))

    mysql.connection.commit()
    cur.close()

    flash("Notification marked as read.")
    return redirect(url_for('notifications'))


### Route to unread count
@app.context_processor
def inject_unread_notifications():
    if 'user_id' in session:
        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT COUNT(*)
                FROM notifications
                WHERE user_id = %s AND is_read = FALSE
            """, [session['user_id']])

            unread_notifications = cur.fetchone()[0]
            cur.close()
            return dict(unread_notifications=unread_notifications)
        except MySQLdb.Error:
            # Keep error pages renderable when the database is unavailable
            pass
    return dict(unread_notifications=0)


# Name shown for a task's assignee: the user, or the group
ASSIGNED_TO_SQL = """COALESCE((SELECT username FROM users WHERE id = tasks.assigned_user_id),
                              (SELECT name FROM groupss WHERE id = tasks.assigned_group_id))"""


def format_date(value):
    return value.strftime('%Y-%m-%d') if value else None


#route to get info button
@app.route('/get_task_info/<int:task_id>', methods=['GET'])
def get_task_info(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    # Query the database for the task details
    cur = mysql.connection.cursor()
    if not can_access_task(cur, task_id):
        cur.close()
        return jsonify({'error': 'Task not found'}), 404

    cur.execute(f"""
        SELECT title, description, status, task_date, {ASSIGNED_TO_SQL} as assigned_to,
               notes, file_path, priority
        FROM tasks WHERE id = %s
    """, (task_id,))
    task = cur.fetchone()
    cur.close()

    # Format task data as a JSON response
    file_path = task[6]
    task_data = {
        'title': task[0],
        'description': task[1],
        'status': task[2],
        'task_date': format_date(task[3]),
        'assigned_to': task[4],
        'notes': task[5],
        'file_url': url_for('uploaded_file', filename=os.path.basename(file_path)) if file_path else None,
        'priority': task[7]
    }
    return jsonify(task_data)


# Serve an attached file to users who can see the task it belongs to
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    condition, params = visible_task_filter()
    cur = mysql.connection.cursor()
    cur.execute(f"SELECT 1 FROM tasks WHERE file_path = %s AND {condition}", [UPLOAD_FOLDER + filename] + params)
    allowed = cur.fetchone() is not None
    cur.close()

    if not allowed:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename)


# Home route to display all tasks
@app.route('/')
def index():
    if 'user_id' not in session:
        flash("Please log in to view your tasks.")
        return redirect(url_for('login'))

    # Tasks and calendar events are loaded by the page from /tasks_json and /calendar_events
    return render_template('index.html')

### Task list route (used by the infinite scroll on the home page) ###
@app.route('/tasks_json', methods=['GET'])
def tasks_json():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    user_id = session['user_id']
    page = request.args.get('page', 1, type=int)
    priority = request.args.get('priority', '')
    per_page = 10  # Number of tasks per page
    offset = (page - 1) * per_page

    # Tasks the user created, or that are assigned to them or their groups
    query = f"""
        SELECT id, title, description, status, task_date, {ASSIGNED_TO_SQL} as assigned_to, priority
        FROM tasks
        WHERE {TASK_VISIBLE_SQL}
    """
    params = [user_id, user_id, user_id]
    if priority in PRIORITIES:
        query += " AND tasks.priority = %s"
        params.append(priority)
    query += f" ORDER BY {PRIORITY_ORDER_SQL}, tasks.task_date LIMIT %s OFFSET %s"
    params += [per_page, offset]

    cur = mysql.connection.cursor()
    cur.execute(query, params)
    tasks = cur.fetchall()
    cur.close()

    # Convert tasks to a dictionary list for JSON response
    task_list = [{
        'id': task[0],
        'title': task[1],
        'description': task[2],
        'status': task[3],
        'task_date': format_date(task[4]),
        'assigned_to': task[5],
        'priority': task[6]
    } for task in tasks]

    return jsonify({'tasks': task_list, 'has_more': len(tasks) == per_page})


###Calendar route###
@app.route('/calendar_events', methods=['GET'])
def calendar_events():
    if 'user_id' not in session:
        return jsonify([]), 403

    user_id = session['user_id']
    # FullCalendar sends the visible range as ISO datetimes; only the date part is needed
    start = request.args.get('start', '')[:10]
    end = request.args.get('end', '')[:10]

    query = f"""
        SELECT id, title, description, status, task_date, {ASSIGNED_TO_SQL} as assigned_to, priority
        FROM tasks
        WHERE {TASK_VISIBLE_SQL}
    """
    params = [user_id, user_id, user_id]
    if start and end:
        query += " AND tasks.task_date >= %s AND tasks.task_date < %s"
        params += [start, end]

    cur = mysql.connection.cursor()
    cur.execute(query, params)
    tasks = cur.fetchall()
    cur.close()

    calendar_colors = {'Urgent': '#dc3545', 'High': '#fd7e14', 'Medium': '#0d6efd', 'Low': '#6c757d'}
    events = [{
        'id': task[0],
        'title': task[1],
        'start': format_date(task[4]),
        'color': calendar_colors.get(task[6], '#0d6efd'),
        'extendedProps': {
            'description': task[2],
            'status': task[3],
            'assigned_to': task[5],
            'priority': task[6]
        }
    } for task in tasks if task[4]]

    return jsonify(events)


### Kanban board ###
@app.route('/board')
def board():
    if 'user_id' not in session:
        flash("Please log in to view your tasks.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    priority = request.args.get('priority', '')

    query = f"""
        SELECT id, title, status, task_date, {ASSIGNED_TO_SQL} as assigned_to, priority
        FROM tasks
        WHERE {TASK_VISIBLE_SQL}
    """
    params = [user_id, user_id, user_id]
    if priority in PRIORITIES:
        query += " AND tasks.priority = %s"
        params.append(priority)
    query += f" ORDER BY {PRIORITY_ORDER_SQL}, tasks.task_date"

    cur = mysql.connection.cursor()
    cur.execute(query, params)
    tasks = cur.fetchall()
    cur.close()

    # Group tasks into one column per status; unknown statuses go in the first column
    columns = {status: [] for status in STATUSES}
    for task in tasks:
        columns.get(task[2], columns[DEFAULT_STATUS]).append(task)

    return render_template('board.html', columns=columns, selected_priority=priority, today=date.today())


# Change a task's status (used when a card is dragged to another column)
@app.route('/update_task_status/<int:task_id>', methods=['POST'])
def update_task_status(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    # Only accept JSON, which a cross-site form post cannot send
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in STATUSES:
        return jsonify({'error': 'Invalid status'}), 400

    cur = mysql.connection.cursor()
    if not can_access_task(cur, task_id):
        cur.close()
        return jsonify({'error': 'Task not found'}), 404

    cur.execute("SELECT status FROM tasks WHERE id = %s", [task_id])
    old_status = cur.fetchone()[0]
    cur.execute("UPDATE tasks SET status = %s WHERE id = %s", (status, task_id))
    mysql.connection.commit()
    cur.close()

    if status != old_status:
        notify_task_status_change(task_id, status)

    return jsonify({'id': task_id, 'status': status})

# Route to add a new task
@app.route('/add_task', methods=['GET', 'POST'])
def add_task():
    if 'user_id' not in session:
        flash("Please log in to add a task.")
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Get form data
        title = request.form.get('title')
        description = request.form.get('description')
        task_date = request.form.get('task_date')
        company_id = request.form.get('company_id')
        branch_id = request.form.get('branch_id')
        section_id = request.form.get('section_id')
        assigned_user_id = request.form.get('assigned_user_id')
        assigned_group_id = request.form.get('assigned_group_id')  # Added for group assignment
        notes = request.form.get('notes')
        priority = clean_priority(request.form.get('priority'))
        user_id = session['user_id']

        # Ensure either user or group is assigned, but not both
        if not assigned_user_id and not assigned_group_id:
            flash("Please assign the task to either a user or a group.")
            return redirect(url_for('add_task'))

        if assigned_user_id and assigned_group_id:
            flash("Please assign the task to only one: either a user or a group, not both.")
            return redirect(url_for('add_task'))

        # File upload handling
        file = request.files.get('file')
        file_path = None
        if file and file.filename != '':
            # Prefix with a random id so files with the same name don't overwrite each other
            filename = f"{uuid.uuid4().hex[:12]}_{secure_filename(file.filename)}"
            file.save(os.path.join(UPLOAD_DIR, filename))
            file_path = UPLOAD_FOLDER + filename

        # Insert task into the database
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO tasks (title, description, task_date, company_id, branch_id, section_id, file_path, assigned_user_id, assigned_group_id, notes, user_id, priority, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            title, description, task_date, company_id, branch_id, section_id, file_path,
            assigned_user_id if assigned_user_id else None,
            assigned_group_id if assigned_group_id else None,
            notes, user_id, priority, DEFAULT_STATUS
        ))

        task_id = cur.lastrowid  # Get the ID of the newly created task
        mysql.connection.commit()

        # Notify the assigned user or group
        if assigned_user_id:
            notify_task_assignment(task_id, assigned_user_id, priority)
        elif assigned_group_id:
            notify_group(task_id, assigned_group_id,
                         f"A new {priority} priority task (ID: {task_id}) has been assigned to your group.")

        cur.close()

        flash("Task added successfully!")
        return redirect(url_for('index'))

    # Fetch companies, users, and groups for dropdowns
    cur = mysql.connection.cursor()

    # Fetch companies
    cur.execute("SELECT * FROM companies")
    companies = cur.fetchall()

    # Fetch users with email
    cur.execute("SELECT id, username, email FROM users")
    users = cur.fetchall()

    # Fetch groups
    cur.execute("SELECT id, name FROM groupss")
    groups = cur.fetchall()

    cur.close()

    # The calendar links here with ?date=YYYY-MM-DD to pre-fill the task date
    return render_template('add_task.html', companies=companies, users=users, groups=groups,
                           task_date=request.args.get('date', ''), default_priority=DEFAULT_PRIORITY)

# Send a notification to every member of a group
def notify_group(task_id, group_id, message):
    cur = mysql.connection.cursor()

    # Get the users associated with the group
    cur.execute("SELECT user_id FROM user_groups WHERE group_id = %s", [group_id])
    users_in_group = cur.fetchall()

    # Insert a notification for each member
    for (user_id,) in users_in_group:
        cur.execute("""
            INSERT INTO notifications (user_id, task_id, message)
            VALUES (%s, %s, %s)
        """, (user_id, task_id, message))

    mysql.connection.commit()
    cur.close()


# Route to get branches based on the selected company
@app.route('/get_branches/<int:company_id>')
def get_branches(company_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM branches WHERE company_id = %s", [company_id])
    branches = cur.fetchall()
    cur.close()
    return jsonify({'branches': [{'id': b[0], 'name': b[1]} for b in branches]})

# Route to get sections based on the selected branch
@app.route('/get_sections/<int:branch_id>')
def get_sections(branch_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM sections WHERE branch_id = %s", [branch_id])
    sections = cur.fetchall()
    cur.close()
    return jsonify({'sections': [{'id': s[0], 'name': s[1]} for s in sections]})

# Route to mark task as completed
@app.route('/complete_task/<int:task_id>', methods=['POST'])
def complete_task(task_id):
    if 'user_id' not in session:
        return "Unauthorized", 401

    cur = mysql.connection.cursor()

    # The creator, the assignee, members of the assigned group, and admins can complete a task
    if not can_access_task(cur, task_id):
        cur.close()
        flash("You don't have permission to update this task.")
        return redirect(request.referrer or url_for('index'))

    # Update task status to "Completed"
    cur.execute("UPDATE tasks SET status = 'Completed' WHERE id = %s", [task_id])
    mysql.connection.commit()
    cur.close()

    notify_task_status_change(task_id, 'Completed')

    return redirect(request.referrer or url_for('index'))


# Delete task
@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if 'user_id' not in session:
        return "Unauthorized", 401

    # Only the creator or an admin can delete a task
    cur = mysql.connection.cursor()
    if is_admin():
        cur.execute("DELETE FROM tasks WHERE id = %s", [task_id])
    else:
        cur.execute("DELETE FROM tasks WHERE id = %s AND user_id = %s", (task_id, session['user_id']))
    deleted = cur.rowcount > 0
    mysql.connection.commit()
    cur.close()

    flash("Task deleted." if deleted else "Only the task's creator or an admin can delete it.")
    return redirect(request.referrer or url_for('index'))


###Edit task route###
@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        flash("Please log in to edit a task.")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    if not can_access_task(cur, task_id):
        cur.close()
        flash("Task not found or you don't have permission to edit it.")
        return redirect(url_for('index'))

    cur.execute("SELECT title, description, task_date, assigned_user_id, status, priority, assigned_group_id "
                "FROM tasks WHERE id = %s", (task_id,))
    task = cur.fetchone()

    if request.method == 'POST':
        # Get form data
        title = request.form['title']
        description = request.form['description']
        task_date = request.form['task_date']
        status = request.form['status'] if request.form.get('status') in STATUSES else task[4]
        priority = clean_priority(request.form.get('priority'))

        # The assignee is sent as "user:<id>" or "group:<id>"
        assign_type, _, assign_id = request.form.get('assignee', '').partition(':')
        if assign_type not in ('user', 'group') or not assign_id.isdigit():
            cur.close()
            flash("Please assign the task to a user or a group.")
            return redirect(url_for('edit_task', task_id=task_id))
        assigned_user_id = int(assign_id) if assign_type == 'user' else None
        assigned_group_id = int(assign_id) if assign_type == 'group' else None

        # Update task in the database
        cur.execute("""
            UPDATE tasks
            SET title = %s, description = %s, task_date = %s, assigned_user_id = %s, assigned_group_id = %s,
                status = %s, priority = %s
            WHERE id = %s
        """, (title, description, task_date, assigned_user_id, assigned_group_id, status, priority, task_id))

        mysql.connection.commit()
        cur.close()

        # Notify whoever the task was reassigned to, or the assignees if only the status changed
        if assigned_user_id and assigned_user_id != task[3]:
            notify_task_assignment(task_id, assigned_user_id, priority)
        elif assigned_group_id and assigned_group_id != task[6]:
            notify_group(task_id, assigned_group_id,
                         f"A {priority} priority task (ID: {task_id}) has been assigned to your group.")
        elif status != task[4]:
            notify_task_status_change(task_id, status)

        flash("Task updated successfully!")
        return redirect(url_for('index'))

    # Fetch all users and groups for reassigning the task
    cur.execute("SELECT id, username, email FROM users")
    users = cur.fetchall()
    cur.execute("SELECT id, name FROM groupss")
    groups = cur.fetchall()

    cur.close()

    # Pass task_id to the template along with task, users and groups
    return render_template('edit_task.html', task=task, users=users, groups=groups, task_id=task_id)


###Settings Route####
@app.route('/settings')
def settings():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    return render_template('settings.html')


#User registration route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']  # Capture email from the form
        password = request.form['password']
        hashed_password = generate_password_hash(password)

        cur = mysql.connection.cursor()

        # Insert the new user into the users table, including email
        try:
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                        (username, email, hashed_password))
            mysql.connection.commit()
        except MySQLdb.IntegrityError:
            flash("That username or email is already registered.")
            return render_template('register.html')
        finally:
            cur.close()

        flash("Registration successful! Please log in.")
        return redirect(url_for('login'))

    return render_template('register.html')

#User login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT id, username, password, is_admin FROM users WHERE username = %s", [username])
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[2], password):  # user[2] is the hashed password
            session.clear()
            session.permanent = True  # Applies PERMANENT_SESSION_LIFETIME
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['is_admin'] = bool(user[3])
            flash("Login successful!")
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password.")

    return render_template('login.html')

##Notifications route##
@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        flash("Please log in to view your notifications.")
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Fetch notifications for the logged-in user
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, message, is_read, created_at
        FROM notifications
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, [user_id])

    notifications = cur.fetchall()
    cur.close()

    return render_template('notifications.html', notifications=notifications)

#Route Setting users Groups
@app.route('/settings/groups', methods=['GET', 'POST'])
def manage_groups():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()

    # Create a new group if the form is submitted
    if request.method == 'POST':
        group_name = request.form['group_name']
        cur.execute("INSERT INTO groupss (name) VALUES (%s)", [group_name])
        mysql.connection.commit()
        flash("Group created successfully!")

    # Fetch all groups with their users
    cur.execute("""
        SELECT g.id AS group_id, g.name AS group_name, u.id AS user_id, u.username AS user_name
        FROM groupss g
        LEFT JOIN user_groups ug ON g.id = ug.group_id
        LEFT JOIN users u ON u.id = ug.user_id
        ORDER BY g.name
    """)
    groups_data = cur.fetchall()

    # Organize groups and their users in a dictionary
    groups = {}
    for group_id, group_name, user_id, user_name in groups_data:
        if group_id not in groups:
            groups[group_id] = {
                'name': group_name,
                'users': []
            }
        if user_id:
            groups[group_id]['users'].append({'id': user_id, 'name': user_name})

    # Fetch all users for the "add user to group" dropdown
    cur.execute("SELECT id, username FROM users")
    users = cur.fetchall()

    cur.close()

    return render_template('manage_groups.html', groups=groups, users=users)


### Route to all notification has been read
@app.route('/notifications/mark_all_read', methods=['POST'])
def mark_all_notifications_as_read():
    if 'user_id' not in session:
        flash("Please log in to view your notifications.")
        return redirect(url_for('login'))

    user_id = session['user_id']

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE notifications
        SET is_read = TRUE
        WHERE user_id = %s
    """, (user_id,))

    mysql.connection.commit()
    cur.close()

    flash("All notifications marked as read.")
    return redirect(url_for('notifications'))


# Route to edit group
@app.route('/settings/groups/edit/<int:group_id>', methods=['GET', 'POST'])
def edit_group(group_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        group_name = request.form['group_name']
        cur.execute("UPDATE groupss SET name = %s WHERE id = %s", [group_name, group_id])
        mysql.connection.commit()
        cur.close()
        flash("Group updated successfully!")
        return redirect(url_for('manage_groups'))

    # Fetch the group name to populate the form
    cur.execute("SELECT name FROM groupss WHERE id = %s", [group_id])
    group = cur.fetchone()
    cur.close()

    return render_template('edit_group.html', group=group, group_id=group_id)


#Route to delete group
@app.route('/settings/groups/delete/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM groupss WHERE id = %s", [group_id])
    mysql.connection.commit()
    cur.close()

    flash("Group deleted successfully!")
    return redirect(url_for('manage_groups'))


# Route to add a user to a group
@app.route('/settings/groups/add_user', methods=['POST'])
def add_user_to_group():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    user_id = request.form['user_id']
    group_id = request.form['group_id']

    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO user_groups (user_id, group_id) VALUES (%s, %s)", [user_id, group_id])
    mysql.connection.commit()
    cur.close()

    flash("User added to group successfully!")
    return redirect(url_for('manage_groups'))

#User profile
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("Please log in to view your profile.")
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Fetch user information
    cur = mysql.connection.cursor()
    cur.execute("SELECT username, email FROM users WHERE id = %s", [user_id])
    user_info = cur.fetchone()  # user_info[0] = username, user_info[1] = email

    # Fetch tasks assigned to this user or to one of their groups
    cur.execute(f"""
        SELECT id, title, description, task_date, status, priority
        FROM tasks
        WHERE assigned_user_id = %s
           OR assigned_group_id IN (SELECT group_id FROM user_groups WHERE user_id = %s)
        ORDER BY {PRIORITY_ORDER_SQL}, task_date
    """, [user_id, user_id])
    assigned_tasks = cur.fetchall()

    cur.close()

    return render_template('profile.html', user_info=user_info, assigned_tasks=assigned_tasks)

#User logout
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('login'))


################# Company Management ##################
@app.route('/settings/companies', methods=['GET', 'POST'])
def manage_companies():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form['name']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO companies (name) VALUES (%s)", [name])
        mysql.connection.commit()
        cur.close()
        flash("Company added successfully!")

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM companies")
    companies = cur.fetchall()
    cur.close()

    return render_template('manage_companies.html', companies=companies)


@app.route('/settings/companies/delete/<int:company_id>', methods=['POST'])
def delete_company(company_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM companies WHERE id = %s", [company_id])
    mysql.connection.commit()
    cur.close()
    flash("Company deleted successfully!")

    return redirect(url_for('manage_companies'))


@app.route('/settings/companies/edit/<int:company_id>', methods=['GET', 'POST'])
def edit_company(company_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM companies WHERE id = %s", [company_id])
    company = cur.fetchone()

    if request.method == 'POST':
        name = request.form['name']
        cur.execute("UPDATE companies SET name = %s WHERE id = %s", [name, company_id])
        mysql.connection.commit()
        cur.close()
        flash("Company updated successfully!")
        return redirect(url_for('manage_companies'))

    cur.close()
    return render_template('edit_company.html', company=company)


###Route for Managing Branches###
@app.route('/settings/branches', methods=['GET', 'POST'])
def manage_branches():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form['name']
        company_id = request.form['company_id']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO branches (name, company_id) VALUES (%s, %s)", [name, company_id])
        mysql.connection.commit()
        cur.close()
        flash("Branch added successfully!")

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM branches")
    branches = cur.fetchall()

    cur.execute("SELECT * FROM companies")
    companies = cur.fetchall()

    cur.close()
    return render_template('manage_branches.html', branches=branches, companies=companies)


@app.route('/settings/branches/delete/<int:branch_id>', methods=['POST'])
def delete_branch(branch_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM branches WHERE id = %s", [branch_id])
    mysql.connection.commit()
    cur.close()
    flash("Branch deleted successfully!")

    return redirect(url_for('manage_branches'))


@app.route('/settings/branches/edit/<int:branch_id>', methods=['GET', 'POST'])
def edit_branch(branch_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM branches WHERE id = %s", [branch_id])
    branch = cur.fetchone()

    cur.execute("SELECT * FROM companies")
    companies = cur.fetchall()

    if request.method == 'POST':
        name = request.form['name']
        company_id = request.form['company_id']
        cur.execute("UPDATE branches SET name = %s, company_id = %s WHERE id = %s", [name, company_id, branch_id])
        mysql.connection.commit()
        cur.close()
        flash("Branch updated successfully!")
        return redirect(url_for('manage_branches'))

    cur.close()
    return render_template('edit_branch.html', branch=branch, companies=companies)

###Route for Managing Sections###
@app.route('/settings/sections', methods=['GET', 'POST'])
def manage_sections():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form['name']
        branch_id = request.form['branch_id']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO sections (name, branch_id) VALUES (%s, %s)", [name, branch_id])
        mysql.connection.commit()
        cur.close()
        flash("Section added successfully!")

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM sections")
    sections = cur.fetchall()

    cur.execute("SELECT * FROM branches")
    branches = cur.fetchall()

    cur.close()
    return render_template('manage_sections.html', sections=sections, branches=branches)


@app.route('/settings/sections/delete/<int:section_id>', methods=['POST'])
def delete_section(section_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM sections WHERE id = %s", [section_id])
    mysql.connection.commit()
    cur.close()
    flash("Section deleted successfully!")

    return redirect(url_for('manage_sections'))


@app.route('/settings/sections/edit/<int:section_id>', methods=['GET', 'POST'])
def edit_section(section_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM sections WHERE id = %s", [section_id])
    section = cur.fetchone()

    cur.execute("SELECT * FROM branches")
    branches = cur.fetchall()

    if request.method == 'POST':
        name = request.form['name']
        branch_id = request.form['branch_id']
        cur.execute("UPDATE sections SET name = %s, branch_id = %s WHERE id = %s", [name, branch_id, section_id])
        mysql.connection.commit()
        cur.close()
        flash("Section updated successfully!")
        return redirect(url_for('manage_sections'))

    cur.close()
    return render_template('edit_section.html', section=section, branches=branches)

###Reports Route####
REPORT_FILTERS = ['start_date', 'end_date', 'username', 'company_id', 'branch_id', 'section_id', 'priority', 'status']
REPORT_COLUMNS = ['Task ID', 'Title', 'Description', 'Task Date', 'Status', 'Notes', 'File Path',
                  'Assigned To', 'Email', 'Company', 'Branch', 'Section', 'Priority']


def fetch_report_tasks(filters):
    """Runs the report query with the given filters; rows follow REPORT_COLUMNS."""
    # LEFT JOINs so tasks assigned to a group, or without a company/branch/section, are still included
    query = f"""
        SELECT tasks.id, tasks.title, tasks.description, tasks.task_date, tasks.status, tasks.notes,
               tasks.file_path, COALESCE(users.username, groupss.name) as assigned_to, users.email,
               companies.name as company, branches.name as branch, sections.name as section, tasks.priority
        FROM tasks
        LEFT JOIN users ON tasks.assigned_user_id = users.id
        LEFT JOIN groupss ON tasks.assigned_group_id = groupss.id
        LEFT JOIN companies ON tasks.company_id = companies.id
        LEFT JOIN branches ON tasks.branch_id = branches.id
        LEFT JOIN sections ON tasks.section_id = sections.id
        WHERE 1=1
    """
    params = []

    # Filter by date range (either end may be left open)
    if filters.get('start_date'):
        query += " AND tasks.task_date >= %s"
        params.append(filters['start_date'])
    if filters.get('end_date'):
        query += " AND tasks.task_date <= %s"
        params.append(filters['end_date'])

    # Filter by username, company, branch, section and priority
    if filters.get('username'):
        query += " AND users.username = %s"
        params.append(filters['username'])
    for column in ('company_id', 'branch_id', 'section_id'):
        if filters.get(column):
            query += f" AND tasks.{column} = %s"
            params.append(filters[column])
    if filters.get('priority') in PRIORITIES:
        query += " AND tasks.priority = %s"
        params.append(filters['priority'])
    if filters.get('status') in STATUSES:
        query += " AND tasks.status = %s"
        params.append(filters['status'])

    query += f" ORDER BY tasks.task_date, {PRIORITY_ORDER_SQL}"

    cur = mysql.connection.cursor()
    cur.execute(query, params)
    tasks = cur.fetchall()
    cur.close()
    return tasks


def report_filters_from(source):
    return {name: source.get(name, '') for name in REPORT_FILTERS}


@app.route('/report', methods=['GET', 'POST'])
def generate_report():
    if not is_admin():
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    filters = report_filters_from(request.form)
    tasks = fetch_report_tasks(filters)

    cur = mysql.connection.cursor()

    # Fetch all usernames for filter dropdown
    cur.execute("SELECT username FROM users")
    users = cur.fetchall()

    # Fetch all companies for filter dropdown
    cur.execute("SELECT id, name FROM companies")
    companies = cur.fetchall()

    # Fetch all branches for filter dropdown
    cur.execute("SELECT id, name FROM branches")
    branches = cur.fetchall()

    # Fetch all sections for filter dropdown
    cur.execute("SELECT id, name FROM sections")
    sections = cur.fetchall()

    cur.close()

    return render_template('report.html', tasks=tasks, users=users, companies=companies, branches=branches, sections=sections,
                           filters=filters, pdf_available=pdfkit is not None)

###Export to excel
@app.route('/export_report_excel', methods=['GET'])
def export_report_excel():
    if not is_admin():
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    tasks = fetch_report_tasks(report_filters_from(request.args))

    # Build the Excel file in memory
    df = pd.DataFrame(list(tasks), columns=REPORT_COLUMNS)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(output, as_attachment=True, download_name='task_report.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

###Report export as PDF
@app.route('/export_report_pdf', methods=['GET'])
def export_report_pdf():
    if not is_admin():
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    if pdfkit is None:
        flash("PDF export needs the pdfkit package and wkhtmltopdf installed.")
        return redirect(url_for('generate_report'))

    tasks = fetch_report_tasks(report_filters_from(request.args))

    # Render the report to an HTML template, then convert it to PDF in memory
    html = render_template('report_pdf.html', tasks=tasks, current_date=date.today().isoformat())
    try:
        pdf = pdfkit.from_string(html, False)
    except OSError as e:
        flash(f"PDF export failed (is wkhtmltopdf installed?): {e}")
        return redirect(url_for('generate_report'))

    return send_file(BytesIO(pdf), as_attachment=True, download_name='task_report.pdf', mimetype='application/pdf')

###Export Reports####
@app.route('/report/download', methods=['GET', 'POST'])
def download_report():
    if not is_admin():
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    tasks = fetch_report_tasks(report_filters_from(request.values))

    # Prepare CSV output
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(REPORT_COLUMNS)
    writer.writerows(tasks)

    # Return CSV file as response (with a BOM so Excel reads Arabic text correctly)
    return Response('﻿' + output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=task_report.csv"})



###Route for Managing Users###
@app.route('/settings/users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']  # Capture email from the form
        password = request.form['password']
        is_admin = 'is_admin' in request.form
        hashed_password = generate_password_hash(password)

        # Insert the new user into the database, including email
        cur = mysql.connection.cursor()
        try:
            cur.execute("INSERT INTO users (username, email, password, is_admin) VALUES (%s, %s, %s, %s)",
                        (username, email, hashed_password, is_admin))
            mysql.connection.commit()
            flash("User added successfully!")
        except MySQLdb.IntegrityError:
            flash("That username or email is already registered.")
        finally:
            cur.close()

    # Fetch users to display in the table
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, email, is_admin FROM users")
    users = cur.fetchall()
    cur.close()

    return render_template('manage_users.html', users=users)


@app.route('/settings/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", [user_id])
    mysql.connection.commit()
    cur.close()
    flash("User deleted successfully!")

    return redirect(url_for('manage_users'))


@app.route('/settings/users/edit/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    if 'user_id' not in session or not session['is_admin']:
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, email, is_admin FROM users WHERE id = %s", [user_id])
    user = cur.fetchone()

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']  # Capture email from the form
        is_admin = 'is_admin' in request.form

        # Update the user information including email
        cur.execute("UPDATE users SET username = %s, email = %s, is_admin = %s WHERE id = %s",
                    (username, email, is_admin, user_id))
        mysql.connection.commit()
        cur.close()
        flash("User updated successfully!")
        return redirect(url_for('manage_users'))

    cur.close()
    return render_template('edit_user.html', user=user)

## Route to error pages
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True)
