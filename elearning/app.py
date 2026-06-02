
import os
import json
import re
import string
import random
from datetime import datetime, timedelta
from collections import Counter
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session, flash
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from sklearn.cluster import KMeans
import numpy as np
import mysql.connector
from functools import wraps

# Initialize Flask App and SocketIO
app = Flask(__name__)
app.secret_key = 'your_super_secret_key'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
SESSION_TIMEOUT_MINUTES = 30
socketio = SocketIO(app, cors_allowed_origins="*")
STUDENT_ROOM = 'all_students'

# --- Database Configuration ---
DB_CONFIG = {
    'user': 'root',
    'password': '',
    'host': '127.0.0.1',
    'database': 'elearning_db',
    'raise_on_warnings': True
}

# --- File Upload Configuration (absolute paths; supports photo/photos folder variants) ---
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_TYPE_DIRS = {
    'video': ('uploads/video', 'uploads/videos'),
    'photo': ('uploads/photo', 'uploads/photos'),
    'pdf': ('uploads/pdf', 'uploads/pdfs'),
}
ALLOWED_EXTENSIONS_VIDEO = {'mp4', 'mov', 'avi', 'webm', 'mkv', 'wmv', 'm4v', 'flv', 'ogv'}
ALLOWED_EXTENSIONS_PHOTO = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_EXTENSIONS_PDF = {'pdf'}


def primary_upload_dir(file_type):
    """Default folder for new uploads (singular path matches student dashboard URLs)."""
    rel = UPLOAD_TYPE_DIRS[file_type][0]
    path = os.path.join(_APP_ROOT, rel)
    os.makedirs(path, exist_ok=True)
    return path


def find_upload_file(filetype, filename):
    """Locate an uploaded file in singular or legacy plural folders."""
    safe = secure_filename(os.path.basename(filename))
    if not safe:
        return None, None
    key = filetype.rstrip('s') if filetype in ('videos', 'photos', 'pdfs') else filetype
    if key not in UPLOAD_TYPE_DIRS:
        return None, None
    for rel in UPLOAD_TYPE_DIRS[key]:
        folder = os.path.join(_APP_ROOT, rel)
        full = os.path.join(folder, safe)
        if os.path.isfile(full):
            return folder, safe
    return None, None


def upload_url_path(file_type):
    """URL segment for templates: /uploads/video/..., /uploads/photo/..., etc."""
    return file_type.rstrip('s') if file_type.endswith('s') else file_type


UPLOAD_FOLDER_VIDEOS = primary_upload_dir('video')
UPLOAD_FOLDER_PHOTOS = primary_upload_dir('photo')
UPLOAD_FOLDER_PDFS = primary_upload_dir('pdf')

app.config.update(
    UPLOAD_FOLDER_VIDEOS=UPLOAD_FOLDER_VIDEOS,
    UPLOAD_FOLDER_PHOTOS=UPLOAD_FOLDER_PHOTOS,
    UPLOAD_FOLDER_PDFS=UPLOAD_FOLDER_PDFS,
    MAX_CONTENT_LENGTH=4 * 1024 * 1024 * 1024   # 4 GB max upload size (supports ~1hr HD video)
)


# ── Handle file-too-large error gracefully ───────────────────────────────────
@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'error': 'File is too large. Maximum allowed size is 4 GB.'}), 413

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
    if stored_hash.startswith('pbkdf2:') or stored_hash.startswith('scrypt:'):
        return check_password_hash(stored_hash, password)
    return stored_hash == password


def resolve_student_usernames(cursor, assign_to=None, assign_class=''):
    """Resolve target students; default to all students when none selected."""
    assign_to = assign_to or []
    if assign_class:
        cursor.execute(
            "SELECT username FROM users WHERE role = 'student' AND class_name = %s",
            (assign_class,),
        )
        return [row[0] for row in cursor.fetchall()]
    if assign_to:
        return [u for u in assign_to if u]
    cursor.execute("SELECT username FROM users WHERE role = 'student'")
    return [row[0] for row in cursor.fetchall()]


def grant_content_permissions(cursor, content_id, assign_to=None, assign_class=''):
    for uname in resolve_student_usernames(cursor, assign_to, assign_class):
        cursor.execute(
            "INSERT IGNORE INTO content_permissions (content_id, student_username) VALUES (%s, %s)",
            (content_id, uname),
        )


def grant_quiz_permissions(cursor, test_id, assign_to=None, assign_class=''):
    for uname in resolve_student_usernames(cursor, assign_to, assign_class):
        cursor.execute(
            "INSERT IGNORE INTO quiz_permissions (test_id, student_username) VALUES (%s, %s)",
            (test_id, uname),
        )


def teacher_chat_room(teacher_username):
    return f"teacher:{teacher_username}"


def format_last_active(value):
    """Format DB timestamp for admin UI (avoid DATE_FORMAT %% escaping bugs)."""
    if value is None:
        return 'Never'
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M')
    if isinstance(value, str):
        if value == 'Never' or not value.strip():
            return 'Never'
        if '%Y' in value and '%' in value:
            return 'Never'
        return value
    return str(value)


def touch_last_active():
    """Update users.last_active in DB (throttled to once per minute per session)."""
    uid = session.get('id')
    if not uid or 'loggedin' not in session:
        return
    now = datetime.utcnow().timestamp()
    if now - session.get('_db_last_active_touch', 0) < 60:
        return
    session['_db_last_active_touch'] = now
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE users SET last_active = NOW() WHERE id = %s', (uid,))
        conn.commit()
    except mysql.connector.Error:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


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


