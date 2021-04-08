from Worker import Worker
from threading import Thread
from flask import Flask, request, Response, json

worker = Worker()
app = Flask(__name__)

#TODO thread for threshold update
#TODO sleep history endpoint

""" HTTP SERVER PART """

def process_incomming(message):
    if ("activity" in message and message["activity"]):
        worker.set_active_flag()

    if ("heartrate" in message):
        worker.update_hr(message["heartrate"])

@app.route('/value_update', methods=['POST'])
def value_update():
    response = Response(json.dumps({"status": "ok"}), mimetype='application/json')
    response.status_code = 200

    if (request.is_json):
        request_data = request.get_json()

        try: 
            process_incomming(request_data)
        except Exception:
            response = Response(json.dumps({"status": "error", "message": "processing error"}), mimetype='application/json')
            response.status_code = 500

    else:
        response = Response(json.dumps({"status": "error", "message": "cannot parse request"}), mimetype='application/json')
        response.status_code = 400
    
    return response

#@app.route('/sleep_history', methods=['GET'])
#def sleep_history():
    

if __name__ == "__main__":
    try:
        worker.run()
        flask_thread = Thread(target=app.run, kwargs={'debug': True, 'use_reloader': False, 'host': "0.0.0.0"})
        flask_thread.start()
    except KeyboardInterrupt:
        flask_thread.join()
        tl.stop()
