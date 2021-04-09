import os
from threading import Timer
from datetime import datetime
from statistics import median
import psycopg2
from psycopg2.extras import RealDictCursor

""" configuration """

DB_DATABASE          = os.getenv("DB_DATABASE", "sleep_detector")
DB_USERNAME          = os.getenv("DB_USERNAME", "postgres")
DB_PASSWORD          = os.getenv("DB_PASSWORD", "postgres")
DB_HOST              = os.getenv("DB_HOST", "localhost")
DB_PORT              = int(os.getenv("DB_PORT", "5555"))
HR_VALID_LOW         = int(os.getenv("HR_VALID_LOW", "40"))
HR_VALID_HIGH        = int(os.getenv("HR_VALID_HIGH", "90"))
WORKER_TICK_INTERVAL = int(os.getenv("WORKER_TICK_INTERVAL", "60"))
MINIMAL_SLEEP_HOURS  = int(os.getenv("MINIMAL_SLEEP_HOURS", "3"))
ACTIVE_FLAG_TIMEOUT  = int(os.getenv("ACTIVE_FLAG_TIMEOUT", "120"))
HR_THRESHOLD_SAMPLES = int(os.getenv("HR_THRESHOLD_SAMPLES", "7"))

class Worker:
    def __init__(self):
        self.hr_threshold           = 0
        self.hr_arr                 = []
        self.sleep_start            = None
        self.avg_sleep_hr           = 0
        self.avg_sleep_cnt          = 0
        self.active_flag            = False
        self.reset_flag_thread      = None
        self.db_connection_settings = {
            'dbname':     DB_DATABASE,
            'user':       DB_USERNAME,
            'password':   DB_PASSWORD,
            'host':       DB_HOST,
            'port':       DB_PORT
        }
        self._create_sleep_table()

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

    def _create_sleep_table(self):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS sleep ("\
                    "sleep_start timestamp with time zone NOT NULL,"\
                    "sleep_end timestamp with time zone NOT NULL,"\
                    "average_heartrate smallint NOT NULL);"
                )
                cursor.execute(
                    "SELECT create_hypertable('sleep', 'sleep_start', if_not_exists => TRUE);"
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

    def _get_hr_threshold(self):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT average_heartrate AS hr FROM sleep ORDER BY sleep_start DESC LIMIT %s;", 
                    (HR_THRESHOLD_SAMPLES,)
                )
                avg_hrs = [element for (element,) in cursor.fetchall()]
                if avg_hrs:
                    self.hr_threshold = max(avg_hrs)
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def _save_sleep(self, sleep_start, sleep_end, avg_hr):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO sleep (sleep_start, sleep_end, average_heartrate) VALUES (%s, %s, %s);", 
                    (sleep_start, sleep_end, avg_hr)
                )
                conn.commit()
            except (psycopg2.Error) as error:
                print(error.pgerror)

    def _calc_hr(self):
        if self.active_flag or not self.hr_arr:
            return None

        heartrate = median(self.hr_arr)
        self.hr_arr = []
        return heartrate

    def _track_sleep(self, act_hr):
        if act_hr:
            if not self.sleep_start:
                self.sleep_start = datetime.now()

            self.avg_sleep_cnt += 1
            self.avg_sleep_hr += (act_hr - self.avg_sleep_hr) / self.avg_sleep_cnt
            print("RUNNING AVERAGE SLEEP HR", self.avg_sleep_hr, datetime.now())
        elif self.sleep_start:
            sleep_end = datetime.now()

            if (sleep_end - self.sleep_start).seconds // 60 >= MINIMAL_SLEEP_HOURS:
                print("SAVING SLEEP", self.avg_sleep_hr)
                self._save_sleep(self.sleep_start, sleep_end, self.avg_sleep_hr)
                self.get_hr_threshold()

            self.avg_sleep_hr  = 0
            self.avg_sleep_cnt = 0
            self.sleep_start   = None

    def _check_for_sleep(self, act_hr):
        print("CHECKING FOR SLEEP", act_hr, self.hr_threshold)
        return not self.active_flag and act_hr and act_hr <= self.hr_threshold

    def _tick(self):
        act_hr = self._calc_hr()
        self._track_sleep(act_hr)
        sleep = self._check_for_sleep(act_hr)

        print("SLEEP", sleep, datetime.now())
        Timer(WORKER_TICK_INTERVAL, self._tick).start()

    def update_hr(self, heartrate):
        if HR_VALID_LOW <= heartrate <= HR_VALID_HIGH:
            self.hr_arr.append(heartrate)

    def run(self):
        self._get_hr_threshold()
        self._tick()