def ensure_schema():
    """Apply lightweight migrations for older databases."""
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    migrations = [
        "ALTER TABLE users ADD COLUMN class_name VARCHAR(100) NULL",
        "ALTER TABLE users ADD COLUMN is_approved TINYINT(1) NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN last_active TIMESTAMP NULL",
        "ALTER TABLE content ADD COLUMN uploaded_by VARCHAR(100) NULL",
        "ALTER TABLE content ADD COLUMN view_count INT NOT NULL DEFAULT 0",
        "ALTER TABLE tests ADD COLUMN created_by VARCHAR(100) NULL",
        "ALTER TABLE tests ADD COLUMN due_date DATETIME NULL",
        "ALTER TABLE student_scores ADD COLUMN answers_json JSON NULL",
        "ALTER TABLE student_scores ADD COLUMN submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except mysql.connector.Error:
            pass
    conn.commit()
    cursor.close()
    conn.close()


def backfill_content_permissions():
    """Assign unassigned content to all students so dashboards are not empty."""
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT c.id FROM content c
            WHERE NOT EXISTS (
                SELECT 1 FROM content_permissions cp WHERE cp.content_id = c.id
            )
            """
        )
        orphan_ids = [row[0] for row in cursor.fetchall()]
        for cid in orphan_ids:
            grant_content_permissions(cursor, cid)
        if orphan_ids:
            conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def humanize_datetime(dt):
    if not dt:
        return ''
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            return dt
    now = datetime.now()
    if dt.tzinfo:
        now = datetime.now(dt.tzinfo)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        m = seconds // 60
        return f'{m} minute{"s" if m != 1 else ""} ago'
    if seconds < 86400:
        h = seconds // 3600
        return f'{h} hour{"s" if h != 1 else ""} ago'
    days = seconds // 86400
    if days < 30:
        return f'{days} day{"s" if days != 1 else ""} ago'
    return dt.strftime('%Y-%m-%d')

def analyze_sentiment(text):
    text = text.lower()
    positive = {'good', 'great', 'excellent', 'love', 'helpful', 'amazing', 'clear', 'thanks', 'awesome'}
    negative = {'bad', 'poor', 'confusing', 'hard', 'difficult', 'boring', 'hate', 'unclear', 'wrong'}
    words = set(re.findall(r'[a-z]+', text))
    if words & positive and not words & negative:
        return 'positive'
    if words & negative and not words & positive:
        return 'negative'
    if words & positive and words & negative:
        return 'mixed'
    return 'neutral'

@app.before_request
def check_session_timeout():
    if 'loggedin' not in session:
        return
    if request.endpoint in ('login', 'register', 'static', None):
        return
    last = session.get('last_activity')
    now = datetime.utcnow().timestamp()
    if last and (now - last) > SESSION_TIMEOUT_MINUTES * 60:
        session.clear()
        if (request.is_json or request.path.startswith('/get_') or request.path.startswith('/teacher/')
                or request.path.startswith('/admin/') or request.path.startswith('/student/')
                or request.path.startswith('/api/') or request.path.startswith('/bookmark')
                or request.path.startswith('/track_view')):
            return jsonify({'error': 'Session expired. Please log in again.'}), 401
        flash('Session expired due to inactivity. Please log in again.', 'error')
        return redirect(url_for('login'))
    session['last_activity'] = now
    touch_last_active()

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
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and verify_password(user['password'], password):
            if user['role'] == 'teacher' and not user.get('is_approved', 1):
                return render_template('login.html', message='Your teacher account is pending admin approval.')
            session.permanent = True
            session.update(
                loggedin=True, id=user['id'], username=user['username'], role=user['role'],
                last_activity=datetime.utcnow().timestamp(),
                _db_last_active_touch=0,
            )
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
        # FIX: class_name was missing from INSERT
        class_name = request.form.get('class_name', 'General')
        conn = get_db_connection()
        if not conn: return render_template('register.html', message='Database connection failed')
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            if cursor.fetchone():
                return render_template('register.html', message='Username already exists!')
            cursor.execute(
                'INSERT INTO users (username, password, role, class_name, is_approved) VALUES (%s, %s, %s, %s, 1)',
                (username, hash_password(password), 'student', class_name)
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

@app.route('/register_teacher', methods=['GET', 'POST'])
def register_teacher():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            return render_template('register_teacher.html', message='Username and password are required.')
        if len(password) < 6:
            return render_template('register_teacher.html', message='Password must be at least 6 characters.')
        conn = get_db_connection()
        if not conn:
            return render_template('register_teacher.html', message='Database connection failed.')
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            if cursor.fetchone():
                return render_template('register_teacher.html', message='Username already taken. Please choose another.')
            cursor.execute(
                'INSERT INTO users (username, password, role, class_name, is_approved) VALUES (%s, %s, %s, %s, %s)',
                (username, hash_password(password), 'teacher', None, 0)
            )
            conn.commit()
            log_audit('register_teacher', f'new teacher {username} awaiting approval', actor_username=username)
            return render_template('register_teacher.html',
                                   message='Account created! Awaiting admin approval before you can log in.')
        except mysql.connector.Error as err:
            conn.rollback()
            return render_template('register_teacher.html', message=f'Database error: {err}')
        finally:
            cursor.close()
            conn.close()
    return render_template('register_teacher.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/admin/dashboard_stats', methods=['GET'])
@login_required('admin')
def get_dashboard_stats():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(id) as count FROM users WHERE role = 'student'")
        total_students = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(id) as count FROM users WHERE role = 'teacher'")
        total_teachers = cursor.fetchone()['count']
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
                'backgroundColor': 'rgba(99, 102, 241, 0.6)',
                'borderColor': 'rgba(99, 102, 241, 1)',
                'borderWidth': 1
            }]
        }
        return jsonify(chart_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/admin')
@login_required('admin')
def admin_dashboard():
    return render_template('admin.html', username=session['username'])

@app.route('/teacher')
@login_required('teacher')
def teacher_dashboard():
    # Re-validate role from DB to prevent stale session misrouting
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT role FROM users WHERE id = %s', (session.get('id'),))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row['role'] != 'teacher':
            session['role'] = row['role']
            if row['role'] == 'student': return redirect(url_for('student_dashboard'))
            if row['role'] == 'admin': return redirect(url_for('admin_dashboard'))
    return render_template('teacher.html', username=session['username'])

@app.route('/admin/create_user', methods=['POST'])
@login_required('admin')
def create_user():
    username = request.form['username']
    password = request.form['password']
    role = request.form['role']
    # FIX: Added class_name field support
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
                (username, hash_password(password), role, class_name if role == 'student' else None, approved)
            )
            conn.commit()
            log_audit('create_user', f'{role} {username}')
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

def _save_content_upload(filetype, title, file, assign_to=None, assign_class=''):
    if not file or not getattr(file, 'filename', None) or file.filename == '':
        return jsonify({'error': 'No file selected. Please choose a file before uploading.'}), 400

    config_map = {
        'video': (app.config['UPLOAD_FOLDER_VIDEOS'], ALLOWED_EXTENSIONS_VIDEO),
        'photo': (app.config['UPLOAD_FOLDER_PHOTOS'], ALLOWED_EXTENSIONS_PHOTO),
        'pdf': (app.config['UPLOAD_FOLDER_PDFS'], ALLOWED_EXTENSIONS_PDF),
    }
    if filetype not in config_map:
        return jsonify({'error': f'Invalid file type category: {filetype}'}), 400

    upload_folder, allowed_extensions = config_map[filetype]
    if not allowed_file(file.filename, allowed_extensions):
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'unknown'
        return jsonify({
            'error': f'File extension ".{ext}" is not allowed for {filetype}. '
                     f'Allowed: {", ".join(sorted(allowed_extensions))}'
        }), 400

    title = (title or '').strip() or 'Untitled'
    filename = secure_filename(file.filename)
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    name, ext2 = os.path.splitext(filename)
    filename = f"{name}_{ts}{ext2}"
    save_path = os.path.join(upload_folder, filename)
    try:
        file.save(save_path)
    except Exception as e:
        return jsonify({'error': f'Could not save file to disk: {str(e)}'}), 500

    conn = get_db_connection()
    if not conn:
        try:
            os.remove(save_path)
        except OSError:
            pass
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = conn.cursor()
    try:
        uploader = session.get('username', 'unknown')
        try:
            cursor.execute(
                "INSERT INTO content (title, file_type, filename, uploaded_by) VALUES (%s, %s, %s, %s)",
                (title, filetype, filename, uploader),
            )
        except mysql.connector.Error:
            cursor.execute(
                "INSERT INTO content (title, file_type, filename) VALUES (%s, %s, %s)",
                (title, filetype, filename),
            )
        content_id = cursor.lastrowid
        grant_content_permissions(cursor, content_id, assign_to, assign_class)
        conn.commit()
        log_audit('upload_content', f'{filetype}: {title} (id={content_id})')
        socketio.emit('new_content', {'title': title, 'type': filetype.capitalize()})
        return jsonify({
            'message': f'{filetype.capitalize()} "{title}" uploaded successfully!',
            'filename': filename,
            'id': content_id,
        })
    except Exception as e:
        conn.rollback()
        try:
            os.remove(save_path)
        except OSError:
            pass
        return jsonify({'error': f'Database error: {str(e)}'}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/upload/<filetype>', methods=['POST'])
@login_required('admin,teacher')
def upload_file(filetype):
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request. Make sure the field name is "file".'}), 400
    title = request.form.get(f'{filetype}_title', '').strip() or request.form.get('title', '').strip()
    assign_to = request.form.getlist('assign_to')
    assign_class = request.form.get('assign_class', '').strip()
    return _save_content_upload(
        filetype, title, request.files['file'], assign_to, assign_class
    )


@app.route('/upload_content', methods=['POST'])
@login_required('admin,teacher')
def upload_content():
    filetype = request.form.get('file_type', '').strip()
    if filetype not in ('video', 'photo', 'pdf'):
        return jsonify({'error': 'Invalid or missing file_type'}), 400
    if 'file' not in request.files:
        return jsonify({'error': 'No file in request'}), 400
    title = request.form.get('title', '').strip()
    assign_to = request.form.getlist('assign_to')
    assign_class = request.form.get('assign_class', '').strip()
    return _save_content_upload(
        filetype, title, request.files['file'], assign_to, assign_class
    )

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
        log_audit('delete_content', f'id={content_id}')
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
        cursor.execute(
            "SELECT id, title, file_type, filename, upload_date, uploaded_by, COALESCE(view_count, 0) AS view_count FROM content ORDER BY upload_date DESC"
        )
        items = cursor.fetchall()
        for item in items:
            if item.get('upload_date'):
                item['upload_date_human'] = humanize_datetime(item['upload_date'])
                item['upload_date'] = item['upload_date'].strftime('%Y-%m-%d %H:%M:%S')
            # Serve files through the permission-checked view endpoint
            item['file_url'] = f"/view_content/{item['id']}"
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/student')
@login_required('student')
def student_dashboard():
    # Re-validate role from DB to prevent stale session misrouting
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT role FROM users WHERE id = %s', (session.get('id'),))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row['role'] != 'student':
            session['role'] = row['role']
            if row['role'] == 'teacher': return redirect(url_for('teacher_dashboard'))
            if row['role'] == 'admin': return redirect(url_for('admin_dashboard'))
    return render_template('student.html', username=session.get('username', 'Guest'))

@app.route('/get_content/<filetype>', methods=['GET'])
@login_required('student')
def get_content(filetype):
    student_username = session.get('username')
    search_q = request.args.get('q', '').strip()
    bookmarks_only = request.args.get('bookmarks') == '1'
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT c.id, c.title, c.filename, c.file_type, c.upload_date, c.uploaded_by,
                   COALESCE(c.view_count, 0) AS view_count,
                   IF(b.id IS NOT NULL, 1, 0) AS is_bookmarked
            FROM content c
            JOIN content_permissions cp ON c.id = cp.content_id
            LEFT JOIN bookmarks b ON b.content_id = c.id AND b.student_username = %s
            WHERE c.file_type = %s AND cp.student_username = %s
        """
        params = [student_username, filetype, student_username]
        if search_q:
            query += " AND c.title LIKE %s"
            params.append(f'%{search_q}%')
        if bookmarks_only:
            query += " AND b.id IS NOT NULL"
        query += " ORDER BY c.upload_date DESC"
        cursor.execute(query, tuple(params))
        items = cursor.fetchall()
        for item in items:
            if item.get('upload_date'):
                item['upload_date_human'] = humanize_datetime(item['upload_date'])
                item['upload_date'] = item['upload_date'].strftime('%Y-%m-%d %H:%M:%S')
            item['teacher_name'] = item.get('uploaded_by') or 'Staff'
            item['is_bookmarked'] = bool(item.get('is_bookmarked'))
            item['time_ago'] = item.get('upload_date_human', '')
            # Serve files through the permission-checked view endpoint
            item['file_url'] = f"/view_content/{item['id']}"
        return jsonify(items)
    finally:
        cursor.close()
        conn.close()


@app.route('/get_all_students', methods=['GET'])
@login_required('admin,teacher')
def get_all_students():
    class_filter = request.args.get('class_name')
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        query = "SELECT username FROM users WHERE role = 'student'"
        params = []
        if class_filter and class_filter != 'all':
            query += " AND class_name = %s"
            params.append(class_filter)
        query += " ORDER BY username ASC"
        cursor.execute(query, tuple(params))
        students = [row['username'] for row in cursor.fetchall()]
        return jsonify(students)
    finally:
        cursor.close()
        conn.close()

@app.route('/get_content_permissions/<int:content_id>', methods=['GET'])
@login_required('admin,teacher')
def get_content_permissions(content_id):
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT student_username FROM content_permissions WHERE content_id = %s", (content_id,))
        students = [row['student_username'] for row in cursor.fetchall()]
        return jsonify(students)
    finally:
        cursor.close()
        conn.close()

@app.route('/update_content_permissions/<int:content_id>', methods=['POST'])
@login_required('admin,teacher')
def update_content_permissions(content_id):
    data = request.get_json()
    student_usernames = data.get('students', [])
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM content_permissions WHERE content_id = %s", (content_id,))
        if student_usernames:
            sql = "INSERT INTO content_permissions (content_id, student_username) VALUES (%s, %s)"
            values = [(content_id, username) for username in student_usernames]
            cursor.executemany(sql, values)
        conn.commit()
        return jsonify({'message': 'Permissions updated successfully!'})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({'error': str(err)}), 500
    finally:
        cursor.close()
        conn.close()

# All student file access goes through /view_content/<id> which enforces
# per-student content_permissions. Teachers/admins may use direct URLs for preview.
@app.route('/uploads/<filetype>/<path:filename>')
def serve_upload(filetype, filename):
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    role = session.get('role')
    if role in ('teacher', 'admin'):
        folder, safe_name = find_upload_file(filetype, filename)
        if not folder:
            return "File not found", 404
        return send_from_directory(folder, safe_name)
    # Students must go through /view_content/<id> — never raw filenames.
    return "Access denied. Please use your dashboard to view content.", 403


@app.route('/view_content/<int:content_id>')
@login_required('student,teacher,admin')
def view_content(content_id):
    """Serve assigned content with correct MIME (PDF inline view, etc.).

    Students may only access content explicitly assigned to them. Teachers
    and admins are allowed to view content for inspection and classroom use.
    """
    conn = get_db_connection()
    if not conn:
        return "Database error", 500
    cursor = conn.cursor(dictionary=True)
    try:
        role = session.get('role')
        if role in ('teacher', 'admin'):
            cursor.execute("SELECT filename, file_type FROM content WHERE id = %s", (content_id,))
        else:
            cursor.execute(
                """
                SELECT c.filename, c.file_type FROM content c
                JOIN content_permissions cp ON c.id = cp.content_id
                WHERE c.id = %s AND cp.student_username = %s
                """,
                (content_id, session.get('username')),
            )
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    if not row:
        return "Not found", 404
    folder, safe_name = find_upload_file(row['file_type'], row['filename'])
    if not folder:
        return "File missing on server", 404
    # Detect MIME from actual extension for photos (png, gif, webp, jpg, etc.)
    ft = row['file_type']
    if ft == 'pdf':
        mime = 'application/pdf'
    elif ft == 'video':
        ext = (safe_name.rsplit('.', 1)[-1].lower()) if '.' in safe_name else 'mp4'
        mime = {'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
                'avi': 'video/x-msvideo', 'mkv': 'video/x-matroska',
                'wmv': 'video/x-ms-wmv', 'm4v': 'video/x-m4v',
                'flv': 'video/x-flv', 'ogv': 'video/ogg'}.get(ext, 'video/mp4')
    elif ft == 'photo':
        ext = (safe_name.rsplit('.', 1)[-1].lower()) if '.' in safe_name else 'jpeg'
        mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                'gif': 'image/gif', 'webp': 'image/webp'}.get(ext, 'image/jpeg')
    else:
        mime = None
    return send_from_directory(folder, safe_name, mimetype=mime)


