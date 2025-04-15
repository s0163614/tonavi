from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import shutil
import win32com.client
import pythoncom
import json  # Add this line at the top with your other imports
from PIL import ImageGrab
import time
import logging
import openpyxl
from openpyxl.utils import get_column_letter
from functools import wraps
import uuid
import re
import requests
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import math





app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['EXCEL_FILE'] = 'Каталог.xlsx'
app.secret_key = 'your-secret-key-here'

# MySQL configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_PORT'] = 3306
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'tonavi'



DADATA_API_KEY = "33ce2ae14246ae3bc798fb5495d8b1a04675e2e6"
DADATA_API_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)





def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=app.config['MYSQL_HOST'],
            port=app.config['MYSQL_PORT'],
            user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'],
            database=app.config['MYSQL_DB']
        )
        return conn
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

users = {}


@app.template_filter('tojson')
def tojson_filter(obj):
    return json.dumps(obj, ensure_ascii=False)


def load_wb_commissions():
    categories = {}  # subjectName -> subjectID
    commissions = {}  # subjectName -> комиссия в %

    try:
        with open('commissions (2).txt', 'r', encoding='utf-8') as f:
            data = json.load(f)

            for item in data.get("report", []):
                name = item["subjectName"]
                categories[name] = item["subjectID"]
                commissions[name] = item.get("kgvpMarketplace", 0.0)
    except Exception as e:
        print(f"Ошибка загрузки комиссий: {str(e)}")

    return categories, commissions


WB_CATEGORIES, WB_COMMISSIONS = load_wb_commissions()


@app.route('/wb_cards')
def wb_cards():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    file_path = os.path.join(app.root_path, app.config['EXCEL_FILE'])
    if not os.path.exists(file_path):
        return render_template('error.html', message="Файл каталога не найден"), 404

    try:
        products = parse_excel(file_path)
        return render_template('wb_cards.html',
                               products=products,
                               wb_categories=WB_CATEGORIES,
                               user={'id': session['user_id']})
    except Exception as e:
        logger.error(f"Ошибка загрузки каталога: {str(e)}")
        return render_template('error.html', message="Ошибка загрузки каталога"), 500


@app.route('/create_wb_cards', methods=['POST'])
def create_wb_cards():
    try:
        selected_products = request.json.get('products', [])
        api_key = request.json.get('api_key', '')

        if not api_key:
            return jsonify({'success': False, 'message': 'API ключ не указан'}), 400

        cards_to_create = []

        for product in selected_products:
            subject_id = WB_CATEGORIES.get(product.get('category', ''), 0)
            commission_percent = WB_COMMISSIONS.get(product.get('category', ''), 16.5) / 100

            if not subject_id:
                continue

            # Константы для расчета цены
            AE2 = 60  # затраты за ФФ
            AC2 = 0.9  # процент выкупа (90%)
            J2 = 0.07  # УСН
            K2 = 0.02  # лимит карточек
            AF2 = 0.015  # эквайринг
            AG2 = 0.015  # риски
            L2 = 0.20  # маржа

            variants = []
            for variant in product['variants']:
                try:
                    # Получаем размеры или используем значения по умолчанию
                    length = int(variant.get('Длина (см)', 0)) or 10
                    width = int(variant.get('Ширина (см)', 0)) or 10
                    height = int(variant.get('Высота (см)', 0)) or 10
                    base_price = float(variant.get('Цена', 0))

                    # Расчет цены
                    volume = (length * width * height) / 1000
                    ab2 = 43.75 + 10.625 * (math.ceil(volume) - 1)
                    ad2 = (ab2 + (50 * (1 - AC2))) / AC2
                    final_price = (base_price + AE2 + ad2) / (1 - J2 - K2 - AF2 - AG2 - commission_percent - L2)
                    final_price = round(final_price)

                    variants.append({
                        "vendorCode": str(variant.get('Артикул', '')),
                        "title": product.get('name', ''),
                        "dimensions": {
                            "length": length,
                            "width": width,
                            "height": height,
                            "weightBrutto": 0.3  # стандартный вес
                        },
                        "sizes": [{
                            "price": final_price
                        }]
                    })
                except Exception as e:
                    print(f"Ошибка при расчёте цены: {str(e)}")
                    continue

            if variants:  # Добавляем только если есть варианты
                cards_to_create.append({
                    "subjectID": subject_id,
                    "variants": variants
                })

        # Логирование для отладки
        print("Отправляемые данные:", json.dumps(cards_to_create, indent=4, ensure_ascii=False))

        headers = {
            'Authorization': api_key,
            'Content-Type': 'application/json'
        }

        response = requests.post(
            'https://content-api.wildberries.ru/content/v2/cards/upload',
            headers=headers,
            json=cards_to_create
        )

        if response.status_code == 200:
            return jsonify({
                'success': True,
                'message': 'Карточки отправлены на создание',
                'response': response.json()
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Ошибка при создании карточек',
                'status_code': response.status_code,
                'response': response.text
            }), 400

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Ошибка: {str(e)}'
        }), 500


