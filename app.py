from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import date, datetime, timedelta
import os

# Configure Flask app with explicit paths for serverless environments
# Get the directory where this file is located
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, 'templates')

# Ensure template directory exists, fallback to default if not
if os.path.exists(template_dir):
    app = Flask(__name__, template_folder=template_dir)
else:
    # Fallback to default Flask template location
    app = Flask(__name__)

app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'super-secret-key-change-me')


# ---------- Helper functions ----------

def compute_bmi(weight_kg, height_cm):
    height_m = height_cm / 100.0
    if height_m <= 0:
        return 0.0
    return round(weight_kg / (height_m ** 2), 2)


def bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight"
    elif bmi < 25:
        return "Normal"
    elif bmi < 30:
        return "Overweight"
    else:
        return "Obese"


def protein_for_level(level, weight_kg):
    if level == "beginner":
        factor = 1.0
    elif level == "intermediate":
        factor = 1.5
    else:  # advanced
        factor = 2.0
    return round(weight_kg * factor, 1)


def water_target_liters(weight_kg):
    # simple rule: 35 ml per kg
    return round(weight_kg * 0.035, 1)


def step_target_for_level(level):
    if level == "beginner":
        return 6000
    elif level == "intermediate":
        return 8000
    else:
        return 10000


def get_period_stats(logs, start_date, end_date):
    stats = {"water": 0.0, "steps": 0, "sleep": 0.0, "protein": 0.0, "challenges": 0}
    for log in logs:
        d = datetime.strptime(log["date"], "%Y-%m-%d").date()
        if start_date <= d <= end_date:
            stats["water"] += log.get("water", 0.0)
            stats["steps"] += log.get("steps", 0)
            stats["sleep"] += log.get("sleep", 0.0)
            stats["protein"] += log.get("protein", 0.0)
            stats["challenges"] += len(log.get("challenges", []))
    for k in ["water", "sleep", "protein"]:
        stats[k] = round(stats[k], 1)
    return stats


def ensure_logs_mapping():
    """
    Make sure we have session['logs_by_email'] (dict).
    If old session only has session['logs'] list, migrate it
    to logs_by_email under current plan's email.
    """
    logs_by_email = session.get("logs_by_email")
    if logs_by_email is None:
        logs_by_email = {}
        old_logs = session.get("logs", [])
        current_plan = session.get("current_plan")
        if current_plan and old_logs:
            key = current_plan["email"].lower()
            logs_by_email[key] = old_logs
        session["logs_by_email"] = logs_by_email
        session.pop("logs", None)
    return logs_by_email


# ---------- Routes ----------

