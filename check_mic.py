import wave, audioop, os, time

files = sorted(
    [f for f in os.listdir('mic_input') if f.startswith('req_')],
    key=lambda f: os.path.getmtime('mic_input/' + f))[-8:]

for name in files:
    path = 'mic_input/' + name
    w = wave.open(path, 'rb')
    rate = w.getframerate()
    frames = w.readframes(w.getnframes())
    w.close()
    data = frames if len(frames) % 2 == 0 else frames[:-1]
    rms = audioop.rms(data, 2)
    mx = audioop.max(data, 2)
    dur = len(data) / 2 / rate
    t = time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(path)))
    verdict = 'SILENT' if mx < 500 else ('quiet' if mx < 3000 else 'loud')
    clip = ' *** CLIPPING ***' if mx >= 32000 else ''
    print('%s %s: %dHz %.2fs rms=%5d peak=%6d -> %s%s' % (t, name, rate, dur, rms, mx, verdict, clip))