class User:
    def __init__(self, user_id, username, password, post=False, company_info=None, saved_companies=None, user_info=None):
        self.id = user_id
        self.username = username
        self.password = password
        self.post = post  # True - поставщик, False - селлер
        self.company_info = company_info or {}
        self.saved_companies = saved_companies or []
        self.user_info = user_info or ""

    def add_saved_company(self, company_data):
        self.saved_companies.append(company_data)
        self._update_db()

    def remove_saved_company(self, inn):
        self.saved_companies = [c for c in self.saved_companies if c.get('inn') != inn]
        self._update_db()

    def update_user_info(self, info):
        self.user_info = info
        self._update_db()

    def _update_db(self):
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                query = """
                UPDATE users 
                SET company_info = %s, saved_companies = %s, user_info = %s
                WHERE id = %s
                """
                cursor.execute(query, (
                    json.dumps(self.company_info) if self.company_info else None,
                    json.dumps(self.saved_companies) if self.saved_companies else None,
                    self.user_info,
                    self.id
                ))
                conn.commit()
            except Error as e:
                print(f"Error updating user in DB: {e}")
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

# Обновленные маршруты регистрации и входа
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        post = request.form.get('post', '0') == '1'  # Получаем значение роли

        if not username or not password:
            return render_template('register.html', error='Заполните все поля')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    return render_template('register.html', error='Пользователь уже существует')

                user_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO users (id, username, password, post) VALUES (%s, %s, %s, %s)",
                    (user_id, username, password, post)
                )
                conn.commit()

                user = User(user_id, username, password, post)
                session['user_id'] = user.id
                session['user_post'] = user.post  # Сохраняем роль в сессии
                return redirect(url_for('profile'))

            except Error as e:
                print(f"Error during registration: {e}")
                return render_template('register.html', error='Ошибка при регистрации')
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()
        else:
            return render_template('register.html', error='Ошибка подключения к базе данных')

    return render_template('register.html')


# Добавим новые маршруты



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, username, password, post, company_info, saved_companies FROM users WHERE username = %s",
                    (username,)
                )
                user_data = cursor.fetchone()

                if not user_data or user_data['password'] != password:
                    return render_template('login.html', error='Неверные учетные данные')

                user = User(
                    user_data['id'],
                    user_data['username'],
                    user_data['password'],
                    user_data['post'],
                    user_data.get('company_info'),
                    user_data.get('saved_companies')
                )
                session['user_id'] = user.id
                session['user_post'] = user.post  # Сохраняем роль в сессии
                return redirect(url_for('index'))

            except Error as e:
                print(f"Error during login: {e}")
                return render_template('login.html', error='Ошибка при входе')
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()
        else:
            return render_template('login.html', error='Ошибка подключения к базе данных')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, username, post, company_info, saved_companies, user_info FROM users WHERE id = %s",
                (session['user_id'],)
            )
            user_data = cursor.fetchone()

            if not user_data:
                session.pop('user_id', None)
                return redirect(url_for('login'))
            
            user_post = bool(user_data['post'])
            user = User(
                user_data['id'],
                user_data['username'],
                '',  # Пароль не нужен для отображения профиля
                user_post,
                user_data['company_info'] if user_data['company_info'] else {},
                user_data['saved_companies'] if user_data['saved_companies'] else [],
                user_data['user_info'] if user_data['user_info'] else ""
            )
            return render_template('profile.html', user=user)

        except Error as e:
            print(f"Error fetching user profile: {e}")
            session.pop('user_id', None)
            return redirect(url_for('login'))
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()
    else:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
