from flask_mysqldb import MySQL
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
import csv
from io import StringIO
import pandas as pd
import pdfkit
import smtplib
import MySQLdb



app = Flask(__name__)
app.secret_key = "supersecretkey"

# Function to switch language
@app.route('/switch_language/<language>')
def switch_language(language):
    session['lang'] = language
    return redirect(request.referrer or url_for('index'))

# Get the selected language or default to English
def get_language():
    return session.get('lang', 'en')



# MySQL Configurations
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '4626284400Ilu@@'
app.config['MYSQL_DB'] = 'task_management'

mysql = MySQL(app)

# Path to store uploaded files
UPLOAD_FOLDER = 'uploads/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# Insert notification when assigning a task to a user
def notify_task_assignment(task_id, assigned_user_id):
    message = "You have been assigned a new task."
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO notifications (user_id, task_id, message) VALUES (%s, %s, %s)",
                (assigned_user_id, task_id, message))
    mysql.connection.commit()
    cur.close()


# Insert notification when task status change
def notify_task_status_change(task_id, assigned_user_id, new_status):
    message = f"Your task has been marked as {new_status}."
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO notifications (user_id, task_id, message) VALUES (%s, %s, %s)",
                (assigned_user_id, task_id, message))
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
    smtp_server = request.form.get('smtp_server')
    smtp_port = request.form.get('smtp_port')
    smtp_user = request.form.get('smtp_user')
    smtp_password = request.form.get('smtp_password')
    use_tls = 'use_tls' in request.form
    test_email = request.form.get('test_email')

    try:
        # Step 1: Establish connection to the SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)

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
@app.route('/mark_notification_read/<int:notification_id>', methods=['GET'])
def mark_notification_read(notification_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()
    cur.execute("UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s", (notification_id, user_id))
    mysql.connection.commit()
    cur.close()

    return redirect(url_for('index'))  # Redirect after marking the notification as read

#route to get info button
@app.route('/get_task_info/<int:task_id>', methods=['GET'])
def get_task_info(task_id):
    # Query the database for the task details
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT title, description, status, task_date, 
               (SELECT username FROM users WHERE id = tasks.assigned_user_id) as assigned_to, 
               notes, file_path 
        FROM tasks WHERE id = %s
    """, (task_id,))
    task = cur.fetchone()
    cur.close()

    if task:
        # Format task data as a JSON response
        task_data = {
            'title': task[0],
            'description': task[1],
            'status': task[2],
            'task_date': task[3].strftime('%Y-%m-%d'),
            'assigned_to': task[4],
            'notes': task[5],
            'file_path': task[6]
        }
        return jsonify(task_data)
    else:
        return jsonify({'error': 'Task not found'}), 404


# Home route to display all tasks
@app.route('/')
def index():
    if 'user_id' not in session:
        flash("Please log in to view your tasks.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    # Pagination variables
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Number of tasks per page
    offset = (page - 1) * per_page

    cur.execute("SELECT * FROM tasks WHERE user_id = %s LIMIT %s OFFSET %s", (user_id, per_page, offset))
    tasks = cur.fetchall()

    # Fetch total count of tasks for pagination
    cur.execute("SELECT COUNT(*) FROM tasks WHERE user_id = %s", [user_id])
    total_tasks = cur.fetchone()[0]

    cur.close()

    return render_template('index.html', tasks=tasks, page=page, total_pages=(total_tasks + per_page - 1) // per_page)

###Calendar route###
@app.route('/tasks_json', methods=['GET'])
def tasks_json():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    user_id = session['user_id']
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of tasks per page
    offset = (page - 1) * per_page

    cur = mysql.connection.cursor()

    # Fetch tasks assigned to the user
    cur.execute("""
        SELECT id, title, description, status, task_date, 
               (SELECT username FROM users WHERE id = tasks.assigned_user_id) as assigned_to 
        FROM tasks
        WHERE user_id = %s OR assigned_user_id = %s
        LIMIT %s OFFSET %s
    """, (user_id, user_id, per_page, offset))

    tasks = cur.fetchall()
    cur.close()

    # Convert tasks to a dictionary list for JSON response
    task_list = [{
        'id': task[0],
        'title': task[1],
        'description': task[2],
        'status': task[3],
        'task_date': task[4].strftime('%Y-%m-%d'),
        'assigned_to': task[5]
    } for task in tasks]

    return jsonify({'tasks': task_list})

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
        notes = request.form.get('notes')
        user_id = session['user_id']

        # File upload handling
        file = request.files.get('file')
        file_path = None
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

        # Insert task into the database
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO tasks (title, description, task_date, company_id, branch_id, section_id, file_path, assigned_user_id, notes, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
        title, description, task_date, company_id, branch_id, section_id, file_path, assigned_user_id, notes, user_id))

        task_id = cur.lastrowid  # Get the ID of the newly created task
        mysql.connection.commit()

        # Notify the assigned user
        notify_task_assignment(task_id, assigned_user_id)

        cur.close()

        flash("Task added successfully!")
        return redirect(url_for('index'))

    # Fetch companies and users for dropdowns
    cur = mysql.connection.cursor()

    # Fetch companies
    cur.execute("SELECT * FROM companies")
    companies = cur.fetchall()

    # Fetch users with email
    cur.execute("SELECT id, username, email FROM users")
    users = cur.fetchall()

    cur.close()

    return render_template('add_task.html', companies=companies, users=users)




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

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    # Update task status to "Completed"
    cur.execute("UPDATE tasks SET status = 'Completed' WHERE id = %s AND user_id = %s", (task_id, user_id))
    mysql.connection.commit()

    # Notify the assigned user
    cur.execute("SELECT assigned_user_id FROM tasks WHERE id = %s", [task_id])
    assigned_user_id = cur.fetchone()[0]

    # Call the notification helper function
    notify_task_status_change(task_id, assigned_user_id, "Completed")

    cur.close()
    return redirect(url_for('index'))


# Delete task
@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if 'user_id' not in session:
        return "Unauthorized", 401

    user_id = session['user_id']
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s AND user_id = %s", (task_id, user_id))
    mysql.connection.commit()
    cur.close()

    return redirect(url_for('index'))


###Edit task route###
@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        flash("Please log in to edit a task.")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        # Get form data
        title = request.form['title']
        description = request.form['description']
        task_date = request.form['task_date']
        assigned_user_id = int(request.form['assigned_user_id'])  # Ensure this is an integer
        status = request.form['status']

        # Update task in the database
        cur.execute("""
            UPDATE tasks
            SET title = %s, description = %s, task_date = %s, assigned_user_id = %s, status = %s
            WHERE id = %s
        """, (title, description, task_date, assigned_user_id, status, task_id))

        mysql.connection.commit()
        cur.close()

        flash("Task updated successfully!")
        return redirect(url_for('index'))

    # Fetch task information to prepopulate the form
    cur.execute("SELECT title, description, task_date, assigned_user_id, status FROM tasks WHERE id = %s", (task_id,))
    task = cur.fetchone()

    # Fetch all users (id, username, email) for reassigning the task
    cur.execute("SELECT id, username, email FROM users")
    users = cur.fetchall()

    cur.close()

    # Pass task_id to the template along with task and users
    return render_template('edit_task.html', task=task, users=users, task_id=task_id)


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
        cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                    (username, email, hashed_password))
        mysql.connection.commit()
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
        cur.execute("SELECT * FROM users WHERE username = %s", [username])
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[2], password):  # user[2] is the hashed password
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['is_admin'] = user[3]  # Assume user[3] is a boolean indicating admin status
            flash("Login successful!")
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password.")

    return render_template('login.html')

##Notifications route##
@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        flash("Please log in to view notifications.")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    # Fetch unread notifications for the current user
    cur.execute("SELECT message FROM notifications WHERE user_id = %s AND is_read = 0", (session['user_id'],))
    notifications = cur.fetchall()
    cur.close()

    return jsonify(notifications)

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

    # Fetch tasks assigned to this user
    cur.execute("""
        SELECT id, title, description, task_date, status
        FROM tasks
        WHERE assigned_user_id = %s
    """, [user_id])
    assigned_tasks = cur.fetchall()

    cur.close()

    return render_template('profile.html', user_info=user_info, assigned_tasks=assigned_tasks)

#User logout
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
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
@app.route('/report', methods=['GET', 'POST'])
def generate_report():
    if 'user_id' not in session or not session.get('is_admin', False):
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()

    # Initialize filters
    start_date = request.form.get('start_date', '')
    end_date = request.form.get('end_date', '')
    username = request.form.get('username', '')

    # SQL query with optional filters
    query = """
        SELECT tasks.id, tasks.title, tasks.description, tasks.task_date, tasks.status, tasks.notes, 
               tasks.file_path, users.username, users.email, companies.name as company, branches.name as branch, sections.name as section
        FROM tasks
        JOIN users ON tasks.assigned_user_id = users.id
        JOIN companies ON tasks.company_id = companies.id
        JOIN branches ON tasks.branch_id = branches.id
        JOIN sections ON tasks.section_id = sections.id
        WHERE 1=1
    """

    filters = []

    # Filter by date range
    if start_date and end_date:
        query += " AND tasks.task_date BETWEEN %s AND %s"
        filters.append(start_date)
        filters.append(end_date)

    # Filter by username
    if username:
        query += " AND users.username = %s"
        filters.append(username)

    # Execute the query
    cur.execute(query, filters)
    tasks = cur.fetchall()

    # Fetch all usernames for filter dropdown
    cur.execute("SELECT username FROM users")
    users = cur.fetchall()

    cur.close()

    return render_template('report.html', tasks=tasks, users=users, start_date=start_date, end_date=end_date, selected_user=username)

###Export to excel
@app.route('/export_report_excel', methods=['GET'])
def export_report_excel():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    username = request.args.get('username', '')

    # Fetch tasks based on filters (similar to generate_report logic)
    cur = mysql.connection.cursor()
    query = """
        SELECT tasks.id, tasks.title, tasks.description, tasks.task_date, tasks.status, tasks.notes, 
               tasks.file_path, users.username, users.email, companies.name as company, branches.name as branch, sections.name as section
        FROM tasks
        JOIN users ON tasks.assigned_user_id = users.id
        JOIN companies ON tasks.company_id = companies.id
        JOIN branches ON tasks.branch_id = branches.id
        JOIN sections ON tasks.section_id = sections.id
        WHERE 1=1
    """
    filters = []
    if start_date and end_date:
        query += " AND tasks.task_date BETWEEN %s AND %s"
        filters.append(start_date)
        filters.append(end_date)
    if username:
        query += " AND users.username = %s"
        filters.append(username)

    cur.execute(query, filters)
    tasks = cur.fetchall()
    cur.close()

    # Convert to DataFrame for Excel export
    df = pd.DataFrame(tasks, columns=['Task ID', 'Title', 'Description', 'Task Date', 'Status', 'Notes', 'File Path',
                                      'Assigned User', 'Email', 'Company', 'Branch', 'Section'])

    # Save the DataFrame to an Excel file
    excel_path = 'task_report.xlsx'
    df.to_excel(excel_path, index=False)

    return send_file(excel_path, as_attachment=True)

###Report export as PDF
@app.route('/export_report_pdf', methods=['GET'])
def export_report_pdf():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    username = request.args.get('username', '')

    # Fetch tasks based on filters (similar to generate_report logic)
    cur = mysql.connection.cursor()
    query = """
        SELECT tasks.id, tasks.title, tasks.description, tasks.task_date, tasks.status, tasks.notes, 
               tasks.file_path, users.username, users.email, companies.name as company, branches.name as branch, sections.name as section
        FROM tasks
        JOIN users ON tasks.assigned_user_id = users.id
        JOIN companies ON tasks.company_id = companies.id
        JOIN branches ON tasks.branch_id = branches.id
        JOIN sections ON tasks.section_id = sections.id
        WHERE 1=1
    """
    filters = []
    if start_date and end_date:
        query += " AND tasks.task_date BETWEEN %s AND %s"
        filters.append(start_date)
        filters.append(end_date)
    if username:
        query += " AND users.username = %s"
        filters.append(username)

    cur.execute(query, filters)
    tasks = cur.fetchall()
    cur.close()

    # Render the report to an HTML template
    html = render_template('report_pdf.html', tasks=tasks)

    # Save the rendered HTML to a PDF
    pdf_path = 'task_report.pdf'
    pdfkit.from_string(html, pdf_path)

    return send_file(pdf_path, as_attachment=True)

###Export Reports####
@app.route('/report/download', methods=['GET', 'POST'])
def download_report():
    if 'user_id' not in session or not session.get('is_admin', False):
        flash("Unauthorized access.")
        return redirect(url_for('index'))

    cur = mysql.connection.cursor()

    # Fetch tasks (you can reuse the logic from the report generation)
    query = """
        SELECT tasks.id, tasks.title, tasks.description, tasks.task_date, tasks.status, tasks.notes, 
               users.username, users.email, companies.name as company, branches.name as branch, sections.name as section
        FROM tasks
        JOIN users ON tasks.assigned_user_id = users.id
        JOIN companies ON tasks.company_id = companies.id
        JOIN branches ON tasks.branch_id = branches.id
        JOIN sections ON tasks.section_id = sections.id
    """
    cur.execute(query)
    tasks = cur.fetchall()
    cur.close()

    # Prepare CSV output
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ['Task ID', 'Title', 'Description', 'Task Date', 'Status', 'Assigned User', 'Email', 'Company', 'Branch',
         'Section', 'Notes'])

    for task in tasks:
        writer.writerow(
            [task[0], task[1], task[2], task[3], task[4], task[6], task[7], task[8], task[9], task[10], task[5]])

    output.seek(0)

    # Return CSV file as response
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=task_report.csv"})



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
        cur.execute("INSERT INTO users (username, email, password, is_admin) VALUES (%s, %s, %s, %s)",
                    (username, email, hashed_password, is_admin))
        mysql.connection.commit()
        cur.close()
        flash("User added successfully!")

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


if __name__ == '__main__':
    app.run(debug=True)