@app.route('/create_test', methods=['POST'])
@login_required('admin,teacher')
def create_test():
    data = request.json
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        due_date = data.get('due_date') or None
        creator = session.get('username')
        try:
            cursor.execute(
                "INSERT INTO tests (title, due_date, created_by) VALUES (%s, %s, %s)",
                (data['title'], due_date, creator),
            )
        except mysql.connector.Error:
            cursor.execute("INSERT INTO tests (title, due_date) VALUES (%s, %s)", (data['title'], due_date))
        test_id = cursor.lastrowid
        for q in data['questions']:
            options_json = json.dumps(q['options'])
            cursor.execute(
                "INSERT INTO questions (test_id, question_text, options, correct_answer) VALUES (%s, %s, %s, %s)",
                (test_id, q['question'], options_json, q['answer'])
            )
        assign_to = data.get('assign_to') or []
        assign_class = (data.get('assign_class') or '').strip()
        grant_quiz_permissions(cursor, test_id, assign_to, assign_class)
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
        cursor.execute("SELECT id, title, created_at, due_date FROM tests ORDER BY created_at DESC")
        tests = cursor.fetchall()
        for test in tests:
            if test.get('created_at'):
                test['created_at'] = test['created_at'].strftime('%Y-%m-%d %H:%M')
            if test.get('due_date'):
                test['due_date_iso'] = test['due_date'].strftime('%Y-%m-%dT%H:%M:%S')
                test['due_date'] = test['due_date'].strftime('%Y-%m-%d %H:%M')
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
        cursor.execute("DELETE FROM student_scores WHERE test_id = %s", (test_id,))
        cursor.execute("DELETE FROM questions WHERE test_id = %s", (test_id,))
        cursor.execute("DELETE FROM tests WHERE id = %s", (test_id,))
        conn.commit()
        return jsonify({'message': 'Test and all associated data deleted successfully!'})
    except mysql.connector.Error as err:
        conn.rollback()
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
    try:
        cursor.execute("SELECT student_username FROM quiz_permissions WHERE test_id = %s", (test_id,))
        students = [row['student_username'] for row in cursor.fetchall()]
        return jsonify(students)
    finally:
        cursor.close()
        conn.close()