@app.route('/get_company_info', methods=['POST'])
def get_company_info():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Необходима авторизация"}), 401

    inn_data = request.get_json()
    if not inn_data:
        return jsonify({"success": False, "message": "Неверный формат запроса"}), 400

    inn = inn_data.get('inn', '').strip()

    if not inn or not re.match(r'^\d{10,12}$', inn):
        return jsonify({"success": False, "message": "Неверный ИНН"}), 400

    try:
        headers = {
            "Authorization": f"Token {DADATA_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {"query": inn, "count": 20}

        response = requests.post(DADATA_API_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        suggestions = data.get("suggestions", [])
        if not suggestions:
            return jsonify({"success": False, "message": "Компания не найдена"})

        companies = []
        for item in suggestions:
            company = {
                "name": item.get("value", ""),
                "inn": item["data"].get("inn", ""),
                "ogrn": item["data"].get("ogrn", ""),
                "kpp": item["data"].get("kpp", ""),
                "status": item["data"].get("state", {}).get("status", ""),
                "registration_date": item["data"].get("state", {}).get("registration_date", ""),
                "address": item["data"].get("address", {}).get("value", ""),
                "director": item["data"].get("management", {}).get("name", ""),
                "director_position": item["data"].get("management", {}).get("post", ""),
                "okved": item["data"].get("okved", ""),
                "source": "Dadata"
            }
            companies.append(company)

        return jsonify({
            "success": True,
            "multiple": len(companies) > 1,
            "data": companies if len(companies) > 1 else companies[0]
        })
    except Exception as e:
        print(f"Ошибка при запросе к Dadata: {str(e)}")
        return jsonify({"success": False, "message": "Ошибка сервера при запросе к Dadata"})

@app.route('/save_company', methods=['POST'])
def save_company():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Необходима авторизация"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Ошибка подключения к базе данных"}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        
        # Get current user
        cursor.execute(
            "SELECT saved_companies FROM users WHERE id = %s",
            (session['user_id'],)
        )
        user_data = cursor.fetchone()
        
        if not user_data:
            return jsonify({"success": False, "message": "Пользователь не найден"}), 404

        company_data = request.get_json()
        if not company_data:
            return jsonify({"success": False, "message": "Неверные данные"}), 400

        # Update saved companies list
        saved_companies = user_data['saved_companies'] or []
        if isinstance(saved_companies, str):
            saved_companies = json.loads(saved_companies)
        
        # Check if company already exists
        if any(c.get('inn') == company_data.get('inn') for c in saved_companies):
            return jsonify({"success": False, "message": "Компания уже сохранена"}), 400

        saved_companies.append(company_data)
        
        # Update database record
        cursor.execute(
            "UPDATE users SET saved_companies = %s WHERE id = %s",
            (json.dumps(saved_companies, ensure_ascii=False), session['user_id'])
        )
        conn.commit()
        
        return jsonify({"success": True, "message": "Компания сохранена"})

    except Error as e:
        print(f"Error saving company: {e}")
        return jsonify({"success": False, "message": "Ошибка сервера"}), 500
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/remove_company/<inn>', methods=['POST'])
def remove_company(inn):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Необходима авторизация"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Ошибка подключения к базе данных"}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        
        # Получаем текущего пользователя
        cursor.execute(
            "SELECT saved_companies FROM users WHERE id = %s",
            (session['user_id'],)
        )
        user_data = cursor.fetchone()
        
        if not user_data:
            return jsonify({"success": False, "message": "Пользователь не найден"}), 404

        saved_companies = user_data['saved_companies'] or []
        if isinstance(saved_companies, str):
            saved_companies = json.loads(saved_companies)
        
        # Удаляем компанию с указанным ИНН
        new_companies = [c for c in saved_companies if c.get('inn') != inn]
        
        # Обновляем запись в базе данных
        cursor.execute(
            "UPDATE users SET saved_companies = %s WHERE id = %s",
            (json.dumps(new_companies), session['user_id'])
        )
        conn.commit()
        
        return jsonify({"success": True, "message": "Компания удалена"})

    except Error as e:
        print(f"Error removing company: {e}")
        return jsonify({"success": False, "message": "Ошибка сервера"}), 500
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()



def cart_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'cart' not in session:
            session['cart'] = []  # Инициализируем корзину, если ее нет
        return f(*args, **kwargs)

    return decorated_function





@app.route('/add_to_cart', methods=['POST'])
@cart_required
def add_to_cart():
    data = request.get_json()
    row = data.get('row')
    
    file_path = os.path.join(app.root_path, app.config['EXCEL_FILE'])
    excel_data = get_excel_data(file_path)
    product = next((item for item in excel_data if item['row'] == row), None)
    
    if not product:
        return jsonify({'success': False, 'message': 'Товар не найден'})
    
    try:
        price = float(product['Цена'])
        if price <= 0:
            raise ValueError("Цена должна быть положительным числом")
    except (ValueError, TypeError) as e:
        logger.error(f"Ошибка преобразования цены: {str(e)}")
        return jsonify({'success': False, 'message': 'Неверный формат цены'})
    
    if not any(item['row'] == row for item in session['cart']):
        # Добавляем информацию о поставщике, если есть
        supplier_id = session.get('current_supplier_id')
        cart_item = {
            'row': product['row'],
            'Название': product['Название'],
            'Артикул': product['Артикул'],
            'Цена': price,
            'quantity': 1
        }
        if supplier_id:
            cart_item['supplier_id'] = supplier_id
            print(f"Added item from supplier: {supplier_id}") 
        
        session['cart'].append(cart_item)
        session.modified = True
        return jsonify({'success': True, 'cart_count': len(session['cart'])})
    
    return jsonify({'success': False, 'message': 'Товар уже в корзине'})

