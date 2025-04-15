// Функции для работы с аутентификацией
document.addEventListener('DOMContentLoaded', function() {
    // Обработка формы входа
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const submitBtn = this.querySelector('button[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Вход...';
            this.submit();
        });
    }

    // Обработка формы регистрации
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const submitBtn = this.querySelector('button[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Регистрация...';
            this.submit();
        });
    }
});

// Функции для работы с компаниями
function searchByINN() {
    const inn = document.getElementById('innInput').value.trim();
    if (!/^\d{10,12}$/.test(inn)) {
        alert('Введите корректный ИНН (10 или 12 цифр)');
        return;
    }

    const resultDiv = document.getElementById('companyInfoResult');
    resultDiv.innerHTML = '<div class="loading-spinner"><i class="fas fa-spinner fa-spin"></i> Поиск компании...</div>';

    fetch('/get_company_info', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({inn: inn})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (data.multiple) {
                showCompanySelection(data.data);
            } else {
                displayCompanyInfo(data.data);
            }
        } else {
            resultDiv.innerHTML = `<div class="error-message">${data.message || 'Ошибка при поиске компании'}</div>`;
        }
    })
    .catch(error => {
        resultDiv.innerHTML = `<div class="error-message">Ошибка сети: ${error.message}</div>`;
    });
}

function showCompanySelection(companies) {
    const resultDiv = document.getElementById('companyInfoResult');
    let html = '<div class="company-selection">';
    html += `<h4>Найдено ${companies.length} компаний:</h4>`;

    companies.forEach((company, index) => {
        html += `
            <div class="company-option" onclick="selectCompany(${index})">
                <div class="company-name">${company.name || 'Без названия'}</div>
                <div class="company-inn">ИНН: ${company.inn}</div>
            </div>
        `;
    });

    html += '</div>';
    resultDiv.innerHTML = html;
    window.currentCompanies = companies;
}

function selectCompany(index) {
    displayCompanyInfo(window.currentCompanies[index]);
}

function displayCompanyInfo(company) {
    const resultDiv = document.getElementById('companyInfoResult');
    let html = `
        <div class="company-info">
            <h3>${company.name || 'Нет названия'}</h3>
            <div class="company-details">
                <p><strong>ИНН:</strong> ${company.inn}</p>
                ${company.ogrn ? `<p><strong>ОГРН:</strong> ${company.ogrn}</p>` : ''}
                ${company.kpp ? `<p><strong>КПП:</strong> ${company.kpp}</p>` : ''}
                ${company.address ? `<p><strong>Адрес:</strong> ${company.address}</p>` : ''}
                <button class="save-company-btn" onclick="saveCompany(${JSON.stringify(company).replace(/"/g, '&quot;')})">
                    <i class="fas fa-save"></i> Сохранить компанию
                </button>
            </div>
        </div>
    `;
    resultDiv.innerHTML = html;
}

function saveCompany(company) {
    fetch('/save_company', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(company)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Компания успешно сохранена');
            location.reload();
        } else {
            alert(data.message || 'Ошибка при сохранении компании');
        }
    })
    .catch(error => {
        alert('Ошибка сети: ' + error.message);
    });
}

function removeCompany(inn) {
    if (confirm('Вы уверены, что хотите удалить эту компанию?')) {
        fetch('/remove_company/' + inn, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert(data.message || 'Ошибка при удалении компании');
            }
        })
        .catch(error => {
            alert('Ошибка сети: ' + error.message);
        });
    }
}
function saveUserInfo() {
    const info = document.getElementById('userInfoTextarea').value;
    
    const formData = new FormData();
    formData.append('user_info', info);
    
    fetch('/update_user_info', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Информация успешно сохранена');
        } else {
            alert('Ошибка при сохранении: ' + (data.message || 'Неизвестная ошибка'));
        }
    })
    .catch(error => {
        alert('Ошибка сети: ' + error.message);
    });
}
