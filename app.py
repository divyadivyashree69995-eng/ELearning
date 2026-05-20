import os
import json
import anthropic
import PyPDF2
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session, flash
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from sklearn.cluster import KMeans
import numpy as np
import mysql.connector
from functools import wraps

# Initialize Flask App and SocketIO (templates live under elearning/)
_BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(_BASE, "elearning", "templates"))
app.secret_key = 'your_super_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Database Configuration ---
DB_CONFIG = {
    'user': 'root',
    'password': '',
    'host': '127.0.0.1',
    'database': 'elearning_db',
    'raise_on_warnings': True
}

# --- File Upload Configuration (use elearning/uploads; support photo/photos paths) ---
_ELEARNING_ROOT = os.path.join(_BASE, "elearning")
UPLOAD_TYPE_DIRS = {
    'video': ('uploads/video', 'uploads/videos'),
    'photo': ('uploads/photo', 'uploads/photos'),
    'pdf': ('uploads/pdf', 'uploads/pdfs'),
}
ALLOWED_EXTENSIONS_VIDEO = {'mp4', 'mov', 'avi', 'webm'}
ALLOWED_EXTENSIONS_PHOTO = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_EXTENSIONS_PDF = {'pdf'}


def primary_upload_dir(file_type):
    rel = UPLOAD_TYPE_DIRS[file_type][0]
    path = os.path.join(_ELEARNING_ROOT, rel)
    os.makedirs(path, exist_ok=True)
    return path


def find_upload_file(filetype, filename):
    safe = secure_filename(os.path.basename(filename))
    if not safe:
        return None, None
    key = filetype.rstrip('s') if filetype in ('videos', 'photos', 'pdfs') else filetype
    if key not in UPLOAD_TYPE_DIRS:
        return None, None
    for rel in UPLOAD_TYPE_DIRS[key]:
        folder = os.path.join(_ELEARNING_ROOT, rel)
        full = os.path.join(folder, safe)
        if os.path.isfile(full):
            return folder, safe
    return None, None


UPLOAD_FOLDER_VIDEOS = primary_upload_dir('video')
UPLOAD_FOLDER_PHOTOS = primary_upload_dir('photo')
UPLOAD_FOLDER_PDFS = primary_upload_dir('pdf')

app.config.update(
    UPLOAD_FOLDER_VIDEOS=UPLOAD_FOLDER_VIDEOS,
    UPLOAD_FOLDER_PHOTOS=UPLOAD_FOLDER_PHOTOS,
    UPLOAD_FOLDER_PDFS=UPLOAD_FOLDER_PDFS,
)

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as err:
        print(f"Error connecting to database: {err}")
        return None


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    """Match elearning DB: Werkzeug hashes (pbkdf2/scrypt/argon2) or legacy plain text."""
    if not stored_hash or password is None:
        return False
    if isinstance(stored_hash, bytes):
        stored_hash = stored_hash.decode("utf-8", errors="ignore")
    if stored_hash.startswith(("pbkdf2:", "scrypt:", "argon2")):
        try:
            return check_password_hash(stored_hash, password)
        except (ValueError, TypeError):
            return False
    return stored_hash == password


def format_last_active(value):
    from datetime import datetime as _dt
    if value is None:
        return 'Never'
    if isinstance(value, _dt):
        return value.strftime('%Y-%m-%d %H:%M')
    if isinstance(value, str):
        if not value.strip() or value == 'Never' or '%Y' in value:
            return 'Never' if not value or value == 'Never' else value
        return value
    return str(value)


def log_audit(action, details=None, actor_username=None):
    actor = actor_username or session.get('username')
    if not actor:
        return
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO audit_log (actor_username, action, details) VALUES (%s, %s, %s)',
            (actor, action, details),
        )
        conn.commit()
    except mysql.connector.Error:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def login_required(role):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'loggedin' not in session or session.get('role') not in role.split(','):
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

