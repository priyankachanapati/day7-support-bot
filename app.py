"""Customer Support Bot (Day 7 Challenge: risk review).

A small Flask app. A customer sends a message, the LLM decides on a reply
and an action, and the app carries out the action.
"""
import json
import logging
import time
import uuid 

from flask import Flask, jsonify, request

from llm import call_llm

app = Flask(__name__)

API_KEY = "sk-demo-4f9a2c71-FAKE-KEY-for-training-only"

logging.basicConfig(filename="logs/app.log", level=logging.INFO)

ORDERS = {
    "10231": {"status": "Shipped", "amount": 1299},
    "10232": {"status": "Delivered", "amount": 499},
    "10233": {"status": "Processing", "amount": 2499},
}
CUSTOMERS = {
    "ravi.kumar@example.com": {"name": "Ravi Kumar", "phone": "+91 98480 12345", "active": True},
    "priya.s@example.com": {"name": "Priya Sharma", "phone": "+91 99890 67890", "active": True},
}
REFUNDS = []


# ---------- Tools the LLM can use ----------

def get_order_status(order_id):
    order = ORDERS.get(order_id)
    return order["status"] if order else "Order not found"


def issue_refund(order_id, amount):
    return "Refund is disabled until customer identity, order ownership and refund eligibility are verified"

def delete_customer_account(customer_email):
    return "Account deletion is disabled until customer identity and confirmation are verified"


TOOLS = {
    "get_order_status": get_order_status,
    "issue_refund": issue_refund,
    "delete_customer_account": delete_customer_account,
}


# ---------- Chat endpoint ----------



@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    email = data.get("customer_email", "")
    message = data.get("message", "")
    customer = CUSTOMERS.get(email, {})

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

    result = json.loads(text)

    action = result.get("action")
    action_result = None

    if action:
        args = result.get("args", {})
        if args.get("customer_email") == "from_request":
            args["customer_email"] = email

        action_result = TOOLS[action](**args)

    return jsonify({
        "reply": result["reply"],
        "action_result": action_result
    })


if __name__ == "__main__":
    app.run(debug=True)
