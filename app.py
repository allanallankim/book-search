import os
import json
import requests
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import xml.etree.ElementTree as ET

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key_here_nl_book_search')

# Ensure absolute path for SQLite database so data is reliably saved and persisted
basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, 'instance')
os.makedirs(instance_dir, exist_ok=True)
db_path = os.path.join(instance_dir, 'book_search.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Persistent Session & Remember Cookie Configuration (prevents losing login state on browser close)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_REFRESH_EACH_REQUEST'] = True

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요한 서비스입니다.'
login_manager.login_message_category = 'warning'

API_KEY = "3fa266309ffe82abc8018e9ed2f3b6c0bd64d01cd326204acfae5062445ed3d2"
API_URL = "https://www.nl.go.kr/NL/search/openApi/search.do"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    is_master = db.Column(db.Boolean, default=False)

class SavedSearch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    query_params = db.Column(db.Text, nullable=False) # Store JSON string

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

SEOJI_API_URL = "https://seoji.nl.go.kr/landingPage/SearchApi.do"
NL_API_URL = "https://www.nl.go.kr/NL/search/openApi/search.do"

@app.route('/api/search')
def api_search():
    try:
        page_num = int(request.args.get('pageNum', 1))
    except (ValueError, TypeError):
        page_num = 1

    try:
        page_size = int(request.args.get('pageSize', 12))
    except (ValueError, TypeError):
        page_size = 12

    category = request.args.get('category', '전체')
    title = request.args.get('title', '').strip()
    author = request.args.get('author', '').strip()
    publisher = request.args.get('publisher', '').strip()
    kwd = request.args.get('kwd', '').strip()
    isbn = request.args.get('isbn', '').strip()

    # Search term mapping
    search_title = title
    if not search_title and kwd:
        search_title = kwd
    elif search_title and kwd and kwd not in search_title:
        search_title = f"{search_title} {kwd}"

    # If no search term at all, return empty result gracefully
    if not search_title and not author and not publisher and not isbn:
        return jsonify({
            'total': 0,
            'pageNum': page_num,
            'pageSize': page_size,
            'result': [],
            'message': '검색어를 입력해 주세요.'
        })

    # 1. Primary: National Library Seoji (ISBN Bibliographic) API
    seoji_params = {
        'cert_key': API_KEY,
        'result_style': 'json',
        'page_no': page_num,
        'page_size': page_size,
    }
    if search_title:
        seoji_params['title'] = search_title
    if author:
        seoji_params['author'] = author
    if publisher:
        seoji_params['publisher'] = publisher
    if isbn:
        seoji_params['isbn'] = isbn

    if category == '전자책':
        seoji_params['ebook_yn'] = 'Y'
    elif category == '도서':
        seoji_params['ebook_yn'] = 'N'

    try:
        res = requests.get(SEOJI_API_URL, params=seoji_params, timeout=6)
        if res.status_code == 200:
            data = res.json()
            total = int(data.get('TOTAL_COUNT', 0))
            docs = data.get('docs', [])
            
            results = []
            for doc in docs:
                doc_title = doc.get('TITLE', '').strip()
                doc_author = doc.get('AUTHOR', '').strip()
                doc_pub = doc.get('PUBLISHER', '').strip()
                pub_date = doc.get('PUBLISH_PREDATE', '') or doc.get('REAL_PUBLISH_DATE', '')
                pub_year = pub_date[:4] if len(pub_date) >= 4 else ''
                doc_isbn = doc.get('EA_ISBN', '') or doc.get('SET_ISBN', '')
                doc_form = doc.get('FORM', '') or doc.get('FORM_DETAIL', '') or '도서'
                price = doc.get('PRE_PRICE', '') or doc.get('REAL_PRICE', '')
                summary = doc.get('BOOK_INTRODUCTION', '') or doc.get('BOOK_SUMMARY', '')
                cover_url = doc.get('TITLE_URL', '')
                
                # Detail link
                if doc_isbn:
                    detail_link = f"https://www.nl.go.kr/seoji/contents/S80100000000.do?schType=simple&schStr={doc_isbn}"
                else:
                    detail_link = f"https://www.nl.go.kr/NL/contents/search.do?srchTarget=total&kwd={requests.utils.quote(doc_title)}"
                
                results.append({
                    'title_info': doc_title or '제목 없음',
                    'author_info': doc_author or '저자 정보 없음',
                    'pub_info': doc_pub or '발행처 정보 없음',
                    'pub_year_info': pub_year,
                    'pub_date': pub_date,
                    'type_name': doc_form,
                    'call_no': doc.get('CONTROL_NO', '') or '-',
                    'isbn': doc_isbn,
                    'price': price,
                    'summary': summary,
                    'cover_url': cover_url,
                    'detail_link': detail_link,
                    'page': doc.get('PAGE', ''),
                    'series_title': doc.get('SERIES_TITLE', ''),
                    'subject': doc.get('SUBJECT', ''),
                    'publisher_url': doc.get('PUBLISHER_URL', '')
                })

            return jsonify({
                'total': total,
                'pageNum': page_num,
                'pageSize': page_size,
                'result': results,
                'source': 'seoji'
            })
    except Exception as seoji_err:
        app.logger.warning(f"Seoji API query failed or timed out: {seoji_err}")

    # 2. Fallback: NL Search Open API (with strict 3s timeout)
    try:
        nl_params = {
            'key': API_KEY,
            'apiType': 'json',
            'pageNum': page_num,
            'pageSize': page_size,
            'kwd': search_title or kwd or title,
            'srchTarget': 'total'
        }
        if category and category != '전체':
            nl_params['category'] = category

        nl_res = requests.get(NL_API_URL, params=nl_params, timeout=3)
        if nl_res.status_code == 200:
            try:
                nl_data = nl_res.json()
                items = nl_data.get('result', [])
                total = int(nl_data.get('total', len(items)))
                return jsonify({
                    'total': total,
                    'pageNum': page_num,
                    'pageSize': page_size,
                    'result': items,
                    'source': 'nl'
                })
            except Exception:
                root = ET.fromstring(nl_res.content)
                results = []
                for item in root.findall('.//item'):
                    res_item = {}
                    for child in item:
                        res_item[child.tag] = child.text
                    results.append(res_item)
                total_elem = root.find('.//total')
                total = int(total_elem.text) if total_elem is not None and total_elem.text else len(results)
                return jsonify({
                    'total': total,
                    'pageNum': page_num,
                    'pageSize': page_size,
                    'result': results,
                    'source': 'nl_xml'
                })
    except Exception as nl_err:
        app.logger.warning(f"NL Open API query failed: {nl_err}")

    return jsonify({
        'total': 0,
        'pageNum': page_num,
        'pageSize': page_size,
        'result': [],
        'error': '도서 검색 서비스를 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요.'
    }), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = True if request.form.get('remember') == 'on' or 'remember' not in request.form else True

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            session.permanent = True
            flash(f'환영합니다, {user.username}님! 도서 검색 화면으로 이동했습니다.')
            next_page = request.args.get('next')
            if next_page and not next_page.startswith('//') and not next_page.startswith('http'):
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다. 다시 확인해 주세요.')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('아이디와 비밀번호를 모두 입력해 주세요.')
            return render_template('register.html')

        user = User.query.filter_by(username=username).first()
        if user:
            flash('이미 등록되어 있는 아이디입니다. 다른 아이디를 입력해 주세요.')
        else:
            new_user = User(username=username, password_hash=generate_password_hash(password, method='pbkdf2:sha256'))
            db.session.add(new_user)
            db.session.commit()
            
            # Immediately log in the user, keep persistent session, and redirect to search screen!
            login_user(new_user, remember=True)
            session.permanent = True
            flash(f'회원가입이 완료되었습니다! {new_user.username}님으로 로그인되어 검색 화면으로 이동했습니다.')
            return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('정상적으로 로그아웃되었습니다.')
    return redirect(url_for('index'))