def get_supplier_name(supplier_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT username FROM users WHERE id = %s", (supplier_id,))
            supplier = cursor.fetchone()
            return supplier['username'] if supplier else "Неизвестный поставщик"
        except Error as e:
            print(f"Error fetching supplier: {e}")
            return "Ошибка загрузки"
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()
    return "Нет подключения"

@app.context_processor
def utility_processor():
    return dict(get_supplier_name=get_supplier_name)

@app.route('/confirm_order', methods=['POST'])
def confirm_order():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Необходима авторизация"}), 401
    
    # Only sellers (post=0) can confirm orders
    if session.get('user_post', True):
        return jsonify({"success": False, "message": "Только продавцы могут оформлять заказы"}), 403
    
    if 'cart' not in session or not session['cart']:
        return jsonify({"success": False, "message": "Корзина пуста"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Ошибка подключения к БД"}), 500
    
    try:
        # Verify all items have the same supplier
        supplier_ids = {item.get('supplier_id') for item in session['cart']}
        if len(supplier_ids) != 1:
            return jsonify({"success": False, "message": "Все товары должны быть от одного поставщика"}), 400
        
        supplier_id = supplier_ids.pop()
        
        # Verify supplier exists
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE id = %s AND post = 1", (supplier_id,))
        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Поставщик не найден"}), 404
        
        # Prepare order items and calculate total
        items = []
        total = 0.0
        for item in session['cart']:
            item_total = float(item['Цена']) * item['quantity']
            items.append({
                'name': item['Название'],
                'article': item['Артикул'],
                'price': float(item['Цена']),
                'quantity': item['quantity'],
                'row': item['row']
            })
            total += item_total
        
        # Convert to JSON string with ensure_ascii=False
        items_json = json.dumps(items, ensure_ascii=False)
        
        # Debug print
        print(f"Items JSON to be stored: {items_json}")
        print(f"Calculated total: {total}")
        
        # Create order
        order_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO orders (id, seller_id, supplier_id, items, total, status) VALUES (%s, %s, %s, %s, %s, 'pending')",
            (order_id, session['user_id'], supplier_id, items_json, total)
        )
        conn.commit()
        
        # Verify order was created
        cursor.execute("SELECT id FROM orders WHERE id = %s", (order_id,))
        if not cursor.fetchone():
            raise Exception("Order not created")
        
        # Clear cart
        session['cart'] = []
        session.modified = True
        
        return jsonify({
            "success": True, 
            "message": "Заказ успешно оформлен",
            "order_id": order_id
        })
    
    except Exception as e:
        conn.rollback()
        print(f"Error creating order: {e}")
        return jsonify({"success": False, "message": f"Ошибка при оформлении заказа: {str(e)}"}), 500
    finally:
        if conn.is_connected():
            conn.close()

@app.route('/confirm_payment/<order_id>', methods=['POST'])
def confirm_payment(order_id):
    if 'user_id' not in session or not session.get('user_post', False):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    if not conn:
        return "Ошибка подключения к базе данных", 500
    
    try:
        cursor = conn.cursor()
        # Verify the order belongs to this supplier
        cursor.execute(
            "UPDATE orders SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP WHERE id = %s AND supplier_id = %s AND status = 'pending'",
            (order_id, session['user_id'])
        )
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({"success": False, "message": "Заказ не найден или уже обработан"}), 400
        
        return jsonify({"success": True, "message": "Платеж подтвержден"})
    
    except Error as e:
        print(f"Error confirming payment: {e}")
        return jsonify({"success": False, "message": "Ошибка сервера"}), 500
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/supplier/orders')
def supplier_orders():
    if 'user_id' not in session or session.get('user_post', 0) != 1:  # Только для поставщиков (post=1)
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    if not conn:
        return render_template('error.html', message="Ошибка подключения к БД"), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                o.id,
                o.status,
                o.seller_id,
                o.supplier_id,
                o.total,
                o.items AS order_items,
                o.created_at,
                DATE_FORMAT(o.created_at, '%%d.%%m.%%Y %%H:%%i') as created_at_formatted,
                o.confirmed_at,
                u.username as seller_name,
                DATE_FORMAT(o.confirmed_at, '%%d.%%m.%%Y %%H:%%i') as confirmed_at_formatted
            FROM orders o
            JOIN users u ON o.seller_id = u.id
            WHERE o.supplier_id = %s
            ORDER BY o.created_at DESC
        """, (session['user_id'],))
        
        orders = []
        for row in cursor.fetchall():
            order = dict(row)
            items_data = order.pop('order_items', '[]')
            try:
                order['order_items'] = json.loads(items_data) if isinstance(items_data, str) else items_data
            except json.JSONDecodeError:
                order['order_items'] = []
            orders.append(order)

        return render_template('supplier_orders.html', orders=orders)
    
    except Error as e:
        print(f"Error fetching orders: {e}")
        return render_template('error.html', message="Ошибка загрузки заказов"), 500
    finally:
        if conn.is_connected():
            conn.close()

@app.route('/checkout', methods=['GET'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session.get('user_post', True):  # Only sellers (post=0) can checkout
        return redirect(url_for('index'))
    
    if 'cart' not in session or not session['cart']:
        return redirect(url_for('view_cart'))
    
    conn = get_db_connection()
    if not conn:
        return "Ошибка подключения к базе данных", 500
    
    try:
        # Get seller info (current user)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, username, user_info FROM users WHERE id = %s",
            (session['user_id'],)
        )
        seller = cursor.fetchone()
        
        # Get supplier info from first item in cart
        supplier_id = session['cart'][0].get('supplier_id')
        if not supplier_id:
            return "Не удалось определить поставщика", 400
            
        cursor.execute(
            "SELECT id, username, user_info FROM users WHERE id = %s",
            (supplier_id,)
        )
        supplier = cursor.fetchone()
        
        if not seller or not supplier:
            return "Не удалось получить информацию о пользователях", 404
        
        return render_template('checkout.html', 
                             seller=seller,
                             supplier=supplier,
                             cart_items=session['cart'],
                             total=sum(item['Цена'] * item['quantity'] for item in session['cart']))
        
    except Error as e:
        print(f"Error during checkout: {e}")
        return "Ошибка сервера", 500
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/cart')
@cart_required
def view_cart():
    cart_items = session.get('cart', [])
    # Убедимся, что все цены - числа
    for item in cart_items:
        if isinstance(item['Цена'], str):
            try:
                item['Цена'] = float(item['Цена'])
            except (ValueError, TypeError):
                item['Цена'] = 0.0
    
    total = sum(item['Цена'] * item['quantity'] for item in cart_items)
    
    # Получаем информацию о пользователе
    user = None
    if 'user_id' in session:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT id, username, post FROM users WHERE id = %s", (session['user_id'],))
                user = cursor.fetchone()
            except Exception as e:
                logger.error(f"Ошибка получения данных пользователя: {str(e)}")
            finally:
                if conn and conn.is_connected():
                    cursor.close()
                    conn.close()
    
    return render_template('cart.html', 
                         cart_items=cart_items, 
                         total=f"{total:.2f} ₽",
                         user=user)  # Передаем данные пользователя в шаблон

@app.route('/remove_from_cart/<int:row>', methods=['POST'])
@cart_required
def remove_from_cart(row):
    session['cart'] = [item for item in session['cart'] if item['row'] != row]
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/supplier_products/<int:supplier_id>')
def supplier_products(supplier_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Получаем данные текущего пользователя
    conn = get_db_connection()
    if not conn:
        return render_template('error.html', message="Ошибка подключения к БД"), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Проверяем, существует ли поставщик
        cursor.execute("SELECT id, username, post FROM users WHERE id = %s AND post = 1", (supplier_id,))
        supplier = cursor.fetchone()
        
        if not supplier:
            return render_template('error.html', message="Поставщик не найден"), 404
        
        # Получаем данные текущего пользователя
        cursor.execute("SELECT id, username, post FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
        
        # Сохраняем ID поставщика в сессии
        session['current_supplier_id'] = supplier_id
        
        # Загружаем товары поставщика
        file_path = os.path.join(app.root_path, app.config['EXCEL_FILE'])
        if not os.path.exists(file_path):
            return render_template('error.html', message="Файл каталога не найден"), 404
        
        try:
            products = parse_excel(file_path)
            return render_template('index.html', 
                                products=products,
                                user=user,
                                is_seller=not user['post'],  # True если продавец
                                supplier_view=True,
                                supplier=supplier)
        except Exception as e:
            logger.error(f"Ошибка загрузки каталога: {str(e)}")
            return render_template('error.html', message="Ошибка загрузки каталога"), 500
            
    except Exception as e:
        logger.error(f"Ошибка в supplier_products: {str(e)}")
        return render_template('error.html', message="Внутренняя ошибка сервера"), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/seller/orders')
def seller_orders():
    if 'user_id' not in session or session.get('user_post', 0) != 0:  # Только для продавцов (post=0)
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    if not conn:
        return render_template('error.html', message="Ошибка подключения к БД"), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                o.id,
                o.status,
                o.seller_id,
                o.supplier_id,
                o.total,
                o.items AS order_items,
                o.created_at,
                DATE_FORMAT(o.created_at, '%%d.%%m.%%Y %%H:%%i') as created_at_formatted,
                o.confirmed_at,
                u.username as supplier_name,
                DATE_FORMAT(o.confirmed_at, '%%d.%%m.%%Y %%H:%%i') as confirmed_at_formatted
            FROM orders o
            JOIN users u ON o.supplier_id = u.id
            WHERE o.seller_id = %s
            ORDER BY o.created_at DESC
        """, (session['user_id'],))
        
        orders = []
        for row in cursor.fetchall():
            order = dict(row)
            items_data = order.pop('order_items', '[]')
            try:
                order['order_items'] = json.loads(items_data) if isinstance(items_data, str) else items_data
            except json.JSONDecodeError:
                order['order_items'] = []
            orders.append(order)

        return render_template('seller_orders.html', orders=orders)
    
    except Error as e:
        print(f"Error fetching orders: {e}")
        return render_template('error.html', message="Ошибка загрузки заказов"), 500
    finally:
        if conn.is_connected():
            conn.close()

@app.route('/update_cart_item/<int:row>', methods=['POST'])
@cart_required
def update_cart_item(row):
    quantity = int(request.form.get('quantity', 1))
    
    for item in session['cart']:
        if item['row'] == row:
            item['quantity'] = quantity
            break
    
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/update_user_info', methods=['POST'])
def update_user_info():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Необходима авторизация"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Ошибка подключения к базе данных"}), 500

    try:
        info = request.form.get('user_info', '')
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET user_info = %s WHERE id = %s",
            (info, session['user_id'])
        )
        conn.commit()
        return jsonify({"success": True, "message": "Информация обновлена"})
    except Error as e:
        print(f"Error updating user info: {e}")
        return jsonify({"success": False, "message": "Ошибка сервера"}), 500
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/clear_cart', methods=['POST'])
@cart_required
def clear_cart():
    session['cart'] = []
    session.modified = True
    return redirect(url_for('view_cart'))


