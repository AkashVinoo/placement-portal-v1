from flask import Flask, request, redirect, render_template, session
from datetime import datetime
from werkzeug.utils import secure_filename
import os

from extensions import db
import models

app = Flask(__name__)

# -------------------- HELPERS --------------------

def flash(message):
    """Store a message in session to show to user"""
    messages = session.get('flash_messages', [])
    messages.append(message)
    session['flash_messages'] = messages

def get_flash_messages():
    """Get and clear flash messages"""
    messages = session.get('flash_messages', [])
    session['flash_messages'] = []
    return messages

def format_date(date_value):
    """Format date to readable string"""
    if date_value:
        try:
            return datetime.strptime(date_value, "%Y-%m-%d").strftime("%B %d, %Y")
        except:
            return date_value
    return "-"

app.config['SECRET_KEY'] = 'secretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['UPLOAD_FOLDER'] = 'static/resumes'

db.init_app(app)

# -------------------- HELPERS --------------------

def is_logged_in():
    return 'user_id' in session

def is_admin():
    return is_logged_in() and session.get('role') == 'admin'

def is_student():
    return is_logged_in() and session.get('role') == 'student'

def is_company():
    return is_logged_in() and session.get('role') == 'company'

def get_current_student():
    return models.Student.query.filter_by(user_id=session['user_id']).first()

def get_current_company():
    return models.Company.query.filter_by(user_id=session['user_id']).first()

# -------------------- ROUTES --------------------

@app.route("/")
def index():
    return render_template("index.html")

# -------- REGISTER --------

@app.route("/register_student", methods=['GET', 'POST'])
def register_student():
    if request.method == "POST":
        email = request.form.get("email")

        if models.User.query.filter_by(email=email).first():
            return render_template("error.html", message="Email already registered")

        # validate CGPA
        cgpa = request.form.get("cgpa")
        if cgpa:
            cgpa = float(cgpa)
            if cgpa < 0 or cgpa > 10:
                return render_template("error.html", message="CGPA must be between 0 and 10")

        # validate passing year
        passing_year = request.form.get("passing_year")
        if passing_year:
            passing_year = int(passing_year)
            current_year = datetime.utcnow().year
            if passing_year < 1900 or passing_year > current_year + 5:
                return render_template("error.html", message="Invalid passing year")

        user = models.User(email=email, password=request.form.get("password"), role="student")
        db.session.add(user)
        db.session.commit()

        student = models.Student(
            user_id=user.id,
            name=request.form.get("name"),
            phone=request.form.get("phone"),
            department=request.form.get("department"),
            course=request.form.get("course"),
            cgpa=float(request.form.get("cgpa")) if request.form.get("cgpa") else None,
            passing_year=int(request.form.get("passing_year")) if request.form.get("passing_year") else None
        )
        db.session.add(student)
        db.session.commit()

        return redirect("/login")

    return render_template("register_student.html")

@app.route("/register_company", methods=['GET', 'POST'])
def register_company():
    if request.method == "POST":
        email = request.form.get("email")

        if models.User.query.filter_by(email=email).first():
            return render_template("error.html", message="Email already registered")

        user = models.User(email=email, password=request.form.get("password"), role="company")
        db.session.add(user)
        db.session.commit()

        company = models.Company(
            user_id=user.id,
            company_name=request.form.get("company_name"),
            hr_contact=request.form.get("hr_contact"),
            website=request.form.get("website"),
            approval_status="pending"
        )

        db.session.add(company)
        db.session.commit()

        return redirect("/login")

    return render_template("register_company.html")

# -------- LOGIN --------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = models.User.query.filter_by(
            email=request.form.get('email')
        ).first()

        if not user or user.password != request.form.get('password'):
            return render_template("login_error.html")

        # BLACKLIST CHECK
        if user.is_blacklisted:
            return render_template("error.html", message="Account is blacklisted")

        session['user_id'] = user.id
        session['role'] = user.role

        if user.role == "student":
            return redirect("/student_dashboard")

        elif user.role == "company":
            company = models.Company.query.filter_by(user_id=user.id).first()

            if company.approval_status == "pending":
                return render_template("company_pending.html")

            elif company.approval_status == "rejected":
                return render_template("company_rejected.html")

            return redirect("/company_dashboard")

        else:
            return redirect("/admin_dashboard")

    return render_template("login.html")

