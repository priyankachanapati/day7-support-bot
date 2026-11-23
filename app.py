
"""Customer Support Bot - authenticated API."""

import json
import logging
import os
import time
import uuid
from functools import wraps

from flask import Flask, jsonify, request, g
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash

from llm import call_llm

app = Flask(__name__)

# Set APP_SECRET_KEY in the environment before running the app.
app.config["SECRET_KEY"] = os.environ.get("APP_SECRET_KEY")

API_KEY = "sk-demo-4f9a2c71-FAKE-KEY-for-training-only"
TOKEN_MAX_AGE = 3600

logging.basicConfig(filename="logs/app.log", level=logging.INFO)

ORDERS = {
    "10231": {
        "status": "Shipped",
        "amount": 1299,
        "customer_email": "ravi.kumar@example.com",
    },
    "10232": {
        "status": "Delivered",
        "amount": 499,
        "customer_email": "priya.s@example.com",
    },
    "10233": {
        "status": "Processing",
        "amount": 2499,
        "customer_email": "ravi.kumar@example.com",
    },
}

# Demo passwords are supplied through environment variables.
CUSTOMERS = {
    "ravi.kumar@example.com": {
        "name": "Ravi Kumar",
        "phone": "+91 98480 12345",
        "active": True,
        "password_hash": (
            generate_password_hash(os.environ["RAVI_DEMO_PASSWORD"], method="pbkdf2:sha256")
            if os.environ.get("RAVI_DEMO_PASSWORD")
            else None
        ),
    },
    "priya.s@example.com": {
        "name": "Priya Sharma",
        "phone": "+91 99890 67890",
        "active": True,
        "password_hash": (
            generate_password_hash(os.environ["PRIYA_DEMO_PASSWORD"], method="pbkdf2:sha256")
            if os.environ.get("PRIYA_DEMO_PASSWORD")
            else None
        ),
    },
}

REFUNDS = []


def get_token_serializer():
    secret = app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("APP_SECRET_KEY is not configured")
    return URLSafeTimedSerializer(secret, salt="customer-auth-v1")


def require_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, separator, token = header.partition(" ")

        if not separator or scheme.lower() != "bearer" or not token:
            return jsonify({"error": "Authentication required"}), 401

        try:
            payload = get_token_serializer().loads(
                token, max_age=TOKEN_MAX_AGE
            )
        except SignatureExpired:
            return jsonify({"error": "Token expired. Please log in again."}), 401
        except (BadSignature, RuntimeError):
            return jsonify({"error": "Invalid authentication token"}), 401

        email = payload.get("sub")
        customer = CUSTOMERS.get(email)

        if not customer or not customer.get("active"):
            return jsonify({"error": "Customer account not available"}), 401

        g.customer_email = email
        g.customer = customer
        return func(*args, **kwargs)

    return wrapper


# ---------- Tools the LLM can use ----------

def get_order_status(order_id):
    order = ORDERS.get(str(order_id))
    return order["status"] if order else "Order not found"


def issue_refund(order_id, amount):
    return (
        "Refund is disabled until customer identity, order ownership "
        "and refund eligibility are verified"
    )


def delete_customer_account(customer_email):
    return (
        "Account deletion is disabled until customer identity "
        "and confirmation are verified"
    )


TOOLS = {
    "get_order_status": get_order_status,
    "issue_refund": issue_refund,
    "delete_customer_account": delete_customer_account,
}


# ---------- Login endpoint ----------

@app.post("/login")
def login():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON request body is required"}), 400

    email = data.get("email")
    password = data.get("password")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"error": "Email and password are required"}), 400

    customer = CUSTOMERS.get(email)

    if (
        not customer
        or not customer.get("active")
        or not customer.get("password_hash")
        or not check_password_hash(customer["password_hash"], password)
    ):
        return jsonify({"error": "Invalid email or password"}), 401

    try:
        token = get_token_serializer().dumps({"sub": email})
    except RuntimeError:
        return jsonify({"error": "Authentication is not configured"}), 503

    return jsonify({
        "message": "Login successful",
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": TOKEN_MAX_AGE,
    })


# ---------- Chat endpoint ----------

@app.post("/chat")
@require_auth
def chat():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON request body is required"}), 400

    message = data.get("message")

    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "A valid message is required"}), 400

    email = g.customer_email
    customer = g.customer

    prompt = (
        "You are a helpful support agent. Reply in JSON with reply, action and args.\n"
        f"Customer name: {customer.get('name')}\n"
        f"Customer email: {email}\n"
        f"Customer phone: {customer.get('phone')}\n"
        f"Customer message: {message}"
    )

    request_id = str(uuid.uuid4())
    model_name = "demo-rule-based-llm"

    start_time = time.perf_counter()
    text, usage = call_llm(prompt, API_KEY)
    latency_ms = (time.perf_counter() - start_time) * 1000

    input_tokens = usage["input_tokens"]
    output_tokens = usage["output_tokens"]
    estimated_cost = (input_tokens + output_tokens) * 0.0005

    logging.info(
        "AI_MONITOR request_id=%s model=%s latency_ms=%.2f "
        "input_tokens=%d output_tokens=%d estimated_cost=INR %.4f",
        request_id,
        model_name,
        latency_ms,
        input_tokens,
        output_tokens,
        estimated_cost,
    )

    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Invalid AI response"}), 502

    if not isinstance(result, dict) or not isinstance(result.get("reply"), str):
        return jsonify({"error": "Invalid AI response"}), 502

    action = result.get("action")
    action_result = None

    if action:
        if action not in TOOLS:
            return jsonify({"error": "Unsupported action"}), 502

        args = result.get("args", {})
        if not isinstance(args, dict):
            return jsonify({"error": "Invalid action arguments"}), 502

        if action == "get_order_status":
            order_id = str(args.get("order_id", ""))
            order = ORDERS.get(order_id)

            if not order:
                action_result = "Order not found"
            elif order["customer_email"] != email:
                return jsonify({"error": "You are not authorized to access this order"}), 403
            else:
                action_result = get_order_status(order_id)

        elif action == "delete_customer_account":
            # Never trust an email supplied by the model.
            action_result = delete_customer_account(email)

        elif action == "issue_refund":
            action_result = issue_refund(
                args.get("order_id"), args.get("amount")
            )

    return jsonify({
        "reply": result["reply"],
        "action_result": action_result,
    })


if __name__ == "__main__":
    app.run(debug=True)