@app.route('/update_quiz_permissions/<int:test_id>', methods=['POST'])
@login_required('admin,teacher')
def update_quiz_permissions(test_id):
    data = request.get_json()
    student_usernames = data.get('students', [])
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM quiz_permissions WHERE test_id = %s", (test_id,))
        if student_usernames:
            sql = "INSERT INTO quiz_permissions (test_id, student_username) VALUES (%s, %s)"
            values = [(test_id, username) for username in student_usernames]
            cursor.executemany(sql, values)
        conn.commit()
        return jsonify({'message': 'Quiz permissions updated successfully!'})
    except mysql.connector.Error as err:
        conn.rollback()
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
        # Show ALL tests not yet completed by this student.
        # A quiz is visible if:
        #   (a) it is explicitly assigned to this student via quiz_permissions, OR
        #   (b) no permissions exist for it at all (open to every student by default)
        query = """
            SELECT t.id, t.title, t.due_date, t.created_by
            FROM tests t
            WHERE t.id NOT IN (
                SELECT ss.test_id FROM student_scores ss
                WHERE ss.student_username = %s
            )
            AND (
                EXISTS (
                    SELECT 1 FROM quiz_permissions qp
                    WHERE qp.test_id = t.id AND qp.student_username = %s
                )
                OR NOT EXISTS (
                    SELECT 1 FROM quiz_permissions qp2
                    WHERE qp2.test_id = t.id
                )
            )
            ORDER BY t.created_at DESC
        """
        cursor.execute(query, (student_username, student_username))
        tests = cursor.fetchall()
        for test in tests:
            if test.get('due_date'):
                test['due_date_iso'] = test['due_date'].strftime('%Y-%m-%dT%H:%M:%S')
                test['due_date_human'] = test['due_date'].strftime('%Y-%m-%d %H:%M')
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
        cursor.execute(
            "SELECT COUNT(*) as count FROM student_scores WHERE student_username = %s AND test_id = %s",
            (session['username'], test_id)
        )
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
    try:
        cursor.execute(
            "SELECT COUNT(*) as count FROM student_scores WHERE student_username = %s AND test_id = %s",
            (student_username, test_id)
        )
        if cursor.fetchone()['count'] > 0:
            return jsonify({'error': 'You have already completed this test.'}), 409
        cursor.execute("SELECT correct_answer FROM questions WHERE test_id = %s ORDER BY id", (test_id,))
        correct_answers = [row['correct_answer'] for row in cursor.fetchall()]
        score_count = sum(1 for i, ans in enumerate(student_answers) if i < len(correct_answers) and str(ans) == str(correct_answers[i]))
        score_percent = (score_count / len(correct_answers)) * 100 if correct_answers else 0
        # FIX: Use non-dict cursor for INSERT
        cursor.close()
        cursor = conn.cursor()
        answers_json = json.dumps(student_answers)
        try:
            cursor.execute(
                "INSERT INTO student_scores (student_username, test_id, score, answers_json) VALUES (%s, %s, %s, %s)",
                (student_username, test_id, score_percent, answers_json),
            )
        except mysql.connector.Error:
            cursor.execute(
                "INSERT INTO student_scores (student_username, test_id, score) VALUES (%s, %s, %s)",
                (student_username, test_id, score_percent),
            )
        conn.commit()
        return jsonify({'message': 'Test submitted!', 'score': score_percent})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/get_scores', methods=['GET'])