# -------- STUDENT --------

@app.route('/student_dashboard')
def student_dashboard():
    if not is_student():
        return redirect("/login")

    student = get_current_student()
    drives = models.PlacementDrive.query.filter_by(status="approved").all()

    apps = models.Application.query.filter_by(student_id=student.id).all()
    applied = []
    for a in apps:
        drive = db.session.get(models.PlacementDrive, a.drive_id)
        company = db.session.get(models.Company, drive.company_id)
        applied.append({
            "company": company.company_name,
            "drive_title": drive.job_title,
            "status": a.status
        })

    message = session.get('message')
    session['message'] = None

    return render_template("student_dashboard.html", drives=drives, applied=applied, message=message)

@app.route("/apply/<int:drive_id>")
def apply(drive_id):
    if not is_student():
        return redirect("/login")

    student = get_current_student()

    if models.Application.query.filter_by(student_id=student.id, drive_id=drive_id).first():
        return render_template("already_applied.html")

    app_entry = models.Application(
        student_id=student.id,
        drive_id=drive_id,
        application_date=datetime.utcnow(),
        status="Applied"
    )

    db.session.add(app_entry)
    db.session.commit()

    session['message'] = "Successfully applied to this drive!"

    return redirect("/student_dashboard")

@app.route("/my_applications")
def my_applications():
    if not is_student():
        return redirect("/login")

    student = get_current_student()
    apps = models.Application.query.filter_by(student_id=student.id).all()

    data = []
    history = []
    for a in apps:
        drive = db.session.get(models.PlacementDrive, a.drive_id)
        company = db.session.get(models.Company, drive.company_id)

        entry = {
            "company": company.company_name,
            "drive_title": drive.job_title,
            "application_date": a.application_date.strftime("%B %d, %Y") if a.application_date else "-",
            "deadline": format_date(drive.application_deadline),
            "status": a.status
        }
        data.append(entry)
        if a.status in ["Selected", "Rejected"]:
            history.append(entry)

    return render_template("my_applications.html", data=data, history=history)

@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():
    if not is_student():
        return redirect("/login")

    student = get_current_student()

    if request.method == "POST":
        # validate CGPA
        cgpa = request.form.get("cgpa")
        if cgpa:
            cgpa = float(cgpa)
            if cgpa < 0 or cgpa > 10:
                return render_template("error.html", message="CGPA must be between 0 and 10")

        # validate passing year
        passing_year = request.form.get("passing_year")
        if passing_year:
            passing_year = int(passing_year)
            current_year = datetime.utcnow().year
            if passing_year < 1900 or passing_year > current_year + 5:
                return render_template("error.html", message="Invalid passing year")

        student.name = request.form.get("name")
        student.phone = request.form.get("phone")
        student.department = request.form.get("department")
        student.course = request.form.get("course")
        student.cgpa = float(request.form.get("cgpa")) if request.form.get("cgpa") else student.cgpa
        student.passing_year = int(request.form.get("passing_year")) if request.form.get("passing_year") else student.passing_year

        file = request.files.get("resume")
        if file and file.filename:
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            student.resume = f"resumes/{filename}"

        db.session.commit()
        return redirect("/student_dashboard")

    return render_template("edit_profile.html", student=student)

# -------- COMPANY --------

@app.route("/company_dashboard")
def company_dashboard():
    if not is_company():
        return redirect("/login")

    company = get_current_company()
    drives = models.PlacementDrive.query.filter_by(company_id=company.id).all()

    data = []
    for d in drives:
        data.append({
            "id": d.id,
            "title": d.job_title,
            "description": d.job_description,
            "eligibility_criteria": d.eligibility_criteria,
            "deadline": d.application_deadline,
            "status": d.status,
            "count": models.Application.query.filter_by(drive_id=d.id).count()
        })

    return render_template("company_dashboard.html", company=company, data=data)

@app.route("/edit_company_profile", methods=["GET", "POST"])
def edit_company_profile():
    if not is_company():
        return redirect("/login")

    company = get_current_company()

    if request.method == "POST":
        company.company_name = request.form.get("company_name")
        company.hr_contact = request.form.get("hr_contact")
        company.website = request.form.get("website")

        db.session.commit()
        return redirect("/company_dashboard")

    return render_template("company_edit_profile.html", company=company)

