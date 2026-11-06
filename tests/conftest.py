import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="session")
def sample_csv(tmp_path_factory):
    """Log sintetis 120 s @ 20 Hz dengan setpoint yaw bertingkat, PPS, PWM, pulsa, dan posisi."""
    rng = np.random.default_rng(0)
    n, fs = 2400, 20.0
    t = np.arange(n) / fs
    sp_yaw = np.select([t < 30, t < 60, t < 90], [0.0, 30.0, -30.0], 0.0)
    yaw = np.zeros(n)
    for i in range(1, n):                                   # orde-1 mengejar setpoint
        yaw[i] = yaw[i - 1] + 0.08 * (sp_yaw[i] - yaw[i - 1])
    yaw += rng.normal(0, 0.2, n)
    cmd = np.select([t < 30, t < 90], ["CMD_STOP", "CMD_MAJU"], "CMD_STOP")
    pwm = np.where(cmd == "CMD_MAJU", 1700 + 20 * np.floor((t % 30) / 10), 1500).astype(float)
    pps = np.where(pwm > 1500, 0.162 * pwm - 236.2, 0.0)
    df = pd.DataFrame({
        "t_mcu": t, "cmd": cmd,
        "roll": rng.normal(0, 0.3, n), "pitch": rng.normal(1, 0.3, n), "yaw": yaw,
        "sp_yaw": sp_yaw, "sp_pitch": 0.0, "sp_roll": 0.0,
        "z": 50 + rng.normal(0, 0.5, n), "sp_z": 50.0,
        "x": np.cumsum(np.where(cmd == "CMD_MAJU", 0.01, 0.0)), "y": np.zeros(n),
    })
    for k in ("rxd", "lxd", "r", "l"):
        df["pwm_" + k] = pwm
        df["pps_" + k] = pps + rng.normal(0, 0.3, n)
        df["pul_" + k] = np.cumsum(pps) / fs
    path = tmp_path_factory.mktemp("log") / "telemetry_test.csv"
    df.to_csv(path, index=False)
    return str(path)