def safe_excel_operation(file_path):
    """Безопасная обертка для работы с Excel"""
    pythoncom.CoInitialize()
    excel = None
    wb = None
    
    try:
        excel = win32com.client.DispatchEx("Excel.Application")  # Используем DispatchEx
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.ScreenUpdating = False
        
        # Полный путь к файлу
        abs_path = os.path.abspath(file_path)
        logger.info(f"Открываем файл: {abs_path}")
        
        wb = excel.Workbooks.Open(abs_path)
        sheet = wb.Sheets(1)
        
        yield sheet
        
    except Exception as e:
        logger.error(f"Ошибка в Excel: {e}")
        raise
    finally:
        try:
            if wb:
                wb.Close(False)
            if excel:
                excel.Quit()
        except Exception as e:
            logger.error(f"Ошибка при закрытии Excel: {e}")
        finally:
            pythoncom.CoUninitialize()

def extract_images(file_path):
    """Извлекаем изображения из Excel"""
    images = {}
    
    try:
        for sheet in safe_excel_operation(file_path):
            for i, shape in enumerate(sheet.Shapes):
                if hasattr(shape, 'Type') and shape.Type == 13:  # msoPicture
                    try:
                        row = int(shape.TopLeftCell.Row)
                        filename = f"img_row_{row}.png"
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        
                        # Копируем изображение с задержкой
                        shape.Copy()
                        time.sleep(0.01)  # Даем время для копирования
                        
                        image = ImageGrab.grabclipboard()
                        if image:
                            image.save(filepath, "PNG")
                            images[row] = filename
                            logger.info(f"Сохранено изображение для строки {row}")
                        else:
                            logger.warning(f"Не удалось получить изображение для строки {row}")
                    except Exception as e:
                        logger.error(f"Ошибка при обработке изображения {i}: {e}")
                        continue
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    
    return images

