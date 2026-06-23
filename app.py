# -*- coding: utf-8 -*-
import os
import csv
import datetime
from typing import List, Optional

from fastapi import FastAPI, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import (Column, Integer, String, Text, DateTime, create_engine,
                        func, select, or_)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from werkzeug.security import generate_password_hash, check_password_hash

# ----------------------------------------------------------------------
# Database setup
# ----------------------------------------------------------------------
DATABASE_URL = "sqlite:///./clients.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True)
    phone = Column(String)
    company = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Create a default admin user if none exists
    db: Session = SessionLocal()
    if not db.query(User).first():
        admin = User(
            username="admin",
            password_hash=generate_password_hash("admin123")
        )
        db.add(admin)
        db.commit()
    db.close()


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def log_activity(username: str, action: str):
    """Append an activity line to activity.log."""
    log_line = f"{datetime.datetime.utcnow().isoformat()} | {username} | {action}\n"
    with open("activity.log", "a", encoding="utf-8") as f:
        f.write(log_line)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    username = request.cookies.get("session")
    if not username:
        return None
    return db.query(User).filter(User.username == username).first()


# ----------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------
app = FastAPI()


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request,
              page: int = 1,
              q: Optional[str] = None,
              db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    per_page = 10
    stmt = select(Client)
    if q:
        stmt = stmt.where(
            or_(
                Client.name.ilike(f"%{q}%"),
                Client.company.ilike(f"%{q}%")
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    clients = db.execute(
        stmt.order_by(Client.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
    ).scalars().all()

    # Build HTML
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Professional Portal</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
<style>
body {{ background-color: #f8f9fa; }}
.navbar {{ background-color: #004080; }}
.table thead {{ background-color: #e9ecef; }}
.table tbody tr:nth-child(even) {{ background-color: #fdfdfd; }}
.table tbody tr:nth-child(odd) {{ background-color: #f8f9fa; }}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="#">Professional Portal</a>
    <div class="collapse navbar-collapse justify-content-end">
      <ul class="navbar-nav">
        <li class="nav-item">
          <span class="nav-link">Logged in as: {user.username}</span>
        </li>
        <li class="nav-item">
          <a class="nav-link btn btn-outline-light ms-2" href="/logout">Logout</a>
        </li>
      </ul>
    </div>
  </div>
</nav>

<div class="container-fluid mt-4">
  <div class="row">
    <!-- Form Column -->
    <div class="col-md-4">
      <h4 id="form-title">Add New Client</h4>
      <form id="client-form" method="post" action="/add">
        <input type="hidden" name="client_id" id="client_id" value="">
        <div class="mb-3">
          <label class="form-label">Name</label>
          <input type="text" class="form-control" name="name" id="name" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Email</label>
          <input type="email" class="form-control" name="email" id="email">
        </div>
        <div class="mb-3">
          <label class="form-label">Phone</label>
          <input type="text" class="form-control" name="phone" id="phone">
        </div>
        <div class="mb-3">
          <label class="form-label">Company</label>
          <input type="text" class="form-control" name="company" id="company">
        </div>
        <div class="mb-3">
          <label class="form-label">Notes</label>
          <textarea class="form-control" name="notes" id="notes"></textarea>
        </div>
        <button type="submit" class="btn btn-success" id="submit-btn"><i class="fa fa-plus"></i> Add</button>
        <button type="button" class="btn btn-primary ms-2" id="update-btn" style="display:none;"><i class="fa fa-save"></i> Save</button>
        <button type="button" class="btn btn-secondary ms-2" id="cancel-btn" style="display:none;">Cancel</button>
      </form>
    </div>

    <!-- Table Column -->
    <div class="col-md-8">
      <div class="d-flex justify-content-between mb-2">
        <form class="d-flex" method="get" action="/">
          <input class="form-control me-2" type="search" placeholder="Search by name or company" name="q" value="{q or ''}">
          <button class="btn btn-outline-success" type="submit"><i class="fa fa-search"></i></button>
        </form>
        <a href="/export" class="btn btn-dark"><i class="fa fa-file-csv"></i> Export CSV</a>
      </div>
      <table class="table table-hover table-responsive">
        <thead>
          <tr>
            <th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Company</th><th>Notes</th><th>Created At</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
"""
    for client in clients:
        html += f"""
          <tr data-id="{client.id}">
            <td>{client.id}</td>
            <td>{client.name}</td>
            <td>{client.email or ''}</td>
            <td>{client.phone or ''}</td>
            <td>{client.company or ''}</td>
            <td>{client.notes or ''}</td>
            <td>{client.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td>
              <button class="btn btn-sm btn-primary edit-btn"><i class="fa fa-edit"></i></button>
              <button class="btn btn-sm btn-danger delete-btn"><i class="fa fa-trash"></i></button>
            </td>
          </tr>
"""
    html += """
        </tbody>
      </table>
      <nav>
        <ul class="pagination">
"""
    total_pages = (total // per_page) + (1 if total % per_page else 0)
    for p in range(1, total_pages + 1):
        active = "active" if p == page else ""
        html += f'<li class="page-item {active}"><a class="page-link" href="/?page={p}&q={q or ""}">{p}</a></li>'
    html += """
        </ul>
      </nav>
    </div>
  </div>
</div>

<!-- Delete Confirmation Modal -->
<div class="modal fade" id="deleteModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Confirm Deletion</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <strong>Are you sure you want to delete this client?</strong>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-danger" id="confirm-delete">Confirm</button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
let deleteClientId = null;
document.querySelectorAll('.edit-btn').forEach(btn => {
    btn.addEventListener('click', e => {
        const tr = e.target.closest('tr');
        const id = tr.dataset.id;
        fetch(`/client/${id}`)
            .then(r => r.json())
            .then(data => {
                document.getElementById('client_id').value = data.id;
                document.getElementById('name').value = data.name;
                document.getElementById('email').value = data.email || '';
                document.getElementById('phone').value = data.phone || '';
                document.getElementById('company').value = data.company || '';
                document.getElementById('notes').value = data.notes || '';
                document.getElementById('form-title').innerText = 'Edit Client';
                document.getElementById('submit-btn').style.display = 'none';
                document.getElementById('update-btn').style.display = 'inline-block';
                document.getElementById('cancel-btn').style.display = 'inline-block';
            });
    });
});

document.getElementById('cancel-btn').addEventListener('click', () => {
    document.getElementById('client-form').reset();
    document.getElementById('client_id').value = '';
    document.getElementById('form-title').innerText = 'Add New Client';
    document.getElementById('submit-btn').style.display = 'inline-block';
    document.getElementById('update-btn').style.display = 'none';
    document.getElementById('cancel-btn').style.display = 'none';
});

document.getElementById('update-btn').addEventListener('click', () => {
    const id = document.getElementById('client_id').value;
    const form = document.getElementById('client-form');
    const data = new URLSearchParams(new FormData(form));
    fetch(`/edit/${id}`, {
        method: 'POST',
        body: data,
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}
    }).then(() => location.reload());
});

document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', e => {
        const tr = e.target.closest('tr');
        deleteClientId = tr.dataset.id;
        const modal = new bootstrap.Modal(document.getElementById('deleteModal'));
        modal.show();
    });
});

document.getElementById('confirm-delete').addEventListener('click', () => {
    fetch(`/delete/${deleteClientId}`, {method: 'POST'}).then(() => location.reload());
});
</script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Login - Professional Portal</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body { background-color: #f8f9fa; }
.card { max-width: 400px; margin: 100px auto; }
</style>
</head>
<body>
<div class="card shadow">
  <div class="card-body">
    <h5 class="card-title text-center mb-4">Login</h5>
    <form method="post" action="/login">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input type="text" class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input type="password" class="form-control" name="password" required>
      </div>
      <button type="submit" class="btn btn-primary w-100">Login</button>
    </form>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not check_password_hash(user.password_hash, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="session", value=user.username, httponly=True, max_age=60*60*24)
    log_activity(user.username, "login")
    return response


@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session")
    username = request.cookies.get("session") or "unknown"
    log_activity(username, "logout")
    return response


@app.post("/add")
def add_client(name: str = Form(...),
               email: Optional[str] = Form(None),
               phone: Optional[str] = Form(None),
               company: Optional[str] = Form(None),
               notes: Optional[str] = Form(None),
               request: Request = None,
               db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    client = Client(name=name, email=email, phone=phone, company=company, notes=notes)
    db.add(client)
    db.commit()
    log_activity(user.username, f"added client id={client.id}")
    return RedirectResponse(url="/", status_code=303)


@app.get("/client/{client_id}")
def get_client(client_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return {
        "id": client.id,
        "name": client.name,
        "email": client.email,
        "phone": client.phone,
        "company": client.company,
        "notes": client.notes
    }


@app.post("/edit/{client_id}")
def edit_client(client_id: int,
                name: str = Form(...),
                email: Optional[str] = Form(None),
                phone: Optional[str] = Form(None),
                company: Optional[str] = Form(None),
                notes: Optional[str] = Form(None),
                request: Request = None,
                db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.name = name
    client.email = email
    client.phone = phone
    client.company = company
    client.notes = notes
    db.commit()
    log_activity(user.username, f"edited client id={client.id}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete/{client_id}")
def delete_client(client_id: int, request: Request = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
    log_activity(user.username, f"deleted client id={client_id}")
    return RedirectResponse(url="/", status_code=303)


@app.get("/export")
def export_csv(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    def iter_csv():
        header = ["id", "name", "email", "phone", "company", "notes", "created_at"]
        yield ",".join(header) + "\n"
        for client in db.query(Client).order_by(Client.id):
            row = [
                str(client.id),
                client.name,
                client.email or "",
                client.phone or "",
                client.company or "",
                client.notes.replace("\\n", " ").replace(",", " ") if client.notes else "",
                client.created_at.isoformat()
            ]
            yield ",".join(row) + "\n"
    log_activity(user.username, "exported CSV")
    return StreamingResponse(iter_csv(),
                             media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=clients.csv"})


# ----------------------------------------------------------------------
# Startup event
# ----------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    init_db()


if __name__ == "__main__":
    import os, uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))