@login_required('student')
def get_scores():
    student_username = session['username']
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT t.title AS test_title, ss.score, ss.test_id,
                   COALESCE(t.created_by, 'Teacher') AS created_by,
                   ss.submission_date
            FROM student_scores ss
            JOIN tests t ON ss.test_id = t.id
            WHERE ss.student_username = %s
            ORDER BY ss.submission_date DESC
        """
        cursor.execute(query, (student_username,))
        rows = cursor.fetchall()
        for row in rows:
            if row.get('submission_date'):
                row['submission_date'] = row['submission_date'].strftime('%Y-%m-%d %H:%M')
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()

@app.route('/get_comments/<int:content_id>', methods=['GET'])
@login_required('admin,teacher,student')
def get_comments(content_id):
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
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
    sentiment = 'neutral'
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO comments (content_id, user_username, comment_text, sentiment) VALUES (%s, %s, %s, %s)",
            (content_id, user_username, comment_text, sentiment)
        )
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
        clustered_students = {f'Cluster {i+1}': [] for i in range(n_clusters)}
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
    return render_template('chat.html', username=session.get('username'), role=session.get('role'))

@app.route('/quiz_review/<int:test_id>')
@login_required('student')
def quiz_review(test_id):
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return "Database error", 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT score, answers_json FROM student_scores WHERE student_username = %s AND test_id = %s",
            (student, test_id),
        )
        score_row = cursor.fetchone()
        if not score_row:
            return redirect(url_for('student_dashboard'))
        cursor.execute("SELECT title FROM tests WHERE id = %s", (test_id,))
        test = cursor.fetchone()
        test_title = (test or {}).get('title', 'Quiz Review')
        answers = []
        if score_row.get('answers_json'):
            try:
                answers = json.loads(score_row['answers_json'])
            except (TypeError, json.JSONDecodeError):
                answers = score_row['answers_json'] if isinstance(score_row['answers_json'], list) else []
        cursor.execute(
            "SELECT question_text, options, correct_answer FROM questions WHERE test_id = %s ORDER BY id",
            (test_id,),
        )
        questions = cursor.fetchall()
        review = []
        for i, q in enumerate(questions):
            opts = json.loads(q['options']) if isinstance(q['options'], str) else q['options']
            your = answers[i] if i < len(answers) else None
            review.append({
                'question': q['question_text'],
                'options': opts,
                'correct_answer': q['correct_answer'],
                'your_answer': your,
                'is_correct': str(your) == str(q['correct_answer']),
            })
        correct_count = sum(1 for r in review if r['is_correct'])
        return render_template(
            'quiz_review.html',
            test_title=test_title,
            score=score_row['score'],
            correct_count=correct_count,
            total=len(review),
            review=review,
        )
    finally:
        cursor.close()
        conn.close()

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

CHAT_ROOM = 'general_chat'

# Track who is in the chat room: sid -> username
_chat_users = {}

@socketio.on('join_general_chat')
def handle_join_general_chat(data):
    username = data.get('username', 'Unknown')
    _chat_users[request.sid] = username
    join_room(CHAT_ROOM)
    # Announce to everyone else
    emit('user_announcement', {'msg': f'{username} joined the chat.'}, to=CHAT_ROOM, skip_sid=request.sid)
    # Tell everyone updated online count
    socketio.emit('online_users', {'count': len(_chat_users)}, to=CHAT_ROOM)

@socketio.on('send_general_message')
def handle_send_general_message(data):
    username = data.get('username', _chat_users.get(request.sid, 'Unknown'))
    role     = data.get('role', 'student')
    msg      = data.get('msg', '').strip()
    if not msg:
        return
    now_str = datetime.now().strftime('%H:%M')
    # Broadcast to everyone in the room including sender
    emit('receive_general_message', {'username': username, 'role': role, 'msg': msg, 'time': now_str}, to=CHAT_ROOM)

@socketio.on('leave_general_chat')
def handle_leave_general_chat(data):
    username = data.get('username', _chat_users.pop(request.sid, 'Someone'))
    _chat_users.pop(request.sid, None)
    leave_room(CHAT_ROOM)
    emit('user_announcement', {'msg': f'{username} left the chat.'}, to=CHAT_ROOM)

_teacher_chat_sids = {}


@socketio.on('join_teacher_chat')
def handle_join_teacher_chat(data):
    data = data or {}
    room = data.get('room', '').strip()
    if not room or not room.startswith('teacher:'):
        return
    join_room(room)
    _teacher_chat_sids[request.sid] = {
        'room': room,
        'username': session.get('username') or data.get('username', 'Unknown'),
        'role': session.get('role') or data.get('role', 'student'),
    }


@socketio.on('leave_teacher_chat')
def handle_leave_teacher_chat(data):
    room = (data or {}).get('room', '').strip()
    if room:
        leave_room(room)
    _teacher_chat_sids.pop(request.sid, None)


@socketio.on('send_teacher_chat')
def handle_send_teacher_chat(data):
    data = data or {}
    room = data.get('room', '').strip()
    msg = data.get('msg', '').strip()
    if not room or not msg:
        return
    info = _teacher_chat_sids.get(request.sid, {})
    username = session.get('username') or data.get('username') or info.get('username', 'Unknown')
    role = session.get('role') or data.get('role') or info.get('role', 'student')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO chat_messages (room_key, sender_username, sender_role, message_text)
                VALUES (%s, %s, %s, %s)
                """,
                (room, username, role, msg),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            cursor.close()
            conn.close()
    emit(
        'receive_teacher_chat',
        {'room': room, 'username': username, 'role': role, 'msg': msg, 'time': now_str},
        to=room,
    )


@socketio.on('disconnect')
def handle_disconnect_chat():
    username = _chat_users.pop(request.sid, None)
    if username:
        socketio.emit('user_announcement', {'msg': f'{username} left the chat.'}, to=CHAT_ROOM)
        socketio.emit('online_users', {'count': len(_chat_users)}, to=CHAT_ROOM)
    leave_room(CHAT_ROOM)
    chat_info = _teacher_chat_sids.pop(request.sid, None)
    if chat_info and chat_info.get('room'):
        leave_room(chat_info['room'])
    leave_room(LIVE_CLASS_ROOM)
    socketio.emit('user_left', {'sid': request.sid}, to=LIVE_CLASS_ROOM)

# ─────────────────────────────────────────────────────────────
#  OFFLINE NLP QUIZ GENERATOR
# ─────────────────────────────────────────────────────────────

def _extract_pdf_text(file_obj):
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(file_obj)
        pages_text = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t.strip())
        return "\n".join(pages_text)
    except Exception as e:
        raise RuntimeError(f"Could not read PDF: {e}")

def _clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '', text)
    return text.strip()

def _split_sentences(text):
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sentences = []
    for s in raw:
        s = s.strip()
        word_count = len(s.split())
        if 5 <= word_count <= 60 and not s.startswith('http'):
            sentences.append(s)
    return sentences

