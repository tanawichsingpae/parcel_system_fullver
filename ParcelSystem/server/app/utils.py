# server/app/utils.py
import datetime

def today_str():
    return datetime.datetime.now().strftime('%Y%m%d')