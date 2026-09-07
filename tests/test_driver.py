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


def test_eight_bit_songs_and_sound_marks():
    """Verify 8-bit songs and robot sound marks dictionaries contain valid Open Interface note sequences."""
    from roomba.driver.sound import EIGHT_BIT_SONGS, SOUND_MARKS, PRESET_TUNES

    # Check key songs exist
    expected_songs = ["tetris", "mario_kart_start", "mario_kart_circuit", "mario_overworld", "pacman", "zelda_theme", "doom_e1m1", "pokemon_title"]
    for song_name in expected_songs:
        assert song_name in EIGHT_BIT_SONGS
        notes = EIGHT_BIT_SONGS[song_name]
        assert len(notes) > 0
        for pitch, dur in notes:
            assert 0 <= pitch <= 127
            assert 1 <= dur <= 255

    # Check robot sound marks exist
    expected_marks = ["startup", "shutdown", "dock_success", "clean_done", "obstacle_alert", "cliff_warning", "low_battery", "ack", "nack", "reverse_beep", "happy", "sad"]
    for mark_name in expected_marks:
        assert mark_name in SOUND_MARKS
        notes = SOUND_MARKS[mark_name]
        assert len(notes) > 0
        for pitch, dur in notes:
            assert 0 <= pitch <= 127
            assert 1 <= dur <= 255

    # Check presets include songs and marks
    for s in expected_songs:
        assert s in PRESET_TUNES
    for m in expected_marks:
        assert m in PRESET_TUNES


def test_rtttl_and_morse_sound_generation():
    """Verify RTTTL string parsing and Morse code note generation."""
    from roomba.driver.sound import rtttl_to_notes, text_to_morse_notes, generate_sos_notes

    # 1. RTTTL parsing
    rtttl_str = "mario:d=4,o=5,b=100:16e6,16e6,32p,8e6"
    notes = rtttl_to_notes(rtttl_str)
    assert len(notes) == 4
    for pitch, dur in notes:
        assert 0 <= pitch <= 127
        assert 1 <= dur <= 255

    # 2. Morse code generation
    morse_notes = text_to_morse_notes("SOS", note=76, dot_duration=6)
    assert len(morse_notes) > 0
    for pitch, dur in morse_notes:
        assert pitch in (0, 76)
        assert dur > 0

    # 3. SOS helper
    sos_notes = generate_sos_notes()
    assert len(sos_notes) == len(morse_notes)