def _extract_keywords_rake(text, max_keywords=40):
    STOP = set("""
    a an the and or but if in on at to for of with is are was were be been being
    has have had do does did will would could should may might shall can
    this that these those it its he she we they them their his her our
    i me my you your us who which what when where how all each every both
    about above after before between by from into through during including
    not no nor only own same so than too very just because as well also
    """.split())
    word_pattern = re.compile(r'[a-zA-Z]+')
    words = word_pattern.findall(text.lower())
    phrases = []
    current = []
    for w in words:
        if w in STOP or len(w) <= 1:
            if current:
                phrases.append(tuple(current))
                current = []
        else:
            current.append(w)
    if current:
        phrases.append(tuple(current))
    word_freq = Counter()
    word_degree = Counter()
    for phrase in phrases:
        for w in phrase:
            word_freq[w] += 1
            word_degree[w] += len(phrase)
    scored = {}
    for phrase in set(phrases):
        score = sum((word_degree[w] + word_freq[w]) / max(word_freq[w], 1) for w in phrase)
        key = ' '.join(phrase)
        if key not in scored or scored[key] < score:
            scored[key] = score
    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
    return ranked[:max_keywords]

def _find_sentence_for_keyword(keyword, sentences):
    kw_lower = keyword.lower()
    candidates = [s for s in sentences if kw_lower in s.lower()]
    if not candidates:
        return None
    return min(candidates, key=lambda s: len(s))

def _make_wh_question(sentence, keyword):
    kw_cap = keyword.strip().capitalize()
    idx = sentence.lower().find(keyword.lower())
    if idx == -1:
        return f"What is {kw_cap}?", keyword
    match = re.search(
        r'(?i)' + re.escape(keyword) + r'\s+(?:is|are|was|were|refers to|means|defined as)\s+(.+)',
        sentence
    )
    if match:
        return f"What is {kw_cap}?", match.group(1).rstrip('.')
    before = sentence[:idx].strip().rstrip(',')
    if before:
        return f"What does '{before}' describe?", keyword
    return f"Which term is described as: \"{sentence.rstrip('.')}\"?", keyword

def _generate_distractors(correct_answer, all_keywords, n=3):
    correct_lower = correct_answer.lower()
    correct_len = len(correct_answer.split())
    pool = [kw for kw, _ in all_keywords if kw.lower() != correct_lower and abs(len(kw.split()) - correct_len) <= 2]
    if len(pool) < n:
        pool = [kw for kw, _ in all_keywords if kw.lower() != correct_lower]
    random.shuffle(pool)
    return pool[:n]

def _build_questions(text, num_questions=5):
    text = _clean_text(text)
    sentences = _split_sentences(text)
    if len(sentences) < 3:
        raise ValueError("Not enough readable sentences found in the PDF.")
    all_keywords = _extract_keywords_rake(text, max_keywords=80)
    if len(all_keywords) < 4:
        raise ValueError("Could not extract enough keywords from the PDF content.")
    questions = []
    used_sentences = set()
    used_keywords = set()
    for keyword, score in all_keywords:
        if len(questions) >= num_questions:
            break
        words = keyword.split()
        if len(words) > 5 or len(words) < 1:
            continue
        if keyword.lower() in used_keywords:
            continue
        sentence = _find_sentence_for_keyword(keyword, sentences)
        if sentence is None or sentence in used_sentences:
            continue
        wh_result = _make_wh_question(sentence, keyword)
        if wh_result is None:
            continue
        q_text, correct_answer = wh_result
        correct_answer = correct_answer.strip().rstrip('.').strip()
        if not correct_answer or len(correct_answer) > 120:
            continue
        distractors = _generate_distractors(correct_answer, all_keywords, n=3)
        if len(distractors) < 3:
            continue
        options = [correct_answer] + distractors[:3]
        random.shuffle(options)
        questions.append({"question": q_text, "options": options, "answer": correct_answer})
        used_sentences.add(sentence)
        used_keywords.add(keyword.lower())
    if len(questions) < 2:
        raise ValueError("The PDF doesn't have enough structured content to auto-generate questions.")
    return questions[:num_questions]

@app.route('/generate_quiz_from_pdf', methods=['POST'])
@login_required('admin,teacher')
def generate_quiz_from_pdf():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'No PDF file provided'}), 400
    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '' or not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a valid .pdf file'}), 400
    try:
        num_questions = int(request.form.get('num_questions', 5))
        num_questions = max(2, min(num_questions, 15))
    except ValueError:
        num_questions = 5
    try:
        text = _extract_pdf_text(pdf_file)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500
    if len(text.strip()) < 200:
        return jsonify({'error': 'PDF has too little readable text.'}), 400
    try:
        questions = _build_questions(text, num_questions=num_questions)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Question generation failed: {e}'}), 500
    return jsonify({'questions': questions})
# --- ADD THESE ROUTES TO app.py ---

