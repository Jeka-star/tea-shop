import os
import io
import base64
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-please-32-chars-min")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

# ---------- БАЗА ----------
db_url = os.environ.get("DATABASE_URL", "sqlite:///tea.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------- МОДЕЛІ ----------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    pass_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.String(20), primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    tea_name = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    visit_date = db.Column(db.String(20), nullable=False)
    visit_time = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(30), default="Прийнято")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_open = db.Column(db.Boolean, default=True)
    close_time = db.Column(db.String(5), default="20:00")

with app.app_context():
    db.create_all()
    if not Setting.query.get(1):
        db.session.add(Setting(id=1, store_open=True, close_time="20:00"))
        db.session.commit()

# ---------- КОНСТАНТИ ----------
TEAS = {
    "black": {"name": "Чорний", "price": 10},
    "fruit": {"name": "Фруктовий", "price": 10},
    "green": {"name": "Зелений", "price": 10},
}

ADMIN_SERIAL_HASH = "7b6df80c57ed2a3f9bd99d03d148576ab5c714ffbd6770e39340ba2533976b46"  # P2515
ADMIN_PASS_HASH   = "e97776493f213d50b346f81e3f93a78aad1fd0f19c051a38bd8f88b43e46e5b5"  # 1506

def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()

def make_qr_b64(text):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def order_to_dict(o, qr_base_url=""):
    d = {
        "id": o.id, "username": o.username, "name": o.name,
        "tea_name": o.tea_name, "price": o.price,
        "visit_date": o.visit_date, "visit_time": o.visit_time,
        "status": o.status,
        "created_at": o.created_at.strftime("%d.%m %H:%M"),
        "expired": datetime.utcnow() > o.expires_at,
        "qr": make_qr_b64(qr_base_url + "/order/" + o.id)
    }
    return d