def clear_images_folder():
    """Удаляет все изображения из папки загрузок."""
    folder_path = app.config['UPLOAD_FOLDER']
    if os.path.exists(folder_path):
        # Удаляем все файлы в папке
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f'Ошибка при удалении файла {file_path}: {e}')
    else:
        # Если папка не существует, создаем её
        os.makedirs(folder_path)


def parse_excel(app):
    file_path = os.path.join(os.getcwd(), app.config['EXCEL_FILE'])
    clear_images_folder()
    images = extract_images(file_path)
    excel_data = get_excel_data(file_path)

    products = []
    current_group = None
    group_data = []
    current_category = None

    try:
        wb = openpyxl.load_workbook(file_path)
        sheet = wb.active

        for row in range(4, sheet.max_row + 1):
            category = sheet[f'I{row}'].value
            if category and str(category).strip():
                current_category = category

            article = sheet[f'D{row}'].value
            if not article:
                continue

            if article != current_group:
                if group_data:
                    img = next((images[r] for r in sorted(images.keys(), reverse=True)
                                if r <= group_data[0]['row']), None)

                    products.append({
                        'article': current_group,
                        'name': group_data[0]['Название'],
                        'image': img,
                        'category': current_category,
                        'variants': group_data
                    })

                current_group = article
                group_data = []

            if sheet[f'C{row}'].value:
                group_data.append({
                    'row': row,
                    'Название': sheet[f'C{row}'].value,
                    'Артикул': article,
                    'Длина (см)': sheet[f'E{row}'].value,
                    'Ширина (см)': sheet[f'F{row}'].value,
                    'Высота (см)': sheet[f'G{row}'].value,
                    'Цена': sheet[f'H{row}'].value,
                })

        if group_data:
            img = next((images[r] for r in sorted(images.keys(), reverse=True)
                        if r <= group_data[0]['row']), None)

            products.append({
                'article': current_group,
                'name': group_data[0]['Название'],
                'image': img,
                'category': current_category,
                'variants': group_data
            })

        wb.close()
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")

    return products

