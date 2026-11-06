# Kraken Log Viewer

Alat analisis dan **replay** log telemetri AUV Kraken. Buka log CSV, putar ulang seperti rekaman,
lihat nilai roll/pitch/yaw, setpoint, error, PPS, PWM dan perintah pada detik tertentu, lalu
dapatkan statistik dan saran tuning (bias, RMS, drift, overshoot, trim thruster, kalibrasi jarak).

## Fitur

- **10 analisis**: Ringkasan data, IMU, IMU Setpoint, Error Setpoint, PPS, Perintah (CMD),
  Analisis Statis, Respons Langkah, PWM-PPS, Jarak/Lintasan.
- **Replay**: putar/jeda, kecepatan 0.25x-20x, klik grafik untuk lompat waktu, lompat antar perintah,
  mode "sembunyikan masa depan".
- **Rentang analisis**: tandai mulai/akhir dari posisi kursor, semua angka dihitung ulang untuk rentang itu.
- **Ekspor**: laporan HTML lengkap atau semua gambar PNG, juga lewat baris perintah tanpa jendela.

## Instalasi

Butuh Python 3.9+ dan Tkinter (untuk jendela).

```bash
git clone <url-repo-ini>
cd kraken-log-viewer
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Tkinter: Ubuntu/Debian `sudo apt install python3-tk`, Fedora `sudo dnf install python3-tkinter`,
Windows centang *tcl/tk and IDLE* saat memasang Python.

## Pemakaian

```bash
kraken-viewer                           # buka jendela
kraken-viewer <file.csv | folder>       # langsung buka log
kraken-viewer <log> --report out.html   # laporan tanpa jendela (cocok lewat SSH)
kraken-viewer <log> --report out.html --set t0=10 --set t1=120 --set track_tol=2
```

Tanpa instalasi: `python -m kraken_viewer ...` dari folder repo.

Folder log bawaan: `~/Documents/kraken_logs/<sesi>/telemetry_*.csv` (tombol **Log terbaru**).

### Kontrol replay

| Aksi | Cara |
|---|---|
| Putar / jeda | tombol Putar atau `Spasi` |
| Mundur / maju 1 detik | `←` / `→` (dengan `Shift` = 10 detik) |
| Ke awal | `Home` |
| Lompat ke waktu | klik pada grafik berbasis waktu |
| Batas rentang analisis | **Tandai mulai** / **Tandai akhir** / **Reset rentang** |

### Opsi `--set`

`t0`, `t1` (rentang), `smooth`, `track_src` (`auto`/`firmware`/`GUI`), `track_tol`, `track_settle`,
`s0`, `s1` (analisis statis), `step_ch`, `step_min`, `step_tol`, `step_hold`, `step_win`,
`ref_pwm`, `settle`, `known`.

## Format log

CSV `telemetry_*.csv` dengan kolom minimal salah satu dari `roll`/`pitch`/`yaw`/`pps_*`.
Basis waktu dipilih otomatis: `t_mcu` > `t_rel` > `t_host` > urutan baris x 0.05 s.
Kolom lain (`sp_*`, `gui_sp_*`, `o_*`, `z`, `pwm_*`, `pul_*`, `x`, `y`, `cmd`, `gz`, `loop_us`)
mengaktifkan analisis yang sesuai; bila tidak ada, tab menjelaskan kolom apa yang kurang.

## Struktur proyek

```
kraken_viewer/
  config.py      konstanta (folder log, parameter firmware)
  utils.py       fungsi bantu (wrap180, fmt, table, ...)
  loader.py      memuat CSV, jendela waktu, segmen perintah
  plotting.py    gaya matplotlib dan new_fig
  analyses.py    semua analisis (an_*) dan daftar TABS
  report.py      run_all dan laporan HTML
  cli.py         titik masuk `kraken-viewer`
  gui/           jendela Tkinter (app, kursor waktu, readout, widget)
tests/           pytest dengan log sintetis
```

Menambah analisis baru: tulis fungsi `an_xxx(data, opts) -> (Figure | None, teks)` di `analyses.py`
lalu daftarkan di `TABS`. Jendela dan laporan HTML otomatis ikut.

## Pengembangan

```bash
pip install -e ".[dev]"
pytest
```

## Lisensi

MIT, lihat [LICENSE](LICENSE).