@app.route("/create_drive", methods=['GET', 'POST'])
def create_drive():
    if not is_company():
        return redirect("/login")

    company = get_current_company()
    if company.approval_status != "approved":
        return render_template("error.html", message="Your company must be approved before creating drives.")

    if request.method == "POST":
        drive = models.PlacementDrive(
            company_id=company.id,
            job_title=request.form.get("title"),
            job_description=request.form.get("description"),
            eligibility_criteria=request.form.get("eligibility_criteria"),
            application_deadline=request.form.get("deadline"),
            status="pending"
        )

        db.session.add(drive)
        db.session.commit()

        return redirect("/company_dashboard")

    return render_template("create_drive.html")

@app.route("/edit_drive/<int:drive_id>", methods=["GET", "POST"])
def edit_drive(drive_id):
    if not is_company():
        return redirect("/login")
    
    drive = db.session.get(models.PlacementDrive, drive_id)
    company = get_current_company()
    
    # check if the company owns this drive
    if drive.company_id != company.id:
        return render_template("error.html", message="You don't have permission to edit this drive.")

    if request.method == "POST":
        drive.job_title = request.form.get("title")
        drive.job_description = request.form.get("description")
        drive.eligibility_criteria = request.form.get("eligibility_criteria")
        drive.application_deadline = request.form.get("deadline")

        db.session.commit()
        return redirect("/company_dashboard")

    return render_template("edit_drive.html", drive=drive)

@app.route("/delete_drive/<int:drive_id>")
def delete_drive(drive_id):
    if not is_company():
        return redirect("/login")

    drive = db.session.get(models.PlacementDrive, drive_id)
    company = get_current_company()
    
    # check if the company owns this drive
    if drive.company_id != company.id:
        return render_template("error.html", message="You don't have permission to delete this drive.")
    
    # delete applications first
    models.Application.query.filter_by(drive_id=drive_id).delete()
    
    db.session.delete(drive)
    db.session.commit()

    return redirect("/company_dashboard")

@app.route("/close_drive/<int:drive_id>")
def close_drive(drive_id):
    if not is_company():
        return redirect("/login")

    drive = db.session.get(models.PlacementDrive, drive_id)
    company = get_current_company()
    
    # check if the company owns this drive
    if drive.company_id != company.id:
        return render_template("error.html", message="You don't have permission to close this drive.")
    
    drive.status = "closed"
    db.session.commit()

    return redirect("/company_dashboard")

@app.route("/view_applicants/<int:drive_id>")
def view_applicants(drive_id):
    if not is_company():
        return redirect("/login")

    apps = models.Application.query.filter_by(drive_id=drive_id).all()

    data = []
    for a in apps:
        student = db.session.get(models.Student, a.student_id)

        data.append({
            "student_name": student.name,
            "phone": student.phone,
            "app_id": a.id,
            "status": a.status,
            "resume": student.resume
        })

    return render_template("view_applicants.html", data=data)

@app.route("/update_status/<int:app_id>/<string:new_status>")
def update_status(app_id, new_status):
    app_entry = db.session.get(models.Application, app_id)
    app_entry.status = new_status
    db.session.commit()

    drive_id = app_entry.drive_id
    return redirect(f"/view_applicants/{drive_id}")

# -------- ADMIN --------


@app.route("/create_admin")
def create_admin():
    # check if admin already exists
    admin = models.User.query.filter_by(role="admin").first()

    if admin:
        return render_template(
            "admin_status.html",
            message="Admin already exists"
        )

    # create admin
    admin = models.User(
        email="admin@gmail.com",
        password="admin",
        role="admin"
    )

    db.session.add(admin)
    db.session.commit()

    return render_template(
        "admin_status.html",
        message="Admin created successfully"
    )


@app.route("/admin_dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect("/login")

    total_students = models.Student.query.count()
    total_companies = models.Company.query.count()
    total_drives = models.PlacementDrive.query.count()
    total_applications = models.Application.query.count()

    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        total_companies=total_companies,
        total_drives=total_drives,
        total_applications=total_applications
    )