def get_excel_data(file_path):
    """Получаем данные из Excel файла"""
    wb = openpyxl.load_workbook(file_path)
    sheet = wb.active
    data = []
    
    for row in range(4, sheet.max_row + 1):
        try:
            price = sheet[f'H{row}'].value
            # Преобразуем цену в число, если возможно
            try:
                price = float(price) if price is not None else 0.0
            except (ValueError, TypeError):
                price = 0.0
                logger.warning(f"Некорректная цена в строке {row}, установлено 0")
            
            data.append({
                'row': row,
                'Название': sheet[f'C{row}'].value,
                'Артикул': sheet[f'D{row}'].value,
                'Длина (см)': sheet[f'E{row}'].value,
                'Ширина (см)': sheet[f'F{row}'].value,
                'Высота (см)': sheet[f'G{row}'].value,
                'Цена': price,  # Уже число
            })
        except Exception as e:
            logger.error(f"Ошибка в строке {row}: {str(e)}")
            continue
    
    wb.close()
    return data

def update_excel_row(file_path, row_data):
    """Обновляем строку в Excel"""
    try:
        # Проверяем доступность файла для записи
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл {file_path} не найден")
            
        if not os.access(file_path, os.W_OK):
            raise PermissionError(f"Нет прав на запись в файл {file_path}")

        # Создаем резервную копию
        backup_path = file_path + '.bak'
        shutil.copy2(file_path, backup_path)
        
        wb = openpyxl.load_workbook(file_path)
        sheet = wb.active
        row = row_data['row']
        
        sheet[f'C{row}'] = row_data['Название']
        sheet[f'D{row}'] = row_data['Артикул']
        sheet[f'E{row}'] = row_data['Длина (см)']
        sheet[f'F{row}'] = row_data['Ширина (см)']
        sheet[f'G{row}'] = row_data['Высота (см)']
        sheet[f'H{row}'] = row_data['Цена']
        
        # Сохраняем с временным именем, затем переименовываем
        temp_path = file_path + '.tmp'
        wb.save(temp_path)
        wb.close()
        
        # Атомарная замена файла
        os.replace(temp_path, file_path)
        
    except Exception as e:
        # Восстанавливаем из резервной копии при ошибке
        if os.path.exists(backup_path):
            os.replace(backup_path, file_path)
        raise
    finally:
        # Удаляем временные файлы
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except:
                pass
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def delete_excel_row(file_path, row_num):
    """Удаляем строку из Excel"""
    wb = openpyxl.load_workbook(file_path)
    sheet = wb.active
    sheet.delete_rows(row_num)
    wb.save(file_path)
    wb.close()

