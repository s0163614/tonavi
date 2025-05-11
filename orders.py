from flask import Blueprint, render_template, request, redirect, flash
import requests
import mysql.connector
from mysql.connector import Error
from flask import jsonify
import os
import base64
from datetime import datetime
from flask import send_from_directory

orders_bp = Blueprint('orders', __name__)
# Добавим константы
STICKERS_FOLDER = os.path.join('static', 'stickers')
os.makedirs(STICKERS_FOLDER, exist_ok=True)


def get_db_connection():
    try:
        return mysql.connector.connect(
            host='localhost',
            port=3306,
            user='tonavi_root',
            password='Ghjdjrfwbz2020',
            database='tonavi_root'
        )
    except Error as e:
        print(f"Ошибка подключения к MySQL: {e}")
        return None

def get_sellers():
    """Получаем всех продавцов (post=0) из БД"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, username, api_key FROM users WHERE post = 0")
        return cursor.fetchall()
    except Error as e:
        print(f"Ошибка при получении продавцов: {e}")
        return []
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

def get_seller_api_key(seller_id):
    """Получаем API-ключ конкретного продавца"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT api_key FROM users WHERE id = %s", (seller_id,))
        result = cursor.fetchone()
        return result['api_key'] if result else None
    except Error as e:
        print(f"Ошибка при получении API-ключа: {e}")
        return None
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

def get_orders(api_key):
    """Получаем все заказы через API с использованием API-ключа продавца"""
    if not api_key:
        return []
        
    url = "https://marketplace-api.wildberries.ru/api/v3/orders/new"
    headers = {"Authorization": api_key}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("orders", [])
        print(f"Ошибка API: {response.status_code} - {response.text}")
        return []
    except Exception as e:
        print(f"Ошибка подключения: {str(e)}")
        return []

@orders_bp.route("/zakazi", methods=["GET"])
def show_orders():
    try:
        seller_id = request.args.get('seller_id')
        tab = request.args.get('tab', 'orders')  # Новый параметр для вкладок
        sellers = get_sellers()
        orders = []
        supplies = []
        current_seller = None

        if seller_id:
            api_key = get_seller_api_key(seller_id)
            if api_key:
                current_seller = next((s for s in sellers if str(s['id']) == seller_id), None)
                if tab == 'orders':
                    orders = get_orders(api_key)
                elif tab == 'supplies':
                    supplies = get_supplies(api_key)
            else:
                flash("API-ключ не найден для выбранного продавца")

        return render_template(
            "zakazi.html",
            orders=orders,
            supplies=supplies,
            sellers=sellers,
            current_seller=current_seller,
            current_tab=tab  # Передаем текущую вкладку в шаблон
        )
    except Exception as e:
        print(f"Ошибка: {str(e)}")
        flash("Произошла ошибка")
        return redirect("/")



