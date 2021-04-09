from threading import Thread
from flask import Flask, request, make_response, json
from worker import Worker

worker = Worker()
app = Flask(__name__)

@app.route('/value_update', methods=['POST'])
def value_update():
    if not request.is_json:
        return make_response(
            json.dumps({"status": "error", "message": "cannot parse request"}),
            400,
            {"Content-Type": "application/json"}
        )

    data = request.get_json()

    if "activity" in data and data["activity"]:
        worker.set_active_flag()

    if "heartrate" in data:
        worker.update_hr(data["heartrate"])

    return make_response(
        json.dumps({"status": "ok"}),
        200,
        {"Content-Type": "application/json"}
    )

@app.route('/sleep_history', methods=['GET'])
def sleep_history():
    count = request.args.get('count', default=10, type=int)
    result = worker.get_sleep_history(count)

    return make_response(json.dumps(result), 200, {"Content-Type": "application/json"})

worker.run()
Thread(
    target=app.run,
    kwargs={'debug': True, 'use_reloader': False, 'host': "0.0.0.0"}
).start()

