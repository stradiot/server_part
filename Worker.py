import psycopg2
from threading import Timer
from statistics import median
from datetime import datetime, timedelta

DB_DATABASE = 'sleep_detector'
DB_USERNAME = 'postgres'
DB_PASSWORD = 'postgres'
DB_HOST     = 'localhost'
DB_PORT     = 5555

HR_VALID_LOW  = 40
HR_VALID_HIGH = 80

WORKER_TICK_INTERVAL = 20

MINIMAL_SLEEP_HOURS = 1

ACTIVE_FLAG_TIMEOUT = 30

HR_THRESHOLD_SAMPLES = 7

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
    
    def reset_active_flag(self):
        self.active_flag = False
        print("ACTIVE FLAG RESET", self.active_flag, datetime.now())
    
    def set_active_flag(self):
        self.active_flag = True

        if (self.reset_flag_thread):
            self.reset_flag_thread.cancel()
        
        self.reset_flag_thread = Timer(ACTIVE_FLAG_TIMEOUT, self.reset_active_flag)
        self.reset_flag_thread.start()

        print("ACTIVE FLAG SET", self.active_flag, datetime.now())

    def get_hr_threshold(self):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT average_heartrate AS hr FROM sleep ORDER BY sleep_start DESC LIMIT %s;", (HR_THRESHOLD_SAMPLES,))
                avg_hrs = [element for (element,) in cursor.fetchall()]
                self.hr_threshold = max(avg_hrs)
            except (Exception, psycopg2.Error) as error:
               print(error.pgerror)

    def save_sleep(self, sleep_start, sleep_end, avg_hr):
        with psycopg2.connect(**self.db_connection_settings) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO sleep (sleep_start, sleep_end, average_heartrate) VALUES (%s, %s, %s);", (sleep_start, sleep_end, avg_hr))
                conn.commit()
            except (Exception, psycopg2.Error) as error:
               print(error.pgerror)
    
    def calc_hr(self):
        if (self.active_flag or not self.hr_arr):
            return None
        else:
            hr = median(self.hr_arr)
            self.hr_arr = []
            return hr

    def track_sleep(self, act_hr):
        if (act_hr):
            if (not self.sleep_start):
                self.sleep_start = datetime.now()

            self.avg_sleep_cnt += 1
            self.avg_sleep_hr += (act_hr - self.avg_sleep_hr) / self.avg_sleep_cnt
            print("RUNNING AVERAGE SLEEP HR", self.avg_sleep_hr, datetime.now())
        elif (self.sleep_start):
            sleep_end = datetime.now()

            if ((sleep_end - self.sleep_start).seconds // 60 >= MINIMAL_SLEEP_HOURS):
                print("SAVING SLEEP", self.avg_sleep_hr)
                self.save_sleep(self.sleep_start, sleep_end, self.avg_sleep_hr)
                self.get_hr_threshold()

            self.avg_sleep_hr  = 0
            self.avg_sleep_cnt = 0
            self.sleep_start   = None

    def check_for_sleep(self, act_hr):
        print("CHECKING FOR SLEEP", act_hr, self.hr_threshold)
        if (not self.active_flag and act_hr and act_hr <= self.hr_threshold):
            return True
        else:
            return False

    def tick(self):
        act_hr = self.calc_hr()
        self.track_sleep(act_hr)
        sleep = self.check_for_sleep(act_hr)

        print("SLEEP", sleep, datetime.now())
        Timer(WORKER_TICK_INTERVAL, self.tick).start()
    
    def update_hr(self, heartrate):
        if (heartrate > HR_VALID_LOW and heartrate < HR_VALID_HIGH):
            self.hr_arr.append(heartrate)

    def run(self):
        self.get_hr_threshold()
        self.tick()

