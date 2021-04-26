import os
import math
from threading import Timer
from datetime import datetime
from statistics import median
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from numpy import percentile

""" configuration """

DB_DATABASE          = os.getenv("DB_DATABASE", "sleep_detector")
DB_USERNAME          = os.getenv("DB_USERNAME", "postgres")
DB_PASSWORD          = os.getenv("DB_PASSWORD", "postgres")
DB_HOST              = os.getenv("DB_HOST", "localhost")
DB_PORT              = int(os.getenv("DB_PORT", "5555"))
HR_VALID_LOW         = int(os.getenv("HR_VALID_LOW", "40"))
HR_VALID_HIGH        = int(os.getenv("HR_VALID_HIGH", "80"))
WORKER_TICK_INTERVAL = int(os.getenv("WORKER_TICK_INTERVAL", "120"))
MINIMAL_SLEEP_HOURS  = int(os.getenv("MINIMAL_SLEEP_HOURS", "3"))
ACTIVE_FLAG_TIMEOUT  = int(os.getenv("ACTIVE_FLAG_TIMEOUT", "300"))
HR_THRESHOLD_SAMPLES = int(os.getenv("HR_THRESHOLD_SAMPLES", "7"))
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "http://192.168.100.33:8123/api/webhook/sleep_detect")

class Worker:
    def __init__(self):
        self.heartrate_threshold    = 0
        self.hr_arr                 = []
        self.sleep_start            = None
        self.active_flag            = False
        self.reset_flag_thread      = None
        self.sleep_sent             = False
        self.db_connection_settings = {
            'dbname':     DB_DATABASE,
            'user':       DB_USERNAME,
            'password':   DB_PASSWORD,
            'host':       DB_HOST,
            'port':       DB_PORT
        }
        self._create_db_tables()

    def _reset_active_flag(self):
        self.active_flag = False
        print("ACTIVE FLAG RESET", self.active_flag, datetime.now())

    def set_active_flag(self):
        self.active_flag = True

        if self.reset_flag_thread:
            self.reset_flag_thread.cancel()

        self.reset_flag_thread = Timer(ACTIVE_FLAG_TIMEOUT, self._reset_active_flag)
        self.reset_flag_thread.start()

        print("ACTIVE FLAG SET", self.active_flag, datetime.now())

    def _create_db_tables(self):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS heartrate ("\
                    "timestamp TIMESTAMPTZ NOT NULL,"\
                    "value smallint NOT NULL);"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS sleep ("\
                    "sleep_start TIMESTAMPTZ NOT NULL,"\
                    "sleep_end TIMESTAMPTZ NOT NULL,"\
                    "heartrate smallint NOT NULL);"
                )
                cursor.execute(
                    "SELECT create_hypertable('heartrate', 'timestamp', if_not_exists => TRUE);"
                )
                conn.commit()
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def get_sleep_history(self, count):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cursor.execute("SELECT * FROM sleep ORDER BY sleep_start DESC LIMIT %s;", (count,))
                sleep_history = cursor.fetchall()
                return sleep_history
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def _get_heartrate_threshold(self):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cursor.execute(
                    "SELECT heartrate FROM sleep ORDER BY sleep_start DESC LIMIT %s;", 
                    (HR_THRESHOLD_SAMPLES,)
                )
                heartrates = [row["heartrate"] for row in cursor.fetchall()]
                return max(heartrates, default=0)
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def _get_sleep_heartrate(self, sleep_start, sleep_end):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cursor.execute(
                    "SELECT value FROM heartrate WHERE timestamp >= %s AND timestamp <= %s;",
                    (sleep_start, sleep_end)
                )
                values = [row["value"] for row in cursor.fetchall()]
                return values
            except (psycopg2.Error) as error:
                print(error.pgerror)
    
    def _save_sleep(self, sleep_start, sleep_end, hr):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO sleep (sleep_start, sleep_end, heartrate) VALUES (%s, %s, %s);", 
                    (sleep_start, sleep_end, hr)
                )
                conn.commit()
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def _save_heartrate(self, timestamp, value):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO heartrate (timestamp, value) VALUES (%s, %s);", 
                    (timestamp, value)
                )
                conn.commit()
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def _calc_heartrate(self):
        if self.active_flag:
            return -1
        if not self.hr_arr:
            return 0

        heartrate = median(self.hr_arr)
        self.hr_arr = []
        return heartrate

    def _track_sleep(self, heartrate):
        if heartrate > 0 and not self.sleep_start:
            self.sleep_start = datetime.now()
            print("STARTING SLEEP", datetime.now())
        elif heartrate <=0 and self.sleep_start:
            print("ENDING SLEEP", datetime.now())
            sleep_end = datetime.now()

            if (sleep_end - self.sleep_start).seconds // 60 >= MINIMAL_SLEEP_HOURS:
                sleep_heartrates = self._get_sleep_heartrate(self.sleep_start, sleep_end)
                sleep_heartrate = math.ceil(percentile(sleep_heartrates, 95))
                print("SAVING SLEEP", sleep_heartrate, datetime.now())
                self._save_sleep(self.sleep_start, sleep_end, sleep_heartrate)
                self._get_heartrate_threshold()
            
            self.sleep_start   = None

    def _check_for_sleep(self, heartrate):
        print("CHECKING FOR SLEEP", "HEARTRATE:", heartrate, "THRESHOLD:", self.heartrate_threshold)
        return not self.active_flag and 0 < heartrate <= self.heartrate_threshold

    def _tick(self):
        heartrate = self._calc_heartrate()
        self._track_sleep(heartrate)
        sleep = self._check_for_sleep(heartrate)
        self._save_heartrate(datetime.now(), heartrate)

        print("SLEEP", sleep, datetime.now())
        if sleep and not self.sleep_sent:
            requests.post(
                WEBHOOK_URL, 
                json={"sleep": True}, 
                headers={"Content-Type": "application/json"}
            )
            self.sleep_sent = True
            print("SLEEP DETECT SENT")
        elif not sleep:
            self.sleep_sent = False

        Timer(WORKER_TICK_INTERVAL, self._tick).start()

    def update_hr(self, heartrate):
        if HR_VALID_LOW <= heartrate <= HR_VALID_HIGH:
            self.hr_arr.append(heartrate)

    def run(self):
        self._get_heartrate_threshold()
        self._tick()