def get_supplies(api_key):
    """Получаем все поставки через API"""
    if not api_key:
        return []
    
    url = "https://marketplace-api.wildberries.ru/api/v3/supplies"
    headers = {"Authorization": api_key}
    supplies = []
    next_token = 0

    while True:
        params = {
            "limit": 1000,
            "next": next_token
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                supplies.extend(data.get("supplies", []))
                next_token = data.get("next", 0)
                if next_token == 0:
                    break
            else:
                print(f"Ошибка API: {response.status_code} - {response.text}")
                break
        except Exception as e:
            print(f"Ошибка подключения: {str(e)}")
            break
            
    return sorted(supplies, key=lambda x: x['createdAt'], reverse=True)





@orders_bp.route("/get_supply_orders", methods=["GET"])
def get_supply_orders():
    try:
        supply_id = request.args.get('supply_id')
        seller_id = request.args.get('seller_id')
        
        if not supply_id or not seller_id:
            return jsonify({"error": "Missing parameters"}), 400
        
        api_key = get_seller_api_key(seller_id)
        if not api_key:
            return jsonify({"error": "API key not found"}), 404
        
        # Запрос к API Wildberries
        url = f"https://marketplace-api.wildberries.ru/api/v3/supplies/{supply_id}/orders"
        headers = {"Authorization": api_key}
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return jsonify(response.json().get("orders", []))
        else:
            return jsonify({"error": response.text}), response.status_code
            
    except Exception as e:
        print(f"Ошибка получения заказов поставки: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500













@orders_bp.route("/create_supply", methods=["POST"])
def create_supply():
    try:
        seller_id = request.form.get("seller_id")
        supply_name = request.form.get("name", "Новая поставка")
        order_ids = request.form.getlist("order_ids[]")

        if not seller_id or not order_ids:
            flash("Не указаны обязательные параметры")
            return redirect(f"/zakazi?seller_id={seller_id}")

        api_key = get_seller_api_key(seller_id)
        if not api_key:
            flash("API ключ не найден")
            return redirect(f"/zakazi?seller_id={seller_id}")

        # 1. Создаем поставку
        create_url = "https://marketplace-api.wildberries.ru/api/v3/supplies"
        headers = {"Authorization": api_key, "Content-Type": "application/json"}
        
        # Создаем новую поставку
        create_response = requests.post(
            create_url,
            headers=headers,
            json={"name": supply_name}
        )
        
        if create_response.status_code != 201:
            flash(f"Ошибка создания поставки: {create_response.text}")
            return redirect(f"/zakazi?seller_id={seller_id}")

        supply_id = create_response.json().get("id")
        if not supply_id:
            flash("Не удалось получить ID новой поставки")
            return redirect(f"/zakazi?seller_id={seller_id}")

        # 2. Добавляем заказы в поставку
        success_count = 0
        errors = []
        
        for order_id in order_ids:
            add_order_url = f"https://marketplace-api.wildberries.ru/api/v3/supplies/{supply_id}/orders/{order_id}"
            add_response = requests.patch(add_order_url, headers=headers)
            
            if add_response.status_code == 204:
                success_count += 1
            else:
                errors.append(f"Ошибка добавления заказа {order_id}: {add_response.text}")

        # Формируем итоговое сообщение
        message = f"Создана новая поставка #{supply_id}. Успешно добавлено заказов: {success_count}/{len(order_ids)}"
        if errors:
            message += " | Ошибки: " + "; ".join(errors[:3])  # Показываем первые 3 ошибки
        
        flash(message)
        return redirect(f"/zakazi?seller_id={seller_id}&tab=supplies")

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        flash("Произошла ошибка при создании поставки")
        return redirect(f"/zakazi?seller_id={seller_id}")









@orders_bp.route("/deliver_supply", methods=["POST"])
def deliver_supply():
    try:
        supply_id = request.form.get("supply_id")
        seller_id = request.form.get("seller_id")

        if not supply_id or not seller_id:
            return jsonify({"error": "Не указаны параметры"}), 400

        api_key = get_seller_api_key(seller_id)
        if not api_key:
            return jsonify({"error": "API ключ не найден"}), 404

        url = f"https://marketplace-api.wildberries.ru/api/v3/supplies/{supply_id}/deliver"
        headers = {"Authorization": api_key}

        response = requests.patch(url, headers=headers)
        
        if response.status_code == 204:
            return jsonify({"success": True, "message": "Поставка успешно отправлена в доставку"})
        else:
            return jsonify({"error": f"Ошибка: {response.text}"}), response.status_code

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500







@orders_bp.route("/generate_sticker", methods=["POST"])
def generate_sticker_view():
    try:
        order_id = request.form.get("order_id")
        seller_id = request.form.get("seller_id")
        
        if not order_id or not seller_id:
            flash("Не указан ID заказа или продавца", "error")
            return redirect(request.referrer)
        
        api_key = get_seller_api_key(seller_id)
        if not api_key:
            flash("API-ключ не найден", "error")
            return redirect(request.referrer)
        
        # Генерация стикера
        url = "https://marketplace-api.wildberries.ru/api/v3/orders/stickers"
        headers = {
            "Authorization": f"HeaderApiKey {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "orders": [order_id],
            "type": "svg",
            "width": 58,
            "height": 40
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            stickers = response.json().get("stickers", [])
            if stickers:
                sticker_data = stickers[0].get("file")
                if sticker_data:
                    # Генерируем уникальное имя файла
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"sticker_{order_id}_{timestamp}.svg"
                    filepath = os.path.join(STICKERS_FOLDER, filename)
                    
                    # Декодируем и сохраняем файл
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(sticker_data))
                    
                    # Формируем URL для скачивания
                    sticker_url = url_for('static', filename=f'stickers/{filename}')
                    flash(f"Стикер успешно сгенерирован! <a href='{sticker_url}' download>Скачать</a>", "success")
                else:
                    flash("Ошибка: Пустые данные стикера", "error")
            else:
                flash("Стикер не был создан", "warning")
        else:
            error_msg = response.json().get("error", {}).get("message", "Неизвестная ошибка")
            flash(f"Ошибка генерации стикера: {error_msg}", "error")
            
        return redirect(f"/zakazi?seller_id={seller_id}")
        
    except Exception as e:
        print(f"Ошибка генерации стикера: {str(e)}")
        flash("Произошла внутренняя ошибка при генерации стикера", "error")
        return redirect(request.referrer)

# Добавим маршрут для скачивания файлов
@orders_bp.route('/stickers/<filename>')
def download_sticker(filename):
    return send_from_directory(STICKERS_FOLDER, filename, as_attachment=True)
