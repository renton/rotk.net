from flask import render_template, request, url_for, redirect, flash, current_app, abort
from flask_login import login_user, logout_user, login_required, current_user

from app import db, limiter
from app.models import User
from app.blueprints.auth.forms import (
    LoginForm,
    RegistrationForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    ChangePasswordForm,
    ChangeEmailForm,
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
    # Public sign-up is disabled until we actually want non-admin users.
    # Admins are created out-of-band via `flask make-admin` or the admin
    # panel. The body below is kept (but unreachable) so re-enabling is
    # just deleting the abort line. `is_administrator=False` is set
    # explicitly so a future regression can't accidentally promote
    # registrants — `User.is_administrator` already defaults to False on
    # the model, but stating it here makes the intent unambiguous.
    abort(404)

    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data.lower(),
            username=form.username.data,
            confirmed=False,
            is_administrator=False,
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


@auth.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour; 20 per day", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user is not None:
            token = user.generate_reset_token()
            send_email(
                to=user.email,
                subject='Reset your password',
                template='auth/email/reset_password',
                user=user,
                token=token,
            )
        # Always show the same response, whether or not the email matched a
        # registered user. Leaking that distinction would help account
        # enumeration.
        flash('If that email is registered, a reset link has been sent.')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html', form=form)


@auth.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.verify_password(form.old_password.data):
            flash('Current password is incorrect.')
        else:
            current_user.password = form.password.data
            db.session.add(current_user)
            db.session.commit()
            flash('Your password has been updated.')
            return redirect(url_for('main.index'))
    return render_template('auth/change_password.html', form=form)


@auth.route('/change-email', methods=['GET', 'POST'])
@login_required
def change_email_request():
    form = ChangeEmailForm()
    if form.validate_on_submit():
        if not current_user.verify_password(form.password.data):
            flash('Password is incorrect.')
        else:
            new_email = form.email.data.lower()
            token = current_user.generate_email_change_token(new_email)
            send_email(
                to=new_email,
                subject='Confirm your new email',
                template='auth/email/change_email',
                user=current_user,
                token=token,
            )
            flash('A confirmation link has been sent to the new email address.')
            return redirect(url_for('main.index'))
    return render_template('auth/change_email.html', form=form)


@auth.route('/change-email/<token>')
@login_required
def change_email_confirm(token):
    expiration = current_app.config['EMAIL_CHANGE_TOKEN_TTL']
    if current_user.change_email(token, expiration=expiration):
        db.session.commit()
        flash('Your email address has been updated.')
    else:
        flash('That email-change link is invalid or has expired.')
    return redirect(url_for('main.index'))


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        expiration = current_app.config['RESET_TOKEN_TTL']
        if User.reset_password(token, form.password.data, expiration=expiration):
            db.session.commit()
            flash('Your password has been updated. You can log in now.')
            return redirect(url_for('auth.login'))
        flash('That reset link is invalid or has expired.')
        return redirect(url_for('auth.forgot_password'))

    return render_template('auth/reset_password.html', form=form)
