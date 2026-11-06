"""Konstanta bersama (nama aplikasi, folder log, parameter firmware)."""
import os

APP_TITLE = "Kraken Log Viewer"
DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "kraken_logs")

THR = ["rxd", "lxd", "r", "l"]          # urutan thruster
CODE_PPS_FWD = (0.162, -236.2)          # nilai di firmware: pps = m*pwm + c  (pwm > 1500)
CODE_PPS_REV = (-0.162, 249.8)          # (pwm < 1500)
CODE_MF = 0.025006857957974433          # meter / pulsa
TIME_COLS = {"t", "t_host", "t_rel", "t_mcu", "seq"}
