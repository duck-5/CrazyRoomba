/**
 * Roomba 960 Cockpit Web Application
 * Real-time WebSocket telemetry rendering, mode management,
 * ARM/DISARM safety logic, and WASD/D-Pad teleoperation.
 */

class RoombaCockpit {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.pingInterval = null;
    this.lastPingSent = 0;

    // Robot State
    this.connected = false;
    this.isMock = false;
    this.armed = false;
    this.currentMode = "Off";
    this.driveSpeed = 150;
    this.pressedDirections = new Set();
    this.activeDirection = null;
    this.isDriving = false;
    this.driveHeartbeat = null;

    // UI Elements
    this.initElements();
    this.bindEvents();
    this.scanPorts();
    this.connectWebSocket();
  }

  initElements() {
    // Top Bar
    this.connIndicator = document.getElementById("conn-indicator");
    this.connStatusText = document.getElementById("conn-status-text");
    this.pingBadge = document.getElementById("ping-badge");
    this.portSelect = document.getElementById("port-select");
    this.btnRefreshPorts = document.getElementById("btn-refresh-ports");
    this.btnConnect = document.getElementById("btn-connect");
    this.btnDisconnect = document.getElementById("btn-disconnect");
    this.mockCheckbox = document.getElementById("mock-checkbox");
    this.btnEstop = document.getElementById("btn-estop");

    // Robot SVG Elements
    this.oiModeBadge = document.getElementById("oi-mode-badge");
    this.svgBumpL = document.getElementById("svg-bump-left");
    this.svgBumpR = document.getElementById("svg-bump-right");
    this.svgWheelL = document.getElementById("svg-wheel-left");
    this.svgWheelR = document.getElementById("svg-wheel-right");
    this.svgCliffL = document.getElementById("svg-cliff-left");
    this.svgCliffFL = document.getElementById("svg-cliff-front-left");
    this.svgCliffFR = document.getElementById("svg-cliff-front-right");
    this.svgCliffR = document.getElementById("svg-cliff-right");
    this.svgWall = document.getElementById("svg-wall");
    this.svgDrivingText = document.getElementById("svg-driving-text");

    // Pills
    this.pillBumpL = document.getElementById("pill-bump-l");
    this.pillBumpR = document.getElementById("pill-bump-r");
    this.pillDropL = document.getElementById("pill-drop-l");
    this.pillDropR = document.getElementById("pill-drop-r");
    this.pillCliffL = document.getElementById("pill-cliff-l");
    this.pillCliffFL = document.getElementById("pill-cliff-fl");
    this.pillCliffFR = document.getElementById("pill-cliff-fr");
    this.pillCliffR = document.getElementById("pill-cliff-r");
    this.pillWall = document.getElementById("pill-wall");
    this.pillVWall = document.getElementById("pill-vwall");

    // Arming
    this.armBadge = document.getElementById("arm-badge");
    this.btnToggleArm = document.getElementById("btn-toggle-arm");

    // Teleop & D-Pad
    this.driveStateBadge = document.getElementById("drive-state-badge");
    this.speedSlider = document.getElementById("speed-slider");
    this.speedValue = document.getElementById("speed-value");
    this.presetButtons = document.querySelectorAll(".btn-preset");
    this.btnFwd = document.getElementById("btn-forward");
    this.btnRev = document.getElementById("btn-backward");
    this.btnLeft = document.getElementById("btn-left");
    this.btnRight = document.getElementById("btn-right");
    this.btnStop = document.getElementById("btn-stop");

    // WASD HUD
    this.keyW = document.getElementById("key-w");
    this.keyA = document.getElementById("key-a");
    this.keyS = document.getElementById("key-s");
    this.keyD = document.getElementById("key-d");
    this.keySpace = document.getElementById("key-space");

    // Nudges
    this.nudgeButtons = document.querySelectorAll(".btn-nudge");

    // Battery & Stats
    this.chgStateBadge = document.getElementById("chg-state-badge");
    this.batteryFill = document.getElementById("battery-fill");
    this.batteryPctText = document.getElementById("battery-pct-text");
    this.statVoltage = document.getElementById("stat-voltage");
    this.statVoltageMv = document.getElementById("stat-voltage-mv");
    this.statCurrent = document.getElementById("stat-current");
    this.statPowerState = document.getElementById("stat-power-state");
    this.statCharge = document.getElementById("stat-charge");
    this.statCapacity = document.getElementById("stat-capacity");
    this.statTemp = document.getElementById("stat-temp");
    this.statDistance = document.getElementById("stat-distance");
    this.statAngle = document.getElementById("stat-angle");
    this.statHeading = document.getElementById("stat-heading");
    this.btnResetOdom = document.getElementById("btn-reset-odom");

    // Mode Buttons
    this.modeButtons = document.querySelectorAll(".btn-mode");

    // Behaviors
    this.activeBehaviorBadge = document.getElementById("active-behavior-badge");
    this.behaviorButtons = document.querySelectorAll(".btn-behavior");

    // Actions
    this.btnActBeep = document.getElementById("btn-act-beep");
    this.btnActDock = document.getElementById("btn-act-dock");
    this.btnActClean = document.getElementById("btn-act-clean");
    this.btnActSpot = document.getElementById("btn-act-spot");

    // Sound & Audio Transmitter Elements
    this.selectPresetTune = document.getElementById("select-preset-tune");
    this.btnPlayTune = document.getElementById("btn-play-tune");
    this.inputMorseText = document.getElementById("input-morse-text");
    this.btnTransmitMorse = document.getElementById("btn-transmit-morse");
    this.inputRtttl = document.getElementById("input-rtttl");
    this.btnPlayRtttl = document.getElementById("btn-play-rtttl");
    this.sliderBeepNote = document.getElementById("slider-beep-note");
    this.sliderBeepDur = document.getElementById("slider-beep-dur");
    this.valBeepNote = document.getElementById("val-beep-note");
    this.valBeepDur = document.getElementById("val-beep-dur");
    this.btnPlayTone = document.getElementById("btn-play-tone");
    this.btnQuickSos = document.getElementById("btn-quick-sos");
    this.inputSpeechText = document.getElementById("input-speech-text");
    this.selectSpeechMode = document.getElementById("select-speech-mode");
    this.selectSpeechTarget = document.getElementById("select-speech-target");
    this.btnSpeakVoice = document.getElementById("btn-speak-voice");
    this.btnRecordMic = document.getElementById("btn-record-mic");
    this.micIcon = document.getElementById("mic-icon");
    this.micLabel = document.getElementById("mic-label");
    this.micStatusBadge = document.getElementById("mic-status-badge");
    this.inputAudioFile = document.getElementById("input-audio-file");
    this.btnGrindFile = document.getElementById("btn-grind-file");
    this.soundboardContainer = document.getElementById("soundboard-container");

    // Microphone state
    this.isRecordingMic = false;
    this.micMediaRecorder = null;
    this.micAudioChunks = [];

    // Console
    this.consoleOutput = document.getElementById("console-output");
    this.btnClearLog = document.getElementById("btn-clear-log");
  }

  log(message, type = "info") {
    const time = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = `log-line log-${type}`;
    line.textContent = `[${time}] ${message}`;
    this.consoleOutput.appendChild(line);
    this.consoleOutput.scrollTop = this.consoleOutput.scrollHeight;
  }

  speakHumanVoice(text) {
    if (!("speechSynthesis" in window)) {
      this.log("Speech Synthesis not supported in this browser.", "warn");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    const voices = window.speechSynthesis.getVoices();
    const engVoice = voices.find((v) => v.lang.startsWith("en"));
    if (engVoice) utterance.voice = engVoice;
    window.speechSynthesis.speak(utterance);
    this.log(`Spoke human voice: "${text}"`, "info");
  }

  async uploadAndGrindAudioBlob(blob) {
    try {
      this.log("Processing and converting voice recording to standard WAV...", "info");
      const wavBlob = await this.blobToWav(blob);
      const formData = new FormData();
      formData.append("file", wavBlob, "voice_recording.wav");
      this.log("Grinding audio signal into 64Hz Roomba formant notes...", "info");
      const res = await fetch("/api/sound/grind_audio", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Audio grinding failed");
      }
      const data = await res.json();
      this.log(`Voice ground into ${data.notes_count} Roomba notes (${data.duration_s ? data.duration_s.toFixed(2) + "s" : ""}) and streaming to robot speaker!`, "success");
      if (this.micStatusBadge) {
        this.micStatusBadge.textContent = "IDLE";
        this.micStatusBadge.className = "badge badge-mode";
      }
    } catch (err) {
      this.log(`Audio Grinder error: ${err.message}`, "error");
      if (this.micStatusBadge) {
        this.micStatusBadge.textContent = "ERROR";
        this.micStatusBadge.className = "badge badge-danger";
      }
    }
  }

  async blobToWav(blob) {
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const arrayBuffer = await blob.arrayBuffer();
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

      const targetSampleRate = 16000;
      const offlineCtx = new OfflineAudioContext(
        1,
        Math.max(16, Math.ceil(audioBuffer.duration * targetSampleRate)),
        targetSampleRate
      );
      const source = offlineCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(offlineCtx.destination);
      source.start(0);
      const rendered = await offlineCtx.startRendering();

      const channelData = rendered.getChannelData(0);
      const wavBuffer = this.pcmToWav(channelData, targetSampleRate);
      return new Blob([wavBuffer], { type: "audio/wav" });
    } catch (e) {
      console.warn("Web Audio decode fallback to raw blob:", e);
      return blob;
    }
  }

  pcmToWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeString = (offset, string) => {
      for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    };
    writeString(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // Mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      let s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buffer;
  }


  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.log("Connected to telemetry stream server.", "success");
      this.startPingLoop();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "pong") {
          const latency = Math.round(performance.now() - this.lastPingSent);
          this.pingBadge.textContent = `${latency} ms`;
        } else if (data.type === "error") {
          this.log(`Command error: ${data.message}`, "warn");
        } else {
          this.handleTelemetry(data);
        }
      } catch (err) {
        console.error("WS Parse error:", err);
      }
    };

    this.ws.onclose = () => {
      this.stopPingLoop();
      this.pingBadge.textContent = "-- ms";
      this.log("Telemetry WebSocket disconnected. Reconnecting in 2s...", "warn");
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 2000);
    };

    this.ws.onerror = (err) => {
      console.warn("WebSocket error:", err);
    };
  }

  startPingLoop() {
    this.stopPingLoop();
    this.pingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.lastPingSent = performance.now();
        this.ws.send(JSON.stringify({ type: "ping", ts: this.lastPingSent }));
      }
    }, 2000);
  }

  stopPingLoop() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  // --- Telemetry Updates ---

  handleTelemetry(data) {
    this.connected = !!data.connected;
    this.isMock = !!data.is_mock;
    this.armed = !!data.armed;
    this.currentMode = data.mode || "Off";
    this.isDriving = !!data.is_driving;

    // 1. Connection Status
    if (this.connected) {
      if (this.isMock) {
        this.connIndicator.className = "status-dot dot-mock";
        this.connStatusText.textContent = "MOCK SIMULATOR";
      } else {
        this.connIndicator.className = "status-dot dot-online";
        this.connStatusText.textContent = `ONLINE (${data.port || "SERIAL"})`;
      }
      this.btnConnect.style.display = "none";
      this.btnDisconnect.style.display = "inline-block";
    } else {
      this.connIndicator.className = "status-dot dot-offline";
      this.connStatusText.textContent = "DISCONNECTED";
      this.btnConnect.style.display = "inline-block";
      this.btnDisconnect.style.display = "none";
    }

    // 2. Mode Badges
    this.oiModeBadge.textContent = this.currentMode.toUpperCase();
    this.modeButtons.forEach((btn) => {
      const m = btn.getAttribute("data-mode");
      if (m && m.toLowerCase() === this.currentMode.toLowerCase()) {
        btn.classList.add("active-mode");
      } else {
        btn.classList.remove("active-mode");
      }
    });

    // 2b. Autonomous Behaviors
    this.activeBehavior = data.active_behavior || "manual";
    if (this.activeBehaviorBadge) {
      this.activeBehaviorBadge.textContent = this.activeBehavior.toUpperCase();
    }
    if (this.behaviorButtons) {
      this.behaviorButtons.forEach((btn) => {
        const b = btn.getAttribute("data-behavior");
        if (b && b.toLowerCase() === this.activeBehavior.toLowerCase()) {
          btn.classList.add("active-behavior");
        } else {
          btn.classList.remove("active-behavior");
        }
      });
    }

    // 3. Safety & Arming
    if (this.armed) {
      this.armBadge.className = "badge badge-armed";
      this.armBadge.textContent = "ARMED";
      this.btnToggleArm.textContent = "DISARM ROBOT";
      this.btnToggleArm.className = "btn btn-arm is-armed";
    } else {
      this.armBadge.className = "badge badge-disarmed";
      this.armBadge.textContent = "DISARMED";
      this.btnToggleArm.textContent = "ARM ROBOT";
      this.btnToggleArm.className = "btn btn-arm";
    }

    // 4. Drive State
    if (this.isDriving) {
      this.driveStateBadge.textContent = "DRIVING";
      this.driveStateBadge.className = "badge badge-armed";
      this.svgDrivingText.textContent = "DRIVING";
    } else {
      this.driveStateBadge.textContent = "STOPPED";
      this.driveStateBadge.className = "badge";
      this.svgDrivingText.textContent = "IDLE";
    }

    // 5. Sensors & SVG Indicators
    const drops = data.bumps_and_drops || {};
    const cliffs = data.cliffs || {};
    const wall = data.wall || {};

    // Bumpers
    this.toggleSvg(this.svgBumpL, "active-bump", drops.bump_left);
    this.toggleSvg(this.svgBumpR, "active-bump", drops.bump_right);
    this.togglePill(this.pillBumpL, "active-danger", drops.bump_left);
    this.togglePill(this.pillBumpR, "active-danger", drops.bump_right);

    // Wheel Drops
    this.toggleSvg(this.svgWheelL, "active-drop", drops.wheel_drop_left);
    this.toggleSvg(this.svgWheelR, "active-drop", drops.wheel_drop_right);
    this.togglePill(this.pillDropL, "active-warn", drops.wheel_drop_left);
    this.togglePill(this.pillDropR, "active-warn", drops.wheel_drop_right);

    // Cliffs
    this.toggleSvg(this.svgCliffL, "active-cliff", cliffs.cliff_left);
    this.toggleSvg(this.svgCliffFL, "active-cliff", cliffs.cliff_front_left);
    this.toggleSvg(this.svgCliffFR, "active-cliff", cliffs.cliff_front_right);
    this.toggleSvg(this.svgCliffR, "active-cliff", cliffs.cliff_right);
    this.togglePill(this.pillCliffL, "active-danger", cliffs.cliff_left);
    this.togglePill(this.pillCliffFL, "active-danger", cliffs.cliff_front_left);
    this.togglePill(this.pillCliffFR, "active-danger", cliffs.cliff_front_right);
    this.togglePill(this.pillCliffR, "active-danger", cliffs.cliff_right);

    // Wall & Virtual Wall
    this.toggleSvg(this.svgWall, "active-wall", wall.wall);
    this.togglePill(this.pillWall, "active-info", wall.wall);
    this.togglePill(this.pillVWall, "active-info", wall.virtual_wall);

    // 6. Battery Gauge & Stats
    const pct = data.battery_percent || 0;
    this.batteryFill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
    this.batteryPctText.textContent = `${pct}%`;

    this.batteryFill.classList.remove("batt-mid", "batt-low");
    if (pct < 20) {
      this.batteryFill.classList.add("batt-low");
    } else if (pct < 50) {
      this.batteryFill.classList.add("batt-mid");
    }

    this.statVoltage.textContent = `${data.voltage_v || 0} V`;
    this.statVoltageMv.textContent = `${data.voltage_mv || 0} mV`;
    this.statCurrent.textContent = `${data.current_ma || 0} mA`;
    this.chgStateBadge.textContent = data.charging_state || "Not Charging";

    if ((data.current_ma || 0) > 0) {
      this.statPowerState.textContent = "Charging";
      this.statPowerState.style.color = "var(--accent-green)";
    } else if ((data.current_ma || 0) < -400) {
      this.statPowerState.textContent = "Driving Load";
      this.statPowerState.style.color = "var(--accent-amber)";
    } else {
      this.statPowerState.textContent = "Standby";
      this.statPowerState.style.color = "var(--text-muted)";
    }

    this.statCharge.textContent = `${data.battery_charge_mah || 0} mAh`;
    this.statCapacity.textContent = `/ ${data.battery_capacity_mah || 0} mAh`;
    this.statTemp.textContent = `${data.temperature_c || 0} °C`;

    const enc = data.encoders || {};
    this.statDistance.textContent = `${enc.distance_mm || 0} mm`;
    this.statAngle.textContent = `${enc.angle_deg || 0}°`;
    if (this.statHeading) {
      this.statHeading.textContent = `Heading: ${enc.heading_deg !== undefined ? enc.heading_deg : 0}°`;
    }
  }

  toggleSvg(el, className, active) {
    if (!el) return;
    if (active) el.classList.add(className);
    else el.classList.remove(className);
  }

  togglePill(el, className, active) {
    if (!el) return;
    if (active) el.classList.add(className);
    else el.classList.remove(className);
  }

  // --- API Requests ---

  async scanPorts() {
    try {
      const res = await fetch("/api/ports");
      const data = await res.json();
      this.portSelect.innerHTML = "";

      if (!data.ports || data.ports.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No COM ports found";
        this.portSelect.appendChild(opt);
        return;
      }

      data.ports.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.device;
        const tag = p.is_roomba ? "⭐ [ROOMBA 960]" : "";
        opt.textContent = `${p.device} ${tag} (${p.description})`;
        if (p.is_roomba) {
          opt.selected = true;
        }
        this.portSelect.appendChild(opt);
      });
    } catch (err) {
      console.warn("Scan ports failed:", err);
    }
  }

  async connectRobot() {
    const isMock = this.mockCheckbox.checked;
    const port = this.portSelect.value;

    this.log(`Connecting (${isMock ? "Mock" : port})...`, "info");

    try {
      const res = await fetch("/api/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ port: isMock ? null : port, mock: isMock, mode: "Safe" }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Connection failed");
      }

      const info = await res.json();
      this.log(`Connected successfully: ${info.port} (${info.mode})`, "success");
    } catch (err) {
      this.log(`Connection error: ${err.message}`, "error");
      alert(`Connection failed: ${err.message}\n\nTip: If COM11 is in use, close teleop_wasd.py or check 'Mock Sim' to test.`);
    }
  }

  async disconnectRobot() {
    try {
      await fetch("/api/disconnect", { method: "POST" });
      this.log("Robot disconnected cleanly.", "info");
    } catch (err) {
      this.log(`Disconnect error: ${err.message}`, "warn");
    }
  }

  async toggleArm() {
    if (!this.connected) {
      alert("Please connect to the Roomba first.");
      return;
    }

    if (this.armed) {
      await fetch("/api/disarm", { method: "POST" });
      this.log("Robot DISARMED by user.", "info");
    } else {
      try {
        const res = await fetch("/api/arm", { method: "POST" });
        if (!res.ok) throw new Error("Arming failed");
        this.log("Robot ARMED by user! Controls are live.", "warn");
      } catch (err) {
        this.log(`Arming error: ${err.message}`, "error");
      }
    }
  }

  async emergencyStop() {
    try {
      await fetch("/api/estop", { method: "POST" });
      this.stopDriving();
      this.log("EMERGENCY STOP EXECUTED!", "critical");
    } catch (err) {
      console.error("ESTOP error:", err);
    }
  }

  async setMode(mode) {
    try {
      const res = await fetch("/api/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Mode change failed");
      }
      this.log(`OI Mode changed to ${mode.toUpperCase()}`, "info");
    } catch (err) {
      this.log(`Mode change error: ${err.message}`, "error");
    }
  }

  async executeAction(action, extra = {}) {
    try {
      const res = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...extra }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Action failed");
      }
      this.log(`Executed action: ${action}`, "info");
    } catch (err) {
      this.log(`Action error: ${err.message}`, "error");
    }
  }

  async executeNudge(left, right, duration = 0.5) {
    if (!this.armed) {
      alert("Robot is DISARMED. Please ARM the robot before driving.");
      return;
    }
    this.log(`Nudging: Left=${left}, Right=${right} for ${duration}s`, "info");
    try {
      await fetch("/api/nudge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ left, right, duration_s: duration }),
      });
    } catch (err) {
      this.log(`Nudge error: ${err.message}`, "error");
    }
  }

  // --- Drive & Teleoperation ---

  sendDriveCommand(left, right) {
    if (!this.armed) {
      return;
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "drive", left, right }));
    } else {
      fetch("/api/drive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ left, right }),
      }).catch((e) => console.warn(e));
    }
  }

  startContinuousDrive(direction) {
    if (!this.armed) {
      alert("Robot is DISARMED. Please click 'ARM ROBOT' to enable motion controls.");
      return;
    }

    this.stopContinuousDrive();
    let left = 0;
    let right = 0;
    const spd = this.driveSpeed;

    switch (direction) {
      case "forward":
        left = spd;
        right = spd;
        this.btnFwd.classList.add("active-drive");
        break;
      case "backward":
        left = -spd;
        right = -spd;
        this.btnRev.classList.add("active-drive");
        break;
      case "left":
        left = -spd;
        right = spd;
        this.btnLeft.classList.add("active-drive");
        break;
      case "right":
        left = spd;
        right = -spd;
        this.btnRight.classList.add("active-drive");
        break;
    }

    this.sendDriveCommand(left, right);

    // Heartbeat to prevent deadman timeout while holding key/button
    this.driveHeartbeat = setInterval(() => {
      this.sendDriveCommand(left, right);
    }, 150);
  }

  stopContinuousDrive() {
    if (this.driveHeartbeat) {
      clearInterval(this.driveHeartbeat);
      this.driveHeartbeat = null;
    }

    this.btnFwd.classList.remove("active-drive");
    this.btnRev.classList.remove("active-drive");
    this.btnLeft.classList.remove("active-drive");
    this.btnRight.classList.remove("active-drive");

    this.stopDriving();
  }

  stopDriving() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "stop" }));
    } else {
      fetch("/api/stop", { method: "POST" }).catch((e) => console.warn(e));
    }
  }

  getDirectionFromEvent(e) {
    const code = e.code || "";
    const key = (e.key || "").toLowerCase();

    // Emergency Stop / Space
    if (code === "Space" || key === " " || key === "spacebar") {
      return "stop";
    }

    // Forward (W / ArrowUp / Hebrew ')
    if (code === "KeyW" || key === "w" || code === "ArrowUp" || key === "arrowup" || key === "'") {
      return "forward";
    }

    // Backward (S / ArrowDown / Hebrew ד)
    if (code === "KeyS" || key === "s" || code === "ArrowDown" || key === "arrowdown" || key === "ד") {
      return "backward";
    }

    // Left (A / ArrowLeft / Hebrew ש)
    if (code === "KeyA" || key === "a" || code === "ArrowLeft" || key === "arrowleft" || key === "ש") {
      return "left";
    }

    // Right (D / ArrowRight / Hebrew ג)
    if (code === "KeyD" || key === "d" || code === "ArrowRight" || key === "arrowright" || key === "ג") {
      return "right";
    }

    return null;
  }

  updateKeycapVisuals() {
    if (this.keyW) this.keyW.classList.toggle("pressed", this.pressedDirections.has("forward"));
    if (this.keyS) this.keyS.classList.toggle("pressed", this.pressedDirections.has("backward"));
    if (this.keyA) this.keyA.classList.toggle("pressed", this.pressedDirections.has("left"));
    if (this.keyD) this.keyD.classList.toggle("pressed", this.pressedDirections.has("right"));
  }

  // --- Event Bindings ---

  bindEvents() {
    // Header
    this.btnRefreshPorts.addEventListener("click", () => this.scanPorts());
    this.btnConnect.addEventListener("click", () => this.connectRobot());
    this.btnDisconnect.addEventListener("click", () => this.disconnectRobot());
    this.btnEstop.addEventListener("click", () => this.emergencyStop());
    this.btnToggleArm.addEventListener("click", () => this.toggleArm());
    this.btnClearLog.addEventListener("click", () => {
      this.consoleOutput.innerHTML = "";
    });

    // Speed Slider
    this.speedSlider.addEventListener("input", (e) => {
      this.driveSpeed = parseInt(e.target.value, 10);
      this.speedValue.textContent = `${this.driveSpeed} mm/s`;
      this.presetButtons.forEach((b) => b.classList.remove("active"));
    });
    this.speedSlider.addEventListener("change", () => {
      this.speedSlider.blur();
    });

    // Speed Presets
    this.presetButtons.forEach((b) => {
      b.addEventListener("click", () => {
        this.presetButtons.forEach((btn) => btn.classList.remove("active"));
        b.classList.add("active");
        this.driveSpeed = parseInt(b.getAttribute("data-speed"), 10);
        this.speedSlider.value = this.driveSpeed;
        this.speedValue.textContent = `${this.driveSpeed} mm/s`;
      });
    });

    // D-Pad and HUD Keycap Mouse & Touch (Hold to drive)
    const bindHold = (el, dir) => {
      if (!el) return;
      const startHold = (e) => {
        e.preventDefault();
        this.pressedDirections.add(dir);
        this.updateKeycapVisuals();
        this.startContinuousDrive(dir);
      };
      const endHold = () => {
        this.pressedDirections.delete(dir);
        this.updateKeycapVisuals();
        if (this.pressedDirections.size === 0) {
          this.stopContinuousDrive();
        } else {
          const remaining = Array.from(this.pressedDirections).pop();
          this.startContinuousDrive(remaining);
        }
      };

      el.addEventListener("mousedown", startHold);
      el.addEventListener("touchstart", startHold);
      el.addEventListener("mouseup", endHold);
      el.addEventListener("mouseleave", endHold);
      el.addEventListener("touchend", endHold);
    };

    // Bind hold controls to D-Pad buttons
    bindHold(this.btnFwd, "forward");
    bindHold(this.btnRev, "backward");
    bindHold(this.btnLeft, "left");
    bindHold(this.btnRight, "right");

    // Bind hold controls to WASD HUD buttons (including D button!)
    bindHold(this.keyW, "forward");
    bindHold(this.keyS, "backward");
    bindHold(this.keyA, "left");
    bindHold(this.keyD, "right");

    this.btnStop.addEventListener("click", () => {
      this.pressedDirections.clear();
      this.updateKeycapVisuals();
      this.stopContinuousDrive();
      this.stopDriving();
    });

    this.keySpace.addEventListener("click", () => {
      this.emergencyStop();
    });

    // Keyboard Teleoperation (WASD + Space + Arrow keys)
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" && ["text", "password", "search"].includes(e.target.type)) return;
      if (e.target.tagName === "TEXTAREA") return;

      const dir = this.getDirectionFromEvent(e);
      if (!dir) return;

      e.preventDefault();

      if (dir === "stop") {
        this.keySpace.classList.add("pressed");
        this.stopContinuousDrive();
        this.emergencyStop();
        return;
      }

      if (e.repeat) return; // Ignore OS auto-repeat events

      this.pressedDirections.add(dir);
      this.updateKeycapVisuals();
      this.startContinuousDrive(dir);
    });

    window.addEventListener("keyup", (e) => {
      const dir = this.getDirectionFromEvent(e);
      if (!dir) return;

      if (dir === "stop") {
        this.keySpace.classList.remove("pressed");
        return;
      }

      this.pressedDirections.delete(dir);
      this.updateKeycapVisuals();

      if (this.pressedDirections.size === 0) {
        this.stopContinuousDrive();
      } else {
        const remaining = Array.from(this.pressedDirections).pop();
        this.startContinuousDrive(remaining);
      }
    });

    // Clear stuck keys if browser window loses focus
    window.addEventListener("blur", () => {
      this.pressedDirections.clear();
      this.updateKeycapVisuals();
      this.stopContinuousDrive();
    });

    // Mode Buttons
    this.modeButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        if (mode) this.setMode(mode);
      });
    });

    // Autonomous Behavior Buttons
    if (this.behaviorButtons) {
      this.behaviorButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const beh = btn.getAttribute("data-behavior");
          if (beh) this.setBehavior(beh);
        });
      });
    }

    // Special Commands
    this.btnActBeep.addEventListener("click", () => this.executeAction("beep", { note: 72, duration: 16 }));
    this.btnActDock.addEventListener("click", () => this.executeAction("dock"));
    this.btnActClean.addEventListener("click", () => this.executeAction("clean"));
    this.btnActSpot.addEventListener("click", () => this.executeAction("spot"));

    if (this.btnResetOdom) {
      this.btnResetOdom.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/odometry/reset", { method: "POST" });
          if (res.ok) {
            this.log("Odometry counters reset to zero.", "info");
            this.statDistance.textContent = "0 mm";
            this.statAngle.textContent = "0°";
            if (this.statHeading) this.statHeading.textContent = "Heading: 0°";
          }
        } catch (err) {
          console.error("Reset odometry error:", err);
        }
      });
    }

    // Nudge Buttons
    this.nudgeButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const act = btn.getAttribute("data-action");
        const spd = this.driveSpeed;
        if (act === "nudge-fwd") this.executeNudge(spd, spd, 0.5);
        if (act === "nudge-rev") this.executeNudge(-spd, -spd, 0.5);
        if (act === "turn-45-l") this.executeNudge(-spd, spd, 0.35);
        if (act === "turn-45-r") this.executeNudge(spd, -spd, 0.35);
      });
    });

    // Sound & Speaker Transmitter Controls
    if (this.sliderBeepNote && this.valBeepNote) {
      this.sliderBeepNote.addEventListener("input", (e) => {
        this.valBeepNote.textContent = e.target.value;
      });
    }
    if (this.sliderBeepDur && this.valBeepDur) {
      this.sliderBeepDur.addEventListener("input", (e) => {
        this.valBeepDur.textContent = e.target.value;
      });
    }

    if (this.btnPlayTone && this.sliderBeepNote && this.sliderBeepDur) {
      this.btnPlayTone.addEventListener("click", () => {
        const note = parseInt(this.sliderBeepNote.value, 10);
        const duration = parseInt(this.sliderBeepDur.value, 10);
        this.executeAction("beep", { note, duration });
      });
    }

    if (this.btnPlayTune && this.selectPresetTune) {
      this.btnPlayTune.addEventListener("click", () => {
        const preset = this.selectPresetTune.value;
        this.executeAction("tune", { preset });
      });
    }

    if (this.btnTransmitMorse && this.inputMorseText) {
      this.btnTransmitMorse.addEventListener("click", () => {
        const text = this.inputMorseText.value.trim();
        if (!text) {
          alert("Please enter text to transmit as Morse code.");
          return;
        }
        this.executeAction("morse", { text, note: 76, dot_duration: 6 });
      });
    }

    if (this.btnQuickSos) {
      this.btnQuickSos.addEventListener("click", () => {
        this.executeAction("sos");
      });
    }

    if (this.btnSpeakVoice && this.inputSpeechText) {
      this.btnSpeakVoice.addEventListener("click", async () => {
        const text = this.inputSpeechText.value.trim();
        if (!text) {
          alert("Please enter text to speak.");
          return;
        }
        const mode = this.selectSpeechMode ? this.selectSpeechMode.value : "formant_interleave";
        const target = this.selectSpeechTarget ? this.selectSpeechTarget.value : "roomba";

        if (target === "browser" || target === "both") {
          this.speakHumanVoice(text);
        }

        if (target === "roomba" || target === "both") {
          try {
            this.log(`Grinding speech "${text}" (${mode})...`, "info");
            const res = await fetch("/api/sound/speech", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ text, mode }),
            });
            if (!res.ok) {
              const err = await res.json();
              throw new Error(err.detail || "Speech failed");
            }
            const data = await res.json();
            this.log(`Roomba speaker vocalized "${text}" (${data.notes_count} notes)`, "success");
          } catch (err) {
            this.log(`Speech Grinder error: ${err.message}`, "error");
          }
        }
      });
    }

    // Live Microphone Voice Grinder
    if (this.btnRecordMic) {
      this.btnRecordMic.addEventListener("click", async () => {
        if (!this.isRecordingMic) {
          try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.micMediaRecorder = new MediaRecorder(stream);
            this.micAudioChunks = [];
            this.micMediaRecorder.ondataavailable = (e) => {
              if (e.data.size > 0) this.micAudioChunks.push(e.data);
            };
            this.micMediaRecorder.onstop = async () => {
              const blob = new Blob(this.micAudioChunks, { type: this.micMediaRecorder.mimeType });
              stream.getTracks().forEach((t) => t.stop());
              await this.uploadAndGrindAudioBlob(blob);
            };
            this.micMediaRecorder.start();
            this.isRecordingMic = true;
            this.btnRecordMic.classList.add("mic-recording");
            if (this.micIcon) this.micIcon.textContent = "⏹️";
            if (this.micLabel) this.micLabel.textContent = "Stop & Grind Voice to Roomba";
            if (this.micStatusBadge) {
              this.micStatusBadge.textContent = "RECORDING...";
              this.micStatusBadge.className = "badge badge-danger";
            }
            this.log("Microphone recording started. Speak now!", "info");
          } catch (err) {
            this.log(`Microphone access error: ${err.message}`, "error");
            alert(`Microphone access error: ${err.message}`);
          }
        } else {
          this.micMediaRecorder.stop();
          this.isRecordingMic = false;
          this.btnRecordMic.classList.remove("mic-recording");
          if (this.micIcon) this.micIcon.textContent = "🎤";
          if (this.micLabel) this.micLabel.textContent = "Record Voice & Grind to Roomba";
          if (this.micStatusBadge) {
            this.micStatusBadge.textContent = "GRINDING...";
            this.micStatusBadge.className = "badge badge-warn";
          }
          this.log("Recording stopped. Grinding audio for Roomba speaker...", "info");
        }
      });
    }

    // Audio File Grinder (.wav)
    if (this.btnGrindFile && this.inputAudioFile) {
      this.btnGrindFile.addEventListener("click", async () => {
        if (!this.inputAudioFile.files || this.inputAudioFile.files.length === 0) {
          alert("Please select a .wav audio file first.");
          return;
        }
        const file = this.inputAudioFile.files[0];
        try {
          this.log(`Uploading & grinding "${file.name}"...`, "info");
          const formData = new FormData();
          formData.append("file", file);
          const res = await fetch("/api/sound/grind_audio", {
            method: "POST",
            body: formData,
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "File grinding failed");
          }
          const data = await res.json();
          this.log(`Audio file ground into ${data.notes_count} Roomba notes (${data.duration_s?.toFixed(2)}s) and playing!`, "success");
        } catch (err) {
          this.log(`File grinding error: ${err.message}`, "error");
        }
      });
    }

    // Interactive Human Soundboard Chips
    const soundChips = document.querySelectorAll(".btn-sound-chip");
    soundChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        const sound = chip.getAttribute("data-sound");
        if (sound) {
          this.log(`Triggered vocal sound: "${sound}"`, "info");
          this.executeAction("human", { sound });
        }
      });
    });

    if (this.btnPlayRtttl && this.inputRtttl) {
      this.btnPlayRtttl.addEventListener("click", () => {
        const rtttl = this.inputRtttl.value.trim();
        if (!rtttl) {
          alert("Please enter an RTTTL ringtone string.");
          return;
        }
        this.executeAction("rtttl", { rtttl });
      });
    }
  }

  async setBehavior(behavior) {
    try {
      const res = await fetch("/api/behaviors/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ behavior }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Behavior switch failed");
      }
      this.log(`Switched behavior to: ${behavior.toUpperCase()}`, "info");
    } catch (err) {
      this.log(`Behavior error: ${err.message}`, "error");
    }
  }
}

// Start application when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  window.cockpit = new RoombaCockpit();
});