@app.route("/all_students")
def all_students():
    if not is_admin():
        return redirect("/login")

    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = models.Student.query.paginate(page=page, per_page=per_page, error_out=False)
    students = pagination.items

    data = []
    for s in students:
        user = db.session.get(models.User, s.user_id)

        data.append({
            "name": s.name,
            "phone": s.phone,
            "department": s.department,
            "course": s.course,
            "cgpa": s.cgpa,
            "passing_year": s.passing_year,
            "user_id": user.id,
            "is_blacklisted": user.is_blacklisted
        })

    return render_template("all_students.html", students=data, pagination=pagination)

@app.route("/all_companies")
def all_companies():
    if not is_admin():
        return redirect("/login")

    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = models.Company.query.paginate(page=page, per_page=per_page, error_out=False)
    companies = pagination.items

    data = []
    for c in companies:
        user = db.session.get(models.User, c.user_id)

        data.append({
            "id": c.id,
            "company_name": c.company_name,
            "hr_contact": c.hr_contact,
            "website": c.website,
            "approval_status": c.approval_status,
            "user_id": user.id,
            "is_blacklisted": user.is_blacklisted
        })

    return render_template("all_companies.html", companies=data, pagination=pagination)

@app.route("/all_applications")
def all_applications():
    if not is_admin():
        return redirect("/login")

    apps = models.Application.query.all()

    data = []
    for a in apps:
        student = db.session.get(models.Student, a.student_id)
        drive = db.session.get(models.PlacementDrive, a.drive_id)
        company = db.session.get(models.Company, drive.company_id)

        data.append({
            "student_name": student.name,
            "company_name": company.company_name,
            "drive_title": drive.job_title,
            "application_date": a.application_date.strftime("%B %d, %Y") if a.application_date else "-",
            "status": a.status
        })

    return render_template("all_applications.html", applications=data)

# -------- BLACKLIST --------

@app.route("/blacklist_student/<int:user_id>")
def blacklist_student(user_id):
    user = db.session.get(models.User, user_id)
    user.is_blacklisted = True
    db.session.commit()
    return redirect("/all_students")

@app.route("/unblacklist_student/<int:user_id>")
def unblacklist_student(user_id):
    user = db.session.get(models.User, user_id)
    user.is_blacklisted = False
    db.session.commit()
    return redirect("/all_students")

@app.route("/blacklist_company/<int:user_id>")
def blacklist_company(user_id):
    user = db.session.get(models.User, user_id)
    user.is_blacklisted = True
    db.session.commit()
    return redirect("/all_companies")

@app.route("/unblacklist_company/<int:user_id>")
def unblacklist_company(user_id):
    user = db.session.get(models.User, user_id)
    user.is_blacklisted = False
    db.session.commit()
    return redirect("/all_companies")

# -------- ADMIN EDIT / DELETE --------

@app.route("/admin_edit_student/<int:user_id>", methods=["GET", "POST"])
def admin_edit_student(user_id):
    if not is_admin():
        return redirect("/login")

    student = models.Student.query.filter_by(user_id=user_id).first()

    if request.method == "POST":
        student.name = request.form.get("name")
        student.phone = request.form.get("phone")
        student.department = request.form.get("department")
        student.course = request.form.get("course")
        student.cgpa = float(request.form.get("cgpa")) if request.form.get("cgpa") else student.cgpa
        student.passing_year = int(request.form.get("passing_year")) if request.form.get("passing_year") else student.passing_year
        db.session.commit()
        return redirect("/all_students")

    return render_template("admin_edit_student.html", student=student)

@app.route("/admin_delete_student/<int:user_id>")
def admin_delete_student(user_id):
    if not is_admin():
        return redirect("/login")

    student = models.Student.query.filter_by(user_id=user_id).first()
    user = db.session.get(models.User, user_id)

    # delete applications first
    models.Application.query.filter_by(student_id=student.id).delete()
    db.session.delete(student)
    db.session.delete(user)
    db.session.commit()
    return redirect("/all_students")

@app.route("/admin_edit_company/<int:company_id>", methods=["GET", "POST"])
def admin_edit_company(company_id):
    if not is_admin():
        return redirect("/login")

    company = db.session.get(models.Company, company_id)

    if request.method == "POST":
        company.company_name = request.form.get("company_name")
        company.hr_contact = request.form.get("hr_contact")
        company.website = request.form.get("website")
        db.session.commit()
        return redirect("/all_companies")

    return render_template("admin_edit_company.html", company=company)

