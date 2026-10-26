import os
import math
import wave
import struct
import random

SAMPLE_RATE = 44100

def create_wav_file(filename, samples, sample_rate=SAMPLE_RATE):
    """Writes float samples (-1.0 to 1.0) into a 16-bit stereo WAV file."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(2)  # Stereo
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        frames = bytearray()
        for left, right in samples:
            # Soft clamp between -0.98 and 0.98
            l_clamped = max(-0.98, min(0.98, left))
            r_clamped = max(-0.98, min(0.98, right))
            l_int = int(l_clamped * 32767.0)
            r_int = int(r_clamped * 32767.0)
            frames.extend(struct.pack('<hh', l_int, r_int))
        wav_file.writeframes(frames)
    print(f"Generated: {filename} ({len(samples)/sample_rate:.2f}s)")

# ==============================================================================
# 1. AVIATOR BACKGROUND ELECTRONIC LOUNGE MUSIC (Looping 8-Bar Groove, ~120 BPM)
# ==============================================================================
def generate_aviator_theme():
    bpm = 120.0
    beat_sec = 60.0 / bpm          # 0.5 sec per beat
    sixteenth_sec = beat_sec / 4.0  # 0.125 sec per 16th note
    total_bars = 4
    total_beats = total_bars * 4
    total_duration = total_beats * beat_sec  # 8.0 seconds loop
    num_samples = int(total_duration * SAMPLE_RATE)
    
    # Chord frequencies for Dm -> Bb -> Gm -> A7
    chords = [
        [146.83, 220.00, 261.63, 329.63], # Dm9 (D3, A3, C4, E4)
        [116.54, 174.61, 233.08, 293.66], # Bbmaj7 (Bb2, F3, Bb3, D4)
        [98.00,  146.83, 196.00, 261.63], # Gm7 (G2, D3, G3, C4)
        [110.00, 164.81, 220.00, 293.66], # Asus4 (A2, E3, A3, D4)
    ]
    
    # Bassline notes (frequencies) for each of the 32 16th notes
    bass_pattern = [
        73.42, 0, 73.42, 0,  87.31, 0, 98.00, 0,   # Bar 1 (Dm)
        58.27, 0, 58.27, 0,  87.31, 0, 116.54, 0,  # Bar 2 (Bb)
        49.00, 0, 49.00, 0,  73.42, 0, 98.00, 0,   # Bar 3 (Gm)
        55.00, 0, 55.00, 0,  82.41, 0, 110.00, 0   # Bar 4 (A7)
    ]
    
    # Arpeggio sequence (melody notes)
    arp_notes = [
        293.66, 329.63, 349.23, 440.00, 523.25, 440.00, 349.23, 329.63, # Bar 1
        233.08, 293.66, 349.23, 466.16, 523.25, 466.16, 349.23, 293.66, # Bar 2
        196.00, 261.63, 293.66, 392.00, 440.00, 392.00, 293.66, 261.63, # Bar 3
        220.00, 293.66, 329.63, 440.00, 493.88, 440.00, 329.63, 293.66  # Bar 4
    ]

    samples = [[0.0, 0.0] for _ in range(num_samples)]
    
    # Render Drums
    for beat in range(total_beats):
        beat_start = int(beat * beat_sec * SAMPLE_RATE)
        
        # 1. Kick on beats 0, 2, 4, 6, 8, 10, 12, 14
        if beat % 2 == 0 or beat % 4 == 3:
            kick_len = int(0.18 * SAMPLE_RATE)
            for i in range(kick_len):
                if beat_start + i < num_samples:
                    t = i / SAMPLE_RATE
                    # Pitch drop 150Hz -> 42Hz
                    pitch = 42.0 + 108.0 * math.exp(-i / (SAMPLE_RATE * 0.035))
                    env = math.exp(-i / (SAMPLE_RATE * 0.06))
                    val = math.sin(2.0 * math.pi * pitch * t) * env * 0.42
                    samples[beat_start + i][0] += val
                    samples[beat_start + i][1] += val
                    
        # 2. Snare on beats 1, 3, 5, 7, 9, 11, 13, 15
        if beat % 2 == 1:
            snare_len = int(0.15 * SAMPLE_RATE)
            for i in range(snare_len):
                if beat_start + i < num_samples:
                    t = i / SAMPLE_RATE
                    env = math.exp(-i / (SAMPLE_RATE * 0.045))
                    tone = math.sin(2.0 * math.pi * 185.0 * t) * 0.2
                    noise = (random.random() * 2.0 - 1.0) * 0.35
                    val = (tone + noise) * env * 0.35
                    samples[beat_start + i][0] += val
                    samples[beat_start + i][1] += val

    # 3. Closed Hi-Hats every 16th note
    total_16ths = total_beats * 4
    for step in range(total_16ths):
        step_start = int(step * sixteenth_sec * SAMPLE_RATE)
        hat_len = int(0.04 * SAMPLE_RATE)
        vol = 0.16 if (step % 2 == 0) else 0.09
        if step % 4 == 2: vol = 0.22  # accent on up-beat
        for i in range(hat_len):
            if step_start + i < num_samples:
                env = math.exp(-i / (SAMPLE_RATE * 0.012))
                noise = (random.random() * 2.0 - 1.0) * env * vol
                samples[step_start + i][0] += noise * 0.9
                samples[step_start + i][1] += noise * 1.1

    # 4. Bassline
    for step in range(total_16ths):
        freq = bass_pattern[step % len(bass_pattern)]
        if freq > 0:
            step_start = int(step * sixteenth_sec * SAMPLE_RATE)
            bass_len = int(sixteenth_sec * 1.8 * SAMPLE_RATE)
            for i in range(bass_len):
                if step_start + i < num_samples:
                    t = i / SAMPLE_RATE
                    env = math.exp(-i / (SAMPLE_RATE * 0.14))
                    # Punchy triangle + warm saw harmonic
                    tone1 = math.sin(2.0 * math.pi * freq * t)
                    tone2 = math.sin(2.0 * math.pi * (freq * 2.0) * t) * 0.35
                    val = (tone1 + tone2) * env * 0.38
                    samples[step_start + i][0] += val
                    samples[step_start + i][1] += val

    # 5. Ambient Chords (Lush synth pads)
    for bar in range(total_bars):
        chord = chords[bar % len(chords)]
        bar_start = int(bar * (4 * beat_sec) * SAMPLE_RATE)
        bar_len = int(4 * beat_sec * SAMPLE_RATE)
        for i in range(bar_len):
            if bar_start + i < num_samples:
                t = i / SAMPLE_RATE
                fade_in = min(1.0, i / (SAMPLE_RATE * 0.25))
                fade_out = min(1.0, (bar_len - i) / (SAMPLE_RATE * 0.25))
                env = fade_in * fade_out * 0.11
                chord_val_l = 0.0
                chord_val_r = 0.0
                for idx, f in enumerate(chord):
                    detune = (idx - 1.5) * 0.4
                    chord_val_l += math.sin(2.0 * math.pi * (f + detune) * t)
                    chord_val_r += math.sin(2.0 * math.pi * (f - detune) * t)
                samples[bar_start + i][0] += chord_val_l * env
                samples[bar_start + i][1] += chord_val_r * env

    # 6. Arpeggiator Melody Lead
    for step in range(total_16ths):
        note = arp_notes[step % len(arp_notes)]
        step_start = int(step * sixteenth_sec * SAMPLE_RATE)
        arp_len = int(0.18 * SAMPLE_RATE)
        pan = 0.5 + 0.3 * math.sin(step * 0.5)  # Stereo ping-pong
        for i in range(arp_len):
            if step_start + i < num_samples:
                t = i / SAMPLE_RATE
                env = math.exp(-i / (SAMPLE_RATE * 0.07))
                # Soft chime / pluck tone
                val = math.sin(2.0 * math.pi * note * t) * env * 0.18
                samples[step_start + i][0] += val * (1.0 - pan)
                samples[step_start + i][1] += val * pan

    return samples

# ==============================================================================
# 2. EXACT AVIATOR FLEW-AWAY SOUND (Supersonic Rocket Jet Zoom + Boom)
# ==============================================================================
def generate_aviator_flew_away():
    duration = 2.4
    num_samples = int(duration * SAMPLE_RATE)
    samples = [[0.0, 0.0] for _ in range(num_samples)]
    
    # Layer 1: Sub-Bass Boom / Jet Afterburner Thump (0.0 to 0.7s)
    thump_len = int(0.7 * SAMPLE_RATE)
    for i in range(thump_len):
        t = i / SAMPLE_RATE
        env = math.exp(-i / (SAMPLE_RATE * 0.18))
        pitch = 30.0 + 85.0 * math.exp(-i / (SAMPLE_RATE * 0.12))
        val = math.sin(2.0 * math.pi * pitch * t) * env * 0.65
        samples[i][0] += val
        samples[i][1] += val

    # Layer 2: Supersonic Jet Turbine Scream (320Hz -> 2800Hz)
    turbine_len = int(1.6 * SAMPLE_RATE)
    phase = 0.0
    for i in range(turbine_len):
        progress = i / turbine_len
        # Exponential pitch glide rocketing upwards
        freq = 320.0 * (8.5 ** progress)
        phase += 2.0 * math.pi * freq / SAMPLE_RATE
        env = math.sin(math.pi * progress) ** 0.8 * 0.38
        saw = (2.0 * (phase / (2.0 * math.pi) % 1.0) - 1.0) * env
        # Stereo Doppler pan: begins left/center, flies far right
        pan_r = min(1.0, 0.3 + 0.7 * progress)
        pan_l = 1.0 - pan_r
        samples[i][0] += saw * pan_l
        samples[i][1] += saw * pan_r

    # Layer 3: Supersonic Turbulent Jet Whoosh (Filtered Noise Burst)
    whoosh_len = int(2.2 * SAMPLE_RATE)
    # Simple IIR 2-pole resonant bandpass filter state
    b0 = 0.0; b1 = 0.0; b2 = 0.0
    a1 = 0.0; a2 = 0.0
    x1 = 0.0; x2 = 0.0; y1 = 0.0; y2 = 0.0

    for i in range(whoosh_len):
        progress = i / whoosh_len
        # Center frequency sweeps from 400Hz up to 3400Hz then down to 400Hz
        center_f = 400.0 + 3000.0 * math.sin(math.pi * progress)
        q = 3.5
        w0 = 2.0 * math.pi * center_f / SAMPLE_RATE
        alpha = math.sin(w0) / (2.0 * q)
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * math.cos(w0) / a0
        a2 = (1.0 - alpha) / a0
        b0 /= a0; b1 /= a0; b2 /= a0

        raw_noise = random.random() * 2.0 - 1.0
        filtered = b0 * raw_noise + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1; x1 = raw_noise
        y2 = y1; y1 = filtered

        env = math.sin(math.pi * (progress ** 0.85)) * 0.72
        pan_r = min(1.0, 0.2 + 0.8 * progress)
        pan_l = 1.0 - pan_r
        samples[i][0] += filtered * env * pan_l
        samples[i][1] += filtered * env * pan_r

    return samples

# ==============================================================================
# 3. CONTINUOUS IN-FLIGHT PROPELLER / TURBINE DRONE (Seamless 2.0s Loop)
# ==============================================================================
def generate_aviator_propeller():
    duration = 2.0
    num_samples = int(duration * SAMPLE_RATE)
    samples = [[0.0, 0.0] for _ in range(num_samples)]
    
    fundamental = 165.0  # Propeller / turbine blade rate in Hz
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        # Harmonic engine buzz (fundamental + 2nd, 3rd, 4th harmonics)
        h1 = math.sin(2.0 * math.pi * fundamental * t) * 0.35
        h2 = math.sin(2.0 * math.pi * (fundamental * 2.0) * t) * 0.25
        h3 = math.sin(2.0 * math.pi * (fundamental * 3.0) * t) * 0.15
        h4 = math.sin(2.0 * math.pi * (fundamental * 4.0) * t) * 0.08
        noise = (random.random() * 2.0 - 1.0) * 0.06
        engine_val = (h1 + h2 + h3 + h4 + noise) * 0.45
        samples[i][0] = engine_val
        samples[i][1] = engine_val
        
    return samples

if __name__ == '__main__':
    base_dir = os.path.dirname(os.path.abspath(__file__))
    audio_dir = os.path.join(base_dir, 'static', 'audio')
    
    print("Synthesizing Aviator Audio Assets...")
    theme_samples = generate_aviator_theme()
    create_wav_file(os.path.join(audio_dir, 'aviator_theme.wav'), theme_samples)
    
    flew_away_samples = generate_aviator_flew_away()
    create_wav_file(os.path.join(audio_dir, 'aviator_flew_away.wav'), flew_away_samples)

    propeller_samples = generate_aviator_propeller()
    create_wav_file(os.path.join(audio_dir, 'aviator_propeller.wav'), propeller_samples)
    print("Done generating all audio assets!")
