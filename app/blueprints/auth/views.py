from flask import render_template, request, url_for, redirect, flash
from flask_login import login_user, logout_user, login_required
from app.blueprints.auth.forms import LoginForm

from app import limiter
from app.models import User
from . import auth

@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user is not None and user.verify_password(form.password.data):
            login_user(user, form.remember_me.data)
            next = request.args.get('next')
            if next is None or not next.startswith('/'):
                next = url_for('main.index')
            return redirect(next)
        flash('Invalid email or password.')
    return render_template('auth/login.html', form=form)

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('main.index'))