@app.route('/')
def home():
    if 'loggedin' in session:
        if session.get('role') == 'admin': return redirect(url_for('admin_dashboard'))
        if session.get('role') == 'teacher': return redirect(url_for('teacher_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        conn = get_db_connection()
        if not conn: return render_template('login.html', message='Database connection failed')
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and verify_password(user.get("password"), password):
            session.update(loggedin=True, id=user['id'], username=user['username'], role=user['role'])
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute('UPDATE users SET last_active = NOW() WHERE id = %s', (user['id'],))
                    conn.commit()
                except mysql.connector.Error:
                    conn.rollback()
                finally:
                    cur.close()
                    conn.close()
            log_audit('login', f"role={user['role']}", actor_username=user['username'])
            if user['role'] == 'admin': return redirect(url_for('admin_dashboard'))
            if user['role'] == 'teacher': return redirect(url_for('teacher_dashboard'))
            return redirect(url_for('student_dashboard'))
        return render_template('login.html', message='Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        if not conn: return render_template('register.html', message='Database connection failed')
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            if cursor.fetchone():
                return render_template('register.html', message='Username already exists!')
            cursor.execute(
                'INSERT INTO users (username, password, role) VALUES (%s, %s, %s)',
                (username, hash_password(password), 'student'),
            )
            conn.commit()
            return redirect(url_for('login'))
        except mysql.connector.Error as err:
            conn.rollback()
            return render_template('register.html', message=f"Database error: {err}")
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# --- ROUTES FOR ADMIN DASHBOARD STATS ---
@app.route('/admin/dashboard_stats', methods=['GET'])
@login_required('admin')
def get_dashboard_stats():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Get total students
        cursor.execute("SELECT COUNT(id) as count FROM users WHERE role = 'student'")
        total_students = cursor.fetchone()['count']

        # Get total teachers
        cursor.execute("SELECT COUNT(id) as count FROM users WHERE role = 'teacher'")
        total_teachers = cursor.fetchone()['count']

        # Get total content
        cursor.execute("SELECT COUNT(id) as count FROM content")
        total_content = cursor.fetchone()['count']
        
        try:
            cursor.execute(
                "SELECT COUNT(id) AS count FROM users WHERE role = 'teacher' AND is_approved = 0"
            )
            pending_teachers = cursor.fetchone()['count']
        except mysql.connector.Error:
            pending_teachers = 0
        return jsonify({
            "total_students": total_students,
            "total_teachers": total_teachers,
            "total_content": total_content,
            "pending_teachers": pending_teachers,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/admin/get_performance_distribution', methods=['GET'])
@login_required('admin')
def get_performance_distribution():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Query to get the average score for each test
        query = """
            SELECT t.title, AVG(ss.score) as average_score
            FROM tests t
            JOIN student_scores ss ON t.id = ss.test_id
            GROUP BY t.id, t.title
            ORDER BY t.title;
        """
        cursor.execute(query)
        results = cursor.fetchall()

        if not results:
             return jsonify({'labels': [], 'datasets': []})

        chart_data = {
            'labels': [row['title'] for row in results],
            'datasets': [{
                'label': 'Average Score (%)',
                'data': [float(row['average_score']) for row in results],
                'backgroundColor': 'rgba(54, 162, 235, 0.6)',
                'borderColor': 'rgba(54, 162, 235, 1)',
                'borderWidth': 1
            }]
        }
        return jsonify(chart_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
# --- END OF ADMIN ROUTES ---


@app.route('/admin')
@login_required('admin')
def admin_dashboard():
    return render_template('admin.html', username=session['username'])

@app.route('/teacher')
@login_required('teacher')
def teacher_dashboard():
    return render_template('teacher.html', username=session['username'])

@app.route('/admin/create_user', methods=['POST'])
@login_required('admin')
def create_user():
    username = request.form['username']
    password = request.form['password']
    role = request.form['role']
    class_name = request.form.get('class_name', 'General')

    if role not in ['student', 'teacher']:
        flash('Invalid role specified.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
        if cursor.fetchone():
            flash(f"Username '{username}' already exists!", 'error')
        else:
            approved = 1 if role == 'student' else 0
            cursor.execute(
                'INSERT INTO users (username, password, role, class_name, is_approved) VALUES (%s, %s, %s, %s, %s)',
                (
                    username,
                    hash_password(password),
                    role,
                    class_name if role == 'student' else None,
                    approved,
                ),
            )
            conn.commit()
            flash(f"{role.capitalize()} '{username}' created successfully!", 'success')
    except mysql.connector.Error as err:
        conn.rollback()
        flash(f"Database error: {err}", 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/get_classes', methods=['GET'])
@login_required('admin,teacher')
def get_classes():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT class_name FROM users WHERE role = 'student' AND class_name IS NOT NULL ORDER BY class_name ASC")
        classes = [row['class_name'] for row in cursor.fetchall()]
        return jsonify(classes)
    finally:
        cursor.close()
        conn.close()

@app.route('/upload/<filetype>', methods=['POST'])
@login_required('admin,teacher')
def upload_file(filetype):
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    file = request.files['file']
    title = request.form.get(f'{filetype}_title', 'Untitled')
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    config_map = {
        'video': (app.config['UPLOAD_FOLDER_VIDEOS'], ALLOWED_EXTENSIONS_VIDEO),
        'photo': (app.config['UPLOAD_FOLDER_PHOTOS'], ALLOWED_EXTENSIONS_PHOTO),
        'pdf': (app.config['UPLOAD_FOLDER_PDFS'], ALLOWED_EXTENSIONS_PDF),
    }
    if filetype not in config_map:
        return jsonify({'error': 'Invalid file type specified'}), 400
    upload_folder, allowed_extensions = config_map[filetype]
    if file and allowed_file(file.filename, allowed_extensions):
        filename = secure_filename(file.filename)
        try:
            file.save(os.path.join(upload_folder, filename))
        except Exception as e:
            print(f"Error saving file: {e}")
            return jsonify({'error': 'Could not save file to disk. Check server permissions.'}), 500
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO content (title, file_type, filename) VALUES (%s, %s, %s)", (title, filetype, filename))
            conn.commit()
            socketio.emit('new_content', {'title': title, 'type': filetype.capitalize()})
            return jsonify({'message': f'{filetype.capitalize()} "{title}" uploaded successfully!'})
        except Exception as e:
            conn.rollback()
            return jsonify({'error': f'Database error: {e}'}), 500
        finally:
            cursor.close()
            conn.close()
    return jsonify({'error': 'File type not allowed'}), 400

@app.route('/delete_content/<int:content_id>', methods=['DELETE'])
@login_required('admin,teacher')
def delete_content(content_id):
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT filename, file_type FROM content WHERE id = %s", (content_id,))
        content_item = cursor.fetchone()
        if not content_item: return jsonify({'error': 'Content not found'}), 404
        filename, file_type = content_item['filename'], content_item['file_type']
        folder_map = {
            'video': app.config['UPLOAD_FOLDER_VIDEOS'],
            'photo': app.config['UPLOAD_FOLDER_PHOTOS'],
            'pdf': app.config['UPLOAD_FOLDER_PDFS']
        }
        folder = folder_map.get(file_type)
        if folder and filename and os.path.exists(os.path.join(folder, filename)):
            os.remove(os.path.join(folder, filename))
        cursor.execute("DELETE FROM content WHERE id = %s", (content_id,))
        conn.commit()
        return jsonify({'message': 'Content deleted successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/admin/get_all_content', methods=['GET'])
@login_required('admin,teacher')
def admin_get_all_content():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, title, file_type, filename, upload_date FROM content ORDER BY upload_date DESC")
        items = cursor.fetchall()
        for item in items:
            if item.get('upload_date'):
                item['upload_date'] = item['upload_date'].strftime('%Y-%m-%d %H:%M:%S')
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/student')
@login_required('student')
def student_dashboard():
    return render_template('student.html', username=session.get('username', 'Guest'))

@app.route('/get_content/<filetype>', methods=['GET'])
@login_required('student')
def get_content(filetype):
    student_username = session.get('username')
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT c.id, c.title, c.filename, c.file_type
        FROM content c
        JOIN content_permissions cp ON c.id = cp.content_id
        WHERE c.file_type = %s AND cp.student_username = %s
        ORDER BY c.upload_date DESC
    """
    cursor.execute(query, (filetype, student_username))
    return jsonify(cursor.fetchall())

@app.route('/get_all_students', methods=['GET'])
@login_required('admin,teacher')
def get_all_students():
    class_filter = request.args.get('class_name')
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    
    query = "SELECT username FROM users WHERE role = 'student'"
    params = []
    
    if class_filter and class_filter != 'all':
        query += " AND class_name = %s"
        params.append(class_filter)
        
    query += " ORDER BY username ASC"
    
    cursor.execute(query, tuple(params))
    students = [row['username'] for row in cursor.fetchall()]
    return jsonify(students)

@app.route('/get_content_permissions/<int:content_id>', methods=['GET'])
@login_required('admin,teacher')
def get_content_permissions(content_id):
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT student_username FROM content_permissions WHERE content_id = %s", (content_id,))
    students = [row['student_username'] for row in cursor.fetchall()]
    return jsonify(students)

@app.route('/update_content_permissions/<int:content_id>', methods=['POST'])
@login_required('admin,teacher')
def update_content_permissions(content_id):
    data = request.get_json()
    student_usernames = data.get('students', [])
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION")
        cursor.execute("DELETE FROM content_permissions WHERE content_id = %s", (content_id,))
        if student_usernames:
            sql = "INSERT INTO content_permissions (content_id, student_username) VALUES (%s, %s)"
            values = [(content_id, username) for username in student_usernames]
            cursor.executemany(sql, values)
        cursor.execute("COMMIT")
        return jsonify({'message': 'Permissions updated successfully!'})
    except mysql.connector.Error as err:
        cursor.execute("ROLLBACK")
        return jsonify({'error': str(err)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/uploads/<filetype>/<path:filename>')
def serve_upload(filetype, filename):
    folder, safe_name = find_upload_file(filetype, filename)
    if not folder:
        return "File not found", 404
    return send_from_directory(folder, safe_name)

@app.route('/create_test', methods=['POST'])
@login_required('admin,teacher')
def create_test():
    data = request.json
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO tests (title) VALUES (%s)", (data['title'],))
        test_id = cursor.lastrowid
        for q in data['questions']:
            options_json = json.dumps(q['options'])
            cursor.execute("INSERT INTO questions (test_id, question_text, options, correct_answer) VALUES (%s, %s, %s, %s)", (test_id, q['question'], options_json, q['answer']))
        conn.commit()
        return jsonify({'message': 'Test created successfully!'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/teacher/get_all_tests', methods=['GET'])
@login_required('admin,teacher')
def teacher_get_all_tests():
    conn = get_db_connection()
    if not conn: 
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, title, created_at FROM tests ORDER BY created_at DESC")
        tests = cursor.fetchall()
        for test in tests:
            if test.get('created_at'):
                test['created_at'] = test['created_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify(tests)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/teacher/delete_test/<int:test_id>', methods=['DELETE'])
@login_required('admin,teacher')
def delete_test(test_id):
    conn = get_db_connection()
    if not conn: 
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION")
        cursor.execute("DELETE FROM student_scores WHERE test_id = %s", (test_id,))
        cursor.execute("DELETE FROM questions WHERE test_id = %s", (test_id,))
        cursor.execute("DELETE FROM tests WHERE id = %s", (test_id,))
        cursor.execute("COMMIT")
        return jsonify({'message': 'Test and all associated data deleted successfully!'})
    except mysql.connector.Error as err:
        cursor.execute("ROLLBACK")
        return jsonify({'error': str(err)}), 500
    finally:
        cursor.close()
        conn.close()
        
@app.route('/get_quiz_permissions/<int:test_id>', methods=['GET'])
@login_required('admin,teacher')
def get_quiz_permissions(test_id):
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT student_username FROM quiz_permissions WHERE test_id = %s", (test_id,))
    students = [row['student_username'] for row in cursor.fetchall()]
    return jsonify(students)

@app.route('/update_quiz_permissions/<int:test_id>', methods=['POST'])
@login_required('admin,teacher')
def update_quiz_permissions(test_id):
    data = request.get_json()
    student_usernames = data.get('students', [])
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION")
        cursor.execute("DELETE FROM quiz_permissions WHERE test_id = %s", (test_id,))
        if student_usernames:
            sql = "INSERT INTO quiz_permissions (test_id, student_username) VALUES (%s, %s)"
            values = [(test_id, username) for username in student_usernames]
            cursor.executemany(sql, values)
        cursor.execute("COMMIT")
        return jsonify({'message': 'Quiz permissions updated successfully!'})
    except mysql.connector.Error as err:
        cursor.execute("ROLLBACK")
        return jsonify({'error': str(err)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/get_tests', methods=['GET'])
@login_required('student')
def get_tests():
    student_username = session['username']
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # This query first finds all tests the student is permitted to take,
        # then filters out the ones they have already completed.
        query = """
            SELECT t.id, t.title
            FROM tests t
            JOIN quiz_permissions qp ON t.id = qp.test_id
            WHERE qp.student_username = %s AND t.id NOT IN (
                SELECT ss.test_id
                FROM student_scores ss
                WHERE ss.student_username = %s
            )
        """
        cursor.execute(query, (student_username, student_username))
        tests = cursor.fetchall()
        return jsonify(tests)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/get_test_details/<int:test_id>', methods=['GET'])
@login_required('student')
def get_test_details(test_id):
    conn = get_db_connection()
    if not conn: 
        return "Database connection failed", 500
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT COUNT(*) as count FROM student_scores WHERE student_username = %s AND test_id = %s", (session['username'], test_id))
        if cursor.fetchone()['count'] > 0:
            flash('You have already completed this test.', 'error')
            return redirect(url_for('student_dashboard'))

        cursor.execute("SELECT title FROM tests WHERE id = %s", (test_id,))
        test = cursor.fetchone()
        if not test:
            return "Test not found", 404
        test_title = test['title']
        
        cursor.execute("SELECT id, question_text, options FROM questions WHERE test_id = %s", (test_id,))
        questions = cursor.fetchall()
        for q in questions:
            q['options'] = json.loads(q['options'])
            
        return render_template('test_page.html', questions=questions, test_title=test_title, test_id=test_id)
        
    except Exception as e:
        print(f"Error fetching test details: {e}")
        return "An error occurred", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/submit_test', methods=['POST'])
@login_required('student')
def submit_test():
    data = request.json
    test_id, student_answers, student_username = data['test_id'], data['answers'], session['username']
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as count FROM student_scores WHERE student_username = %s AND test_id = %s", (student_username, test_id))
    if cursor.fetchone()['count'] > 0: return jsonify({'error': 'You have already completed this test.'}), 409
    cursor.execute("SELECT correct_answer FROM questions WHERE test_id = %s ORDER BY id", (test_id,))
    correct_answers = [row['correct_answer'] for row in cursor.fetchall()]
    score_count = sum(1 for i, ans in enumerate(student_answers) if str(ans) == str(correct_answers[i]))
    score_percent = (score_count / len(correct_answers)) * 100 if correct_answers else 0
    cursor.execute("INSERT INTO student_scores (student_username, test_id, score) VALUES (%s, %s, %s)", (student_username, test_id, score_percent))
    conn.commit()
    return jsonify({'message': 'Test submitted!', 'score': score_percent})

@app.route('/get_scores', methods=['GET'])
@login_required('student')
def get_scores():
    student_username = session['username']
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    query = "SELECT t.title as test_title, ss.score FROM student_scores ss JOIN tests t ON ss.test_id = t.id WHERE ss.student_username = %s ORDER BY ss.submission_date DESC"
    cursor.execute(query, (student_username,))
    return jsonify(cursor.fetchall())

@app.route('/get_comments/<int:content_id>', methods=['GET'])
@login_required('admin,teacher,student')
def get_comments(content_id):
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Note: The 'sentiment' column is now just 'neutral' by default
        query = "SELECT c.id, c.user_username, c.comment_text, c.created_at, c.sentiment FROM comments c WHERE c.content_id = %s ORDER BY c.created_at ASC"
        cursor.execute(query, (content_id,))
        comments = cursor.fetchall()
        for comment in comments:
            if comment.get('created_at'):
                comment['created_at'] = comment['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        return jsonify(comments)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/add_comment/<int:content_id>', methods=['POST'])
@login_required('admin,teacher,student')
def add_comment(content_id):
    user_username = session['username']
    data = request.json
    comment_text = data.get('comment_text')
    if not comment_text or not comment_text.strip():
        return jsonify({'error': 'Comment text cannot be empty'}), 400
    
    # Set sentiment to neutral as the AI model is removed
    sentiment = 'neutral'
    
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO comments (content_id, user_username, comment_text, sentiment) VALUES (%s, %s, %s, %s)",
                       (content_id, user_username, comment_text, sentiment))
        conn.commit()
        return jsonify({'message': 'Comment added successfully!'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/get_recommendations', methods=['GET'])
@login_required('student')
def get_recommendations():
    # This feature relied on AI-based topic modeling. 
    # Returning an empty list as a placeholder.
    return jsonify([])

@app.route('/cluster_students', methods=['GET'])
@login_required('admin,teacher')
def cluster_students():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    try:
        query = "SELECT student_username, test_id, score FROM student_scores"
        df = pd.read_sql(query, conn)
        if df.empty or len(df['student_username'].unique()) < 3:
            return jsonify({'error': 'Not enough data to perform clustering. At least 3 students with scores are needed.'}), 400
        pivot_df = df.pivot(index='student_username', columns='test_id', values='score')
        pivot_df.fillna(pivot_df.mean(), inplace=True)
        pivot_df.fillna(50, inplace=True)
        student_data = pivot_df.values
        student_names = pivot_df.index.tolist()
        n_clusters = min(3, len(student_names))
        if n_clusters <= 1:
             return jsonify({'error': 'Cannot cluster a single student.'}), 400
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(student_data)
        clustered_students = {}
        for i in range(n_clusters):
            clustered_students[f'Cluster {i+1}'] = []
        for student_name, cluster_id in zip(student_names, clusters):
            clustered_students[f'Cluster {cluster_id+1}'].append(student_name)
        return jsonify(clustered_students)
    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500
    finally:
        if conn and conn.is_connected():
            conn.close()

@app.route('/live_class')
@login_required('teacher,student')
def live_class():
    return render_template('live_class.html', role=session.get('role'), username=session.get('username'))

@app.route('/chat')
@login_required('teacher,student')
def chat():
    return render_template('chat.html', username=session.get('username'))

LIVE_CLASS_ROOM = 'live_class_room'

@socketio.on('join_room')
def handle_join_room(data):
    username = data.get('username')
    join_room(LIVE_CLASS_ROOM)
    socketio.emit('user_joined', {'username': username, 'sid': request.sid}, room=LIVE_CLASS_ROOM, skip_sid=request.sid)

@socketio.on('offer')
def handle_offer(data):
    target_sid = data.get('target_sid')
    offer = data.get('offer')
    socketio.emit('offer_received', {'offer': offer, 'initiator_sid': request.sid}, room=target_sid)

@socketio.on('answer')
def handle_answer(data):
    target_sid = data.get('target_sid')
    answer = data.get('answer')
    socketio.emit('answer_received', {'answer': answer, 'responder_sid': request.sid}, room=target_sid)

@socketio.on('ice_candidate')
def handle_ice_candidate(data):
    target_sid = data.get('target_sid')
    candidate = data.get('candidate')
    socketio.emit('ice_candidate_received', {'candidate': candidate, 'sender_sid': request.sid}, room=target_sid)

@socketio.on('teacher_live')
def handle_teacher_live(data):
    username = data.get('username', 'The teacher')
    message = f"📢 {username} has started a live class!"
    socketio.emit('session_started', {'message': message})

@socketio.on('disconnect')
def handle_disconnect():
    leave_room(LIVE_CLASS_ROOM)
    socketio.emit('user_left', {'sid': request.sid}, room=LIVE_CLASS_ROOM)

# --- GENERAL CHAT SOCKET EVENTS ---
CHAT_ROOM = 'general_chat'

@socketio.on('join_general_chat')
def handle_join_general_chat(data):
    username = data['username']
    join_room(CHAT_ROOM)
    # Notify others in the room that a user has joined
    emit('user_announcement', {'msg': f'{username} has joined the chat.'}, room=CHAT_ROOM, skip_sid=request.sid)

@socketio.on('send_general_message')
def handle_send_general_message(data):
    # Broadcast the received message to all clients in the room
    emit('receive_general_message', data, room=CHAT_ROOM)

@socketio.on('leave_general_chat')
def handle_leave_general_chat(data):
    username = data['username']
    leave_room(CHAT_ROOM)
    # Notify others that a user has left
    emit('user_announcement', {'msg': f'{username} has left the chat.'}, room=CHAT_ROOM, skip_sid=request.sid)

@app.route('/generate_quiz_from_pdf', methods=['POST'])
@login_required('admin,teacher')
def generate_quiz_from_pdf():
    """
    Accepts a PDF upload, extracts its text, then uses the Anthropic API
    to generate multiple-choice quiz questions from the content.
    """
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'No PDF file provided'}), 400

    pdf_file = request.files['pdf_file']
    num_questions = int(request.form.get('num_questions', 5))

    if pdf_file.filename == '' or not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a valid PDF file'}), 400

    # --- Extract text from the PDF ---
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        extracted_text = ''
        for page in reader.pages:
            extracted_text += page.extract_text() or ''
        extracted_text = extracted_text.strip()
    except Exception as e:
        return jsonify({'error': f'Failed to read PDF: {str(e)}'}), 500

    if len(extracted_text) < 100:
        return jsonify({'error': 'PDF has too little readable text. Please upload a text-based PDF.'}), 400

    # Truncate to avoid hitting token limits (~12,000 chars)
    text_for_prompt = extracted_text[:12000]

    # --- Call the Anthropic API ---
    try:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

        prompt = f"""You are an expert quiz creator. Based on the following text, generate exactly {num_questions} multiple-choice quiz questions.

RULES:
- Each question must have exactly 4 answer options (A, B, C, D).
- Exactly one option must be the correct answer.
- Questions should test understanding of key concepts in the text.
- Return ONLY a valid JSON array with no extra text, no markdown, no code fences.

JSON format:
[
  {{
    "question": "Question text here?",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "answer": "The exact text of the correct option"
  }}
]

TEXT:
{text_for_prompt}
"""

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_response = message.content[0].text.strip()

        # Strip markdown fences if present
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]

        questions = json.loads(raw_response)

        # Validate structure
        for q in questions:
            if not all(k in q for k in ('question', 'options', 'answer')):
                raise ValueError("Invalid question format returned by AI")
            if len(q['options']) != 4:
                raise ValueError("Each question must have exactly 4 options")

        return jsonify({'questions': questions})

    except json.JSONDecodeError as e:
        return jsonify({'error': f'AI returned invalid JSON: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'AI generation failed: {str(e)}'}), 500


@app.route('/admin/get_users/<role>', methods=['GET'])
@login_required('admin')
def get_users_by_role(role):
    if role not in ('student', 'teacher'):
        return jsonify({'error': 'Invalid role'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, username, role,
                   COALESCE(class_name, '—') AS class_name,
                   COALESCE(is_approved, 1) AS is_approved,
                   last_active
            FROM users WHERE role = %s ORDER BY username
            """,
            (role,),
        )
        rows = cursor.fetchall()
        for row in rows:
            row['last_active'] = format_last_active(row.get('last_active'))
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/approve_teacher/<int:user_id>', methods=['POST'])
@login_required('admin')
def approve_teacher(user_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET is_approved = 1 WHERE id = %s AND role = 'teacher'",
            (user_id,),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({'error': 'Teacher not found'}), 404
        return jsonify({'message': 'Teacher approved'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/audit_log', methods=['GET'])
@login_required('admin')
def admin_audit_log():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT actor_username, action, details, created_at
            FROM audit_log ORDER BY created_at DESC LIMIT 100
            """
        )
        rows = cursor.fetchall()
        for row in rows:
            if row.get('created_at'):
                row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify(rows)
    except mysql.connector.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
   socketio.run(app, debug=True, port=5001)