def parse_excel(file_path):
    products = []
    current_group = None
    group_data = []
    current_category = None

    clear_images_folder()
    images = extract_images(file_path)
    excel_data = get_excel_data(file_path)

    try:
        wb = openpyxl.load_workbook(file_path)
        sheet = wb.active

        for row in range(4, sheet.max_row + 1):
            category = sheet[f'I{row}'].value
            if category and str(category).strip():
                current_category = category

            article = sheet[f'D{row}'].value
            if not article:
                continue

            if article != current_group:
                if group_data:
                    img = next((images[r] for r in sorted(images.keys(), reverse=True)
                               if r <= group_data[0]['row']), None)

                    products.append({
                        'article': current_group,
                        'name': group_data[0]['Название'],
                        'category': current_category,
                        'image': img,
                        'variants': group_data
                    })
                current_group = article
                group_data = []

            if sheet[f'C{row}'].value:
                group_data.append({
                    'row': row,
                    'Название': sheet[f'C{row}'].value,
                    'Артикул': article,
                    'Длина (см)': sheet[f'E{row}'].value,
                    'Ширина (см)': sheet[f'F{row}'].value,
                    'Высота (см)': sheet[f'G{row}'].value,
                    'Цена': sheet[f'H{row}'].value,
                })

        if group_data:
            img = next((images[r] for r in sorted(images.keys(), reverse=True)
                       if r <= group_data[0]['row']), None)

            products.append({
                'article': current_group,
                'name': group_data[0]['Название'],
                'category': current_category,
                'image': img,
                'variants': group_data
            })

        wb.close()
    except Exception as e:
        print(f"Ошибка при парсинге Excel: {str(e)}")

    return products


@app.route('/edit/<int:row>', methods=['GET', 'POST'])
def edit_product(row):
    file_path = os.path.join(app.root_path, app.config['EXCEL_FILE'])
    
    if request.method == 'POST':
        try:
            updated_data = {
                'row': row,
                'Название': request.form['name'],
                'Артикул': request.form['article'],
                'Длина (см)': request.form['length'],
                'Ширина (см)': request.form['width'],
                'Высота (см)': request.form['height'],
                'Цена': request.form['price']
            }
            update_excel_row(file_path, updated_data)
            return redirect(url_for('index'))
        except Exception as e:
            app.logger.error(f"Ошибка при обновлении: {str(e)}")
            return render_template('edit.html', 
                                product=request.form,
                                error=f"Ошибка сохранения: {str(e)}")
    
    try:
        excel_data = get_excel_data(file_path)
        product_to_edit = next((item for item in excel_data if item['row'] == row), None)
        
        if not product_to_edit:
            return "Товар не найден", 404
        
        return render_template('edit.html', product=product_to_edit)
    except Exception as e:
        app.logger.error(f"Ошибка при загрузке: {str(e)}")
        return f"Ошибка: {str(e)}", 500

@app.route('/delete/<int:row>', methods=['POST'])
def delete_product(row):
    file_path = os.path.join(app.root_path, app.config['EXCEL_FILE'])
    delete_excel_row(file_path, row)
    return redirect(url_for('index'))

@app.route('/suppliers')
def suppliers_list():
    if 'user_id' not in session or session.get('user_post', True):
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        return "Ошибка подключения к базе данных", 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, username, company_info FROM users WHERE post = 1")
        suppliers = cursor.fetchall()
        return render_template('suppliers.html', suppliers=suppliers)
    except Error as e:
        print(f"Error fetching suppliers: {e}")
        return "Ошибка сервера", 500
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', message="Страница не найдена"), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html', message="Внутренняя ошибка сервера"), 500

@app.route('/')
def index():
    # Проверка авторизации
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Получаем данные пользователя
    conn = get_db_connection()
    if not conn:
        return render_template('error.html', message="Ошибка подключения к БД"), 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, username, post FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
        
        # Для поставщиков показываем каталог
        if user['post']:
            file_path = os.path.join(app.root_path, app.config['EXCEL_FILE'])
            if not os.path.exists(file_path):
                return render_template('error.html', message="Файл каталога не найден"), 404
            
            try:
                products = parse_excel(file_path)
                return render_template('index.html', 
                                    products=products,
                                    user=user,
                                    is_seller=False,
                                    
                                    wb_categories=WB_CATEGORIES,
                                    supplier_view=False)
            except Exception as e:
                logger.error(f"Ошибка загрузки каталога: {str(e)}")
                return render_template('error.html', message="Ошибка загрузки каталога"), 500
        
        # Для продавцов перенаправляем на список поставщиков
        return redirect(url_for('suppliers_list'))
        
    except Exception as e:
        logger.error(f"Ошибка в index: {str(e)}")
        return render_template('error.html', message="Внутренняя ошибка сервера"), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    app.run(debug=True)