# ============================================================
#  ФРОНТЕНД (встроен в один шаблон)
# ============================================================
HTML = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Чайний дім</title>
<style>
  *{box-sizing:border-box;font-family:system-ui,sans-serif}
  body{margin:0;background:#f6f1e7;color:#2b2b2b}
  .container{max-width:860px;margin:0 auto;padding:20px}
  header{display:flex;justify-content:space-between;align-items:center;padding:16px 0;border-bottom:1px solid #d8cbb4}
  h1{font-size:22px;margin:0}h2{font-size:18px;margin:0 0 12px}
  .card{background:#fff;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 4px 14px rgba(0,0,0,.06)}
  input,select,button{font-size:15px;padding:10px 12px;border-radius:8px;border:1px solid #c9bda6;width:100%;margin:6px 0}
  button{background:#6b8e4e;color:#fff;border:none;cursor:pointer;font-weight:600}
  button:hover{background:#5a7a41}
  button.secondary{background:#a99b7d}
  .row{display:flex;gap:10px}.row>*{flex:1}
  .error{color:#b85c4a;font-size:14px;min-height:18px}
  .ok{color:#4e7a41;font-size:14px;min-height:18px}
  .hidden{display:none!important}
  .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:13px;background:#e7efd9;color:#4e7a41}
  .badge.off{background:#f3d9d3;color:#b85c4a}
  .tea-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
  .tea{border:1px solid #d8cbb4;border-radius:10px;padding:12px;cursor:pointer}
  .tea.selected{outline:2px solid #6b8e4e;background:#eef4e4}
  .order{border:1px solid #e0d6c3;border-radius:10px;padding:12px;margin:10px 0;background:#fffdf8}
  .qr-img{width:120px;height:120px}
  .small{font-size:13px;color:#6f6656}
  .warning{background:#fff3d6;border-left:4px solid #e0a92e;padding:10px 14px;border-radius:6px;font-size:14px;margin:10px 0}
  .tab{display:flex;gap:8px;margin-bottom:12px}
  .tab button{flex:0 0 auto;background:#c9bda6;color:#2b2b2b;padding:8px 14px}
  .tab button.active{background:#6b8e4e;color:#fff}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>🍵 Чайний дім</h1>
  <div><span id="userLabel" class="small"></span>
  <button id="logoutBtn" class="secondary hidden" style="width:auto;padding:6px 12px;margin-left:10px">Вийти</button></div>
</header>

<div id="authScreen" class="card">
  <div class="tab">
    <button id="tabReg" class="active">Реєстрація</button>
    <button id="tabLogin">Вхід</button>
  </div>
  <div id="regBox">
    <input id="regFirst" placeholder="Ім'я">
    <input id="regLast" placeholder="Прізвище">
    <input id="regUser" placeholder="Нікнейм">
    <input id="regPass" type="password" placeholder="Пароль">
    <input id="regPass2" type="password" placeholder="Повторіть пароль">
    <div id="regMsg" class="error"></div>
    <button id="regBtn">Зареєструватися</button>
  </div>
  <div id="loginBox" class="hidden">
    <input id="logUser" placeholder="Нікнейм">
    <input id="logPass" type="password" placeholder="Пароль">
    <div id="logMsg" class="error"></div>
    <button id="logBtn">Увійти</button>
  </div>
</div>

<div id="adminGate" class="card hidden">
  <h2>Службовий вхід</h2>
  <input id="adminSerial" placeholder="Серійний номер">
  <input id="adminPass" type="password" placeholder="Пароль адміністратора">
  <div id="adminMsg" class="error"></div>
  <button id="adminBtn">Підтвердити</button>
  <button id="adminCancel" class="secondary">Скасувати</button>
</div>

<div id="userScreen" class="hidden">
  <div class="card">
    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px">
      <div>Стан: <span id="storeStatus" class="badge">—</span></div>
      <div class="small">Сьогодні до: <b id="todayClose">—</b></div>
    </div>
    <div id="closedNotice" class="warning hidden">Крамниця зачинена.</div>
  </div>
  <div class="card">
    <h2>Оберіть чай</h2>
    <div id="teaGrid" class="tea-grid"></div>
    <h2 style="margin-top:20px">Деталі</h2>
    <div class="warning">⏳ Замовлення діє 1 годину.</div>
    <input id="orderName" readonly>
    <div class="row">
      <select id="visitDate"></select>
      <select id="visitTime"></select>
    </div>
    <div id="orderMsg" class="error"></div>
    <button id="makeOrderBtn">Оформити</button>
  </div>
  <div class="card"><h2>Мої замовлення</h2><div id="myOrders"></div></div>
</div>

<div id="adminScreen" class="hidden">
  <div class="card">
    <h2>Панель адміністратора</h2>
    <div class="row" style="align-items:center;flex-wrap:wrap">
      <label style="flex:0 0 auto;display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="storeOpen" style="width:auto;margin:0"> Крамниця відчинена
      </label>
      <input id="closeTime" type="time" style="max-width:160px">
      <button id="saveSettings" style="max-width:180px">Зберегти</button>
    </div>
    <div id="settingsMsg" class="ok"></div>
  </div>
  <div class="card"><h2>Усі замовлення</h2><div id="allOrders"></div></div>
</div>
</div>

<script>
const $ = id => document.getElementById(id);
let session = null, isAdmin = false, selectedTea = null, settings = {open:true, closeTime:'20:00'};
const TEAS = {black:'Чорний', fruit:'Фруктовий', green:'Зелений'};
let pollTimer = null;

function showOnly(el){
  ['authScreen','adminGate','userScreen','adminScreen'].forEach(x=>$(x).classList.add('hidden'));
  if(el) $(el).classList.remove('hidden');
  $('userLabel').textContent = session ? 'Ви: '+session : (isAdmin?'Адмін':'');
  $('logoutBtn').classList.toggle('hidden', !session && !isAdmin);
}

async function api(url, opts={}){
  const r = await fetch(url, {credentials:'same-origin', ...opts});
  return await r.json();
}

// ---- АВТОРИЗАЦІЯ ----
$('tabReg').onclick = ()=>{$('tabReg').classList.add('active');$('tabLogin').classList.remove('active');$('regBox').classList.remove('hidden');$('loginBox').classList.add('hidden')};
$('tabLogin').onclick = ()=>{$('tabLogin').classList.add('active');$('tabReg').classList.remove('active');$('loginBox').classList.remove('hidden');$('regBox').classList.add('hidden')};

$('regBtn').onclick = async ()=>{
  const body = {
    first:$('regFirst').value.trim(), last:$('regLast').value.trim(),
    username:$('regUser').value.trim(), password:$('regPass').value,
    password2:$('regPass2').value
  };
  const r = await api('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const m = $('regMsg'); m.className = r.ok?'ok':'error'; m.textContent = r.message;
  if(r.ok){ session = body.username; setTimeout(enterUser,300); }
};

$('logBtn').onclick = async ()=>{
  const username = $('logUser').value.trim();
  const password = $('logPass').value;
  if(username.toLowerCase()==='admin'){ showOnly('adminGate'); return; }
  const r = await api('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
  const m = $('logMsg'); m.className = r.ok?'ok':'error'; m.textContent = r.message;
  if(r.ok){ session = r.username; enterUser(); }
};

$('adminBtn').onclick = async ()=>{
  const body = {serial:$('adminSerial').value.trim(), password:$('adminPass').value};
  const r = await api('/api/admin-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const m = $('adminMsg'); m.className = r.ok?'ok':'error'; m.textContent = r.message;
  if(r.ok){ isAdmin = true; session = null; enterAdmin(); }
};
$('adminCancel').onclick = ()=>showOnly('authScreen');

$('logoutBtn').onclick = async ()=>{
  await api('/api/logout',{method:'POST'});
  session = null; isAdmin = false; clearInterval(pollTimer);
  showOnly('authScreen');
};

// ---- КОРИСТУВАЧ ----
async function enterUser(){
  showOnly('userScreen');
  $('orderName').value = session;
  const s = await api('/api/settings'); settings = s;
  renderStatus(); renderTeas(); renderDates(); renderTimes();
  await renderMyOrders();
  clearInterval(pollTimer);
  pollTimer = setInterval(async ()=>{
    await renderMyOrders();
    const st = await api('/api/settings');
    if(st.store_open !== settings.open || st.close_time !== settings.closeTime){
      settings = st; renderStatus(); renderTimes();
    }
  }, 3000);
}

function renderStatus(){
  $('storeStatus').textContent = settings.open?'Відчинена':'Зачинена';
  $('storeStatus').className = 'badge'+(settings.open?'':' off');
  $('todayClose').textContent = settings.close_time;
  $('closedNotice').classList.toggle('hidden', settings.open);
  $('makeOrderBtn').disabled = !settings.open;
}

function renderTeas(){
  const g = $('teaGrid'); g.innerHTML='';
  Object.entries(TEAS).forEach(([id,name])=>{
    const d = document.createElement('div');
    d.className = 'tea'+(selectedTea===id?' selected':'');
    d.innerHTML = `<b>${name}</b><div class="small">10 ₴</div>`;
    d.onclick = ()=>{selectedTea=id;renderTeas()};
    g.appendChild(d);
  });
}

function renderDates(){
  const s = $('visitDate'); s.innerHTML='';
  const today = new Date();
  for(let i=0;i<3;i++){
    const d = new Date(today); d.setDate(today.getDate()+i);
    const o = document.createElement('option');
    o.value = d.toISOString().slice(0,10);
    o.textContent = i===0?'Сьогодні':d.toLocaleDateString('uk-UA');
    s.appendChild(o);
  }
}

function renderTimes(){
  const s = $('visitTime'); s.innerHTML='';
  const [h,m] = (settings.close_time||'20:00').split(':').map(Number);
  for(let hh=9;hh<=h;hh++) for(let mm=0;mm<60;mm+=30){
    if(hh===h&&mm>m) continue;
    const t = String(hh).padStart(2,'0')+':'+String(mm).padStart(2,'0');
    const o = document.createElement('option'); o.value=t; o.textContent=t; s.appendChild(o);
  }
}

$('makeOrderBtn').onclick = async ()=>{
  const msg = $('orderMsg'); msg.className='error'; msg.textContent='';
  if(!settings.open){msg.textContent='Крамниця зачинена.';return;}
  if(!selectedTea){msg.textContent='Оберіть чай.';return;}
  const body = {tea_id:selectedTea, visit_date:$('visitDate').value, visit_time:$('visitTime').value};
  const r = await api('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  msg.className = r.ok?'ok':'error'; msg.textContent = r.message;
  if(r.ok) renderMyOrders();
};

function orderCard(o){
  const d = document.createElement('div'); d.className='order';
  d.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px">
      <div>
        <b>${o.id}</b> — ${o.tea_name} (${o.price} ₴)<br>
        <span class="small">${o.name} · ${o.visit_date} о ${o.visit_time}</span><br>
        <span class="small">Створено: ${o.created_at}</span>
      </div>
      <div style="text-align:right"><span class="badge ${o.expired?'off':''}">${o.expired?'Спливло':'Активне'}</span></div>
    </div>
    <img class="qr-img" src="data:image/png;base64,${o.qr}">
  `;
  return d;
}

async function renderMyOrders(){
  const data = await api('/api/orders/mine');
  const box = $('myOrders'); box.innerHTML='';
  if(!data.length){ box.innerHTML='<div class="small">Замовлень поки немає.</div>'; return; }
  data.forEach(o=>box.appendChild(orderCard(o)));
}

// ---- АДМІН ----
async function enterAdmin(){
  showOnly('adminScreen');
  const s = await api('/api/settings'); settings = s;
  $('storeOpen').checked = settings.open;
  $('closeTime').value = settings.close_time;
  await renderAll();
  clearInterval(pollTimer);
  pollTimer = setInterval(renderAll, 3000);
}

async function renderAll(){
  const data = await api('/api/orders/all');
  const box = $('allOrders'); box.innerHTML='';
  if(!data.length){ box.innerHTML='<div class="small">Замовлень немає.</div>'; return; }
  data.forEach(o=>box.appendChild(orderCard(o)));
}

$('saveSettings').onclick = async ()=>{
  const body = {store_open:$('storeOpen').checked, close_time:$('closeTime').value||'20:00'};
  const r = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  $('settingsMsg').textContent = r.ok?'Збережено ✓':'Помилка';
  setTimeout(()=>$('settingsMsg').textContent='',2000);
};

// ---- СТАРТ ----
(async ()=>{
  const s = await api('/api/me');
  if(s.admin){ isAdmin=true; enterAdmin(); }
  else if(s.username){ session=s.username; enterUser(); }
  else showOnly('authScreen');
})();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/order/<order_id>")
def order_page(order_id):
    o = Order.query.get(order_id)
    if not o:
        return "<h2>Замовлення не знайдено</h2>", 404
    d = order_to_dict(o, request.host_url.rstrip("/"))
    return render_template_string("""
    <html><head><meta charset="utf-8"><title>Замовлення {{o.id}}</title></head>
    <body style="font-family:system-ui;padding:20px;background:#f6f1e7">
      <h2>Замовлення {{o.id}}</h2>
      <p><b>{{o.name}}</b><br>
      {{o.tea_name}} — {{o.price}} ₴<br>
      Візит: {{o.visit_date}} о {{o.visit_time}}<br>
      Статус: {{o.status}}</p>
    </body></html>
    """, o=d)

# ============ API ============
@app.route("/api/me")
def me():
    return jsonify({
        "username": session.get("username"),
        "admin": session.get("admin", False)
    })

@app.route("/api/register", methods=["POST"])
def register():
    d = request.get_json()
    if not all([d.get("first"), d.get("last"), d.get("username"), d.get("password")]):
        return jsonify(ok=False, message="Заповніть усі поля.")
    if d["password"] != d.get("password2"):
        return jsonify(ok=False, message="Паролі не збігаються.")
    if d["username"].lower() == "admin":
        return jsonify(ok=False, message="Цей нікнейм зарезервовано.")
    if User.query.filter_by(username=d["username"]).first():
        return jsonify(ok=False, message="Нікнейм зайнятий.")
    u = User(
        username=d["username"], first_name=d["first"], last_name=d["last"],
        pass_hash=generate_password_hash(d["password"])
    )
    db.session.add(u); db.session.commit()
    session["username"] = u.username
    return jsonify(ok=True, message="Готово!")

@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json()
    u = User.query.filter_by(username=d.get("username","")).first()
    if not u or not check_password_hash(u.pass_hash, d.get("password","")):
        return jsonify(ok=False, message="Невірний нікнейм або пароль.")
    session["username"] = u.username
    session.pop("admin", None)
    return jsonify(ok=True, username=u.username)

@app.route("/api/admin-login", methods=["POST"])
def admin_login():
    d = request.get_json()
    serial = d.get("serial","")
    password = d.get("password","")
    if sha256(serial) != ADMIN_SERIAL_HASH or sha256(password) != ADMIN_PASS_HASH:
        return jsonify(ok=False, message="Невірні дані.")
    session.clear()
    session["admin"] = True
    return jsonify(ok=True)

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(ok=True)

@app.route("/api/settings")
def get_settings():
    s = Setting.query.get(1)
    return jsonify(store_open=s.store_open, close_time=s.close_time)

@app.route("/api/settings", methods=["POST"])
def set_settings():
    if not session.get("admin"):
        return jsonify(ok=False, message="Тільки адмін."), 403
    d = request.get_json()
    s = Setting.query.get(1)
    s.store_open = bool(d.get("store_open", s.store_open))
    s.close_time = d.get("close_time", s.close_time)
    db.session.commit()
    return jsonify(ok=True)

@app.route("/api/order", methods=["POST"])
def make_order():
    if "username" not in session:
        return jsonify(ok=False, message="Увійдіть."), 401
    s = Setting.query.get(1)
    if not s.store_open:
        return jsonify(ok=False, message="Крамниця зачинена.")
    d = request.get_json()
    tea_id = d.get("tea_id")
    if tea_id not in TEAS:
        return jsonify(ok=False, message="Оберіть чай.")
    u = User.query.filter_by(username=session["username"]).first()
    tea = TEAS[tea_id]
    o = Order(
        id="ORD-" + os.urandom(3).hex().upper(),
        username=u.username,
        name=f"{u.first_name} {u.last_name}",
        tea_name=tea["name"], price=tea["price"],
        visit_date=d["visit_date"], visit_time=d["visit_time"],
        expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    db.session.add(o); db.session.commit()
    return jsonify(ok=True, message=f"Замовлення {o.id} оформлено!")

@app.route("/api/orders/mine")
def my_orders():
    if "username" not in session:
        return jsonify([])
    rows = Order.query.filter_by(username=session["username"]).order_by(Order.created_at.desc()).all()
    host = request.host_url.rstrip("/")
    return jsonify([order_to_dict(o, host) for o in rows])

@app.route("/api/orders/all")
def all_orders():
    if not session.get("admin"):
        return jsonify([]), 403
    rows = Order.query.order_by(Order.created_at.desc()).all()
    host = request.host_url.rstrip("/")
    return jsonify([order_to_dict(o, host) for o in rows])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))