@app.route('/custom_search')
@login_required
def custom_search():
    saved_searches = SavedSearch.query.filter_by(user_id=current_user.id).all()
    return render_template('custom_search.html', saved_searches=saved_searches)

@app.route('/api/save_search', methods=['POST'])
@login_required
def save_search():
    data = request.json
    name = data.get('name')
    query_params = data.get('query_params')
    
    if not name or not query_params:
        return jsonify({'error': 'Missing data'}), 400
        
    saved = SavedSearch(user_id=current_user.id, name=name, query_params=json.dumps(query_params))
    db.session.add(saved)
    db.session.commit()
    return jsonify({'success': True, 'id': saved.id})

@app.route('/api/delete_search/<int:search_id>', methods=['DELETE'])
@login_required
def delete_search(search_id):
    saved = SavedSearch.query.get_or_404(search_id)
    if saved.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(saved)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_master:
        return "Access Denied", 403
    users = User.query.filter_by(is_master=False).all()
    return render_template('admin.html', users=users)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_master:
        return "Access Denied", 403
    user = User.query.get_or_404(user_id)
    # Also delete their saved searches
    SavedSearch.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} deleted.')
    return redirect(url_for('admin'))

def init_db():
    with app.app_context():
        db.create_all()
        # Create master account if not exists
        master = User.query.filter_by(username='allan').first()
        if not master:
            master = User(username='allan', password_hash=generate_password_hash('1234', method='pbkdf2:sha256'), is_master=True)
            db.session.add(master)
            db.session.commit()

# Ensure database tables are created when imported by Gunicorn
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