@app.route("/", methods=["GET", "POST"])
def index():
    if "plans" not in session:
        session["plans"] = []

    # always ensure mapping exists
    ensure_logs_mapping()

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        weight = float(request.form.get("weight", 0) or 0)
        height = float(request.form.get("height", 0) or 0)
        level = request.form.get("level", "beginner")

        bmi = compute_bmi(weight, height)
        category = bmi_category(bmi)
        protein = protein_for_level(level, weight)
        water = water_target_liters(weight)
        steps = step_target_for_level(level)

        plan = {
            "email": email,
            "weight": weight,
            "height_cm": height,
            "level": level,
            "bmi": bmi,
            "bmi_category": category,
            "protein_target": protein,
            "water_target": water,
            "step_target": steps,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        plans = session.get("plans", [])
        plans.append(plan)
        session["plans"] = plans

        # 🔑 identify user by email (case-insensitive)
        email_key = email.lower()
        logs_by_email = ensure_logs_mapping()

        # If this email already has logs -> old member, KEEP their history.
        # If not, new user -> start with empty list (fresh summary).
        if email_key not in logs_by_email:
            logs_by_email[email_key] = []  # new user → fresh logs

        session["logs_by_email"] = logs_by_email
        session["current_plan"] = plan
        session["current_email"] = email_key

        return redirect(url_for("dashboard"))

    current_plan = session.get("current_plan")
    return render_template(
        "main.html",
        page="index",
        current_plan=current_plan,
        date=date
    )


@app.route("/dashboard")
def dashboard():
    plan = session.get("current_plan")
    if not plan:
        return redirect(url_for("index"))

    logs_by_email = ensure_logs_mapping()
    email_key = plan["email"].lower()
    logs = logs_by_email.get(email_key, [])

    today = date.today()
    today_stats = get_period_stats(logs, today, today)

    week_start = today - timedelta(days=6)
    week_stats = get_period_stats(logs, week_start, today)

    month_start = today.replace(day=1)
    month_stats = get_period_stats(logs, month_start, today)

    challenges = [
        "Drink at least 2.5L of water",
        "Walk an extra 1,000 steps",
        "Sleep at least 7 hours",
        "Avoid sugary drinks today",
        "Complete a 20-minute workout",
    ]

    return render_template(
        "main.html",
        page="dashboard",
        plan=plan,
        today_stats=today_stats,
        week_stats=week_stats,
        month_stats=month_stats,
        challenges=challenges,
        date=date,
    )


@app.route("/log-daily", methods=["POST"])
def log_daily():
    plan = session.get("current_plan")
    if not plan:
        return redirect(url_for("index"))

    logs_by_email = ensure_logs_mapping()
    email_key = plan["email"].lower()
    logs = logs_by_email.get(email_key, [])

    log_date = request.form.get("log_date") or date.today().strftime("%Y-%m-%d")
    try:
        water = float(request.form.get("water") or 0)
    except ValueError:
        water = 0.0
    try:
        steps = int(request.form.get("steps") or 0)
    except ValueError:
        steps = 0
    try:
        sleep = float(request.form.get("sleep") or 0)
    except ValueError:
        sleep = 0.0
    try:
        protein = float(request.form.get("protein") or 0)
    except ValueError:
        protein = 0.0

    challenges_done = request.form.getlist("challenges")

    log = {
        "date": log_date,
        "water": water,
        "steps": steps,
        "sleep": sleep,
        "protein": protein,
        "challenges": challenges_done,
    }

    logs.append(log)
    logs_by_email[email_key] = logs
    session["logs_by_email"] = logs_by_email

    return redirect(url_for("dashboard"))


@app.route("/assistant", methods=["POST"])
def assistant():
    data = request.get_json() or {}
    message = (data.get("message") or "").lower()

    plan = session.get("current_plan")
    reply = "I'm your AI fitness assistant. Ask me about BMI, water, steps, sleep or protein."

    if plan:
        if "bmi" in message:
            reply = (
                f"Your BMI is {plan['bmi']} which is in the "
                f"'{plan['bmi_category']}' range."
            )
        elif "protein" in message:
            reply = f"Your daily protein target is {plan['protein_target']} g."
        elif "water" in message:
            reply = f"Try to drink around {plan['water_target']} liters of water today."
        elif "steps" in message:
            reply = f"Your daily step goal is {plan['step_target']} steps."
        elif "sleep" in message:
            reply = (
                "Aim for 7–9 hours of sleep per night for recovery and performance."
            )
        elif "meal" in message or "diet" in message:
            reply = (
                "Base your meals on lean protein, complex carbs, healthy fats "
                "and plenty of vegetables. Keep sugar and deep-fried foods low."
            )

    return jsonify({"reply": reply})


@app.route("/started-plans")
def started_plans():
    plans = session.get("plans", [])
    return render_template(
        "main.html",
        page="started_plans",
        plans=plans,
        date=date,
    )


@app.route("/delete-plan/<int:plan_index>", methods=["POST"])
def delete_plan(plan_index):
    plans = session.get("plans", [])
    if 0 <= plan_index < len(plans):
        plan_to_delete = plans[plan_index]
        email_key = plan_to_delete["email"].lower()

        # remove plan
        del plans[plan_index]
        session["plans"] = plans

        # optional: also remove logs for that email
        logs_by_email = ensure_logs_mapping()
        if email_key in logs_by_email:
            del logs_by_email[email_key]
        session["logs_by_email"] = logs_by_email

        # if it was current plan, clear it
        current = session.get("current_plan")
        if current and current["email"].lower() == email_key:
            session["current_plan"] = None

    return redirect(url_for("started_plans"))


if __name__ == "__main__":
    app.run(debug=True)