@app.route("/admin_delete_company/<int:company_id>")
def admin_delete_company(company_id):
    if not is_admin():
        return redirect("/login")

    company = db.session.get(models.Company, company_id)
    user = db.session.get(models.User, company.user_id)

    # delete drives and their applications first
    for drive in models.PlacementDrive.query.filter_by(company_id=company.id).all():
        models.Application.query.filter_by(drive_id=drive.id).delete()
        db.session.delete(drive)

    db.session.delete(company)
    db.session.delete(user)
    db.session.commit()
    return redirect("/all_companies")

# -------- DRIVE DETAILS --------

@app.route("/drive/<int:drive_id>")
def drive_details(drive_id):
    if not is_student():
        return redirect("/login")
    drive = db.session.get(models.PlacementDrive, drive_id)
    return render_template("drive_details.html", drive=drive)

# -------- ADMIN DRIVES --------

@app.route("/admin_drives")
def admin_drives():
    if not is_admin():
        return redirect("/login")
    drives = models.PlacementDrive.query.all()
    return render_template("admin_drives.html", drives=drives)

@app.route("/approve_drive/<int:drive_id>")
def approve_drive(drive_id):
    if not is_admin():
        return redirect("/login")
    drive = db.session.get(models.PlacementDrive, drive_id)
    drive.status = "approved"
    db.session.commit()
    return redirect("/admin_drives")

@app.route("/reject_drive/<int:drive_id>")
def reject_drive(drive_id):
    if not is_admin():
        return redirect("/login")
    drive = db.session.get(models.PlacementDrive, drive_id)
    drive.status = "rejected"
    db.session.commit()
    return redirect("/admin_drives")

@app.route("/approve_company/<int:company_id>")
def approve_company(company_id):
    if not is_admin():
        return redirect("/login")
    company = db.session.get(models.Company, company_id)
    company.approval_status = "approved"
    db.session.commit()
    return redirect("/all_companies")

@app.route("/reject_company/<int:company_id>")
def reject_company(company_id):
    if not is_admin():
        return redirect("/login")
    company = db.session.get(models.Company, company_id)
    company.approval_status = "rejected"
    db.session.commit()
    return redirect("/all_companies")

@app.route("/search_students")
def search_students():
    if not is_admin():
        return redirect("/login")
    q = request.args.get("q", "").strip()
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # get all students and filter manually
    all_students = models.Student.query.all()
    filtered = []
    for s in all_students:
        user = db.session.get(models.User, s.user_id)
        if q == "" or (q.lower() in (s.name or "").lower() or
            q.lower() in (s.phone or "").lower() or
            q == str(user.id)):
            filtered.append({
                "name": s.name, "phone": s.phone, "department": s.department,
                "course": s.course, "cgpa": s.cgpa, "passing_year": s.passing_year,
                "user_id": user.id, "is_blacklisted": user.is_blacklisted
            })
    
    # manual pagination for search results
    total = len(filtered)
    start = (page - 1) * per_page
    end = start + per_page
    students_page = filtered[start:end]
    
    # create simple pagination object
    class Pagination:
        def __init__(self, page, per_page, total):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page
            self.items = students_page
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1
            self.next_num = page + 1
    
    pagination = Pagination(page, per_page, total)
    
    return render_template("all_students.html", students=students_page, pagination=pagination)

@app.route("/search_companies")
def search_companies():
    if not is_admin():
        return redirect("/login")
    q = request.args.get("q", "").strip()
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # get all companies and filter
    all_companies = models.Company.query.all()
    filtered = []
    for c in all_companies:
        if q == "" or q.lower() in (c.company_name or "").lower():
            user = db.session.get(models.User, c.user_id)
            filtered.append({
                "id": c.id, "company_name": c.company_name, "hr_contact": c.hr_contact,
                "website": c.website, "approval_status": c.approval_status,
                "user_id": user.id, "is_blacklisted": user.is_blacklisted
            })
    
    # manual pagination for search results
    total = len(filtered)
    start = (page - 1) * per_page
    end = start + per_page
    companies_page = filtered[start:end]
    
    # create simple pagination object
    class Pagination:
        def __init__(self, page, per_page, total):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page
            self.items = companies_page
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1
            self.next_num = page + 1
    
    pagination = Pagination(page, per_page, total)
    
    return render_template("all_companies.html", companies=companies_page, pagination=pagination)

# -------- LOGOUT --------

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------- INIT --------

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)