"""
Unit tests for Roomba driver layer (protocol, mock simulation, and discovery).
"""

import pytest
from roomba.driver.protocol import RoombaOpcode, RoombaSensorPacket, RoombaSensors, PACKET_100_STRUCT_FMT
from roomba.driver.mock import MockRoombaClient
from roomba.driver.discovery import list_serial_ports


def test_protocol_packet_100_format():
    """Verify packet 100 struct unpacking matches 80 bytes."""
    import struct
    calc_size = struct.calcsize(PACKET_100_STRUCT_FMT)
    assert calc_size == 80


def test_protocol_roomba_sensors_from_bytes():
    """Verify parsing a dummy 80-byte packet into RoombaSensors."""
    dummy_80_bytes = bytes([0] * 80)
    sensors = RoombaSensors.from_bytes(dummy_80_bytes)
    assert sensors is not None
    assert sensors.bump_left is False
    assert sensors.bump_right is False
    assert sensors.voltage_v == 0.0

    # Test dictionary conversion
    d = sensors.to_dict()
    assert isinstance(d, dict)
    assert "bump_left" in d


def test_discovery_list_ports():
    """Verify port discovery returns list of serial ports on current platform."""
    ports = list_serial_ports()
    assert isinstance(ports, list)


@pytest.mark.asyncio
async def test_mock_roomba_client_lifecycle():
    """Verify mock client connection, modes, and sensor simulation."""
    client = MockRoombaClient()
    assert not client.is_connected

    await client.connect()
    assert client.is_connected
    assert client.mode == "Off"

    await client.safe_mode()
    assert client.mode == "Safe"

    await client.full_mode()
    assert client.mode == "Full"

    await client.drive_direct(150, 150)
    assert client.left_velocity == 150
    assert client.right_velocity == 150

    telemetry = await client.get_telemetry()
    assert telemetry["connected"] is True
    assert telemetry["is_mock"] is True
    assert telemetry["voltage_v"] > 14.0

    await client.stop()
    assert client.left_velocity == 0
    assert client.right_velocity == 0

    await client.disconnect()
    assert not client.is_connected


def test_odometry_kinematics_and_rollover():
    """Verify RoombaClient odometry calculation, rollover handling, and persistence."""
    from roomba.driver.client import RoombaClient

    client = RoombaClient(port="TEST")
    # Initial ticks baseline
    delta1 = client._update_odometry(1000, 1000)
    assert delta1 == (0.0, 0.0)
    assert client.total_distance_mm == 0.0
    assert client.total_angle_deg == 0.0

    # Robot drives forward 100 ticks on both wheels
    # MM_PER_TICK = 0.444563 -> 100 * 0.444563 = 44.4563 mm
    delta2 = client._update_odometry(1100, 1100)
    assert abs(delta2[0] - 44.4563) < 0.1
    assert abs(delta2[1] - 0.0) < 0.01
    assert abs(client.total_distance_mm - 44.4563) < 0.1

    # Robot stops: encoder ticks don't change -> delta is 0, but total distance stays persistent!
    delta_stop = client._update_odometry(1100, 1100)
    assert delta_stop == (0.0, 0.0)
    assert abs(client.total_distance_mm - 44.4563) < 0.1  # Still persistent!

    # Rollover test: encoder rolls over 65535 -> 0
    # From 65500 to 50: delta should be (50 - 65500 + 32768) % 65536 - 32768 = 86 ticks
    client.reset_odometry()
    client._update_odometry(65500, 65500)
    delta_roll = client._update_odometry(50, 50)
    assert abs(delta_roll[0] - (86 * 0.444563)) < 0.1

    # In-place turn test: Left wheel backward 100 ticks, Right wheel forward 100 ticks
    # delta_dist = 0, delta_angle = (100 - (-100)) * 0.444563 / 235.0 * 180 / pi
    client.reset_odometry()
    client._update_odometry(1000, 1000)
    delta_turn = client._update_odometry(900, 1100)
    assert abs(delta_turn[0]) < 0.01
    expected_angle = (200 * 0.444563 / 235.0) * (180.0 / 3.141592653589793)
    assert abs(delta_turn[1] - expected_angle) < 0.1
    assert abs(client.total_angle_deg - expected_angle) < 0.1

    # Test reset_odometry
    client.reset_odometry()
    assert client.total_distance_mm == 0.0
    assert client.total_angle_deg == 0.0


def test_sound_grind_audio_to_roomba_notes():
    """Verify audio grinding DSP pipeline handles silence, tones, consonants, and run-length compression."""
    import numpy as np
    from roomba.driver.sound import grind_audio_to_roomba_notes

    sr = 16000
    # 1. Pure silence -> all rests (0, dur)
    silence = np.zeros(sr, dtype=np.float32)
    notes_silence = grind_audio_to_roomba_notes(silence, sr)
    assert len(notes_silence) >= 1
    assert all(p == 0 for p, _ in notes_silence)

    # 2. Pure 440 Hz tone (A4, MIDI 69)
    t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
    tone_440 = (0.8 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    notes_tone = grind_audio_to_roomba_notes(tone_440, sr, mode="dominant_peak")
    assert len(notes_tone) >= 1
    # Check that the detected pitch is close to 69 (A4)
    pitches = [p for p, _ in notes_tone if p > 0]
    assert len(pitches) > 0
    assert any(abs(p - 69) <= 2 for p in pitches)

    # 3. High-frequency noise (unvoiced consonant simulation)
    noise = np.random.uniform(-0.8, 0.8, int(sr * 0.2)).astype(np.float32)
    notes_noise = grind_audio_to_roomba_notes(noise, sr)
    assert len(notes_noise) >= 1
    # High ZCR noise maps to higher pitch range
    high_pitches = [p for p, _ in notes_noise if p >= 80]
    assert len(high_pitches) > 0


def test_sound_speech_synthesis_and_wav_grinding():
    """Verify speech synthesis and WAV bytes grinding produce valid Roomba note sequences."""
    import io
    import numpy as np
    from scipy.io import wavfile
    from roomba.driver.sound import synthesize_and_grind_speech, grind_wav_bytes_to_notes

    # 1. Speech synthesis
    notes = synthesize_and_grind_speech("Roomba start cleaning")
    assert len(notes) > 0
    for pitch, dur in notes:
        assert 0 <= pitch <= 127
        assert 1 <= dur <= 255

    # 2. WAV byte buffer grinding
    sr = 16000
    t = np.linspace(0, 0.3, int(sr * 0.3), endpoint=False)
    sig = (0.6 * np.sin(2 * np.pi * 587 * t) * 32767).astype(np.int16) # D5, ~MIDI 74
    buf = io.BytesIO()
    wavfile.write(buf, sr, sig)
    wav_bytes = buf.getvalue()

    ground_notes = grind_wav_bytes_to_notes(wav_bytes)
    assert len(ground_notes) > 0
    detected_pitches = [p for p, _ in ground_notes if p > 0]
    assert len(detected_pitches) > 0
    assert any(abs(p - 74) <= 2 for p in detected_pitches)


