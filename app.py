import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

load_dotenv()

app = Flask(__name__)

client = Client(
    os.environ["TWILIO_ACCOUNT_SID"],
    os.environ["TWILIO_AUTH_TOKEN"],
)
TWILIO_PHONE = os.environ["TWILIO_PHONE_NUMBER"]
TWILIO_WHATSAPP = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sms", methods=["POST"])
def send_sms():
    data = request.json
    try:
        msg = client.messages.create(
            from_=TWILIO_PHONE,
            to=data["to"],
            body=data["body"],
        )
        return jsonify({"sid": msg.sid, "status": msg.status})
    except TwilioRestException as e:
        return jsonify({"error": e.msg, "code": e.code}), 400


@app.route("/api/call", methods=["POST"])
def make_call():
    data = request.json
    try:
        call = client.calls.create(
            from_=TWILIO_PHONE,
            to=data["to"],
            twiml=f'<Response><Say language="{data.get("language", "en-US")}">{data["message"]}</Say></Response>',
        )
        return jsonify({"sid": call.sid, "status": call.status})
    except TwilioRestException as e:
        return jsonify({"error": e.msg, "code": e.code}), 400


@app.route("/api/voice-message", methods=["POST"])
def send_voice_message():
    """Call the number and deliver a longer spoken message, then hang up."""
    data = request.json
    language = data.get("language", "en-US")
    twiml = (
        f'<Response>'
        f'<Say language="{language}">{data["message"]}</Say>'
        f'<Pause length="1"/>'
        f'<Say language="{language}">This was an automated voice message. Goodbye.</Say>'
        f'</Response>'
    )
    try:
        call = client.calls.create(
            from_=TWILIO_PHONE,
            to=data["to"],
            twiml=twiml,
        )
        return jsonify({"sid": call.sid, "status": call.status})
    except TwilioRestException as e:
        return jsonify({"error": e.msg, "code": e.code}), 400


@app.route("/api/whatsapp", methods=["POST"])
def send_whatsapp():
    data = request.json
    try:
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP,
            to=f'whatsapp:{data["to"]}',
            body=data["body"],
        )
        return jsonify({"sid": msg.sid, "status": msg.status})
    except TwilioRestException as e:
        return jsonify({"error": e.msg, "code": e.code}), 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)
