from flask import render_template, request, url_for, redirect, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app import db, limiter
from app.models import User
from app.blueprints.auth.forms import (
    LoginForm,
    RegistrationForm,
)
from app.blueprints.auth.emails import send_email
from . import auth


@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user is not None and user.verify_password(form.password.data):
            login_user(user, form.remember_me.data)
            next_url = request.args.get('next')
            if next_url is None or not next_url.startswith('/'):
                next_url = url_for('main.index')
            return redirect(next_url)
        flash('Invalid email or password.')
    return render_template('auth/login.html', form=form)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('main.index'))


@auth.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour; 20 per day", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data.lower(),
            username=form.username.data,
            confirmed=False,
        )
        user.password = form.password.data
        db.session.add(user)
        db.session.commit()

        token = user.generate_confirmation_token()
        send_email(
            to=user.email,
            subject='Confirm your account',
            template='auth/email/confirm',
            user=user,
            token=token,
        )
        flash('A confirmation link has been sent to your email.')
        login_user(user)
        return redirect(url_for('auth.unconfirmed'))

    return render_template('auth/register.html', form=form)


@auth.route('/confirm/<token>')
@login_required
def confirm(token):
    if current_user.confirmed:
        return redirect(url_for('main.index'))
    expiration = current_app.config['CONFIRM_TOKEN_TTL']
    if current_user.confirm(token, expiration=expiration):
        db.session.commit()
        flash('You have confirmed your account. Thanks!')
    else:
        flash('The confirmation link is invalid or has expired.')
    return redirect(url_for('main.index'))


@auth.route('/resend-confirmation')
@login_required
@limiter.limit("3 per hour")
def resend_confirmation():
    if current_user.confirmed:
        return redirect(url_for('main.index'))
    token = current_user.generate_confirmation_token()
    send_email(
        to=current_user.email,
        subject='Confirm your account',
        template='auth/email/confirm',
        user=current_user,
        token=token,
    )
    flash('A new confirmation link has been sent to your email.')
    return redirect(url_for('auth.unconfirmed'))


@auth.route('/unconfirmed')
def unconfirmed():
    if current_user.is_anonymous or current_user.confirmed:
        return redirect(url_for('main.index'))
    return render_template('auth/unconfirmed.html')