@app.route('/admin/get_users', methods=['GET'])
@login_required('admin')
def get_users():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, username, role, IFNULL(class_name, 'N/A') AS class_name FROM users "
            "WHERE role IN ('student', 'teacher') ORDER BY role, username"
        )
        users = cursor.fetchall()
        return jsonify(users)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


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
        log_audit('approve_teacher', f'user_id={user_id}')
        return jsonify({'message': 'Teacher approved'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/admin/delete_user/<int:user_id>', methods=['DELETE'])
@login_required('admin')
def delete_user(user_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username, role FROM users WHERE id = %s AND role != 'admin'", (user_id,))
        target = cursor.fetchone()
        if not target:
            return jsonify({'error': 'User not found or cannot delete admin'}), 404
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        log_audit('delete_user', f"{target[1]} {target[0]} (id={user_id})")
        return jsonify({'message': 'User deleted successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/admin/update_user/<int:user_id>', methods=['PUT'])
@login_required('admin')
def update_user(user_id):
    data = request.json
    username   = data.get('username', '').strip()
    password   = data.get('password')  # None means keep existing
    role       = data.get('role')
    class_name = data.get('class_name')

    if not username:
        return jsonify({'error': 'Username cannot be empty'}), 400
    if role not in ('student', 'teacher'):
        return jsonify({'error': 'Invalid role'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        # Check target user exists and is not admin
        cursor.execute("SELECT id FROM users WHERE id = %s AND role != 'admin'", (user_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'User not found or cannot edit admin'}), 404

        # Check username uniqueness (exclude self)
        cursor.execute("SELECT id FROM users WHERE username = %s AND id != %s", (username, user_id))
        if cursor.fetchone():
            return jsonify({'error': f"Username '{username}' is already taken"}), 409

        if password:
            cursor.execute(
                "UPDATE users SET username=%s, password=%s, role=%s, class_name=%s WHERE id=%s",
                (username, password, role, class_name if role == 'student' else None, user_id)
            )
        else:
            cursor.execute(
                "UPDATE users SET username=%s, role=%s, class_name=%s WHERE id=%s",
                (username, role, class_name if role == 'student' else None, user_id)
            )
        conn.commit()
        return jsonify({'message': f"User '{username}' updated successfully"})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/admin/share_content', methods=['POST'])
@login_required('admin')
def share_content():
    data = request.json
    content_id = data.get('content_id')
    target = data.get('target') # can be 'all' or a specific 'username'
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if target == 'all':
            # Share with all students
            cursor.execute("SELECT username FROM users WHERE role = 'student'")
            students = cursor.fetchall()
            for student in students:
                cursor.execute("INSERT IGNORE INTO content_permissions (content_id, student_username) VALUES (%s, %s)", 
                               (content_id, student[0]))
        else:
            # Share with one specific student
            cursor.execute("INSERT IGNORE INTO content_permissions (content_id, student_username) VALUES (%s, %s)", 
                           (content_id, target))
        conn.commit()
        return jsonify({"message": f"Content shared with {target} successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# ── Teacher dashboard APIs ────────────────────────────────────────────────────

@app.route('/teacher/my_content', methods=['GET'])
@login_required('teacher,admin')
def teacher_my_content():
    teacher = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT c.id, c.title, c.file_type, c.filename, c.upload_date,
                   COALESCE(c.view_count, 0) AS view_count,
                   (SELECT COUNT(*) FROM content_permissions cp WHERE cp.content_id = c.id) AS assigned_count
            FROM content c
            WHERE c.uploaded_by = %s
            ORDER BY c.upload_date DESC
            """,
            (teacher,),
        )
        items = cursor.fetchall()
        for item in items:
            if item.get('upload_date'):
                item['upload_date'] = item['upload_date'].strftime('%Y-%m-%d %H:%M')
        return jsonify(items)
    finally:
        cursor.close()
        conn.close()


@app.route('/teacher/get_classes', methods=['GET'])
@login_required('teacher,admin')
def teacher_get_classes():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT class_name FROM users
            WHERE role = 'student' AND class_name IS NOT NULL AND class_name != ''
            ORDER BY class_name
            """
        )
        return jsonify([row[0] for row in cursor.fetchall()])
    finally:
        cursor.close()
        conn.close()


@app.route('/teacher/get_students', methods=['GET'])
@login_required('teacher,admin')
def teacher_get_students():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT username, COALESCE(class_name, '') AS class_name
            FROM users WHERE role = 'student'
            ORDER BY username
            """
        )
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route('/teacher/quiz_analytics', methods=['GET'])
@login_required('teacher,admin')
def teacher_quiz_analytics():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT t.id, t.title, t.due_date,
                   COUNT(ss.id) AS submissions,
                   AVG(ss.score) AS avg_score,
                   MIN(ss.score) AS min_score,
                   MAX(ss.score) AS max_score
            FROM tests t
            LEFT JOIN student_scores ss ON ss.test_id = t.id
            GROUP BY t.id, t.title, t.due_date
            ORDER BY t.created_at DESC
            """
        )
        rows = cursor.fetchall()
        for row in rows:
            if row.get('due_date'):
                row['due_date'] = row['due_date'].strftime('%Y-%m-%d %H:%M')
            row['avg_score'] = round(row['avg_score'], 1) if row.get('avg_score') is not None else 0
            row['submissions'] = row.get('submissions') or 0
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route('/teacher/quiz_submissions/<int:test_id>', methods=['GET'])
@login_required('teacher,admin')
def teacher_quiz_submissions(test_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT ss.student_username, ss.score, ss.submission_date,
                   COALESCE(u.class_name, '') AS class_name
            FROM student_scores ss
            LEFT JOIN users u ON u.username = ss.student_username
            WHERE ss.test_id = %s
            ORDER BY ss.submission_date DESC
            """,
            (test_id,),
        )
        rows = cursor.fetchall()
        for row in rows:
            if row.get('submission_date'):
                row['submission_date'] = row['submission_date'].strftime('%Y-%m-%d %H:%M')
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route('/teacher/broadcast', methods=['POST'])
@login_required('teacher,admin')
def teacher_broadcast():
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()
    target_class = (data.get('target_class') or '').strip() or None
    if not message:
        return jsonify({'error': 'Message is required'}), 400
    teacher = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO announcements (teacher_username, message, target_class)
            VALUES (%s, %s, %s)
            """,
            (teacher, message, target_class),
        )
        conn.commit()
        log_audit('broadcast', message[:200], actor_username=teacher)
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
    socketio.emit(
        'teacher_broadcast',
        {
            'from': teacher,
            'teacher_username': teacher,
            'message': message,
            'target_class': target_class or '',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        },
    )
    return jsonify({'message': 'Announcement sent to students'})


# ── Student dashboard APIs ────────────────────────────────────────────────────

@app.route('/student/progress', methods=['GET'])
@login_required('student')
def student_progress():
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(DISTINCT t.id) AS total_tests
            FROM tests t
            WHERE (
                EXISTS (
                    SELECT 1 FROM quiz_permissions qp
                    WHERE qp.test_id = t.id AND qp.student_username = %s
                )
                OR NOT EXISTS (SELECT 1 FROM quiz_permissions qp2 WHERE qp2.test_id = t.id)
            )
            """,
            (student,),
        )
        total_tests = (cursor.fetchone() or {}).get('total_tests', 0)

        cursor.execute(
            "SELECT COUNT(*) AS done_tests FROM student_scores WHERE student_username = %s",
            (student,),
        )
        done_tests = (cursor.fetchone() or {}).get('done_tests', 0)

        cursor.execute(
            "SELECT COUNT(*) AS total_content FROM content_permissions WHERE student_username = %s",
            (student,),
        )
        total_content = (cursor.fetchone() or {}).get('total_content', 0)

        cursor.execute(
            "SELECT COUNT(DISTINCT content_id) AS viewed_content FROM content_views WHERE student_username = %s",
            (student,),
        )
        viewed_content = (cursor.fetchone() or {}).get('viewed_content', 0)

        cursor.execute(
            "SELECT AVG(score) AS avg_score FROM student_scores WHERE student_username = %s",
            (student,),
        )
        avg = (cursor.fetchone() or {}).get('avg_score')
        avg_score = round(avg, 1) if avg is not None else 0

        cursor.execute(
            "SELECT COUNT(*) AS bookmarks FROM bookmarks WHERE student_username = %s",
            (student,),
        )
        bookmarks = (cursor.fetchone() or {}).get('bookmarks', 0)

        return jsonify({
            'total_tests': total_tests,
            'done_tests': done_tests,
            'total_content': total_content,
            'viewed_content': viewed_content,
            'avg_score': avg_score,
            'bookmarks': bookmarks,
        })
    finally:
        cursor.close()
        conn.close()


@app.route('/student/announcements', methods=['GET'])
@login_required('student')
def student_announcements():
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT class_name FROM users WHERE username = %s", (student,))
        row = cursor.fetchone()
        class_name = (row or {}).get('class_name')
        cursor.execute(
            """
            SELECT teacher_username, message, target_class, created_at
            FROM announcements
            WHERE target_class IS NULL OR target_class = '' OR target_class = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (class_name,),
        )
        items = cursor.fetchall()
        for item in items:
            if item.get('created_at'):
                item['created_at'] = item['created_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify(items)
    finally:
        cursor.close()
        conn.close()


@app.route('/track_view/<int:content_id>', methods=['POST'])
@login_required('student')
def track_view(content_id):
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT c.id FROM content c
            JOIN content_permissions cp ON c.id = cp.content_id
            WHERE c.id = %s AND cp.student_username = %s
            """,
            (content_id, student),
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Not allowed'}), 403
        cursor.execute(
            """
            INSERT IGNORE INTO content_views (content_id, student_username)
            VALUES (%s, %s)
            """,
            (content_id, student),
        )
        if cursor.rowcount:
            cursor.execute(
                "UPDATE content SET view_count = COALESCE(view_count, 0) + 1 WHERE id = %s",
                (content_id,),
            )
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/bookmark/<int:content_id>', methods=['POST'])
@login_required('student')
def add_bookmark(content_id):
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT IGNORE INTO bookmarks (content_id, student_username) VALUES (%s, %s)",
            (content_id, student),
        )
        conn.commit()
        return jsonify({'message': 'Bookmarked'})
    finally:
        cursor.close()
        conn.close()


@app.route('/bookmark/<int:content_id>', methods=['DELETE'])
@login_required('student')
def remove_bookmark(content_id):
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM bookmarks WHERE content_id = %s AND student_username = %s",
            (content_id, student),
        )
        conn.commit()
        return jsonify({'message': 'Removed'})
    finally:
        cursor.close()
        conn.close()


@app.route('/get_bookmark_ids', methods=['GET'])
@login_required('student')
def get_bookmark_ids():
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT content_id FROM bookmarks WHERE student_username = %s",
            (student,),
        )
        return jsonify([row[0] for row in cursor.fetchall()])
    finally:
        cursor.close()
        conn.close()


@app.route('/get_bookmarks', methods=['GET'])
@login_required('student')
def get_bookmarks():
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT c.id, c.title, c.file_type, c.upload_date, c.uploaded_by
            FROM bookmarks b
            JOIN content c ON c.id = b.content_id
            WHERE b.student_username = %s
            ORDER BY b.id DESC
            """,
            (student,),
        )
        items = cursor.fetchall()
        for item in items:
            if item.get('upload_date'):
                item['upload_date'] = item['upload_date'].strftime('%Y-%m-%d %H:%M')
        return jsonify(items)
    finally:
        cursor.close()
        conn.close()


@app.route('/download_content/<int:content_id>')
@login_required('student')
def download_content(content_id):
    conn = get_db_connection()
    if not conn:
        return "Database error", 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT c.filename, c.file_type, c.title FROM content c
            JOIN content_permissions cp ON c.id = cp.content_id
            WHERE c.id = %s AND cp.student_username = %s
            """,
            (content_id, session.get('username')),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    if not row:
        return "Not found", 404
    folder, safe_name = find_upload_file(row['file_type'], row['filename'])
    if not folder:
        return "File missing", 404
    return send_from_directory(
        folder, safe_name, as_attachment=True, download_name=row.get('title') or safe_name
    )


@app.route('/get_score_review/<int:test_id>', methods=['GET'])
@login_required('student')
def get_score_review(test_id):
    student = session.get('username')
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT score, answers_json FROM student_scores
            WHERE student_username = %s AND test_id = %s
            """,
            (student, test_id),
        )
        score_row = cursor.fetchone()
        if not score_row:
            return jsonify({'error': 'No submission found'}), 404
        answers = []
        if score_row.get('answers_json'):
            try:
                answers = json.loads(score_row['answers_json'])
            except (TypeError, json.JSONDecodeError):
                answers = score_row['answers_json'] if isinstance(score_row['answers_json'], list) else []
        cursor.execute(
            "SELECT question_text, options, correct_answer FROM questions WHERE test_id = %s ORDER BY id",
            (test_id,),
        )
        questions = cursor.fetchall()
        review = []
        for i, q in enumerate(questions):
            opts = json.loads(q['options']) if isinstance(q['options'], str) else q['options']
            your = answers[i] if i < len(answers) else None
            review.append({
                'question': q['question_text'],
                'options': opts,
                'correct_answer': q['correct_answer'],
                'your_answer': your,
            })
        return jsonify({'score': score_row['score'], 'review': review})
    finally:
        cursor.close()
        conn.close()


@app.route('/change_password', methods=['POST'])
@login_required('admin,teacher,student')
def change_password():
    cur_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if not cur_pw or not new_pw:
        return jsonify({'error': 'All fields are required'}), 400
    if new_pw != confirm:
        return jsonify({'error': 'New passwords do not match'}), 400
    if len(new_pw) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT password FROM users WHERE id = %s", (session.get('id'),))
        row = cursor.fetchone()
        if not row or not verify_password(row['password'], cur_pw):
            return jsonify({'error': 'Current password is incorrect'}), 400
        cursor.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (hash_password(new_pw), session.get('id')),
        )
        conn.commit()
        return jsonify({'message': 'Password updated successfully'})
    finally:
        cursor.close()
        conn.close()


# ── Chat REST API ─────────────────────────────────────────────────────────────

@app.route('/api/chat/contacts', methods=['GET'])
@login_required('teacher,student')
def api_chat_contacts():
    role = session.get('role')
    username = session.get('username')
    if role == 'teacher':
        # Return own classroom room plus each student as an individual contact
        conn = get_db_connection()
        if not conn:
            return jsonify({'room': teacher_chat_room(username), 'contacts': []})
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT username FROM users WHERE role = 'student' ORDER BY username",
            )
            students = [r['username'] for r in cursor.fetchall()]
            # Each student contact shares the same room key as when the student
            # messages this teacher: teacher:<teacherUsername>
            contacts = [{'username': s, 'label': s, 'room': teacher_chat_room(username)} for s in students]
            return jsonify({'room': teacher_chat_room(username), 'contacts': contacts})
        finally:
            cursor.close()
            conn.close()
    # Always return ALL approved teachers so new teachers are immediately
    # visible in every student's chat list, even before uploading any content.
    conn = get_db_connection()
    if not conn:
        return jsonify({'contacts': []})
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT username FROM users
            WHERE role = 'teacher' AND COALESCE(is_approved, 1) = 1
            ORDER BY username
            """
        )
        contacts = [
            {'username': r['username'], 'label': r['username']}
            for r in cursor.fetchall()
            if r['username']
        ]
        return jsonify({'contacts': contacts})
    finally:
        cursor.close()
        conn.close()


@app.route('/api/chat/history', methods=['GET'])
@login_required('teacher,student')
def api_chat_history():
    room = request.args.get('room', '').strip()
    if not room:
        return jsonify([])
    conn = get_db_connection()
    if not conn:
        return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT sender_username, sender_role, message_text, created_at
            FROM chat_messages
            WHERE room_key = %s
            ORDER BY created_at ASC
            LIMIT 200
            """,
            (room,),
        )
        rows = cursor.fetchall()
        for row in rows:
            if row.get('created_at'):
                row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/all_content', methods=['GET'])
@login_required('admin')
def admin_all_content_alias():
    return admin_get_all_content()


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
            FROM audit_log
            ORDER BY created_at DESC
            LIMIT 100
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
    ensure_schema()
    backfill_content_permissions()
    socketio.run(app, debug=True, port=5001)