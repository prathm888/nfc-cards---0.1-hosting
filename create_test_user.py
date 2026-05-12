from app import create_app
from models import db, User

app = create_app()
with app.app_context():
    # Create a test employee if they don't exist
    emp = User.query.filter_by(username='test_emp').first()
    if not emp:
        emp = User(
            username='test_emp', 
            email='test@samartha.in', 
            name='Rajesh Kumar', 
            emp_id='SA-101', 
            phone='+91 98765 43210',
            business_name='Samartha Ayurveda',
            designation='Senior Health Consultant',
            address='123 Wellness Avenue, Mumbai'
        )
        emp.set_password('password123')
        db.session.add(emp)
        db.session.commit()
        print("Employee account 'test_emp' created successfully.")
    else:
        print("Employee 'test_emp' already exists.")
