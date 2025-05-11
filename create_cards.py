from flask import Blueprint, render_template, request, jsonify
import os
import openpyxl
import json
import requests
import math

# Создаем новый Blueprint для карточек
create_cards_bp = Blueprint('create_cards', __name__)

# Загрузка категорий и комиссий
def load_wb_commissions():
    categories = {}
    commissions = {}
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

def parse_excel(file_path):
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
                    products.append({
                        'article': current_group,
                        'name': group_data[0]['Название'],
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
            products.append({
                'article': current_group,
                'name': group_data[0]['Название'],
                'category': current_category,
                'variants': group_data
            })

        wb.close()
    except Exception as e:
        print(f"Ошибка при парсинге Excel: {str(e)}")

    return products

@create_cards_bp.route('/create_wb_cards', methods=['POST'])
def create_wb_cards():
    try:
        selected_products = request.json.get('products', [])
        api_key = request.json.get('api_key', '')

        if not api_key:
            return jsonify({'success': False, 'message': 'API ключ не указан'}), 400

        # Подготовка данных для WB API
        cards_to_create = []

        for product in selected_products:
            # Находим subjectID по названию категории
            subject_id = WB_CATEGORIES.get(product['category'], 0)
            commission_percent = WB_COMMISSIONS.get(product['category'], 16.5) / 100  # по умолчанию 16.5%

            if not subject_id:
                continue  # Пропускаем если категория не найдена

            # Константы
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
                    length = int(variant.get('Длина (см)', 0)) or 10
                    width = int(variant.get('Ширина (см)', 0)) or 10
                    height = int(variant.get('Высота (см)', 0)) or 10
                    base_price = float(variant.get('Цена', 0))

                    # 1. Объем
                    volume = (length * width * height) / 1000

                    # 2. AB2
                    ab2 = 43.75 + 10.625 * (math.ceil(volume) - 1)

                    # 3. AD2 - логистика с учетом возврата
                    ad2 = (ab2 + (50 * (1 - AC2))) / AC2

                    # 4. Формула цены с учетом всех коэффициентов
                    final_price = (base_price + AE2 + ad2) / (1 - J2 - K2 - AF2 - AG2 - commission_percent - L2)
                    final_price = round(final_price)

                    variants.append({
                        "vendorCode": str(variant.get('Артикул', '')),
                        "title": product.get('name', ''),
                        "dimensions": {
                            "length": length,
                            "width": width,
                            "height": height,
                            "weightBrutto": 0.3
                        },
                        "sizes": [{
                            "price": final_price
                        }]
                    })
                except Exception as e:
                    print(f"Ошибка при расчёте цены: {str(e)}")

            # Создаем карточку товара
            cards_to_create.append({
                "subjectID": subject_id,
                "variants": variants
            })

        # Логирование отправляемых данных
        print("Отправляемые данные:", json.dumps(cards_to_create, indent=4, ensure_ascii=False))

        # Отправка данных в WB API
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
        return jsonify({
            'success': False,
            'message': f'Ошибка: {str(e)}'
        }), 500

@create_cards_bp.route('/cards/index')
def index():
    file_path = os.path.join(app.root_path, 'Каталог.xlsx')
    if not os.path.exists(file_path):
        return "Файл не найден", 404

    try:
        products = parse_excel(file_path)
        return render_template('wb_cards.html', products=products, wb_categories=WB_CATEGORIES)
    except Exception as e:
        return f"Ошибка: {str(e)}", 500
